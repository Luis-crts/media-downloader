"""Internet Archive (archive.org): películas de dominio público o con licencia libre.

Usa la API pública (sin clave):
- ``advancedsearch.php`` para buscar,
- ``/metadata/<id>`` para conocer los archivos de cada película (formato, resolución,
  tamaño) y elegir la mejor versión.

Qué se considera «legal» (``LEGAL_SCOPE``): películas de la colección ``feature_films`` que
declaran una licencia abierta (Creative Commons o marca de dominio público) y las de las
colecciones de dominio público que mantiene el propio Archive (cine mudo, negro, ciencia
ficción y terror, comedia, dibujos clásicos, Prelinger). La licencia la declara quien sube
el contenido: cada resultado la muestra para que el usuario pueda comprobarla.

Cada película de Archive contiene varias copias del mismo video (MP4, MP4 de 512 kb, OGV…)
y su torrent las incluye todas. El resultado indica solo la mejor versión (y sus
subtítulos) en ``files``; el motor P2P descarga únicamente esos archivos.

Los torrents de Archive se sirven sobre todo desde sus servidores (web seeds), pero sus URL
(``archive.org/download/``) redirigen al servidor que guarda el ítem, y libtorrent no puede
completar tras una redirección las piezas que comparte el archivo elegido con los vecinos:
la descarga se quedaba en ~94 %. Por eso cada resultado añade como ``web_seeds`` las URL
directas de esos servidores (``server``/``d1``/``d2`` + ``dir`` de los metadatos).
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app import __version__
from app.core.base import DownloadType
from app.core.search.base import (
    BaseSearchProvider,
    LanguageFilter,
    SearchError,
    SearchQuery,
    SearchResult,
    normalize_language,
    register_search_provider,
)

log = logging.getLogger(__name__)

SEARCH_URL = "https://archive.org/advancedsearch.php"
METADATA_URL = "https://archive.org/metadata/{id}"
DOWNLOAD_URL = "https://archive.org/download/{id}/{name}"
DETAILS_URL = "https://archive.org/details/{id}"
USER_AGENT = f"MediaDownloader/{__version__} (+https://github.com/Luis-crts/media-downloader)"
TIMEOUT = 20

OPEN_LICENSE = "(licenseurl:*creativecommons.org* OR licenseurl:*publicdomain*)"
CURATED_COLLECTIONS = (
    "silent_films", "Film_Noir", "SciFi_Horror", "comedy_films", "classic_cartoons", "prelinger",
)
LEGAL_SCOPE = (
    f"mediatype:movies AND ((collection:feature_films AND {OPEN_LICENSE}) "
    f"OR collection:({' OR '.join(CURATED_COLLECTIONS)}))"
)
# Archive mezcla códigos ISO («spa») y nombres («Spanish»).
LANGUAGE_QUERIES = {
    LanguageFilter.SPANISH: "language:(spa OR spanish OR español OR castellano)",
    LanguageFilter.ENGLISH: "language:(eng OR english)",
}
SEARCH_FIELDS = ("identifier", "title", "year", "date", "language", "downloads", "item_size", "licenseurl")

# Formatos de video de Archive: (familia, preferencia). Primero la familia —MP4/MKV se
# reproducen en cualquier dispositivo; MPEG2 (VOB de DVD, varios GB) u OGV no—, después la
# resolución y, a igualdad, la preferencia dentro de la familia.
VIDEO_FORMAT_RANK = {
    "h.264 HD": (2, 3), "h.264": (2, 2), "h.264 IA": (2, 2), "MPEG4": (2, 1), "Matroska": (2, 1),
    "512Kb MPEG4": (2, 0), "MPEG2": (1, 1), "QuickTime": (1, 1), "Ogg Video": (1, 0),
    "Cinepack": (0, 0), "Windows Media": (0, 0),
}
SUBTITLE_EXTENSIONS = (".srt",)   # los .vtt de Archive son copias de los mismos subtítulos
_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')


def escape_query(text: str) -> str:
    """Escapa la sintaxis de Lucene: el texto del usuario se busca tal cual."""
    return _LUCENE_SPECIAL.sub(r"\\\1", text.strip())


def license_label(url: str) -> str:
    """URL de licencia → texto corto («CC BY-NC-ND 3.0», «Dominio público»…)."""
    lower = url.lower()
    if "publicdomain/zero" in lower:
        return "CC0 (dominio público)"
    if "publicdomain" in lower:
        return "Dominio público"
    match = re.search(r"creativecommons\.org/licenses/([a-z-]+)/([\d.]+)", lower)
    if match:
        return f"CC {match.group(1).upper()} {match.group(2)}"
    return "Licencia abierta" if lower else ""


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else value


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _int(value: Any) -> int | None:
    try:
        return int(float(str(_first(value)).strip()))
    except (TypeError, ValueError):
        return None


_PART_TOKEN = re.compile(r"(?:part|parte|pt|reel|rollo|cd|disc|disco)[\s_.-]*\d+|\d+\s*of\s*\d+", re.IGNORECASE)
_HEIGHT_IN_NAME = re.compile(r"(?<!\d)(\d{3,4})p(?![a-z])", re.IGNORECASE)


def _part_pattern(name: str) -> str:
    """Nombre sin el número de parte: «x-1of5.mp4» y «x-2of5.mp4» → «x-#.mp4».

    Solo cuentan marcas explícitas de parte; «_720p» y «_1080p» son resoluciones distintas
    de la misma película, no partes.
    """
    return _PART_TOKEN.sub("#", name.lower())


def _height(f: dict) -> int:
    """Alto en píxeles: de los metadatos o, si faltan, del nombre («…_1080p.mp4»)."""
    height = _int(f.get("height"))
    if height:
        return height
    match = _HEIGHT_IN_NAME.search(f.get("name", ""))
    return int(match.group(1)) if match else 0


def pick_files(files: list[dict]) -> tuple[list[dict], list[dict]]:
    """(videos de la mejor versión, subtítulos). Vacío si el ítem no tiene video.

    La mejor versión es la de mayor resolución y, a igualdad, la de mejor formato. Si la
    película está partida en varios archivos del mismo formato y origen (p. ej. rollos),
    se toman todos.
    """
    videos = [f for f in files if f.get("format") in VIDEO_FORMAT_RANK]
    if not videos:
        return [], []

    def key(f: dict) -> tuple:
        family, preference = VIDEO_FORMAT_RANK[f["format"]]
        return (family, _height(f), preference, _int(f.get("size")) or 0)

    best = max(videos, key=key)
    # Partes de la misma película: mismo formato y origen, y nombres que solo difieren en
    # números («Pelicula_parte1.mp4», «Pelicula_parte2.mp4»). Otras copias del mismo
    # formato (versiones distintas subidas al mismo ítem) no se incluyen.
    pattern = _part_pattern(best["name"])
    same_version = sorted(
        (f for f in videos
         if f.get("format") == best.get("format") and f.get("source") == best.get("source")
         and _part_pattern(f["name"]) == pattern),
        key=lambda f: f["name"],
    )
    subtitles = [f for f in files if f.get("name", "").lower().endswith(SUBTITLE_EXTENSIONS)]
    return same_version, subtitles


def direct_web_seeds(meta: dict | None) -> tuple[str, ...]:
    """URL base (sin redirección) de los servidores que guardan el ítem.

    Para un torrent multiarchivo, libtorrent pide ``<base><nombre del torrent>/<archivo>``;
    el torrent de Archive se llama como el ítem, así que la base es ``dir`` sin él.
    """
    if not meta or not meta.get("dir"):
        return ()
    base_dir = str(meta["dir"]).rsplit("/", 1)[0] + "/"
    hosts = dict.fromkeys(h for h in (meta.get("server"), meta.get("d1"), meta.get("d2")) if h)
    return tuple(f"https://{host}{base_dir}" for host in hosts)


@register_search_provider
class ArchiveOrgSearchProvider(BaseSearchProvider):
    name = "Internet Archive"
    description = "Películas de dominio público y con licencia libre (archive.org)"
    metadata_workers = 10

    def search(self, query: SearchQuery) -> list[SearchResult]:
        text = query.text.strip()
        if not text:
            raise SearchError("Escribe el título o las palabras que quieres buscar.")
        q = f"({escape_query(text)}) AND {LEGAL_SCOPE}"
        if query.language in LANGUAGE_QUERIES:
            q += f" AND {LANGUAGE_QUERIES[query.language]}"
        docs = self._search_docs(q, query.limit)
        log.info("Archive.org: %d resultado(s) para %r (idioma: %s)", len(docs), text, query.language.value)
        if not docs:
            return []

        with ThreadPoolExecutor(max_workers=self.metadata_workers) as pool:
            metadata = list(pool.map(self._metadata, (d["identifier"] for d in docs)))
        results = [
            result for rank, (doc, meta) in enumerate(zip(docs, metadata))
            if (result := self.build_result(doc, meta, rank)) is not None
        ]
        log.info("Archive.org: %d película(s) con video descargable", len(results))
        return results

    # ------------------------------------------------------------------ HTTP
    def _get_json(self, url: str) -> Any:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
            return json.load(response)

    def _search_docs(self, q: str, rows: int) -> list[dict]:
        params = [("q", q), ("rows", str(rows)), ("page", "1"), ("output", "json")]
        params += [("fl[]", f) for f in SEARCH_FIELDS]
        try:
            data = self._get_json(f"{SEARCH_URL}?{urllib.parse.urlencode(params)}")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise SearchError(
                "No se pudo consultar Internet Archive. Revisa tu conexión e inténtalo de nuevo.",
                detail=str(exc),
            ) from exc
        if "error" in data:
            raise SearchError("Internet Archive rechazó la búsqueda.", detail=str(data["error"]))
        return (data.get("response") or {}).get("docs") or []

    def _metadata(self, identifier: str) -> dict | None:
        try:
            return self._get_json(METADATA_URL.format(id=urllib.parse.quote(identifier)))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            log.warning("Archive.org: sin metadatos para %s", identifier, exc_info=True)
            return None

    # ------------------------------------------------------------- resultado
    @staticmethod
    def build_result(doc: dict, meta: dict | None, rank: int) -> SearchResult | None:
        """Un resultado a partir de la búsqueda y los metadatos. None si no hay video."""
        identifier = doc["identifier"]
        files = (meta or {}).get("files") or []
        item_meta = (meta or {}).get("metadata") or {}
        videos, subtitles = pick_files(files)
        if meta is not None and not videos:
            return None

        languages = []
        # El índice de búsqueda y los metadatos del ítem no siempre coinciden: se unen ambos.
        for raw in _as_list(doc.get("language")) + _as_list(item_meta.get("language")):
            name = normalize_language(str(raw))
            if name and name not in languages:
                languages.append(name)
        year = _int(doc.get("year")) or _int(str(_first(doc.get("date")) or "")[:4])
        license_url = str(_first(doc.get("licenseurl")) or _first(item_meta.get("licenseurl")) or "")
        license_text = license_label(license_url) or "Dominio público (colección curada de Archive)"

        has_torrent = any(f.get("format") == "Archive BitTorrent" for f in files)
        selected = videos + subtitles
        if videos:
            best = videos[0]
            height = _height(best)
            quality = f"{height}p · {best['format']}" if height else best["format"]
            size = sum(_int(f.get("size")) or 0 for f in selected) or None
        else:   # sin metadatos: se descargará el ítem completo
            quality, size = "—", _int(doc.get("item_size"))

        if has_torrent or not videos:
            torrent = f"{identifier}_archive.torrent"
            download_url = DOWNLOAD_URL.format(id=urllib.parse.quote(identifier), name=urllib.parse.quote(torrent))
            download_type = DownloadType.TORRENT
            chosen = tuple(f["name"] for f in selected)
        else:   # sin torrent: descarga directa del mejor archivo
            download_url = DOWNLOAD_URL.format(id=urllib.parse.quote(identifier), name=urllib.parse.quote(videos[0]["name"]))
            download_type = DownloadType.WEB_VIDEO
            chosen = ()

        return SearchResult(
            provider=ArchiveOrgSearchProvider.name,
            id=identifier,
            title=str(_first(doc.get("title")) or identifier),
            page_url=DETAILS_URL.format(id=urllib.parse.quote(identifier)),
            download_url=download_url,
            download_type=download_type,
            year=year,
            quality=quality,
            languages=tuple(languages),
            size_bytes=size,
            popularity=_int(doc.get("downloads")),
            license=license_text,
            files=chosen,
            web_seeds=direct_web_seeds(meta) if download_type is DownloadType.TORRENT else (),
            rank=rank,
        )
