"""Validación del archivo final (usa FFmpeg real; se omite si no está instalado)."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.core import CorruptFileError, DownloadType, ProcessingError
from app.core.dependencies import find_ffmpeg, find_ffprobe
from app.core.ytdlp_backend import translate_error
from app.core.validation import validate_media

FFMPEG = find_ffmpeg()
FFPROBE = find_ffprobe(FFMPEG)


def make_media(path: Path, seconds: int, video: bool) -> Path:
    """Genera un clip real con FFmpeg (patrón de prueba + tono)."""
    inputs = ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    if video:
        inputs = ["-f", "lavfi", "-i", f"testsrc=size=320x240:rate=25:duration={seconds}"] + inputs
    codecs = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"] if video else ["-c:a", "libmp3lame"]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.run([str(FFMPEG), "-y", "-v", "error", *inputs, *codecs, "-shortest", str(path)],
                   check=True, creationflags=flags)
    return path


@unittest.skipUnless(FFMPEG and FFPROBE, "requiere FFmpeg y ffprobe")
class ValidateMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.video = make_media(cls.tmp / "video.mp4", 20, video=True)
        cls.audio = make_media(cls.tmp / "cancion.mp3", 20, video=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_valid_video_and_audio_pass(self):
        check = validate_media(self.video, True, FFPROBE, expected_duration=20)
        self.assertTrue(check.ok, check.reason)
        self.assertAlmostEqual(check.duration, 20, delta=1)
        # Un MP3 corto y ligero (muy por debajo de 5 MB) es válido: por eso no se usa un umbral fijo.
        self.assertLess(self.audio.stat().st_size, 5_000_000)
        self.assertTrue(validate_media(self.audio, False, FFPROBE, expected_duration=20).ok)

    def test_tiny_file_like_the_reported_bug_fails(self):
        tiny = self.tmp / "roto.mp4"
        tiny.write_bytes(self.video.read_bytes()[:796])
        check = validate_media(tiny, True, FFPROBE)
        self.assertFalse(check.ok)
        self.assertIn("796 bytes", check.reason)

    def test_garbage_that_ffmpeg_cannot_read_fails(self):
        junk = self.tmp / "basura.mp4"
        junk.write_bytes(os.urandom(200_000))
        check = validate_media(junk, True, FFPROBE)
        self.assertFalse(check.ok)
        self.assertIn("FFmpeg no puede leerlo", check.reason)

    def test_audio_only_file_is_not_a_valid_video(self):
        check = validate_media(self.audio, True, FFPROBE)
        self.assertFalse(check.ok)
        self.assertIn("pista de video", check.reason)

    def test_shorter_than_announced_is_incomplete(self):
        check = validate_media(self.video, True, FFPROBE, expected_duration=600)
        self.assertFalse(check.ok)
        self.assertIn("incompleto", check.reason)

    def test_missing_file(self):
        self.assertFalse(validate_media(self.tmp / "no-existe.mp4", True, FFPROBE).ok)


class ProcessingErrorTests(unittest.TestCase):
    def test_ffmpeg_failures_are_processing_errors(self):
        for message in (
            "ERROR: Postprocessing: Conversion failed!",
            "ERROR: Postprocessing: video.mp4: Invalid data found when processing input",
        ):
            self.assertIsInstance(translate_error(message), ProcessingError, message)

    def test_missing_segment_is_not_reported_as_network_problem(self):
        from app.core import ContentUnavailableError
        error = translate_error("ERROR: [download] Got error: HTTP Error 404: Not Found. Giving up after 20 retries")
        self.assertIsInstance(error, ContentUnavailableError)
        self.assertIn("404", str(error))

    def test_corrupt_error_has_user_message(self):
        error = CorruptFileError(detail="video.mp4: el archivo final solo ocupa 796 bytes")
        self.assertIn("se eliminó", str(error))
        self.assertIn("796 bytes", error.detail)
        self.assertTrue(DownloadType.WEB_VIDEO.is_video)


if __name__ == "__main__":
    unittest.main()
