"""Contratos comunes a todos los proveedores de descarga.

Cualquier fuente nueva (p. ej. un módulo de películas) solo necesita heredar de
``BaseDownloader``, implementar ``can_handle`` y ``download`` y registrarse con
``@register_downloader``. La GUI no conoce a los proveedores concretos.
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable


# --------------------------------------------------------------------------- #
# Modelos
# --------------------------------------------------------------------------- #
class DownloadType(Enum):
    """Tipos de descarga. El valor es la etiqueta que muestra la GUI."""

    MP3 = "Audio MP3 (mejor calidad)"
    M4A = "Audio M4A / MP4 (sin video)"
    MP4 = "Video MP4 (video + audio)"


class DownloadStage(Enum):
    ANALYZING = "analyzing"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    ITEM_DONE = "item_done"


@dataclass(frozen=True)
class DownloadRequest:
    url: str
    output_dir: Path
    download_type: DownloadType
    allow_playlist: bool = True


@dataclass
class ProgressInfo:
    stage: DownloadStage
    title: str = ""
    message: str = ""
    percent: float | None = None      # 0-100; None = progreso desconocido
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed: float | None = None        # bytes/s
    eta: int | None = None            # segundos
    item_index: int | None = None     # posición dentro de la lista
    item_count: int | None = None


@dataclass
class DownloadResult:
    output_dir: Path
    completed: list[Path] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


ProgressCallback = Callable[[ProgressInfo], None]


# --------------------------------------------------------------------------- #
# Errores (mensajes pensados para mostrarse directamente al usuario)
# --------------------------------------------------------------------------- #
class DownloaderError(Exception):
    title = "Error de descarga"
    default_message = "Ocurrió un error inesperado durante la descarga."

    def __init__(self, message: str | None = None, detail: str = "") -> None:
        super().__init__(message or self.default_message)
        self.detail = detail


class InvalidURLError(DownloaderError):
    title = "Enlace no válido"
    default_message = "El enlace no es válido o la fuente no está soportada."


class NetworkError(DownloaderError):
    title = "Sin conexión"
    default_message = (
        "No se pudo conectar con el servidor. Revisa tu conexión a Internet "
        "e inténtalo de nuevo."
    )


class FFmpegNotFoundError(DownloaderError):
    title = "FFmpeg no encontrado"
    default_message = (
        "FFmpeg no está instalado o no está en el PATH.\n"
        "Instálalo (ver README) o copia ffmpeg.exe y ffprobe.exe en la carpeta 'bin' "
        "de la aplicación."
    )


class ContentUnavailableError(DownloaderError):
    title = "Contenido no disponible"
    default_message = "El contenido es privado, fue eliminado o no está disponible en tu región."


class DownloadCancelledError(DownloaderError):
    title = "Descarga cancelada"
    default_message = "La descarga fue cancelada por el usuario."


# --------------------------------------------------------------------------- #
# Proveedor base y registro
# --------------------------------------------------------------------------- #
class BaseDownloader(ABC):
    name: str = "base"
    supported_types: tuple[DownloadType, ...] = ()

    @classmethod
    @abstractmethod
    def can_handle(cls, url: str) -> bool:
        """Devuelve True si este proveedor sabe procesar la URL."""

    @abstractmethod
    def download(
        self,
        request: DownloadRequest,
        on_progress: ProgressCallback,
        cancel_event: threading.Event | None = None,
    ) -> DownloadResult:
        """Descarga de forma bloqueante (llamar desde un hilo secundario).

        Debe lanzar subclases de ``DownloaderError`` ante cualquier fallo y
        ``DownloadCancelledError`` si ``cancel_event`` se activa.
        """


_PROVIDERS: list[type[BaseDownloader]] = []


def register_downloader(cls: type[BaseDownloader]) -> type[BaseDownloader]:
    _PROVIDERS.append(cls)
    return cls


def available_sources() -> list[str]:
    return [p.name for p in _PROVIDERS]


def get_downloader(url: str) -> BaseDownloader:
    url = url.strip()
    if not url:
        raise InvalidURLError("Pega un enlace antes de descargar.")
    for provider in _PROVIDERS:
        if provider.can_handle(url):
            return provider()
    raise InvalidURLError(
        "El enlace no es válido o la fuente no está soportada todavía.\n"
        f"Fuentes disponibles: {', '.join(available_sources())}."
    )
