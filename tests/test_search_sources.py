"""Pruebas sin red de los proveedores Wikimedia Commons y Blender Studio."""
import unittest

from app.core import DownloadType
from app.core.search import (
    LanguageFilter,
    SearchError,
    SearchQuery,
    SearchResult,
    merge_results,
    search_providers,
)
from app.core.search.blender import BlenderOpenMoviesProvider, clean_title, title_key
from app.core.search.commons import (
    WikimediaCommonsSearchProvider,
    clean_url,
    file_title_to_name,
    page_to_results,
    resolution_label,
)

SPANISH_SUBS = {"title": "Category:Files with closed captioning in Spanish"}
ENGLISH_SUBS = {"title": "Category:Files with closed captioning in English"}


def video_page(title, width, height, size, duration, license_="CC BY 3.0", date="2008", derivatives=(),
               categories=(), pageid=1, index=1):
    return {
        "pageid": pageid, "index": index, "title": title, "categories": list(categories),
        "videoinfo": [{
            "url": f"https://upload.wikimedia.org/x/{title[5:]}?utm_source=commons.wikimedia.org",
            "size": size, "width": width, "height": height, "duration": duration, "mime": "video/webm",
            "extmetadata": {"LicenseShortName": {"value": license_}, "DateTimeOriginal": {"value": date}},
            "derivatives": [
                {"transcodekey": key, "width": w, "height": h, "bandwidth": bw, "src": f"https://upload.wikimedia.org/t/{key}"}
                for key, w, h, bw in derivatives
            ],
        }],
    }


BBB = video_page("File:Big Buck Bunny 4K.webm", 4000, 2250, 2965000000, 634.0, date="2008",
                 derivatives=[("1080p.vp9.webm", 1920, 1080, 3788064), ("480p.vp9.webm", 854, 480, 1218440),
                              ("240p.vp9.webm", 426, 240, 383864)])


class FakeClient:
    """Sustituye a CommonsClient: devuelve páginas según el generador pedido."""

    def __init__(self, search_pages=(), categories=None):
        self.search_pages = list(search_pages)
        self.categories = categories or {}
        self.calls = []

    def video_pages(self, **generator):
        self.calls.append(generator)
        if generator.get("generator") == "categorymembers":
            return list(self.categories.get(generator["gcmtitle"], []))
        return list(self.search_pages)


class CommonsHelpersTests(unittest.TestCase):
    def test_resolution_label_uses_width(self):
        self.assertEqual(resolution_label(1920, 818), "1080p")      # panorámica
        self.assertEqual(resolution_label(4000, 2250), "4K")
        self.assertEqual(resolution_label(854, 480), "480p")
        self.assertEqual(resolution_label(640, 360), "360p")

    def test_url_and_title_helpers(self):
        self.assertEqual(clean_url("https://u.org/a.webm?utm_source=x&utm_campaign=api"), "https://u.org/a.webm")
        self.assertEqual(file_title_to_name("File:Nosferatu_(1922).webm"), "Nosferatu (1922)")

    def test_one_row_per_quality(self):
        rows = page_to_results(BBB, "Wikimedia Commons", rank=0)
        self.assertEqual([r.quality for r in rows],
                         ["4K · WebM · original · 11 min", "1080p · WebM · 11 min", "480p · WebM · 11 min"])
        self.assertEqual(rows[0].size_bytes, 2965000000)
        self.assertEqual(rows[1].size_bytes, int(3788064 * 634 / 8))   # estimado: bitrate × duración
        self.assertEqual(rows[0].download_url, "https://upload.wikimedia.org/x/Big Buck Bunny 4K.webm")
        self.assertEqual([r.filename for r in rows], ["Big Buck Bunny 4K", "Big Buck Bunny 4K (1080p)",
                                                      "Big Buck Bunny 4K (480p)"])
        self.assertTrue(all(r.download_type is DownloadType.WEB_VIDEO for r in rows))
        self.assertEqual({(r.year, r.license) for r in rows}, {(2008, "CC BY 3.0")})

    def test_downloads_identify_the_app(self):
        # upload.wikimedia.org responde 403 a un User-Agent de navegador genérico.
        for row in page_to_results(BBB, "x", 0):
            self.assertTrue(row.headers["User-Agent"].startswith("MediaDownloader/"))

    def test_transcodes_bigger_than_original_are_skipped(self):
        page = video_page("File:Small.webm", 854, 480, 50_000_000, 300.0,
                          derivatives=[("1080p.vp9.webm", 1920, 1080, 3_000_000), ("480p.vp9.webm", 854, 480, 900_000)])
        self.assertEqual(len(page_to_results(page, "x", 0)), 1)

    def test_subtitles_from_categories(self):
        page = video_page("File:Film.webm", 1920, 1080, 1, 600.0, categories=[ENGLISH_SUBS, SPANISH_SUBS])
        row = page_to_results(page, "x", 0)[0]
        self.assertEqual(row.subtitle_languages, ("Español", "Inglés"))
        self.assertTrue(row.has_language("Español"))
        self.assertEqual(row.language_label, "subt.: Español, Inglés")


class CommonsProviderTests(unittest.TestCase):
    def test_search_filters_short_clips_and_uses_language_category(self):
        short = video_page("File:Clip.webm", 1920, 1080, 1_000_000, 45.0, pageid=2, index=2)
        client = FakeClient(search_pages=[BBB, short])
        provider = WikimediaCommonsSearchProvider(client)
        results = provider.search(SearchQuery('nosferatu "x" incategory:y', LanguageFilter.SPANISH, limit=10))
        self.assertTrue(all(r.title == "Big Buck Bunny 4K" for r in results))    # sin el clip de 45 s
        search = client.calls[0]["gsrsearch"]
        self.assertTrue(search.startswith("filetype:video nosferatu"))
        self.assertNotIn("incategory:y", search)                                  # operadores del usuario neutralizados
        self.assertIn('incategory:"Files with closed captioning in Spanish"', search)
        self.assertEqual(client.calls[0]["gsrlimit"], 10)

    def test_empty_text(self):
        with self.assertRaises(SearchError):
            WikimediaCommonsSearchProvider(FakeClient()).search(SearchQuery("  "))


class BlenderProviderTests(unittest.TestCase):
    def setUp(self):
        sintel_small = video_page("File:Sintel movie - Blender Fondation.ogv", 2048, 872, 238_000_000, 888.0,
                                  categories=[SPANISH_SUBS], pageid=10)
        sintel_4k = video_page("File:Sintel movie 4K.webm", 4096, 1744, 3_498_000_000, 888.0,
                               categories=[SPANISH_SUBS, ENGLISH_SUBS], pageid=11,
                               derivatives=[("1080p.vp9.webm", 1920, 818, 2_280_000)])
        sprite = video_page("File:Sprite Fright - Blender Open Movie-full movie.webm", 2048, 858, 159_000_000,
                            629.0, license_="CC BY 4.0", date="2021", pageid=12)
        wing = video_page("File:WING IT! - Blender Open Movie-full movie.webm", 1920, 1080, 36_000_000, 237.0,
                          license_="CC BY 4.0", date="2023-06-01", pageid=13, categories=[ENGLISH_SUBS])
        self.client = FakeClient(categories={
            "Category:Blender movies": [BBB, sprite, wing],
            "Category:Sintel (complete video)": [sintel_small, sintel_4k],
        })
        self.provider = BlenderOpenMoviesProvider(self.client)

    def test_title_cleaning(self):
        self.assertEqual(clean_title("Sprite Fright - Blender Open Movie-full movie"), "Sprite Fright")
        self.assertEqual(clean_title("Tears of Steel in 4k - Official Blender Foundation release"), "Tears of Steel")
        self.assertEqual(clean_title("Elephants Dream (2006) 1080p24"), "Elephants Dream")
        self.assertEqual(title_key("WING IT!"), "wing it")

    def test_whole_catalog_sorted_by_year_without_duplicates(self):
        results = self.provider.search(SearchQuery("blender"))
        films = list(dict.fromkeys((r.title, r.year) for r in results))
        self.assertEqual([f[0] for f in films], ["Big Buck Bunny", "Sintel", "Sprite Fright", "WING IT!"])
        self.assertEqual([f[1] for f in films], [2008, 2010, 2021, 2023])
        sintel = [r for r in results if r.title == "Sintel"]
        # El duplicado de menor resolución se descarta; se añade la copia de blender.org.
        self.assertEqual([r.quality.split(" · ")[0] for r in sintel], ["4K", "1080p", "1080p"])
        self.assertTrue(sintel[-1].download_url.startswith("https://download.blender.org/"))
        self.assertTrue(all(r.provider == "Blender Studio" for r in results))

    def test_title_search_and_language_filter(self):
        self.assertEqual({r.title for r in self.provider.search(SearchQuery("sprite"))}, {"Sprite Fright"})
        self.assertEqual(self.provider.search(SearchQuery("nosferatu")), [])
        spanish = self.provider.search(SearchQuery("blender", LanguageFilter.SPANISH))
        self.assertEqual({r.title for r in spanish}, {"Sintel"})          # solo tiene subtítulos en español

    def test_empty_text(self):
        with self.assertRaises(SearchError):
            self.provider.search(SearchQuery(" "))


class MultiSourceTests(unittest.TestCase):
    def test_providers_registered_in_order(self):
        self.assertEqual(search_providers(), ["Internet Archive", "Wikimedia Commons", "Blender Studio"])

    def test_merge_interleaves_sources_by_relevance(self):
        def results(source, n):
            return [SearchResult(provider=source, id=f"{source}{i}", title=f"{source}{i}", page_url="",
                                 download_url=f"https://example.org/{source}{i}", download_type=DownloadType.WEB_VIDEO,
                                 rank=i) for i in range(n)]

        merged = merge_results([results("A", 2), results("B", 3), results("C", 0)])
        self.assertEqual([r.id for r in merged], ["A0", "B0", "A1", "B1", "B2"])

    def test_same_file_from_two_sources_keeps_the_specific_one(self):
        def result(source, title):
            return SearchResult(provider=source, id=title, title=title, page_url="",
                                download_url="https://upload.wikimedia.org/sintel.webm",
                                download_type=DownloadType.WEB_VIDEO)

        merged = merge_results([[result("Wikimedia Commons", "Sintel movie 4K")], [result("Blender Studio", "Sintel")]])
        self.assertEqual([(r.provider, r.title) for r in merged], [("Blender Studio", "Sintel")])


if __name__ == "__main__":
    unittest.main()
