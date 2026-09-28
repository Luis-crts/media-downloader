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


def external_env() -> dict[str, str]:
    """Entorno para lanzar programas del sistema (ffprobe, xdg-open, notify-send…).

    En Linux (y macOS), el ejecutable de PyInstaller apunta ``LD_LIBRARY_PATH``
    (``DYLD_LIBRARY_PATH``) a sus bibliotecas empaquetadas, y los procesos hijos lo heredan:
    el ``ffprobe`` del sistema cargaba el ``libstdc++`` de la app (de la distribución donde
    se compiló) y no arrancaba en distribuciones más nuevas («GLIBCXX_3.4.32 not found»).
    Se restaura el valor original que PyInstaller guarda en ``*_ORIG`` (o se elimina si no
    había), igual que hace yt-dlp con sus propias llamadas a FFmpeg.
    """
    env = os.environ.copy()
    if not is_frozen():
        return env
    for key in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        original = env.pop(f"{key}_ORIG", None)
        if original is None:
            env.pop(key, None)
        else:
            env[key] = original
    return env


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


def queue_file_path() -> Path:
    """Cola de descargas pendientes, guardada entre sesiones."""
    return user_data_dir() / "queue.json"


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
