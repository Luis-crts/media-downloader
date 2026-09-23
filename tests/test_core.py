"""Pruebas sin red del núcleo: python -m unittest discover -s tests"""
import unittest
from pathlib import Path

from app.core import (
    AccessDeniedError,
    DownloadRequest,
    DownloadType,
    DRMProtectedError,
    InvalidURLError,
    NetworkError,
    ResolvedMedia,
    get_downloader,
)
from app.core.extractor import (
    find_iframes,
    find_media_urls,
    is_direct_media,
    name_from_url,
    page_title,
    with_referer,
)
from app.core.generic import GenericDownloader
from app.core.ytdlp_backend import YtDlpDownloader, format_options, translate_error

PAGE = "https://peliculas.example/ver/mi-pelicula"


class ExtractorTests(unittest.TestCase):
    def test_direct_media_detection(self):
        self.assertTrue(is_direct_media("https://cdn.example/hls/master.m3u8?token=abc"))
        self.assertTrue(is_direct_media("https://cdn.example/files/Movie.2024.mp4"))
        self.assertFalse(is_direct_media("https://example.com/watch/123"))
        self.assertFalse(is_direct_media("https://example.com/v.mp4/page"))

    def test_name_from_url_skips_generic_names(self):
        self.assertIsNone(name_from_url("https://cdn.example/hls/master.m3u8"))
        self.assertEqual(name_from_url("https://cdn.example/Big_Buck_Bunny.mp4"), "Big Buck Bunny")

    def test_finds_quoted_and_escaped_urls_prioritizing_m3u8(self):
        html = """
            <script>var cfg = {"poster":"https:\\/\\/cdn.example\\/p.jpg",
                               "sources":[{"file":"https:\\/\\/cdn.example\\/v\\/480.mp4"}]};</script>
            <script>player.load('/hls/master.m3u8?t=1&amp;e=2');</script>
        """
        urls = find_media_urls(html, PAGE)
        self.assertEqual(urls[0], "https://peliculas.example/hls/master.m3u8?t=1&e=2")
        self.assertIn("https://cdn.example/v/480.mp4", urls)
        self.assertNotIn("https://cdn.example/p.jpg", urls)

    def test_video_source_tag_without_extension(self):
        html = '<video controls><source src="/stream?id=42" type="application/x-mpegURL"></video>'
        self.assertEqual(find_media_urls(html, PAGE), ["https://peliculas.example/stream?id=42"])

    def test_jwplayer_key_without_extension(self):
        html = 'jwplayer("p").setup({file: "https://edge.example/play/abc123", image: "x.jpg"});'
        self.assertEqual(find_media_urls(html, PAGE), ["https://edge.example/play/abc123"])

    def test_unpacks_dean_edwards_packed_js(self):
        # Equivale a: player.src("https://cdn.example/secret/index.m3u8")
        packed = (
            "eval(function(p,a,c,k,e,d){e=function(c){return c.toString(36)};"
            "if(!''.replace(/^/,String)){while(c--){d[c.toString(a)]=k[c]||c.toString(a)}"
            "k=[function(e){return d[e]}];e=function(){return'\\\\w+'};c=1};"
            "while(c--){if(k[c]){p=p.replace(new RegExp('\\\\b'+e(c)+'\\\\b','g'),k[c])}}return p}"
            "('0.1(\"2://3.4/5/6.7\")',8,8,'player|src|https|cdn|example|secret|index|m3u8'"
            ".split('|'),0,{}))"
        )
        self.assertEqual(find_media_urls(packed, PAGE), ["https://cdn.example/secret/index.m3u8"])

    def test_iframes_skip_ads(self):
        html = (
            '<iframe src="//player.example/e/xyz"></iframe>'
            '<iframe data-src="https://googleads.g.doubleclick.net/x"></iframe>'
        )
        self.assertEqual(find_iframes(html, PAGE), ["https://player.example/e/xyz"])

    def test_page_title_prefers_og_title(self):
        html = '<title>Ver online | Sitio</title><meta property="og:title" content="Mi Película (2024)">'
        self.assertEqual(page_title(html), "Mi Película (2024)")

    def test_with_referer_keeps_user_values(self):
        headers = with_referer({"Referer": "https://mio.example/"}, PAGE)
        self.assertEqual(headers["Referer"], "https://mio.example/")
        self.assertEqual(headers["Origin"], "https://peliculas.example")


class RoutingTests(unittest.TestCase):
    def test_youtube_urls_use_youtube_provider(self):
        self.assertEqual(get_downloader("https://youtu.be/dQw4w9WgXcQ", DownloadType.MP3).name, "YouTube")

    def test_web_video_type_always_uses_generic(self):
        downloader = get_downloader("https://youtu.be/dQw4w9WgXcQ", DownloadType.WEB_VIDEO)
        self.assertIsInstance(downloader, GenericDownloader)

    def test_other_sites_fall_back_to_generic(self):
        downloader = get_downloader("https://vimeo.com/76979871", DownloadType.MP4)
        self.assertIsInstance(downloader, GenericDownloader)

    def test_invalid_urls_are_rejected(self):
        for url in ("", "hola", "ftp://example.com/x.mp4"):
            with self.assertRaises(InvalidURLError):
                get_downloader(url, DownloadType.WEB_VIDEO)


class BackendTests(unittest.TestCase):
    def test_quality_limits_format_sort(self):
        self.assertEqual(format_options(DownloadType.WEB_VIDEO, 720)["format_sort"][0], "res:720")
        self.assertEqual(format_options(DownloadType.MP4)["format_sort"][0], "res")

    def test_error_translation(self):
        cases = {
            "ERROR: [generic] x: This video is DRM protected": DRMProtectedError,
            "ERROR: unable to download video data: HTTP Error 403: Forbidden": AccessDeniedError,
            "ERROR: <urlopen error [Errno 11001] getaddrinfo failed>": NetworkError,
            "ERROR: Unsupported URL: https://example.com": InvalidURLError,
        }
        for message, expected in cases.items():
            self.assertIsInstance(translate_error(message), expected, message)

    def test_output_template_uses_custom_name_safely(self):
        request = DownloadRequest(
            url="https://cdn.example/master.m3u8", output_dir=Path("out"),
            download_type=DownloadType.WEB_VIDEO, filename='Mi Peli: 100% "HD"',
        )
        template = YtDlpDownloader._output_template(
            GenericDownloader(), request, ResolvedMedia(url=request.url), is_playlist=False
        )
        self.assertNotIn(":", template.name)
        self.assertIn("100%%", template.name)   # % escapado para outtmpl
        self.assertTrue(template.name.endswith(".%(ext)s"))


if __name__ == "__main__":
    unittest.main()
