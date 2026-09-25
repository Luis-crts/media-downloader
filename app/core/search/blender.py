"""Películas abiertas de la Fundación Blender / Blender Studio.

Elephants Dream, Big Buck Bunny, Sintel, Tears of Steel, Cosmos Laundromat, Spring,
Sprite Fright, Charge… Todas con licencia Creative Commons (casi siempre CC BY).

Blender Studio no ofrece una API de catálogo, así que el listado se obtiene de la
categoría «Blender movies» de Wikimedia Commons, donde están subidas con su licencia
revisada: al publicarse una película nueva en esa categoría aparece sola. Se añaden las
copias de ``download.blender.org`` que siguen disponibles (más ligeras que los originales
4K de Commons).

La búsqueda es local sobre ese catálogo: «blender» (o «todas») lo muestra entero; otro
texto filtra por título.
"""
from __future__ import annotations

import logging
import re
import unicodedata

from app.core.base import DownloadType
from app.core.search.base import (
    BaseSearchProvider,
    LanguageFilter,
    SearchError,
    SearchQuery,
    SearchResult,
    register_search_provider,
)
from app.core.search.commons import CommonsClient, file_title_to_name, make_title_cleaner, page_to_results

log = logging.getLogger(__name__)

CATEGORIES = ("Category:Blender movies", "Category:Sintel (complete video)")
SHOW_ALL = {"blender", "todas", "todo", "todos", "all", "*", "open movie", "open movies", "peliculas abiertas"}

clean_title = make_title_cleaner((
    r"\s*[-–]\s*Blender Open Movie(-full movie)?",
    r"\s*[-–]\s*Open Movie by Blender Studio",
    r"\s*[-–]\s*Official Blender Foundation release",
    r"\s*[-–]\s*Blender Foundation's new Open Movie",
    r"\s*[-–,]\s*Blender Fo(u)?ndation",
    r"\s*[-–]\s*Short Movie",
    r"\s+in 4k\b", r"\s+4K\b", r"\s+movie\b", r"\s*\(\d{4}\)", r"\s+\d{3,4}p\d*",
))

# Año de estreno de las películas conocidas (el de Commons es a veces el de la subida).
KNOWN_YEARS = {
    "elephants dream": 2006, "big buck bunny": 2008, "sintel": 2010, "tears of steel": 2012,
    "caminandes llama drama": 2013, "caminandes gran dillama": 2014, "cosmos laundromat": 2015,
    "glass half": 2015, "hero": 2018, "spring": 2019, "coffee run": 2020, "sprite fright": 2021,
    "charge": 2022, "wing it": 2023,
}

# Copias en los servidores de Blender (verificadas: HTTP 200 y tamaño).
BLENDER_ORG_DOWNLOADS = {
    "sintel": ("https://download.blender.org/durian/movies/Sintel.2010.1080p.mkv",
               "1080p · MKV · blender.org", 1180090590),
    "tears of steel": ("https://download.blender.org/demo/movies/ToS/tears_of_steel_720p.mov",
                       "720p · MOV · blender.org", 372178639),
}


def title_key(title: str) -> str:
    """Clave para comparar títulos: minúsculas, sin tildes ni signos («WING IT!» → «wing it»)."""
    folded = unicodedata.normalize("NFKD", title.lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


@register_search_provider
class BlenderOpenMoviesProvider(BaseSearchProvider):
    name = "Blender Studio"
    description = "películas abiertas de la Fundación Blender (Creative Commons)"

    def __init__(self, client: CommonsClient | None = None) -> None:
        self.client = client or CommonsClient()

    def search(self, query: SearchQuery) -> list[SearchResult]:
        text = title_key(query.text)
        if not text:
            raise SearchError("Escribe un título o «blender» para ver todo el catálogo.")
        films = self._catalog()
        if text not in SHOW_ALL:
            words = [w for w in text.split() if len(w) > 2] or text.split()
            films = [f for f in films if all(w in f[0] for w in words)]

        results: list[SearchResult] = []
        for rank, (key, title, page) in enumerate(films):
            rows = page_to_results(page, self.name, rank, title=title, year=KNOWN_YEARS.get(key))
            extra = BLENDER_ORG_DOWNLOADS.get(key)
            if extra:
                url, quality, size = extra
                base = rows[0]
                rows.append(SearchResult(
                    provider=self.name, id=f"{key}:blender.org", title=title, page_url=base.page_url,
                    download_url=url, download_type=DownloadType.WEB_VIDEO, year=base.year,
                    quality=quality, size_bytes=size, license=base.license,
                    subtitle_languages=base.subtitle_languages, duration=base.duration,
                    filename=f"{title} (blender.org)", rank=rank,
                ))
            results.extend(rows)
        if query.language is not LanguageFilter.ALL:
            # Blender no tiene doblajes: el filtro de idioma se aplica a los subtítulos.
            results = [r for r in results if r.has_language(query.language.value)]
        log.info("Blender: %d fila(s) de %d película(s) para %r", len(results), len(films), query.text)
        return results

    def _catalog(self) -> list[tuple[str, str, dict]]:
        """(clave, título limpio, página) sin duplicados, ordenado por año."""
        best: dict[str, tuple[str, dict]] = {}
        for category in CATEGORIES:
            pages = self.client.video_pages(generator="categorymembers", gcmtitle=category,
                                            gcmtype="file", gcmlimit=200)
            for page in pages:
                title = clean_title(file_title_to_name(page["title"]))
                key = title_key(title)
                info = page["videoinfo"][0]
                score = (int(info.get("height") or 0), int(info.get("size") or 0))
                current = best.get(key)
                if current is None or score > self._score(current[1]):
                    best[key] = (title, page)
        films = [(key, title, page) for key, (title, page) in best.items()]
        return sorted(films, key=lambda f: (KNOWN_YEARS.get(f[0], 9999), f[1]))

    @staticmethod
    def _score(page: dict) -> tuple[int, int]:
        info = page["videoinfo"][0]
        return int(info.get("height") or 0), int(info.get("size") or 0)
