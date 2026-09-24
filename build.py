"""Compila la aplicación con PyInstaller (Windows y Linux).

Uso:
    python build.py                    # carpeta distribuible (--onedir), recomendado
    python build.py --onefile          # un único ejecutable
    python build.py --embed-ffmpeg     # incluye ffmpeg/ffprobe dentro del paquete
    python build.py --installer        # Windows: además, dist/MediaDownloader_Setup.exe (Inno Setup)

Resultado:
    --onedir   dist/MediaDownloader/MediaDownloader(.exe)
    --onefile  dist/MediaDownloader(.exe)
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "MediaDownloader"
EXE = ".exe" if os.name == "nt" else ""
SEP = os.pathsep  # separador origen/destino de --add-data: ';' en Windows, ':' en Linux


def locate_ffmpeg_pair() -> tuple[Path, Path]:
    """Busca ffmpeg y ffprobe en ./bin o en el PATH."""
    found = []
    for tool in ("ffmpeg", "ffprobe"):
        local = ROOT / "bin" / f"{tool}{EXE}"
        path = local if local.is_file() else shutil.which(tool)
        if not path:
            sys.exit(f"[build] No se encontró {tool}. Instálalo o cópialo en ./bin para usar --embed-ffmpeg.")
        found.append(Path(path).resolve())
    return found[0], found[1]


def pyinstaller_args(onefile: bool, embed_ffmpeg: bool) -> list[str]:
    args = [
        str(ROOT / "main.py"),
        "--name", APP_NAME,
        "--onefile" if onefile else "--onedir",
        "--windowed",                          # sin consola de fondo (equivale a --noconsole / -w)
        "--noconfirm",
        "--clean",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),     # el .spec generado no ensucia la raíz
        # Iconos de la ventana, accesibles en tiempo de ejecución vía sys._MEIPASS/assets
        # (icon_source.png solo sirve para generarlos: no se empaqueta).
        "--add-data", f"{ROOT / 'assets' / 'icon.ico'}{SEP}assets",
        "--add-data", f"{ROOT / 'assets' / 'icon.png'}{SEP}assets",
        # Temas/fuentes JSON de CustomTkinter y scripts JS de yt-dlp-ejs
        "--collect-data", "customtkinter",
        "--collect-data", "yt_dlp_ejs",
    ]
    if sys.platform == "win32":
        args += ["--icon", str(ROOT / "assets" / "icon.ico")]
    if embed_ffmpeg:
        for binary in locate_ffmpeg_pair():
            print(f"[build] Embebiendo {binary}")
            args += ["--add-binary", f"{binary}{SEP}bin"]
    return args


# FFmpeg que acompaña al instalador: compilación LGPL «shared» de BtbN (ffmpeg y ffprobe
# comparten las DLL, así que ocupa mucho menos que dos ejecutables estáticos).
FFMPEG_ZIP = "ffmpeg-n9.0-latest-win64-lgpl-shared-9.0.zip"
FFMPEG_URL = f"https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/{FFMPEG_ZIP}"
FFMPEG_CACHE = ROOT / "build" / "ffmpeg"


def app_version() -> str:
    text = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def installer_ffmpeg(explicit: str | None) -> Path:
    """Carpeta con bin/ffmpeg.exe, bin/ffprobe.exe, sus DLL y LICENSE.txt."""
    if explicit:
        folder = Path(explicit)
    else:
        folder = FFMPEG_CACHE / FFMPEG_ZIP.removesuffix(".zip")
        if not (folder / "bin" / "ffmpeg.exe").is_file():
            FFMPEG_CACHE.mkdir(parents=True, exist_ok=True)
            archive = FFMPEG_CACHE / FFMPEG_ZIP
            if not archive.is_file():
                print(f"[build] Descargando FFmpeg LGPL: {FFMPEG_URL}")
                urllib.request.urlretrieve(FFMPEG_URL, archive)  # noqa: S310
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(FFMPEG_CACHE)
    for required in ("bin/ffmpeg.exe", "bin/ffprobe.exe", "LICENSE.txt"):
        if not (folder / required).is_file():
            sys.exit(f"[build] Falta {required} en {folder}")
    return folder


def find_iscc() -> Path:
    candidates = [
        os.environ.get("ISCC"),
        shutil.which("ISCC"),
        str(Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe"),
        str(Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    sys.exit("[build] No se encontró Inno Setup 6 (ISCC.exe). Instálalo: winget install --id JRSoftware.InnoSetup -e")


def build_installer(ffmpeg_dir: str | None) -> Path:
    if sys.platform != "win32":
        sys.exit("[build] --installer solo está disponible en Windows (en Linux se usa install.sh).")
    ffmpeg = installer_ffmpeg(ffmpeg_dir)
    version = app_version()
    print(f"[build] Compilando instalador {version} con FFmpeg de {ffmpeg}")
    subprocess.run([
        str(find_iscc()), "/Qp",
        f"/DAppVersion={version}",
        f"/DDistDir={ROOT / 'dist' / APP_NAME}",
        f"/DFFmpegDir={ffmpeg}",
        f"/DOutputDir={ROOT / 'dist'}",
        str(ROOT / "packaging" / "windows" / "MediaDownloader.iss"),
    ], check=True)
    setup = ROOT / "dist" / "MediaDownloader_Setup.exe"
    print(f"[build] Instalador: {setup} ({setup.stat().st_size / 1e6:.1f} MB)")
    return setup


def run_self_check(onefile: bool) -> None:
    exe = ROOT / "dist" / (f"{APP_NAME}{EXE}" if onefile else f"{APP_NAME}/{APP_NAME}{EXE}")
    print(f"[build] Verificando {exe} --self-check …")
    code = subprocess.run([str(exe), "--self-check"], timeout=180).returncode
    if code != 0:
        sys.exit("[build] El self-check falló. Revisa self-check.txt en la carpeta de datos de la app.")
    print("[build] Self-check OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--onefile", action="store_true", help="un único ejecutable (arranque más lento)")
    parser.add_argument("--embed-ffmpeg", action="store_true", help="incluir ffmpeg y ffprobe en el paquete")
    parser.add_argument("--skip-check", action="store_true", help="no ejecutar el self-check al terminar")
    parser.add_argument("--installer", action="store_true",
                        help="Windows: generar también dist/MediaDownloader_Setup.exe con Inno Setup")
    parser.add_argument("--ffmpeg-dir", help="FFmpeg a incluir en el instalador (por defecto se descarga el LGPL)")
    opts = parser.parse_args()
    if opts.installer and opts.onefile:
        sys.exit("[build] El instalador empaqueta la versión --onedir: no combines --installer con --onefile.")

    try:
        import PyInstaller.__main__
    except ImportError:
        sys.exit("[build] Falta PyInstaller: pip install -r requirements-dev.txt")

    PyInstaller.__main__.run(pyinstaller_args(opts.onefile, opts.embed_ffmpeg))
    if not opts.skip_check:
        run_self_check(opts.onefile)
    if opts.installer:
        build_installer(opts.ffmpeg_dir)


if __name__ == "__main__":
    main()
