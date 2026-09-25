"""Pruebas sin red del módulo de búsqueda (app/core/search)."""
import shutil
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from app.core import DownloadRequest, DownloadType
from app.core.search import (
    BaseSearchProvider,
    LanguageFilter,
    SearchError,
    SearchQuery,
    SearchResult,
    SortOrder,
    filter_by_language,
    get_search_provider,
    normalize_language,
    search_providers,
    sort_results,
)
from app.core.search.archive_org import (
    LEGAL_SCOPE,
    ArchiveOrgSearchProvider,
    direct_web_seeds,
    escape_query,
    license_label,
    pick_files,
)
from app.core.torrent import TorrentDownloader
from app.download_queue import QueueItem, load_queue, save_queue

DOC = {
    "identifier": "ScarletStreet", "title": "Scarlet Street", "year": "1945", "language": "eng",
    "downloads": 381245, "item_size": 1500000000, "licenseurl": "http://creativecommons.org/licenses/publicdomain/",
}
META = {
    "server": "ia800202.us.archive.org", "d1": "ia600202.us.archive.org", "dir": "/16/items/ScarletStreet",
    "metadata": {"language": "English"},
    "files": [
        {"name": "ScarletStreet_archive.torrent", "format": "Archive BitTorrent", "size": "40351"},
        {"name": "Scarlet_Street.asr.srt", "format": "SubRip", "size": "67304"},
        {"name": "Scarlet_Street.asr.vtt", "format": "Web Video Text Tracks", "size": "68000"},
        {"name": "Scarlet_Street.mp4", "format": "h.264", "size": "633398173", "height": "480", "source": "derivative"},
        {"name": "Scarlet_Street.ogv", "format": "Ogg Video", "size": "413843189", "height": "304", "source": "derivative"},
        {"name": "Scarlet_Street_512kb.mp4", "format": "512Kb MPEG4", "size": "441562845", "height": "240", "source": "derivative"},
        {"name": "Scarlet_Street.mpeg", "format": "MPEG2", "size": "4000000000", "height": "480", "source": "original"},
        {"name": "__ia_thumb.jpg", "format": "Item Tile", "size": "6550"},
    ],
}


class RegistryTests(unittest.TestCase):
    def test_archive_is_registered_as_default(self):
        self.assertEqual(search_providers()[0], "Internet Archive")
        self.assertIsInstance(get_search_provider(), ArchiveOrgSearchProvider)
        self.assertIsInstance(get_search_provider("Internet Archive"), BaseSearchProvider)

    def test_unknown_provider(self):
        with self.assertRaises(SearchError):
            get_search_provider("No existe")


class HelpersTests(unittest.TestCase):
    def test_languages(self):
        for raw, expected in (("spa", "Español"), ("Spanish", "Español"), ("español", "Español"),
                              ("eng", "Inglés"), ("English", "Inglés"), ("english-handwritten", "Inglés"),
                              ("tur", "Tur"), ("None", None), ("", None)):
            self.assertEqual(normalize_language(raw), expected, raw)

    def test_query_escaping(self):
        self.assertEqual(escape_query('star wars: "el"'), 'star wars\\: \\"el\\"')
        self.assertEqual(escape_query("AC/DC (live)"), "AC\\/DC \\(live\\)")

    def test_license_labels(self):
        self.assertEqual(license_label("http://creativecommons.org/licenses/by-nc-nd/3.0/"), "CC BY-NC-ND 3.0")
        self.assertEqual(license_label("http://creativecommons.org/publicdomain/zero/1.0/"), "CC0 (dominio público)")
        self.assertEqual(license_label("https://creativecommons.org/publicdomain/mark/1.0/"), "Dominio público")
        self.assertEqual(license_label(""), "")

    def test_legal_scope_requires_license_or_curated_collection(self):
        self.assertIn("licenseurl:*creativecommons.org*", LEGAL_SCOPE)
        self.assertIn("collection:feature_films AND", LEGAL_SCOPE)
        self.assertIn("silent_films", LEGAL_SCOPE)


class PickFilesTests(unittest.TestCase):
    def test_prefers_playable_mp4_over_huge_mpeg2(self):
        videos, subs = pick_files(META["files"])
        self.assertEqual([f["name"] for f in videos], ["Scarlet_Street.mp4"])
        self.assertEqual([f["name"] for f in subs], ["Scarlet_Street.asr.srt"])   # sin el .vtt duplicado

    def test_explicit_parts_are_kept_together(self):
        files = [{"name": f"nosferatu-{i}of3_512kb.mp4", "format": "512Kb MPEG4", "size": "10", "source": "derivative"}
                 for i in (1, 2, 3)]
        videos, _ = pick_files(files)
        self.assertEqual(len(videos), 3)

    def test_resolutions_are_not_parts_and_name_gives_height(self):
        files = [{"name": f"Night_{r}.mp4", "format": "h.264", "size": "10", "source": "original"}
                 for r in ("480p", "720p", "1080p")]
        videos, _ = pick_files(files)
        self.assertEqual([f["name"] for f in videos], ["Night_1080p.mp4"])

    def test_no_video(self):
        self.assertEqual(pick_files([{"name": "a.jpg", "format": "JPEG"}]), ([], []))


class BuildResultTests(unittest.TestCase):
    def test_full_result_from_search_and_metadata(self):
        r = ArchiveOrgSearchProvider.build_result(DOC, META, rank=3)
        self.assertEqual((r.title, r.year, r.rank), ("Scarlet Street", 1945, 3))
        self.assertEqual(r.quality, "480p · h.264")
        self.assertEqual(r.languages, ("Inglés",))
        self.assertEqual(r.size_bytes, 633398173 + 67304)          # lo que se descarga, no el ítem
        self.assertEqual(r.popularity, 381245)
        self.assertEqual(r.license, "Dominio público")
        self.assertIs(r.download_type, DownloadType.TORRENT)
        self.assertEqual(r.download_url, "https://archive.org/download/ScarletStreet/ScarletStreet_archive.torrent")
        self.assertEqual(r.files, ("Scarlet_Street.mp4", "Scarlet_Street.asr.srt"))
        self.assertEqual(r.web_seeds, ("https://ia800202.us.archive.org/16/items/",
                                       "https://ia600202.us.archive.org/16/items/"))
        self.assertEqual(r.page_url, "https://archive.org/details/ScarletStreet")

    def test_languages_from_search_and_metadata_are_merged(self):
        meta = dict(META, metadata={"language": ["spa", "English"]})
        self.assertEqual(ArchiveOrgSearchProvider.build_result(DOC, meta, 0).languages, ("Inglés", "Español"))

    def test_without_torrent_it_is_a_direct_download(self):
        meta = dict(META, files=[f for f in META["files"] if f["format"] != "Archive BitTorrent"])
        r = ArchiveOrgSearchProvider.build_result(DOC, meta, 0)
        self.assertIs(r.download_type, DownloadType.WEB_VIDEO)
        self.assertEqual(r.download_url, "https://archive.org/download/ScarletStreet/Scarlet_Street.mp4")
        self.assertEqual((r.files, r.web_seeds), ((), ()))

    def test_item_without_video_is_skipped(self):
        meta = dict(META, files=[{"name": "a.jpg", "format": "JPEG"}])
        self.assertIsNone(ArchiveOrgSearchProvider.build_result(DOC, meta, 0))

    def test_without_metadata_downloads_whole_torrent(self):
        doc = dict(DOC, licenseurl=None)
        r = ArchiveOrgSearchProvider.build_result(doc, None, 0)
        self.assertIs(r.download_type, DownloadType.TORRENT)
        self.assertEqual((r.files, r.size_bytes, r.quality), ((), 1500000000, "—"))
        self.assertIn("colección curada", r.license)

    def test_direct_web_seeds_without_metadata(self):
        self.assertEqual(direct_web_seeds(None), ())


class SearchCallTests(unittest.TestCase):
    def setUp(self):
        self.provider = ArchiveOrgSearchProvider()

    def test_query_uses_legal_scope_and_language(self):
        calls = []

        def fake_get(url):
            calls.append(url)
            return {"response": {"docs": [DOC]}} if "advancedsearch" in url else META

        with mock.patch.object(self.provider, "_get_json", side_effect=fake_get):
            results = self.provider.search(SearchQuery("scarlet", LanguageFilter.SPANISH, limit=5))
        self.assertEqual(len(results), 1)
        search_url = calls[0]
        self.assertIn("collection%3Afeature_films", search_url)
        self.assertIn("language%3A%28spa", search_url)
        self.assertIn("rows=5", search_url)
        self.assertTrue(any("metadata/ScarletStreet" in c for c in calls))

    def test_empty_text(self):
        with self.assertRaises(SearchError):
            self.provider.search(SearchQuery("   "))

    def test_network_error(self):
        with mock.patch.object(self.provider, "_get_json", side_effect=urllib.error.URLError("sin red")):
            with self.assertRaises(SearchError) as ctx:
                self.provider.search(SearchQuery("nosferatu"))
        self.assertIn("Internet Archive", str(ctx.exception))


class SortFilterTests(unittest.TestCase):
    def setUp(self):
        base = dict(provider="p", page_url="", download_url="", download_type=DownloadType.TORRENT)
        self.a = SearchResult(id="a", title="A", size_bytes=900, popularity=5, languages=("Español",), rank=0, **base)
        self.b = SearchResult(id="b", title="B", size_bytes=100, popularity=50, languages=("Inglés",), rank=1, **base)
        self.c = SearchResult(id="c", title="C", size_bytes=None, popularity=None, rank=2, **base)

    def ids(self, results):
        return [r.id for r in results]

    def test_orders(self):
        items = [self.c, self.a, self.b]
        self.assertEqual(self.ids(sort_results(items, SortOrder.RELEVANCE)), ["a", "b", "c"])
        self.assertEqual(self.ids(sort_results(items, SortOrder.SIZE_ASC)), ["b", "a", "c"])
        self.assertEqual(self.ids(sort_results(items, SortOrder.SIZE_DESC)), ["a", "b", "c"])   # sin tamaño, al final
        self.assertEqual(self.ids(sort_results(items, SortOrder.POPULARITY)), ["b", "a", "c"])

    def test_language_filter(self):
        items = [self.a, self.b, self.c]
        self.assertEqual(self.ids(filter_by_language(items, LanguageFilter.SPANISH)), ["a"])
        self.assertEqual(self.ids(filter_by_language(items, LanguageFilter.ALL)), ["a", "b", "c"])


class TorrentSelectionTests(unittest.TestCase):
    class Storage:
        paths = ["ScarletStreet\\Scarlet_Street.mp4", "ScarletStreet\\.____padding_file\\1",
                 "ScarletStreet\\Scarlet_Street.ogv", "ScarletStreet\\Scarlet_Street.asr.srt"]

        def num_files(self):
            return len(self.paths)

        def file_path(self, i):
            return self.paths[i]

    def test_only_requested_files_are_selected(self):
        indices = TorrentDownloader._wanted_indices(self.Storage(), ("Scarlet_Street.mp4", "Scarlet_Street.asr.srt"))
        self.assertEqual(indices, [0, 3])

    def test_selection_and_web_seeds_survive_restart(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            request = DownloadRequest("https://archive.org/download/x/x_archive.torrent", Path("out"),
                                      DownloadType.TORRENT, torrent_files=("a.mp4",),
                                      web_seeds=("https://ia800202.us.archive.org/16/items/",))
            save_queue(tmp / "q.json", [QueueItem(request=request)])
            self.assertEqual(load_queue(tmp / "q.json")[0].request, request)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
