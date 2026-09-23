"""Genera assets/icon.png (Linux) y assets/icon.ico (Windows).

Solo hace falta ejecutarlo si se cambia el diseño del icono (requiere Pillow):
    python packaging/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SIZE = 1024  # se dibuja grande y se reduce para obtener bordes suaves


def draw_icon() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    # Fondo: degradado vertical dentro de un cuadrado redondeado.
    gradient = Image.new("RGBA", (SIZE, SIZE))
    top, bottom = (59, 130, 246), (37, 58, 190)
    gdraw = ImageDraw.Draw(gradient)
    for y in range(SIZE):
        t = y / (SIZE - 1)
        color = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
        gdraw.line([(0, y), (SIZE, y)], fill=(*color, 255))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((40, 40, SIZE - 40, SIZE - 40), radius=220, fill=255)
    img.paste(gradient, (0, 0), mask)

    draw = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)

    # Nota musical (corchea) en la parte superior izquierda.
    draw.ellipse((250, 470, 420, 600), fill=white)
    draw.rectangle((385, 200, 420, 540), fill=white)
    draw.polygon([(420, 200), (560, 270), (560, 340), (420, 280)], fill=white)

    # Flecha de descarga a la derecha.
    draw.rectangle((620, 250, 700, 520), fill=white)
    draw.polygon([(540, 500), (780, 500), (660, 640)], fill=white)

    # Bandeja inferior.
    draw.rounded_rectangle((240, 700, 784, 780), radius=40, fill=white)
    return img


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    icon = draw_icon()
    icon.resize((256, 256), Image.LANCZOS).save(ASSETS / "icon.png")
    icon.save(ASSETS / "icon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print(f"Iconos generados en {ASSETS}")


if __name__ == "__main__":
    main()
