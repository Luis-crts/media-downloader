"""Pruebas del modelo de la cola de descargas (sin interfaz ni red)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app.core import DownloadRequest, DownloadType
from app.download_queue import DownloadQueue, ItemStatus, QueueItem, load_queue, save_queue


def request(url: str, download_type: DownloadType = DownloadType.MP3, **kwargs) -> DownloadRequest:
    return DownloadRequest(url=url, output_dir=Path("out"), download_type=download_type, **kwargs)


class DownloadQueueTests(unittest.TestCase):
    def setUp(self):
        self.queue = DownloadQueue()
        self.a = self.queue.add(request("https://youtu.be/a"), source="YouTube")
        self.b = self.queue.add(request("https://youtu.be/b"))
        self.c = self.queue.add(request("https://cdn.example/c.m3u8", DownloadType.WEB_VIDEO, quality=720))

    def test_fifo_order_and_single_active(self):
        self.assertIs(self.queue.next_pending(), self.a)
        self.a.status = ItemStatus.ACTIVE
        self.assertIs(self.queue.active(), self.a)
        self.assertIs(self.queue.next_pending(), self.b)
        self.a.status = ItemStatus.DONE
        self.assertIsNone(self.queue.active())
        self.assertEqual(self.queue.pending_count(), 2)

    def test_paused_item_is_still_the_active_one(self):
        self.a.status = ItemStatus.PAUSED
        self.assertIs(self.queue.active(), self.a)

    def test_duplicates_only_while_not_finished(self):
        self.assertIs(self.queue.find_duplicate(request("https://youtu.be/a")), self.a)
        # Mismo enlace con otro tipo no es duplicado.
        self.assertIsNone(self.queue.find_duplicate(request("https://youtu.be/a", DownloadType.MP4)))
        self.a.status = ItemStatus.DONE
        self.assertIsNone(self.queue.find_duplicate(request("https://youtu.be/a")))

    def test_cannot_remove_running_item(self):
        self.a.status = ItemStatus.ACTIVE
        self.assertFalse(self.queue.remove(self.a.id))
        self.assertTrue(self.queue.remove(self.b.id))
        self.assertEqual([i.id for i in self.queue.items], [self.a.id, self.c.id])

    def test_clear_finished_and_pending(self):
        self.a.status = ItemStatus.DONE
        self.b.status = ItemStatus.ACTIVE
        self.assertEqual(self.queue.clear_finished(), [self.a.id])
        self.assertEqual(self.queue.clear_pending(), [self.c.id])
        self.assertEqual([i.id for i in self.queue.items], [self.b.id])

    def test_counts_and_summary(self):
        self.a.status = ItemStatus.FAILED
        counts = self.queue.counts()
        self.assertEqual(counts[ItemStatus.FAILED], 1)
        self.assertEqual(counts[ItemStatus.PENDING], 2)
        self.assertEqual(self.a.summary, "Audio MP3 · YouTube")
        self.assertEqual(self.c.summary, "Películas / Video Web · ≤720p")
        self.assertEqual(self.b.display_title, "https://youtu.be/b")
        self.b.title = "Título real"
        self.assertEqual(self.b.display_title, "Título real")


class ReorderTests(unittest.TestCase):
    def setUp(self):
        self.queue = DownloadQueue()
        self.active = self.queue.add(request("https://ejemplo.com/pelicula"))
        self.active.status = ItemStatus.ACTIVE
        self.done = self.queue.add(request("https://ejemplo.com/hecha"))
        self.done.status = ItemStatus.DONE
        self.movie = self.queue.add(request("https://ejemplo.com/otra-pelicula"))
        self.song = self.queue.add(request("https://youtu.be/cancion"))

    def order(self):
        return [i.id for i in self.queue.items]

    def test_move_up_gives_priority_without_touching_active(self):
        self.assertTrue(self.queue.move(self.song.id, -1))
        self.assertIs(self.queue.next_pending(), self.song)
        self.assertEqual(self.order(), [self.active.id, self.done.id, self.song.id, self.movie.id])
        self.assertIs(self.queue.active(), self.active)

    def test_limits_and_non_pending_items(self):
        self.assertFalse(self.queue.move(self.movie.id, -1))   # ya es el primer pendiente
        self.assertFalse(self.queue.move(self.song.id, 1))     # ya es el último
        self.assertFalse(self.queue.move(self.active.id, 1))   # la activa no se mueve
        self.assertFalse(self.queue.move(self.done.id, -1))
        self.assertEqual(self.queue.pending_position(self.song.id), (1, 2))
        self.assertIsNone(self.queue.pending_position(self.active.id))

    def test_unfinished_puts_active_first(self):
        self.queue.move(self.song.id, -1)
        self.assertEqual(
            [i.id for i in self.queue.unfinished()], [self.active.id, self.song.id, self.movie.id]
        )


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "queue.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_round_trip_keeps_order_and_options(self):
        original = [
            QueueItem(
                request=request(
                    "https://cdn.example/master.m3u8", DownloadType.WEB_VIDEO, quality=720,
                    headers={"Referer": "https://sitio.example/ver"}, filename="Película",
                    subtitles=True, subtitle_langs=("es",),
                ),
                source="Web / M3U8", title="Película (2024)",
            ),
            QueueItem(request=request("https://youtu.be/a"), source="YouTube"),
        ]
        save_queue(self.path, original)
        loaded = load_queue(self.path)
        self.assertEqual([i.request for i in loaded], [i.request for i in original])
        self.assertEqual(loaded[0].title, "Película (2024)")
        self.assertEqual(loaded[0].source, "Web / M3U8")
        self.assertTrue(all(i.status is ItemStatus.PENDING for i in loaded))
        self.assertFalse(self.path.with_suffix(".json.tmp").exists())

    def test_file_with_bom_is_accepted(self):
        data = {"version": 1, "items": [{"request": {
            "url": "https://youtu.be/a", "output_dir": "out", "download_type": "MP3"}}]}
        self.path.write_text(json.dumps(data), encoding="utf-8-sig")
        self.assertEqual([i.request.url for i in load_queue(self.path)], ["https://youtu.be/a"])

    def test_missing_file_is_empty_queue(self):
        self.assertEqual(load_queue(self.path), [])

    def test_corrupt_file_is_set_aside(self):
        self.path.write_text("{ esto no es json", encoding="utf-8")
        self.assertEqual(load_queue(self.path), [])
        self.assertFalse(self.path.exists())
        self.assertTrue(self.path.with_suffix(".json.bad").exists())

    def test_invalid_entries_are_skipped(self):
        self.path.write_text(json.dumps({"version": 1, "items": [
            {"request": {"url": "https://youtu.be/ok", "output_dir": "out", "download_type": "MP3"}},
            {"request": {"url": "https://youtu.be/x", "output_dir": "out", "download_type": "NO_EXISTE"}},
            {"sin_request": True},
        ]}), encoding="utf-8")
        self.assertEqual([i.request.url for i in load_queue(self.path)], ["https://youtu.be/ok"])

    def test_restore_skips_duplicates(self):
        queue = DownloadQueue()
        queue.add(request("https://youtu.be/a"))
        restored = queue.restore([
            QueueItem(request=request("https://youtu.be/a")),
            QueueItem(request=request("https://youtu.be/b")),
        ])
        self.assertEqual([i.request.url for i in restored], ["https://youtu.be/b"])


if __name__ == "__main__":
    unittest.main()
