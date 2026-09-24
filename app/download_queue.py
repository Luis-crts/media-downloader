"""Cola de descargas: modelo sin dependencias de la interfaz.

Solo la manipula el hilo de la GUI (los hilos de descarga se comunican con ella
mediante eventos), así que no necesita bloqueos.
"""
from __future__ import annotations

import itertools
import json
import logging
import os
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

from app.core import DownloadRequest, DownloadType

log = logging.getLogger(__name__)
_ids = itertools.count(1)
# Prefijo «[3/12] » que la interfaz añade al título de los elementos de una lista.
_PLAYLIST_POSITION = re.compile(r"^\[\d+/\d+\]\s*")


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
        if self.request.concurrent_fragments != 8:
            parts.append(f"{self.request.concurrent_fragments} hilos")
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

    def restore(self, items: list[QueueItem]) -> list[QueueItem]:
        """Añade elementos cargados de disco como pendientes (omite duplicados)."""
        added = []
        for item in items:
            if self.find_duplicate(item.request) is None:
                item.status = ItemStatus.PENDING
                self._items.append(item)
                added.append(item)
        return added

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

    def retry(self, item_id: int) -> bool:
        """Vuelve a poner en cola (al final) una descarga fallida o cancelada.

        Si no tenía un nombre fijado, se fija el que usó el primer intento: así el
        reintento escribe en el mismo archivo y yt-dlp reanuda desde su .part en lugar de
        empezar de cero (el título de una página web puede cambiar entre visitas, y el
        nombre automático de un .m3u8 directo lleva la hora).
        """
        item = self.get(item_id)
        if item is None or item.status not in (ItemStatus.FAILED, ItemStatus.CANCELLED):
            return False
        stem = _PLAYLIST_POSITION.sub("", item.title).strip()
        if item.request.filename is None and stem and not _PLAYLIST_POSITION.match(item.title):
            item.request = replace(item.request, filename=stem)
        item.status = ItemStatus.PENDING
        item.percent = 0.0
        item.message = ""
        item.error = ""
        item.files = []
        self._items.remove(item)
        self._items.append(item)
        return True

    def move(self, item_id: int, direction: int) -> bool:
        """Sube (-1) o baja (+1) un pendiente un puesto *entre los pendientes*.

        Solo intercambia posiciones con el pendiente vecino, así que la descarga
        activa y las terminadas no cambian de sitio.
        """
        item = self.get(item_id)
        if item is None or item.status is not ItemStatus.PENDING or direction not in (-1, 1):
            return False
        pending = [i for i in self._items if i.status is ItemStatus.PENDING]
        index = pending.index(item)
        neighbour_index = index + direction
        if not 0 <= neighbour_index < len(pending):
            return False
        neighbour = pending[neighbour_index]
        a, b = self._items.index(item), self._items.index(neighbour)
        self._items[a], self._items[b] = self._items[b], self._items[a]
        return True

    def pending_position(self, item_id: int) -> tuple[int, int] | None:
        """(posición, total) de un pendiente entre los pendientes, empezando en 0."""
        pending = [i.id for i in self._items if i.status is ItemStatus.PENDING]
        return (pending.index(item_id), len(pending)) if item_id in pending else None

    # ---------------------------------------------------------- persistencia
    def unfinished(self) -> list[QueueItem]:
        """Lo que hay que conservar al cerrar: la activa (primero) y las pendientes."""
        running = [i for i in self._items if i.status.running]
        pending = [i for i in self._items if i.status is ItemStatus.PENDING]
        return running + pending


# --------------------------------------------------------------------------- #
# Persistencia en JSON
# --------------------------------------------------------------------------- #
QUEUE_FILE_VERSION = 1


def request_to_dict(request: DownloadRequest) -> dict:
    return {
        "url": request.url,
        "output_dir": str(request.output_dir),
        "download_type": request.download_type.name,
        "allow_playlist": request.allow_playlist,
        "quality": request.quality,
        "headers": dict(request.headers),
        "filename": request.filename,
        "subtitles": request.subtitles,
        "subtitle_langs": list(request.subtitle_langs),
        "concurrent_fragments": request.concurrent_fragments,
    }


def request_from_dict(data: dict) -> DownloadRequest:
    return DownloadRequest(
        url=str(data["url"]),
        output_dir=Path(data["output_dir"]),
        download_type=DownloadType[data["download_type"]],
        allow_playlist=bool(data.get("allow_playlist", True)),
        quality=data.get("quality"),
        headers={str(k): str(v) for k, v in (data.get("headers") or {}).items()},
        filename=data.get("filename"),
        subtitles=bool(data.get("subtitles", False)),
        subtitle_langs=tuple(data.get("subtitle_langs") or ("es", "en")),
        concurrent_fragments=int(data.get("concurrent_fragments") or 8),
    )


def save_queue(path: Path, items: list[QueueItem]) -> None:
    """Guarda los elementos como pendientes. Escritura atómica: nunca queda a medias."""
    payload = {
        "version": QUEUE_FILE_VERSION,
        "items": [
            {"request": request_to_dict(i.request), "source": i.source, "title": i.title}
            for i in items
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_queue(path: Path) -> list[QueueItem]:
    """Carga la cola guardada. Los elementos inválidos se descartan y se registran.

    Si el archivo está dañado se renombra a ``.bad`` para no perderlo ni volver a fallar.
    """
    if not path.is_file():
        return []
    try:
        # utf-8-sig: acepta también archivos con BOM (p. ej. editados con el Bloc de notas).
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        entries = payload["items"]
    except (OSError, ValueError, KeyError, TypeError):
        log.warning("Cola guardada ilegible: %s (se renombra a .bad)", path, exc_info=True)
        try:
            os.replace(path, path.with_suffix(path.suffix + ".bad"))
        except OSError:
            pass
        return []

    items = []
    for entry in entries:
        try:
            items.append(QueueItem(
                request=request_from_dict(entry["request"]),
                source=str(entry.get("source") or ""),
                title=str(entry.get("title") or ""),
            ))
        except (KeyError, TypeError, ValueError):
            log.warning("Elemento de la cola descartado: %r", entry, exc_info=True)
    return items
