"""Compila la aplicación con PyInstaller (Windows y Linux).

Uso:
    python build.py                    # carpeta distribuible (--onedir), recomendado
    python build.py --onefile          # un único ejecutable
    python build.py --embed-ffmpeg     # incluye ffmpeg/ffprobe dentro del paquete

Resultado:
    --onedir   dist/MediaDownloader/MediaDownloader(.exe)
    --onefile  dist/MediaDownloader(.exe)
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
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
    opts = parser.parse_args()

    try:
        import PyInstaller.__main__
    except ImportError:
        sys.exit("[build] Falta PyInstaller: pip install -r requirements-dev.txt")

    PyInstaller.__main__.run(pyinstaller_args(opts.onefile, opts.embed_ffmpeg))
    if not opts.skip_check:
        run_self_check(opts.onefile)


if __name__ == "__main__":
    main()
