"""Descargas P2P (BitTorrent) con libtorrent: enlaces magnet y archivos .torrent.

Convive con el motor de yt-dlp como un proveedor más: mismo contrato
(``BaseDownloader``), mismos eventos de progreso, pausa, cancelación y errores, así
que la cola y la interfaz no distinguen entre ambos.

Decisiones:
- **Sin compartir al terminar:** al llegar al 100 % el torrent se detiene. Mientras
  descarga, BitTorrent sube datos a otros pares (es parte del protocolo); al acabar no
  se sigue compartiendo, así la IP deja de estar visible en el enjambre.
- **Reanudación:** al cancelar o cerrar se conservan los datos. Al volver a añadir el
  mismo torrent en la misma carpeta, libtorrent comprueba las piezas existentes
  (verificadas por hash) y solo descarga las que faltan.
- **Integridad:** cada pieza se verifica con su hash (SHA-1/SHA-256), por lo que no hace
  falta la validación con ffprobe que se aplica a las descargas HTTP.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from app import __version__
from app.core.base import (
    BaseDownloader,
    ContentUnavailableError,
    DownloadCancelledError,
    DownloaderError,
    DownloadRequest,
    DownloadResult,
    DownloadStage,
    DownloadType,
    InvalidURLError,
    NetworkError,
    ProgressCallback,
    ProgressInfo,
    register_downloader,
)

log = logging.getLogger(__name__)

_MAGNET = re.compile(r"^magnet:\?(?:.*&)?xt=urn:bt(?:ih|mh):", re.IGNORECASE)
POLL_SECONDS = 0.5
METADATA_TIMEOUT = 300        # s sin conseguir los metadatos de un magnet
STALL_TIMEOUT = 15 * 60       # s sin fuentes ni avance antes de rendirse
MAX_TORRENT_FILE = 20 * 1024 * 1024


class LibtorrentMissingError(DownloaderError):
    title = "Soporte de torrents no disponible"
    default_message = (
        "Falta la biblioteca libtorrent.\nInstálala con: pip install libtorrent"
    )


def is_torrent_source(url: str) -> bool:
    """Enlace magnet, URL http(s) a un .torrent o ruta local a un .torrent."""
    url = url.strip()
    if _MAGNET.match(url):
        return True
    path = urlsplit(url).path if "://" in url else url
    return path.lower().endswith(".torrent")


def _load_libtorrent():
    try:
        import libtorrent
    except ImportError as exc:
        raise LibtorrentMissingError(detail=str(exc)) from exc
    return libtorrent


def libtorrent_version() -> str | None:
    try:
        import libtorrent
    except ImportError:
        return None
    return libtorrent.__version__


@register_downloader
class TorrentDownloader(BaseDownloader):
    name = "Torrent"
    supported_types = (DownloadType.TORRENT,)

    @classmethod
    def can_handle(cls, url: str) -> bool:
        return is_torrent_source(url)

    # ------------------------------------------------------------------ #
    def download(
        self,
        request: DownloadRequest,
        on_progress: ProgressCallback,
        cancel_event: threading.Event | None = None,
        pause_event: threading.Event | None = None,
    ) -> DownloadResult:
        lt = _load_libtorrent()
        cancel_event = cancel_event or threading.Event()
        pause_event = pause_event or threading.Event()
        try:
            request.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DownloaderError(
                f"No se puede escribir en la carpeta de destino:\n{request.output_dir}", detail=str(exc)
            ) from exc

        log.info("Torrent iniciado | libtorrent %s | %s", lt.__version__, _short(request.url))
        on_progress(ProgressInfo(stage=DownloadStage.ANALYZING, message="Leyendo el torrent…"))
        params = self._params(lt, request.url.strip())
        params.save_path = str(request.output_dir)

        session = lt.session(self._settings(lt))
        handle = session.add_torrent(params)
        # La pausa la controla la aplicación, no la cola interna de libtorrent.
        handle.unset_flags(lt.torrent_flags.auto_managed)
        handle.resume()
        try:
            name = self._run(lt, handle, on_progress, cancel_event, pause_event)
            files = self._files(handle, request.output_dir)
        finally:
            # Se conservan los datos descargados (reanudables); se deja de compartir.
            session.remove_torrent(handle)
            del session

        log.info("Torrent completado: %s (%d archivo(s))", name, len(files))
        for path in files:
            on_progress(ProgressInfo(
                stage=DownloadStage.ITEM_DONE, title=path.stem, percent=100.0,
                message=f"Guardado: {path.name}",
            ))
        return DownloadResult(output_dir=request.output_dir, completed=files)

    # ------------------------------------------------------------ internos
    @staticmethod
    def _settings(lt) -> dict:
        return {
            "listen_interfaces": "0.0.0.0:6881,[::]:6881",
            "enable_dht": True,        # imprescindible para los enlaces magnet
            "enable_lsd": True,
            # No se abren puertos en el router automáticamente.
            "enable_upnp": False,
            "enable_natpmp": False,
            "user_agent": f"MediaDownloader/{__version__} libtorrent/{lt.__version__}",
        }

    @staticmethod
    def _params(lt, source: str):
        """add_torrent_params a partir de un magnet, una URL a .torrent o un archivo local."""
        try:
            if _MAGNET.match(source):
                return lt.parse_magnet_uri(source)
            if "://" in source:
                request = urllib.request.Request(source, headers={"User-Agent": f"MediaDownloader/{__version__}"})
                with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                    data = response.read(MAX_TORRENT_FILE + 1)
                if len(data) > MAX_TORRENT_FILE:
                    raise InvalidURLError("El archivo .torrent es demasiado grande para ser válido.")
                info = lt.torrent_info(lt.bdecode(data))
            else:
                path = Path(source).expanduser()
                if not path.is_file():
                    raise InvalidURLError(f"No existe el archivo .torrent:\n{path}")
                info = lt.torrent_info(str(path))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if isinstance(exc, urllib.error.HTTPError):
                raise InvalidURLError(f"No se pudo descargar el .torrent (HTTP {exc.code}).", detail=str(exc)) from exc
            raise NetworkError(detail=f"{source}: {exc}") from exc
        except RuntimeError as exc:   # libtorrent: magnet o .torrent mal formado
            raise InvalidURLError("El enlace magnet o el archivo .torrent no es válido.", detail=str(exc)) from exc
        params = lt.add_torrent_params()
        params.ti = info
        return params

    def _run(self, lt, handle, on_progress, cancel_event, pause_event) -> str:
        """Bucle de estado hasta completar. Devuelve el nombre del torrent."""
        states = lt.torrent_status.states
        started = last_activity = time.monotonic()
        last_done = -1
        paused = False
        while True:
            if cancel_event.is_set():
                log.info("Torrent cancelado por el usuario (los datos se conservan)")
                raise DownloadCancelledError()
            if pause_event.is_set() != paused:
                paused = pause_event.is_set()
                if paused:
                    handle.pause()
                    log.info("Torrent en pausa")
                    on_progress(ProgressInfo(stage=DownloadStage.PAUSED, message="En pausa"))
                else:
                    handle.resume()
                    log.info("Torrent reanudado")
                last_activity = time.monotonic()
            if paused:
                cancel_event.wait(POLL_SECONDS)
                continue

            status = handle.status()
            if status.errc.value():
                raise DownloaderError(f"Error del torrent: {status.errc.message()}", detail=status.errc.message())
            name = status.name or "Torrent"
            now = time.monotonic()

            if not status.has_metadata:
                if now - started > METADATA_TIMEOUT:
                    raise ContentUnavailableError(
                        "No se encontró a nadie que comparta este enlace magnet (sin metadatos tras "
                        f"{METADATA_TIMEOUT // 60} minutos). Puedes reintentarlo más tarde.",
                        detail=f"pares conocidos: {status.list_peers}",
                    )
                on_progress(ProgressInfo(
                    stage=DownloadStage.ANALYZING, title=name,
                    message=f"Buscando metadatos del magnet… ({status.num_peers} pares conectados)",
                    seeds=status.num_seeds, peers=status.num_peers,
                ))
            elif status.state in (states.checking_files, states.checking_resume_data):
                on_progress(ProgressInfo(
                    stage=DownloadStage.PROCESSING, title=name, percent=status.progress * 100,
                    message="Comprobando los datos ya descargados…",
                ))
                last_activity = now
            elif status.is_finished or status.is_seeding or status.state in (states.finished, states.seeding):
                return name
            else:
                remaining = max(0, status.total_wanted - status.total_wanted_done)
                rate = status.download_rate
                on_progress(ProgressInfo(
                    stage=DownloadStage.DOWNLOADING, title=name, percent=status.progress * 100,
                    downloaded_bytes=status.total_wanted_done, total_bytes=status.total_wanted,
                    speed=rate, eta=int(remaining / rate) if rate > 0 else None,
                    upload_speed=status.upload_rate, seeds=status.num_seeds, peers=status.num_peers,
                    message=(f"Semillas: {status.num_seeds} ({status.list_seeds} conocidas) · "
                             f"Pares: {status.num_peers} ({status.list_peers} conocidos)"),
                ))
                if status.total_wanted_done != last_done:
                    last_done = status.total_wanted_done
                    last_activity = now
                elif now - last_activity > STALL_TIMEOUT:
                    raise ContentUnavailableError(
                        f"El torrent lleva {STALL_TIMEOUT // 60} minutos sin avanzar: no hay fuentes "
                        "disponibles. Lo descargado se conserva; puedes reintentar más tarde.",
                        detail=f"{status.progress * 100:.1f} % · semillas {status.list_seeds} · pares {status.list_peers}",
                    )
            cancel_event.wait(POLL_SECONDS)

    @staticmethod
    def _files(handle, output_dir: Path) -> list[Path]:
        storage = handle.torrent_file().files()
        return [output_dir / storage.file_path(i) for i in range(storage.num_files())]


def _short(url: str) -> str:
    """Para el log: el magnet sin la lista de trackers."""
    return url.split("&tr=", 1)[0] if url.startswith("magnet:") else url
