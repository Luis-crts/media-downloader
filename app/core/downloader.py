"""Proveedor de descargas de YouTube basado en yt-dlp + FFmpeg."""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadCancelled, DownloadError

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
    ProgressCallback,
    ProgressInfo,
    register_downloader,
)
from app.core.dependencies import check_connection, find_js_runtime, require_ffmpeg

log = logging.getLogger(__name__)

_YOUTUBE_URL = re.compile(
    r"^(https?://)?((www|m|music)\.)?(youtube\.com|youtu\.be|youtube-nocookie\.com)/\S+",
    re.IGNORECASE,
)
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_NETWORK_HINTS = (
    "getaddrinfo failed", "failed to resolve", "name or service not known",
    "temporary failure in name resolution", "network is unreachable", "timed out",
    "connection refused", "connection reset", "no route to host", "urlopen error",
    "unable to download webpage", "remote end closed connection",
)
_FFMPEG_HINTS = ("ffmpeg not found", "ffprobe not found", "ffmpeg is not installed")
_INVALID_HINTS = ("unsupported url", "is not a valid url", "incomplete youtube id", "does not exist")
_UNAVAILABLE_HINTS = (
    "unavailable", "private video", "not available", "members-only",
    "sign in to confirm", "has been removed", "copyright", "this live event",
)

_POSTPROCESSOR_LABELS = {
    "ExtractAudio": "Convirtiendo audio…",
    "Merger": "Uniendo video y audio…",
    "VideoRemuxer": "Ajustando contenedor MP4…",
    "Metadata": "Escribiendo metadatos…",
    "EmbedThumbnail": "Insertando carátula…",
    "ThumbnailsConvertor": "Preparando carátula…",
}


def _clean(message: str) -> str:
    message = _ANSI.sub("", str(message)).strip()
    return re.sub(r"^ERROR:\s*", "", message)


def _translate_error(message: str) -> DownloaderError:
    """Convierte un error de yt-dlp en un error comprensible para el usuario."""
    text = _clean(message)
    lower = text.lower()
    if any(h in lower for h in _FFMPEG_HINTS):
        return FFmpegNotFoundError(detail=text)
    if any(h in lower for h in _NETWORK_HINTS):
        return NetworkError(detail=text)
    if any(h in lower for h in _INVALID_HINTS):
        return InvalidURLError("No se encontró ningún video o lista en ese enlace.", detail=text)
    if any(h in lower for h in _UNAVAILABLE_HINTS):
        return ContentUnavailableError(detail=text)
    return DownloaderError(f"No se pudo completar la descarga:\n{text}", detail=text)


class _YdlLogger:
    """Silencia la salida de consola de yt-dlp y guarda los errores."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def debug(self, msg: str) -> None:
        log.debug(msg)

    def info(self, msg: str) -> None:
        log.debug(msg)

    def warning(self, msg: str) -> None:
        log.warning(_clean(msg))

    def error(self, msg: str) -> None:
        self.errors.append(_clean(msg))
        log.error(_clean(msg))


class _ProgressTracker:
    """Adapta los hooks de yt-dlp a ``ProgressInfo`` y gestiona la cancelación."""

    def __init__(self, emit: ProgressCallback, cancel_event: threading.Event, item_count: int | None):
        self._emit = emit
        self._cancel = cancel_event
        self._item_count = item_count
        self.completed: list[Path] = []

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise DownloadCancelled("Cancelado por el usuario")

    def _position(self, info: dict[str, Any]) -> tuple[int | None, int | None]:
        index = info.get("playlist_index") or info.get("playlist_autonumber")
        count = info.get("n_entries") or info.get("playlist_count") or self._item_count
        return index, count

    @staticmethod
    def _stream_label(info: dict[str, Any]) -> str:
        has_video = info.get("vcodec") not in (None, "none")
        has_audio = info.get("acodec") not in (None, "none")
        if has_video and not has_audio:
            return "Descargando pista de video…"
        if has_audio and not has_video:
            return "Descargando pista de audio…"
        return "Descargando…"

    def on_download(self, d: dict[str, Any]) -> None:
        self._check_cancel()
        info = d.get("info_dict") or {}
        index, count = self._position(info)
        title = info.get("title") or ""

        if d["status"] == "downloading":
            done = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                percent = min(done / total * 100, 100.0)
            elif d.get("fragment_count"):
                percent = (d.get("fragment_index") or 0) / d["fragment_count"] * 100
            else:
                percent = None
            self._emit(ProgressInfo(
                stage=DownloadStage.DOWNLOADING, title=title, message=self._stream_label(info),
                percent=percent, downloaded_bytes=done, total_bytes=total,
                speed=d.get("speed"), eta=d.get("eta"), item_index=index, item_count=count,
            ))
        elif d["status"] == "finished":
            self._emit(ProgressInfo(
                stage=DownloadStage.PROCESSING, title=title, percent=100.0,
                message="Descarga terminada, procesando…", item_index=index, item_count=count,
            ))

    def on_postprocess(self, d: dict[str, Any]) -> None:
        self._check_cancel()
        if d["status"] != "started":
            return
        info = d.get("info_dict") or {}
        index, count = self._position(info)
        self._emit(ProgressInfo(
            stage=DownloadStage.PROCESSING, title=info.get("title") or "",
            message=_POSTPROCESSOR_LABELS.get(d.get("postprocessor", ""), "Procesando…"),
            item_index=index, item_count=count,
        ))

    def on_file_done(self, filepath: str) -> None:
        path = Path(filepath)
        self.completed.append(path)
        self._emit(ProgressInfo(
            stage=DownloadStage.ITEM_DONE, title=path.stem, percent=100.0,
            message=f"Guardado: {path.name}",
        ))


@register_downloader
class YouTubeDownloader(BaseDownloader):
    name = "YouTube"
    supported_types = tuple(DownloadType)

    @classmethod
    def can_handle(cls, url: str) -> bool:
        return bool(_YOUTUBE_URL.match(url.strip()))

    # ------------------------------------------------------------------ #
    def download(
        self,
        request: DownloadRequest,
        on_progress: ProgressCallback,
        cancel_event: threading.Event | None = None,
    ) -> DownloadResult:
        cancel_event = cancel_event or threading.Event()
        url = request.url.strip()
        if not self.can_handle(url):
            raise InvalidURLError("El enlace no parece ser de YouTube.")

        ffmpeg = require_ffmpeg()
        check_connection()
        try:
            request.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DownloaderError(
                f"No se puede escribir en la carpeta de destino:\n{request.output_dir}", detail=str(exc)
            ) from exc

        on_progress(ProgressInfo(stage=DownloadStage.ANALYZING, message="Analizando enlace…"))
        info = self._probe(url, request.allow_playlist)
        if cancel_event.is_set():
            raise DownloadCancelledError()

        is_playlist = info.get("_type") == "playlist"
        item_count = len(info.get("entries") or []) if is_playlist else 1
        if is_playlist:
            on_progress(ProgressInfo(
                stage=DownloadStage.ANALYZING, title=info.get("title") or "",
                message=f"Lista detectada: {item_count} elementos", item_count=item_count,
            ))

        logger = _YdlLogger()
        tracker = _ProgressTracker(on_progress, cancel_event, item_count)
        options = self._build_options(request, ffmpeg, is_playlist, logger, tracker)

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([url])
        except DownloadCancelled as exc:
            raise DownloadCancelledError() from exc
        except DownloadError as exc:
            raise _translate_error(str(exc)) from exc

        if not tracker.completed:
            if logger.errors:
                raise _translate_error(logger.errors[0])
            raise DownloaderError("No se encontró contenido descargable en el enlace.")

        return DownloadResult(
            output_dir=request.output_dir, completed=tracker.completed, failed=logger.errors,
        )

    # ------------------------------------------------------------------ #
    def _base_options(self, logger: _YdlLogger) -> dict[str, Any]:
        options: dict[str, Any] = {
            "logger": logger,
            "quiet": True,
            "no_warnings": False,
            "noprogress": True,
            "socket_timeout": 20,
            "retries": 5,
            "fragment_retries": 5,
        }
        runtime = find_js_runtime()
        if runtime:
            options["js_runtimes"] = {runtime: {}}
        return options

    def _probe(self, url: str, allow_playlist: bool) -> dict[str, Any]:
        """Extracción rápida (sin descargar) para validar el enlace y detectar listas."""
        options = self._base_options(_YdlLogger()) | {
            "skip_download": True,
            "extract_flat": "in_playlist",
            "noplaylist": not allow_playlist,
        }
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
        except DownloadError as exc:
            raise _translate_error(str(exc)) from exc
        if not info:
            raise InvalidURLError("No se encontró ningún video en ese enlace.")
        return info

    def _build_options(
        self,
        request: DownloadRequest,
        ffmpeg: Path,
        is_playlist: bool,
        logger: _YdlLogger,
        tracker: _ProgressTracker,
    ) -> dict[str, Any]:
        out = request.output_dir
        if is_playlist:
            template = out / "%(playlist_title)s" / "%(playlist_index)03d - %(title)s.%(ext)s"
        else:
            template = out / "%(title)s.%(ext)s"

        options = self._base_options(logger) | {
            "outtmpl": str(template),
            "ffmpeg_location": str(ffmpeg.parent),
            "noplaylist": not request.allow_playlist,
            # En listas, un video no disponible no debe abortar el resto.
            "ignoreerrors": "only_download" if is_playlist else False,
            "windowsfilenames": True,
            "overwrites": False,
            "continuedl": True,
            "concurrent_fragment_downloads": 4,
            "progress_hooks": [tracker.on_download],
            "postprocessor_hooks": [tracker.on_postprocess],
            "post_hooks": [tracker.on_file_done],
        }
        options.update(self._format_options(request.download_type))
        return options

    @staticmethod
    def _format_options(download_type: DownloadType) -> dict[str, Any]:
        metadata = {"key": "FFmpegMetadata", "add_metadata": True}
        thumbnail = {"key": "EmbedThumbnail", "already_have_thumbnail": False}

        if download_type is DownloadType.MP3:
            return {
                "format": "bestaudio/best",
                "writethumbnail": True,
                "postprocessors": [
                    # preferredquality "0" = VBR V0, la mejor calidad de LAME.
                    {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"},
                    metadata,
                    thumbnail,
                ],
            }

        if download_type is DownloadType.M4A:
            return {
                # YouTube casi siempre ofrece AAC nativo: se extrae sin recodificar.
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "writethumbnail": True,
                "postprocessors": [
                    {"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "192"},
                    metadata,
                    thumbnail,
                ],
            }

        if download_type is DownloadType.MP4:
            return {
                "format": "bv*+ba/b",
                # Máxima resolución primero; a igualdad, H.264/AAC por compatibilidad.
                "format_sort": ["res", "fps", "vcodec:h264", "acodec:aac"],
                "merge_output_format": "mp4",
                "postprocessors": [
                    {"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"},
                    metadata,
                ],
            }

        raise ValueError(f"Tipo de descarga no soportado: {download_type}")
