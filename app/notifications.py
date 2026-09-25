"""Notificaciones nativas de escritorio, sin dependencias externas.

- **Windows 10/11:** notificaciones del sistema (API WinRT de Windows) lanzadas con
  PowerShell. Windows solo muestra notificaciones de aplicaciones sin empaquetar si su
  identificador (AppUserModelID) está registrado: el instalador lo registra en
  ``Software\\Classes\\AppUserModelId\\MediaDownloader.App`` y la app lo crea si falta
  (p. ej. al ejecutarla desde el código fuente).
- **Linux:** ``notify-send`` (libnotify) o, si no está, ``gdbus`` contra el servicio
  estándar ``org.freedesktop.Notifications``.
- **macOS:** ``osascript``.

Se muestran en segundo plano y nunca lanzan excepciones: si el sistema no puede mostrar
la notificación, solo se registra en el log.
"""
from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from xml.sax.saxutils import escape

log = logging.getLogger(__name__)

APP_ID = "MediaDownloader.App"          # el mismo que usa main.set_windows_app_id()
APP_NAME = "Media Downloader"
_REGISTRY_KEY = rf"Software\Classes\AppUserModelId\{APP_ID}"


# --------------------------------------------------------------------------- #
# Windows
# --------------------------------------------------------------------------- #
def register_windows_app_id(icon: Path) -> None:
    """Registra el identificador de la app para que Windows acepte sus notificaciones."""
    if sys.platform != "win32":
        return
    try:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _REGISTRY_KEY) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
            if icon.is_file():
                winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(icon))
    except OSError:
        log.warning("No se pudo registrar %s para las notificaciones", APP_ID, exc_info=True)


def windows_toast_script(title: str, message: str, app_id: str = APP_ID) -> str:
    """Script de PowerShell que muestra la notificación (texto escapado para XML y PS)."""
    xml = (
        '<toast><visual><binding template="ToastGeneric">'
        f"<text>{escape(title)}</text><text>{escape(message)}</text>"
        "</binding></visual></toast>"
    ).replace("'", "''")                          # comillas simples dentro de '…' en PowerShell
    return (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null;"
        "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument;"
        f"$xml.LoadXml('{xml}');"
        "$toast = New-Object Windows.UI.Notifications.ToastNotification $xml;"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{app_id}').Show($toast)"
    )


def windows_command(title: str, message: str) -> list[str]:
    # -EncodedCommand (UTF-16LE en base64) evita cualquier problema de comillas o acentos.
    encoded = base64.b64encode(windows_toast_script(title, message).encode("utf-16-le")).decode("ascii")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden", "-EncodedCommand", encoded]


# --------------------------------------------------------------------------- #
# Linux / macOS
# --------------------------------------------------------------------------- #
def linux_command(title: str, message: str, icon: Path | None = None) -> list[str] | None:
    if shutil.which("notify-send"):
        command = ["notify-send", "--app-name", APP_NAME]
        if icon and icon.is_file():
            command += ["--icon", str(icon)]
        return command + [title, message]
    if shutil.which("gdbus"):
        return ["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
                "--object-path", "/org/freedesktop/Notifications",
                "--method", "org.freedesktop.Notifications.Notify",
                APP_NAME, "0", str(icon or ""), title, message, "[]", "{}", "5000"]
    return None


def macos_command(title: str, message: str) -> list[str]:
    def quote(text: str) -> str:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return ["osascript", "-e", f"display notification {quote(message)} with title {quote(title)}"]


# --------------------------------------------------------------------------- #
def build_command(title: str, message: str, icon: Path | None = None) -> list[str] | None:
    if sys.platform == "win32":
        return windows_command(title, message)
    if sys.platform == "darwin":
        return macos_command(title, message)
    return linux_command(title, message, icon)


def notify(title: str, message: str, icon: Path | None = None) -> None:
    """Muestra la notificación en un hilo aparte. Nunca lanza excepciones."""
    def run() -> None:
        command = build_command(title, message, icon)
        if command is None:
            log.info("Notificación no disponible en este sistema: %s — %s", title, message)
            return
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30, creationflags=flags)
        except (OSError, subprocess.SubprocessError):
            log.warning("No se pudo mostrar la notificación", exc_info=True)
            return
        if result.returncode != 0:
            log.warning("La notificación falló (%d): %s", result.returncode, (result.stderr or "").strip()[:300])

    threading.Thread(target=run, daemon=True, name="notificacion").start()
