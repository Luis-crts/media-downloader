"""Widgets reutilizables de la interfaz (CustomTkinter)."""
from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from app.download_queue import ItemStatus, QueueItem

_MUTED = ("gray40", "gray65")
_STATUS_COLORS = {
    ItemStatus.PENDING: ("gray50", "gray35"),
    ItemStatus.ACTIVE: ("#1f6aa5", "#1f6aa5"),
    ItemStatus.PAUSED: ("#b9770e", "#b9770e"),
    ItemStatus.DONE: ("#1e8449", "#1e8449"),
    ItemStatus.FAILED: ("#c0392b", "#a93226"),
    ItemStatus.CANCELLED: ("gray55", "gray30"),
}


def shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class CollapsibleSection(ctk.CTkFrame):
    """Sección plegable: una cabecera clicable (▸ / ▾) que muestra u oculta ``content``.

    Los widgets de la sección se crean dentro de ``section.content``. Con la sección
    plegada, ``set_summary`` permite mostrar en la cabecera un resumen de lo configurado.
    """

    def __init__(
        self,
        master,
        title: str,
        expanded: bool = False,
        on_toggle: Callable[[bool], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._title = title
        self._summary = ""
        self._expanded = expanded
        self._on_toggle = on_toggle
        self.grid_columnconfigure(0, weight=1)

        self.header = ctk.CTkButton(
            self, text="", anchor="w", height=38, corner_radius=10,
            fg_color="transparent", hover_color=("gray85", "gray25"),
            text_color=("gray10", "gray90"), font=ctk.CTkFont(size=14, weight="bold"),
            command=self.toggle,
        )
        self.header.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 10))
        self.content.grid_columnconfigure(1, weight=1)
        self._render()

    @property
    def expanded(self) -> bool:
        return self._expanded

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)
        if self._on_toggle:
            self._on_toggle(self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._render()

    def set_summary(self, summary: str) -> None:
        self._summary = summary
        self._render_header()

    def _render_header(self) -> None:
        arrow = "▾" if self._expanded else "▸"
        text = f"{arrow}  {self._title}"
        if self._summary and not self._expanded:
            text += f"   ·   {self._summary}"
        self.header.configure(text=text)

    def _render(self) -> None:
        self._render_header()
        if self._expanded:
            self.content.grid()
        else:
            self.content.grid_remove()


class QueueRow(ctk.CTkFrame):
    """Fila de la cola: estado · título/detalle · progreso · acción."""

    def __init__(
        self,
        master,
        item: QueueItem,
        on_remove: Callable[[int], None],
        on_open: Callable[[QueueItem], None],
    ) -> None:
        super().__init__(master, corner_radius=8, fg_color=("gray88", "gray20"))
        self._on_remove = on_remove
        self._on_open = on_open
        self._item = item
        self.grid_columnconfigure(1, weight=1)

        self.status = ctk.CTkLabel(
            self, width=104, height=24, corner_radius=6, text_color="white",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.status.grid(row=0, column=0, rowspan=2, padx=(10, 10), pady=8)
        self.title = ctk.CTkLabel(self, anchor="w", font=ctk.CTkFont(size=13))
        self.title.grid(row=0, column=1, sticky="ew", pady=(6, 0))
        self.detail = ctk.CTkLabel(self, anchor="w", font=ctk.CTkFont(size=11), text_color=_MUTED)
        self.detail.grid(row=1, column=1, sticky="ew", pady=(0, 6))
        self.bar = ctk.CTkProgressBar(self, width=110, height=8)
        self.bar.grid(row=0, column=2, rowspan=2, padx=(10, 4))
        self.percent = ctk.CTkLabel(self, width=48, anchor="e", font=ctk.CTkFont(size=12))
        self.percent.grid(row=0, column=3, rowspan=2, padx=(0, 6))
        self.action = ctk.CTkButton(
            self, width=72, height=26, fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"), command=self._on_action,
        )
        self.action.grid(row=0, column=4, rowspan=2, padx=(4, 10))
        self.update_item(item)

    def update_item(self, item: QueueItem) -> None:
        self._item = item
        self.status.configure(text=item.status.value, fg_color=_STATUS_COLORS[item.status])
        self.title.configure(text=shorten(item.display_title, 70))

        if item.status is ItemStatus.FAILED:
            detail = item.error.splitlines()[0] if item.error else "Error"
            self.detail.configure(text=shorten(detail, 90), text_color=("#c0392b", "#ec7063"))
        else:
            detail = item.summary
            if item.status.running and item.message:
                detail += f"  —  {item.message}"
            elif item.status is ItemStatus.DONE and item.files:
                detail += f"  —  {len(item.files)} archivo(s)"
            self.detail.configure(text=shorten(detail, 90), text_color=_MUTED)

        percent = 100.0 if item.status is ItemStatus.DONE else item.percent
        self.bar.set(percent / 100)
        # A 0 % CTkProgressBar pinta igualmente un extremo de color: en pendientes se
        # iguala al fondo de la barra para que no parezca que ya empezó.
        self.bar.configure(
            progress_color=self.bar.cget("fg_color") if item.status is ItemStatus.PENDING
            else _STATUS_COLORS[item.status]
        )
        self.percent.configure(text=f"{percent:.0f} %" if item.status is not ItemStatus.PENDING else "")

        if item.status is ItemStatus.DONE:
            self.action.configure(text="Abrir", state="normal", border_width=1)
        elif item.status.running:
            # Se controla con Pausar / Cancelar. El botón se vacía en lugar de ocultarse
            # para que la barra de progreso quede alineada con las demás filas.
            self.action.configure(text="", state="disabled", border_width=0)
        else:
            self.action.configure(text="Quitar", state="normal", border_width=1)

    def _on_action(self) -> None:
        if self._item.status is ItemStatus.DONE:
            self._on_open(self._item)
        else:
            self._on_remove(self._item.id)


class QueueView(ctk.CTkFrame):
    """Lista de descargas activas, pendientes y terminadas."""

    def __init__(
        self,
        master,
        on_remove: Callable[[int], None],
        on_open: Callable[[QueueItem], None],
        on_clear_finished: Callable[[], None],
        on_clear_pending: Callable[[], None],
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._on_remove = on_remove
        self._on_open = on_open
        self._rows: dict[int, QueueRow] = {}
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 6))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header, text="Cola de descargas", font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        self.counts = ctk.CTkLabel(header, text="", text_color=_MUTED)
        self.counts.grid(row=0, column=1, sticky="w", padx=12)
        button_style = {
            "height": 26, "fg_color": "transparent", "border_width": 1,
            "text_color": ("gray10", "gray90"),
        }
        self.clear_pending_button = ctk.CTkButton(
            header, text="Vaciar pendientes", width=130, command=on_clear_pending, **button_style,
        )
        self.clear_pending_button.grid(row=0, column=2, padx=(0, 6))
        self.clear_finished_button = ctk.CTkButton(
            header, text="Limpiar terminadas", width=130, command=on_clear_finished, **button_style,
        )
        self.clear_finished_button.grid(row=0, column=3)

        self.rows_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.rows_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.rows_frame.grid_columnconfigure(0, weight=1)
        self.empty = ctk.CTkLabel(
            self.rows_frame, text_color=_MUTED,
            text="La cola está vacía. Pulsa «Descargar» para añadir enlaces; se descargan de uno en uno.",
        )
        self.set_counts({status: 0 for status in ItemStatus})

    def add_item(self, item: QueueItem) -> None:
        row = QueueRow(self.rows_frame, item, self._on_remove, self._on_open)
        self._rows[item.id] = row
        self._regrid()

    # No se llama update(): sobrescribiría Misc.update() de Tk.
    def update_item(self, item: QueueItem) -> None:
        row = self._rows.get(item.id)
        if row:
            row.update_item(item)

    def remove_item(self, item_id: int) -> None:
        row = self._rows.pop(item_id, None)
        if row:
            row.destroy()
            self._regrid()

    def set_counts(self, counts: dict[ItemStatus, int]) -> None:
        active = counts[ItemStatus.ACTIVE] + counts[ItemStatus.PAUSED]
        finished = counts[ItemStatus.DONE] + counts[ItemStatus.FAILED] + counts[ItemStatus.CANCELLED]
        self.counts.configure(
            text=f"{active} activa · {counts[ItemStatus.PENDING]} pendiente(s) · {finished} terminada(s)"
        )
        self.clear_pending_button.configure(state="normal" if counts[ItemStatus.PENDING] else "disabled")
        self.clear_finished_button.configure(state="normal" if finished else "disabled")

    def _regrid(self) -> None:
        if not self._rows:
            self.empty.grid(row=0, column=0, sticky="w", padx=6, pady=6)
            return
        self.empty.grid_remove()
        for index, row in enumerate(self._rows.values()):
            row.grid(row=index, column=0, sticky="ew", pady=3)
