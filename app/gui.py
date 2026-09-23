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
from app.paths import log_file_path, resource_path
from app.core import (
    DownloadCancelledError,
    DownloaderError,
    DownloadRequest,
    DownloadResult,
    DownloadStage,
    DownloadType,
    ProgressInfo,
    QualityOption,
    available_sources,
    default_user_agent,
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
AUTO_QUALITY = "Máxima disponible (automática)"
ROW_HEADER, ROW_INPUT, ROW_WEB, ROW_PROGRESS, ROW_ACTIONS, ROW_LOG = range(6)


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


def open_path(path: Path) -> None:
    """Abre una carpeta o un archivo con la aplicación predeterminada del sistema."""
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
        self.geometry("800x820")
        self.minsize(680, 520)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        # Contenedor con scroll: en pantallas bajas (p. ej. 1366x768) nada queda fuera.
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        self.body.grid(row=0, column=0, sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)

        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()   # activo = descarga en pausa
        self._downloading = False
        self._last_stage: DownloadStage | None = None
        self._worker: threading.Thread | None = None
        self._indeterminate = False
        # Calidades analizadas: etiqueta → altura máxima (None = automática), y para qué URL.
        self._quality_map: dict[str, int | None] = {AUTO_QUALITY: None}
        self._qualities_url: str | None = None

        default_dir = Path(self._settings.get("output_dir") or Path.home() / "Downloads")
        self.output_dir = ctk.StringVar(value=str(default_dir))
        saved_type = self._settings.get("download_type")
        self.download_type = ctk.StringVar(
            value=saved_type if saved_type in TYPE_BY_LABEL else DownloadType.MP3.value
        )
        self.allow_playlist = ctk.BooleanVar(value=self._settings.get("allow_playlist", True))
        self.quality = ctk.StringVar(value=AUTO_QUALITY)
        self.user_agent = ctk.StringVar(value=self._settings.get("user_agent") or default_user_agent())
        self.referer = ctk.StringVar()
        self.filename = ctk.StringVar()
        self.subtitles = ctk.BooleanVar(value=self._settings.get("subtitles", False))
        self.subtitle_langs = ctk.StringVar(value=self._settings.get("subtitle_langs", "es, en"))

        self._build_header()
        self._build_input_card()
        self._build_web_card()
        self._build_progress_card()
        self._build_actions()
        self._build_log()

        self._on_type_change(self.download_type.get())
        self._on_subtitles_toggle()
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
        frame = ctk.CTkFrame(self.body, corner_radius=12)
        frame.grid(row=row, column=0, sticky="nsew", padx=20, pady=(0, 14))
        frame.grid_columnconfigure(1, weight=1)
        return frame

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self.body, fg_color="transparent")
        header.grid(row=ROW_HEADER, column=0, sticky="ew", padx=20, pady=(18, 12))
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
        card = self._card(ROW_INPUT)
        pad = {"padx": 14, "pady": 8}

        ctk.CTkLabel(card, text="Enlace").grid(row=0, column=0, sticky="w", **pad)
        self.url_entry = ctk.CTkEntry(
            card, height=36,
            placeholder_text="YouTube, página de video, enlace .m3u8 o .mp4…",
        )
        self.url_entry.grid(row=0, column=1, sticky="ew", pady=(14, 8))
        self.url_entry.bind("<Return>", lambda _e: self._start_download())
        self.url_entry.bind("<KeyRelease>", lambda _e: self._on_url_changed())
        ctk.CTkButton(card, text="Pegar", width=80, command=self._paste_url).grid(
            row=0, column=2, padx=14, pady=(14, 8)
        )

        ctk.CTkLabel(card, text="Formato").grid(row=1, column=0, sticky="w", **pad)
        ctk.CTkOptionMenu(
            card, values=list(TYPE_BY_LABEL), variable=self.download_type, height=34,
            dynamic_resizing=False, command=self._on_type_change,
        ).grid(row=1, column=1, sticky="ew", pady=8)

        # Calidad: solo para video. «Analizar» consulta las resoluciones disponibles.
        self.quality_label = ctk.CTkLabel(card, text="Calidad")
        self.quality_label.grid(row=2, column=0, sticky="w", **pad)
        self.quality_menu = ctk.CTkOptionMenu(
            card, values=[AUTO_QUALITY], variable=self.quality, height=34, dynamic_resizing=False,
        )
        self.quality_menu.grid(row=2, column=1, sticky="ew", pady=8)
        self.analyze_button = ctk.CTkButton(
            card, text="Analizar", width=80, command=self._start_analyze,
        )
        self.analyze_button.grid(row=2, column=2, padx=14, pady=8)

        # Subtítulos: solo para video. Se incrustan en el MP4 y se guarda también el .srt.
        self.subtitles_label = ctk.CTkLabel(card, text="Subtítulos")
        self.subtitles_label.grid(row=3, column=0, sticky="w", **pad)
        self.subtitles_row = ctk.CTkFrame(card, fg_color="transparent")
        self.subtitles_row.grid(row=3, column=1, columnspan=2, sticky="ew", pady=4, padx=(0, 14))
        self.subtitles_row.grid_columnconfigure(2, weight=1)
        ctk.CTkCheckBox(
            self.subtitles_row, text="Descargar e incrustar (incluye automáticos)",
            variable=self.subtitles, command=self._on_subtitles_toggle,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(self.subtitles_row, text="Idiomas").grid(row=0, column=1, padx=(16, 6))
        self.subtitle_langs_entry = ctk.CTkEntry(
            self.subtitles_row, textvariable=self.subtitle_langs, height=30, width=140,
            placeholder_text="es, en  o  all",
        )
        self.subtitle_langs_entry.grid(row=0, column=2, sticky="w")

        ctk.CTkCheckBox(
            card, text="Descargar lista completa", variable=self.allow_playlist,
        ).grid(row=4, column=1, sticky="w", pady=(4, 8))

        ctk.CTkLabel(card, text="Destino").grid(row=5, column=0, sticky="w", **pad)
        folder = ctk.CTkEntry(card, textvariable=self.output_dir, height=34, state="readonly")
        folder.grid(row=5, column=1, sticky="ew", pady=(8, 14))
        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.grid(row=5, column=2, padx=14, pady=(8, 14))
        ctk.CTkButton(buttons, text="Cambiar…", width=80, command=self._choose_folder).pack(
            side="left"
        )
        ctk.CTkButton(
            buttons, text="Abrir", width=60, fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"), command=self._open_output_dir,
        ).pack(side="left", padx=(6, 0))

    def _build_web_card(self) -> None:
        """Opciones para películas / video web: cabeceras HTTP y nombre del archivo."""
        card = self._card(ROW_WEB)
        self.web_card = card
        pad = {"padx": 14, "pady": 6}

        ctk.CTkLabel(
            card, text="Opciones de video web", font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(12, 2))

        ctk.CTkLabel(card, text="User-Agent").grid(row=1, column=0, sticky="w", **pad)
        ctk.CTkEntry(card, textvariable=self.user_agent, height=32).grid(
            row=1, column=1, sticky="ew", pady=6
        )
        ctk.CTkButton(
            card, text="Restablecer", width=80, fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"),
            command=lambda: self.user_agent.set(default_user_agent()),
        ).grid(row=1, column=2, padx=14, pady=6)

        ctk.CTkLabel(card, text="Referer").grid(row=2, column=0, sticky="w", **pad)
        ctk.CTkEntry(
            card, textvariable=self.referer, height=32,
            placeholder_text="https://pagina-donde-se-reproduce-el-video/…  (opcional)",
        ).grid(row=2, column=1, columnspan=2, sticky="ew", pady=6, padx=(0, 14))

        ctk.CTkLabel(card, text="Nombre").grid(row=3, column=0, sticky="w", **pad)
        ctk.CTkEntry(
            card, textvariable=self.filename, height=32,
            placeholder_text="Nombre del archivo, sin extensión  (opcional)",
        ).grid(row=3, column=1, columnspan=2, sticky="ew", pady=6, padx=(0, 14))

        ctk.CTkLabel(
            card, anchor="w", justify="left", text_color=("gray40", "gray65"),
            text=(
                "Si la web bloquea la descarga, pon en Referer la dirección de la página del "
                "reproductor. Para enlaces .m3u8: F12 → Red → filtra «m3u8»."
            ),
            wraplength=680,
        ).grid(row=4, column=0, columnspan=3, sticky="ew", padx=14, pady=(2, 12))

    def _build_progress_card(self) -> None:
        card = self._card(ROW_PROGRESS)
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
        bar = ctk.CTkFrame(self.body, fg_color="transparent")
        bar.grid(row=ROW_ACTIONS, column=0, sticky="ew", padx=20, pady=(0, 14))
        bar.grid_columnconfigure(0, weight=1)

        self.download_button = ctk.CTkButton(
            bar, text="Descargar", height=42, font=ctk.CTkFont(size=15, weight="bold"),
            command=self._start_download,
        )
        self.download_button.grid(row=0, column=0, sticky="ew")
        self.pause_button = ctk.CTkButton(
            bar, text="Pausar", height=42, width=120, state="disabled",
            fg_color=("#d68910", "#b9770e"), hover_color=("#b9770e", "#9c640c"),
            command=self._toggle_pause,
        )
        self.pause_button.grid(row=0, column=1, padx=(10, 0))
        self.cancel_button = ctk.CTkButton(
            bar, text="Cancelar", height=42, width=120, state="disabled",
            fg_color=("#c0392b", "#a93226"), hover_color=("#a93226", "#922b21"),
            command=self._cancel_download,
        )
        self.cancel_button.grid(row=0, column=2, padx=(10, 0))

    def _build_log(self) -> None:
        frame = ctk.CTkFrame(self.body, fg_color="transparent")
        frame.grid(row=ROW_LOG, column=0, sticky="nsew", padx=20, pady=(0, 18))
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            frame, text="Actividad", font=ctk.CTkFont(size=13, weight="bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))
        ctk.CTkButton(
            frame, text="Abrir archivo de logs", width=150, height=28,
            fg_color="transparent", border_width=1, text_color=("gray10", "gray90"),
            command=self._open_log_file,
        ).grid(row=0, column=1, sticky="e", pady=(0, 4))
        self.log_box = ctk.CTkTextbox(frame, height=110, corner_radius=12, state="disabled")
        self.log_box.grid(row=1, column=0, columnspan=2, sticky="nsew")

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
        self._on_url_changed()

    def _on_type_change(self, label: str) -> None:
        download_type = TYPE_BY_LABEL[label]
        quality_widgets = (
            self.quality_label, self.quality_menu, self.analyze_button,
            self.subtitles_label, self.subtitles_row,
        )
        for widget in quality_widgets:
            if download_type.is_video:
                widget.grid()
            else:
                widget.grid_remove()
        if download_type is DownloadType.WEB_VIDEO:
            self.web_card.grid()
        else:
            self.web_card.grid_remove()

    def _on_subtitles_toggle(self) -> None:
        self.subtitle_langs_entry.configure(state="normal" if self.subtitles.get() else "disabled")

    def _open_log_file(self) -> None:
        path = log_file_path()
        for handler in logging.getLogger().handlers:
            handler.flush()
        try:
            path.touch(exist_ok=True)
            open_path(path)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"No se pudo abrir el archivo de logs:\n{path}\n\n{exc}")

    def _on_url_changed(self) -> None:
        """Las calidades analizadas dejan de valer si cambia el enlace."""
        if self._qualities_url and self.url_entry.get().strip() != self._qualities_url:
            self._set_qualities(None, [])

    def _set_qualities(self, url: str | None, options: list[QualityOption]) -> None:
        self._qualities_url = url
        self._quality_map = {AUTO_QUALITY: None} | {o.label: o.max_height for o in options}
        self.quality_menu.configure(values=list(self._quality_map))
        self.quality.set(AUTO_QUALITY)

    def _selected_quality(self, url: str) -> int | None:
        if url != self._qualities_url:
            return None
        return self._quality_map.get(self.quality.get())

    def _build_request(self) -> DownloadRequest:
        url = self.url_entry.get().strip()
        download_type = TYPE_BY_LABEL[self.download_type.get()]
        headers: dict[str, str] = {}
        filename = None
        if download_type is DownloadType.WEB_VIDEO:
            if self.user_agent.get().strip():
                headers["User-Agent"] = self.user_agent.get().strip()
            if self.referer.get().strip():
                headers["Referer"] = self.referer.get().strip()
            filename = self.filename.get().strip() or None
        return DownloadRequest(
            url=url,
            output_dir=Path(self.output_dir.get()),
            download_type=download_type,
            allow_playlist=self.allow_playlist.get(),
            quality=self._selected_quality(url) if download_type.is_video else None,
            headers=headers,
            filename=filename,
            subtitles=download_type.is_video and self.subtitles.get(),
            subtitle_langs=self._parse_subtitle_langs(),
        )

    def _parse_subtitle_langs(self) -> tuple[str, ...]:
        raw = self.subtitle_langs.get().replace(";", ",").replace(" ", ",")
        codes = tuple(code for code in (c.strip().lower() for c in raw.split(",")) if code)
        return codes or ("es", "en")

    def _start_analyze(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        request = self._build_request()
        try:
            downloader = get_downloader(request.url, request.download_type)
        except DownloaderError as exc:
            messagebox.showerror(exc.title, str(exc))
            return
        self._set_running(True, analyzing=True)
        self._reset_progress()
        self._set_indeterminate(True)
        self.status_label.configure(text=f"Analizando calidades ({downloader.name})…")
        self._worker = threading.Thread(
            target=self._run_analyze, args=(downloader, request), daemon=True
        )
        self._worker.start()

    def _run_analyze(self, downloader, request: DownloadRequest) -> None:
        """Hilo secundario: consulta las calidades sin descargar nada."""
        try:
            options = downloader.list_qualities(request)
            self._events.put(("qualities", (request.url, options)))
        except DownloaderError as exc:
            log.warning("Análisis fallido: %s | %s", exc, exc.detail)
            self._events.put(("analyze_error", exc))
        except Exception as exc:
            log.exception("Error inesperado al analizar")
            self._events.put(("analyze_error", DownloaderError(f"Error inesperado: {exc}")))

    def _choose_folder(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.output_dir.get(), title="Carpeta de destino")
        if chosen:
            self.output_dir.set(str(Path(chosen)))

    def _open_output_dir(self) -> None:
        path = Path(self.output_dir.get())
        if path.is_dir():
            open_path(path)
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
        request = self._build_request()
        try:
            # Valida la URL y elige el proveedor antes de lanzar el hilo.
            downloader = get_downloader(request.url, request.download_type)
        except DownloaderError as exc:
            messagebox.showerror(exc.title, str(exc))
            return

        self._settings.update(
            output_dir=str(request.output_dir),
            download_type=request.download_type.value,
            allow_playlist=request.allow_playlist,
            subtitles=self.subtitles.get(),
            subtitle_langs=self.subtitle_langs.get(),
        )
        if self.user_agent.get().strip() not in ("", default_user_agent()):
            self._settings["user_agent"] = self.user_agent.get().strip()
        else:
            self._settings.pop("user_agent", None)
        save_settings(self._settings)

        self._cancel_event.clear()
        self._pause_event.clear()
        self._set_running(True)
        self._reset_progress()
        quality = f" · ≤{request.quality}p" if request.quality else ""
        if request.subtitles:
            quality += f" · subtítulos {','.join(request.subtitle_langs)}"
        self._log(f"→ {request.download_type.value}{quality} [{downloader.name}]: {request.url}")
        self._worker = threading.Thread(
            target=self._run_download, args=(downloader, request), daemon=True
        )
        self._worker.start()

    def _run_download(self, downloader, request: DownloadRequest) -> None:
        """Se ejecuta en el hilo secundario: nunca toca widgets directamente."""
        try:
            result = downloader.download(
                request,
                lambda info: self._events.put(("progress", info)),
                self._cancel_event,
                self._pause_event,
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

    def _toggle_pause(self) -> None:
        if not self._downloading:
            return
        if self._pause_event.is_set():
            self._pause_event.clear()
            self.pause_button.configure(text="Pausar")
            self.status_label.configure(text="Reanudando…")
            self._log("▶ Descarga reanudada")
            log.info("Usuario: reanudar")
        else:
            self._pause_event.set()
            self.pause_button.configure(text="Reanudar")
            self._set_indeterminate(False)
            self.speed_label.configure(text="Velocidad: —")
            self.eta_label.configure(text="Restante: —")
            if self._last_stage is DownloadStage.PROCESSING:
                self.status_label.configure(text="Se pausará al terminar el paso de FFmpeg en curso…")
            else:
                self.status_label.configure(text="En pausa · lo ya descargado se conserva")
            self._log("⏸ Descarga en pausa")
            log.info("Usuario: pausar")

    def _cancel_download(self) -> None:
        self._cancel_event.set()
        self._pause_event.clear()
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
                elif kind == "qualities":
                    self._on_qualities(*payload)  # type: ignore[misc]
                elif kind == "analyze_error":
                    self._on_error(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.after(POLL_MS, self._poll_events)

    def _apply_progress(self, p: ProgressInfo) -> None:
        if p.stage is DownloadStage.PAUSED:
            self.status_label.configure(text="En pausa · lo ya descargado se conserva")
            return
        if self._pause_event.is_set() and p.stage is not DownloadStage.ITEM_DONE:
            return   # hilos de segmentos que informan antes de detenerse
        self._last_stage = p.stage
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
                f"{summary}\n\nHubo {len(result.failed)} error(es) durante la descarga. "
                "Revisa el archivo de logs para más detalles.",
            )

    def _on_qualities(self, url: str, options: list[QualityOption]) -> None:
        self._set_running(False)
        self._reset_progress()
        self._set_qualities(url, options)
        if options:
            labels = ", ".join(o.label for o in options)
            self.status_label.configure(text=f"Calidades disponibles: {labels}")
            self._log(f"ℹ Calidades: {labels}")
        else:
            self.status_label.configure(
                text="No se pudieron determinar calidades; se usará la máxima disponible."
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

    def _set_running(self, running: bool, analyzing: bool = False) -> None:
        self._downloading = running and not analyzing
        if not running:
            self._pause_event.clear()
            self._last_stage = None
        busy_text = "Analizando…" if analyzing else "Descargando…"
        self.download_button.configure(
            state="disabled" if running else "normal",
            text=busy_text if running else "Descargar",
        )
        self.analyze_button.configure(state="disabled" if running else "normal")
        # El análisis es corto y no admite pausa ni cancelación.
        self.cancel_button.configure(state="normal" if self._downloading else "disabled")
        self.pause_button.configure(
            state="normal" if self._downloading else "disabled", text="Pausar",
        )

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
            self._pause_event.clear()
        self.destroy()


def run() -> None:
    DownloaderApp().mainloop()
