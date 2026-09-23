"""Rutas que funcionan igual desde el código fuente y desde el binario de PyInstaller.

- ``bundle_dir()``: recursos de solo lectura empaquetados (iconos, FFmpeg embebido).
  En PyInstaller es ``sys._MEIPASS`` (carpeta temporal en --onefile, ``_internal``
  en --onedir).
- ``app_dir()``: carpeta donde está el ejecutable. El usuario puede dejar ahí una
  carpeta ``bin/`` con su propio FFmpeg.
- ``user_data_dir()``: carpeta escribible del usuario (self-check y respaldo del log).
- ``log_file_path()``: ``media_downloader.log`` en ``app_dir()`` (o en ``user_data_dir()``
  si ahí no se puede escribir).
"""
from __future__ import annotations

import functools
import os
import sys
from pathlib import Path

APP_ID = "media-downloader"
_SOURCE_ROOT = Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return _SOURCE_ROOT


def app_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _SOURCE_ROOT


def resource_path(*parts: str) -> Path:
    """Ruta a un recurso empaquetado con ``--add-data`` / ``--add-binary``."""
    return bundle_dir().joinpath(*parts)


LOG_FILENAME = "media_downloader.log"


@functools.lru_cache(maxsize=1)
def log_file_path() -> Path:
    """Archivo de log: en la carpeta del proyecto (o junto al ejecutable).

    Si esa carpeta no admite escritura (p. ej. instalada en «Archivos de programa»),
    se usa la carpeta de datos del usuario.
    """
    preferred = app_dir() / LOG_FILENAME
    try:
        with open(preferred, "a", encoding="utf-8"):
            pass
        return preferred
    except OSError:
        return user_data_dir() / LOG_FILENAME


def user_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        path = base / "MediaDownloader"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "MediaDownloader"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        path = base / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path
