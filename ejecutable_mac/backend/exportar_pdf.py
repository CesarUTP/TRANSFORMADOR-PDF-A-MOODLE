"""
exportar_pdf.py — el examen revisado como PDF imprimible, con su clave (2.1).

Es un documento de APOYO: el docente lo guarda o lo imprime junto al Moodle
XML, que sigue siendo lo que se importa a Moodle. El PDF sale de las MISMAS
preguntas y la MISMA clave que el XML y usa los mismos resolutores del modelo
(modelo.py) para decidir qué es correcto, así que no puede discrepar de él. No
inventa nada: lo que no se pudo escribir en papel (un carácter que la fuente
no tiene, una fórmula que no se convierte a texto, una imagen ilegible) se
deja visible o se avisa.

    resultado = generar_pdf(preguntas, answer_key, total_points, datos)
    resultado.pdf, resultado.paginas, resultado.avisos

Maquetación (ReportLab, Platypus): papel Carta o A4, márgenes de 2 cm, cada
pregunta entera en su página mientras quepa, casillas dibujadas como figuras
(círculo = una respuesta, cuadrado = varias; así se imprimen igual en cualquier
fuente y en blanco y negro), «Página X de Y». La CLAVE va en páginas aparte al
final (o sola): cada respuesta con su letra Y su texto, porque Moodle mezcla
las opciones y la letra sola no basta.
"""

import base64
import io
import random
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, legal, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate, Flowable, Frame, Image as RLImage, Indenter, KeepTogether, NextPageTemplate,
    PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.platypus.doctemplate import LayoutError

import latex_texto
from config import DEFAULT_MATCHING_STEM
from modelo import (
    Pregunta, PreguntaCloze, PreguntaEssay, PreguntaMatching, PreguntaMultichoice,
    PreguntaNumerical, PreguntaShortanswer, PreguntaTruefalse, preguntas_desde_dicts,
)
from xml_builder import compute_grades

CONTENIDOS = ("examen_y_clave", "solo_examen", "solo_clave", "folleto_hoja_clave")
PAPELES = {"carta": letter, "legal": legal, "a4": A4}      # legal = 21,59 x 35,56 cm
# Márgenes como los de Word (en cm): (arriba, abajo, izquierda, derecha).
MARGENES = {"normal": (2.5, 2.5, 3.0, 3.0), "estrechos": (1.27, 1.27, 1.27, 1.27),
            "moderados": (2.54, 2.54, 1.91, 1.91), "anchos": (2.54, 2.54, 5.08, 5.08)}
LIMITE_CAMPO = 160
LIMITE_INSTRUCCIONES = 1500
LIMITE_VERSION = 20                     # «A», «B»… o un nombre corto
LIMITE_LOGO = 2_000_000                 # caracteres base64 (~1,5 MB) por logo
ROTULOS = {"facilitador": "FACILITADOR", "docente": "DOCENTE", "profesor": "PROFESOR"}

ROMANOS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX"]
NOMBRE_PARTE = {"multichoice": "SELECCIÓN MÚLTIPLE", "truefalse": "VERDADERO O FALSO", "matching": "EMPAREJAMIENTO",
                "cloze": "COMPLETAR", "shortanswer": "RESPUESTA CORTA", "numerical": "RESPUESTA NUMÉRICA", "essay": "DESARROLLO"}

# Opciones que dependen de su POSICIÓN («todas las anteriores», «A y B»…): esa pregunta no se mezcla.
_POSICIONAL = re.compile(r"\b(anteriores?|ambas|ambos|las dos|los dos|todas las (opciones|respuestas|de arriba)|"
                         r"ninguna de (las|los)|ninguno de (las|los)|(opci[oó]n|incisos?|literal(es)?)\s+[A-J])\b|"
                         r"\b[A-J]\s*(y|e|o|,)\s*[A-J]\b", re.I)

_DIR_FUENTES = Path(__file__).resolve().parent / "fuentes"
_FAMILIA = "DejaVu"                       # la fuente de respaldo: tiene casi todos los símbolos
_ESTILOS_FUENTE = {"": 0, "-B": 1, "-I": 2, "-BI": 3}
# Tipos de letra elegibles: clave → (nombre en ReportLab, [normal, negrita, cursiva, negrita cursiva]).
FUENTES = {
    "dejavu": ("DejaVu", ["DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf"]),
    "arial": ("LiberationSans", ["LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf", "LiberationSans-Italic.ttf", "LiberationSans-BoldItalic.ttf"]),
    "times": ("LiberationSerif", ["LiberationSerif-Regular.ttf", "LiberationSerif-Bold.ttf", "LiberationSerif-Italic.ttf", "LiberationSerif-BoldItalic.ttf"]),
}
TAM_MIN, TAM_MAX = 7.0, 20.0
RENGLONES_MIN, RENGLONES_MAX = 2, 24
_GRIS = colors.HexColor("#555555")
_GRIS_CLARO = colors.HexColor("#b8b8b8")
_FONDO = colors.HexColor("#f2f2f2")


@dataclass
class DatosExamen:
    """Lo que el docente escribe antes de exportar (todo opcional)."""
    institucion: str = ""
    facultad: str = ""
    departamento: str = ""
    materia: str = ""
    docente: str = ""
    actividad: str = ""
    grupo: str = ""
    fecha: str = ""
    instrucciones: str = ""
    titulo_respaldo: str = "Examen"          # si no hay actividad ni materia (el nombre del archivo)
    version: str = ""                        # «A», «B»…: una de las versiones de un examen (sale en el encabezado y en la clave)
    contenido: str = "examen_y_clave"        # CONTENIDOS
    papel: str = "carta"                     # PAPELES
    margenes: str = "moderados"              # MARGENES
    campos_estudiante: bool = True           # cuadro de Nombre / Cédula / Grupo / Fecha y Calificación
    rotulo_docente: str = "facilitador"      # ROTULOS
    puntos_por_pregunta: bool = True         # False: el examen no dice cuánto vale cada pregunta (solo cada parte y el total)
    puntos_enteros: bool = False             # True: el PDF solo admite puntos enteros (si llega un decimal, se rechaza: nunca se redondea aquí)
    renglones_ensayo: int = 6                # renglones de cada respuesta de desarrollo
    mezclar: bool = True                     # mezclar las opciones y la Columna B: que la clave no forme un patrón
    fuente_titulos: str = "dejavu"           # FUENTES: títulos, encabezados e indicaciones
    tam_titulos: float = 11.0                # tamaño (pt) del encabezado; lo demás de ese grupo es proporcional
    fuente_preguntas: str = "dejavu"         # FUENTES: las preguntas, sus opciones y la clave
    tam_preguntas: float = 10.0              # tamaño (pt) del enunciado; lo demás de ese grupo es proporcional
    partes: bool = True                      # agrupar por tipo: «I PARTE: …» con su indicación y su valor
    logo_izquierdo: str = ""                 # imagen en base64 ("" = sin logo)
    logo_derecho: str = ""


class PuntosNoEnteros(ValueError):
    """Se pidió un PDF con puntos enteros y alguna pregunta trae decimales (se muestra al docente)."""


def _decimal(x: float) -> bool:
    return abs(x - round(x)) > 1e-6


def revisar_puntos_enteros(preguntas: List[Pregunta], puntos: List[float]) -> None:
    """Con `puntos_enteros`, el servidor NO redondea (el PDF dejaría de coincidir con lo que el docente vio):
    avisa qué preguntas traen decimales y deja que la interfaz las reparta."""
    malas = [(p.num, x) for p, x in zip(preguntas, puntos) if _decimal(x)]
    if not malas:
        return
    detalle = ", ".join(f"{n} ({str(round(x, 2)).replace('.', ',')})" for n, x in malas[:5]) + ("…" if len(malas) > 5 else "")
    raise PuntosNoEnteros(
        f"Con «Puntos enteros» activado, {len(malas)} pregunta{'s' if len(malas) != 1 else ''} del PDF "
        f"tiene{'n' if len(malas) != 1 else ''} puntos con decimales: {detalle}. Reparte los puntos en enteros o desactiva esa opción.")


@dataclass
class ResultadoPdf:
    pdf: bytes
    paginas: int
    preguntas: int
    avisos: List[str] = field(default_factory=list)


# ── Fuente ──────────────────────────────────────────────────────────────────

_COBERTURA: Dict[str, frozenset] = {}
_CANDADO = threading.Lock()


def _registrar_fuentes(*claves: str) -> None:
    """Registra DejaVu (siempre, es la de respaldo) y los tipos de letra pedidos; ReportLab guarda las fuentes por
    nombre, así que cada una se registra una sola vez por proceso."""
    with _CANDADO:
        for clave in ("dejavu",) + tuple(claves):
            nombre, archivos = FUENTES[clave]
            if nombre in _COBERTURA:
                continue
            for sufijo, archivo in zip(_ESTILOS_FUENTE, archivos):
                pdfmetrics.registerFont(TTFont(nombre + sufijo, str(_DIR_FUENTES / archivo)))
            pdfmetrics.registerFontFamily(nombre, normal=nombre, bold=nombre + "-B", italic=nombre + "-I", boldItalic=nombre + "-BI")
            _COBERTURA[nombre] = frozenset(pdfmetrics.getFont(nombre).face.charToGlyph)


# ── Texto: de lo que escribió el docente al marcado de un párrafo ───────────

class _Texto:
    """Convierte textos del examen en marcado seguro de Paragraph y cuenta lo que no se pudo
    escribir tal cual (para avisarlo)."""

    def __init__(self, familias: Tuple[str, ...] = (_FAMILIA,)) -> None:
        self.formulas_crudas = 0
        self.sin_glifo = 0
        # Lo que NO tienen todas las fuentes elegidas se escribe con DejaVu (que casi lo tiene todo).
        self.cobertura = [_COBERTURA[f] for f in set(familias) if f != _FAMILIA]

    def plano(self, s: Any) -> str:
        """El texto con las fórmulas convertidas y sin caracteres imposibles de imprimir (SIN escapar)."""
        s = unicodedata.normalize("NFC", str(s if s is not None else ""))
        s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
        s, _, crudas = latex_texto.formulas_a_texto(s)
        self.formulas_crudas += crudas
        out: List[str] = []
        for ch in s:
            if ch == "\n" or ord(ch) in _COBERTURA[_FAMILIA]:
                out.append(ch)
            elif unicodedata.category(ch) in ("Cf", "Cc", "Mn", "Me", "Cs", "Co", "Cn"):
                continue                       # invisibles (ZWJ, selectores de variación, control)
            else:
                out.append("?")
                self.sin_glifo += 1
        return "".join(out)

    def marcado(self, s: Any) -> str:
        t = self.plano(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        t = re.sub(r" {2,}", lambda m: " " * (len(m.group(0)) - 1) + " ", t)
        t = re.sub(r"(?m)^ ", " ", t)
        if self.cobertura:
            t = re.sub(r"[^\x00-\x7f]+", lambda m: self._respaldo(m.group(0)), t)
        return t.replace("\n", "<br/>")

    def _respaldo(self, trozo: str) -> str:
        """Los caracteres que la fuente elegida no tiene van con DejaVu, en el mismo párrafo."""
        salida, fuera = [], []
        for ch in trozo:
            if any(ord(ch) not in c for c in self.cobertura):
                fuera.append(ch)
            else:
                if fuera:
                    salida.append(f'<font name="{_FAMILIA}">{"".join(fuera)}</font>')
                    fuera = []
                salida.append(ch)
        if fuera:
            salida.append(f'<font name="{_FAMILIA}">{"".join(fuera)}</font>')
        return "".join(salida)


def _campo(s: Any, limite: int) -> str:
    """Un dato de la portada: una línea, sin controles, con tope de largo."""
    t = re.sub(r"[\x00-\x1f\x7f]+", " ", str(s or "")).strip()
    return t[:limite]


def _pts(x: float) -> str:
    s = f"{x:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{s} pt" if s == "1" else f"{s} pts"


# ── Figuras ─────────────────────────────────────────────────────────────────

class _Casilla(Flowable):
    """Círculo (una respuesta) o cuadrado (varias), dibujado: no depende de ningún glifo."""

    def __init__(self, redonda: bool, lado: float = 8.5):
        super().__init__()
        self.redonda, self.lado = redonda, lado

    def wrap(self, aw, ah):
        return self.lado, self.lado

    def draw(self):
        c = self.canv
        c.setLineWidth(0.8)
        c.setStrokeColor(colors.black)
        if self.redonda:
            c.circle(self.lado / 2, self.lado / 2, self.lado / 2 - 0.4)
        else:
            c.rect(0.4, 0.4, self.lado - 0.8, self.lado - 0.8)


class _Renglones(Flowable):
    """Espacio rayado para una respuesta de desarrollo."""

    def __init__(self, n: int, paso: float = 22):
        super().__init__()
        self.n, self.paso = n, paso

    def wrap(self, aw, ah):
        self.ancho = aw
        return aw, self.n * self.paso

    def draw(self):
        c = self.canv
        c.setStrokeColor(_GRIS_CLARO)
        c.setLineWidth(0.6)
        for i in range(self.n):
            y = self.paso * (i + 1) - 4
            c.line(0, y, self.ancho, y)


class _Lienzo(canvas.Canvas):
    """Pone «Página X de Y» al final, cuando ya se sabe cuántas páginas hay. Cada sección (el examen o el folleto,
    la hoja de respuestas, la clave) numera las suyas: se imprimen y se reparten por separado."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._estados: List[dict] = []

    def showPage(self):
        self._estados.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        por_seccion: Dict[Any, int] = {}
        for estado in self._estados:
            s = estado.get("_seccion")
            por_seccion[s] = por_seccion.get(s, 0) + 1
        vistas: Dict[Any, int] = {}
        for estado in self._estados:
            self.__dict__.update(estado)
            s = estado.get("_seccion")
            vistas[s] = vistas.get(s, 0) + 1
            self.setFont(getattr(self, "_fuente_pie", _FAMILIA), 8)
            self.setFillColor(_GRIS)
            self.drawRightString(self._pagesize[0] - getattr(self, "_margen_der", 2 * cm), getattr(self, "_pie_y", 1.1 * cm),
                                 f"Página {vistas[s]} de {por_seccion[s]}")
            super().showPage()
        super().save()


class _Burbujas(Flowable):
    """Fila de una hoja de respuestas de opción: el número y una burbuja con su letra por opción (círculo = una
    respuesta, cuadro = varias). Con `marcadas` es la clave: esas burbujas van rellenas."""

    PASO = 19

    def __init__(self, num: int, letras: List[str], redonda: bool, marcadas=(), fam: str = _FAMILIA):
        super().__init__()
        self.num, self.letras, self.redonda, self.marcadas, self.fam = num, list(letras), redonda, set(marcadas), fam

    def wrap(self, aw, ah):
        self.aw = aw
        return aw, 19

    def draw(self):
        c = self.canv
        c.setFont(self.fam + "-B", 9)
        c.setFillColor(colors.black)
        etiqueta = f"{self.num}."
        c.drawString(0, 5, etiqueta)
        x = max(24, pdfmetrics.stringWidth(etiqueta, self.fam + "-B", 9) + 6)
        r = 6.6
        for letra in self.letras:
            lleno = letra in self.marcadas
            c.setLineWidth(0.8)
            c.setStrokeColor(colors.black)
            c.setFillColor(colors.black if lleno else colors.white)
            if self.redonda:
                c.circle(x + r, 9.5, r, stroke=1, fill=1)
            else:
                c.rect(x, 9.5 - r, 2 * r, 2 * r, stroke=1, fill=1)
            c.setFillColor(colors.white if lleno else colors.black)
            c.setFont(self.fam, 7)
            c.drawCentredString(x + r, 7.2, letra)
            x += self.PASO


class _Huecos(Flowable):
    """Respuestas que se escriben, en una hoja de respuestas: «6.  1. ______  2. ______». Con valores es la clave
    (la respuesta escrita sobre la raya). `items` = [(etiqueta, valor o None, largo de la raya o None = hasta el
    final de la línea)]; si no caben en una línea pasan a la siguiente."""

    PASO = 24

    def __init__(self, num: int, items, tam: float = 10, fam: str = _FAMILIA):
        super().__init__()
        self.num, self.items, self.tam, self.fam = num, list(items), tam, fam

    def _disponer(self, aw):
        fb = self.fam + "-B"
        x0 = pdfmetrics.stringWidth(f"{self.num}.", fb, self.tam) + 10
        filas, fila, x = [], [], x0
        for etiqueta, valor, largo in self.items:
            w_et = (pdfmetrics.stringWidth(etiqueta, fb, self.tam) + 4) if etiqueta else 0
            real = largo if largo is not None else max(60.0, aw - x - w_et)
            if fila and x + w_et + real > aw:
                filas.append(fila)
                fila, x = [], x0
                real = largo if largo is not None else max(60.0, aw - x - w_et)
            fila.append((x, etiqueta, valor, w_et, real))
            x += w_et + real + 14
        filas.append(fila)
        return filas

    def wrap(self, aw, ah):
        self.filas = self._disponer(aw)
        return aw, len(self.filas) * self.PASO + 2

    def draw(self):
        c = self.canv
        fb = self.fam + "-B"
        alto = len(self.filas) * self.PASO + 2
        for r, fila in enumerate(self.filas):
            y = alto - (r + 1) * self.PASO + 8
            c.setFillColor(colors.black)
            if r == 0:
                c.setFont(fb, self.tam)
                c.drawString(0, y, f"{self.num}.")
            for x, etiqueta, valor, w_et, largo in fila:
                if etiqueta:
                    c.setFont(fb, self.tam)
                    c.drawString(x, y, etiqueta)
                c.setStrokeColor(colors.black)
                c.setLineWidth(0.7)
                c.line(x + w_et, y - 2, x + w_et + largo, y - 2)
                if valor:
                    tam = self.tam
                    while tam > 6 and pdfmetrics.stringWidth(valor, fb, tam) > largo - 4:
                        tam -= 0.5
                    c.setFont(fb, tam)
                    c.drawCentredString(x + w_et + largo / 2, y, valor)


# ── Estilos ─────────────────────────────────────────────────────────────────

def _estilos(sangria: float, fe: str, fp: str, tam_titulos: float, tam_preguntas: float) -> Dict[str, ParagraphStyle]:
    """Dos grupos: lo de la institución (encabezado, partes, indicaciones: fuente `fe`, tamaño `tam_titulos`) y lo
    del examen (enunciados, opciones, clave: fuente `fp`, tamaño `tam_preguntas`). Cada estilo mide lo que medía
    con 11 y 10 pt, en proporción."""
    r, q = tam_titulos / 11.0, tam_preguntas / 10.0
    base = ParagraphStyle("base", fontName=fp, fontSize=10 * q, leading=13.5 * q)
    en = lambda nombre, **kw: ParagraphStyle(nombre, parent=base, **{"fontName": fe, **kw})
    return {
        "base": base,
        "enunciado": ParagraphStyle("enunciado", parent=base, leftIndent=sangria, bulletIndent=0,
                                    bulletFontName=fp + "-B", spaceBefore=11, spaceAfter=3),
        "ayuda": ParagraphStyle("ayuda", parent=base, fontName=fp + "-I", fontSize=8.5 * q,
                                leading=11 * q, textColor=_GRIS, spaceAfter=3),
        "opcion": ParagraphStyle("opcion", parent=base),
        "parte": en("parte", fontName=fe + "-B", fontSize=10.5 * r, leading=14 * r, spaceBefore=16, spaceAfter=2),
        "aviso_folleto": en("aviso_folleto", fontName=fe + "-B", fontSize=9 * r, leading=12 * r, alignment=1, textColor=_GRIS),
        "opcion_lista": ParagraphStyle("opcion_lista", parent=base, fontSize=9.5 * q, leading=12.5 * q, leftIndent=16, bulletIndent=0,
                                       bulletFontName=fp + "-B", spaceAfter=1.5),
        "celda": ParagraphStyle("celda", parent=base, fontSize=9.5 * q, leading=12.5 * q),
        "titulo": en("titulo", fontName=fe + "-B", fontSize=16 * r, leading=20 * r, alignment=1, spaceAfter=4),
        "institucion": en("institucion", fontSize=10.5 * r, leading=14 * r, alignment=1, textColor=_GRIS, spaceAfter=2),
        "cabecera": en("cabecera", fontName=fe + "-B", fontSize=11 * r, leading=14.5 * r, alignment=1),
        "rotulo": en("rotulo", fontName=fe + "-B", fontSize=10.5 * r, leading=14 * r),
        "indicacion": en("indicacion", fontSize=10 * r, leading=13.5 * r, leftIndent=22, bulletIndent=8, bulletFontName=fe, spaceAfter=2),
        "datos": en("datos", fontSize=9.5 * r, leading=12.5 * r, alignment=1, textColor=_GRIS, spaceAfter=8),
        "valor": en("valor", fontSize=10 * r, leading=13 * r),
        "etiqueta": en("etiqueta", fontName=fe + "-B", fontSize=9 * r, leading=12 * r),
        "pequeno": ParagraphStyle("pequeno", parent=base, fontSize=9 * q, leading=12 * q),
        "clave": ParagraphStyle("clave", parent=base, leftIndent=sangria, bulletIndent=0,
                                bulletFontName=fp + "-B", spaceBefore=5),
    }


# ── Imágenes ────────────────────────────────────────────────────────────────

def _imagen(im, ancho_max: float, alto_max: float) -> Optional[RLImage]:
    """La imagen de una pregunta (ver _imagen_b64)."""
    return _imagen_b64(im.b64, im.mime, ancho_max, alto_max)


def _imagen_b64(b64: Optional[str], mime: Optional[str], ancho_max: float, alto_max: float,
                ampliar: bool = False) -> Optional[RLImage]:
    """Una imagen en base64, reescrita con Pillow (PNG o JPEG sin transparencia) para que
    cualquier formato, paleta o canal alfa se imprima igual. None si no se puede leer.
    `ampliar`: llena la caja aunque la imagen sea más pequeña (los logos)."""
    try:
        crudo = base64.b64decode(b64 or "", validate=False)
        with PILImage.open(io.BytesIO(crudo)) as origen:
            origen.load()
            ancho_px, alto_px = origen.size
            if ancho_px < 1 or alto_px < 1:
                return None
            if origen.mode in ("RGBA", "LA", "P"):
                rgba = origen.convert("RGBA")
                fondo = PILImage.new("RGB", rgba.size, "white")
                fondo.paste(rgba, mask=rgba.split()[-1])
                listo = fondo
            else:
                listo = origen.convert("RGB")
        salida = io.BytesIO()
        if (mime or "").lower().endswith("png"):
            listo.save(salida, "PNG")
        else:
            listo.save(salida, "JPEG", quality=88)
        salida.seek(0)
    except Exception:
        return None
    # 96 ppp como medida natural: una captura pequeña no se agranda, una grande se ajusta a la hoja.
    ancho, alto = ancho_px * 0.75, alto_px * 0.75
    k = min(ancho_max / ancho, alto_max / alto)
    if not ampliar:
        k = min(1.0, k)
    return RLImage(salida, width=ancho * k, height=alto * k, hAlign="LEFT")


# ── El examen ───────────────────────────────────────────────────────────────

class _Constructor:
    def __init__(self, preguntas: List[Pregunta], puntos: List[float], datos: DatosExamen, simple: bool = False):
        self.preguntas, self.puntos, self.datos, self.simple = preguntas, puntos, datos, simple
        self.tam = PAPELES.get(datos.papel, letter)
        arriba, abajo, izquierda, derecha = (x * cm for x in MARGENES.get(datos.margenes, MARGENES["moderados"]))
        self.m_sup, self.m_inf, self.m_izq, self.m_der = arriba, abajo, izquierda, derecha
        self.ancho = self.tam[0] - izquierda - derecha
        # Hueco del número de pregunta: «100.» no cabe en lo que cabe «10.».
        self.sangria = 18 + 9 * max(0, len(str(len(preguntas))) - 2)
        # Tipos de letra y tamaños: lo desconocido o fuera de rango vuelve al de siempre (la ruta ya lo rechaza).
        self.fe = FUENTES.get(datos.fuente_titulos, FUENTES["dejavu"])[0]
        self.fp = FUENTES.get(datos.fuente_preguntas, FUENTES["dejavu"])[0]
        self.H = min(TAM_MAX, max(TAM_MIN, float(datos.tam_titulos))) if datos.tam_titulos == datos.tam_titulos else 11.0
        self.Q = min(TAM_MAX, max(TAM_MIN, float(datos.tam_preguntas))) if datos.tam_preguntas == datos.tam_preguntas else 10.0
        self.renglones = min(RENGLONES_MAX, max(RENGLONES_MIN, int(datos.renglones_ensayo)))
        self.est = _estilos(self.sangria, self.fe, self.fp, self.H, self.Q)
        self.est['opcion_folleto'] = ParagraphStyle('opcion_folleto', parent=self.est['base'], leftIndent=18, bulletIndent=0,
                                                    bulletFontName=self.fp + '-B', spaceAfter=2)
        self.txt = _Texto((self.fe, self.fp))
        self.imagenes_fallidas: List[int] = []
        self.logos_fallidos: List[str] = []
        self.folleto = False                  # True mientras se arma el folleto: preguntas sin espacio para responder
        actividad, materia = _campo(datos.actividad, LIMITE_CAMPO), _campo(datos.materia, LIMITE_CAMPO)
        self.titulo = " · ".join(x for x in (actividad, materia) if x) or _campo(datos.titulo_respaldo, LIMITE_CAMPO) or "Examen"
        self.version = _campo(datos.version, LIMITE_VERSION).upper()

    # ---- piezas comunes ----
    def _p(self, texto: str, estilo: str = "base") -> Paragraph:
        return Paragraph(texto, self.est[estilo])

    def _enunciado(self, n: int, texto: str, puntos: float) -> Paragraph:
        cuerpo = self.txt.marcado(texto)
        return Paragraph(f"{cuerpo}{self._pts_de(puntos)}", self.est["enunciado"], bulletText=f"{n}.")

    def _pts_de(self, puntos: float) -> str:
        """« (2 pts)» al final del enunciado, o nada si el docente pidió ocultar el valor de cada pregunta."""
        if not self.datos.puntos_por_pregunta:
            return ""
        return f" <font size='{self.Q * 0.8:.1f}' color='#555555'>({_pts(puntos)})</font>"

    def _imagenes(self, p: Pregunta, n: int) -> list:
        out = []
        for im in p.images or []:
            f = _imagen(im, self.ancho - self.sangria, 7.5 * cm)
            if f is None:
                self.imagenes_fallidas.append(n)
            else:
                out += [Spacer(1, 3), f, Spacer(1, 3)]
        return out

    def _opcion(self, casilla: Optional[_Casilla], texto: str) -> Any:
        if casilla is None or self.simple:
            return self._p(("○ " if casilla is not None and casilla.redonda else "□ " if casilla is not None else "") + texto)
        t = Table([[casilla, self._p(texto, "opcion")]], colWidths=[18, self.ancho - self.sangria - 18])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (0, 0), 2.5),
                               ("TOPPADDING", (1, 0), (1, 0), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        return t

    # ---- orden en que se IMPRIMEN las opciones (y por tanto la clave) ----
    def _opciones_impresas(self, p: PreguntaMultichoice) -> List[Tuple[str, str, bool]]:
        """[(letra impresa, texto, es correcta)] en el orden del papel. Con `mezclar` se barajan (siempre igual para la
        misma pregunta) para que la clave no forme un patrón; una pregunta cuyas opciones dependen de su posición
        («todas las anteriores», «A y B») conserva el suyo. Al barajar, las letras se reasignan A, B, C…"""
        correctas = set(p.resolver_correctas()[0])
        items = [(L, p.options[L]) for L in sorted(p.options or {})]
        if self.datos.mezclar and len(items) > 1 and not any(_POSICIONAL.search(str(tx)) for _, tx in items):
            random.Random(f"mc-{p.num}").shuffle(items)
            return [(chr(65 + i) if i < 26 else str(i + 1), tx, L in correctas) for i, (L, tx) in enumerate(items)]
        return [(L, tx, L in correctas) for L, tx in items]

    def _pareo(self, p: PreguntaMatching):
        """(claves de la Columna A, [(letra impresa, texto)] de la Columna B, {clave de A: letra impresa de su pareja}).
        Con `mezclar` la Columna B se baraja hasta que las respuestas no formen un patrón (1-a, 2-b, 3-c… o al revés,
        o casi todas en su sitio): en el documento original suele ir en el mismo orden que la A."""
        col_a, col_b = p.col_a or {}, p.col_b or {}
        a_claves = sorted(col_a, key=lambda x: int(x) if str(x).isdigit() else str(x))
        b_claves = sorted(col_b)
        parejas = [p.letra_de(k) for k in a_claves]
        orden = list(b_claves)
        if self.datos.mezclar and len(orden) > 1:
            for intento in range(80):
                cand = list(b_claves)
                random.Random(f"mt-{p.num}-{intento}").shuffle(cand)
                seq = [cand.index(L) for L in parejas if L is not None]
                if len(seq) < 3:
                    bueno = cand != b_claves
                else:
                    fijos = sum(1 for i, s in enumerate(seq) if i == s)
                    bueno = seq != sorted(seq) and seq != sorted(seq, reverse=True) and fijos <= len(seq) // 3
                orden = cand
                if bueno:
                    break
            letras = [chr(97 + i) if i < 26 else str(i + 1) for i in range(len(orden))]
        else:
            letras = list(orden)
        impresas = [(letras[i], col_b[L]) for i, L in enumerate(orden)]
        nueva = {L: letras[i] for i, L in enumerate(orden)}
        return a_claves, impresas, {k: nueva.get(L) for k, L in zip(a_claves, parejas)}

    # ---- una pregunta del examen (sin respuestas) ----
    def pregunta(self, n: int, p: Pregunta, puntos: float, ayudas: bool = True) -> KeepTogether:
        if self.folleto:
            return self._pregunta_folleto(n, p, puntos, ayudas)
        if isinstance(p, PreguntaMultichoice):
            letras, _ = p.resolver_correctas()
            varias = len(letras) > 1
            items = [self._enunciado(n, p.stem, puntos)] + self._imagenes(p, n)
            items.append(Indenter(left=self.sangria))
            if ayudas:
                items.append(self._p("Selecciona todas las que correspondan." if varias else "Selecciona una.", "ayuda"))
            for letra, texto, _ok in self._opciones_impresas(p):
                items.append(self._opcion(_Casilla(redonda=not varias), f"<b>{self.txt.marcado(letra)})</b> {self.txt.marcado(texto)}"))
            items.append(Indenter(left=-self.sangria))
            return KeepTogether(items)

        if isinstance(p, PreguntaTruefalse):
            items = [self._enunciado(n, p.stem, puntos)] + self._imagenes(p, n) + [Indenter(left=self.sangria)]
            items += [self._opcion(_Casilla(True), "Verdadero"), self._opcion(_Casilla(True), "Falso"), Indenter(left=-self.sangria)]
            return KeepTogether(items)

        if isinstance(p, PreguntaMatching):
            col_a = p.col_a or {}
            a_claves, b_impresas, _de_a = self._pareo(p)
            filas = [[self._p("<b>Columna A</b>", "celda"), self._p("<b>Columna B</b>", "celda")]]
            for i in range(max(len(a_claves), len(b_impresas))):
                izq = (f"<b>______ {self.txt.marcado(a_claves[i])}.</b> {self.txt.marcado(col_a[a_claves[i]])}") if i < len(a_claves) else ""
                der = (f"<b>{self.txt.marcado(b_impresas[i][0])})</b> {self.txt.marcado(b_impresas[i][1])}") if i < len(b_impresas) else ""
                filas.append([self._p(izq, "celda"), self._p(der, "celda")])
            mitad = (self.ancho - self.sangria) / 2
            tabla = Table(filas, colWidths=[mitad, mitad])
            tabla.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                       ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LINEBELOW", (0, 0), (-1, 0), 0.5, _GRIS_CLARO)]))
            return KeepTogether([self._enunciado(n, p.stem or DEFAULT_MATCHING_STEM, puntos)] + self._imagenes(p, n) + [
                Indenter(left=self.sangria)]
                + ([self._p("Escribe en cada espacio la letra de la Columna B que corresponde.", "ayuda")] if ayudas else [])
                + [tabla, Indenter(left=-self.sangria)])

        if isinstance(p, PreguntaCloze):
            return self._cloze(n, p, puntos, ayudas)

        if isinstance(p, PreguntaEssay):
            return KeepTogether([self._enunciado(n, p.stem, puntos)] + self._imagenes(p, n) + [
                Indenter(left=self.sangria), Spacer(1, 4), _Renglones(self.renglones), Indenter(left=-self.sangria)])

        # respuesta corta y numérica: una línea
        return KeepTogether([self._enunciado(n, p.stem, puntos)] + self._imagenes(p, n) + [
            Indenter(left=self.sangria), Spacer(1, 4), self._p("Respuesta: " + "_" * 38), Indenter(left=-self.sangria)])

    def _pregunta_folleto(self, n: int, p: Pregunta, puntos: float, ayudas: bool) -> KeepTogether:
        """La pregunta del folleto: solo para leer. No lleva casillas ni rayas (se responde en la hoja de respuestas)."""
        if isinstance(p, PreguntaMultichoice):
            varias = len(p.resolver_correctas()[0]) > 1
            items = [self._enunciado(n, p.stem, puntos)] + self._imagenes(p, n) + [Indenter(left=self.sangria)]
            if ayudas:
                items.append(self._p("Selecciona todas las que correspondan." if varias else "Selecciona una.", "ayuda"))
            items += [Paragraph(self.txt.marcado(texto), self.est["opcion_folleto"], bulletText=f"{self.txt.marcado(letra)})")
                      for letra, texto, _ok in self._opciones_impresas(p)]
            return KeepTogether(items + [Indenter(left=-self.sangria)])
        if isinstance(p, PreguntaMatching):
            col_a = p.col_a or {}
            a_claves, b_impresas, _de_a = self._pareo(p)
            filas = [[self._p("<b>Columna A</b>", "celda"), self._p("<b>Columna B</b>", "celda")]]
            for i in range(max(len(a_claves), len(b_impresas))):
                izq = f"<b>{self.txt.marcado(a_claves[i])}.</b> {self.txt.marcado(col_a[a_claves[i]])}" if i < len(a_claves) else ""
                der = f"<b>{self.txt.marcado(b_impresas[i][0])})</b> {self.txt.marcado(b_impresas[i][1])}" if i < len(b_impresas) else ""
                filas.append([self._p(izq, "celda"), self._p(der, "celda")])
            mitad = (self.ancho - self.sangria) / 2
            tabla = Table(filas, colWidths=[mitad, mitad])
            tabla.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                       ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LINEBELOW", (0, 0), (-1, 0), 0.5, _GRIS_CLARO)]))
            return KeepTogether([self._enunciado(n, p.stem or DEFAULT_MATCHING_STEM, puntos)] + self._imagenes(p, n)
                                + [Indenter(left=self.sangria), tabla, Indenter(left=-self.sangria)])
        if isinstance(p, PreguntaCloze):
            return self._cloze(n, p, puntos, ayudas)
        # verdadero/falso, respuesta corta, numérica y desarrollo: solo el enunciado
        return KeepTogether([self._enunciado(n, p.stem, puntos)] + self._imagenes(p, n))

    @staticmethod
    def _orden_hueco(p: PreguntaCloze, h) -> List[int]:
        """Posiciones de las opciones de un hueco en el orden en que se IMPRIMEN. Se barajan (siempre igual para
        la misma pregunta) porque en el documento la correcta va primera; la clave usa este mismo orden."""
        orden = list(range(len(h.opciones)))
        azar = random.Random(f"{p.num}-{h.letra}")
        azar.shuffle(orden)
        if len(orden) > 1 and orden[0] == 0:           # nunca en su lugar de origen: ahí va la correcta
            j = azar.randrange(1, len(orden))
            orden[0], orden[j] = orden[j], orden[0]
        return orden

    @staticmethod
    def _letra_opcion(i: int) -> str:
        return "abcdefghijklmnopqrstuvwxyz"[i] if i < 26 else str(i + 1)

    def _cloze(self, n: int, p: PreguntaCloze, puntos: float, ayudas: bool = True) -> KeepTogether:
        """Un «Completar» en papel, como el cloze de opción múltiple de los exámenes: en el texto cada espacio es
        «(1) ____» y debajo, UNA LISTA POR ESPACIO con sus opciones lettered a), b), c)… (una por línea si son
        largas, en una sola línea si son cortas). El estudiante escribe la letra elegida en el espacio. Un espacio
        con un solo texto posible es de escribir y lleva una raya larga."""
        texto = p.text or ""
        huecos = p.huecos()
        trozos, ultimo = [], 0
        for k, h in enumerate(huecos, 1):
            trozos.append(self.txt.marcado(texto[ultimo:h.inicio]))
            raya = "_" * (10 if len(h.opciones) >= 2 else 22)
            trozos.append(f"<b>({k})</b>\u00a0{raya}")
            ultimo = h.fin
        trozos.append(self.txt.marcado(texto[ultimo:]))
        enunciado = Paragraph("".join(trozos) + self._pts_de(puntos),
                              self.est["enunciado"], bulletText=f"{n}.")
        filas = []
        for k_hueco, h in enumerate(huecos, 1):
            if len(h.opciones) < 2:
                continue
            correctas, _ = h.resolver()
            opciones = [(self._letra_opcion(k), self.txt.marcado(h.opciones[i])) for k, i in enumerate(self._orden_hueco(p, h))]
            if max(len(self.txt.plano(h.opciones[i])) for i in range(len(h.opciones))) <= 16:
                celda = [self._p("     ".join(f"<b>{le})</b>\u00a0{tx}" for le, tx in opciones), "celda")]
            else:
                celda = [Paragraph(tx, self.est["opcion_lista"], bulletText=f"{le})") for le, tx in opciones]
            if len(correctas) > 1:
                celda.append(self._p("Elige todas las que correspondan: escribe todas las letras.", "ayuda"))
            filas.append([self._p(f"<b>{k_hueco}.</b>", "celda"), celda])
        cuerpo: list = []
        if filas:
            tabla = Table(filas, colWidths=[1.0 * cm, self.ancho - self.sangria - 1.0 * cm])
            tabla.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                       ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                       ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LINEBELOW", (0, 0), (-1, -2), 0.4, _GRIS_CLARO)]))
            cuerpo = [Indenter(left=self.sangria)]
            if ayudas:
                cuerpo.append(self._p("Escribe en cada espacio la letra de la opción que lo completa." if all(len(h.opciones) >= 2 for h in huecos)
                                      else "En los espacios con opciones escribe la letra elegida; en los demás, la respuesta.", "ayuda"))
            cuerpo += [tabla, Indenter(left=-self.sangria)]
        return KeepTogether([enunciado] + self._imagenes(p, n) + cuerpo)

    # ---- una entrada de la clave ----
    def entrada_clave(self, n: int, p: Pregunta, puntos: float) -> KeepTogether:
        t = self.txt
        lineas: List[str] = []
        if isinstance(p, PreguntaMultichoice):
            lineas = [f"<b>{t.marcado(L)})</b> {t.marcado(tx)}" for L, tx, ok in self._opciones_impresas(p) if ok]
        elif isinstance(p, PreguntaTruefalse):
            v = p.es_verdadero()
            lineas = ["<b>Verdadero</b>" if v else "<b>Falso</b>"] if v is not None else []
        elif isinstance(p, PreguntaMatching):
            a_claves, b_impresas, de_a = self._pareo(p)
            textos_b = dict(b_impresas)
            lineas = [f"{t.marcado(k)}. {t.marcado((p.col_a or {})[k])} → <b>{t.marcado(de_a[k])})</b> {t.marcado(textos_b[de_a[k]])}"
                      for k in a_claves if de_a.get(k)]
        elif isinstance(p, PreguntaCloze):
            for k_hueco, h in enumerate(p.huecos(), 1):
                idx, _ = h.resolver()
                if not idx:
                    continue
                if len(h.opciones) >= 2:
                    pos = {i: k for k, i in enumerate(self._orden_hueco(p, h))}      # el mismo orden que se imprimió
                    dicho = "; ".join(f"<b>{self._letra_opcion(pos[i])})</b> {t.marcado(h.opciones[i])}" for i in sorted(idx, key=pos.get))
                else:
                    dicho = f"<b>{t.marcado(h.opciones[idx[0]])}</b>"
                lineas.append(f"<b>({k_hueco})</b> " + dicho)
        elif isinstance(p, PreguntaNumerical):
            v = p.valor_numerico() or p.respuesta_texto.strip()
            lineas = [f"<b>{t.marcado(v)}</b>"] if v and not p.sin_respuesta else []
        elif isinstance(p, PreguntaShortanswer):
            lineas = [f"<b>{t.marcado(p.respuesta_texto.strip())}</b>"] if not p.sin_respuesta else []
        elif isinstance(p, PreguntaEssay):
            lineas = ["<i>Respuesta abierta: se califica a mano.</i>"]
            if (p.feedback or "").strip():
                lineas.append(f"<i>Orientación:</i> {t.marcado(p.feedback.strip())}")
        if not lineas:
            lineas = ["<i>(sin respuesta válida en la clave)</i>"]
        cabecera = self.txt.marcado(self._resumen(p)) + f" <font size='{self.Q * 0.8:.1f}' color='#555555'>({_pts(puntos)})</font>"
        return KeepTogether([Paragraph(cabecera, self.est["clave"], bulletText=f"{n}."),
                             Indenter(left=self.sangria)] + [self._p(x, "pequeno") for x in lineas] + [Indenter(left=-self.sangria)])

    @staticmethod
    def _resumen(p: Pregunta, largo: int = 70) -> str:
        """El comienzo del enunciado, para reconocer la pregunta en la clave."""
        s = " ".join((p.stem or p.text or "").split())
        s = re.sub(r"\[[A-Za-z]: ([^\]/]*)[^\]]*\]", "____", s)
        return s if len(s) <= largo else s[:largo - 1].rstrip() + "…"

    # ---- hoja de respuestas (y clave llena) ----
    def _valor_cloze(self, p: PreguntaCloze, h) -> str:
        idx, _ = h.resolver()
        if not idx:
            return ""
        if len(h.opciones) >= 2:
            pos = {i: k for k, i in enumerate(self._orden_hueco(p, h))}      # el mismo orden que se imprimió
            return ", ".join(self._letra_opcion(pos[i]) for i in sorted(idx, key=pos.get))
        return h.opciones[idx[0]]

    def _fila_hoja(self, n: int, p: Pregunta, llena: bool) -> list:
        """Lo que escribe el estudiante para una pregunta que no es de burbujas (con `llena`, la respuesta)."""
        if isinstance(p, PreguntaMatching):
            a_claves, _b, de_a = self._pareo(p)
            items = [(f"{self.txt.plano(k)}.", (self.txt.plano(de_a.get(k) or "") if llena else None), 1.5 * cm) for k in a_claves]
            return [_Huecos(n, items, self.Q, self.fp)]
        if isinstance(p, PreguntaCloze):
            items = []
            for k, h in enumerate(p.huecos(), 1):
                con_opciones = len(h.opciones) >= 2
                items.append((f"({k})", self.txt.plano(self._valor_cloze(p, h)) if llena else None, 1.7 * cm if con_opciones else 5.5 * cm))
            return [_Huecos(n, items, self.Q, self.fp)]
        if isinstance(p, PreguntaNumerical):
            v = (p.valor_numerico() or p.respuesta_texto.strip()) if llena and not p.sin_respuesta else None
            return [_Huecos(n, [("", self.txt.plano(v) if v else None, 5 * cm)], self.Q, self.fp)]
        if isinstance(p, PreguntaShortanswer):
            v = p.respuesta_texto.strip() if llena and not p.sin_respuesta else None
            return [_Huecos(n, [("", self.txt.plano(v) if v else None, None)], self.Q, self.fp)]
        if isinstance(p, PreguntaEssay):
            if llena:
                texto = f"<b>{n}.</b> <i>Respuesta abierta: se califica a mano.</i>"
                if (p.feedback or "").strip():
                    texto += f" <i>Orientación:</i> {self.txt.marcado(p.feedback.strip())}"
                return [self._p(texto, "pequeno"), Spacer(1, 4)]
            return [self._p(f"<b>{n}.</b>", "pequeno"), _Renglones(self.renglones), Spacer(1, 4)]
        return [self._p(f"<b>{n}.</b>", "pequeno")]

    def _burbujas(self, n: int, p: Pregunta, llena: bool) -> _Burbujas:
        if isinstance(p, PreguntaTruefalse):
            v = p.es_verdadero()
            return _Burbujas(n, ["V", "F"], True, [("V" if v else "F")] if llena and v is not None else [], self.fp)
        opciones = self._opciones_impresas(p)
        correctas = [L for L, _tx, ok in opciones if ok]
        return _Burbujas(n, [L for L, _tx, _ok in opciones], len(correctas) <= 1, correctas if llena else [], self.fp)

    def hoja_respuestas(self, llena: bool) -> list:
        """La hoja de respuestas por partes: burbujas para opción múltiple y verdadero/falso, rayas para lo demás.
        Con `llena` es la clave (las mismas burbujas rellenas y las respuestas escritas)."""
        salida: list = []
        n = 0
        for i, (tipo, grupo) in enumerate(self.partes()):
            titulo = [self._titulo_parte(i, tipo, grupo, True, hoja=True)] if tipo is not None else []
            corrida: List[_Burbujas] = []

            def emitir(piezas: list):
                nonlocal titulo
                salida.append(KeepTogether(titulo + piezas) if titulo else KeepTogether(piezas))
                titulo = []

            def vaciar():
                if not corrida:
                    return
                maximo = max(len(b.letras) for b in corrida)
                cols = max(1, min(4, int(self.ancho // (28 + maximo * _Burbujas.PASO + 8))))
                filas = -(-len(corrida) // cols)
                celdas = [[corrida[c * filas + r] if c * filas + r < len(corrida) else "" for c in range(cols)] for r in range(filas)]
                tabla = Table(celdas, colWidths=[self.ancho / cols] * cols)
                tabla.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                                           ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
                emitir([Spacer(1, 2), tabla, Spacer(1, 4)])
                corrida.clear()

            for p, _pts in grupo:
                n += 1
                if isinstance(p, (PreguntaMultichoice, PreguntaTruefalse)):
                    corrida.append(self._burbujas(n, p, llena))
                else:
                    vaciar()
                    emitir(self._fila_hoja(n, p, llena))
            vaciar()
        return salida

    # ---- partes del examen ----
    def partes(self) -> List[Tuple[Optional[str], List[Tuple[Pregunta, float]]]]:
        """[(tipo, [(pregunta, puntos)])]. Con `partes` las preguntas se agrupan por tipo, en el orden en que cada
        tipo aparece por primera vez; sin él, todo va junto y en el orden del editor (tipo None)."""
        pares = list(zip(self.preguntas, self.puntos))
        if not self.datos.partes:
            return [(None, pares)]
        grupos: Dict[str, List[Tuple[Pregunta, float]]] = {}
        for p, pts in pares:
            grupos.setdefault(p.tipo or "", []).append((p, pts))
        return list(grupos.items())

    def _indicacion(self, tipo: Optional[str], grupo: List[Tuple[Pregunta, float]]) -> str:
        """Lo que el estudiante debe hacer en una parte, según el tipo (y, en opción múltiple y «Completar»,
        según lo que traigan sus preguntas, que es lo que el papel le muestra). En el folleto remite a la hoja de respuestas."""
        if self.folleto:
            return self._indicacion_folleto(tipo, grupo)
        if tipo == "multichoice":
            varias = [len(q.resolver_correctas()[0]) > 1 for q, _ in grupo if isinstance(q, PreguntaMultichoice)]
            if all(varias):
                return "MARQUE CON UNA X EL CUADRO DE TODAS LAS OPCIONES QUE USTED CONSIDERE CORRECTAS."
            if not any(varias):
                return "MARQUE CON UNA X EL CÍRCULO DE LA OPCIÓN QUE USTED CONSIDERE COMO RESPUESTA CORRECTA."
            return ("MARQUE CON UNA X EL CÍRCULO (UNA SOLA RESPUESTA) O EL CUADRO (TODAS LAS CORRECTAS) "
                    "DE LAS OPCIONES QUE USTED CONSIDERE CORRECTAS.")
        if tipo == "truefalse":
            return "MARQUE CON UNA X EL CÍRCULO DE «VERDADERO» O «FALSO», SEGÚN CORRESPONDA."
        if tipo == "matching":
            return "ESCRIBA EN CADA ESPACIO LA LETRA DE LA COLUMNA B QUE CORRESPONDA A CADA ELEMENTO DE LA COLUMNA A."
        if tipo == "cloze":
            solo_opciones = all(len(h.opciones) >= 2 for q, _ in grupo if isinstance(q, PreguntaCloze) for h in q.huecos())
            return ("ESCRIBA EN CADA ESPACIO LA LETRA DE LA OPCIÓN QUE COMPLETA CORRECTAMENTE EL ENUNCIADO." if solo_opciones else
                    "ESCRIBA EN CADA ESPACIO CON OPCIONES LA LETRA DE LA OPCIÓN QUE COMPLETA CORRECTAMENTE EL ENUNCIADO; "
                    "EN LOS DEMÁS, ESCRIBA LA RESPUESTA.")
        if tipo == "shortanswer":
            return "ESCRIBA EN LA LÍNEA LA RESPUESTA CORTA A CADA PREGUNTA."
        if tipo == "numerical":
            return "ESCRIBA EN LA LÍNEA EL VALOR NUMÉRICO QUE RESPONDE CADA PREGUNTA."
        if tipo == "essay":
            return "DESARROLLE SU RESPUESTA EN EL ESPACIO PROVISTO."
        return ""

    def _indicacion_folleto(self, tipo: Optional[str], grupo: List[Tuple[Pregunta, float]]) -> str:
        hoja = "EN LA HOJA DE RESPUESTAS"
        if tipo == "multichoice":
            varias = [len(q.resolver_correctas()[0]) > 1 for q, _ in grupo if isinstance(q, PreguntaMultichoice)]
            if all(varias):
                return f"SELECCIONE TODAS LAS OPCIONES QUE USTED CONSIDERE CORRECTAS Y MARQUE SUS LETRAS {hoja}."
            if not any(varias):
                return f"SELECCIONE LA OPCIÓN QUE USTED CONSIDERE COMO RESPUESTA CORRECTA Y MARQUE SU LETRA {hoja}."
            return f"SELECCIONE UNA O VARIAS OPCIONES, SEGÚN INDIQUE CADA PREGUNTA, Y MARQUE SUS LETRAS {hoja}."
        if tipo == "truefalse":
            return f"MARQUE {hoja} «V» SI LA AFIRMACIÓN ES VERDADERA O «F» SI ES FALSA."
        if tipo == "matching":
            return f"ESCRIBA {hoja} LA LETRA DE LA COLUMNA B QUE CORRESPONDA A CADA ELEMENTO DE LA COLUMNA A."
        if tipo == "cloze":
            solo_opciones = all(len(h.opciones) >= 2 for q, _ in grupo if isinstance(q, PreguntaCloze) for h in q.huecos())
            return (f"ESCRIBA {hoja} LA LETRA DE LA OPCIÓN QUE COMPLETA CORRECTAMENTE CADA ESPACIO." if solo_opciones else
                    f"ESCRIBA {hoja} LA LETRA DE LA OPCIÓN QUE COMPLETA CADA ESPACIO CON OPCIONES; EN LOS DEMÁS, ESCRIBA LA RESPUESTA.")
        if tipo == "shortanswer":
            return f"ESCRIBA {hoja} LA RESPUESTA CORTA A CADA PREGUNTA."
        if tipo == "numerical":
            return f"ESCRIBA {hoja} EL VALOR NUMÉRICO QUE RESPONDE CADA PREGUNTA."
        if tipo == "essay":
            return f"DESARROLLE SU RESPUESTA EN EL ESPACIO DE LA HOJA DE RESPUESTAS."
        return ""

    def _indicacion_hoja(self, tipo: Optional[str], grupo: List[Tuple[Pregunta, float]]) -> str:
        if tipo == "multichoice":
            varias = [len(q.resolver_correctas()[0]) > 1 for q, _ in grupo if isinstance(q, PreguntaMultichoice)]
            if all(varias):
                return "RELLENE POR COMPLETO EL CUADRO DE CADA OPCIÓN CORRECTA."
            if not any(varias):
                return "RELLENE POR COMPLETO EL CÍRCULO DE LA OPCIÓN ESCOGIDA."
            return "RELLENE POR COMPLETO EL CÍRCULO (UNA RESPUESTA) O LOS CUADROS (VARIAS) DE LAS OPCIONES ESCOGIDAS."
        if tipo == "truefalse":
            return "RELLENE POR COMPLETO EL CÍRCULO DE «V» (VERDADERO) O «F» (FALSO)."
        if tipo == "matching":
            return "ESCRIBA EN CADA RAYA LA LETRA DE LA COLUMNA B."
        if tipo == "cloze":
            return "ESCRIBA EN CADA RAYA LA LETRA DE LA OPCIÓN ESCOGIDA (O LA RESPUESTA, EN LOS ESPACIOS SIN OPCIONES)."
        if tipo == "shortanswer":
            return "ESCRIBA LA RESPUESTA EN LA RAYA."
        if tipo == "numerical":
            return "ESCRIBA EL VALOR NUMÉRICO EN LA RAYA."
        if tipo == "essay":
            return "DESARROLLE SU RESPUESTA EN LOS RENGLONES."
        return ""

    def _titulo_parte(self, i: int, tipo: Optional[str], grupo, con_indicacion: bool, hoja: bool = False) -> Paragraph:
        valor = _pts(sum(pts for _, pts in grupo)).upper()
        nombre = NOMBRE_PARTE.get(tipo or "", "PREGUNTAS")
        ind = (self._indicacion_hoja(tipo, grupo) if hoja else self._indicacion(tipo, grupo)) if con_indicacion else ""
        texto = f"{ROMANOS[min(i, len(ROMANOS) - 1)]} PARTE: {nombre}" + (f": {ind}" if ind else "") + f" VALOR: {valor}"
        return self._p(self.txt.marcado(texto), "parte")

    # ---- portada, encabezados y documento ----
    def _ancho_negrita(self, texto: str, tam: float) -> float:
        return pdfmetrics.stringWidth(texto, self.fe + "-B", tam)

    def _una_linea(self, texto: str, ancho: float, tam: float, alinear: int = 0) -> Paragraph:
        """Un párrafo en negrita de tamaño `tam` que cabe SIEMPRE en una línea de `ancho`: lo que sobre se
        corta con «…» (el texto nunca pasa a otra línea)."""
        plano = self.txt.plano(texto).replace("\n", " ")
        ancho -= 1.5
        if self._ancho_negrita(plano, tam) > ancho:
            while plano and self._ancho_negrita(plano + "…", tam) > ancho:
                plano = plano[:-1]
            plano = plano.rstrip() + "…"
        estilo = ParagraphStyle("linea", parent=self.est["rotulo"], fontSize=tam, leading=tam + 3, alignment=alinear)
        return Paragraph(plano.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), estilo)

    def _logo(self, b64: str, lado: str) -> Optional[RLImage]:
        if not (b64 or "").strip():
            return None
        f = _imagen_b64(b64, "image/png", 2.5 * cm, 2.5 * cm, ampliar=True)
        if f is None:
            self.logos_fallidos.append(lado)
        return f

    def cabecera(self, total: float, clave: bool = False, modo: str = "examen") -> list:
        """Encabezado de la primera hoja: logos y título centrado, cuadro del estudiante, docente y
        calificación, indicaciones. En la clave el cuadro dice «CLAVE» y no lleva calificación ni indicaciones."""
        d = self.datos
        folleto, hoja = modo == "folleto", modo == "hoja"
        estudiante = d.campos_estudiante and not folleto       # el folleto no se escribe: sin cuadro de estudiante
        lineas = [_campo(x, LIMITE_CAMPO).upper() for x in (d.institucion, d.facultad, d.departamento, d.materia, d.actividad)]
        lineas = [x for x in lineas if x] or [self.titulo.upper()]
        if self.version:
            lineas.append(f"VERSIÓN {self.version}")
        centro = [self._p(self.txt.marcado(x), "cabecera") for x in lineas]
        izq, der = self._logo(d.logo_izquierdo, "izquierdo"), self._logo(d.logo_derecho, "derecho")
        items: list = []
        if izq is None and der is None:
            items += centro
        else:
            lado = 2.7 * cm
            tabla = Table([[izq or "", centro, der or ""]], colWidths=[lado, self.ancho - 2 * lado, lado])
            tabla.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (0, 0), "LEFT"), ("ALIGN", (2, 0), (2, 0), "RIGHT"),
                                       ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                       ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
            for logo, col in ((izq, 0), (der, 2)):
                if logo is not None:
                    logo.hAlign = "LEFT" if col == 0 else "RIGHT"
            items.append(tabla)
        items.append(Spacer(1, 8))

        docente = _campo(d.docente, LIMITE_CAMPO)
        rotulo = ROTULOS.get(d.rotulo_docente, ROTULOS["facilitador"])
        if estudiante:
            w = self.ancho
            # Las etiquetas miden lo que miden (con márgenes anchos no pueden partirse): el resto se reparte entre los espacios.
            e1 = max(self._ancho_negrita(x, self.H * 10.5 / 11) for x in ("NOMBRE:", "GRUPO:")) + 14
            e2 = max(self._ancho_negrita(x, self.H * 10.5 / 11) for x in ("CÉDULA:", "FECHA:")) + 14
            etiqueta = lambda s: self._p(s, "rotulo")
            valor = lambda s, estilo="valor": self._p(self.txt.marcado(s), estilo)
            nombre = self._p("<i>CLAVE</i>", "rotulo") if clave else ""
            cuadro = Table([[etiqueta("NOMBRE:"), nombre, etiqueta("CÉDULA:"), ""],
                            [etiqueta("GRUPO:"), valor(_campo(d.grupo, LIMITE_CAMPO)), etiqueta("FECHA:"), valor(_campo(d.fecha, LIMITE_CAMPO))]],
                           colWidths=[e1, (w - e1 - e2) * 0.56, e2, (w - e1 - e2) * 0.44], rowHeights=[max(0.95 * cm, self.H * 2.1)] * 2)
            cuadro.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.8, colors.black), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                        ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
            items += [cuadro, Spacer(1, 12)]
        # «FACILITADOR: …» y «CALIFICACIÓN: ___/N»: SIEMPRE en una sola línea. La calificación tiene su
        # ancho; el nombre usa el resto y, si es muy largo, se achica la letra (y al final, «…»).
        if estudiante and not clave:
            nota = f"CALIFICACIÓN: ________/{_pts(total).rsplit(' ', 1)[0]}"
        elif not estudiante:
            extra = [f"{rot}: {_campo(v, LIMITE_CAMPO)}" for rot, v in (("Grupo", d.grupo), ("Fecha", d.fecha)) if _campo(v, LIMITE_CAMPO)]
            nota = None
        else:
            nota = None
        if estudiante:
            izquierda = f"{rotulo}: {docente}" if docente else ""
        else:
            izquierda = "   ·   ".join(([f"{rotulo}: {docente}"] if docente else []) + extra)
        if izquierda or nota:
            # El nombre y la calificación comparten tamaño de letra: si no caben a 10,5 pt se achican los dos
            # por igual (hasta 7 pt) y, si aun así sobra, se corta el nombre con «…».
            hueco = 12 if nota else 0
            plano_i, plano_n = self.txt.plano(izquierda), self.txt.plano(nota or "")
            tam = self.H * 10.5 / 11
            suma = self._ancho_negrita(plano_i, tam) + self._ancho_negrita(plano_n, tam)
            if suma + hueco > self.ancho - 6:
                tam = max(TAM_MIN, tam * (self.ancho - 6 - hueco) / suma)
            ancho_nota = (self._ancho_negrita(plano_n, tam) + 2) if nota else 0
            ancho_izq = self.ancho - ancho_nota - hueco
            celdas = [self._una_linea(izquierda, ancho_izq, tam) if izquierda else ""]
            anchos = [ancho_izq]
            if nota:
                celdas.append(self._una_linea(nota, ancho_nota, tam, alinear=2))
                anchos = [ancho_izq + hueco, ancho_nota]
            fila_t = Table([celdas], colWidths=anchos)
            fila_t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                        ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
            items += [fila_t, Spacer(1, 10)]

        if folleto:
            items += [self._p("NO ESCRIBA EN ESTE FOLLETO: SUS RESPUESTAS VAN EN LA HOJA DE RESPUESTAS.", "aviso_folleto"), Spacer(1, 8)]
        instr = _campo_largo(d.instrucciones, LIMITE_INSTRUCCIONES)
        if instr and not clave and not hoja:
            items.append(self._p("INDICACIONES GENERALES:", "rotulo"))
            items.append(Spacer(1, 4))
            for linea in instr.split("\n"):
                linea = re.sub(r"^\s*[-•*·]\s*", "", linea).strip()
                if linea:
                    items.append(Paragraph(self.txt.marcado(linea), self.est["indicacion"], bulletText="•"))
            items.append(Spacer(1, 6))
        return items

    def _encabezado(self, seccion: str, derecha: str, primera_sin: bool):
        izquierda = " · ".join(x for x in (_campo(self.datos.materia, 60), _campo(self.datos.actividad, 60)) if x) or self.titulo
        if self.version:
            izquierda += f" · VERSIÓN {self.version}"

        def dibujar(c, doc):
            c._seccion = seccion                     # para «Página X de Y» dentro de su sección (ver _Lienzo)
            c._margen_der = self.m_der               # el pie va dentro del margen inferior, a la altura que quepa
            c._pie_y = max(0.45 * cm, self.m_inf - 0.8 * cm)
            c._fuente_pie = self.fe
            # Primera hoja de la sección: lleva el encabezado grande, no el corrido.
            self._vista["n"] = self._vista["n"] + 1 if self._vista["seccion"] == seccion else 1
            self._vista["seccion"] = seccion
            if primera_sin and self._vista["n"] == 1:
                return
            c.saveState()
            c.setFont(self.fe, 8)
            c.setFillColor(_GRIS)
            y = self.tam[1] - max(0.55 * cm, self.m_sup - 0.8 * cm)      # dentro del margen superior
            c.drawString(self.m_izq, y, self.txt.plano(izquierda))
            c.drawRightString(self.tam[0] - self.m_der, y, self.txt.plano(derecha))
            c.setStrokeColor(_GRIS_CLARO)
            c.setLineWidth(0.5)
            c.line(self.m_izq, y - 4, self.tam[0] - self.m_der, y - 4)
            c.restoreState()
        return dibujar

    def construir(self) -> Tuple[bytes, int]:
        d = self.datos
        total = sum(self.puntos)
        buf = io.BytesIO()
        doc = BaseDocTemplate(buf, pagesize=self.tam, leftMargin=self.m_izq, rightMargin=self.m_der,
                              topMargin=self.m_sup, bottomMargin=self.m_inf, title=self.txt.plano(self.titulo),
                              author=self.txt.plano(_campo(d.docente, 80)), subject=self.txt.plano(_campo(d.materia, 80)),
                              creator="Cátedra")
        marco = lambda: Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="m", leftPadding=0, rightPadding=0,
                              topPadding=0, bottomPadding=0)
        self._vista = {"seccion": None, "n": 0}
        docente = _campo(d.docente, 60)
        plantillas = {
            "examen": PageTemplate(id="examen", frames=[marco()], onPage=self._encabezado("examen", docente, True)),
            "hoja": PageTemplate(id="hoja", frames=[marco()], onPage=self._encabezado("hoja", "HOJA DE RESPUESTAS", True)),
            "clave": PageTemplate(id="clave", frames=[marco()], onPage=self._encabezado("clave", "CLAVE DE RESPUESTAS · uso del docente", False)),
        }
        c = d.contenido
        orden = {"examen_y_clave": ["examen", "clave"], "solo_examen": ["examen"], "solo_clave": ["clave"],
                 "folleto_hoja_clave": ["examen", "hoja", "clave"]}[c]
        doc.addPageTemplates([plantillas[k] for k in orden])

        historia: list = []

        def cambiar_a(nombre: str):
            historia.extend([NextPageTemplate(nombre), PageBreak()])

        def partes_del_examen(folleto: bool):
            n = 0
            self.folleto = folleto
            for i, (tipo, grupo) in enumerate(self.partes()):
                mixto = tipo == "multichoice" and len({len(q.resolver_correctas()[0]) > 1 for q, _ in grupo}) > 1
                titulo = [self._titulo_parte(i, tipo, grupo, True)] if tipo is not None else []
                for p, pts in grupo:
                    n += 1
                    q = self.pregunta(n, p, pts, ayudas=(tipo is None or mixto))
                    # El título de la parte viaja DENTRO del bloque de su primera pregunta: nunca queda solo
                    # al final de una hoja con la parte empezando en la siguiente.
                    historia.append(KeepTogether(titulo + q._content) if titulo else q)
                    titulo = []
            self.folleto = False

        def clave_compacta():
            historia.extend(self.cabecera(total, clave=True))
            historia.extend([self._p("CLAVE DE RESPUESTAS", "titulo"),
                             self._p(self.txt.marcado("Documento para el docente: no se entrega a los estudiantes. "
                                                      "Las opciones se identifican por su letra y su texto porque Moodle las mezcla."), "datos")])
            n = 0
            for i, (tipo, grupo) in enumerate(self.partes()):
                titulo = [self._titulo_parte(i, tipo, grupo, False)] if tipo is not None else []
                for p, pts in grupo:
                    n += 1
                    e = self.entrada_clave(n, p, pts)
                    historia.append(KeepTogether(titulo + e._content) if titulo else e)
                    titulo = []

        if c in ("examen_y_clave", "solo_examen"):
            historia += self.cabecera(total)
            partes_del_examen(False)
        if c == "examen_y_clave":
            cambiar_a("clave")
        if c in ("examen_y_clave", "solo_clave"):
            clave_compacta()
        if c == "folleto_hoja_clave":
            historia += self.cabecera(total, modo="folleto")
            partes_del_examen(True)
            cambiar_a("hoja")
            historia += self.cabecera(total, modo="hoja")
            historia += [self._p("HOJA DE RESPUESTAS", "titulo"),
                         self._p("Escriba aquí sus respuestas; no escriba en el folleto de preguntas.", "datos")]
            historia += self.hoja_respuestas(False)
            cambiar_a("clave")
            historia += self.cabecera(total, clave=True, modo="hoja")
            historia += [self._p("CLAVE DE RESPUESTAS", "titulo"),
                         self._p(self.txt.marcado("Es la hoja de respuestas llena. Documento para el docente: no se entrega a los estudiantes."), "datos")]
            historia += self.hoja_respuestas(True)
        doc.build(historia, canvasmaker=_Lienzo)
        return buf.getvalue(), doc.page


def _campo_largo(s: Any, limite: int) -> str:
    """Un texto de varias líneas (instrucciones): sin controles raros y con tope de largo."""
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+", " ", str(s or "")).replace("\r\n", "\n").strip()
    return t[:limite]


def generar_pdf(questions: List[Dict[str, Any]], answer_key: Dict[int, Dict[str, Any]],
                total_points: float, datos: DatosExamen) -> ResultadoPdf:
    """El PDF del examen (y su clave). `questions` y `answer_key` son los mismos que recibe
    xml_builder.build_xml: aquí no se valida (lo hace la ruta, igual que para el XML)."""
    if datos.fuente_titulos not in FUENTES or datos.fuente_preguntas not in FUENTES:
        raise ValueError("tipo de letra no válido")
    _registrar_fuentes(datos.fuente_titulos, datos.fuente_preguntas)
    if datos.contenido not in CONTENIDOS:
        raise ValueError("contenido no válido")
    preguntas = [p for p in preguntas_desde_dicts(questions, answer_key) if not p.tiene_error]
    if not preguntas:
        raise ValueError("No hay preguntas que exportar.")
    notas = compute_grades(questions, total_points)
    puntos = [p.puntos_validos if p.puntos_validos is not None else notas.get(p.tipo, 1.0) for p in preguntas]
    if datos.puntos_enteros:
        revisar_puntos_enteros(preguntas, puntos)

    # Si una pregunta no cabe en una página dentro de una tabla (algo enorme), se rehace sin tablas.
    for simple in (False, True):
        c = _Constructor(preguntas, puntos, datos, simple=simple)
        try:
            pdf, paginas = c.construir()
            break
        except LayoutError:
            if simple:
                raise
    avisos: List[str] = []
    if c.txt.formulas_crudas:
        avisos.append(f"{c.txt.formulas_crudas} fórmula{'s' if c.txt.formulas_crudas != 1 else ''} no se pudo{'ieron' if c.txt.formulas_crudas != 1 else ''} "
                      "escribir como texto y quedó con su notación LaTeX entre \\( y \\).")
    if c.txt.sin_glifo:
        avisos.append(f"{c.txt.sin_glifo} carácter{'es' if c.txt.sin_glifo != 1 else ''} que la fuente del PDF no tiene se escribió como «?» "
                      "(por ejemplo, emojis).")
    if c.logos_fallidos:
        avisos.append("No se pudo usar el logo " + " ni el ".join(sorted(set(c.logos_fallidos))) + ": se omitió.")
    if c.imagenes_fallidas:
        avisos.append("No se pudo incluir la imagen de la pregunta " + ", ".join(str(n) for n in sorted(set(c.imagenes_fallidas))) + ".")
    return ResultadoPdf(pdf=pdf, paginas=paginas, preguntas=len(preguntas), avisos=avisos)
