"""Interfaz gráfica (CustomTkinter).

Solo contiene presentación: la descarga se delega a ``app.core`` y se ejecuta en
un hilo secundario. El hilo se comunica con la GUI mediante una ``queue.Queue``
que se consulta con ``after()``, porque Tkinter no es thread-safe.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from app import __version__
from app.paths import resource_path
from app.core import (
    DownloadCancelledError,
    DownloaderError,
    DownloadRequest,
    DownloadResult,
    DownloadStage,
    DownloadType,
    ProgressInfo,
    available_sources,
    find_ffmpeg,
    find_js_runtime,
    get_downloader,
)

log = logging.getLogger(__name__)

APP_NAME = "Media Downloader"
WM_CLASS = "MediaDownloader"
SETTINGS_FILE = Path.home() / ".media_downloader.json"
POLL_MS = 100
APPEARANCE = {"Sistema": "System", "Claro": "Light", "Oscuro": "Dark"}
TYPE_BY_LABEL = {t.value: t for t in DownloadType}


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def format_bytes(value: float | None) -> str:
    if not value:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def format_eta(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def open_folder(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError:
        log.warning("No se pudo guardar la configuración en %s", SETTINGS_FILE)


# --------------------------------------------------------------------------- #
# Ventana principal
# --------------------------------------------------------------------------- #
class DownloaderApp(ctk.CTk):
    def __init__(self) -> None:
        self._settings = load_settings()
        ctk.set_appearance_mode(self._settings.get("appearance", "System"))
        ctk.set_default_color_theme("blue")
        # className fija el WM_CLASS en Linux (debe coincidir con StartupWMClass del .desktop).
        super().__init__(className=WM_CLASS)

        self.title(f"{APP_NAME} {__version__}")
        self._set_window_icon()
        self.geometry("760x640")
        self.minsize(640, 600)
        self.grid_columnconfigure(0, weight=1)

        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._cancel_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._indeterminate = False

        default_dir = Path(self._settings.get("output_dir") or Path.home() / "Downloads")
        self.output_dir = ctk.StringVar(value=str(default_dir))
        saved_type = self._settings.get("download_type")
        self.download_type = ctk.StringVar(
            value=saved_type if saved_type in TYPE_BY_LABEL else DownloadType.MP3.value
        )
        self.allow_playlist = ctk.BooleanVar(value=self._settings.get("allow_playlist", True))

        self._build_header()
        self._build_input_card()
        self._build_progress_card()
        self._build_actions()
        self._build_log()

        self._check_dependencies()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(POLL_MS, self._poll_events)

    # ------------------------------------------------------------------ UI
    def _set_window_icon(self) -> None:
        try:
            if sys.platform == "win32":
                self.iconbitmap(str(resource_path("assets", "icon.ico")))
            else:
                self._icon_image = tk.PhotoImage(file=str(resource_path("assets", "icon.png")))
                self.iconphoto(True, self._icon_image)
        except (tk.TclError, OSError):
            log.warning("No se pudo cargar el icono de la ventana", exc_info=True)

    def _card(self, row: int) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self, corner_radius=12)
        frame.grid(row=row, column=0, sticky="nsew", padx=20, pady=(0, 14))
        frame.grid_columnconfigure(1, weight=1)
        return frame

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 12))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header, text=APP_NAME, font=ctk.CTkFont(size=24, weight="bold")).grid(
            row=0, column=0, sticky="w"
        )
        ctk.CTkLabel(
            header, text=f"Fuentes: {', '.join(available_sources())}",
            text_color=("gray40", "gray65"),
        ).grid(row=1, column=0, sticky="w")

        current = next(
            (k for k, v in APPEARANCE.items() if v == self._settings.get("appearance")), "Sistema"
        )
        theme = ctk.CTkSegmentedButton(
            header, values=list(APPEARANCE), command=self._change_appearance
        )
        theme.set(current)
        theme.grid(row=0, column=1, rowspan=2, sticky="e")

    def _build_input_card(self) -> None:
        card = self._card(1)
        pad = {"padx": 14, "pady": 8}

        ctk.CTkLabel(card, text="Enlace").grid(row=0, column=0, sticky="w", **pad)
        self.url_entry = ctk.CTkEntry(
            card, height=36,
            placeholder_text="https://www.youtube.com/watch?v=…  o  una lista de reproducción",
        )
        self.url_entry.grid(row=0, column=1, sticky="ew", pady=(14, 8))
        self.url_entry.bind("<Return>", lambda _e: self._start_download())
        ctk.CTkButton(card, text="Pegar", width=80, command=self._paste_url).grid(
            row=0, column=2, padx=14, pady=(14, 8)
        )

        ctk.CTkLabel(card, text="Formato").grid(row=1, column=0, sticky="w", **pad)
        ctk.CTkOptionMenu(
            card, values=list(TYPE_BY_LABEL), variable=self.download_type, height=34,
            dynamic_resizing=False,
        ).grid(row=1, column=1, sticky="ew", pady=8)
        ctk.CTkCheckBox(
            card, text="Descargar lista completa", variable=self.allow_playlist,
        ).grid(row=2, column=1, sticky="w", pady=(0, 8))

        ctk.CTkLabel(card, text="Destino").grid(row=3, column=0, sticky="w", **pad)
        folder = ctk.CTkEntry(card, textvariable=self.output_dir, height=34, state="readonly")
        folder.grid(row=3, column=1, sticky="ew", pady=(8, 14))
        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.grid(row=3, column=2, padx=14, pady=(8, 14))
        ctk.CTkButton(buttons, text="Cambiar…", width=80, command=self._choose_folder).pack(
            side="left"
        )
        ctk.CTkButton(
            buttons, text="Abrir", width=60, fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"), command=self._open_output_dir,
        ).pack(side="left", padx=(6, 0))

    def _build_progress_card(self) -> None:
        card = self._card(2)
        card.grid_columnconfigure((0, 1, 2), weight=1)

        self.item_label = ctk.CTkLabel(
            card, text="Listo para descargar", anchor="w",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.item_label.grid(row=0, column=0, columnspan=3, sticky="ew", padx=14, pady=(14, 4))

        self.progress = ctk.CTkProgressBar(card, height=14, mode="determinate")
        self.progress.set(0)
        self.progress.grid(row=1, column=0, columnspan=3, sticky="ew", padx=14, pady=6)

        stat_font = ctk.CTkFont(size=13)
        self.percent_label = ctk.CTkLabel(card, text="0 %", font=stat_font)
        self.speed_label = ctk.CTkLabel(card, text="Velocidad: —", font=stat_font)
        self.eta_label = ctk.CTkLabel(card, text="Restante: —", font=stat_font)
        self.percent_label.grid(row=2, column=0, sticky="w", padx=14)
        self.speed_label.grid(row=2, column=1)
        self.eta_label.grid(row=2, column=2, sticky="e", padx=14)

        self.status_label = ctk.CTkLabel(
            card, text="", anchor="w", text_color=("gray40", "gray65"),
        )
        self.status_label.grid(row=3, column=0, columnspan=3, sticky="ew", padx=14, pady=(4, 12))

    def _build_actions(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 14))
        bar.grid_columnconfigure(0, weight=1)

        self.download_button = ctk.CTkButton(
            bar, text="Descargar", height=42, font=ctk.CTkFont(size=15, weight="bold"),
            command=self._start_download,
        )
        self.download_button.grid(row=0, column=0, sticky="ew")
        self.cancel_button = ctk.CTkButton(
            bar, text="Cancelar", height=42, width=120, state="disabled",
            fg_color=("#c0392b", "#a93226"), hover_color=("#a93226", "#922b21"),
            command=self._cancel_download,
        )
        self.cancel_button.grid(row=0, column=1, padx=(10, 0))

    def _build_log(self) -> None:
        self.grid_rowconfigure(4, weight=1)
        self.log_box = ctk.CTkTextbox(self, height=110, corner_radius=12, state="disabled")
        self.log_box.grid(row=4, column=0, sticky="nsew", padx=20, pady=(0, 18))

    # ------------------------------------------------------------- acciones
    def _change_appearance(self, label: str) -> None:
        mode = APPEARANCE[label]
        ctk.set_appearance_mode(mode)
        self._settings["appearance"] = mode
        save_settings(self._settings)

    def _paste_url(self) -> None:
        try:
            text = self.clipboard_get().strip()
        except Exception:  # portapapeles vacío o sin texto
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, text)

    def _choose_folder(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.output_dir.get(), title="Carpeta de destino")
        if chosen:
            self.output_dir.set(str(Path(chosen)))

    def _open_output_dir(self) -> None:
        path = Path(self.output_dir.get())
        if path.is_dir():
            open_folder(path)
        else:
            messagebox.showinfo(APP_NAME, "La carpeta aún no existe; se creará al descargar.")

    def _check_dependencies(self) -> None:
        missing = []
        if find_ffmpeg() is None:
            missing.append("FFmpeg no encontrado: las descargas fallarán hasta instalarlo.")
        if find_js_runtime() is None:
            missing.append("Deno no encontrado: YouTube puede ofrecer menos formatos (ver README).")
        for line in missing:
            self._log(f"⚠ {line}")
        if missing:
            self.status_label.configure(text=missing[0])

    def _start_download(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        request = DownloadRequest(
            url=self.url_entry.get().strip(),
            output_dir=Path(self.output_dir.get()),
            download_type=TYPE_BY_LABEL[self.download_type.get()],
            allow_playlist=self.allow_playlist.get(),
        )
        try:
            downloader = get_downloader(request.url)  # valida la URL antes de lanzar el hilo
        except DownloaderError as exc:
            messagebox.showerror(exc.title, str(exc))
            return

        self._settings.update(
            output_dir=str(request.output_dir),
            download_type=request.download_type.value,
            allow_playlist=request.allow_playlist,
        )
        save_settings(self._settings)

        self._cancel_event.clear()
        self._set_running(True)
        self._reset_progress()
        self._log(f"→ {request.download_type.value}: {request.url}")
        self._worker = threading.Thread(
            target=self._run_download, args=(downloader, request), daemon=True
        )
        self._worker.start()

    def _run_download(self, downloader, request: DownloadRequest) -> None:
        """Se ejecuta en el hilo secundario: nunca toca widgets directamente."""
        try:
            result = downloader.download(
                request, lambda info: self._events.put(("progress", info)), self._cancel_event
            )
            self._events.put(("done", result))
        except DownloadCancelledError:
            self._events.put(("cancelled", None))
        except DownloaderError as exc:
            log.warning("Descarga fallida: %s | %s", exc, exc.detail)
            self._events.put(("error", exc))
        except Exception as exc:  # error inesperado: se registra y se informa
            log.exception("Error inesperado durante la descarga")
            self._events.put(("error", DownloaderError(f"Error inesperado: {exc}")))

    def _cancel_download(self) -> None:
        self._cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self.status_label.configure(text="Cancelando…")

    # -------------------------------------------------------- eventos/estado
    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "progress":
                    self._apply_progress(payload)  # type: ignore[arg-type]
                elif kind == "done":
                    self._on_done(payload)  # type: ignore[arg-type]
                elif kind == "error":
                    self._on_error(payload)  # type: ignore[arg-type]
                elif kind == "cancelled":
                    self._on_cancelled()
        except queue.Empty:
            pass
        self.after(POLL_MS, self._poll_events)

    def _apply_progress(self, p: ProgressInfo) -> None:
        position = ""
        if p.item_index and p.item_count and p.item_count > 1:
            position = f"[{p.item_index}/{p.item_count}] "
        if p.title:
            self.item_label.configure(text=f"{position}{p.title}")
        if p.message:
            self.status_label.configure(text=p.message)

        if p.stage is DownloadStage.DOWNLOADING and p.percent is not None:
            self._set_indeterminate(False)
            self.progress.set(p.percent / 100)
            self.percent_label.configure(text=f"{p.percent:.1f} %")
            self.speed_label.configure(text=f"Velocidad: {format_bytes(p.speed)}/s")
            self.eta_label.configure(text=f"Restante: {format_eta(p.eta)}")
        elif p.stage is DownloadStage.ITEM_DONE:
            self._set_indeterminate(False)
            self.progress.set(1)
            self.percent_label.configure(text="100 %")
            self._log(f"✔ {p.message}")
        else:  # analizando / procesando: sin avance medible
            self._set_indeterminate(True)
            self.speed_label.configure(text="Velocidad: —")
            self.eta_label.configure(text="Restante: —")

    def _on_done(self, result: DownloadResult) -> None:
        self._set_running(False)
        self._set_indeterminate(False)
        self.progress.set(1)
        self.percent_label.configure(text="100 %")
        summary = f"Completado: {len(result.completed)} archivo(s) en {result.output_dir}"
        self.item_label.configure(text="Descarga completada")
        self.status_label.configure(text=summary)
        if result.failed:
            for error in result.failed:
                self._log(f"✖ {error}")
            messagebox.showwarning(
                APP_NAME,
                f"{summary}\n\n{len(result.failed)} elemento(s) no se pudieron descargar. "
                "Revisa el registro para más detalles.",
            )

    def _on_error(self, error: DownloaderError) -> None:
        self._set_running(False)
        self._reset_progress()
        self.item_label.configure(text=error.title)
        self.status_label.configure(text=str(error).splitlines()[0])
        self._log(f"✖ {error.title}: {error}")
        messagebox.showerror(error.title, str(error))

    def _on_cancelled(self) -> None:
        self._set_running(False)
        self._reset_progress()
        self.item_label.configure(text="Descarga cancelada")
        self.status_label.configure(
            text="Los archivos parciales (.part) se reanudarán si vuelves a descargar."
        )
        self._log("■ Descarga cancelada")

    def _set_running(self, running: bool) -> None:
        self.download_button.configure(
            state="disabled" if running else "normal",
            text="Descargando…" if running else "Descargar",
        )
        self.cancel_button.configure(state="normal" if running else "disabled")

    def _set_indeterminate(self, on: bool) -> None:
        if on == self._indeterminate:
            return
        self._indeterminate = on
        if on:
            self.progress.configure(mode="indeterminate")
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")

    def _reset_progress(self) -> None:
        self._set_indeterminate(False)
        self.progress.set(0)
        self.percent_label.configure(text="0 %")
        self.speed_label.configure(text="Velocidad: —")
        self.eta_label.configure(text="Restante: —")

    def _log(self, line: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _on_close(self) -> None:
        if self._worker and self._worker.is_alive():
            if not messagebox.askyesno(APP_NAME, "Hay una descarga en curso. ¿Cancelarla y salir?"):
                return
            self._cancel_event.set()
        self.destroy()


def run() -> None:
    DownloaderApp().mainloop()
