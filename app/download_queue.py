"""Cola de descargas: modelo sin dependencias de la interfaz.

Solo la manipula el hilo de la GUI (los hilos de descarga se comunican con ella
mediante eventos), así que no necesita bloqueos.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from app.core import DownloadRequest

_ids = itertools.count(1)


class ItemStatus(Enum):
    PENDING = "Pendiente"
    ACTIVE = "Descargando"
    PAUSED = "En pausa"
    DONE = "Completada"
    FAILED = "Error"
    CANCELLED = "Cancelada"

    @property
    def finished(self) -> bool:
        return self in (ItemStatus.DONE, ItemStatus.FAILED, ItemStatus.CANCELLED)

    @property
    def running(self) -> bool:
        return self in (ItemStatus.ACTIVE, ItemStatus.PAUSED)


@dataclass
class QueueItem:
    request: DownloadRequest
    source: str = ""                  # nombre del proveedor (YouTube, Web / M3U8…)
    id: int = field(default_factory=lambda: next(_ids))
    status: ItemStatus = ItemStatus.PENDING
    title: str = ""
    percent: float = 0.0
    message: str = ""
    files: list[Path] = field(default_factory=list)
    error: str = ""

    @property
    def display_title(self) -> str:
        return self.title or self.request.filename or self.request.url

    @property
    def summary(self) -> str:
        """Descripción corta: tipo · calidad · subtítulos."""
        parts = [self.request.download_type.value.split(" (")[0]]
        if self.request.quality:
            parts.append(f"≤{self.request.quality}p")
        if self.request.subtitles:
            parts.append("subs " + ",".join(self.request.subtitle_langs))
        if self.source:
            parts.append(self.source)
        return " · ".join(parts)


class DownloadQueue:
    def __init__(self) -> None:
        self._items: list[QueueItem] = []

    # ------------------------------------------------------------ consultas
    @property
    def items(self) -> list[QueueItem]:
        return list(self._items)

    def get(self, item_id: int) -> QueueItem | None:
        return next((i for i in self._items if i.id == item_id), None)

    def active(self) -> QueueItem | None:
        return next((i for i in self._items if i.status.running), None)

    def next_pending(self) -> QueueItem | None:
        return next((i for i in self._items if i.status is ItemStatus.PENDING), None)

    def pending_count(self) -> int:
        return sum(i.status is ItemStatus.PENDING for i in self._items)

    def counts(self) -> dict[ItemStatus, int]:
        result = {status: 0 for status in ItemStatus}
        for item in self._items:
            result[item.status] += 1
        return result

    def find_duplicate(self, request: DownloadRequest) -> QueueItem | None:
        """Misma URL y tipo que un elemento que aún no ha terminado."""
        return next(
            (
                i for i in self._items
                if not i.status.finished
                and i.request.url == request.url
                and i.request.download_type is request.download_type
            ),
            None,
        )

    # ---------------------------------------------------------- operaciones
    def add(self, request: DownloadRequest, source: str = "") -> QueueItem:
        item = QueueItem(request=request, source=source)
        self._items.append(item)
        return item

    def remove(self, item_id: int) -> bool:
        """Quita un elemento que no se esté descargando."""
        item = self.get(item_id)
        if item is None or item.status.running:
            return False
        self._items.remove(item)
        return True

    def clear_finished(self) -> list[int]:
        removed = [i.id for i in self._items if i.status.finished]
        self._items = [i for i in self._items if not i.status.finished]
        return removed

    def clear_pending(self) -> list[int]:
        removed = [i.id for i in self._items if i.status is ItemStatus.PENDING]
        self._items = [i for i in self._items if i.status is not ItemStatus.PENDING]
        return removed
