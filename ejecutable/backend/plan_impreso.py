"""
plan_impreso.py — QUÉ lleva el examen en el papel, sin dibujarlo (2.8).

El PDF (`exportar_pdf.py`) y el Word (`exportar_docx.py`) salen del MISMO plan: aquí se decide, una sola vez,
el orden de las preguntas, las letras impresas de las opciones (con su barajado), cada texto de indicación, la
clave, la hoja de respuestas, las fórmulas ya convertidas, los tamaños y las medidas. Los dos dibujantes solo
traducen estos bloques a su formato, así que el contenido de uno y otro coincide por construcción.

    plan = construir_plan(questions, answer_key, total_points, datos)
    plan.secciones      → [Seccion(bloques=[…])]  (examen / hoja de respuestas / clave)
    plan.avisos         → lo que no se pudo escribir en papel (se le dice al docente)

El texto va en un marcado mínimo (el de los párrafos de ReportLab): `<b>`, `<i>`, `<br/>` y
`<font name=… size=… color=…>`; `&amp; &lt; &gt;` escapados. Cada dibujante lo lee a su manera.

Este módulo no dibuja nada, pero SÍ mide texto con las fuentes (la altura de una línea, si cabe o se corta con «…»),
para decidir igual en los dos formatos: por eso registra las fuentes en ReportLab.
"""

import base64
import io
import random
import re
import threading
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image as PILImage
from reportlab.lib.pagesizes import A4, legal, letter
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

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
GRIS = "#555555"
GRIS_CLARO = "#b8b8b8"
PASO_BURBUJAS = 19                      # separación de las burbujas de la hoja de respuestas
PASO_HUECOS = 24                        # alto de cada línea de «Huecos» de la hoja de respuestas
PASO_RENGLONES = 22                     # alto de cada renglón de desarrollo
LADO_CASILLA = 8.5


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


# ── Fuentes (se registran para MEDIR texto; los dibujantes las usan igual) ───

_COBERTURA: Dict[str, frozenset] = {}
_CANDADO = threading.Lock()


def registrar_fuentes(*claves: str) -> None:
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


# ── Los bloques del plan ────────────────────────────────────────────────────

@dataclass(frozen=True)
class Estilo:
    """Cómo se escribe un párrafo. `grupo`: «e» (la institución: encabezado, partes, indicaciones) o «p» (el examen:
    enunciados, opciones, clave); cada grupo tiene su tipo de letra y su tamaño. Las medidas van en puntos."""
    grupo: str
    tam: float
    leading: float
    negrita: bool = False
    cursiva: bool = False
    color: Optional[str] = None
    alinear: int = 0                  # 0 izquierda, 1 centro, 2 derecha
    sangria: float = 0.0              # sangría de TODO el párrafo (a la izquierda)
    vineta_sangria: float = 0.0       # dónde empieza la viñeta o el número
    vineta_negrita: bool = False
    vineta_tam: float = 10.0          # el número de una pregunta mide 10 pt aunque el texto sea más grande (como siempre)
    antes: float = 0.0
    despues: float = 0.0
    nombre: str = ""                  # cómo se llama el estilo (el Word lo crea con este nombre, editable)


@dataclass
class Parrafo:
    estilo: Estilo
    marcado: str
    vineta: Optional[str] = None      # «3.», «a)», «•»


@dataclass
class Espacio:
    alto: float


@dataclass
class Imagen:
    datos: bytes
    formato: str                      # "PNG" o "JPEG"
    ancho: float                      # pt
    alto: float
    alinear: str = "LEFT"


@dataclass
class Sangrado:
    """Lo que va dentro se corre `izquierda` pt a la derecha (las opciones respecto de su número)."""
    hijos: list
    izquierda: float


@dataclass
class Grupo:
    """Bloques que no se separan entre páginas mientras quepan (una pregunta con su título de parte)."""
    hijos: list


@dataclass
class Opcion:
    casilla: str                      # "redonda" (una respuesta) o "cuadrada" (varias)
    marcado: str


@dataclass
class TablaPareo:
    filas: List[Tuple[Parrafo, Parrafo]]     # la primera fila es el encabezado «Columna A | Columna B»


@dataclass
class TablaHuecos:
    """Un «Completar» en papel: una fila por espacio, con su número y la lista de sus opciones."""
    filas: List[Tuple[Parrafo, List[Parrafo]]]


@dataclass
class Renglones:
    n: int
    paso: float = PASO_RENGLONES


@dataclass
class Burbujas:
    """Fila de la hoja de respuestas de opción: el número y una burbuja con su letra por opción. Con `marcadas`
    es la clave (esas burbujas van rellenas)."""
    num: int
    letras: List[str]
    redonda: bool
    marcadas: Tuple[str, ...] = ()


@dataclass
class RejillaBurbujas:
    celdas: List[List[Optional[Burbujas]]]   # filas × columnas, por columnas (la 1.ª columna baja primero)
    columnas: int


@dataclass
class Huecos:
    """Respuestas que se escriben en la hoja de respuestas, ya repartidas en líneas: «6.  1. ______  2. ______».
    Cada elemento: (x, etiqueta, valor o None, ancho de la etiqueta, largo de la raya, tamaño del valor)."""
    num: int
    lineas: List[List[Tuple[float, str, Optional[str], float, float, float]]]
    tam: float


@dataclass
class LogosCabecera:
    izquierdo: Optional[Imagen]
    centro: List[Parrafo]
    derecho: Optional[Imagen]
    lado: float                       # ancho de cada columna de logo


@dataclass
class CuadroEstudiante:
    filas: List[list]                 # 2 filas × 4 celdas (Parrafo o "")
    anchos: List[float]
    alto_fila: float


@dataclass
class FilaDocente:
    """«FACILITADOR: …» y «CALIFICACIÓN: ___/N» en una sola línea, ya ajustadas de tamaño y de largo."""
    izquierda: Optional[Parrafo]
    nota: Optional[Parrafo]
    ancho_izquierda: float
    ancho_nota: float
    hueco: float


@dataclass
class Seccion:
    id: str                           # "examen", "hoja" o "clave": cada una numera sus páginas
    izquierda: str                    # encabezado corrido (texto plano)
    derecha: str
    primera_sin_encabezado: bool
    bloques: list = field(default_factory=list)


@dataclass
class Geo:
    papel: Tuple[float, float]
    m_sup: float
    m_inf: float
    m_izq: float
    m_der: float
    ancho: float                      # ancho útil
    sangria: float                    # hueco del número de pregunta


@dataclass
class Plan:
    datos: DatosExamen
    geo: Geo
    estilos: Dict[str, Estilo]
    fuente_e: str                     # nombre en ReportLab de la fuente de los títulos
    fuente_p: str                     # … y de las preguntas
    clave_fuente_e: str               # «dejavu», «arial» o «times» (para quien las nombre de otra forma)
    clave_fuente_p: str
    tam_titulos: float
    tam_preguntas: float
    titulo: str
    meta: Dict[str, str]
    secciones: List[Seccion]
    preguntas: int
    avisos: List[str]


# ── Texto: de lo que escribió el docente al marcado de un párrafo ───────────

class Texto:
    """Convierte textos del examen en marcado seguro y cuenta lo que no se pudo escribir tal cual (para avisarlo)."""

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
        t = re.sub(r" {2,}", lambda m: "\u00a0" * (len(m.group(0)) - 1) + " ", t)
        t = re.sub(r"(?m)^ ", "\u00a0", t)
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


def _campo_largo(s: Any, limite: int) -> str:
    """Un texto de varias líneas (instrucciones): sin controles raros y con tope de largo."""
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+", " ", str(s or "")).replace("\r\n", "\n").strip()
    return t[:limite]


def _pts(x: float) -> str:
    s = f"{x:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{s} pt" if s == "1" else f"{s} pts"


# ── Imágenes ────────────────────────────────────────────────────────────────

def imagen_desde_b64(b64: Optional[str], mime: Optional[str], ancho_max: float, alto_max: float,
                     ampliar: bool = False) -> Optional[Imagen]:
    """Una imagen en base64, reescrita con Pillow (PNG o JPEG sin transparencia) para que cualquier formato, paleta
    o canal alfa se imprima igual. None si no se puede leer. `ampliar`: llena la caja aunque la imagen sea más
    pequeña (los logos)."""
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
        formato = "PNG" if (mime or "").lower().endswith("png") else "JPEG"
        if formato == "PNG":
            listo.save(salida, "PNG")
        else:
            listo.save(salida, "JPEG", quality=88)
    except Exception:
        return None
    # 96 ppp como medida natural: una captura pequeña no se agranda, una grande se ajusta a la hoja.
    ancho, alto = ancho_px * 0.75, alto_px * 0.75
    k = min(ancho_max / ancho, alto_max / alto)
    if not ampliar:
        k = min(1.0, k)
    return Imagen(datos=salida.getvalue(), formato=formato, ancho=ancho * k, alto=alto * k)


# ── Estilos ─────────────────────────────────────────────────────────────────

def estilos(sangria: float, tam_titulos: float, tam_preguntas: float) -> Dict[str, Estilo]:
    """Dos grupos: lo de la institución (encabezado, partes, indicaciones: tamaño `tam_titulos`) y lo del examen
    (enunciados, opciones, clave: tamaño `tam_preguntas`). Cada estilo mide lo que medía con 11 y 10 pt, en proporción."""
    r, q = tam_titulos / 11.0, tam_preguntas / 10.0
    e = lambda tam, lead, **kw: Estilo("e", tam * r, lead * r, **kw)
    p = lambda tam, lead, **kw: Estilo("p", tam * q, lead * q, **kw)
    base = p(10, 13.5)
    todos = {
        "base": base,
        "enunciado": replace(base, sangria=sangria, vineta_negrita=True, antes=11, despues=3),
        "ayuda": p(8.5, 11, cursiva=True, color=GRIS, despues=3),
        "opcion": base,
        "parte": e(10.5, 14, negrita=True, antes=16, despues=2),
        "aviso_folleto": e(9, 12, negrita=True, alinear=1, color=GRIS),
        "opcion_lista": p(9.5, 12.5, sangria=16, vineta_negrita=True, despues=1.5),
        "celda": p(9.5, 12.5),
        "titulo": e(16, 20, negrita=True, alinear=1, despues=4),
        "institucion": e(10.5, 14, alinear=1, color=GRIS, despues=2),
        "cabecera": e(11, 14.5, negrita=True, alinear=1),
        "rotulo": e(10.5, 14, negrita=True),
        "indicacion": e(10, 13.5, sangria=22, vineta_sangria=8, despues=2),
        "datos": e(9.5, 12.5, alinear=1, color=GRIS, despues=8),
        "valor": e(10, 13),
        "etiqueta": e(9, 12, negrita=True),
        "pequeno": p(9, 12),
        "clave": replace(base, sangria=sangria, vineta_negrita=True, antes=5),
        "opcion_folleto": replace(base, sangria=18, vineta_negrita=True, despues=2),
    }
    return {k: replace(v, nombre=k) for k, v in todos.items()}


# ── El plan ─────────────────────────────────────────────────────────────────

class _Armador:
    def __init__(self, preguntas: List[Pregunta], puntos: List[float], datos: DatosExamen):
        self.preguntas, self.puntos, self.datos = preguntas, puntos, datos
        tam = PAPELES.get(datos.papel, letter)
        arriba, abajo, izquierda, derecha = (x * cm for x in MARGENES.get(datos.margenes, MARGENES["moderados"]))
        self.ancho = tam[0] - izquierda - derecha
        # Hueco del número de pregunta: «100.» no cabe en lo que cabe «10.».
        self.sangria = 18 + 9 * max(0, len(str(len(preguntas))) - 2)
        self.geo = Geo(papel=(tam[0], tam[1]), m_sup=arriba, m_inf=abajo, m_izq=izquierda, m_der=derecha,
                       ancho=self.ancho, sangria=self.sangria)
        # Tipos de letra y tamaños: lo desconocido o fuera de rango vuelve al de siempre (la ruta ya lo rechaza).
        self.fe = FUENTES.get(datos.fuente_titulos, FUENTES["dejavu"])[0]
        self.fp = FUENTES.get(datos.fuente_preguntas, FUENTES["dejavu"])[0]
        self.H = min(TAM_MAX, max(TAM_MIN, float(datos.tam_titulos))) if datos.tam_titulos == datos.tam_titulos else 11.0
        self.Q = min(TAM_MAX, max(TAM_MIN, float(datos.tam_preguntas))) if datos.tam_preguntas == datos.tam_preguntas else 10.0
        self.renglones = min(RENGLONES_MAX, max(RENGLONES_MIN, int(datos.renglones_ensayo)))
        self.est = estilos(self.sangria, self.H, self.Q)
        self.txt = Texto((self.fe, self.fp))
        self.imagenes_fallidas: List[int] = []
        self.logos_fallidos: List[str] = []
        self.folleto = False                  # True mientras se arma el folleto: preguntas sin espacio para responder
        actividad, materia = _campo(datos.actividad, LIMITE_CAMPO), _campo(datos.materia, LIMITE_CAMPO)
        self.titulo = " · ".join(x for x in (actividad, materia) if x) or _campo(datos.titulo_respaldo, LIMITE_CAMPO) or "Examen"
        self.version = _campo(datos.version, LIMITE_VERSION).upper()

    # ---- piezas comunes ----
    def _p(self, texto: str, estilo: str = "base") -> Parrafo:
        return Parrafo(self.est[estilo], texto)

    def _enunciado(self, n: int, texto: str, puntos: float) -> Parrafo:
        cuerpo = self.txt.marcado(texto)
        return Parrafo(self.est["enunciado"], f"{cuerpo}{self._pts_de(puntos)}", vineta=f"{n}.")

    def _pts_de(self, puntos: float) -> str:
        """« (2 pts)» al final del enunciado, o nada si el docente pidió ocultar el valor de cada pregunta."""
        if not self.datos.puntos_por_pregunta:
            return ""
        return f" <font size='{self.Q * 0.8:.1f}' color='{GRIS}'>({_pts(puntos)})</font>"

    def _imagenes(self, p: Pregunta, n: int) -> list:
        out = []
        for im in p.images or []:
            f = imagen_desde_b64(im.b64, im.mime, self.ancho - self.sangria, 7.5 * cm)
            if f is None:
                self.imagenes_fallidas.append(n)
            else:
                out += [Espacio(3), f, Espacio(3)]
        return out

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

    def _tabla_pareo(self, p: PreguntaMatching, folleto: bool) -> TablaPareo:
        col_a = p.col_a or {}
        a_claves, b_impresas, _de_a = self._pareo(p)
        filas = [(self._p("<b>Columna A</b>", "celda"), self._p("<b>Columna B</b>", "celda"))]
        for i in range(max(len(a_claves), len(b_impresas))):
            if folleto:
                izq = f"<b>{self.txt.marcado(a_claves[i])}.</b> {self.txt.marcado(col_a[a_claves[i]])}" if i < len(a_claves) else ""
            else:
                izq = (f"<b>______ {self.txt.marcado(a_claves[i])}.</b> {self.txt.marcado(col_a[a_claves[i]])}") if i < len(a_claves) else ""
            der = (f"<b>{self.txt.marcado(b_impresas[i][0])})</b> {self.txt.marcado(b_impresas[i][1])}") if i < len(b_impresas) else ""
            filas.append((self._p(izq, "celda"), self._p(der, "celda")))
        return TablaPareo(filas)

    # ---- una pregunta del examen (sin respuestas) ----
    def pregunta(self, n: int, p: Pregunta, puntos: float, ayudas: bool = True) -> Grupo:
        if self.folleto:
            return self._pregunta_folleto(n, p, puntos, ayudas)
        if isinstance(p, PreguntaMultichoice):
            letras, _ = p.resolver_correctas()
            varias = len(letras) > 1
            dentro: list = []
            if ayudas:
                dentro.append(self._p("Selecciona todas las que correspondan." if varias else "Selecciona una.", "ayuda"))
            for letra, texto, _ok in self._opciones_impresas(p):
                dentro.append(Opcion("cuadrada" if varias else "redonda", f"<b>{self.txt.marcado(letra)})</b> {self.txt.marcado(texto)}"))
            return Grupo([self._enunciado(n, p.stem, puntos)] + self._imagenes(p, n) + [Sangrado(dentro, self.sangria)])

        if isinstance(p, PreguntaTruefalse):
            return Grupo([self._enunciado(n, p.stem, puntos)] + self._imagenes(p, n)
                         + [Sangrado([Opcion("redonda", "Verdadero"), Opcion("redonda", "Falso")], self.sangria)])

        if isinstance(p, PreguntaMatching):
            dentro = ([self._p("Escribe en cada espacio la letra de la Columna B que corresponde.", "ayuda")] if ayudas else [])
            dentro.append(self._tabla_pareo(p, False))
            return Grupo([self._enunciado(n, p.stem or DEFAULT_MATCHING_STEM, puntos)] + self._imagenes(p, n)
                         + [Sangrado(dentro, self.sangria)])

        if isinstance(p, PreguntaCloze):
            return self._cloze(n, p, puntos, ayudas)

        if isinstance(p, PreguntaEssay):
            return Grupo([self._enunciado(n, p.stem, puntos)] + self._imagenes(p, n)
                         + [Sangrado([Espacio(4), Renglones(self.renglones)], self.sangria)])

        # respuesta corta y numérica: una línea
        return Grupo([self._enunciado(n, p.stem, puntos)] + self._imagenes(p, n)
                     + [Sangrado([Espacio(4), self._p("Respuesta: " + "_" * 38)], self.sangria)])

    def _pregunta_folleto(self, n: int, p: Pregunta, puntos: float, ayudas: bool) -> Grupo:
        """La pregunta del folleto: solo para leer. No lleva casillas ni rayas (se responde en la hoja de respuestas)."""
        if isinstance(p, PreguntaMultichoice):
            varias = len(p.resolver_correctas()[0]) > 1
            dentro: list = []
            if ayudas:
                dentro.append(self._p("Selecciona todas las que correspondan." if varias else "Selecciona una.", "ayuda"))
            dentro += [Parrafo(self.est["opcion_folleto"], self.txt.marcado(texto), vineta=f"{self.txt.marcado(letra)})")
                       for letra, texto, _ok in self._opciones_impresas(p)]
            return Grupo([self._enunciado(n, p.stem, puntos)] + self._imagenes(p, n) + [Sangrado(dentro, self.sangria)])
        if isinstance(p, PreguntaMatching):
            return Grupo([self._enunciado(n, p.stem or DEFAULT_MATCHING_STEM, puntos)] + self._imagenes(p, n)
                         + [Sangrado([self._tabla_pareo(p, True)], self.sangria)])
        if isinstance(p, PreguntaCloze):
            return self._cloze(n, p, puntos, ayudas)
        # verdadero/falso, respuesta corta, numérica y desarrollo: solo el enunciado
        return Grupo([self._enunciado(n, p.stem, puntos)] + self._imagenes(p, n))

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

    def _cloze(self, n: int, p: PreguntaCloze, puntos: float, ayudas: bool = True) -> Grupo:
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
        enunciado = Parrafo(self.est["enunciado"], "".join(trozos) + self._pts_de(puntos), vineta=f"{n}.")
        filas = []
        for k_hueco, h in enumerate(huecos, 1):
            if len(h.opciones) < 2:
                continue
            correctas, _ = h.resolver()
            opciones = [(self._letra_opcion(k), self.txt.marcado(h.opciones[i])) for k, i in enumerate(self._orden_hueco(p, h))]
            if max(len(self.txt.plano(h.opciones[i])) for i in range(len(h.opciones))) <= 16:
                celda = [self._p("     ".join(f"<b>{le})</b>\u00a0{tx}" for le, tx in opciones), "celda")]
            else:
                celda = [Parrafo(self.est["opcion_lista"], tx, vineta=f"{le})") for le, tx in opciones]
            if len(correctas) > 1:
                celda.append(self._p("Elige todas las que correspondan: escribe todas las letras.", "ayuda"))
            filas.append((self._p(f"<b>{k_hueco}.</b>", "celda"), celda))
        cuerpo: list = []
        if filas:
            dentro: list = []
            if ayudas:
                dentro.append(self._p("Escribe en cada espacio la letra de la opción que lo completa." if all(len(h.opciones) >= 2 for h in huecos)
                                      else "En los espacios con opciones escribe la letra elegida; en los demás, la respuesta.", "ayuda"))
            dentro.append(TablaHuecos(filas))
            cuerpo = [Sangrado(dentro, self.sangria)]
        return Grupo([enunciado] + self._imagenes(p, n) + cuerpo)

    # ---- una entrada de la clave ----
    def entrada_clave(self, n: int, p: Pregunta, puntos: float) -> Grupo:
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
        cabecera = self.txt.marcado(self._resumen(p)) + f" <font size='{self.Q * 0.8:.1f}' color='{GRIS}'>({_pts(puntos)})</font>"
        return Grupo([Parrafo(self.est["clave"], cabecera, vineta=f"{n}."),
                      Sangrado([self._p(x, "pequeno") for x in lineas], self.sangria)])

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

    def _ancho_texto(self, texto: str, grupo: str, tam: float, negrita: bool = True) -> float:
        nombre = (self.fe if grupo == "e" else self.fp) + ("-B" if negrita else "")
        return pdfmetrics.stringWidth(texto, nombre, tam)

    def _huecos(self, num: int, items) -> Huecos:
        """Reparte «6.  1. ______  2. ______» en líneas: lo que no cabe en una pasa a la siguiente. `items` =
        [(etiqueta, valor o None, largo de la raya o None = hasta el final de la línea)]."""
        aw, tam = self.ancho, self.Q
        x0 = self._ancho_texto(f"{num}.", "p", tam) + 10
        lineas, fila, x = [], [], x0
        for etiqueta, valor, largo in items:
            w_et = (self._ancho_texto(etiqueta, "p", tam) + 4) if etiqueta else 0
            real = largo if largo is not None else max(60.0, aw - x - w_et)
            if fila and x + w_et + real > aw:
                lineas.append(fila)
                fila, x = [], x0
                real = largo if largo is not None else max(60.0, aw - x - w_et)
            tam_v = tam
            if valor:
                while tam_v > 6 and self._ancho_texto(valor, "p", tam_v) > real - 4:
                    tam_v -= 0.5
            fila.append((x, etiqueta, valor, w_et, real, tam_v))
            x += w_et + real + 14
        lineas.append(fila)
        return Huecos(num, lineas, tam)

    def _fila_hoja(self, n: int, p: Pregunta, llena: bool) -> list:
        """Lo que escribe el estudiante para una pregunta que no es de burbujas (con `llena`, la respuesta)."""
        if isinstance(p, PreguntaMatching):
            a_claves, _b, de_a = self._pareo(p)
            items = [(f"{self.txt.plano(k)}.", (self.txt.plano(de_a.get(k) or "") if llena else None), 1.5 * cm) for k in a_claves]
            return [self._huecos(n, items)]
        if isinstance(p, PreguntaCloze):
            items = []
            for k, h in enumerate(p.huecos(), 1):
                con_opciones = len(h.opciones) >= 2
                items.append((f"({k})", self.txt.plano(self._valor_cloze(p, h)) if llena else None, 1.7 * cm if con_opciones else 5.5 * cm))
            return [self._huecos(n, items)]
        if isinstance(p, PreguntaNumerical):
            v = (p.valor_numerico() or p.respuesta_texto.strip()) if llena and not p.sin_respuesta else None
            return [self._huecos(n, [("", self.txt.plano(v) if v else None, 5 * cm)])]
        if isinstance(p, PreguntaShortanswer):
            v = p.respuesta_texto.strip() if llena and not p.sin_respuesta else None
            return [self._huecos(n, [("", self.txt.plano(v) if v else None, None)])]
        if isinstance(p, PreguntaEssay):
            if llena:
                texto = f"<b>{n}.</b> <i>Respuesta abierta: se califica a mano.</i>"
                if (p.feedback or "").strip():
                    texto += f" <i>Orientación:</i> {self.txt.marcado(p.feedback.strip())}"
                return [self._p(texto, "pequeno"), Espacio(4)]
            return [self._p(f"<b>{n}.</b>", "pequeno"), Renglones(self.renglones), Espacio(4)]
        return [self._p(f"<b>{n}.</b>", "pequeno")]

    def _burbujas(self, n: int, p: Pregunta, llena: bool) -> Burbujas:
        if isinstance(p, PreguntaTruefalse):
            v = p.es_verdadero()
            return Burbujas(n, ["V", "F"], True, tuple([("V" if v else "F")] if llena and v is not None else []))
        opciones = self._opciones_impresas(p)
        correctas = [L for L, _tx, ok in opciones if ok]
        return Burbujas(n, [L for L, _tx, _ok in opciones], len(correctas) <= 1, tuple(correctas if llena else []))

    def hoja_respuestas(self, llena: bool) -> list:
        """La hoja de respuestas por partes: burbujas para opción múltiple y verdadero/falso, rayas para lo demás.
        Con `llena` es la clave (las mismas burbujas rellenas y las respuestas escritas)."""
        salida: list = []
        n = 0
        for i, (tipo, grupo) in enumerate(self.partes()):
            titulo = [self._titulo_parte(i, tipo, grupo, True, hoja=True)] if tipo is not None else []
            corrida: List[Burbujas] = []

            def emitir(piezas: list):
                nonlocal titulo
                salida.append(Grupo(titulo + piezas))
                titulo = []

            def vaciar():
                if not corrida:
                    return
                maximo = max(len(b.letras) for b in corrida)
                cols = max(1, min(4, int(self.ancho // (28 + maximo * PASO_BURBUJAS + 8))))
                filas = -(-len(corrida) // cols)
                celdas = [[corrida[c * filas + r] if c * filas + r < len(corrida) else None for c in range(cols)] for r in range(filas)]
                emitir([Espacio(2), RejillaBurbujas(celdas, cols), Espacio(4)])
                corrida.clear()

            for p, _pts_ in grupo:
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

    def _titulo_parte(self, i: int, tipo: Optional[str], grupo, con_indicacion: bool, hoja: bool = False) -> Parrafo:
        valor = _pts(sum(pts for _, pts in grupo)).upper()
        nombre = NOMBRE_PARTE.get(tipo or "", "PREGUNTAS")
        ind = (self._indicacion_hoja(tipo, grupo) if hoja else self._indicacion(tipo, grupo)) if con_indicacion else ""
        texto = f"{ROMANOS[min(i, len(ROMANOS) - 1)]} PARTE: {nombre}" + (f": {ind}" if ind else "") + f" VALOR: {valor}"
        return self._p(self.txt.marcado(texto), "parte")

    # ---- portada ----
    def _ancho_negrita(self, texto: str, tam: float) -> float:
        return pdfmetrics.stringWidth(texto, self.fe + "-B", tam)

    def _una_linea(self, texto: str, ancho: float, tam: float, alinear: int = 0) -> Parrafo:
        """Un párrafo en negrita de tamaño `tam` que cabe SIEMPRE en una línea de `ancho`: lo que sobre se
        corta con «…» (el texto nunca pasa a otra línea)."""
        plano = self.txt.plano(texto).replace("\n", " ")
        ancho -= 1.5
        if self._ancho_negrita(plano, tam) > ancho:
            while plano and self._ancho_negrita(plano + "…", tam) > ancho:
                plano = plano[:-1]
            plano = plano.rstrip() + "…"
        estilo = replace(self.est["rotulo"], tam=tam, leading=tam + 3, alinear=alinear)
        return Parrafo(estilo, plano.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    def _logo(self, b64: str, lado: str) -> Optional[Imagen]:
        if not (b64 or "").strip():
            return None
        f = imagen_desde_b64(b64, "image/png", 2.5 * cm, 2.5 * cm, ampliar=True)
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
            if izq is not None:
                izq.alinear = "LEFT"
            if der is not None:
                der.alinear = "RIGHT"
            items.append(LogosCabecera(izq, centro, der, 2.7 * cm))
        items.append(Espacio(8))

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
            filas = [[etiqueta("NOMBRE:"), nombre, etiqueta("CÉDULA:"), ""],
                     [etiqueta("GRUPO:"), valor(_campo(d.grupo, LIMITE_CAMPO)), etiqueta("FECHA:"), valor(_campo(d.fecha, LIMITE_CAMPO))]]
            items += [CuadroEstudiante(filas, [e1, (w - e1 - e2) * 0.56, e2, (w - e1 - e2) * 0.44], max(0.95 * cm, self.H * 2.1)), Espacio(12)]
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
            items += [FilaDocente(self._una_linea(izquierda, ancho_izq, tam) if izquierda else None,
                                  self._una_linea(nota, ancho_nota, tam, alinear=2) if nota else None,
                                  ancho_izq + hueco if nota else ancho_izq, ancho_nota, hueco), Espacio(10)]

        if folleto:
            items += [self._p("NO ESCRIBA EN ESTE FOLLETO: SUS RESPUESTAS VAN EN LA HOJA DE RESPUESTAS.", "aviso_folleto"), Espacio(8)]
        instr = _campo_largo(d.instrucciones, LIMITE_INSTRUCCIONES)
        if instr and not clave and not hoja:
            items.append(self._p("INDICACIONES GENERALES:", "rotulo"))
            items.append(Espacio(4))
            for linea in instr.split("\n"):
                linea = re.sub(r"^\s*[-•*·]\s*", "", linea).strip()
                if linea:
                    items.append(Parrafo(self.est["indicacion"], self.txt.marcado(linea), vineta="•"))
            items.append(Espacio(6))
        return items

    # ---- el documento ----
    def _encabezado_izq(self) -> str:
        izquierda = " · ".join(x for x in (_campo(self.datos.materia, 60), _campo(self.datos.actividad, 60)) if x) or self.titulo
        if self.version:
            izquierda += f" · VERSIÓN {self.version}"
        return self.txt.plano(izquierda)

    def secciones(self) -> List[Seccion]:
        d = self.datos
        total = sum(self.puntos)
        izq = self._encabezado_izq()
        docente = self.txt.plano(_campo(d.docente, 60))
        examen = Seccion("examen", izq, docente, True)
        hoja = Seccion("hoja", izq, "HOJA DE RESPUESTAS", True)
        clave = Seccion("clave", izq, "CLAVE DE RESPUESTAS · uso del docente", False)
        c = d.contenido

        def partes_del_examen(folleto: bool) -> list:
            salida = []
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
                    salida.append(Grupo(titulo + q.hijos) if titulo else q)
                    titulo = []
            self.folleto = False
            return salida

        def clave_compacta() -> list:
            salida = list(self.cabecera(total, clave=True))
            salida += [self._p("CLAVE DE RESPUESTAS", "titulo"),
                       self._p(self.txt.marcado("Documento para el docente: no se entrega a los estudiantes. "
                                                "Las opciones se identifican por su letra y su texto porque Moodle las mezcla."), "datos")]
            n = 0
            for i, (tipo, grupo) in enumerate(self.partes()):
                titulo = [self._titulo_parte(i, tipo, grupo, False)] if tipo is not None else []
                for p, pts in grupo:
                    n += 1
                    e = self.entrada_clave(n, p, pts)
                    salida.append(Grupo(titulo + e.hijos) if titulo else e)
                    titulo = []
            return salida

        if c in ("examen_y_clave", "solo_examen"):
            examen.bloques = self.cabecera(total) + partes_del_examen(False)
        if c in ("examen_y_clave", "solo_clave"):
            clave.bloques = clave_compacta()
        if c == "folleto_hoja_clave":
            examen.bloques = self.cabecera(total, modo="folleto") + partes_del_examen(True)
            hoja.bloques = (self.cabecera(total, modo="hoja")
                            + [self._p("HOJA DE RESPUESTAS", "titulo"),
                               self._p("Escriba aquí sus respuestas; no escriba en el folleto de preguntas.", "datos")]
                            + self.hoja_respuestas(False))
            clave.bloques = (self.cabecera(total, clave=True, modo="hoja")
                             + [self._p("CLAVE DE RESPUESTAS", "titulo"),
                                self._p(self.txt.marcado("Es la hoja de respuestas llena. Documento para el docente: no se entrega a los estudiantes."), "datos")]
                             + self.hoja_respuestas(True))
        orden = {"examen_y_clave": [examen, clave], "solo_examen": [examen], "solo_clave": [clave],
                 "folleto_hoja_clave": [examen, hoja, clave]}[c]
        return orden

    def avisos(self) -> List[str]:
        avisos: List[str] = []
        if self.txt.formulas_crudas:
            n = self.txt.formulas_crudas
            avisos.append(f"{n} fórmula{'s' if n != 1 else ''} no se pudo{'ieron' if n != 1 else ''} "
                          "escribir como texto y quedó con su notación LaTeX entre \\( y \\).")
        if self.txt.sin_glifo:
            n = self.txt.sin_glifo
            avisos.append(f"{n} carácter{'es' if n != 1 else ''} que la fuente del PDF no tiene se escribió como «?» "
                          "(por ejemplo, emojis).")
        if self.logos_fallidos:
            avisos.append("No se pudo usar el logo " + " ni el ".join(sorted(set(self.logos_fallidos))) + ": se omitió.")
        if self.imagenes_fallidas:
            avisos.append("No se pudo incluir la imagen de la pregunta " + ", ".join(str(n) for n in sorted(set(self.imagenes_fallidas))) + ".")
        return avisos


def construir_plan(questions: List[Dict[str, Any]], answer_key: Dict[int, Dict[str, Any]],
                   total_points: float, datos: DatosExamen) -> Plan:
    """El plan del examen (y su clave). `questions` y `answer_key` son los mismos que recibe
    xml_builder.build_xml: aquí no se valida (lo hace la ruta, igual que para el XML)."""
    if datos.fuente_titulos not in FUENTES or datos.fuente_preguntas not in FUENTES:
        raise ValueError("tipo de letra no válido")
    registrar_fuentes(datos.fuente_titulos, datos.fuente_preguntas)
    if datos.contenido not in CONTENIDOS:
        raise ValueError("contenido no válido")
    preguntas = [p for p in preguntas_desde_dicts(questions, answer_key) if not p.tiene_error]
    if not preguntas:
        raise ValueError("No hay preguntas que exportar.")
    notas = compute_grades(questions, total_points)
    puntos = [p.puntos_validos if p.puntos_validos is not None else notas.get(p.tipo, 1.0) for p in preguntas]
    if datos.puntos_enteros:
        revisar_puntos_enteros(preguntas, puntos)

    a = _Armador(preguntas, puntos, datos)
    secciones = a.secciones()
    meta = {"titulo": a.txt.plano(a.titulo), "autor": a.txt.plano(_campo(datos.docente, 80)),
            "materia": a.txt.plano(_campo(datos.materia, 80))}
    return Plan(datos=datos, geo=a.geo, estilos=a.est, fuente_e=a.fe, fuente_p=a.fp,
                clave_fuente_e=datos.fuente_titulos, clave_fuente_p=datos.fuente_preguntas,
                tam_titulos=a.H, tam_preguntas=a.Q, titulo=a.titulo, meta=meta, secciones=secciones,
                preguntas=len(preguntas), avisos=a.avisos())
