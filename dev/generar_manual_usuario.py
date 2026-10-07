"""
generar_manual_usuario.py — arma el Manual de usuario de Cátedra (PDF, tamaño carta).

    backend/venv/bin/python dev/generar_manual_usuario.py

Toma la plantilla `docs/manual-usuario/fuente/manual.html`, le pone las tipografías de la marca, el logo (de
dev/generar_manual_identidad.py) y las capturas de `docs/manual-usuario/fuente/capturas/`, y la imprime a PDF con Google
Chrome en modo headless → `docs/manual-usuario/Catedra-Manual-de-Usuario.pdf`. El índice con los números de página se
calcula solo (se imprime una vez para saber en qué página cae cada sección y otra con los números ya puestos).

Si cambia la interfaz, se vuelven a tomar las capturas con dev/capturas_manual_usuario.py (necesita Playwright; ver ese
archivo) y se corre este script. Hace falta Chrome o Chromium; no usa red.
"""

import base64
import io
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from generar_manual_identidad import buscar_chrome, css_fuentes, simbolos_svg  # noqa: E402

PLANTILLA = RAIZ / "docs" / "manual-usuario" / "fuente" / "manual.html"
CAPTURAS = RAIZ / "docs" / "manual-usuario" / "fuente" / "capturas"
SALIDA = RAIZ / "docs" / "manual-usuario" / "Catedra-Manual-de-Usuario.pdf"
ANCHO_MAX_IMAGEN = 1500


def imagen_data_uri(nombre: str) -> str:
    """La captura como data URI PNG, reducida a ANCHO_MAX_IMAGEN px de ancho (más que eso no se nota en una hoja carta)."""
    ruta = CAPTURAS / nombre
    if not ruta.exists():
        sys.exit(f"Falta la captura {nombre}: corre dev/capturas_manual_usuario.py")
    from PIL import Image
    im = Image.open(ruta).convert("RGB")
    if im.width > ANCHO_MAX_IMAGEN:
        im = im.resize((ANCHO_MAX_IMAGEN, round(im.height * ANCHO_MAX_IMAGEN / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def preparar_html(numeros: dict) -> str:
    html = PLANTILLA.read_text(encoding="utf-8")
    html = html.replace("/*FUENTES*/", css_fuentes() + ".mk{position:absolute;font-size:1px;color:transparent;}").replace("<!--SIMBOLOS-->", simbolos_svg())
    html = re.sub(r"\{\{IMG:([^}]+)\}\}", lambda m: imagen_data_uri(m.group(1)), html)
    # Una marca invisible al inicio de cada sección con id: así se sabe en qué página cae.
    html = re.sub(r'(<section[^>]*\bid="([a-z0-9-]+)"[^>]*>)', lambda m: f'{m.group(1)}<span class="mk">§§{m.group(2)}§§</span>', html)
    html = re.sub(r'<span class="pg" data-pag="([a-z0-9-]+)"></span>',
                  lambda m: f'<span class="pg">{numeros.get(m.group(1), "")}</span>', html)
    return html


def imprimir(html: str, destino: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        archivo = Path(tmp) / "manual.html"
        archivo.write_text(html, encoding="utf-8")
        if destino.exists():
            destino.unlink()
        proceso = subprocess.Popen([
            buscar_chrome(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--hide-scrollbars",
            f"--user-data-dir={tmp}/perfil", f"--print-to-pdf={destino}", archivo.as_uri(),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Chrome a veces no termina solo: se espera a que el PDF aparezca y deje de crecer, y se cierra.
        previo, estables, inicio = -1, 0, time.time()
        while time.time() - inicio < 240 and proceso.poll() is None:
            time.sleep(1)
            tam = destino.stat().st_size if destino.exists() else 0
            estables = estables + 1 if tam > 10_000 and tam == previo else 0
            previo = tam
            if estables >= 3:
                break
        if proceso.poll() is None:
            proceso.terminate()
            try:
                proceso.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proceso.kill()
    if not destino.exists() or destino.stat().st_size < 10_000:
        sys.exit("Chrome no generó el PDF.")


def paginas_de_secciones(pdf: Path) -> dict:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf))
    numeros = {}
    try:
        for i in range(len(doc)):
            texto = doc[i].get_textpage().get_text_range()
            for ident in re.findall(r"§§([a-z0-9-]+)§§", texto):
                numeros.setdefault(ident, i + 1)
    finally:
        doc.close()
    return numeros


def main() -> None:
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    imprimir(preparar_html({}), SALIDA)
    numeros = paginas_de_secciones(SALIDA)
    imprimir(preparar_html(numeros), SALIDA)
    verificados = paginas_de_secciones(SALIDA)
    if verificados != numeros:
        # Poner los números no cambia el largo de nada, pero si cambiara, se imprime una vez más.
        imprimir(preparar_html(verificados), SALIDA)
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(SALIDA))
    paginas = len(doc)
    doc.close()
    print(f"Manual de usuario: {SALIDA.relative_to(RAIZ)} · {paginas} páginas · {SALIDA.stat().st_size // 1024} KB")
    print("Secciones:", ", ".join(f"{k}→{v}" for k, v in sorted(verificados.items(), key=lambda kv: kv[1])))


if __name__ == "__main__":
    main()
