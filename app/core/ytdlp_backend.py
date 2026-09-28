"""Backend común basado en yt-dlp.

``YtDlpDownloader`` implementa todo el flujo (validar → analizar → descargar →
post-procesar con FFmpeg). Los proveedores concretos (YouTube, genérico/M3U8…)
solo sobrescriben los puntos de extensión:

- ``can_handle`` / ``supported_types``
- ``_resolve``: convierte la URL del usuario en la URL que recibirá yt-dlp.
- ``_analyze``: extracción previa (p. ej. para añadir un plan B de scraping).
"""
from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Callable

import yt_dlp
from yt_dlp.utils import DownloadCancelled, DownloadError, sanitize_filename

from app.core.base import (
    AccessDeniedError,
    BaseDownloader,
    ContentUnavailableError,
    CorruptFileError,
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
    ProcessingError,
    ProgressCallback,
    ProgressInfo,
    QualityOption,
    ResolvedMedia,
)
from app.core.dependencies import check_connection, find_ffprobe, find_js_runtime, require_ffmpeg
from app.core.validation import MediaCheck, validate_media, wait_until_stable

log = logging.getLogger(__name__)

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

# El orden importa: se evalúan de arriba abajo.
_ERROR_RULES: tuple[tuple[tuple[str, ...], type[DownloaderError]], ...] = (
    (("ffmpeg not found", "ffprobe not found", "ffmpeg is not installed"), FFmpegNotFoundError),
    (("postprocessing:", "conversion failed", "ffmpeg exited with code",
      "invalid data found when processing input"), ProcessingError),
    (("drm protected", "drm-protected", "this video is drm"), DRMProtectedError),
    (("http error 403", "http error 401", "403: forbidden", "401: unauthorized"), AccessDeniedError),
    ((
        "getaddrinfo failed", "failed to resolve", "name or service not known",
        "temporary failure in name resolution", "network is unreachable", "timed out",
        "connection refused", "connection reset", "no route to host", "urlopen error",
        "remote end closed connection", "giving up after", "incompleteread",
        "connection aborted",
    ), NetworkError),
    (("unsupported url", "is not a valid url", "incomplete youtube id", "does not exist",
      "http error 404", "no video formats found"), InvalidURLError),
    (("unavailable", "private video", "not available", "members-only", "sign in to confirm",
      "has been removed", "copyright", "this live event"), ContentUnavailableError),
)

_POSTPROCESSOR_LABELS = {
    "ExtractAudio": "Convirtiendo audio…",
    "Merger": "Uniendo video y audio…",
    "VideoRemuxer": "Ajustando contenedor MP4…",
    "FixupM3u8": "Uniendo segmentos HLS en MP4…",
    "Metadata": "Escribiendo metadatos…",
    "SubtitlesConvertor": "Convirtiendo subtítulos a SRT…",
    "EmbedSubtitle": "Incrustando subtítulos…",
    "EmbedThumbnail": "Insertando carátula…",
    "ThumbnailsConvertor": "Preparando carátula…",
}


def clean_message(message: str) -> str:
    message = _ANSI.sub("", str(message)).strip()
    return re.sub(r"^ERROR:\s*", "", message)


def translate_error(message: str) -> DownloaderError:
    """Convierte un error de yt-dlp en un error comprensible para el usuario."""
    text = clean_message(message)
    lower = text.lower()
    # Reintentos agotados por un 4xx (p. ej. un segmento HLS que el servidor ya no tiene):
    # no es un problema de conexión aunque el mensaje diga «Giving up after N retries».
    if "giving up after" in lower and re.search(r"http error (404|410)", lower):
        return ContentUnavailableError(
            "Una parte del video ya no está disponible en el servidor (HTTP 404).\n"
            "No se ensambló un archivo con cortes; lo descargado se conserva y puedes "
            "reintentar más tarde.",
            detail=text,
        )
    for hints, error_cls in _ERROR_RULES:
        if any(h in lower for h in hints):
            if error_cls is InvalidURLError:
                return InvalidURLError("No se encontró ningún video en ese enlace.", detail=text)
            return error_cls(detail=text)
    return DownloaderError(f"No se pudo completar la descarga:\n{text}", detail=text)


def format_options(download_type: DownloadType, quality: int | None = None) -> dict[str, Any]:
    """Opciones de formato/post-procesado de yt-dlp para cada tipo de descarga."""
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

    if download_type.is_video:
        # "res:720" = la mayor resolución que no supere 720p; "res" = la máxima.
        resolution = f"res:{quality}" if quality else "res"
        return {
            # bv*+ba: pistas separadas (DASH/HLS con audio aparte); b: stream ya multiplexado.
            "format": "bv*+ba/b",
            # A igualdad de resolución, H.264/AAC por compatibilidad.
            "format_sort": [resolution, "fps", "vcodec:h264", "acodec:aac"],
            "merge_output_format": "mp4",
            "postprocessors": [
                {"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"},
                metadata,
            ],
        }

    raise ValueError(f"Tipo de descarga no soportado: {download_type}")


def _retry_backoff(n: int) -> float:
    """Espera creciente entre reintentos (1, 2, 4, 8, 10, 10… s): da tiempo a que
    la red o el CDN se recuperen en lugar de agotar los reintentos en segundos.

    yt-dlp la invoca como ``sleep_func(n=intento)`` (argumento con nombre), así que el
    parámetro debe llamarse exactamente ``n``.
    """
    return float(min(2 ** n, 10))


def subtitle_options(langs: tuple[str, ...]) -> dict[str, Any]:
    """Descarga subtítulos (manuales o, si no hay, automáticos) de los idiomas pedidos."""
    codes = [code.strip().lower() for code in langs if code.strip()]
    if not codes or "all" in codes:
        patterns = ["all"]
    else:
        # "es" → es, es-ES, es-419 (región en mayúsculas o numérica). Se excluyen las
        # traducciones automáticas de YouTube, que usan "destino-origen" en minúsculas
        # (es-de, en-fr…): son decenas por video y provocarían bloqueos (HTTP 429).
        # yt-dlp compara con re.fullmatch(patrón, re.IGNORECASE), así que la región se
        # marca como sensible a mayúsculas con el flag local (?-i:…).
        # Una traducción concreta se puede pedir escribiendo su código: "es-en".
        patterns = [f"{re.escape(code)}(?-i:-[A-Z]{{2}}|-[0-9]{{3}})?" for code in codes]
    return {
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": [*patterns, "-live_chat"],
        "subtitlesformat": "srt/vtt/best",
    }


def qualities_from_info(info: dict[str, Any]) -> list[QualityOption]:
    heights = {
        int(f["height"])
        for f in info.get("formats") or []
        if f.get("height") and f.get("vcodec") != "none"
    }
    return [QualityOption(label=f"{h}p", max_height=h) for h in sorted(heights, reverse=True)]


def literal_for_template(name: str) -> str:
    """Convierte un texto en un fragmento literal y seguro para ``outtmpl``."""
    return sanitize_filename(name.strip(), restricted=False).replace("%", "%%")


class YdlLogger:
    """Silencia la salida de consola de yt-dlp y guarda los errores."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def debug(self, msg: str) -> None:
        # yt-dlp envía por debug() tanto sus mensajes de depuración como los informativos
        # ("[download] Destination: …", "[hlsnative] Total fragments: …").
        if msg.startswith("[debug] "):
            log.debug(msg)
        else:
            log.info(msg)

    def info(self, msg: str) -> None:
        log.info(msg)

    def warning(self, msg: str) -> None:
        log.warning(clean_message(msg))

    def error(self, msg: str) -> None:
        self.errors.append(clean_message(msg))
        log.error(clean_message(msg))


def _path_key(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


class ProgressTracker:
    """Adapta los hooks de yt-dlp a ``ProgressInfo`` y aplica pausa y cancelación."""

    def __init__(
        self,
        emit: ProgressCallback,
        cancel_event: threading.Event,
        item_count: int | None,
        title_hint: str | None = None,
        pause_event: threading.Event | None = None,
        validator: Callable[[Path, float | None], MediaCheck] | None = None,
    ):
        self._emit = emit
        self._validator = validator
        self.corrupt: list[str] = []            # archivos finales descartados por dañados
        self._expected_durations: dict[str, float] = {}
        self._last_duration: float | None = None
        # Descargas directas (no segmentadas): tamaño anunciado por el servidor la primera
        # vez, para detectar si cambia el archivo entre reintentos o si queda incompleto.
        self._announced_sizes: dict[str, int] = {}
        self._download_issues: list[str] = []
        self._downloaded: list[Path] = []      # archivos que yt-dlp terminó de descargar
        self._cancel = cancel_event
        self._pause = pause_event or threading.Event()
        self._pause_lock = threading.Lock()   # en HLS los hooks llegan desde varios hilos
        self._paused_announced = False
        self._item_count = item_count
        # Título a mostrar en lugar del de yt-dlp (que para un .m3u8 suele ser «master»).
        self._title_hint = title_hint
        self.completed: list[Path] = []

    def _title(self, info: dict[str, Any]) -> str:
        return self._title_hint or info.get("title") or ""

    def _checkpoint(self) -> None:
        """Se ejecuta en cada hook de yt-dlp: aplica la pausa y la cancelación.

        Pausar bloquea aquí el hilo que descarga (en HLS, cada hilo de segmentos al
        informar de su progreso): deja de leer del socket y no pide más segmentos.
        Lo ya descargado se conserva (.part y segmentos terminados). Si durante la pausa
        el servidor cierra la conexión inactiva, al reanudar yt-dlp la reintenta y sigue
        desde el byte o segmento donde iba (``continuedl`` + reintentos).
        """
        if self._pause.is_set() and not self._cancel.is_set():
            with self._pause_lock:
                if not self._paused_announced:
                    self._paused_announced = True
                    log.info("Descarga en pausa")
                    self._emit(ProgressInfo(stage=DownloadStage.PAUSED, message="En pausa"))
            while self._pause.is_set() and not self._cancel.is_set():
                self._cancel.wait(0.25)   # vuelve al instante si se cancela
            with self._pause_lock:
                if self._paused_announced:
                    self._paused_announced = False
                    log.info("Descarga reanudada")
        if self._cancel.is_set():
            raise DownloadCancelled("Cancelado por el usuario")

    def _position(self, info: dict[str, Any]) -> tuple[int | None, int | None]:
        index = info.get("playlist_index") or info.get("playlist_autonumber")
        count = info.get("n_entries") or info.get("playlist_count") or self._item_count
        return index, count

    @staticmethod
    def _stream_label(d: dict[str, Any], info: dict[str, Any]) -> str:
        if d.get("fragment_count"):
            return f"Descargando segmentos {d.get('fragment_index') or 0}/{d['fragment_count']}…"
        has_video = info.get("vcodec") not in (None, "none")
        has_audio = info.get("acodec") not in (None, "none")
        if has_video and not has_audio:
            return "Descargando pista de video…"
        if has_audio and not has_video:
            return "Descargando pista de audio…"
        return "Descargando…"

    def on_download(self, d: dict[str, Any]) -> None:
        self._checkpoint()
        info = d.get("info_dict") or {}
        index, count = self._position(info)
        title = self._title(info)

        self._check_size_consistency(d)
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
                stage=DownloadStage.DOWNLOADING, title=title, message=self._stream_label(d, info),
                percent=percent, downloaded_bytes=done, total_bytes=total,
                speed=d.get("speed"), eta=d.get("eta"), item_index=index, item_count=count,
            ))
        elif d["status"] == "finished":
            if d.get("filename"):
                self._downloaded.append(Path(d["filename"]))
            self._emit(ProgressInfo(
                stage=DownloadStage.PROCESSING, title=title, percent=100.0,
                message="Descarga terminada, procesando…", item_index=index, item_count=count,
            ))

    def _check_size_consistency(self, d: dict[str, Any]) -> None:
        """Descarga directa por HTTP: detecta un servidor que cambia el archivo al reanudar.

        Al reanudar tras un corte, yt-dlp pide «desde el byte N». Si entretanto el servidor
        sirve otra versión del archivo (otro tamaño total), los trozos no encajan y el
        resultado queda corrupto aunque la descarga «termine». En HLS/DASH no aplica: cada
        segmento se descarga entero.
        """
        filename = d.get("filename")
        if not filename or d.get("fragment_count") or d.get("fragment_index"):
            return
        announced = d.get("total_bytes")
        if d["status"] == "downloading" and announced:
            first = self._announced_sizes.setdefault(filename, int(announced))
            if int(announced) != first:
                issue = (f"el servidor cambió el archivo durante la descarga ({first:,} → "
                         f"{int(announced):,} bytes); las partes reanudadas no encajan")
                if issue not in self._download_issues:
                    log.warning("%s: %s", Path(filename).name, issue)
                    self._download_issues.append(issue)
                self._announced_sizes[filename] = int(announced)
        elif d["status"] == "finished" and filename in self._announced_sizes:
            expected = self._announced_sizes[filename]
            try:
                actual = os.path.getsize(filename)
            except OSError:
                actual = int(d.get("downloaded_bytes") or 0)
            if actual < expected * 0.99:
                issue = f"descarga incompleta: {actual:,} de {expected:,} bytes anunciados por el servidor"
                log.warning("%s: %s", Path(filename).name, issue)
                self._download_issues.append(issue)

    def on_postprocess(self, d: dict[str, Any]) -> None:
        self._checkpoint()
        info = d.get("info_dict") or {}
        if d["status"] == "finished":
            # Duración anunciada por la fuente, para comprobar luego el archivo final.
            duration = info.get("duration")
            if duration:
                self._last_duration = float(duration)
                if info.get("filepath"):
                    self._expected_durations[_path_key(info["filepath"])] = float(duration)
            return
        if d["status"] != "started":
            return
        index, count = self._position(info)
        self._emit(ProgressInfo(
            stage=DownloadStage.PROCESSING, title=self._title(info),
            message=_POSTPROCESSOR_LABELS.get(d.get("postprocessor", ""), "Procesando…"),
            item_index=index, item_count=count,
        ))

    def discard_unreadable_downloads(self) -> None:
        """Tras un fallo de FFmpeg: elimina lo descargado que ni FFmpeg puede leer.

        Las pistas válidas (p. ej. video y audio por separado cuando falla la unión) se
        conservan para que un reintento no tenga que volver a descargarlas.
        """
        if self._validator is None:
            return
        for path in self._downloaded:
            if not path.is_file():
                continue
            check = self._validator(path, None)
            if check.ok:
                log.info("Se conserva para reintentar: %s (%.1f MB)", path.name, check.size / 1e6)
                continue
            log.error("Archivo descargado ilegible, se elimina: %s | motivo: %s", path, check.reason)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                log.warning("No se pudo eliminar %s", path, exc_info=True)

    def on_file_done(self, filepath: str) -> None:
        """post_hook de yt-dlp: el archivo terminó (descarga + todo el post-procesado).

        Antes de darlo por bueno se valida; si está dañado se elimina para que no quede
        un archivo inservible con apariencia de completo y se anota como fallo.
        """
        path = Path(filepath)
        issues, self._download_issues = self._download_issues, []
        if self._validator is not None:
            expected = self._expected_durations.get(_path_key(filepath), self._last_duration)
            self._last_duration = None
            # Si la propia descarga ya fue inconsistente no hace falta analizar el archivo.
            if issues:
                check = MediaCheck(False, "; ".join(issues))
            else:
                wait_until_stable(path)
                check = self._validator(path, expected)
            if not check.ok:
                log.error("Archivo final dañado, se elimina: %s | motivo: %s", path, check.reason)
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    log.warning("No se pudo eliminar %s", path, exc_info=True)
                self.corrupt.append(f"{path.name}: {check.reason}")
                self._emit(ProgressInfo(
                    stage=DownloadStage.PROCESSING, title=path.stem,
                    message=f"Archivo dañado ({check.reason}); se eliminó",
                ))
                return
            if check.warning:
                log.warning("Archivo sin verificar: %s (%.1f MB) | %s", path, check.size / 1e6, check.warning)
            else:
                log.info(
                    "Archivo verificado: %s (%.1f MB%s)", path.name, check.size / 1e6,
                    f", {check.duration:.0f} s" if check.duration else "",
                )
        self.completed.append(path)
        unverified = self._validator is not None and check.warning
        self._emit(ProgressInfo(
            stage=DownloadStage.ITEM_DONE, title=path.stem, percent=100.0,
            message=f"Guardado{' (sin verificar)' if unverified else ''}: {path.name}",
        ))


class YtDlpDownloader(BaseDownloader):
    """Flujo completo de descarga con yt-dlp. Ver docstring del módulo."""

    # ------------------------------------------------------ puntos de extensión
    def _resolve(self, request: DownloadRequest, on_progress: ProgressCallback) -> ResolvedMedia:
        return ResolvedMedia(url=request.url.strip(), headers=dict(request.headers))

    def _analyze(
        self, request: DownloadRequest, on_progress: ProgressCallback
    ) -> tuple[ResolvedMedia, dict[str, Any]]:
        target = self._resolve(request, on_progress)
        return target, self._probe(target, request.allow_playlist)

    # ------------------------------------------------------------- API pública
    def download(
        self,
        request: DownloadRequest,
        on_progress: ProgressCallback,
        cancel_event: threading.Event | None = None,
        pause_event: threading.Event | None = None,
    ) -> DownloadResult:
        cancel_event = cancel_event or threading.Event()
        url = request.url.strip()
        if not self.can_handle(url):
            raise InvalidURLError(f"El enlace no es compatible con la fuente {self.name}.")

        ffmpeg = require_ffmpeg()
        check_connection(url)
        try:
            request.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DownloaderError(
                f"No se puede escribir en la carpeta de destino:\n{request.output_dir}", detail=str(exc)
            ) from exc

        log.info(
            "Descarga iniciada | fuente=%s tipo=%s calidad=%s subtítulos=%s url=%s",
            self.name, request.download_type.name, request.quality or "máx",
            ",".join(request.subtitle_langs) if request.subtitles else "no", url,
        )
        on_progress(ProgressInfo(stage=DownloadStage.ANALYZING, message="Analizando enlace…"))
        target, info = self._analyze(request, on_progress)
        if target.url != url:
            log.info("Enlace resuelto (%s): %s", target.source, target.url)
        if cancel_event.is_set():
            raise DownloadCancelledError()

        is_playlist = info.get("_type") == "playlist"
        item_count = len(info.get("entries") or []) if is_playlist else 1
        if is_playlist:
            on_progress(ProgressInfo(
                stage=DownloadStage.ANALYZING, title=info.get("title") or "",
                message=f"Lista detectada: {item_count} elementos", item_count=item_count,
            ))

        logger = YdlLogger()
        title_hint = None if is_playlist else (request.filename or target.title)
        ffprobe = find_ffprobe(ffmpeg)
        expect_video = request.download_type.is_video
        tracker = ProgressTracker(
            on_progress, cancel_event, item_count, title_hint, pause_event,
            validator=lambda path, expected: validate_media(path, expect_video, ffprobe, expected),
        )
        options = self._build_options(request, target, ffmpeg, is_playlist, logger, tracker)

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([target.url])
        except DownloadCancelled as exc:
            log.info("Descarga cancelada por el usuario")
            raise DownloadCancelledError() from exc
        except DownloadError as exc:
            error = translate_error(str(exc))
            if isinstance(error, ProcessingError):
                tracker.discard_unreadable_downloads()
            raise self._failure(error) from exc

        failed = logger.errors + tracker.corrupt
        if not tracker.completed:
            if tracker.corrupt:
                raise self._failure(CorruptFileError(detail="; ".join(tracker.corrupt)))
            if logger.errors:
                raise self._failure(translate_error(logger.errors[0]))
            raise self._failure(DownloaderError("No se encontró contenido descargable en el enlace."))

        log.info("Descarga completada: %d archivo(s), %d error(es)", len(tracker.completed), len(failed))
        return DownloadResult(output_dir=request.output_dir, completed=tracker.completed, failed=failed)

    @staticmethod
    def _failure(error: DownloaderError) -> DownloaderError:
        """Registra la causa completa en media_downloader.log antes de propagar el error."""
        log.error("Descarga fallida [%s]: %s | detalle: %s",
                  type(error).__name__, str(error).replace("\n", " "), error.detail or "-")
        return error

    def list_qualities(self, request: DownloadRequest) -> list[QualityOption]:
        url = request.url.strip()
        if not self.can_handle(url):
            raise InvalidURLError(f"El enlace no es compatible con la fuente {self.name}.")
        check_connection(url)
        _target, info = self._analyze(request, lambda _p: None)
        if info.get("_type") == "playlist":
            return []   # cada elemento puede tener calidades distintas
        return qualities_from_info(info)

    # ---------------------------------------------------------------- internos
    def _base_options(self, logger: YdlLogger, headers: dict[str, str] | None = None) -> dict[str, Any]:
        options: dict[str, Any] = {
            "logger": logger,
            "quiet": True,
            "no_warnings": False,
            "noprogress": True,
            # Robustez frente a cortes de red (evita "Giving up after N retries"):
            "socket_timeout": 30,
            "retries": 20,              # peticiones HTTP (archivos directos, manifiestos)
            "fragment_retries": 20,     # cada segmento HLS/DASH
            "extractor_retries": 5,
            "file_access_retries": 5,
            "retry_sleep_functions": {
                kind: _retry_backoff for kind in ("http", "fragment", "extractor")
            },
        }
        if headers:
            # yt-dlp las combina con sus cabeceras por defecto y las usa en TODAS las
            # peticiones: página, manifiesto M3U8, segmentos .ts y claves AES-128.
            options["http_headers"] = headers
        runtime = find_js_runtime()
        if runtime:
            options["js_runtimes"] = {runtime: {}}
        return options

    def _probe(self, target: ResolvedMedia, allow_playlist: bool) -> dict[str, Any]:
        """Extracción sin descargar: valida el enlace, detecta listas y calidades."""
        options = self._base_options(YdlLogger(), target.headers) | {
            "skip_download": True,
            "extract_flat": "in_playlist",
            "noplaylist": not allow_playlist,
        }
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(target.url, download=False)
        except DownloadError as exc:
            raise translate_error(str(exc)) from exc
        if not info:
            raise InvalidURLError("No se encontró ningún video en ese enlace.")
        return info

    def _output_template(self, request: DownloadRequest, target: ResolvedMedia, is_playlist: bool) -> Path:
        out = request.output_dir
        if is_playlist:
            return out / "%(playlist_title)s" / "%(playlist_index)03d - %(title)s.%(ext)s"
        name = request.filename or target.title
        stem = literal_for_template(name) if name and name.strip() else "%(title)s"
        return out / f"{stem}.%(ext)s"

    def _build_options(
        self,
        request: DownloadRequest,
        target: ResolvedMedia,
        ffmpeg: Path,
        is_playlist: bool,
        logger: YdlLogger,
        tracker: ProgressTracker,
    ) -> dict[str, Any]:
        options = self._base_options(logger, target.headers) | {
            "outtmpl": str(self._output_template(request, target, is_playlist)),
            "ffmpeg_location": str(ffmpeg.parent),
            "noplaylist": not request.allow_playlist,
            "ignoreerrors": self._ignoreerrors(request, is_playlist),
            "windowsfilenames": True,
            "overwrites": False,
            # Reanuda archivos .part y segmentos ya descargados (tras pausa, corte o reinicio).
            "continuedl": True,
            # Si un segmento HLS/DASH falla tras todos los reintentos, se aborta en lugar de
            # saltarlo: así FFmpeg solo une el video cuando están el 100 % de los segmentos
            # (por defecto yt-dlp los omite y el video final queda con cortes).
            "skip_unavailable_fragments": False,
            # Hilos en paralelo para los segmentos HLS/DASH (elegible en Opciones avanzadas).
            "concurrent_fragment_downloads": max(1, request.concurrent_fragments),
            "progress_hooks": [tracker.on_download],
            "postprocessor_hooks": [tracker.on_postprocess],
            "post_hooks": [tracker.on_file_done],
        }
        options.update(format_options(request.download_type, request.quality))

        if request.subtitles and request.download_type.is_video:
            options.update(subtitle_options(request.subtitle_langs))
            postprocessors = options["postprocessors"]
            # Antes de descargar el video: VTT → SRT. Tras el remux a MP4 (índice 0):
            # incrustar como pista mov_text, conservando el .srt junto al archivo.
            postprocessors.insert(0, {"key": "FFmpegSubtitlesConvertor", "format": "srt", "when": "before_dl"})
            postprocessors.insert(2, {"key": "FFmpegEmbedSubtitle", "already_have_subtitle": True})
        return options

    @staticmethod
    def _ignoreerrors(request: DownloadRequest, is_playlist: bool) -> bool | str:
        if request.subtitles:
            # Sin True, yt-dlp aborta el video entero si falla un subtítulo (p. ej. un 429 de
            # YouTube). Con True solo emite un aviso; los errores reales del video siguen
            # llegando a YdlLogger.errors y download() los convierte en excepción.
            return True
        # En listas, un video no disponible no debe abortar el resto.
        return "only_download" if is_playlist else False
