"""Núcleo de descarga: independiente de cualquier interfaz gráfica."""
from app.core.base import (
    AccessDeniedError,
    BaseDownloader,
    ContentUnavailableError,
    DownloadCancelledError,
    DownloaderError,
    DownloadRequest,
    DownloadResult,
    DownloadStage,
    DownloadType,
    DRMProtectedError,
    FFmpegNotFoundError,
    InvalidURLError,
    NetworkError,
    ProgressInfo,
    QualityOption,
    ResolvedMedia,
    available_sources,
    get_downloader,
    register_downloader,
)
from app.core.dependencies import find_ffmpeg, find_js_runtime, ffmpeg_version
from app.core.extractor import default_user_agent, register_resolver

# Importar los proveedores los registra. El orden importa: los específicos primero
# y el genérico al final, como respaldo para cualquier URL http(s).
from app.core import downloader  # noqa: F401,E402  (YouTube)
from app.core import generic  # noqa: F401,E402  (Web / M3U8)

__all__ = [
    "AccessDeniedError", "BaseDownloader", "ContentUnavailableError", "DownloadCancelledError",
    "DownloaderError", "DownloadRequest", "DownloadResult", "DownloadStage", "DownloadType",
    "DRMProtectedError", "FFmpegNotFoundError", "InvalidURLError", "NetworkError", "ProgressInfo",
    "QualityOption", "ResolvedMedia", "available_sources", "get_downloader", "register_downloader",
    "register_resolver", "default_user_agent", "find_ffmpeg", "find_js_runtime", "ffmpeg_version",
]
