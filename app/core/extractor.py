"""Resolución de enlaces web: de «página con reproductor» a «URL de video descargable».

Tres niveles, del más específico al más general:

1. **Resolvers por sitio** (``SiteResolver`` + ``@register_resolver``): lógica a
   medida para un servidor de video concreto. Se ejecutan *antes* que yt-dlp.
2. **yt-dlp** (lo hace ``GenericDownloader``): reconoce más de 1800 sitios y su
   extractor genérico detecta reproductores HTML5/JWPlayer/embeds comunes.
3. **Sniffer** (``sniff_page``): plan B si yt-dlp no reconoce la página. Busca en el
   HTML (y en iframes y JavaScript empaquetado) URLs ``.m3u8``/``.mp4``/``.mpd``.

Añadir un resolver
------------------
::

    from app.core.base import ResolvedMedia
    from app.core.extractor import SiteResolver, register_resolver, fetch_page

    @register_resolver
    class MiServidorResolver(SiteResolver):
        name = "MiServidor"
        domains = ("miservidor.example", "cdn.miservidor.example")

        def resolve(self, url: str, headers: dict[str, str]) -> ResolvedMedia:
            page = fetch_page(url, headers)
            match = re.search(r'"hls"\\s*:\\s*"([^"]+)"', page.text)
            if not match:
                raise InvalidURLError("MiServidor: no se encontró el video.")
            return ResolvedMedia(
                url=match.group(1),
                headers=with_referer(headers, page.url),   # muchos CDN exigen el Referer
                title=page_title(page.text),
                source=f"resolver:{self.name}",
            )

Importa el módulo en ``app/core/__init__.py`` (o colócalo en ``app/core/resolvers/``)
para que se registre. Los resolvers solo deben usarse con contenido que tengas
derecho a descargar; esta aplicación no elude DRM ni otros sistemas anticopia.
"""
from __future__ import annotations

import html as html_lib
import logging
import re
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from app.core.base import AccessDeniedError, DownloaderError, NetworkError, ResolvedMedia

log = logging.getLogger(__name__)

MEDIA_EXTENSIONS = ("m3u8", "mpd", "mp4", "m4v", "webm", "mkv", "mov")
_MAX_PAGE_BYTES = 5 * 1024 * 1024
_FETCH_TIMEOUT = 20

_EXT = "|".join(MEDIA_EXTENSIONS)
# Cualquier cadena entre comillas que termine en una extensión de video (con query opcional).
_QUOTED_MEDIA = re.compile(
    rf"""["'](?P<url>[^"'\s<>]+?\.(?:{_EXT})(?:\?[^"'\s<>]*)?)["']""", re.IGNORECASE
)
# <video src>, <source src> (aunque la URL no tenga extensión).
_TAG_SRC = re.compile(
    r"""<(?:video|source)\b[^>]*?\ssrc\s*=\s*["'](?P<url>[^"']+)["']""", re.IGNORECASE
)
# Configuraciones de reproductores JS: JWPlayer (file:), Clappr/Video.js (source/src:), hls: …
_PLAYER_KEYS = re.compile(
    r"""["']?(?:file|source|src|hls|hlsUrl|hls_url|videoUrl|video_url|stream_url|m3u8)["']?"""
    r"""\s*[:=]\s*["'](?P<url>(?:https?:)?//[^"'\s]+)["']""",
    re.IGNORECASE,
)
_IFRAME = re.compile(
    r"""<iframe\b[^>]*?\s(?:data-)?src\s*=\s*["'](?P<url>[^"']+)["']""", re.IGNORECASE
)
_TITLE = re.compile(r"<title[^>]*>(?P<t>.*?)</title>", re.IGNORECASE | re.DOTALL)
_OG_TITLE = re.compile(
    r"""<meta[^>]+property=["']og:title["'][^>]+content=["'](?P<t>[^"']+)["']""", re.IGNORECASE
)
_NOT_MEDIA = re.compile(r"\.(?:jpe?g|png|gif|svg|webp|ico|css|js|vtt|srt|json|html?|php)(?:\?|$)", re.I)
_AD_HOSTS = ("doubleclick", "googlesyndication", "googletagmanager", "facebook.com/plugins", "disqus")
_GENERIC_STEMS = {"master", "index", "playlist", "chunklist", "manifest", "video", "stream", "prog_index"}


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
@dataclass
class PageResponse:
    url: str     # URL final tras redirecciones
    text: str


def default_user_agent() -> str:
    """User-Agent de navegador de escritorio que yt-dlp mantiene actualizado."""
    try:
        from yt_dlp.utils.networking import std_headers

        return std_headers["User-Agent"]
    except (ImportError, KeyError):
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        )


def with_default_headers(headers: dict[str, str] | None) -> dict[str, str]:
    merged = {k: v for k, v in (headers or {}).items() if v}
    merged.setdefault("User-Agent", default_user_agent())
    return merged


def with_referer(headers: dict[str, str], page_url: str, override: bool = False) -> dict[str, str]:
    """Añade Referer/Origin de la página donde está el reproductor.

    Con ``override=False`` se respetan los valores que ya puso el usuario; con
    ``override=True`` se reemplazan (como hace un navegador dentro de un iframe).
    """
    parts = urlsplit(page_url)
    result = dict(headers)
    if override:
        result.pop("Referer", None)
        result.pop("Origin", None)
    result.setdefault("Referer", page_url)
    result.setdefault("Origin", f"{parts.scheme}://{parts.netloc}")
    return result


def fetch_page(url: str, headers: dict[str, str], timeout: float = _FETCH_TIMEOUT) -> PageResponse:
    request = urllib.request.Request(url, headers=with_default_headers(headers))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read(_MAX_PAGE_BYTES)
            charset = response.headers.get_content_charset() or "utf-8"
            return PageResponse(url=response.geturl(), text=raw.decode(charset, errors="replace"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise AccessDeniedError(detail=f"{exc.code} {url}") from exc
        raise DownloaderError(f"La página respondió con error HTTP {exc.code}.", detail=url) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise NetworkError(detail=f"{url}: {exc}") from exc


# --------------------------------------------------------------------------- #
# Análisis de HTML
# --------------------------------------------------------------------------- #
def is_direct_media(url: str) -> bool:
    """True si la URL apunta directamente a un manifiesto o archivo de video."""
    last_segment = urlsplit(url).path.lower().rsplit("/", 1)[-1]
    return "." in last_segment and last_segment.rsplit(".", 1)[-1] in MEDIA_EXTENSIONS


def name_from_url(url: str) -> str | None:
    """Nombre legible a partir de la URL (``None`` si es genérico, como master.m3u8)."""
    stem = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if not stem or stem.lower() in _GENERIC_STEMS or len(stem) < 3:
        return None
    return urllib.request.unquote(stem).replace("_", " ").replace(".", " ").strip() or None


def page_title(text: str) -> str | None:
    match = _OG_TITLE.search(text) or _TITLE.search(text)
    if not match:
        return None
    title = html_lib.unescape(re.sub(r"\s+", " ", match.group("t"))).strip()
    return title[:150] or None


def _unpack_js(text: str) -> str:
    """Desempaqueta JavaScript ofuscado con el packer de Dean Edwards
    (``eval(function(p,a,c,k,e,d)…``), muy usado para esconder la URL del video."""
    marker = "eval(function(p,a,c,k,e,"
    if marker not in text:
        return ""
    try:
        from yt_dlp.utils import decode_packed_codes
    except ImportError:
        return ""
    decoded = []
    for match in re.finditer(re.escape(marker), text):
        try:
            decoded.append(decode_packed_codes(text[match.start():]))
        except Exception:  # bloque malformado: se ignora
            log.debug("No se pudo desempaquetar un bloque JS", exc_info=True)
    return "\n".join(decoded)


def _normalize(text: str) -> str:
    """Deshace los escapes de JSON/JS (``\\/``, ``\\"``) y las entidades HTML (``&amp;``)."""
    text = text.replace("\\/", "/").replace('\\"', '"').replace("\\'", "'")
    return html_lib.unescape(text)


def _media_rank(url: str) -> tuple[int, int]:
    lower = url.lower()
    if ".m3u8" in lower:
        kind = 0
    elif ".mpd" in lower:
        kind = 1
    elif re.search(r"\.(mp4|m4v|webm|mkv|mov)", lower):
        kind = 2
    else:
        kind = 3   # URL sin extensión (p. ej. <source src="/stream?id=…">)
    master = 0 if any(k in lower for k in ("master", "playlist", "index")) else 1
    return kind, master


def find_media_urls(text: str, base_url: str) -> list[str]:
    """URLs de video encontradas en el HTML/JS, ordenadas de mejor a peor candidata."""
    text = _normalize(text)
    text += "\n" + _normalize(_unpack_js(text))
    found: dict[str, None] = {}
    for pattern in (_QUOTED_MEDIA, _TAG_SRC, _PLAYER_KEYS):
        for match in pattern.finditer(text):
            candidate = match.group("url").strip()
            if candidate.startswith(("data:", "blob:", "javascript:")):
                continue
            absolute = urljoin(base_url, candidate)
            if urlsplit(absolute).scheme not in ("http", "https") or _NOT_MEDIA.search(absolute):
                continue
            found.setdefault(absolute)
    return sorted(found, key=_media_rank)


def find_iframes(text: str, base_url: str) -> list[str]:
    urls: dict[str, None] = {}
    for match in _IFRAME.finditer(_normalize(text)):
        absolute = urljoin(base_url, match.group("url").strip())
        if urlsplit(absolute).scheme in ("http", "https") and not any(a in absolute for a in _AD_HOSTS):
            urls.setdefault(absolute)
    return list(urls)


def sniff_page(url: str, headers: dict[str, str], max_depth: int = 2) -> ResolvedMedia | None:
    """Busca el video dentro de una página (y de sus iframes hasta ``max_depth`` niveles).

    Devuelve la mejor URL encontrada con el Referer/Origin de la página que la contiene
    (lo que enviaría un navegador), o ``None`` si no hay nada. Si solo hay iframes sin
    video visible, devuelve el primero para que yt-dlp lo intente (suele ser un
    reproductor de un sitio que sí reconoce).
    """
    page = fetch_page(url, headers)
    title = page_title(page.text)
    # Todo lo que cuelga de esta página (video o iframe) se pide con ella como Referer.
    referred = with_referer(headers, page.url, override=True)
    media = find_media_urls(page.text, page.url)
    if media:
        log.info("Sniffer: %d candidatos en %s; elegido %s", len(media), page.url, media[0])
        return ResolvedMedia(url=media[0], headers=referred, title=title, source="sniffer")

    iframes = find_iframes(page.text, page.url)
    if max_depth > 0:
        for iframe in iframes[:5]:
            try:
                found = sniff_page(iframe, referred, max_depth - 1)
            except DownloaderError:
                log.info("Sniffer: no se pudo abrir el iframe %s", iframe, exc_info=True)
                continue
            if found:
                # El título de la página principal suele ser el de la película;
                # el del iframe, el del reproductor.
                found.title = title or found.title
                return found
    if iframes:
        return ResolvedMedia(url=iframes[0], headers=referred, title=title, source="iframe")
    return None


# --------------------------------------------------------------------------- #
# Resolvers por sitio
# --------------------------------------------------------------------------- #
class SiteResolver(ABC):
    name: str = "resolver"
    domains: tuple[str, ...] = ()

    def matches(self, url: str) -> bool:
        host = (urlsplit(url).hostname or "").lower()
        return any(host == d or host.endswith(f".{d}") for d in self.domains)

    @abstractmethod
    def resolve(self, url: str, headers: dict[str, str]) -> ResolvedMedia:
        """Devuelve la URL de video final (m3u8/mp4) con las cabeceras necesarias."""


_RESOLVERS: list[SiteResolver] = []


def register_resolver(cls: type[SiteResolver]) -> type[SiteResolver]:
    _RESOLVERS.append(cls())
    return cls


def find_resolver(url: str) -> SiteResolver | None:
    return next((r for r in _RESOLVERS if r.matches(url)), None)


def registered_resolvers() -> list[str]:
    return [r.name for r in _RESOLVERS]
