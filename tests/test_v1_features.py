"""Pruebas de las funciones de la 1.0: reproducir desde la cola y notificaciones."""
import base64
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from app import notifications
from app.core import DownloadRequest, DownloadType
from app.download_queue import ItemStatus, QueueItem


class MediaFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def item_with(self, files: dict[str, int]) -> QueueItem:
        paths = []
        for name, size in files.items():
            path = self.tmp / name
            path.write_bytes(b"x" * size)
            paths.append(path)
        item = QueueItem(request=DownloadRequest("https://x/y", self.tmp, DownloadType.TORRENT))
        item.status, item.files = ItemStatus.DONE, paths
        return item

    def test_biggest_media_file_skipping_subtitles_and_extras(self):
        item = self.item_with({"Sintel.es.srt": 50, "Sintel.mp4": 500, "trailer.mp4": 100, "poster.jpg": 900})
        self.assertEqual(item.media_file.name, "Sintel.mp4")

    def test_audio_is_playable(self):
        self.assertEqual(self.item_with({"cancion.mp3": 10}).media_file.name, "cancion.mp3")

    def test_missing_or_non_media(self):
        item = self.item_with({"notas.txt": 10})
        self.assertIsNone(item.media_file)
        item = self.item_with({"video.mkv": 10})
        item.files[0].unlink()                      # el usuario lo movió o lo borró
        self.assertIsNone(item.media_file)


class NotificationTests(unittest.TestCase):
    def test_windows_script_escapes_xml_and_quotes(self):
        script = notifications.windows_toast_script("Descarga <completada>", "L'Atalante & otros")
        self.assertIn("Descarga &lt;completada&gt;", script)
        self.assertIn("L''Atalante &amp; otros", script)          # comilla simple duplicada para PowerShell
        self.assertIn("CreateToastNotifier('MediaDownloader.App')", script)

    def test_windows_command_is_encoded(self):
        command = notifications.windows_command("Título", "Película: «Sintel»")
        self.assertEqual(command[0], "powershell.exe")
        decoded = base64.b64decode(command[-1]).decode("utf-16-le")
        self.assertIn("Película: «Sintel»", decoded)

    def test_linux_prefers_notify_send_then_gdbus(self):
        icon = Path("icon.png")
        with mock.patch("shutil.which", side_effect=lambda name: "/usr/bin/notify-send" if name == "notify-send" else None):
            self.assertEqual(notifications.linux_command("T", "M")[:3], ["notify-send", "--app-name", "Media Downloader"])
        with mock.patch("shutil.which", side_effect=lambda name: "/usr/bin/gdbus" if name == "gdbus" else None):
            command = notifications.linux_command("T", "M", icon)
            self.assertEqual(command[0], "gdbus")
            self.assertIn("org.freedesktop.Notifications.Notify", command)
        with mock.patch("shutil.which", return_value=None):
            self.assertIsNone(notifications.linux_command("T", "M"))

    def test_notify_never_raises(self):
        finished = threading.Event()

        def failing_run(*_a, **_k):
            finished.set()
            raise OSError("sin PowerShell")

        with mock.patch("subprocess.run", side_effect=failing_run), \
             mock.patch.object(notifications, "build_command", return_value=["no-existe"]):
            notifications.notify("T", "M")                 # no debe lanzar
            self.assertTrue(finished.wait(5))


if __name__ == "__main__":
    unittest.main()
