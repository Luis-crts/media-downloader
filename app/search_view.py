"""Pestaña «Buscar películas»: búsqueda en fuentes legales y envío a la cola.

La búsqueda corre en un hilo secundario (puede tardar unos segundos: se consultan los
metadatos de cada resultado) y comunica el resultado por una cola que se consulta con
``after()``, igual que las descargas. Con «Todas» se consulta cada fuente registrada en
paralelo; si una falla, se muestran las demás. Los filtros de orden se aplican en local;
el de idioma repite la búsqueda en cada fuente para no perder resultados.
"""
from __future__ import annotations

import logging
import queue
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import customtkinter as ctk

from app.core.search import (
    LanguageFilter,
    SearchError,
    SearchQuery,
    SearchResult,
    SortOrder,
    get_search_provider,
    merge_results,
    search_providers,
    sort_results,
)
from app.widgets import shorten

log = logging.getLogger(__name__)

_MUTED = ("gray40", "gray65")
POLL_MS = 100
ALL_SOURCES = "Todas"
PER_SOURCE_LIMIT = 25        # con «Todas», resultados pedidos a cada fuente
COLUMNS = (   # (encabezado, ancho mínimo)
    ("Título", 240), ("Año", 50), ("Formato / calidad", 200), ("Idioma", 140),
    ("Tamaño", 80), ("Popularidad", 80), ("", 150),
)


def format_size(size: int | None) -> str:
    if not size:
        return "—"
    return f"{size / 1e9:.2f} GB" if size >= 1e9 else f"{size / 1e6:.0f} MB"


def format_count(count: int | None) -> str:
    if count is None:
        return "—"
    if count >= 1_000_000:
        return f"{count / 1e6:.1f} M"
    if count >= 1_000:
        return f"{count / 1e3:.0f} k"
    return str(count)


class SearchView(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_add: Callable[[SearchResult], bool],
        on_log: Callable[[str], None],
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._on_add = on_add
        self._on_log = on_log
        self._providers = {name: get_search_provider(name) for name in search_providers()}
        self._results: list[SearchResult] = []
        self._added: set[str] = set()
        self._events: queue.Queue[tuple[int, object]] = queue.Queue()
        self._token = 0             # identifica la búsqueda en curso (descarta respuestas viejas)
        self._counts: dict[str, int] = {}
        self._errors: dict[str, SearchError] = {}
        self._searching = False
        self._last_text = ""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)
        self._build()
        self.after(POLL_MS, self._poll)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 6))
        bar.grid_columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(bar, height=36, placeholder_text="Título, director, género… (p. ej. nosferatu, metropolis)")
        self.entry.grid(row=0, column=0, sticky="ew")
        self.entry.bind("<Return>", lambda _e: self.start_search())
        self.search_button = ctk.CTkButton(bar, text="Buscar", width=100, height=36, command=self.start_search)
        self.search_button.grid(row=0, column=1, padx=(8, 0))
        ctk.CTkLabel(
            bar, anchor="w", text_color=_MUTED,
            text="Solo contenido de dominio público o con licencia libre: "
                 + "; ".join(f"{p.name} ({p.description})" for p in self._providers.values())
                 + ". La licencia aparece bajo cada título: pulsa el título para ver su página.",
            wraplength=780, justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        sources = ctk.CTkFrame(self, fg_color="transparent")
        sources.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 6))
        ctk.CTkLabel(sources, text="Fuente").pack(side="left", padx=(0, 6))
        self.source = ctk.CTkSegmentedButton(
            sources, values=[ALL_SOURCES, *self._providers], command=self._on_filter_change,
        )
        self.source.set(ALL_SOURCES)
        self.source.pack(side="left")

        filters = ctk.CTkFrame(self, fg_color="transparent")
        filters.grid(row=2, column=0, sticky="ew", padx=4, pady=(0, 6))
        ctk.CTkLabel(filters, text="Ordenar").pack(side="left", padx=(0, 6))
        self.sort = ctk.CTkSegmentedButton(filters, values=[o.value for o in SortOrder], command=lambda _v: self._render())
        self.sort.set(SortOrder.RELEVANCE.value)
        self.sort.pack(side="left")
        ctk.CTkLabel(filters, text="Idioma").pack(side="left", padx=(18, 6))
        self.language = ctk.CTkSegmentedButton(
            filters, values=[l.value for l in LanguageFilter], command=self._on_filter_change,
        )
        self.language.set(LanguageFilter.ALL.value)
        self.language.pack(side="left")

        status = ctk.CTkFrame(self, fg_color="transparent")
        status.grid(row=3, column=0, sticky="ew", padx=4)
        status.grid_columnconfigure(1, weight=1)
        self.spinner = ctk.CTkProgressBar(status, mode="indeterminate", width=120, height=8)
        self.status = ctk.CTkLabel(status, text="Escribe qué buscar y pulsa «Buscar».", anchor="w", text_color=_MUTED)
        self.status.grid(row=0, column=1, sticky="ew", pady=(0, 4))

        self.table = ctk.CTkScrollableFrame(self, corner_radius=12)
        self.table.grid(row=4, column=0, sticky="nsew", padx=4, pady=(0, 4))
        for col, (_, minsize) in enumerate(COLUMNS):
            self.table.grid_columnconfigure(col, weight=1 if col == 0 else 0, minsize=minsize)

    # ------------------------------------------------------------- búsqueda
    def _on_filter_change(self, _value: str) -> None:
        """Fuente o idioma: se repite la búsqueda (el filtro lo aplica cada fuente)."""
        if self._last_text:
            self.start_search(self._last_text)

    def start_search(self, text: str | None = None) -> None:
        text = (text if text is not None else self.entry.get()).strip()
        if not text:
            self.status.configure(text="Escribe el título o las palabras que quieres buscar.")
            return
        self._last_text = text
        self._token += 1
        language = LanguageFilter(self.language.get())
        source = self.source.get()
        providers = list(self._providers.values()) if source == ALL_SOURCES else [self._providers[source]]
        query = SearchQuery(text=text, language=language)
        if len(providers) > 1:
            query = SearchQuery(text=text, language=language, limit=PER_SOURCE_LIMIT)
        names = ", ".join(p.name for p in providers)
        self._set_searching(True, f"Buscando opciones en {names}…")
        log.info("Búsqueda #%d: %r (fuentes: %s, idioma: %s)", self._token, text, names, language.value)
        threading.Thread(target=self._run, args=(self._token, providers, query), daemon=True, name="busqueda").start()

    def _run(self, token: int, providers: list, query: SearchQuery) -> None:
        """Hilo secundario: consulta las fuentes en paralelo. Nunca toca widgets."""
        def one(provider):
            try:
                return provider, provider.search(query), None
            except SearchError as exc:
                log.warning("Búsqueda fallida en %s: %s | %s", provider.name, exc, exc.detail)
                return provider, [], exc
            except Exception as exc:   # un fallo de una fuente no tumba las demás
                log.exception("Error inesperado en la búsqueda (%s)", provider.name)
                return provider, [], SearchError(f"Error inesperado: {exc}")

        with ThreadPoolExecutor(max_workers=len(providers)) as pool:
            outcomes = list(pool.map(one, providers))
        counts = {provider.name: len(results) for provider, results, _ in outcomes}
        errors = {provider.name: error for provider, _, error in outcomes if error is not None}
        merged = merge_results([results for _, results, _ in outcomes])
        self._events.put((token, (merged, counts, errors)))

    def _poll(self) -> None:
        try:
            while True:
                token, payload = self._events.get_nowait()
                if token != self._token:
                    continue          # respuesta de una búsqueda ya reemplazada
                self._set_searching(False)
                results, counts, errors = payload
                self._results = results
                self._counts, self._errors = counts, errors
                self._render()
        except queue.Empty:
            pass
        self.after(POLL_MS, self._poll)

    def _set_searching(self, searching: bool, message: str = "") -> None:
        self._searching = searching
        self.search_button.configure(state="disabled" if searching else "normal",
                                     text="Buscando…" if searching else "Buscar")
        if searching:
            self.spinner.grid(row=0, column=0, padx=(0, 10), pady=(0, 4))
            self.spinner.start()
            self.status.configure(text=message)
        else:
            self.spinner.stop()
            self.spinner.grid_remove()

    # ------------------------------------------------------------ resultados
    def _render(self) -> None:
        for widget in self.table.winfo_children():
            widget.destroy()
        header_font = ctk.CTkFont(size=12, weight="bold")
        for col, (title, _) in enumerate(COLUMNS):
            ctk.CTkLabel(self.table, text=title, font=header_font, anchor="w").grid(
                row=0, column=col, sticky="ew", padx=6, pady=(4, 6))

        results = sort_results(self._results, SortOrder(self.sort.get()))
        by_source = " · ".join(
            f"{name}: {'sin respuesta' if name in self._errors else count}" for name, count in self._counts.items()
        )
        if not results:
            if self._last_text and not self._searching:
                if self._errors and len(self._errors) == len(self._counts):
                    message = str(next(iter(self._errors.values())))
                else:
                    message = f"Sin resultados para «{self._last_text}» con estos filtros ({by_source})."
                self.status.configure(text=message)
            return
        self.status.configure(text=f"{len(results)} opción(es) para «{self._last_text}» — {by_source}.")
        for row, result in enumerate(results, start=1):
            self._render_row(row, result)

    def _render_row(self, row: int, result: SearchResult) -> None:
        cell = {"padx": 6, "pady": 4}
        title_box = ctk.CTkFrame(self.table, fg_color="transparent")
        title_box.grid(row=row, column=0, sticky="ew", **cell)
        title = ctk.CTkLabel(title_box, text=shorten(result.title, 60), anchor="w", cursor="hand2",
                             font=ctk.CTkFont(size=13, underline=True))
        title.pack(anchor="w")
        title.bind("<Button-1>", lambda _e, url=result.page_url: webbrowser.open(url))
        ctk.CTkLabel(title_box, text=f"{result.provider} · {result.license}", anchor="w", text_color=_MUTED,
                     font=ctk.CTkFont(size=11)).pack(anchor="w")

        values = (
            str(result.year or "—"), result.quality or "—", shorten(result.language_label, 26),
            format_size(result.size_bytes), format_count(result.popularity),
        )
        for col, value in enumerate(values, start=1):
            ctk.CTkLabel(self.table, text=value, anchor="w").grid(row=row, column=col, sticky="ew", **cell)

        added = result.download_url in self._added
        button = ctk.CTkButton(self.table, width=130, height=28,
                               text="✓ En la cola" if added else "Añadir a la cola",
                               state="disabled" if added else "normal")
        button.configure(command=lambda r=result, b=button: self._add(r, b))
        # Margen derecho extra: la barra de desplazamiento no debe tapar el botón.
        button.grid(row=row, column=len(COLUMNS) - 1, padx=(6, 18), pady=4)

    def _add(self, result: SearchResult, button: ctk.CTkButton) -> None:
        if self._on_add(result):
            self._added.add(result.download_url)
            button.configure(text="✓ En la cola", state="disabled")
            self.status.configure(text=f"«{shorten(result.title, 50)}» añadida a la cola de descargas.")
