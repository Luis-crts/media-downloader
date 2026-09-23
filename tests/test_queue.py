"""Pruebas del modelo de la cola de descargas (sin interfaz ni red)."""
import unittest
from pathlib import Path

from app.core import DownloadRequest, DownloadType
from app.download_queue import DownloadQueue, ItemStatus


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


if __name__ == "__main__":
    unittest.main()
