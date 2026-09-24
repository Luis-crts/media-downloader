"""Pruebas sin red del proveedor de torrents."""
import shutil
import tempfile
import unittest
from pathlib import Path

from app.core import DownloadRequest, DownloadType, InvalidURLError, get_downloader
from app.core.generic import GenericDownloader
from app.core.torrent import TorrentDownloader, is_torrent_source, libtorrent_version
from app.download_queue import QueueItem, load_queue, save_queue

SINTEL = ("magnet:?xt=urn:btih:08ada5a7a6183aae1e09d831df6748d566095a10&dn=Sintel"
          "&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce")


class SourceDetectionTests(unittest.TestCase):
    def test_torrent_sources(self):
        for source in (
            SINTEL,
            "MAGNET:?dn=x&xt=urn:btih:08ada5a7a6183aae1e09d831df6748d566095a10",   # xt no primero
            "magnet:?xt=urn:btmh:1220caf1e1c30e81cb361b9ee167c4aa64228a7fa4fa9f6105232b28ad099f3a302e",  # v2
            "https://example.org/files/debian-12.iso.torrent",
            r"C:\Users\yo\Descargas\sintel.torrent",
        ):
            self.assertTrue(is_torrent_source(source), source)

    def test_other_sources(self):
        for source in (
            "https://youtu.be/dQw4w9WgXcQ",
            "https://cdn.example/master.m3u8",
            "magnet:?dn=sin-hash",
            "https://example.org/torrent-news/article",
        ):
            self.assertFalse(is_torrent_source(source), source)


class RoutingTests(unittest.TestCase):
    def test_magnet_goes_to_torrent_provider(self):
        self.assertIsInstance(get_downloader(SINTEL, DownloadType.TORRENT), TorrentDownloader)

    def test_torrent_type_does_not_steal_http_video(self):
        with self.assertRaises(InvalidURLError):
            get_downloader("https://cdn.example/master.m3u8", DownloadType.TORRENT)
        self.assertIsInstance(get_downloader("https://cdn.example/master.m3u8", DownloadType.WEB_VIDEO),
                              GenericDownloader)

    def test_other_types_reject_magnets(self):
        with self.assertRaises(InvalidURLError):
            get_downloader(SINTEL, DownloadType.MP4)


@unittest.skipUnless(libtorrent_version(), "requiere libtorrent")
class ParamsTests(unittest.TestCase):
    def setUp(self):
        import libtorrent
        self.lt = libtorrent
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_magnet_is_parsed(self):
        params = TorrentDownloader._params(self.lt, SINTEL)
        self.assertEqual(str(params.info_hashes.v1), "08ada5a7a6183aae1e09d831df6748d566095a10")

    def test_invalid_torrent_file(self):
        bad = self.tmp / "roto.torrent"
        bad.write_bytes(b"esto no es un torrent")
        with self.assertRaises(InvalidURLError):
            TorrentDownloader._params(self.lt, str(bad))

    def test_missing_torrent_file(self):
        with self.assertRaises(InvalidURLError):
            TorrentDownloader._params(self.lt, str(self.tmp / "no-existe.torrent"))

    def test_invalid_magnet(self):
        with self.assertRaises(InvalidURLError):
            TorrentDownloader._params(self.lt, "magnet:?xt=urn:btih:ZZZ")


class QueueTests(unittest.TestCase):
    def test_torrent_items_survive_restart(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            item = QueueItem(request=DownloadRequest(SINTEL, Path("out"), DownloadType.TORRENT), source="Torrent")
            save_queue(tmp / "queue.json", [item])
            loaded = load_queue(tmp / "queue.json")
            self.assertEqual(loaded[0].request.download_type, DownloadType.TORRENT)
            self.assertEqual(loaded[0].request.url, SINTEL)
            self.assertEqual(loaded[0].summary, "Película / Torrent · Torrent")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
