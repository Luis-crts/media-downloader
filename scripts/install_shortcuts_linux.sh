#!/usr/bin/env bash
# Crea (o elimina) el lanzador .desktop de Media Downloader en el menú de
# aplicaciones (~/.local/share/applications) y en el Escritorio del usuario.
#
# Busca el ejecutable en este orden:
#   1. --target RUTA
#   2. dist/MediaDownloader/MediaDownloader   (build --onedir)
#   3. dist/MediaDownloader                   (build --onefile)
#   4. .venv/bin/python main.py               (modo código fuente)
#
# Uso:
#   ./scripts/install_shortcuts_linux.sh
#   ./scripts/install_shortcuts_linux.sh --no-desktop
#   ./scripts/install_shortcuts_linux.sh --target /opt/MediaDownloader/MediaDownloader
#   ./scripts/install_shortcuts_linux.sh --uninstall
set -euo pipefail

APP_ID="media-downloader"
APP_NAME="Media Downloader"
WM_CLASS="MediaDownloader"   # debe coincidir con className en app/gui.py
COMMENT="Descarga música y videos de YouTube"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APPS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/256x256/apps"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
[[ -z "$DESKTOP_DIR" || "$DESKTOP_DIR" == "$HOME" ]] && DESKTOP_DIR="$HOME/Desktop"

TARGET=""
WITH_DESKTOP=1
UNINSTALL=0

usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)     TARGET="${2:?--target requiere una ruta}"; shift 2 ;;
        --no-desktop) WITH_DESKTOP=0; shift ;;
        --uninstall)  UNINSTALL=1; shift ;;
        -h|--help)    usage 0 ;;
        *)            echo "Opción desconocida: $1" >&2; usage 1 ;;
    esac
done

LAUNCHER_FILES=("$APPS_DIR/$APP_ID.desktop")
[[ $WITH_DESKTOP -eq 1 ]] && LAUNCHER_FILES+=("$DESKTOP_DIR/$APP_ID.desktop")

if [[ $UNINSTALL -eq 1 ]]; then
    for f in "${LAUNCHER_FILES[@]}" "$ICON_DIR/$APP_ID.png"; do
        [[ -e "$f" ]] && rm -f "$f" && echo "Eliminado: $f"
    done
    command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" 2>/dev/null || true
    exit 0
fi

# Escapa un argumento para la clave Exec según la especificación Desktop Entry:
#  1. nivel comillas: se escapan \ " ` $ con una barra y se duplican los %;
#  2. nivel cadena: se duplican todas las barras (p. ej. un $ literal queda \\$).
exec_quote() {
    local s="$1"
    s="${s//\\/\\\\}"; s="${s//\"/\\\"}"; s="${s//\`/\\\`}"; s="${s//\$/\\\$}"; s="${s//%/%%}"
    s="${s//\\/\\\\}"
    printf '"%s"' "$s"
}

if [[ -n "$TARGET" ]]; then
    [[ -f "$TARGET" ]] || { echo "No existe el ejecutable: $TARGET" >&2; exit 1; }
    TARGET="$(cd "$(dirname "$TARGET")" && pwd)/$(basename "$TARGET")"
    EXEC_LINE="$(exec_quote "$TARGET")"
    WORK_DIR="$(dirname "$TARGET")"
elif [[ -f "$PROJECT_ROOT/dist/MediaDownloader/MediaDownloader" ]]; then
    TARGET="$PROJECT_ROOT/dist/MediaDownloader/MediaDownloader"
    EXEC_LINE="$(exec_quote "$TARGET")"
    WORK_DIR="$(dirname "$TARGET")"
elif [[ -f "$PROJECT_ROOT/dist/MediaDownloader" ]]; then
    TARGET="$PROJECT_ROOT/dist/MediaDownloader"
    EXEC_LINE="$(exec_quote "$TARGET")"
    WORK_DIR="$(dirname "$TARGET")"
elif [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
    echo "Aviso: no hay ejecutable compilado; se usará .venv/bin/python main.py" >&2
    TARGET="$PROJECT_ROOT/.venv/bin/python"
    EXEC_LINE="$(exec_quote "$TARGET") $(exec_quote "$PROJECT_ROOT/main.py")"
    WORK_DIR="$PROJECT_ROOT"
else
    echo "No se encontró la aplicación. Compila con 'python3 build.py' o crea .venv (ver README)." >&2
    exit 1
fi
chmod +x "$TARGET"

# Icono: se instala en el tema hicolor del usuario.
mkdir -p "$APPS_DIR" "$ICON_DIR"
cp "$PROJECT_ROOT/assets/icon.png" "$ICON_DIR/$APP_ID.png"
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$DATA_HOME/icons/hicolor" 2>/dev/null || true

write_desktop_file() {
    cat > "$1" <<EOF
[Desktop Entry]
Type=Application
Version=1.5
Name=$APP_NAME
Comment=$COMMENT
Exec=$EXEC_LINE
Path=$WORK_DIR
Icon=$ICON_DIR/$APP_ID.png
Terminal=false
Categories=AudioVideo;Audio;Video;Network;
Keywords=youtube;download;mp3;mp4;music;video;
StartupNotify=true
StartupWMClass=$WM_CLASS
EOF
    chmod +x "$1"
    echo "Creado: $1"
}

write_desktop_file "$APPS_DIR/$APP_ID.desktop"

if [[ $WITH_DESKTOP -eq 1 ]]; then
    mkdir -p "$DESKTOP_DIR"
    write_desktop_file "$DESKTOP_DIR/$APP_ID.desktop"
    # GNOME/Nautilus exige marcar el lanzador como confiable para poder abrirlo.
    command -v gio >/dev/null && gio set "$DESKTOP_DIR/$APP_ID.desktop" metadata::trusted true 2>/dev/null || true
fi

command -v desktop-file-validate >/dev/null && desktop-file-validate "$APPS_DIR/$APP_ID.desktop" || true
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" 2>/dev/null || true

echo "Listo. Destino: $EXEC_LINE"
