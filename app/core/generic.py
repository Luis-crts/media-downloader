"""Proveedor genérico: M3U8/HLS, DASH, enlaces directos y páginas web con reproductor.

Para HLS, yt-dlp descarga los segmentos ``.ts``/``.m4s`` en paralelo (con las
cabeceras indicadas, también para las claves AES-128) y FFmpeg los une en un MP4
sin recodificar. Se registra el último: actúa como respaldo para cualquier URL
http(s) que no reconozca un proveedor específico (YouTube…).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from app.core.base import (
    DownloadRequest,
    DownloadStage,
    DownloadType,
    InvalidURLError,
    ProgressCallback,
    ProgressInfo,
    ResolvedMedia,
    register_downloader,
)
from app.core.extractor import (
    find_resolver,
    is_direct_media,
    name_from_url,
    sniff_page,
    with_default_headers,
)
from app.core.ytdlp_backend import YtDlpDownloader

log = logging.getLogger(__name__)

_NOT_FOUND_HINT = (
    "No se encontró ningún video en la página.\n\n"
    "Si el video se reproduce en el navegador, puedes obtener el enlace del stream:\n"
    "1. Abre las herramientas de desarrollador (F12) → pestaña «Red».\n"
    "2. Reproduce el video y filtra por «m3u8» (o «mp4»).\n"
    "3. Copia esa URL y pégala aquí; pon la dirección de la página en «Referer»."
)


@register_downloader
class GenericDownloader(YtDlpDownloader):
    name = "Web / M3U8"
    supported_types = tuple(DownloadType)

    @classmethod
    def can_handle(cls, url: str) -> bool:
        parts = urlsplit(url.strip())
        return parts.scheme in ("http", "https") and bool(parts.hostname)

    # ------------------------------------------------------------------ #
    def _resolve(self, request: DownloadRequest, on_progress: ProgressCallback) -> ResolvedMedia:
        url = request.url.strip()
        headers = with_default_headers(request.headers)

        if is_direct_media(url):
            # «master.m3u8» no es un buen nombre: se usa el de la URL o una marca de tiempo.
            title = name_from_url(url) or f"video-{datetime.now():%Y%m%d-%H%M%S}"
            return ResolvedMedia(url=url, headers=headers, title=title, source="direct")

        resolver = find_resolver(url)
        if resolver:
            on_progress(ProgressInfo(
                stage=DownloadStage.ANALYZING, message=f"Resolviendo enlace de {resolver.name}…",
            ))
            return resolver.resolve(url, headers)

        return ResolvedMedia(url=url, headers=headers, source="page")

    def _analyze(
        self, request: DownloadRequest, on_progress: ProgressCallback
    ) -> tuple[ResolvedMedia, dict[str, Any]]:
        target = self._resolve(request, on_progress)
        try:
            return target, self._probe(target, request.allow_playlist)
        except InvalidURLError as exc:
            if target.source != "page":
                raise
            log.info("yt-dlp no reconoce %s; se analiza el HTML", target.url)
            on_progress(ProgressInfo(
                stage=DownloadStage.ANALYZING, message="Buscando el reproductor en la página…",
            ))
            found = sniff_page(target.url, target.headers)
            if not found:
                raise InvalidURLError(_NOT_FOUND_HINT, detail=exc.detail) from exc
            on_progress(ProgressInfo(
                stage=DownloadStage.ANALYZING, title=found.title or "",
                message="Video encontrado en la página; analizando stream…",
            ))
            try:
                return found, self._probe(found, request.allow_playlist)
            except InvalidURLError as inner:
                raise InvalidURLError(_NOT_FOUND_HINT, detail=inner.detail) from inner
