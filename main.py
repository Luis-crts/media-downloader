"""Punto de entrada.

    python main.py                 # abre la interfaz
    python main.py --self-check    # verifica recursos y dependencias (útil tras empaquetar)
    python main.py --test-download URL   # descarga real sin interfaz (diagnóstico)
"""
from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

if sys.version_info < (3, 10):
    sys.exit("Se requiere Python 3.10 o superior.")

from app import __version__  # noqa: E402
from app.paths import is_frozen, log_file_path, resource_path, user_data_dir  # noqa: E402

log = logging.getLogger("main")


def setup_logging() -> None:
    """Registra eventos, avisos y errores (de la app y de yt-dlp) en media_downloader.log.

    Rota a los 5 MB y conserva 3 copias (media_downloader.log.1, .2, .3).
    """
    handlers: list[logging.Handler] = [
        RotatingFileHandler(log_file_path(), maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    ]
    # Con --noconsole/--windowed, sys.stderr es None: solo se registra en archivo.
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s",
        handlers=handlers,
    )
    # Errores no capturados en hilos secundarios (descargas) también al log.
    threading.excepthook = lambda args: logging.getLogger("thread").error(
        "Excepción no capturada en %s", args.thread.name if args.thread else "?",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )
    log.info("=== Media Downloader %s | log: %s ===", __version__, log_file_path())


def set_windows_app_id() -> None:
    """Agrupa la ventana en la barra de tareas con su propio icono (no el de Python)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MediaDownloader.App")
    except (AttributeError, OSError):
        pass


def _has_ejs_scripts() -> bool:
    """yt-dlp-ejs aporta los scripts JS para los retos de YouTube (datos, no código Python)."""
    try:
        import yt_dlp_ejs
    except ImportError:
        return False
    return any(Path(yt_dlp_ejs.__file__).parent.rglob("*.js"))


def self_check() -> int:
    """Comprueba que el binario contiene todo lo necesario. Devuelve el código de salida."""
    from app.core import find_ffmpeg, find_js_runtime
    from app.core.torrent import libtorrent_version
    import yt_dlp

    import customtkinter

    checks = {
        "version": __version__,
        "frozen": is_frozen(),
        "icon.ico": resource_path("assets", "icon.ico").is_file(),
        "icon.png": resource_path("assets", "icon.png").is_file(),
        "customtkinter_theme": (
            Path(customtkinter.__file__).parent / "assets" / "themes" / "blue.json"
        ).is_file(),
        "yt_dlp": yt_dlp.version.__version__,
        "yt_dlp_extractors": len(yt_dlp.extractor.gen_extractor_classes()) > 100,
        "yt_dlp_ejs": _has_ejs_scripts(),
        "ffmpeg": str(find_ffmpeg() or "NO ENCONTRADO"),
        "js_runtime": find_js_runtime() or "NO ENCONTRADO",
        "libtorrent": libtorrent_version() or "",
    }
    required = ("icon.ico", "icon.png", "customtkinter_theme", "yt_dlp_extractors", "yt_dlp_ejs", "libtorrent")
    ok = all(checks[k] for k in required)

    report = "\n".join(f"{k}: {v}" for k, v in checks.items())
    report += f"\nresultado: {'OK' if ok else 'FALLO'}\n"
    (user_data_dir() / "self-check.txt").write_text(report, encoding="utf-8")
    log.info("Self-check:\n%s", report)
    return 0 if ok else 1


def test_download(url: str) -> int:
    """Descarga real sin interfaz (diagnóstico del binario): MediaDownloader --test-download URL

    Guarda el archivo en la carpeta de datos del usuario (subcarpeta test-download) con la
    calidad más baja disponible y deja el resultado en el log y en self-check.txt.
    """
    from app.core import DownloaderError, DownloadRequest, DownloadType, get_downloader
    from app.core.torrent import is_torrent_source

    output = user_data_dir() / "test-download"
    kind = DownloadType.TORRENT if is_torrent_source(url) else DownloadType.WEB_VIDEO
    request = DownloadRequest(
        url=url, output_dir=output, download_type=kind,
        quality=240, filename="test-download", concurrent_fragments=8,
    )
    try:
        result = get_downloader(url, request.download_type).download(request, lambda _p: None)
        files = ", ".join(f"{f.name} ({f.stat().st_size / 1e6:.1f} MB)" for f in result.completed)
        report, code = f"test-download: OK -> {files}\n", 0
    except DownloaderError as exc:
        report, code = f"test-download: FALLO -> {exc.title}: {exc} | {exc.detail}\n", 1
    except Exception as exc:  # cualquier otro fallo también debe quedar registrado
        log.exception("test-download: error inesperado")
        report, code = f"test-download: FALLO -> {type(exc).__name__}: {exc}\n", 1
    (user_data_dir() / "self-check.txt").write_text(report, encoding="utf-8")
    log.info(report.strip())
    return code


def main() -> int:
    setup_logging()
    if "--self-check" in sys.argv:
        return self_check()
    if "--test-download" in sys.argv:
        index = sys.argv.index("--test-download")
        if index + 1 >= len(sys.argv):
            log.error("Uso: --test-download URL")
            return 2
        return test_download(sys.argv[index + 1])

    set_windows_app_id()
    try:
        from app.gui import run

        run()
    except Exception:
        log.exception("Error fatal")
        # Sin consola, el usuario no vería nada: se muestra un diálogo.
        try:
            from tkinter import messagebox

            messagebox.showerror(
                "Media Downloader",
                f"La aplicación se cerró por un error inesperado.\n"
                f"Detalles en: {log_file_path()}",
            )
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
