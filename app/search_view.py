"""Pestaña «Buscar películas»: búsqueda en fuentes legales y envío a la cola.

La búsqueda corre en un hilo secundario (puede tardar unos segundos: se consultan los
metadatos de cada resultado) y comunica el resultado por una cola que se consulta con
``after()``, igual que las descargas. Los filtros de orden se aplican en local; el de
idioma repite la búsqueda en el servidor para no perder resultados.
"""
from __future__ import annotations

import logging
import queue
import threading
import webbrowser
from typing import Callable

import customtkinter as ctk

from app.core.search import (
    LanguageFilter,
    SearchError,
    SearchQuery,
    SearchResult,
    SortOrder,
    get_search_provider,
    sort_results,
)
from app.widgets import shorten

log = logging.getLogger(__name__)

_MUTED = ("gray40", "gray65")
POLL_MS = 100
COLUMNS = (   # (encabezado, ancho mínimo)
    ("Título", 260), ("Año", 50), ("Formato / calidad", 130), ("Idioma", 90),
    ("Tamaño", 80), ("Popularidad", 90), ("", 140),
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
        self._provider = get_search_provider()
        self._results: list[SearchResult] = []
        self._added: set[str] = set()
        self._events: queue.Queue[tuple[int, object]] = queue.Queue()
        self._token = 0             # identifica la búsqueda en curso (descarta respuestas viejas)
        self._searching = False
        self._last_text = ""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
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
            text=f"Fuente: {self._provider.name} — {self._provider.description}. "
                 "La licencia de cada película la declara quien la subió: revísala en su página.",
            wraplength=720, justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        filters = ctk.CTkFrame(self, fg_color="transparent")
        filters.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 6))
        ctk.CTkLabel(filters, text="Ordenar").pack(side="left", padx=(0, 6))
        self.sort = ctk.CTkSegmentedButton(filters, values=[o.value for o in SortOrder], command=lambda _v: self._render())
        self.sort.set(SortOrder.RELEVANCE.value)
        self.sort.pack(side="left")
        ctk.CTkLabel(filters, text="Idioma").pack(side="left", padx=(18, 6))
        self.language = ctk.CTkSegmentedButton(
            filters, values=[l.value for l in LanguageFilter], command=self._on_language_change,
        )
        self.language.set(LanguageFilter.ALL.value)
        self.language.pack(side="left")

        status = ctk.CTkFrame(self, fg_color="transparent")
        status.grid(row=2, column=0, sticky="ew", padx=4)
        status.grid_columnconfigure(1, weight=1)
        self.spinner = ctk.CTkProgressBar(status, mode="indeterminate", width=120, height=8)
        self.status = ctk.CTkLabel(status, text="Escribe qué buscar y pulsa «Buscar».", anchor="w", text_color=_MUTED)
        self.status.grid(row=0, column=1, sticky="ew", pady=(0, 4))

        self.table = ctk.CTkScrollableFrame(self, corner_radius=12)
        self.table.grid(row=3, column=0, sticky="nsew", padx=4, pady=(0, 4))
        for col, (_, minsize) in enumerate(COLUMNS):
            self.table.grid_columnconfigure(col, weight=1 if col == 0 else 0, minsize=minsize)

    # ------------------------------------------------------------- búsqueda
    def _on_language_change(self, _value: str) -> None:
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
        query = SearchQuery(text=text, language=language)
        self._set_searching(True, f"Buscando opciones en {self._provider.name}…")
        log.info("Búsqueda #%d: %r (idioma: %s)", self._token, text, language.value)
        threading.Thread(target=self._run, args=(self._token, query), daemon=True, name="busqueda").start()

    def _run(self, token: int, query: SearchQuery) -> None:
        """Hilo secundario: nunca toca widgets."""
        try:
            self._events.put((token, self._provider.search(query)))
        except SearchError as exc:
            log.warning("Búsqueda fallida: %s | %s", exc, exc.detail)
            self._events.put((token, exc))
        except Exception as exc:   # cualquier otro fallo se informa igual
            log.exception("Error inesperado en la búsqueda")
            self._events.put((token, SearchError(f"Error inesperado: {exc}")))

    def _poll(self) -> None:
        try:
            while True:
                token, payload = self._events.get_nowait()
                if token != self._token:
                    continue          # respuesta de una búsqueda ya reemplazada
                self._set_searching(False)
                if isinstance(payload, SearchError):
                    self._results = []
                    self._render()
                    self.status.configure(text=str(payload))
                else:
                    self._results = payload
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
        if not results:
            if self._last_text and not self._searching:
                self.status.configure(text=f"Sin resultados para «{self._last_text}» con estos filtros.")
            return
        self.status.configure(
            text=f"{len(results)} película(s) para «{self._last_text}». Pulsa el título para ver su página y licencia."
        )
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
        ctk.CTkLabel(title_box, text=result.license, anchor="w", text_color=_MUTED,
                     font=ctk.CTkFont(size=11)).pack(anchor="w")

        values = (
            str(result.year or "—"), result.quality or "—", result.language_label,
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
