"""
mark_resolver.py — Resuelve en CÓDIGO las respuestas marcadas en un PDF
digital (texto en color, resaltado, subrayado o negrita, y cuadros de
marcas), sin depender del modelo.

Por qué existe (medido con dev/eval.py): aun viendo la marca en el texto
que recibe (⟦rojo⟧Java⟦/rojo⟧, o la "X" en su columna de la tabla), el
modelo a veces responde con lo que él cree correcto — marca "JavaScript"
en vez de la "C" que el docente puso en rojo, o asigna una fila de la
tabla a la columna que "tiene sentido" y no a la marcada. Pero en un PDF
digital la marca ya es un dato exacto: pdfplumber sabe qué palabras son
rojas y en qué celda está cada X. Así que el modelo se usa para lo que
hace bien (estructurar: qué es enunciado, qué es opción) y la respuesta se
decide aquí, leyendo la marca.

Trabaja sobre la forma interna que consumen el editor y el validador
({questions, answer_key}), así que sirve igual para el modo texto y el
modo JSON. Si algo no se puede resolver con certeza (no se ubica la
pregunta, falta alguna opción, la tabla no calza), NO toca nada y queda lo
que dijo el modelo.
"""

import re
import unicodedata
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

# Nombre de la "marca" cuando cada pregunta usa la suya (ver resolve_answer_marks).
MIXED_MARKS = "mixta"

_TAG = re.compile(r"⟦/?([a-záéíóú]+)⟧")
_OPEN = re.compile(r"⟦([a-záéíóú]+)⟧")
_LABEL = re.compile(r"^\s*(?:[A-Za-z]|\d{1,2})\s*[.)\-]\s+")


def _norm(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    # Se conservan los símbolos que pueden ser, por sí solos, una opción
    # completa en un examen de programación ("%", "**", "==", "!=").
    return " ".join(re.sub(r"[^\w'\"(){}\[\]=<>+\-*/.,:%!&|^~#@$]", " ", s).split())


class _Line:
    __slots__ = ("raw", "plain", "norm", "colors")

    def __init__(self, raw: str):
        self.raw = raw
        self.plain = _TAG.sub("", raw)
        self.norm = _norm(_LABEL.sub("", self.plain))
        # Color que cubre la MAYOR parte de la línea (o None si es texto normal).
        colored = Counter()
        pos, current = 0, None
        for m in _TAG.finditer(raw):
            if current:
                colored[current] += len(raw[pos:m.start()].strip())
            current = None if m.group(0).startswith("⟦/") else m.group(1)
            pos = m.end()
        total = len(self.plain.strip()) or 1
        top = colored.most_common(1)
        self.colors = top[0][0] if top and top[0][1] >= 0.6 * total else None


def _lines(pages: List[str]) -> List[_Line]:
    out: List[_Line] = []
    for page in pages:
        in_table = False
        for raw in page.splitlines():
            if raw.startswith("[Tabla]"):
                in_table = True
            if not in_table and raw.strip():
                out.append(_Line(raw))
            if raw.startswith("[/Tabla]"):
                in_table = False
    return out


def _mark_color(lines: List[_Line]) -> Optional[str]:
    """La marca que el documento usa para señalar respuestas (un color, o
    resaltado/subrayado/negrita): la más frecuente entre líneas cortas que
    parecen opciones (los títulos marcados son pocos y largos o terminan
    en ":"/"?")."""
    counts = Counter(
        ln.colors for ln in lines
        if ln.colors and len(ln.plain) <= 140 and not ln.plain.rstrip().endswith(("?", ":"))
    )
    if not counts:
        return None
    color, n = counts.most_common(1)[0]
    return color if n >= 2 else None


def _find_anchor(lines: List[_Line], stem: str, start: int) -> Optional[int]:
    key = _norm(stem)[:40]
    # Desde el final del enunciado hacia atrás: la última línea del
    # enunciado es la que queda justo antes de las opciones.
    probes = [key]
    tail = _norm(stem)[-35:]
    if tail and tail != key:
        probes.append(tail)
    for probe in probes:
        if len(probe) < 12:
            continue
        for i in range(start, len(lines)):
            if probe[:25] in lines[i].norm or (len(lines[i].norm) >= 12 and lines[i].norm in probe):
                return i
    return None


def _option_line(lines: List[_Line], lo: int, hi: int, option: str) -> Optional[int]:
    opt = _norm(option)
    if not opt:
        return None
    for i in range(lo, hi):
        ln = lines[i].norm
        if not ln:
            continue
        if ln == opt or (len(opt) >= 12 and ln.startswith(opt[:40])) or (len(ln) >= 12 and opt.startswith(ln)):
            return i
    return None


def _anchors(questions: List[Dict[str, Any]], lines: List[_Line]) -> List[Optional[int]]:
    """Línea donde termina el enunciado de cada pregunta (None si no se ubica)."""
    anchors: List[Optional[int]] = []
    cursor = 0
    for q in questions:
        stem = (q.get("data") or {}).get("stem") or (q.get("data") or {}).get("text") or ""
        a = _find_anchor(lines, stem, cursor) if stem else None
        anchors.append(a)
        if a is not None:
            cursor = a + 1
    return anchors


def _candidates(questions: List[Dict[str, Any]], lines: List[_Line], anchors: List[Optional[int]],
                only: Optional[str]) -> Tuple[int, List[Tuple[Dict[str, Any], List[str]]]]:
    """
    (preguntas ubicadas, [(pregunta, opciones marcadas)]). Con `only`, la
    marca de respuesta es esa. Sin `only` (marcas mezcladas), cada pregunta
    usa la marca que traigan sus propias opciones, con tal de que sea UNA
    sola: si en la misma pregunta hay dos marcas distintas, no se decide.
    """
    located = 0
    candidates: List[Tuple[Dict[str, Any], List[str]]] = []
    for idx, q in enumerate(questions):
        if q.get("type") != "multichoice" or anchors[idx] is None:
            continue
        lo = anchors[idx] + 1
        hi = next((a for a in anchors[idx + 1:] if a is not None and a > lo), len(lines))
        options: Dict[str, str] = q["data"].get("options") or {}
        found = {L: _option_line(lines, lo, hi, text) for L, text in options.items()}
        if not options or any(v is None for v in found.values()):
            continue
        # Dos letras distintas no pueden apuntar a la MISMA línea: si pasa,
        # una coincidencia difusa (una opción cuyo texto es prefijo del de
        # otra, ej. "Estructura de datos abstracta" y "... compleja") le
        # "robó" la línea a su vecina — no se puede confiar en esta
        # ubicación, así que se descarta la pregunta entera (mismo criterio
        # que "falta alguna opción", ver docstring del módulo).
        if len(set(found.values())) != len(found):
            continue
        located += 1
        marks = {L: lines[i].colors for L, i in sorted(found.items())}
        if only is not None:
            letters = [L for L, m in marks.items() if m == only]
        else:
            distinct = {m for m in marks.values() if m}
            letters = [L for L, m in marks.items() if m] if len(distinct) == 1 else []
        marked = [options[L] for L in letters]
        # Sin marca, o con TODAS las opciones marcadas (ej. un examen que
        # pone todas las opciones en negrita): eso no señala una respuesta.
        if marked and len(marked) < len(options):
            candidates.append((q, marked))
    return located, candidates


def resolve_answer_marks(questions: List[Dict[str, Any]], answer_key: Dict[int, Dict[str, Any]],
                         pages: List[str]) -> Dict[str, Any]:
    """
    Para cada pregunta multichoice, ubica su bloque en el texto enriquecido
    (entre su enunciado y el de la siguiente pregunta) y cada opción. Si
    TODAS se encuentran y algunas (no todas) llevan la marca del documento
    (un color, resaltado, subrayado o negrita), la respuesta pasa a ser
    exactamente las opciones marcadas.

    Solo se aplica si la marca funciona de verdad como sistema de
    respuestas: en al menos 2 preguntas y en al menos el 30 % de las que se
    pudieron ubicar. Muchos exámenes usan negrita o color para títulos o
    para destacar una palabra: una opción marcada de casualidad no debe
    reemplazar la respuesta de la clave.

    1.º se prueba la marca dominante del documento. 2.º, si esa sola no
    alcanza (un docente que subraya en una pregunta, resalta en otra y pone
    negrita en la siguiente), se prueban TODAS las marcas juntas, con los
    mismos umbrales aplicados al conjunto ("mixta").

    Devuelve {"mark": nombre de la marca o None, "applied": preguntas cuya
    respuesta salió de la marca, "changed": cuántas cambiaron respecto a
    lo que dijo el modelo}.
    """
    result = {"mark": None, "applied": 0, "changed": 0}
    lines = _lines(pages)
    anchors = _anchors(questions, lines)
    dominant = _mark_color(lines)

    chosen: List[Tuple[Dict[str, Any], List[str]]] = []
    for mark, only in ((dominant, dominant), (MIXED_MARKS, None)):
        if mark is None:
            continue
        located, candidates = _candidates(questions, lines, anchors, only)
        if len(candidates) >= 2 and len(candidates) >= 0.3 * located:
            result["mark"], chosen = mark, candidates
            break
    if not chosen:
        return result

    for q, marked in chosen:
        new_answer = " | ".join(marked)
        entry = answer_key.setdefault(q["num"], {"type": "multichoice"})
        if entry.get("answer") != new_answer:
            entry["answer"] = new_answer
            result["changed"] += 1
        q["data"]["answer_from_marks"] = True
        result["applied"] += 1
    return result


# ── Cuadros de marcas (REGLA 10) ─────────────────────────────────────────────

def resolve_table_marks(questions: List[Dict[str, Any]], answer_key: Dict[int, Dict[str, Any]],
                        tables: List[List[List[str]]]) -> int:
    """
    Para cada emparejamiento, busca la tabla cuyas filas coinciden con su
    Columna A; si en cada fila hay exactamente UNA celda marcada (x/X), la
    pareja de esa fila es el encabezado de esa columna — leído de la
    estructura de la tabla, no deducido por el significado.
    """
    changed = 0
    for q in questions:
        if q.get("type") != "matching":
            continue
        col_a: Dict[str, str] = q["data"].get("col_a") or {}
        col_b: Dict[str, str] = q["data"].get("col_b") or {}
        if not col_a or not col_b:
            continue
        b_by_norm = {_norm(v): k for k, v in col_b.items()}
        for table in tables:
            if len(table) < 2:
                continue
            header = [_norm(c) for c in table[0]]
            rows = {_norm(r[0]): r for r in table[1:] if r and r[0]}
            pairs: Dict[str, str] = {}
            for num, item in col_a.items():
                row = rows.get(_norm(item))
                if row is None:
                    break
                marks = [j for j, c in enumerate(row[1:], start=1) if str(c or "").strip().lower() == "x"]
                if len(marks) != 1 or marks[0] >= len(header):
                    break
                letter = b_by_norm.get(header[marks[0]])
                if letter is None:
                    break
                pairs[num] = letter
            if len(pairs) != len(col_a):
                continue
            ordered = sorted(pairs.items(), key=lambda kv: int(kv[0]))
            new_answer = "; ".join(f"{k}-{v}" for k, v in ordered)
            entry = answer_key.setdefault(q["num"], {"type": "matching"})
            if entry.get("answer") != new_answer:
                entry["answer"] = new_answer
                entry["pairs"] = dict(ordered)
                changed += 1
            q["data"]["answer_from_marks"] = True
            break
    return changed


# ── Verdadero/falso marcado en el propio documento ───────────────────────────
# "( X ) Verdadero   (   ) Falso", "[x] Falso", o la palabra en color /
# resaltado / subrayado / negrita. Sin esto la respuesta la decidía el modelo
# (dev/eval x01: con "( X ) Verdadero" en "El español es el idioma oficial de
# Brasil" devolvía "Falso", lo que él cree cierto y no lo que marcó el docente).

_TF_WORD = {"verdadero": "Verdadero", "cierto": "Verdadero", "v": "Verdadero", "falso": "Falso", "f": "Falso"}
_TF_CHECKED = re.compile(r"[\(\[]\s*[xX✓✔]\s*[\)\]]\s*(verdadero|falso|cierto|v|f)\b", re.IGNORECASE)
_TF_MARKED_WORD = re.compile(r"⟦([a-záéíóú]+)⟧\s*(verdadero|falso|cierto|v|f)\s*⟦/\1⟧", re.IGNORECASE)


def _tf_mark(raw_lines: List[str]) -> Optional[str]:
    text = " ".join(raw_lines)
    found = {_TF_WORD[w.lower()] for w in _TF_CHECKED.findall(text)}
    found |= {_TF_WORD[m.group(2).lower()] for m in _TF_MARKED_WORD.finditer(text)}
    return found.pop() if len(found) == 1 else None


def resolve_tf_marks(questions: List[Dict[str, Any]], answer_key: Dict[int, Dict[str, Any]],
                     pages: List[str]) -> int:
    """
    Para cada verdadero/falso, busca en su línea (y las 2 siguientes, hasta la
    pregunta que sigue) UNA casilla marcada o UNA de las dos palabras marcada.
    Si hay exactamente una, esa es la respuesta. Si la misma palabra sale
    marcada en todas las preguntas (con 3 o más), es un estilo del documento
    (ej. "Verdadero" siempre en negrita) y no se aplica nada.
    Devuelve cuántas preguntas quedaron con la respuesta leída de la marca.
    """
    lines = _lines(pages)
    anchors = _anchors(questions, lines)
    found: List[Tuple[Dict[str, Any], str]] = []
    for idx, q in enumerate(questions):
        if q.get("type") != "truefalse" or anchors[idx] is None:
            continue
        lo = anchors[idx]
        hi = next((a for a in anchors[idx + 1:] if a is not None and a > lo), len(lines))
        answer = _tf_mark([ln.raw for ln in lines[lo:min(hi, lo + 3)]])
        if answer:
            found.append((q, answer))
    if not found or (len(found) >= 3 and len({a for _, a in found}) == 1):
        return 0
    for q, answer in found:
        entry = answer_key.setdefault(q["num"], {"type": "truefalse"})
        entry["answer"] = answer
        q["data"]["answer_from_marks"] = True
    return len(found)
