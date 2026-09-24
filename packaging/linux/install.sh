#!/usr/bin/env bash
# Instalador de Media Downloader para Linux (usuario actual).
#
# Se ejecuta desde la carpeta descomprimida de MediaDownloader-linux.tar.gz:
#     ./install.sh              instala (pide sudo solo si hay que instalar FFmpeg)
#     ./install.sh -y           sin preguntas (para scripts)
#     ./install.sh --no-desktop no crea el acceso directo en el Escritorio
#     ./install.sh --no-ffmpeg  no instala FFmpeg
#     ./install.sh --uninstall  desinstala (conserva configuración y cola)
#     ./install.sh --uninstall --purge   desinstala y borra también esos datos
#
# Qué hace:
#   1. Instala FFmpeg con el gestor de paquetes (apt, dnf, pacman o zypper) si falta.
#   2. Copia la aplicación a ~/.local/share/media-downloader/app y crea el comando
#      ~/.local/bin/MediaDownloader.
#   3. Registra el icono y el lanzador .desktop en el menú de aplicaciones y en el Escritorio.
set -euo pipefail

APP_ID="media-downloader"
APP_NAME="Media Downloader"
WM_CLASS="MediaDownloader"      # debe coincidir con className en app/gui.py
COMMENT="Descarga música, videos y torrents"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$HERE/MediaDownloader"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_HOME="$DATA_HOME/$APP_ID"
INSTALL_DIR="$APP_HOME/app"
BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/MediaDownloader"
APPS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/256x256/apps"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
[[ -z "$DESKTOP_DIR" || "$DESKTOP_DIR" == "$HOME" ]] && DESKTOP_DIR="$HOME/Desktop"

ASSUME_YES=0; WITH_DESKTOP=1; WITH_FFMPEG=1; UNINSTALL=0; PURGE=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes)     ASSUME_YES=1 ;;
        --no-desktop) WITH_DESKTOP=0 ;;
        --no-ffmpeg)  WITH_FFMPEG=0 ;;
        --uninstall)  UNINSTALL=1 ;;
        --purge)      PURGE=1 ;;
        -h|--help)    sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)            echo "Opción desconocida: $1 (usa --help)" >&2; exit 1 ;;
    esac
    shift
done

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33maviso:\033[0m %s\n' "$*" >&2; }

# ------------------------------------------------------------------ desinstalar
if [[ $UNINSTALL -eq 1 ]]; then
    say "Desinstalando $APP_NAME"
    rm -rf "$INSTALL_DIR"
    rm -f "$LAUNCHER" "$APPS_DIR/$APP_ID.desktop" "$DESKTOP_DIR/$APP_ID.desktop" "$ICON_DIR/$APP_ID.png"
    if [[ $PURGE -eq 1 ]]; then
        rm -rf "$APP_HOME" "$HOME/.media_downloader.json"
        say "Configuración, cola y registros eliminados"
    else
        rmdir "$APP_HOME" 2>/dev/null || say "Se conservan la configuración y la cola en $APP_HOME (usa --purge para borrarlas)"
    fi
    command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" 2>/dev/null || true
    say "Listo. FFmpeg no se desinstala (puede usarlo otro programa)."
    exit 0
fi

# ---------------------------------------------------------------------- FFmpeg
install_ffmpeg() {
    if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
        say "FFmpeg ya está instalado: $(command -v ffmpeg)"
        return
    fi
    local sudo=""
    if [[ $(id -u) -ne 0 ]]; then
        if command -v sudo >/dev/null; then sudo="sudo"; else
            warn "FFmpeg no está instalado y no hay sudo. Instálalo con el gestor de paquetes y vuelve a ejecutar."
            return
        fi
    fi
    local yes=(); [[ $ASSUME_YES -eq 1 ]] && yes=(-y)
    say "Instalando FFmpeg (se pedirá tu contraseña de administrador)"
    if command -v apt-get >/dev/null; then
        $sudo apt-get update && $sudo apt-get install "${yes[@]}" ffmpeg
    elif command -v dnf >/dev/null; then
        # Fedora trae «ffmpeg-free» en sus repositorios; «ffmpeg» completo viene de RPM Fusion.
        $sudo dnf install "${yes[@]}" ffmpeg || $sudo dnf install "${yes[@]}" ffmpeg-free
    elif command -v pacman >/dev/null; then
        local noconfirm=(); [[ $ASSUME_YES -eq 1 ]] && noconfirm=(--noconfirm)
        $sudo pacman -S --needed "${noconfirm[@]}" ffmpeg
    elif command -v zypper >/dev/null; then
        local nonint=(); [[ $ASSUME_YES -eq 1 ]] && nonint=(--non-interactive)
        $sudo zypper "${nonint[@]}" install ffmpeg || $sudo zypper "${nonint[@]}" install ffmpeg-7
    else
        warn "Gestor de paquetes no reconocido: instala FFmpeg manualmente."
        return
    fi
    command -v ffmpeg >/dev/null || warn "No se pudo instalar FFmpeg; la app avisará al descargar."
}

# ------------------------------------------------------------------- aplicación
[[ -x "$SOURCE_DIR/MediaDownloader" ]] || {
    echo "No se encontró $SOURCE_DIR/MediaDownloader." >&2
    echo "Ejecuta install.sh desde la carpeta descomprimida de MediaDownloader-linux.tar.gz." >&2
    exit 1
}
[[ $WITH_FFMPEG -eq 1 ]] && install_ffmpeg

say "Copiando la aplicación a $INSTALL_DIR"
mkdir -p "$APP_HOME" "$BIN_DIR" "$APPS_DIR" "$ICON_DIR"
rm -rf "$INSTALL_DIR.new"
cp -a "$SOURCE_DIR" "$INSTALL_DIR.new"
rm -rf "$INSTALL_DIR"
mv "$INSTALL_DIR.new" "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/MediaDownloader"
ln -sfn "$INSTALL_DIR/MediaDownloader" "$LAUNCHER"

# Escapa un argumento para Exec según la especificación Desktop Entry (ver
# scripts/install_shortcuts_linux.sh): nivel comillas y después nivel cadena.
exec_quote() {
    local s="$1"
    s="${s//\\/\\\\}"; s="${s//\"/\\\"}"; s="${s//\`/\\\`}"; s="${s//\$/\\\$}"; s="${s//%/%%}"
    s="${s//\\/\\\\}"
    printf '"%s"' "$s"
}

cp "$INSTALL_DIR/_internal/assets/icon.png" "$ICON_DIR/$APP_ID.png"
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$DATA_HOME/icons/hicolor" 2>/dev/null || true

write_desktop_file() {
    cat > "$1" <<EOF
[Desktop Entry]
Type=Application
Version=1.5
Name=$APP_NAME
Comment=$COMMENT
Exec=$(exec_quote "$INSTALL_DIR/MediaDownloader")
Path=$INSTALL_DIR
Icon=$ICON_DIR/$APP_ID.png
Terminal=false
Categories=AudioVideo;Audio;Video;Network;
Keywords=youtube;download;mp3;mp4;music;video;torrent;magnet;
StartupNotify=true
StartupWMClass=$WM_CLASS
EOF
    chmod +x "$1"
}

say "Registrando el lanzador en el menú de aplicaciones"
write_desktop_file "$APPS_DIR/$APP_ID.desktop"
if [[ $WITH_DESKTOP -eq 1 ]]; then
    mkdir -p "$DESKTOP_DIR"
    write_desktop_file "$DESKTOP_DIR/$APP_ID.desktop"
    # GNOME/Nautilus exige marcarlo como confiable para poder abrirlo con doble clic.
    command -v gio >/dev/null && gio set "$DESKTOP_DIR/$APP_ID.desktop" metadata::trusted true 2>/dev/null || true
    say "Acceso directo creado en $DESKTOP_DIR"
fi
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" 2>/dev/null || true

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR no está en tu PATH: abre la app desde el menú o añade esa carpeta al PATH." ;;
esac
say "Instalado. Ábrelo desde el menú de aplicaciones o con: MediaDownloader"
