"""
origen_pdf.py — Dónde está cada pregunta en el PDF original.

El editor puede mostrar, al lado de cada pregunta, el recorte del original de
donde salió. Para eso hace falta saber la página y el rectángulo. La IA dice
una página (a veces se equivoca) pero no el rectángulo; aquí se calcula en
código, leyendo la capa de texto del PDF con pdfplumber, sin IA.

    ubicar_preguntas(pdf_bytes, preguntas) ->
        {num: {"page": int (≥ 1), "recuadro": [fx0, fy0, fx1, fy1]}}

`recuadro` son FRACCIONES (0–1) del ancho y del alto de la página, con el
origen arriba a la izquierda. Una pregunta que no se pudo ubicar con certeza
NO aparece en el resultado: este módulo nunca adivina. Ante la duda se omite.

Cómo se ubica
  1. Se leen las palabras de cada página y se agrupan en líneas (con su
     posición). Se abre el PDF una sola vez y cada página se cierra al terminar.
  2. Ancla: la línea donde EMPIEZA el enunciado de la pregunta. Se compara el
     comienzo del enunciado (sin número, tildes ni signos) con cada línea; vale
     la línea igual al enunciado, la que lo trae entero más las opciones en el
     mismo renglón, o la que es el comienzo de un enunciado de varias líneas
     (y, solo si no hay otra, una casi idéntica: la IA corrige ortografía). Si
     el enunciado aparece en más de una línea con la misma fuerza, o dos
     preguntas caen en la misma línea, ninguna se ubica.
  3. Recuadro: de la primera línea del enunciado a la última línea de sus
     opciones, que es la línea anterior al ancla de la pregunta siguiente. Si la
     siguiente empieza en otra página (o no hay siguiente), el bloque sigue
     mientras el texto sea continuo (o encaje con el contenido de la pregunta)
     hasta el fin de la página: se toma la página donde empieza.

Casos en que NO ubica (la pregunta se omite del resultado)
  · PDF escaneado o sin texto; páginas giradas; documentos Word o TXT (solo se
    llama con PDF).
  · Páginas con varias columnas o tablas anchas: las líneas se mezclan entre
    columnas y el rectángulo sería falso.
  · Enunciado ausente, de menos de 8 caracteres o que la IA reescribió (código
    transcrito de una imagen, fórmulas distintas…): no hay ancla.
  · Ancla ambigua: texto repetido en el documento.
  · La pregunta siguiente de la lista no se ubicó y esta no está numerada en el
    documento (sin numeración no se sabe dónde termina), o quedó en un orden
    distinto del documento.
"""

import io
import logging
import re
import statistics
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pdfplumber
from pdfplumber.utils import cluster_objects

from extractor import MAX_PAGINAS

logger = logging.getLogger(__name__)

# Un enunciado más corto es demasiado genérico para servir de ancla.
_MIN_ANCLA = 8
# Menos palabras por página que esto, de media: no hay texto de verdad (escaneado).
_MIN_PALABRAS_POR_PAGINA = 15
# Página de varias columnas: hay una franja vertical libre (≥ 6 pt) en el medio
# de la página que casi ninguna línea cruza (≤ 5 %) y que separa texto a sus dos
# lados en al menos el 25 % de las líneas (cada lado).
_ANCHO_CANAL = 6
_FRACCION_CRUCE = 0.05
_FRACCION_COLUMNAR = 0.25
_MIN_LINEAS_COLUMNAR = 6
# Cabecera y pie de página: franja de los bordes con líneas cortas.
_FRANJA_BORDE = 0.06
_PALABRAS_BORDE = 6
# Margen alrededor del texto, en puntos.
_MARGEN_X = 3.0
_MARGEN_Y = 2.0

_NUMERADA = re.compile(r"^\s*(?:pregunta\s*)?(\d{1,3})\s*[.):-]\s*\S", re.IGNORECASE)
# Encabezado que abre otra cosa: la hoja de respuestas o una nueva sección.
_ENCABEZADO = re.compile(
    r"^(?:(?:hoja de )?(?:respuestas?|clave|claves|solucionario|answers?|soluciones)"
    r"|(?:seccion|parte|section|part|bloque|capitulo)(?:\s+(?:[ivx]+|\d+|[a-z]))?)\b", re.IGNORECASE)
_ETIQUETA = re.compile(r"^\s*(?:[A-Za-z]|\d{1,3})\s*[.):\-]\s+")


# ── Normalización ──────────────────────────────────────────────────────────

def _norm(texto: str) -> str:
    """Forma comparable: sin etiquetas de marca, fórmulas LaTeX, tildes, signos
    ni el número de pregunta del comienzo."""
    t = re.sub(r"⟦/?[^⟧]*⟧", "", texto or "")
    t = re.sub(r"\\\(.*?\\\)", " ", t)
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"^\s*(?:pregunta\s*)?\d{1,3}\s*[.):-]?\s*", "", t)
    # «Completa: La capital es ___»: la IA suele quitar la instrucción del
    # enunciado de un «Completar»; se quita de los dos lados para poder cotejar.
    t = re.sub(r"^\s*(?:completa|completar|complete|rellena|rellenar)\b\s*[:.\-]?\s*", "", t)
    t = " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())
    # «… es 18. ( ) Verdadero ( ) Falso»: las opciones de un V/F van en el
    # mismo renglón del enunciado y no son parte de él.
    return re.sub(r"\s+(?:verdadero|cierto|v)\s+(?:falso|f)$", "", t)


def _norm_sin_numero(texto: str) -> str:
    """Como _norm pero sin quitar un número del comienzo (para cotejar el
    contenido de una línea con el de la pregunta)."""
    t = re.sub(r"⟦/?[^⟧]*⟧", "", texto or "")
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


# ── Lectura del PDF ────────────────────────────────────────────────────────

@dataclass
class _Linea:
    pag: int            # índice de página, desde 0
    top: float
    bottom: float
    x0: float
    x1: float
    texto: str
    norm: str
    palabras: int
    tramos: Tuple[Tuple[float, float], ...] = ()   # (x0, x1) de cada palabra


@dataclass
class _Pagina:
    x0: float
    top: float
    ancho: float
    alto: float
    usable: bool = True        # False: girada o de varias columnas
    paso: float = 0.0          # distancia típica entre líneas (top a top)


def _es_columnar(lineas: List[_Linea], pagina: _Pagina) -> bool:
    """¿La página tiene varias columnas (o una tabla ancha)? Entonces las
    líneas que agrupa pdfplumber mezclan columnas y un rectángulo sería falso."""
    n = len(lineas)
    if n < _MIN_LINEAS_COLUMNAR:
        return False
    ancho = int(pagina.ancho)
    cruces = [0] * (ancho + 1)
    for l in lineas:
        bins = set()
        for a, b in l.tramos:
            bins.update(range(max(0, int(a - pagina.x0)), min(ancho, int(b - pagina.x0)) + 1))
        for k in bins:
            cruces[k] += 1
    inicio = int(ancho * 0.3)
    fin = int(ancho * 0.7)
    k = inicio
    while k <= fin:
        if cruces[k] > _FRACCION_CRUCE * n:
            k += 1
            continue
        j = k
        while j <= fin and cruces[j] <= _FRACCION_CRUCE * n:
            j += 1
        if j - k >= _ANCHO_CANAL:
            xs, xe = pagina.x0 + k, pagina.x0 + j
            izquierda = sum(1 for l in lineas if l.x0 < xs)
            derecha = sum(1 for l in lineas if l.x1 > xe)
            if izquierda >= _FRACCION_COLUMNAR * n and derecha >= _FRACCION_COLUMNAR * n:
                return True
        k = j + 1
    return False


def _leer(pdf_bytes: bytes) -> Tuple[List[_Linea], List[_Pagina], int]:
    """(líneas en orden de lectura, datos de página, total de palabras)."""
    lineas: List[_Linea] = []
    paginas: List[_Pagina] = []
    total = 0
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for n, page in enumerate(pdf.pages[:MAX_PAGINAS]):
            try:
                bx0, btop, bx1, bbottom = page.bbox
                info = _Pagina(bx0, btop, bx1 - bx0, bbottom - btop)
                paginas.append(info)
                if (getattr(page, "rotation", 0) or 0) % 360 or info.ancho <= 0 or info.alto <= 0:
                    info.usable = False
                    continue
                palabras = page.extract_words()
                total += len(palabras)
                propias: List[_Linea] = []
                for grupo in cluster_objects(palabras, "top", tolerance=3):
                    ws = sorted(grupo, key=lambda w: w["x0"])
                    texto = " ".join(w["text"] for w in ws)
                    propias.append(_Linea(
                        n, min(w["top"] for w in ws), max(w["bottom"] for w in ws),
                        min(w["x0"] for w in ws), max(w["x1"] for w in ws),
                        texto, _norm(texto), len(ws), tuple((w["x0"], w["x1"]) for w in ws)))
                propias.sort(key=lambda l: (l.top, l.x0))
                if _es_columnar(propias, info):
                    info.usable = False
                tops = [b.top - a.top for a, b in zip(propias, propias[1:]) if b.top - a.top > 1]
                info.paso = statistics.median(tops) if tops else 0.0
                lineas.extend(propias)
            finally:
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass
    return lineas, paginas, total


# ── Ancla de cada pregunta ─────────────────────────────────────────────────

def _texto_ancla(q: Dict[str, Any]) -> str:
    """Comienzo comparable del enunciado. En «Completar» (cloze) el enunciado
    de la IA lleva los huecos como [A: x / y]: solo vale lo que va antes del
    primer hueco."""
    d = q.get("data") if isinstance(q.get("data"), dict) else {}
    if q.get("type") == "cloze":
        texto = str(d.get("text") or d.get("stem") or "").split("[", 1)[0]
    else:
        texto = str(d.get("stem") or d.get("text") or "")
    return _norm(texto)


def _fuerza(linea: str, ancla: str) -> int:
    """Cuánto coincide una línea con el comienzo del enunciado: 3 igual, 2 la
    línea trae el enunciado entero y más (opciones en el renglón), 1 la línea
    es el comienzo de un enunciado de varias líneas, 0 no coincide."""
    if len(linea) < _MIN_ANCLA or len(ancla) < _MIN_ANCLA:
        return 0
    if linea == ancla:
        return 3
    if linea.startswith(ancla + " "):
        return 2
    if ancla.startswith(linea + " "):
        return 1
    return 0


def _parecida(linea: str, ancla: str) -> bool:
    """La IA corrige la ortografía del documento («coreponda» → «corresponda»):
    línea larga casi idéntica al comienzo del enunciado."""
    if len(linea) < 20 or len(ancla) < 20:
        return False
    return SequenceMatcher(None, linea, ancla[:len(linea) + 3], autojunk=False).ratio() >= 0.92


def _anclas(preguntas: Sequence[Dict[str, Any]], lineas: List[_Linea]) -> List[Optional[int]]:
    """Índice de la línea ancla de cada pregunta, o None si no hay una única."""
    por_inicio: Dict[str, List[int]] = {}
    for k, l in enumerate(lineas):
        if len(l.norm) >= _MIN_ANCLA:
            por_inicio.setdefault(l.norm[:8], []).append(k)
    encontradas: List[Optional[int]] = []
    for q in preguntas:
        ancla = _texto_ancla(q)
        if len(ancla) < _MIN_ANCLA:
            encontradas.append(None)
            continue
        candidatas = por_inicio.get(ancla[:8], [])
        mejor = 0
        elegidas: List[int] = []
        for k in candidatas:
            f = _fuerza(lineas[k].norm, ancla)
            if f > mejor:
                mejor, elegidas = f, [k]
            elif f == mejor and f:
                elegidas.append(k)
        if not mejor:
            elegidas = [k for k in range(len(lineas)) if _parecida(lineas[k].norm, ancla)] if len(ancla) >= 20 else []
        encontradas.append(elegidas[0] if len(elegidas) == 1 else None)
    # Dos preguntas en la misma línea: ninguna de las dos es fiable.
    usadas: Dict[int, int] = {}
    for k in encontradas:
        if k is not None:
            usadas[k] = usadas.get(k, 0) + 1
    return [k if k is not None and usadas[k] == 1 else None for k in encontradas]


# ── Fin del bloque ─────────────────────────────────────────────────────────

def _es_borde(l: _Linea, pagina: _Pagina) -> bool:
    """Cabecera o pie de página: línea corta en la franja de arriba o de abajo."""
    if l.palabras > _PALABRAS_BORDE:
        return False
    rel = (l.top - pagina.top) / pagina.alto
    return rel < _FRANJA_BORDE or rel > 1 - _FRANJA_BORDE


def _palabras_pregunta(q: Dict[str, Any]) -> set:
    d = q.get("data") if isinstance(q.get("data"), dict) else {}
    partes: List[str] = [str(d.get("stem") or ""), str(d.get("text") or "")]
    for campo in ("options", "col_a", "col_b"):
        v = d.get(campo)
        if isinstance(v, dict):
            partes.extend(str(x) for x in v.values())
    return set(_norm_sin_numero(" ".join(partes)).split())


def _pertenece_por_contenido(l: _Linea, vocabulario: set) -> bool:
    """La mayoría de las palabras de la línea (sin su rótulo «a)») son de la pregunta."""
    palabras = _norm_sin_numero(_ETIQUETA.sub("", l.texto)).split()
    if not palabras:
        return False
    return sum(1 for p in palabras if p in vocabulario) / len(palabras) >= 0.7


def _fin_continuo(lineas: List[_Linea], paginas: List[_Pagina], ancla: int, q: Dict[str, Any]) -> Tuple[int, str]:
    """(índice de la última línea del bloque, por qué terminó) cuando no hay
    una pregunta siguiente en la misma página: el bloque sigue mientras el
    texto sea continuo o encaje con el contenido de la pregunta. Motivos:
    «pagina» (se acabó la página), «borde» (cabecera o pie), «encabezado»
    (de respuestas o de otra sección), «numerada» (empieza otra cosa numerada),
    «hueco» (un espacio en blanco mayor que el normal)."""
    pag = lineas[ancla].pag
    pagina = paginas[pag]
    vocabulario = _palabras_pregunta(q)
    fin = ancla
    j = ancla + 1
    while j < len(lineas) and lineas[j].pag == pag:
        l = lineas[j]
        if _es_borde(l, pagina):
            return fin, "borde"
        if _ENCABEZADO.match(_norm_sin_numero(l.texto)):
            return fin, "encabezado"
        pertenece = _pertenece_por_contenido(l, vocabulario)
        continuo = pagina.paso > 0 and (l.top - lineas[j - 1].top) <= 1.8 * pagina.paso
        if _NUMERADA.match(l.texto) and not pertenece:
            return fin, "numerada"
        if not (pertenece or continuo):
            return fin, "hueco"
        fin = j
        j += 1
    return fin, "pagina"


def _numero(l: _Linea) -> Optional[int]:
    m = _NUMERADA.match(l.texto)
    return int(m.group(1)) if m else None


def _bloques(preguntas: Sequence[Dict[str, Any]], lineas: List[_Linea],
             paginas: List[_Pagina], anclas: List[Optional[int]]) -> Dict[int, Tuple[int, int]]:
    """{posición en `preguntas`: (primera línea, última línea)} de las que se
    pueden delimitar con certeza."""
    out: Dict[int, Tuple[int, int]] = {}
    for i, a in enumerate(anclas):
        if a is None or not paginas[lineas[a].pag].usable:
            continue
        pag = lineas[a].pag
        siguiente = anclas[i + 1] if i + 1 < len(anclas) else None
        sin_ubicar = i + 1 < len(anclas) and siguiente is None
        if sin_ubicar and not _NUMERADA.match(lineas[a].texto):
            continue  # la que sigue no se ubicó y no hay numeración que marque su comienzo
        if siguiente is not None and siguiente <= a:
            continue  # el documento tiene otro orden que la lista
        if siguiente is not None and lineas[siguiente].pag == pag:
            fin = siguiente - 1
            # Un encabezado de sección o de respuestas entre ambas cierra el bloque.
            for j in range(a + 1, siguiente):
                if _ENCABEZADO.match(_norm_sin_numero(lineas[j].texto)):
                    fin = j - 1
                    break
            # Una pregunta del documento que la IA no devolvió queda entre
            # ambas: si hay una línea que empieza con un número intermedio, el
            # bloque termina antes de ella.
            n0, n1 = _numero(lineas[a]), _numero(lineas[siguiente])
            if n0 is not None and n1 is not None and n1 - n0 > 1:
                for j in range(a + 1, fin + 1):
                    k = _numero(lineas[j])
                    if k is not None and n0 < k < n1:
                        fin = j - 1
                        break
        else:
            fin, motivo = _fin_continuo(lineas, paginas, a, preguntas[i])
            if sin_ubicar and motivo == "hueco":
                continue  # sin numeración que la delimite, el bloque podría haber absorbido a la siguiente
        if fin >= a:
            out[i] = (a, fin)
    return out


# ── API pública ────────────────────────────────────────────────────────────

def ubicar_preguntas(pdf_bytes: bytes, preguntas: Sequence[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """Página y recuadro de cada pregunta que se pueda ubicar con certeza.
    `preguntas`: [{"num", "type", "data": {...}}] en el orden del examen.
    Nunca lanza: ante cualquier problema devuelve lo que haya (o {})."""
    if not pdf_bytes or not preguntas:
        return {}
    try:
        lineas, paginas, total_palabras = _leer(pdf_bytes)
        if not lineas or total_palabras < _MIN_PALABRAS_POR_PAGINA * max(1, len(paginas)):
            return {}  # escaneado, o con un hilo de texto: nada que ubicar
        anclas = _anclas(preguntas, lineas)
        bloques = _bloques(preguntas, lineas, paginas, anclas)
    except Exception as exc:  # noqa: BLE001 — sin ubicación, la conversión sigue igual
        logger.warning("No se pudieron ubicar las preguntas en el PDF: %s", exc)
        return {}

    resultado: Dict[int, Dict[str, Any]] = {}
    for i, (a, fin) in bloques.items():
        num = preguntas[i].get("num")
        if not isinstance(num, int) or isinstance(num, bool) or num in resultado:
            continue
        bloque = lineas[a:fin + 1]
        pagina = paginas[bloque[0].pag]
        x0 = min(l.x0 for l in bloque) - _MARGEN_X
        x1 = max(l.x1 for l in bloque) + _MARGEN_X
        y0 = min(l.top for l in bloque) - _MARGEN_Y
        y1 = max(l.bottom for l in bloque) + _MARGEN_Y
        # Nunca pasar del comienzo de la pregunta siguiente (una marca de agua
        # o una letra suelta con la parte baja por debajo de su primer renglón).
        vecina = anclas[i + 1] if i + 1 < len(anclas) else None
        if vecina is not None and lineas[vecina].pag == bloque[0].pag and lineas[vecina].top > y0:
            y1 = min(y1, lineas[vecina].top - 0.5)

        def f(v: float, origen: float, largo: float) -> float:
            return round(min(1.0, max(0.0, (v - origen) / largo)), 4)

        caja = [f(x0, pagina.x0, pagina.ancho), f(y0, pagina.top, pagina.alto),
                f(x1, pagina.x0, pagina.ancho), f(y1, pagina.top, pagina.alto)]
        if caja[2] <= caja[0] or caja[3] <= caja[1]:
            continue
        resultado[num] = {"page": bloque[0].pag + 1, "recuadro": caja}
    return resultado
