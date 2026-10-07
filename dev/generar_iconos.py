"""
generar_iconos.py — dibuja el ícono de Cátedra (C ámbar con renglones, fuente: assets/icono-catedra.svg) en todos los
tamaños y arma frontend/img/icono.png, assets/Icon.ico, ejecutable/assets/Icon.ico y ejecutable_mac/assets/Icon.icns.

    backend/venv/bin/python dev/generar_iconos.py

En tamaños de 48 px o menos los puntos y los renglones van un poco más gruesos para que se lean. Hace falta macOS
(iconutil) para el .icns.
"""
import io, math, struct, subprocess, shutil, sys
from pathlib import Path
from PIL import Image, ImageDraw

RAIZ = Path(__file__).resolve().parent.parent
NAVY, AMBAR, CIELO, BLANCO = "#1e3a5f", "#fbbf24", "#7dd3fc", "#ffffff"

def dibujar(px: int) -> Image.Image:
    """Ícono de `px` píxeles. En tamaños chicos los renglones y los puntos van un poco más gruesos para que se lean."""
    k = 8                                   # supermuestreo
    S = px * k
    u = S / 100.0
    chico = px <= 48
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=22 * u, fill=NAVY)
    # La C: arco de 29 de radio, trazo 11, abierto a la derecha (±45°)
    w = 11 * u
    r = 29 * u
    c = 50 * u
    d.arc([c - r - w / 2, c - r - w / 2, c + r + w / 2, c + r + w / 2], start=45, end=315, fill=AMBAR, width=round(w))
    for ang in (45, 315):
        x = c + r * math.cos(math.radians(ang)); y = c + r * math.sin(math.radians(ang))
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=AMBAR)
    # Viñetas y renglones
    rp = (3.4 if chico else 2.7) * u
    lw = (5.6 if chico else 4.5) * u
    filas = [(41, 64, CIELO), (50, 67, CIELO), (59, 60, BLANCO)]
    for y, x2, col in filas:
        d.ellipse([41 * u - rp, y * u - rp, 41 * u + rp, y * u + rp], fill=col)
        a, b = (49 if chico else 48) * u, x2 * u
        d.line([(a, y * u), (b, y * u)], fill=BLANCO, width=round(lw))
        for x in (a, b):
            d.ellipse([x - lw / 2, y * u - lw / 2, x + lw / 2, y * u + lw / 2], fill=BLANCO)
    return img.resize((px, px), Image.LANCZOS)

def png_bytes(im): 
    b = io.BytesIO(); im.save(b, "PNG", optimize=True); return b.getvalue()

def escribir_ico(ruta: Path, tamanos):
    datos = [(t, png_bytes(dibujar(t))) for t in tamanos]
    cab = struct.pack("<HHH", 0, 1, len(datos))
    entradas, cuerpo, desplaz = b"", b"", 6 + 16 * len(datos)
    for t, png in datos:
        entradas += struct.pack("<BBBBHHII", t % 256, t % 256, 0, 0, 1, 32, len(png), desplaz)
        cuerpo += png; desplaz += len(png)
    ruta.write_bytes(cab + entradas + cuerpo)

def escribir_icns(ruta: Path):
    tmp = Path("/tmp/Catedra.iconset"); shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir()
    for base in (16, 32, 128, 256, 512):
        dibujar(base).save(tmp / f"icon_{base}x{base}.png")
        dibujar(base * 2).save(tmp / f"icon_{base}x{base}@2x.png")
    subprocess.run(["iconutil", "-c", "icns", str(tmp), "-o", str(ruta)], check=True)

if __name__ == "__main__":
    (RAIZ / "frontend/img").mkdir(exist_ok=True)
    dibujar(256).save(RAIZ / "frontend/img/icono.png", optimize=True)
    TAM = [16, 24, 32, 48, 64, 128, 256]
    for ico in (RAIZ / "assets/Icon.ico", RAIZ / "ejecutable/assets/Icon.ico"):
        ico.parent.mkdir(exist_ok=True); escribir_ico(ico, TAM)
    escribir_icns(RAIZ / "ejecutable_mac/assets/Icon.icns")
    dibujar(512).save(RAIZ / "assets/icono-catedra.png", optimize=True)
    print("listo")
