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
from answer_matching import split_answers

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


# ── Resolución determinista de la clave ─────────────────────────────────────
# Cuando el documento trae una clave separada ("RESPUESTAS: 1. c"), el
# modelo solo COPIA ese texto en clave_texto y la respuesta se resuelve
# aquí, en código. Motivo (medido en dev/eval.py, s01): aun con la clave
# explícita "c) Saturno" y la instrucción de no corregirla, el modelo
# marcaba "Júpiter" — su propio conocimiento le ganaba a la clave. Copiar
# un texto es una tarea que no invita a "corregir"; interpretarlo, sí.

def _norm(s: Any) -> str:
    return " ".join(str(s or "").lower().split()).strip(" .)")


_QNUM_PREFIX = re.compile(r"^\s*\d{1,3}\s*[.)]\s+(?=\S)")


def _clave(q: dict) -> str:
    """clave_texto sin el número de la pregunta que a veces antepone el
    modelo al copiar la línea de la clave ("9. 50" → "50", "1. c" → "c").
    No aplica a emparejamiento, donde "1-b" es parte de la respuesta."""
    raw = str(q.get("clave_texto") or "").strip()
    if q.get("tipo") == "matching":
        return raw
    return _QNUM_PREFIX.sub("", raw, count=1)


def _key_letters(clave: str) -> List[str]:
    """ "c" / "b, d" / "C." / "b y d" → ["c"] / ["b", "d"]. [] si la clave
    no es una lista de rótulos sueltos (ej. trae el texto de la opción)."""
    tokens = re.split(r"\s*(?:,|;|/|\||\by\b|\be\b|\s)\s*", clave.strip())
    tokens = [t.strip(" .)(") for t in tokens if t.strip(" .)(")]
    if tokens and all(re.fullmatch(r"[A-Za-z]|\d{1,2}", t) for t in tokens):
        return [t.lower() for t in tokens]
    return []


def _resolve_mc_from_key(clave: str, opts: List[dict]) -> List[int]:
    """Índices de las opciones que indica la clave literal; [] si no se
    puede resolver con certeza (entonces se usa lo que marcó el modelo)."""
    clave = (clave or "").strip()
    if not clave or not opts:
        return []
    labels = [_norm(o.get("letra_original")) for o in opts]
    letters = _key_letters(clave)
    if not letters:
        # "C. Rusia" / "c) Ambas": rótulo + texto → vale si ambos coinciden.
        m = re.match(r"^\s*([A-Za-z]|\d{1,2})\s*[.)\-:]\s*(.+)$", clave)
        if m:
            letters = [m.group(1).lower()]
            idx = _index_for_label(letters[0], labels, len(opts))
            if idx is not None and _norm(opts[idx].get("texto")) == _norm(m.group(2)):
                return [idx]
            letters = []
        # Clave con el texto de la(s) opción(es).
        wanted = [_norm(x) for x in split_answers(clave)]
        hits = [i for i, o in enumerate(opts) if _norm(o.get("texto")) in wanted]
        return hits if len(hits) == len(wanted) else []
    idxs = [_index_for_label(L, labels, len(opts)) for L in letters]
    return idxs if all(i is not None for i in idxs) else []


def _index_for_label(label: str, labels: List[str], n: int):
    if label in labels:
        return labels.index(label)
    # Opciones sin rótulo propio: la letra o el número de la clave es su
    # posición (a=1, "1"=1) — letra_original documenta ambos casos ("a",
    # "B", "1"...), pero antes solo se resolvía por posición una letra; una
    # clave puramente numérica ("2") sin ninguna opción rotulada no
    # resolvía nada y caía en lo que marcó el modelo en vez de en la clave
    # literal del documento.
    if not any(labels):
        if len(label) == 1 and label.isalpha():
            i = ord(label) - ord("a")
            return i if 0 <= i < n else None
        if label.isdigit():
            i = int(label) - 1
            return i if 0 <= i < n else None
    return None


def _multichoice(q: dict) -> Tuple[dict, str]:
    opts = [o for o in (q.get("opciones") or []) if str(o.get("texto", "")).strip()][:len(_LETTERS)]
    options = {_LETTERS[i]: _line(o["texto"]) for i, o in enumerate(opts)}
    from_key = _resolve_mc_from_key(_clave(q), opts)
    if from_key:
        correct = [options[_LETTERS[i]] for i in from_key]
    else:
        correct = [options[_LETTERS[i]] for i, o in enumerate(opts) if o.get("correcta")]
        if not q.get("respuesta_marcada", True):
            correct = []
        # Todas las opciones marcadas (ej. las 4 en rojo): esa marca no señala
        # una respuesta (lo dice el propio prompt, REGLA 8) — antes el modelo
        # la ignoraba y las 4 salían como correctas (dev/eval x04). Se deja
        # sin respuesta para que el docente decida; una clave explícita
        # ("a, b, c, d") sí se respeta, y se resuelve arriba.
        elif len(opts) >= 2 and len(correct) == len(opts):
            correct = []
    answer = " | ".join(correct) if correct else SIN_RESPUESTA
    return {"stem": _text(q.get("enunciado")), "options": options}, answer


def _truefalse(q: dict) -> Tuple[dict, str]:
    raw = _clave(q) or str(q.get("respuesta_texto") or "").strip()
    if _clave(q):
        q = {**q, "respuesta_marcada": True}
    first = raw.split()[0].strip(".,;:()").lower() if raw else ""
    answer = _TF.get(first, SIN_RESPUESTA) if q.get("respuesta_marcada", True) else SIN_RESPUESTA
    return {"stem": _text(q.get("enunciado"))}, answer


def _matching(q: dict) -> Tuple[dict, str, Dict[str, str]]:
    left = [_line(x) for x in (q.get("items_izquierda") or []) if str(x).strip()]
    right = [_line(x) for x in (q.get("items_derecha") or []) if str(x).strip()]
    col_a = {str(i + 1): t for i, t in enumerate(left)}
    col_b = {_LETTERS[i].lower(): t for i, t in enumerate(right[:len(_LETTERS)])}
    pairs: Dict[str, str] = {}
    # Clave compacta del documento ("1-b, 2-a"): se aplica tal cual, en
    # código, si todos los pares caen dentro de las columnas.
    key_pairs = re.findall(r"(\d+)\s*[-.→:]\s*([A-Za-z])\b", str(q.get("clave_texto") or ""))
    if key_pairs and all(1 <= int(n) <= len(left) and ord(L.lower()) - 96 <= len(col_b) for n, L in key_pairs):
        pairs = {str(int(n)): L.lower() for n, L in key_pairs}
    # Sin clave en el documento (respuesta_marcada=false) las parejas que el
    # modelo devuelva las resolvió él con su conocimiento, no las leyó del
    # documento: se descartan (dev/eval x12: 4 de 4 emparejamientos sin clave
    # salían resueltos). La clave compacta y las tablas de marcas siguen valiendo.
    unmarked = q.get("respuesta_marcada", True) is False
    for p in ([] if (pairs or unmarked) else (q.get("parejas") or [])):
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
        # " / " es el separador de opciones de la forma interna; dentro de
        # una opción se compacta a "/" para no partirla.
        def clean(o): return _line(o["texto"]).replace(" / ", "/")
        opts = [clean(o) for o in h.get("opciones") or [] if str(o.get("texto", "")).strip()]
        correct = [clean(o) for o in h.get("opciones") or []
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
    key = _clave(q)
    if key:
        return {"stem": stem}, key
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
