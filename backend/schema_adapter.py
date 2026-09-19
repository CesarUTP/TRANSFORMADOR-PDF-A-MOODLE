"""
schema_adapter.py — JSON estructurado del modelo (RESPONSE_SCHEMA) → la
forma que ya consumen el editor, el validador y xml_builder.

El modo "json" cambia CÓMO el modelo entrega la información, no qué
recibe el resto del sistema: este adaptador produce exactamente el mismo
{questions, answer_key} que antes salía de parser.py, así que el frontend
y la generación del XML no cambian.

    questions:  [{"num", "type", "data": {...}}]
    answer_key: {num: {"type", "answer", ["pairs"]}}

Las convenciones de ese formato (letras A, B... en opciones; " | " para
varias correctas; "1-a; 2-b" en emparejamiento; "[A: x / y]" en cloze con
clave "A. x; B. y"; SIN_RESPUESTA cuando el documento no marca nada) son
las mismas que ya validan validator.py y xml_builder.py.
"""

import re
from typing import Any, Dict, List, Tuple

from config import TRANSCRIPTION_FAILED_MARKER

SIN_RESPUESTA = "SIN_RESPUESTA"
_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_TF = {
    "verdadero": "Verdadero", "cierto": "Verdadero", "correcto": "Verdadero",
    "true": "Verdadero", "v": "Verdadero",
    "falso": "Falso", "incorrecto": "Falso", "false": "Falso", "f": "Falso",
}
# Marcadores de hueco en el enunciado de un cloze: [A], [ A ], [a]...
_SLOT = re.compile(r"\[\s*([A-Za-z])\s*\]")


def _text(s: Any) -> str:
    """Enunciado: conserva los saltos de línea (código, listas A./B. propias
    del enunciado), solo limpia espacios sobrantes al final de cada línea."""
    lines = [ln.rstrip() for ln in str(s or "").strip().splitlines()]
    return "\n".join(ln for i, ln in enumerate(lines) if ln or (i and lines[i - 1]))


def _line(s: Any) -> str:
    """Opción/elemento: una sola línea."""
    return " ".join(str(s or "").split())


def _multichoice(q: dict) -> Tuple[dict, str]:
    opts = [o for o in (q.get("opciones") or []) if str(o.get("texto", "")).strip()]
    options = {_LETTERS[i]: _line(o["texto"]) for i, o in enumerate(opts[:len(_LETTERS)])}
    correct = [options[_LETTERS[i]] for i, o in enumerate(opts[:len(_LETTERS)]) if o.get("correcta")]
    answer = " | ".join(correct) if (correct and q.get("respuesta_marcada", True)) else SIN_RESPUESTA
    return {"stem": _text(q.get("enunciado")), "options": options}, answer


def _truefalse(q: dict) -> Tuple[dict, str]:
    raw = str(q.get("respuesta_texto") or "").strip()
    first = raw.split()[0].strip(".,;:()").lower() if raw else ""
    answer = _TF.get(first, SIN_RESPUESTA) if q.get("respuesta_marcada", True) else SIN_RESPUESTA
    return {"stem": _text(q.get("enunciado"))}, answer


def _matching(q: dict) -> Tuple[dict, str, Dict[str, str]]:
    left = [_line(x) for x in (q.get("items_izquierda") or []) if str(x).strip()]
    right = [_line(x) for x in (q.get("items_derecha") or []) if str(x).strip()]
    col_a = {str(i + 1): t for i, t in enumerate(left)}
    col_b = {_LETTERS[i].lower(): t for i, t in enumerate(right[:len(_LETTERS)])}
    pairs: Dict[str, str] = {}
    for p in q.get("parejas") or []:
        li, ri = p.get("izquierda"), p.get("derecha")
        if isinstance(li, int) and isinstance(ri, int) and 1 <= li <= len(left) and 1 <= ri <= len(col_b):
            pairs[str(li)] = _LETTERS[ri - 1].lower()
    ordered = sorted(pairs.items(), key=lambda kv: int(kv[0]))
    answer = "; ".join(f"{k}-{v}" for k, v in ordered) if ordered else SIN_RESPUESTA
    data = {"stem": _text(q.get("enunciado")), "col_a": col_a, "col_b": col_b}
    if q.get("origen_tabla"):
        data["from_table"] = True
    return data, answer, dict(ordered)


def _cloze(q: dict) -> Tuple[dict, str]:
    text = str(q.get("enunciado") or "").strip()
    huecos = q.get("huecos") or []
    by_letter = {}
    for i, h in enumerate(huecos):
        letter = (str(h.get("marcador") or "").strip()[:1] or _LETTERS[i]).upper()
        by_letter[letter] = h

    key_parts: List[str] = []

    def render(m: re.Match) -> str:
        letter = m.group(1).upper()
        h = by_letter.get(letter)
        if not h:
            return m.group(0)
        opts = [_line(o["texto"]) for o in h.get("opciones") or [] if str(o.get("texto", "")).strip()]
        correct = [_line(o["texto"]) for o in h.get("opciones") or []
                   if o.get("correcta") and str(o.get("texto", "")).strip()]
        if correct and q.get("respuesta_marcada", True):
            key_parts.append(f"{letter}. {' | '.join(correct)}")
            return f"[{letter}: {' / '.join(opts)}]"
        # Mismo convenio que el formato de texto (REGLA 5): el hueco sin
        # respuesta lleva SIN_RESPUESTA dentro de los corchetes y en la clave.
        key_parts.append(f"{letter}. {SIN_RESPUESTA}")
        return f"[{letter}: {' / '.join([SIN_RESPUESTA] + opts)}]"

    rendered = _SLOT.sub(render, text)
    answer = "; ".join(key_parts) if key_parts else SIN_RESPUESTA
    return {"text": rendered}, answer


def _plain(q: dict, qtype: str) -> Tuple[dict, str]:
    stem = _text(q.get("enunciado"))
    if qtype == "essay":
        return {"stem": stem}, "respuesta abierta, se califica manualmente"
    raw = str(q.get("respuesta_texto") or "").strip()
    if not raw or not q.get("respuesta_marcada", True):
        return {"stem": stem}, SIN_RESPUESTA
    return {"stem": stem}, raw


def adapt(payload: dict) -> Tuple[List[Dict[str, Any]], Dict[int, Dict[str, Any]]]:
    """
    Convierte la respuesta del modelo en (questions, answer_key).
    El número de cada pregunta es su posición final (1..N) según "orden",
    igual que la renumeración limpia del formato de texto.
    """
    raw_qs = sorted(payload.get("preguntas") or [], key=lambda q: (q.get("orden") or 0))
    questions: List[Dict[str, Any]] = []
    answer_key: Dict[int, Dict[str, Any]] = {}

    for num, q in enumerate(raw_qs, start=1):
        qtype = q.get("tipo")
        pairs = None
        if qtype == "multichoice":
            data, answer = _multichoice(q)
        elif qtype == "truefalse":
            data, answer = _truefalse(q)
        elif qtype == "matching":
            data, answer, pairs = _matching(q)
        elif qtype == "cloze":
            data, answer = _cloze(q)
        elif qtype in ("essay", "shortanswer", "numerical"):
            data, answer = _plain(q, qtype)
        else:
            continue

        # REGLA 11: imagen ilegible y sin respuesta → el validador reconoce
        # este marcador y da el motivo específico ("revisa la imagen a
        # mano") en vez del genérico "no tiene respuesta".
        low_conf = q.get("confianza") == "baja"
        if low_conf and answer == SIN_RESPUESTA:
            key = "text" if qtype == "cloze" else "stem"
            data[key] = f"{TRANSCRIPTION_FAILED_MARKER} {data.get(key, '')}".strip()
        elif low_conf:
            data["low_confidence"] = True

        page = q.get("pagina")
        if isinstance(page, int) and page > 0:
            data["page"] = page

        questions.append({"num": num, "type": qtype, "data": data})
        entry: Dict[str, Any] = {"type": qtype, "answer": answer}
        if pairs is not None:
            entry["pairs"] = pairs
        answer_key[num] = entry

    return questions, answer_key
