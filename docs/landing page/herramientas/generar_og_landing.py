"""
generar_og_landing.py — la imagen que se ve al compartir el enlace de la landing (1200 × 630) → docs/landing page/img/og.png

    backend/venv/bin/python "docs/landing page/herramientas/generar_og_landing.py"

Mismo método que dev/generar_redes.py: HTML con las tipografías y el logo de la marca, fotografiado con Chrome headless.
"""

import base64
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CARPETA = Path(__file__).resolve().parent.parent          # «landing page/»
RAIZ = CARPETA.parent.parent                              # la raíz del proyecto
sys.path.insert(0, str(RAIZ / "dev"))
from generar_manual_identidad import buscar_chrome, css_fuentes, simbolos_svg  # noqa: E402

IMG = CARPETA / "img"
SALIDA = IMG / "og.png"

HTML = """<!doctype html><html lang="es"><head><meta charset="utf-8"><style>/*FUENTES*/
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1200px;height:630px;overflow:hidden;background:#1e3a5f;font-family:'Hanken Grotesk',sans-serif;color:#fff}
.c{position:absolute;right:-180px;top:-120px;width:760px;height:760px}
.marca{position:absolute;left:72px;top:60px;display:flex;align-items:center;gap:18px;font:800 40px/1 'Outfit',sans-serif;letter-spacing:-.02em}
.marca svg{width:64px;height:64px;border-radius:15px}
h1{position:absolute;left:72px;top:190px;width:560px;font:800 66px/1.04 'Outfit',sans-serif;letter-spacing:-.03em}
p{position:absolute;left:72px;bottom:64px;width:520px;font:500 26px/1.4 'Hanken Grotesk',sans-serif;color:#dbe6f3}
.hoja{position:absolute;left:660px;top:76px;width:470px;height:560px;background:#fff;border-radius:6px;box-shadow:0 30px 60px rgba(7,17,33,.45);padding:26px 26px 0;overflow:hidden}
.hoja img{display:block;width:100%;border:1px solid #cbd5e1;border-radius:14px}
.hoja .t{font:800 22px/1.2 'Outfit',sans-serif;color:#0f172a;margin-bottom:16px}
.o{display:flex;align-items:center;gap:12px;margin-top:11px;font:700 20px/1.2 'Hanken Grotesk',sans-serif;color:#0f172a}
.o i{width:22px;height:22px;border:2px solid #0f172a;border-radius:4px;background:#fbbf24;display:grid;place-items:center}
.o svg{width:15px;height:15px;fill:none;stroke:#0f172a;stroke-width:3.4;stroke-linecap:round;stroke-linejoin:round}
</style></head><body><!--SIMBOLOS-->
<svg class="c" viewBox="0 0 100 100"><path d="M70.5 29.5 A29 29 0 1 0 70.5 70.5" fill="none" stroke="#27456e" stroke-width="11" stroke-linecap="round"/></svg>
<div class="marca"><svg viewBox="0 0 100 100"><use href="#logo-principal"/></svg>Cátedra</div>
<h1>Del examen que ya tienes, a Moodle y al papel.</h1>
<p>Tu espacio para gestionar tus evaluaciones.</p>
<div class="hoja"><div class="t">1. ¿Qué necesitas hacer con tu examen?</div><img src="{{IMG}}"><div class="o"><i><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></i>Llevarlo a Moodle</div><div class="o"><i><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></i>Imprimirlo</div><div class="o"><i><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></i>Sacar varias versiones</div><div class="o"><i><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></i>Ordenarlo por materia</div></div>
</body></html>"""


def main() -> None:
    figura = IMG / "figura-original.webp"
    from PIL import Image
    import io
    im = Image.open(figura).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    datos = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    html = HTML.replace("/*FUENTES*/", css_fuentes()).replace("<!--SIMBOLOS-->", simbolos_svg()).replace("{{IMG}}", datos)
    with tempfile.TemporaryDirectory() as tmp:
        archivo = Path(tmp) / "og.html"
        archivo.write_text(html, encoding="utf-8")
        if SALIDA.exists():
            SALIDA.unlink()
        proceso = subprocess.Popen([
            buscar_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
            "--window-size=1200,630", f"--user-data-dir={tmp}/perfil", "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=4000", f"--screenshot={SALIDA}", archivo.as_uri(),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        previo, estables, inicio = -1, 0, time.time()
        while time.time() - inicio < 90 and proceso.poll() is None:
            time.sleep(0.5)
            tam = SALIDA.stat().st_size if SALIDA.exists() else 0
            estables = estables + 1 if tam > 5_000 and tam == previo else 0
            previo = tam
            if estables >= 3:
                break
        if proceso.poll() is None:
            proceso.terminate()
            try:
                proceso.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proceso.kill()
    if not SALIDA.exists():
        sys.exit("Chrome no generó la imagen.")
    with Image.open(SALIDA) as r:
        print(f"{SALIDA.relative_to(RAIZ)}  {r.size[0]}×{r.size[1]}  {SALIDA.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
