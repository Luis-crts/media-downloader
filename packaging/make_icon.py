"""Genera los iconos de la aplicación a partir de assets/icon_source.png.

    python packaging/make_icon.py

Produce:
    assets/icon.ico   Windows: ventana, .exe y accesos directos (16 a 256 px)
    assets/icon.png   Linux: ventana y lanzador .desktop (256 px)

La imagen original es vertical (espada + reloj de engranajes, trazo blanco sobre negro).
- 64 px o más: se recorta un cuadrado centrado en la esfera y se borra la frase que queda
  dentro del recorte; en 64 px se engrosan un poco los trazos antes de reducir.
- 48 px o menos (explorador, barra de tareas, barra de título): versión simplificada con
  las mismas piezas (esfera, espada, flechas, engranaje). La ilustración tiene demasiado
  detalle fino y a esos tamaños se convertiría en una mancha gris.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SOURCE = ASSETS / "icon_source.png"

# Coordenadas en la imagen original (522 x 920).
CROP_BOX = (81, 335, 441, 695)            # cuadrado de 360 px centrado en la esfera
TEXT_BOXES = [(266, 630, 398, 676)]       # «for that one reader.」 dentro del recorte
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
GLYPH_MAX_SIZE = 48                       # hasta este tamaño se usa la versión simplificada
CORNER_RADIUS = 0.18                      # esquinas redondeadas (proporción del lado)


def load_emblem() -> Image.Image:
    """Recorte cuadrado en escala de grises (blanco = trazo)."""
    image = Image.open(SOURCE).convert("L")
    draw = ImageDraw.Draw(image)
    for box in TEXT_BOXES:
        draw.rectangle(box, fill=0)
    return image.crop(CROP_BOX)


def glyph(size: int) -> Image.Image:
    """Versión simplificada del emblema para tamaños pequeños (máscara L de ``size`` px).

    Mismas piezas y composición que la ilustración —esfera, espada vertical con guarda,
    flechas horizontales y engranaje central— dibujadas con trazo limpio. Se dibuja 8
    veces más grande y se reduce para obtener bordes suavizados.
    """
    ss = 8
    n = size * ss
    mask = Image.new("L", (n, n), 0)
    d = ImageDraw.Draw(mask)
    c = n / 2
    thin = max(ss, round(n * 0.034))            # elementos secundarios (esfera, flechas)
    bold = max(ss, round(n * 0.05))             # espada y engranajes

    def p(v: float) -> float:
        return v * n

    def gear(cx: float, cy: float, radius: float, teeth: int) -> None:
        for i in range(teeth):
            angle = math.tau * i / teeth + 0.2
            d.line(
                (cx + math.cos(angle) * radius * 0.85, cy + math.sin(angle) * radius * 0.85,
                 cx + math.cos(angle) * radius * 1.32, cy + math.sin(angle) * radius * 1.32),
                fill=255, width=bold,
            )
        d.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=0, outline=255, width=bold)
        hub = radius * 0.3
        d.ellipse((cx - hub, cy - hub, cx + hub, cy + hub), fill=255)

    # Esfera del reloj: arco abierto a la derecha como en la ilustración.
    r = p(0.31)
    d.arc((c - r, c - r, c + r, c + r), start=-150, end=150, fill=255, width=thin)
    # Flechas horizontales (secundarias), solo fuera de la esfera: una línea completa
    # por el centro convertiría el conjunto en una mira telescópica.
    d.line((p(0.1), c, c - r, c), fill=255, width=thin)
    d.line((c + r, c, p(0.9), c), fill=255, width=thin)
    head = p(0.055)
    for tip, sign in ((p(0.05), 1), (p(0.95), -1)):
        d.polygon([(tip, c), (tip + sign * head * 1.8, c - head), (tip + sign * head * 1.8, c + head)], fill=255)
    # Engranaje secundario abajo a la izquierda (rompe la simetría, como en el original).
    gear(c - p(0.17), c + p(0.17), p(0.085), 8)
    # Espada: hoja ahusada de arriba abajo, guarda ancha y pomo.
    blade = p(0.04)
    d.polygon([(c - blade, p(0.2)), (c + blade, p(0.2)), (c + blade * 0.7, p(0.82)), (c, p(0.97)),
               (c - blade * 0.7, p(0.82))], fill=255)
    d.rectangle((c - p(0.16), p(0.19), c + p(0.16), p(0.19) + bold), fill=255)   # guarda
    d.rectangle((c - blade * 0.55, p(0.08), c + blade * 0.55, p(0.19)), fill=255)  # empuñadura
    pommel = p(0.05)
    d.polygon([(c, p(0.01)), (c + pommel, p(0.06)), (c, p(0.11)), (c - pommel, p(0.06))], fill=255)
    # Engranaje central, atravesado por la espada.
    gear(c, c, p(0.11), 10)
    d.rectangle((c - blade * 0.5, c - p(0.11), c + blade * 0.5, c + p(0.11)), fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def render(emblem: Image.Image, size: int) -> Image.Image:
    """Icono RGBA de ``size`` px: trazos blancos sobre un cuadrado negro redondeado."""
    if size <= GLYPH_MAX_SIZE:
        # La ilustración tiene demasiado detalle fino para tan pocos píxeles.
        lines = glyph(size)
        inner, offset = size, 0
    else:
        scale = size / emblem.width
        lines = emblem
        if scale < 0.5:
            # Engrosa los trazos en proporción a la reducción (dilatación = MaxFilter).
            # MaxFilter necesita un tamaño impar >= 3: con 1, Pillow aborta el proceso.
            radius = max(1, round(0.55 / scale / 2))
            lines = emblem.filter(ImageFilter.MaxFilter(2 * radius + 1))
        # Margen interior del 6 % para que las flechas no toquen el borde.
        inner = round(size * 0.88)
        offset = (size - inner) // 2
        lines = lines.resize((inner, inner), Image.LANCZOS)

    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=round(size * CORNER_RADIUS), fill=255
    )
    icon.paste((10, 10, 12, 255), (0, 0), mask)
    white = Image.new("RGBA", (inner, inner), (255, 255, 255, 255))
    icon.paste(white, (offset, offset), lines)
    return icon


def main() -> None:
    emblem = load_emblem()
    frames = [render(emblem, size) for size in ICO_SIZES]
    frames[-1].save(ASSETS / "icon.png")
    # Cada tamaño del .ico se renderiza por separado (append_images) en lugar de dejar
    # que Pillow reduzca el de 256 px, que perdería los trazos finos.
    frames[-1].save(
        ASSETS / "icon.ico", sizes=[(s, s) for s in ICO_SIZES], append_images=frames[:-1]
    )
    print(f"Iconos generados en {ASSETS} ({', '.join(map(str, ICO_SIZES))} px)")


if __name__ == "__main__":
    main()
