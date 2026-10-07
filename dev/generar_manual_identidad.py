"""
generar_manual_identidad.py — arma el Manual de identidad visual de Cátedra (PDF) y los archivos del logo.

    backend/venv/bin/python dev/generar_manual_identidad.py

Qué hace (todo sale de aquí, así el logo, los colores y las cifras del manual no pueden discrepar entre sí):
  1. Escribe los símbolos del logo en `assets/marca/*.svg` (principal, claro, monocromo, glifos sin fondo).
  2. Lee la plantilla `docs/identidad/fuente/manual.html`, le inyecta las tipografías de la marca (de
     `frontend/fonts/`, embebidas), el logo, la paleta (con RGB y CMYK aproximado y los contrastes WCAG calculados).
  3. Lo imprime a PDF con Google Chrome en modo headless → `docs/identidad/Catedra-Manual-de-Identidad-Visual.pdf`.

Hace falta Google Chrome (o Chromium) instalado; no usa red. Si cambia el logo o la paleta, se cambia AQUÍ y se vuelve a correr.
"""

import base64
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLA = RAIZ / "docs" / "identidad" / "fuente" / "manual.html"
SALIDA_PDF = RAIZ / "docs" / "identidad" / "Catedra-Manual-de-Identidad-Visual.pdf"
CARPETA_MARCA = RAIZ / "assets" / "marca"
FUENTES = RAIZ / "frontend" / "fonts"

# ── El logo ─────────────────────────────────────────────────────────────────
# Geometría en un lienzo de 100 × 100 (la misma de dev/generar_iconos.py): una C de radio 29 y trazo 11, abierta a la
# derecha (±45°), con tres viñetas y tres renglones dentro.
C_ARCO = "M70.5 29.5 A29 29 0 1 0 70.5 70.5"
RENGLONES = "M48 41 H64 M48 50 H67 M48 59 H60"
VARIANTES = {
    # nombre: (fondo, borde del fondo, color de la C, colores de las 3 viñetas, color de los renglones)
    "principal": ("#1e3a5f", None, "#fbbf24", ("#7dd3fc", "#7dd3fc", "#ffffff"), "#ffffff"),
    "claro": ("#f0f9ff", "#bae6fd", "#0369a1", ("#7dd3fc", "#7dd3fc", "#f59e0b"), "#7dd3fc"),
    "monocromo": ("#1e3a5f", None, "#ffffff", ("#ffffff", "#ffffff", "#ffffff"), "#ffffff"),
    "glifo-blanco": (None, None, "#ffffff", ("#ffffff", "#ffffff", "#ffffff"), "#ffffff"),
    "glifo-azul": (None, None, "#1e3a5f", ("#1e3a5f", "#1e3a5f", "#1e3a5f"), "#1e3a5f"),
}
NOMBRES_ARCHIVO = {
    "principal": "catedra-icono.svg", "claro": "catedra-icono-claro.svg", "monocromo": "catedra-icono-monocromo.svg",
    "glifo-blanco": "catedra-glifo-blanco.svg", "glifo-azul": "catedra-glifo-azul.svg",
}


def _contenido_logo(variante: str, renglones: bool = True) -> str:
    fondo, borde, c, viñetas, lineas = VARIANTES[variante]
    partes = []
    if fondo:
        extra = f' stroke="{borde}" stroke-width="1.5"' if borde else ""
        partes.append(f'<rect width="100" height="100" rx="22" fill="{fondo}"{extra}/>')
    partes.append(f'<path d="{C_ARCO}" fill="none" stroke="{c}" stroke-width="11" stroke-linecap="round"/>')
    if renglones:
        for y, col in zip((41, 50, 59), viñetas):
            partes.append(f'<circle cx="41" cy="{y}" r="2.7" fill="{col}"/>')
        partes.append(f'<path d="{RENGLONES}" fill="none" stroke="{lineas}" stroke-width="4.5" stroke-linecap="round"/>')
    return "".join(partes)


def logo_svg(variante: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="512" height="512">'
            f"<title>Cátedra</title>{_contenido_logo(variante)}</svg>\n")


ROBOT = """<circle cx="50" cy="50" r="48" fill="#1e63b8"/><circle cx="50" cy="50" r="46" fill="#e8f0fe"/>
<g clip-path="url(#robot-recorte)"><path d="M72 80 C82 76 84 66 81 58" fill="none" stroke="#cbd5e1" stroke-width="7" stroke-linecap="round"/>
<circle cx="80.5" cy="54" r="5.2" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.8"/>
<path d="M28 82 C22 88 22 94 24 100" fill="none" stroke="#cbd5e1" stroke-width="7" stroke-linecap="round"/>
<ellipse cx="50" cy="88" rx="23" ry="20" fill="#e2e8f0" stroke="#94a3b8" stroke-width="2"/><rect x="43" y="74" width="14" height="5" rx="2.5" fill="#fbbf24"/>
<circle cx="50" cy="46" r="24" fill="#f1f5f9" stroke="#94a3b8" stroke-width="2"/><rect x="29" y="37" width="42" height="18" rx="9" fill="#1e3a5f"/>
<path d="M36.5 48.5 Q41 41.5 45.5 48.5" fill="none" stroke="#7dd3fc" stroke-width="2.8" stroke-linecap="round"/>
<path d="M54.5 48.5 Q59 41.5 63.5 48.5" fill="none" stroke="#7dd3fc" stroke-width="2.8" stroke-linecap="round"/>
<circle cx="34.5" cy="51.5" r="1.8" fill="#fbbf24"/><circle cx="65.5" cy="51.5" r="1.8" fill="#fbbf24"/>
<path d="M50 22 V16" stroke="#94a3b8" stroke-width="2.4" stroke-linecap="round"/><circle cx="50" cy="14" r="3" fill="#fbbf24"/></g>"""


def simbolos_svg() -> str:
    """Los símbolos que el HTML reutiliza con <use href="#...">."""
    s = ['<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>',
         '<clipPath id="robot-recorte"><circle cx="50" cy="50" r="46"/></clipPath>']
    for v in VARIANTES:
        s.append(f'<symbol id="logo-{v}" viewBox="0 0 100 100">{_contenido_logo(v)}</symbol>')
    s.append(f'<symbol id="logo-incompleto" viewBox="0 0 100 100">{_contenido_logo("principal", renglones=False)}</symbol>')
    s.append(f'<symbol id="robot" viewBox="0 0 100 100">{ROBOT}</symbol>')
    s.append("</defs></svg>")
    return "".join(s)


# ── Colores ─────────────────────────────────────────────────────────────────
def a_rgb(h: str):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def a_cmyk(h: str):
    """CMYK aproximado (conversión matemática sin perfil de color): sirve de guía, no sustituye una prueba de impresión."""
    r, g, b = (x / 255 for x in a_rgb(h))
    k = 1 - max(r, g, b)
    if k >= 1:
        return 0, 0, 0, 100
    return tuple(round(100 * v) for v in ((1 - r - k) / (1 - k), (1 - g - k) / (1 - k), (1 - b - k) / (1 - k), k))


def luminancia(h: str) -> float:
    def canal(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = a_rgb(h)
    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def contraste(a: str, b: str) -> float:
    la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _claro(h: str) -> bool:
    return luminancia(h) > 0.45


PALETAS = {
    "marca": [
        ("Azul marino Cátedra", "#1e3a5f", "El fondo del símbolo. Color base de la marca."),
        ("Ámbar", "#fbbf24", "La C del símbolo. El acento cálido: se usa poco y con intención."),
        ("Celeste", "#7dd3fc", "Las viñetas del símbolo y los detalles sobre azul marino."),
        ("Blanco", "#ffffff", "Los renglones del símbolo y el texto sobre azul marino."),
    ],
    "interfaz": [
        ("Azul Cátedra", "#0369a1", "Acción principal: botones, enlaces y paso activo."),
        ("Azul señal", "#38bdf8", "Acento de la interfaz en modo oscuro y detalles."),
        ("Tinta", "#0f172a", "Texto principal sobre fondo claro."),
        ("Pizarra", "#475569", "Texto secundario y descripciones."),
        ("Fondo", "#f1f5f9", "El fondo de la aplicación en modo claro."),
        ("Superficie", "#ffffff", "Tarjetas, ventanas y campos."),
        ("Borde", "#cbd5e1", "Líneas y separadores."),
    ],
    "estados": [
        ("Éxito", "#047d58", "Confirmaciones y «listo»."),
        ("Aviso", "#ac5f05", "Algo que conviene revisar."),
        ("Error", "#d31b44", "Algo que impide continuar."),
    ],
    "tipos": [
        ("Opción múltiple", "#0270a9", ""), ("Verdadero/Falso", "#047854", ""), ("Emparejamiento", "#a25904", ""),
        ("Completar", "#6d28d9", ""), ("Ensayo", "#be185d", ""), ("Respuesta corta", "#0f766e", ""), ("Numérica", "#c2410c", ""),
    ],
}


def muestras(lista, compacta=False, angosta=False) -> str:
    sep = " " if angosta else " · "
    html = []
    for nombre, h, uso in lista:
        r, g, b = a_rgb(h)
        c, m, y, k = a_cmyk(h)
        texto = "#0f172a" if _claro(h) else "#ffffff"
        borde = "border:1px solid #cbd5e1;" if h.lower() in ("#ffffff", "#f1f5f9") else ""
        if compacta:
            html.append(f'<div class="mu mu-c"><div class="mu-color" style="background:{h};color:{texto};{borde}">{h.upper()}</div>'
                        f'<div class="mu-nombre">{nombre}</div></div>')
        else:
            html.append(f'<div class="mu"><div class="mu-color" style="background:{h};color:{texto};{borde}"><b>{nombre}</b></div>'
                        f'<div class="mu-datos"><span><i>HEX</i> {h.upper()}</span><span><i>RGB</i> {r}{sep}{g}{sep}{b}</span>'
                        f'<span><i>CMYK</i> {c}{sep}{m}{sep}{y}{sep}{k}</span></div><p>{uso}</p></div>')
    return "".join(html)


def tabla_contrastes() -> str:
    pares = [
        ("#ffffff", "#1e3a5f", "Texto blanco sobre azul marino"),
        ("#fbbf24", "#1e3a5f", "Ámbar sobre azul marino"),
        ("#7dd3fc", "#1e3a5f", "Celeste sobre azul marino"),
        ("#0f172a", "#f1f5f9", "Tinta sobre el fondo claro"),
        ("#475569", "#ffffff", "Pizarra sobre blanco"),
        ("#fbbf24", "#ffffff", "Ámbar sobre blanco (evitarlo para texto)"),
        ("#ffffff", "#0369a1", "Texto blanco sobre Azul Cátedra"),
        ("#0369a1", "#ffffff", "Azul Cátedra sobre blanco"),
    ]
    filas = []
    for fg, bg, texto in pares:
        r = contraste(fg, bg)
        nivel = "AAA" if r >= 7 else "AA" if r >= 4.5 else "solo texto grande" if r >= 3 else "no cumple"
        filas.append(f'<tr><td><span class="ej" style="background:{bg};color:{fg}">Aa</span></td><td>{texto}</td>'
                     f'<td class="num">{r:.1f} : 1</td><td><b class="{"ok" if r >= 4.5 else "no"}">{nivel}</b></td></tr>')
    return "".join(filas)


# ── Tipografías (se incrustan para que el PDF no dependa de nada instalado) ─────────────────────────
def css_fuentes() -> str:
    def face(familia, archivo, pesos):
        datos = base64.b64encode((FUENTES / archivo).read_bytes()).decode()
        return (f"@font-face{{font-family:'{familia}';font-weight:{pesos};font-style:normal;"
                f"src:url(data:font/woff2;base64,{datos}) format('woff2');}}")
    return "".join([
        face("Outfit", "outfit-latin-wght-normal.woff2", "100 900"),
        face("Hanken Grotesk", "hanken-grotesk-latin-wght-normal.woff2", "100 900"),
        face("JetBrains Mono", "jetbrains-mono-latin-wght-normal.woff2", "100 800"),
    ])


def buscar_chrome() -> str:
    candidatos = [
        os.environ.get("CHROME_BIN", ""),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        shutil.which("google-chrome") or "", shutil.which("chromium") or "", shutil.which("chromium-browser") or "",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in candidatos:
        if c and Path(c).exists():
            return c
    sys.exit("No encontré Google Chrome ni Chromium. Instálalo o indica la ruta en la variable CHROME_BIN.")


def main() -> None:
    CARPETA_MARCA.mkdir(parents=True, exist_ok=True)
    for v, nombre in NOMBRES_ARCHIVO.items():
        (CARPETA_MARCA / nombre).write_text(logo_svg(v), encoding="utf-8")
    html = PLANTILLA.read_text(encoding="utf-8")
    sustituciones = {
        "/*FUENTES*/": css_fuentes(),
        "<!--SIMBOLOS-->": simbolos_svg(),
        "<!--PALETA_MARCA-->": muestras(PALETAS["marca"]),
        "<!--PALETA_INTERFAZ-->": muestras(PALETAS["interfaz"], angosta=True),
        "<!--PALETA_ESTADOS-->": muestras(PALETAS["estados"], angosta=True),
        "<!--PALETA_TIPOS-->": muestras(PALETAS["tipos"], compacta=True),
        "<!--CONTRASTES-->": tabla_contrastes(),
    }
    for marca, valor in sustituciones.items():
        if marca not in html:
            sys.exit(f"La plantilla no tiene el marcador {marca}")
        html = html.replace(marca, valor)
    with tempfile.TemporaryDirectory() as tmp:
        archivo = Path(tmp) / "manual.html"
        archivo.write_text(html, encoding="utf-8")
        SALIDA_PDF.parent.mkdir(parents=True, exist_ok=True)
        if SALIDA_PDF.exists():
            SALIDA_PDF.unlink()
        # Chrome a veces no termina solo después de imprimir: se espera a que el PDF aparezca y deje de crecer, y se cierra.
        proceso = subprocess.Popen([
            buscar_chrome(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--hide-scrollbars",
            f"--user-data-dir={tmp}/perfil", f"--print-to-pdf={SALIDA_PDF}", archivo.as_uri(),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        tamano_previo, estables, inicio = -1, 0, time.time()
        while time.time() - inicio < 180 and proceso.poll() is None:
            time.sleep(1)
            tam = SALIDA_PDF.stat().st_size if SALIDA_PDF.exists() else 0
            estables = estables + 1 if tam > 10_000 and tam == tamano_previo else 0
            tamano_previo = tam
            if estables >= 3:
                break
        if proceso.poll() is None:
            proceso.terminate()
            try:
                proceso.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proceso.kill()
        resultado = proceso
    if not SALIDA_PDF.exists() or SALIDA_PDF.stat().st_size < 10_000:
        sys.exit("Chrome no generó el PDF.")
    print(f"Manual: {SALIDA_PDF.relative_to(RAIZ)} ({SALIDA_PDF.stat().st_size // 1024} KB)")
    print(f"Logos: {CARPETA_MARCA.relative_to(RAIZ)}/ ({len(NOMBRES_ARCHIVO)} archivos)")


if __name__ == "__main__":
    main()
