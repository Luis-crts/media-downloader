"""Contrato de los proveedores de búsqueda y registro.

Igual que los proveedores de descarga (``@register_downloader``): cada fuente hereda de
``BaseSearchProvider``, implementa ``search`` y se registra con
``@register_search_provider``. La interfaz solo conoce este contrato.

Cada resultado lleva ya preparada la ``DownloadRequest`` parcial que se añadirá a la cola
(URL, tipo de descarga y archivos concretos), así que la GUI no necesita saber de dónde
viene ni cómo se descarga.
"""
from __future__ import annotations

import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

from app.core.base import DownloadType


class LanguageFilter(Enum):
    ALL = "Todos"
    SPANISH = "Español"
    ENGLISH = "Inglés"


class SortOrder(Enum):
    RELEVANCE = "Relevancia"
    SIZE_ASC = "Menor peso"
    SIZE_DESC = "Mayor peso"
    POPULARITY = "Más populares"


@dataclass
class SearchResult:
    provider: str
    id: str
    title: str
    page_url: str                         # página del contenido (para verlo en el navegador)
    download_url: str                     # .torrent, magnet o enlace directo
    download_type: DownloadType
    year: int | None = None
    quality: str = ""                     # p. ej. "480p · h.264"
    languages: tuple[str, ...] = ()       # idioma del audio: ("Español", "Inglés")
    subtitle_languages: tuple[str, ...] = ()   # subtítulos disponibles en la fuente
    duration: float | None = None         # segundos
    size_bytes: int | None = None         # lo que se descargará (no el ítem completo)
    popularity: int | None = None         # descargas / visitas según la fuente
    license: str = ""                     # p. ej. "Dominio público", "CC BY-NC-ND 3.0"
    files: tuple[str, ...] = ()           # archivos concretos a descargar dentro del torrent
    web_seeds: tuple[str, ...] = ()       # servidores HTTP para el torrent (BEP 19)
    filename: str = ""                    # nombre del archivo en descargas directas
    headers: dict[str, str] = field(default_factory=dict)   # cabeceras HTTP para la descarga
    rank: int = 0                         # posición original (orden por relevancia)

    @property
    def language_label(self) -> str:
        parts = [", ".join(self.languages)] if self.languages else []
        if self.subtitle_languages:
            subs = ", ".join(self.subtitle_languages[:3])
            extra = len(self.subtitle_languages) - 3
            parts.append(f"subt.: {subs}" + (f" (+{extra})" if extra > 0 else ""))
        return " · ".join(parts) if parts else "—"

    def has_language(self, language: str) -> bool:
        """Audio o subtítulos en ese idioma."""
        return language in self.languages or language in self.subtitle_languages


@dataclass(frozen=True)
class SearchQuery:
    text: str
    language: LanguageFilter = LanguageFilter.ALL
    limit: int = 40
    extra: dict = field(default_factory=dict)


class SearchError(Exception):
    """Error de búsqueda con un mensaje listo para mostrar."""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


class BaseSearchProvider(ABC):
    name: str = "base"
    description: str = ""

    @abstractmethod
    def search(self, query: SearchQuery) -> list[SearchResult]:
        """Búsqueda bloqueante (llamar desde un hilo secundario). Lanza ``SearchError``."""


# --------------------------------------------------------------------------- #
# Registro
# --------------------------------------------------------------------------- #
_PROVIDERS: list[type[BaseSearchProvider]] = []


def register_search_provider(cls: type[BaseSearchProvider]) -> type[BaseSearchProvider]:
    _PROVIDERS.append(cls)
    return cls


def search_providers() -> list[str]:
    return [p.name for p in _PROVIDERS]


def get_search_provider(name: str | None = None) -> BaseSearchProvider:
    """El proveedor con ese nombre, o el primero registrado si no se indica."""
    if not _PROVIDERS:
        raise SearchError("No hay proveedores de búsqueda registrados.")
    if name is None:
        return _PROVIDERS[0]()
    for provider in _PROVIDERS:
        if provider.name == name:
            return provider()
    raise SearchError(f"Proveedor de búsqueda desconocido: {name}")


# --------------------------------------------------------------------------- #
# Utilidades comunes: idiomas y orden
# --------------------------------------------------------------------------- #
_LANGUAGE_NAMES = {
    "Español": ("spa", "es", "spanish", "espanol", "castellano", "latino"),
    "Inglés": ("eng", "en", "english"),
    "Francés": ("fre", "fra", "fr", "french", "frances"),
    "Alemán": ("ger", "deu", "de", "german", "aleman"),
    "Italiano": ("ita", "it", "italian"),
    "Portugués": ("por", "pt", "portuguese", "portugues"),
    "Japonés": ("jpn", "ja", "japanese", "japones"),
    "Ruso": ("rus", "ru", "russian", "ruso"),
}
_LANGUAGE_BY_CODE = {code: name for name, codes in _LANGUAGE_NAMES.items() for code in codes}


def _fold(text: str) -> str:
    """Minúsculas y sin tildes (para comparar «Español» con «espanol»)."""
    normalized = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(c for c in normalized if not unicodedata.combining(c))


def normalize_language(value: str) -> str | None:
    """«spa», «Spanish», «español» → «Español». None si está vacío o es «None»."""
    folded = _fold(value)
    if not folded or folded in ("none", "n/a", "unknown", "und"):
        return None
    if folded in _LANGUAGE_BY_CODE:
        return _LANGUAGE_BY_CODE[folded]
    for code, name in _LANGUAGE_BY_CODE.items():
        if len(code) > 3 and folded.startswith(code):       # «english-handwritten»
            return name
    return value.strip().title()


def filter_by_language(results: list[SearchResult], language: LanguageFilter) -> list[SearchResult]:
    if language is LanguageFilter.ALL:
        return list(results)
    return [r for r in results if r.has_language(language.value)]


def merge_results(per_source: list[list[SearchResult]]) -> list[SearchResult]:
    """Une los resultados de varias fuentes intercalándolos por relevancia: primero el
    mejor de cada fuente, después el segundo… (``rank`` se reescribe para ello).

    Si dos fuentes devuelven el mismo archivo (p. ej. una película de Blender que está en
    Wikimedia Commons), se conserva el de la fuente registrada después, que es la más
    específica y suele tener mejores datos (título limpio, año de estreno).
    """
    by_url: dict[str, SearchResult] = {}
    for index, results in enumerate(per_source):
        for result in results:
            result.rank = result.rank * len(per_source) + index
            by_url[result.download_url] = result
    return sorted(by_url.values(), key=lambda r: r.rank)


def sort_results(results: list[SearchResult], order: SortOrder) -> list[SearchResult]:
    """Orden en el cliente; los tamaños desconocidos van siempre al final."""
    if order is SortOrder.SIZE_ASC:
        return sorted(results, key=lambda r: (r.size_bytes is None, r.size_bytes or 0))
    if order is SortOrder.SIZE_DESC:
        return sorted(results, key=lambda r: (r.size_bytes is None, -(r.size_bytes or 0)))
    if order is SortOrder.POPULARITY:
        return sorted(results, key=lambda r: -(r.popularity or 0))
    return sorted(results, key=lambda r: r.rank)
