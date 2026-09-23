"""Núcleo de descarga: independiente de cualquier interfaz gráfica."""
from app.core.base import (
    BaseDownloader,
    ContentUnavailableError,
    DownloadCancelledError,
    DownloaderError,
    DownloadRequest,
    DownloadResult,
    DownloadStage,
    DownloadType,
    FFmpegNotFoundError,
    InvalidURLError,
    NetworkError,
    ProgressInfo,
    available_sources,
    get_downloader,
    register_downloader,
)
from app.core.dependencies import find_ffmpeg, find_js_runtime, ffmpeg_version

# Importar los proveedores los registra automáticamente.
from app.core import downloader  # noqa: F401,E402

__all__ = [
    "BaseDownloader", "ContentUnavailableError", "DownloadCancelledError", "DownloaderError",
    "DownloadRequest", "DownloadResult", "DownloadStage", "DownloadType", "FFmpegNotFoundError",
    "InvalidURLError", "NetworkError", "ProgressInfo", "available_sources", "get_downloader",
    "register_downloader", "find_ffmpeg", "find_js_runtime", "ffmpeg_version",
]
