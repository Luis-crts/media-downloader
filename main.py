"""Punto de entrada.

    python main.py                 # abre la interfaz
    python main.py --self-check    # verifica recursos y dependencias (útil tras empaquetar)
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

if sys.version_info < (3, 10):
    sys.exit("Se requiere Python 3.10 o superior.")

from app import __version__  # noqa: E402
from app.paths import is_frozen, resource_path, user_data_dir  # noqa: E402

log = logging.getLogger("main")


def setup_logging() -> None:
    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            user_data_dir() / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
    ]
    # Con --noconsole/--windowed, sys.stderr es None: solo se registra en archivo.
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


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
    }
    required = ("icon.ico", "icon.png", "customtkinter_theme", "yt_dlp_extractors", "yt_dlp_ejs")
    ok = all(checks[k] for k in required)

    report = "\n".join(f"{k}: {v}" for k, v in checks.items())
    report += f"\nresultado: {'OK' if ok else 'FALLO'}\n"
    (user_data_dir() / "self-check.txt").write_text(report, encoding="utf-8")
    log.info("Self-check:\n%s", report)
    return 0 if ok else 1


def main() -> int:
    setup_logging()
    if "--self-check" in sys.argv:
        return self_check()

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
                f"Detalles en: {user_data_dir() / 'app.log'}",
            )
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
