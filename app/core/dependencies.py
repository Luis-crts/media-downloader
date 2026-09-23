"""Localización de dependencias externas (FFmpeg y runtime de JavaScript)."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

from app.core.base import FFmpegNotFoundError, NetworkError
from app.paths import app_dir, bundle_dir

_EXE = ".exe" if os.name == "nt" else ""


def find_ffmpeg() -> Path | None:
    """Orden de búsqueda:

    1. ``<carpeta del ejecutable>/bin`` (FFmpeg portable que deja el usuario).
    2. ``<sys._MEIPASS>/bin`` (FFmpeg embebido con ``build.py --embed-ffmpeg``).
    3. El PATH del sistema.
    """
    for base in dict.fromkeys((app_dir(), bundle_dir())):
        candidate = base / "bin" / f"ffmpeg{_EXE}"
        if candidate.is_file():
            return candidate
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def require_ffmpeg() -> Path:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise FFmpegNotFoundError()
    return ffmpeg


def ffmpeg_version(ffmpeg: Path) -> str | None:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        out = subprocess.run(
            [str(ffmpeg), "-version"], capture_output=True, text=True,
            timeout=10, creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    first_line = out.stdout.splitlines()[0] if out.stdout else ""
    return first_line or None


def find_js_runtime() -> str | None:
    """yt-dlp necesita un runtime JS (Deno recomendado) para YouTube.

    Devuelve el nombre del runtime disponible o None.
    """
    for runtime in ("deno", "node", "bun"):
        if shutil.which(runtime):
            return runtime
    return None


def check_connection(host: str = "www.youtube.com", port: int = 443, timeout: float = 6) -> None:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError as exc:
        raise NetworkError(detail=str(exc)) from exc
