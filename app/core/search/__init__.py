"""Búsqueda de contenido en fuentes legales.

Añadir una fuente: crea un módulo aquí, hereda de ``BaseSearchProvider``, implementa
``search`` (devolviendo ``SearchResult`` con la URL y el tipo de descarga) y decora la clase
con ``@register_search_provider``; después impórtala abajo. La GUI la mostrará sola.
"""
from app.core.search.base import (
    BaseSearchProvider,
    LanguageFilter,
    SearchError,
    SearchQuery,
    SearchResult,
    SortOrder,
    filter_by_language,
    get_search_provider,
    normalize_language,
    register_search_provider,
    search_providers,
    sort_results,
)

# Importar los proveedores los registra (el primero es el predeterminado).
from app.core.search import archive_org  # noqa: F401,E402

__all__ = [
    "BaseSearchProvider", "LanguageFilter", "SearchError", "SearchQuery", "SearchResult", "SortOrder",
    "filter_by_language", "get_search_provider", "normalize_language", "register_search_provider",
    "search_providers", "sort_results",
]
