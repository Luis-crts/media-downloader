"""Wikimedia Commons: videos de dominio público o con licencia libre.

Commons solo admite contenido libre (es su política y se revisa), así que todo lo que
devuelve se puede descargar y compartir respetando la licencia indicada (normalmente,
citando al autor).

API pública (sin clave): https://commons.wikimedia.org/w/api.php
- ``generator=search`` con ``filetype:video`` para buscar,
- ``prop=videoinfo`` para URL, tamaño, resolución, duración, licencia y *transcodes*,
- ``prop=categories`` filtrado a «Files with closed captioning in …» para saber en qué
  idiomas hay subtítulos (Commons no registra el idioma del audio).

Cada video da varias filas, una por calidad: el original y, si existen, las versiones
recodificadas por Commons a 1080p y 480p (WebM VP9), mucho más ligeras que un original 4K.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from app import __version__
from app.core.base import DownloadType
from app.core.search.base import (
    BaseSearchProvider,
    LanguageFilter,
    SearchError,
    SearchQuery,
    SearchResult,
    register_search_provider,
)

log = logging.getLogger(__name__)

API_URL = "https://commons.wikimedia.org/w/api.php"
FILE_PAGE_URL = "https://commons.wikimedia.org/wiki/{title}"
# Wikimedia exige un User-Agent que identifique la aplicación y una forma de contacto.
USER_AGENT = f"MediaDownloader/{__version__} (https://github.com/Luis-crts/media-downloader)"
TIMEOUT = 25

# Categorías de subtítulos → nombre legible (las más habituales).
CAPTION_CATEGORY = "Category:Files with closed captioning in {}"
CAPTION_LANGUAGES = {
    "Spanish": "Español", "English": "Inglés", "French": "Francés", "German": "Alemán",
    "Italian": "Italiano", "Portuguese": "Portugués", "Brazilian Portuguese": "Portugués",
    "Japanese": "Japonés", "Russian": "Ruso", "Chinese": "Chino", "Arabic": "Árabe",
    "Dutch": "Neerlandés", "Polish": "Polaco", "Korean": "Coreano",
}
LANGUAGE_CAPTIONS = {LanguageFilter.SPANISH: "Spanish", LanguageFilter.ENGLISH: "English"}
# Versiones recodificadas que se ofrecen además del original (si son más pequeñas).
TRANSCODES = ("1080p.vp9.webm", "480p.vp9.webm")
MIME_LABELS = {"video/webm": "WebM", "application/ogg": "OGV", "video/ogg": "OGV", "video/mp4": "MP4",
               "video/mpeg": "MPEG", "video/quicktime": "MOV"}
_YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_SEARCH_UNSAFE = re.compile(r'[":]')   # evita inyectar operadores (incategory:, insource:…)


def clean_url(url: str) -> str:
    """URL sin los parámetros de seguimiento (utm_*) que añade la API."""
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(parts._replace(query="", fragment=""))


def file_title_to_name(title: str) -> str:
    """«File:Nosferatu (1922).webm» → «Nosferatu (1922)»."""
    name = title.split(":", 1)[-1]
    name = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", name)
    return name.replace("_", " ").strip()


def resolution_label(width: int, height: int) -> str:
    """Etiqueta por anchura, como se suele nombrar: una película panorámica de 1920×818
    es «1080p», no «818p»; 3840 o más de ancho es «4K»."""
    for min_width, label in ((3800, "4K"), (2500, "1440p"), (1900, "1080p"), (1260, "720p"), (840, "480p")):
        if width >= min_width:
            return label
    return f"{height}p" if height else ""


def format_minutes(seconds: float | None) -> str:
    if not seconds:
        return ""
    minutes = round(seconds / 60)
    return f"{minutes} min" if minutes >= 1 else f"{round(seconds)} s"


class CommonsClient:
    """Acceso mínimo a la API de Commons (compartido por varios proveedores)."""

    VIDEO_PROPS = {
        "prop": "videoinfo|categories",
        "viprop": "url|size|dimensions|mime|derivatives|extmetadata",
        "viextmetadatafilter": "LicenseShortName|DateTimeOriginal",
        "clcategories": "|".join(CAPTION_CATEGORY.format(lang) for lang in CAPTION_LANGUAGES),
        "cllimit": "max",
    }

    def query(self, **params: Any) -> dict:
        params.update(action="query", format="json", formatversion="2")
        url = f"{API_URL}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
                data = json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise SearchError(
                "No se pudo consultar Wikimedia Commons. Revisa tu conexión e inténtalo de nuevo.",
                detail=str(exc),
            ) from exc
        if "error" in data:
            raise SearchError("Wikimedia Commons rechazó la búsqueda.", detail=str(data["error"]))
        return data

    def video_pages(self, **generator: Any) -> list[dict]:
        """Páginas de archivo con la información de video, en el orden del generador."""
        data = self.query(**generator, **self.VIDEO_PROPS)
        pages = (data.get("query") or {}).get("pages") or []
        return sorted((p for p in pages if p.get("videoinfo")), key=lambda p: p.get("index", 0))


def subtitle_languages(page: dict) -> tuple[str, ...]:
    names = []
    for category in page.get("categories") or []:
        language = category["title"].rsplit(" in ", 1)[-1]
        name = CAPTION_LANGUAGES.get(language)
        if name and name not in names:
            names.append(name)
    # Español e inglés primero: son los del filtro.
    order = {"Español": 0, "Inglés": 1}
    return tuple(sorted(names, key=lambda n: order.get(n, 2)))


def page_to_results(
    page: dict,
    provider: str,
    rank: int,
    title: str | None = None,
    year: int | None = None,
    license_text: str | None = None,
) -> list[SearchResult]:
    """Una fila por calidad disponible del video (original + recodificaciones)."""
    info = page["videoinfo"][0]
    meta = info.get("extmetadata") or {}
    duration = float(info.get("duration") or 0) or None
    title = title or file_title_to_name(page["title"])
    if year is None:
        match = _YEAR.search(str((meta.get("DateTimeOriginal") or {}).get("value", "")))
        year = int(match.group(1)) if match else None
    license_text = license_text or str((meta.get("LicenseShortName") or {}).get("value", "")) or "Licencia libre"
    common = dict(
        provider=provider, title=title,
        page_url=FILE_PAGE_URL.format(title=urllib.parse.quote(page["title"].replace(" ", "_"))),
        download_type=DownloadType.WEB_VIDEO, year=year, license=license_text,
        subtitle_languages=subtitle_languages(page), duration=duration, rank=rank,
        # upload.wikimedia.org responde 403 a clientes que se presentan con un User-Agent de
        # navegador genérico: su política pide identificar la aplicación.
        headers={"User-Agent": USER_AGENT},
    )
    minutes = format_minutes(duration)
    original_height = int(info.get("height") or 0)
    original_label = resolution_label(int(info.get("width") or 0), original_height)
    fmt = MIME_LABELS.get(str(info.get("mime", "")).split(";")[0], "Video")

    results = [SearchResult(
        id=f"{page.get('pageid')}:original",
        download_url=clean_url(info["url"]),
        quality=" · ".join(filter(None, [original_label, fmt, "original", minutes])),
        size_bytes=int(info.get("size") or 0) or None,
        filename=title,
        **common,
    )]
    derivatives = {d.get("transcodekey"): d for d in info.get("derivatives") or [] if d.get("transcodekey")}
    for key in TRANSCODES:
        derivative = derivatives.get(key)
        height = int((derivative or {}).get("height") or 0)
        if not derivative or not height or height >= original_height:
            continue
        # Commons no da el tamaño de las recodificaciones: se estima con bitrate × duración.
        bandwidth = derivative.get("bandwidth")
        size = int(bandwidth * duration / 8) if bandwidth and duration else None
        results.append(SearchResult(
            id=f"{page.get('pageid')}:{key}",
            download_url=clean_url(derivative["src"]),
            quality=" · ".join(filter(None, [resolution_label(int(derivative.get("width") or 0), height), "WebM", minutes])),
            size_bytes=size,
            filename=f"{title} ({key.split('.')[0]})",
            **common,
        ))
    return results


@register_search_provider
class WikimediaCommonsSearchProvider(BaseSearchProvider):
    name = "Wikimedia Commons"
    description = "películas y documentales libres de commons.wikimedia.org"
    min_duration = 180          # s: deja fuera clips y tutoriales cortos

    def __init__(self, client: CommonsClient | None = None) -> None:
        self.client = client or CommonsClient()

    def search(self, query: SearchQuery) -> list[SearchResult]:
        text = _SEARCH_UNSAFE.sub(" ", query.text).strip()
        if not text:
            raise SearchError("Escribe el título o las palabras que quieres buscar.")
        search = f"filetype:video {text}"
        if query.language in LANGUAGE_CAPTIONS:
            search += f' incategory:"Files with closed captioning in {LANGUAGE_CAPTIONS[query.language]}"'
        pages = self.client.video_pages(generator="search", gsrnamespace=6, gsrsearch=search, gsrlimit=query.limit)
        results: list[SearchResult] = []
        for rank, page in enumerate(pages):
            duration = float(page["videoinfo"][0].get("duration") or 0)
            if duration < self.min_duration:
                continue
            results.extend(page_to_results(page, self.name, rank))
        log.info("Commons: %d fila(s) de %d video(s) para %r", len(results), len(pages), text)
        return results


def make_title_cleaner(patterns: tuple[str, ...]) -> Callable[[str], str]:
    regex = re.compile("|".join(patterns), re.IGNORECASE)
    return lambda name: re.sub(r"\s{2,}", " ", regex.sub("", name)).strip(" -–,")
