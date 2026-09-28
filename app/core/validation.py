"""Validación del archivo final antes de dar una descarga por buena.

yt-dlp puede terminar sin error y aun así dejar un archivo inservible: por ejemplo,
cuando el servidor corta la conexión y al reanudar sirve una versión distinta del
archivo, los trozos no encajan y el post-procesado de FFmpeg genera un .mp4 de unos
pocos bytes. Aquí se comprueba el resultado con ffprobe antes de marcarlo como
completado.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from app.paths import external_env

log = logging.getLogger(__name__)

# Ningún audio o video real ocupa tan poco (el caso detectado pesaba 796 bytes).
MIN_BYTES = 16 * 1024
# Tasa mínima creíble (bytes por segundo de duración). Muy por debajo de cualquier
# calidad real: un video a 144p ronda 10 KB/s y un MP3 de voz a 32 kbps, 4 KB/s.
MIN_VIDEO_BYTES_PER_SECOND = 3_000
MIN_AUDIO_BYTES_PER_SECOND = 1_000
# Se admite una pequeña diferencia con la duración anunciada por la fuente.
DURATION_TOLERANCE = 0.9
# Si ffprobe no puede leer un archivo de más de este tamaño, no se borra: se conserva con
# un aviso. Un fallo de ffprobe (p. ej. no arranca por un problema de bibliotecas) no debe
# costarle al usuario una descarga de gigas.
KEEP_UNREADABLE_ABOVE = 1024 * 1024
# Espera antes de analizar: a que el archivo deje de cambiar de tamaño (antivirus,
# indexadores o el propio post-procesado aún pueden estar escribiéndolo).
SETTLE_MIN_SECONDS = 0.5
SETTLE_MAX_SECONDS = 3.0


@dataclass
class MediaCheck:
    ok: bool
    reason: str = ""
    size: int = 0
    duration: float | None = None
    warning: str = ""          # válido pero sin verificar (se conserva y se avisa en el log)


def wait_until_stable(path: Path, min_wait: float = SETTLE_MIN_SECONDS,
                      max_wait: float = SETTLE_MAX_SECONDS, step: float = 0.25) -> None:
    """Espera al menos ``min_wait`` y hasta que el tamaño no cambie entre dos lecturas."""
    deadline = time.monotonic() + max_wait
    time.sleep(min_wait)
    try:
        previous = path.stat().st_size
        while time.monotonic() < deadline:
            time.sleep(step)
            current = path.stat().st_size
            if current == previous:
                return
            previous = current
    except OSError:
        return          # el archivo no existe: lo informará validate_media


def probe(path: Path, ffprobe: Path) -> tuple[dict | None, str]:
    """Ejecuta ffprobe y devuelve (datos JSON, error)."""
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        result = subprocess.run(
            [str(ffprobe), "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,codec_name", "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, creationflags=flags, env=external_env(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"no se pudo ejecutar ffprobe: {exc}"
    if result.returncode != 0:
        return None, (result.stderr.strip() or f"ffprobe terminó con código {result.returncode}")
    try:
        return json.loads(result.stdout or "{}"), ""
    except ValueError:
        return None, "ffprobe devolvió una respuesta ilegible"


def validate_media(
    path: Path,
    expect_video: bool,
    ffprobe: Path | None,
    expected_duration: float | None = None,
) -> MediaCheck:
    """Comprueba que ``path`` es un audio/video real y completo."""
    if not path.is_file():
        return MediaCheck(False, "el archivo final no existe")
    size = path.stat().st_size
    if size < MIN_BYTES:
        return MediaCheck(False, f"el archivo final solo ocupa {size} bytes", size)
    if ffprobe is None:
        log.warning("ffprobe no disponible: solo se comprobó el tamaño de %s", path.name)
        return MediaCheck(True, size=size)

    data, error = probe(path, ffprobe)
    if data is None:
        reason = f"FFmpeg no puede leerlo ({(error.splitlines() or ['?'])[-1][:200]})"
        if size > KEEP_UNREADABLE_ABOVE:
            return MediaCheck(True, size=size, warning=f"{reason}; se conserva sin verificar")
        return MediaCheck(False, reason, size)

    kinds = {stream.get("codec_type") for stream in data.get("streams") or []}
    if expect_video and "video" not in kinds:
        return MediaCheck(False, "no contiene pista de video", size)
    if not kinds & {"video", "audio"}:
        return MediaCheck(False, "no contiene pistas de audio ni de video", size)

    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except ValueError:
        duration = 0.0
    if duration <= 0:
        return MediaCheck(False, "duración 0 o desconocida", size)
    if expected_duration and duration < expected_duration * DURATION_TOLERANCE:
        return MediaCheck(
            False,
            f"incompleto: dura {duration:.0f} s de {expected_duration:.0f} s esperados",
            size, duration,
        )
    floor = MIN_VIDEO_BYTES_PER_SECOND if expect_video else MIN_AUDIO_BYTES_PER_SECOND
    if size / duration < floor:
        return MediaCheck(
            False,
            f"tamaño incoherente: {size / 1e6:.2f} MB para {duration:.0f} s de duración",
            size, duration,
        )
    return MediaCheck(True, size=size, duration=duration)
