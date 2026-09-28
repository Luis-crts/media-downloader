"""Regresión v1.0.1: en Linux, el validador borraba descargas válidas.

El ejecutable de PyInstaller apunta LD_LIBRARY_PATH a sus bibliotecas; el ffprobe del
sistema las heredaba y no arrancaba («GLIBCXX_3.4.32 not found»), así que el validador
tomaba el archivo por dañado y lo eliminaba.
"""
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from app.core import validation
from app.core.validation import KEEP_UNREADABLE_ABOVE, validate_media, wait_until_stable
from app.paths import external_env

FROZEN = {"frozen": True, "_MEIPASS": "/opt/app/_internal"}


class ExternalEnvTests(unittest.TestCase):
    def test_frozen_restores_original_library_path(self):
        env = {"LD_LIBRARY_PATH": "/opt/app/_internal", "LD_LIBRARY_PATH_ORIG": "/usr/local/lib", "PATH": "/usr/bin"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.multiple(sys, create=True, **FROZEN):
            result = external_env()
        self.assertEqual(result["LD_LIBRARY_PATH"], "/usr/local/lib")
        self.assertNotIn("LD_LIBRARY_PATH_ORIG", result)
        self.assertEqual(result["PATH"], "/usr/bin")

    def test_frozen_without_original_removes_the_bundled_path(self):
        with mock.patch.dict(os.environ, {"LD_LIBRARY_PATH": "/opt/app/_internal"}, clear=True), \
             mock.patch.multiple(sys, create=True, **FROZEN):
            self.assertNotIn("LD_LIBRARY_PATH", external_env())

    def test_from_source_the_environment_is_untouched(self):
        with mock.patch.dict(os.environ, {"LD_LIBRARY_PATH": "/mine"}, clear=True):
            self.assertEqual(external_env()["LD_LIBRARY_PATH"], "/mine")

    def test_ffprobe_is_launched_with_the_restored_environment(self):
        captured = {}

        def fake_run(*_args, **kwargs):
            captured.update(kwargs.get("env") or {})
            raise OSError("parar aquí")

        env = {"LD_LIBRARY_PATH": "/opt/app/_internal", "PATH": "/usr/bin"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.multiple(sys, create=True, **FROZEN), \
             mock.patch("subprocess.run", side_effect=fake_run):
            validation.probe(Path("x.mp4"), Path("/usr/bin/ffprobe"))
        self.assertEqual(captured.get("PATH"), "/usr/bin")        # se pasó un entorno explícito…
        self.assertNotIn("LD_LIBRARY_PATH", captured)             # …sin las bibliotecas de la app


class SafetyNetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name: str, size: int) -> Path:
        path = self.tmp / name
        path.write_bytes(os.urandom(size))
        return path

    def test_large_file_is_kept_when_ffprobe_cannot_run(self):
        # Mismo síntoma que en Linux: ffprobe existe pero no arranca.
        video = self.write("pelicula.mp4", KEEP_UNREADABLE_ABOVE + 1)
        with mock.patch.object(validation, "probe",
                               return_value=(None, "ffprobe: libstdc++.so.6: version `GLIBCXX_3.4.32' not found")):
            check = validate_media(video, True, Path("/usr/bin/ffprobe"))
        self.assertTrue(check.ok)
        self.assertIn("GLIBCXX", check.warning)
        self.assertIn("sin verificar", check.warning)

    def test_small_unreadable_file_is_still_rejected(self):
        junk = self.write("roto.mp4", 200_000)
        with mock.patch.object(validation, "probe", return_value=(None, "Invalid data found")):
            check = validate_media(junk, True, Path("ffprobe"))
        self.assertFalse(check.ok)
        self.assertEqual(check.warning, "")

    def test_tiny_file_is_rejected_before_ffprobe(self):
        tiny = self.write("mini.mp4", 796)
        with mock.patch.object(validation, "probe") as probe:
            self.assertFalse(validate_media(tiny, True, Path("ffprobe")).ok)
        probe.assert_not_called()

    def test_wait_until_stable(self):
        stable = self.write("quieto.mp4", 10)
        start = time.monotonic()
        wait_until_stable(stable, min_wait=0.2, max_wait=2)
        self.assertLess(time.monotonic() - start, 1.0)

        growing = self.write("creciendo.mp4", 10)

        def append():
            for _ in range(4):
                time.sleep(0.15)
                with growing.open("ab") as fh:
                    fh.write(b"x" * 100)

        writer = threading.Thread(target=append)
        writer.start()
        wait_until_stable(growing, min_wait=0.1, max_wait=3, step=0.2)
        writer.join()
        self.assertEqual(growing.stat().st_size, 410)   # esperó a que terminara de escribirse

    def test_missing_file_does_not_block(self):
        start = time.monotonic()
        wait_until_stable(self.tmp / "no-existe.mp4", min_wait=0.1, max_wait=2)
        self.assertLess(time.monotonic() - start, 0.5)


if __name__ == "__main__":
    unittest.main()
