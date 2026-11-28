"""
formulas.py — dibuja como imagen las fórmulas que no se pueden escribir como texto.

Las sencillas (potencias, letras griegas, ½…) las sigue escribiendo `latex_texto` como texto Unicode. Las
que quedarían mal en una línea (matrices, casos, integrales o sumas con límites, fracciones o raíces
compuestas, vectores…) se dibujan aquí: ziamath las convierte en trazos (con la fuente STIX Two Math que
trae), ReportLab los pone en una hoja del tamaño de la fórmula y PDFium la pasa a una imagen nítida (600
puntos por pulgada), que usan igual el PDF y el Word. Todo ocurre en el equipo, sin red ni TeX instalado.

Principio de siempre: lo que no se entiende NO se adivina. Con un comando desconocido, llaves sin cerrar o
un trazo que esta conversión no sepa dibujar, se devuelve None y la fórmula queda escrita tal cual (y se avisa).
"""

import base64
import io
import logging
import os
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Optional
from xml.etree import ElementTree

import latex2mathml.converter
import pypdfium2 as pdfium

if sys.platform == "win32":
    # ziafont (dentro de ziamath) lee %WINDIR% al importarse: sin esa variable, la aplicación no arrancaba.
    os.environ.setdefault("WINDIR", os.environ.get("SYSTEMROOT") or r"C:\Windows")

import ziamath  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from pdfium_cerrojo import CERROJO  # noqa: E402

logger = logging.getLogger(__name__)

ziamath.config.svg2 = False              # trazos sueltos en el SVG (sin <symbol> ni <use>)

LIMITE_LATEX = 1500                      # una fórmula más larga no es una fórmula de examen
ESCALA = 600 / 72                        # píxeles por punto de la imagen (600 ppp)
LIMITE_PIXELES = 12_000_000              # tope de una imagen (una matriz enorme a todo el ancho usa menos de 3 M)

# Un comando que latex2mathml no conoce llega como texto («\comando») dentro de un identificador u operador.
_DESCONOCIDO = re.compile(r"<(?:mi|mo|mn)\b[^>]*>\s*\\")
# En texto lineal se leen mal: aunque `latex_texto` sepa escribirlas, se dibujan.
_MARCAS_LINEALES = ("_(", "^(", "√(", "∛(", "∜(")
_FRACCION = re.compile(r"\\[dtc]?frac(?![A-Za-z])")
_CON_LIMITES = re.compile(r"\\(?:int|iint|iiint|oint|sum|prod|lim|bigcup|bigcap)(?![A-Za-z])\s*(?:\\limits\s*)?[_^]")
_NUMERO = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_TROZO = re.compile(r"([MLHVQCZ])|(-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)|([A-Za-z])")


@dataclass(frozen=True)
class Formula:
    png: bytes
    ancho: float                         # en puntos, al tamaño pedido
    alto: float
    bajo: float                          # cuánto queda por debajo de la línea base (puntos)

    def etiqueta(self) -> str:
        """El `<img>` de ReportLab (que también lee exportar_docx)."""
        datos = base64.b64encode(self.png).decode("ascii")
        return (f'<img src="data:image/png;base64,{datos}" width="{self.ancho:.2f}" height="{self.alto:.2f}" '
                f'valign="{-self.bajo:.2f}"/>')


def conviene_dibujar(latex: str, como_texto: Optional[str]) -> bool:
    """¿Se dibuja? Sí si no hay forma de escribirla como texto, o si en una sola línea se leería mal."""
    if como_texto is None:
        return True
    if any(m in como_texto for m in _MARCAS_LINEALES):
        return True
    if "/" in como_texto and _FRACCION.search(latex):
        return True
    return bool(_CON_LIMITES.search(latex))


@lru_cache(maxsize=512)
def dibujar(latex: str, tam: float, ancho_max: float) -> Optional[Formula]:
    """La fórmula `latex` (sin los \\( \\)) a `tam` puntos, reducida si no cabe en `ancho_max`; None si no se puede."""
    if not latex.strip() or len(latex) > LIMITE_LATEX:
        return None
    try:
        with CERROJO:                    # ni ziamath ni PDFium se usan desde dos hilos a la vez
            if _DESCONOCIDO.search(latex2mathml.converter.convert(latex)):
                return None
            svg = ziamath.Math.fromlatex(latex, size=tam).svg()
            return _a_imagen(svg, ancho_max)
    except Exception:                    # noqa: BLE001  (una fórmula rara nunca debe impedir el examen)
        logger.info("No se pudo dibujar una fórmula", exc_info=True)
        return None


def _a_imagen(svg: str, ancho_max: float) -> Optional[Formula]:
    raiz = ElementTree.fromstring(svg)
    x0, y0, w, h = (float(v) for v in raiz.attrib["viewBox"].split())
    if not (w > 0 and h > 0 and ancho_max > 0):
        return None
    k = min(1.0, ancho_max / w)
    ancho, alto = w * k, h * k
    if ancho * ESCALA * alto * ESCALA > LIMITE_PIXELES:
        return None
    bytes_pdf = io.BytesIO()
    c = canvas.Canvas(bytes_pdf, pagesize=(ancho, alto), invariant=1)
    # Las coordenadas del SVG crecen hacia abajo y las del PDF hacia arriba.
    c.transform(k, 0, 0, -k, -x0 * k, (y0 + h) * k)
    c.setFillColorRGB(0, 0, 0)
    for el in raiz.iter():
        nombre = el.tag.rsplit("}", 1)[-1]
        if nombre in ("svg", "g"):
            if "transform" in el.attrib:
                return None
        elif nombre == "path" and "transform" not in el.attrib:
            _trazo(c, el.attrib.get("d", ""))
        elif nombre == "rect" and "transform" not in el.attrib:
            c.rect(*(float(el.attrib.get(a, 0)) for a in ("x", "y", "width", "height")), stroke=0, fill=1)
        else:
            return None                  # algo que no sabemos dibujar: mejor la fórmula escrita que una a medias
    c.showPage()
    c.save()
    documento = pdfium.PdfDocument(bytes_pdf.getvalue())
    try:
        pagina = documento[0]
        imagen = pagina.render(scale=ESCALA, fill_color=(255, 255, 255, 0)).to_pil().copy()
        pagina.close()
    finally:
        documento.close()
    salida = io.BytesIO()
    imagen.save(salida, "PNG")
    return Formula(png=salida.getvalue(), ancho=ancho, alto=alto, bajo=(y0 + h) * k)


def _trazo(c: canvas.Canvas, d: str) -> None:
    """Un `d` de SVG con órdenes absolutas (M, L, H, V, Q, C, Z), relleno con la regla «non-zero» de las fuentes."""
    p = c.beginPath()
    orden, numeros = "", []          # type: str, List[float]
    x = y = inicio_x = inicio_y = 0.0
    cuantos = {"M": 2, "L": 2, "H": 1, "V": 1, "Q": 4, "C": 6}
    for letra, numero, otra in _TROZO.findall(d):
        if otra:
            raise ValueError(f"orden de trazo no admitida: {otra}")
        if letra:
            if numeros:
                raise ValueError("trazo incompleto")
            orden = letra
            if orden == "Z":
                p.close()
                x, y = inicio_x, inicio_y
            continue
        numeros.append(float(numero))
        if len(numeros) < cuantos.get(orden, 99):
            continue
        if orden == "M":
            x, y = numeros
            inicio_x, inicio_y = x, y
            p.moveTo(x, y)
            orden = "L"              # más pares tras una M son líneas
        elif orden in ("L", "H", "V"):
            x, y = (numeros[0], numeros[1]) if orden == "L" else (numeros[0], y) if orden == "H" else (x, numeros[0])
            p.lineTo(x, y)
        elif orden == "Q":           # ReportLab solo tiene curvas cúbicas: se convierte
            cx, cy, fx, fy = numeros
            p.curveTo(x + 2 / 3 * (cx - x), y + 2 / 3 * (cy - y), fx + 2 / 3 * (cx - fx), fy + 2 / 3 * (cy - fy), fx, fy)
            x, y = fx, fy
        else:
            p.curveTo(*numeros)
            x, y = numeros[4], numeros[5]
        numeros = []
    if numeros:
        raise ValueError("trazo incompleto")
    c.drawPath(p, stroke=0, fill=1, fillMode=1)
