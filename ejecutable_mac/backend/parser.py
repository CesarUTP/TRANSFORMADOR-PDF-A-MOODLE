"""
parser.py — Dynamic answer-key detection and question parsing.

Eliminates all hardcoded range() calls from the original script.
Detects question types by reading the RESPUESTAS section first,
builds an answer_key dict, then dispatches to the correct parser.
"""

import re
from typing import Dict, List, Optional


# ──────────────────────────────────────────────
#  SECTION 1: Answer-key parsing
# ──────────────────────────────────────────────

def parse_matching_pairs(raw: str) -> Dict[str, str]:
    """
    Extract {item_number: letter} pairs from a compact matching answer key
    such as "1-a; 2-b; 3-c" or "1-a, 2-b, 3-c, 4-d" or "1. a; 2. b".

    Deliberately strict: only matches a digit followed by a SINGLE letter
    (word-bounded), so it never mistakes a full-text arrow pair like
    "1. Cooperación → a" for a valid number-letter pair — that malformed
    shape is left unmatched on purpose so validation can flag it instead
    of silently building wrong subquestion/answer pairs.
    """
    pairs: Dict[str, str] = {}
    for m in re.finditer(r'(\d+)\s*[-.→:]\s*([A-Za-z])\b', raw):
        pairs[m.group(1)] = m.group(2).lower()
    return pairs

def parse_answer_key(full_text: str) -> Dict[int, dict]:
    """
    Locate the RESPUESTAS section and parse every answer line.

    Returns:
        answer_key: {question_num: {"type": str, "answer": str}}
    """
    key_start = full_text.find("RESPUESTAS")
    if key_start < 0:
        key_start = full_text.find("RESPUESTAS\n")
    key_section = full_text[key_start:] if key_start >= 0 else ""

    # Clean recurring column-header noise
    clean_key = re.sub(r'\s*Nº\s+Tipo\s+Respuesta\s+correcta\s*\n?\s*', '\n', key_section)
    clean_key = re.sub(r'^RESPUESTAS\s*\n?', '', clean_key).strip()

    answer_key: Dict[int, dict] = {}

    # Reusable "rest of the answer" group: captures the current line plus any
    # wrapped continuation lines, stopping at the next numbered answer row.
    # Without this, a long answer that happens to wrap onto a second line
    # (e.g. a lengthy multichoice option copied verbatim) would silently
    # truncate to just its first line.
    _REST = r'([^\n]+(?:\n(?!\d+\s+(?:\w+|múltiple|multiple|ciertofalso|verdaderofalso|emparejamiento|completar)\s+).*)*)'

    # ── multichoice ──
    mc_entries = re.findall(rf'(?:^|\n)(\d+)\s+(?:multichoice|múltiple|multiple)\s+{_REST}', clean_key, re.IGNORECASE)
    for num_str, answer_rest in mc_entries:
        num = int(num_str)
        answer = re.sub(r'\n\s*', ' ', answer_rest).strip()
        answer_key[num] = {"type": "multichoice", "answer": answer}

    # ── truefalse ──
    tf_entries = re.findall(rf'(?:^|\n)(\d+)\s+(?:truefalse|ciertofalso|verdaderofalso)\s+{_REST}', clean_key, re.IGNORECASE)
    for num_str, answer_rest in tf_entries:
        num = int(num_str)
        answer = answer_rest.split()[0].strip()
        answer_key[num] = {"type": "truefalse", "answer": answer}

    # ── matching ──
    # Each matching line: "N  emparejamiento  1-a; 2-b; 3-c" (puede traer texto extra, p.ej. justificación)
    mt_pattern = re.compile(
        rf'(?:^|\n)(\d+)\s+(?:matching|emparejamiento)\s+{_REST}',
        re.MULTILINE | re.IGNORECASE
    )
    for m in mt_pattern.finditer(clean_key):
        num = int(m.group(1))
        raw = m.group(2).strip()
        # Collapse wrapped lines, stop at next numbered answer line
        raw = re.sub(r'\n(?!\d+\s)', ' ', raw)
        raw = re.sub(r'\s{2,}', ' ', raw).strip()
        answer_key[num] = {"type": "matching", "answer": raw, "pairs": parse_matching_pairs(raw)}

    # ── cloze ──
    cl_entries = re.findall(rf'(?:^|\n)(\d+)\s+(?:cloze|completar)\s+{_REST}', clean_key, re.IGNORECASE)
    for num_str, answer_rest in cl_entries:
        num = int(num_str)
        answer = re.sub(r'\n\s*', ' ', answer_rest).strip()
        answer_key[num] = {"type": "cloze", "answer": answer}

    return answer_key


# ──────────────────────────────────────────────
#  SECTION 2: Individual question extractors
# ──────────────────────────────────────────────

def extract_question_text(text: str, q_num: int) -> Optional[str]:
    """Extract the raw text block for a specific question number."""
    start_pattern = rf'Pregunta {q_num}:\s*\n'
    start_match = re.search(start_pattern, text)
    if not start_match:
        return None

    start_pos = start_match.end()
    end_candidates = []

    # Buscar CUALQUIER "Pregunta N:" siguiente, no solo q_num+1: si la
    # numeración del documento tiene un salto (p. ej. falta la Pregunta 5),
    # limitarse a q_num+1 hacía que esta pregunta se tragara todo el resto
    # del documento como si fuera su propio enunciado.
    for m in re.finditer(r'\nPregunta\s+(\d+):', text[start_pos:]):
        if int(m.group(1)) > q_num:
            end_candidates.append(m.start())
            break

    for pattern in [r'\ntruefalse\n', r'\nmatching\n', r'\ncloze\n',
                    r'\nRESPUESTAS\n', r'\nRESPUESTAS\s']:
        sec_match = re.search(pattern, text[start_pos:])
        if sec_match:
            end_candidates.append(sec_match.start())

    end_pos = min(end_candidates) if end_candidates else len(text) - start_pos
    return text[start_pos:start_pos + end_pos].strip()


def parse_multichoice(q_text: str) -> Optional[dict]:
    """Parse a multichoice question block."""
    a_match = re.search(r'\nA\.\s', q_text)
    if not a_match:
        return None

    stem = q_text[:a_match.start()].strip()
    stem = re.sub(r'^Afirmación:\s*', '', stem).strip()

    options: Dict[str, str] = {}
    # No limitado a A-D: algunos exámenes traen 5+ opciones (E, F...); se
    # descartaban en silencio si el patrón solo reconocía hasta D.
    opt_pattern = r'\n([A-Z])\.\s+(.*?)(?=\n[A-Z]\.\s|\n*$)'
    for match in re.finditer(opt_pattern, q_text, re.DOTALL):
        letter = match.group(1)
        opt_text = match.group(2).strip()
        opt_text = re.sub(r'\n\s*', ' ', opt_text)
        options[letter] = opt_text

    return {"stem": stem, "options": options}


def parse_truefalse(q_text: str) -> Optional[dict]:
    """Parse a true/false question block."""
    stem = q_text.strip()
    stem = re.sub(r'^Afirmación:\s*', '', stem).strip()
    stem = re.sub(r'\n+', ' ', stem).strip()
    stem = re.sub(r'\s{2,}', ' ', stem).strip()
    return {"stem": stem}


def parse_matching(q_text: str) -> Optional[dict]:
    """Parse a matching question block with Columna A / Columna B.

    Header matching tolerates a trailing descriptive parenthetical
    (e.g. "Columna A (Situaciones de trabajo):") in case the upstream
    normalization step doesn't strip it to the bare "Columna A:" form.
    """
    # El prefiltro de IA marca así una pregunta que originalmente era una
    # tabla/cuadro (ej. una fila por evento, una columna marcada por fila)
    # y que convirtió a emparejamiento por su cuenta (ver REGLA 10 del
    # SYSTEM_PROMPT) — se guarda la marca para que el usuario la vea
    # resaltada en el editor y la revise con más cuidado antes de aceptarla.
    from_table = False
    table_marker_match = re.match(r'\s*\[TABLA_CONVERTIDA\]\s*\n?', q_text)
    if table_marker_match:
        from_table = True
        q_text = q_text[table_marker_match.end():]

    col_a_header = re.search(r'Columna A[^:\n]*:', q_text)
    stem = ""
    if col_a_header and col_a_header.start() > 0:
        stem = q_text[:col_a_header.start()].strip()
        stem = re.sub(r'^Afirmaci\u00f3n:\s*', '', stem).strip()

    col_a_match = re.search(r'Columna A[^:\n]*:\s*\n(.*?)Columna B[^:\n]*:', q_text, re.DOTALL)
    col_b_match = re.search(r'Columna B[^:\n]*:\s*\n(.*)', q_text, re.DOTALL)

    col_a_items: Dict[str, str] = {}
    col_b_items: Dict[str, str] = {}

    if col_a_match:
        col_a_text = col_a_match.group(1).strip()
        # Lookahead al siguiente número (o fin de texto) en vez de '$' con
        # MULTILINE: un elemento envuelto en 2+ líneas ya no se trunca en
        # la primera línea.
        for m in re.finditer(r'(\d+)\.\s+(.*?)(?=\n\d+\.\s|$)', col_a_text, re.DOTALL):
            item = re.sub(r'\n\s*', ' ', m.group(2).strip())
            col_a_items[m.group(1)] = item

    if col_b_match:
        col_b_text = col_b_match.group(1).strip()
        col_b_text = re.sub(r'\n(truefalse|matching|cloze|RESPUESTAS)\n', '\n', col_b_text)
        # No limitado a a-d: una Columna B con 5+ pares (e, f...) se perdía
        # en silencio — el último elemento reconocido absorbía todo el resto
        # como si fuera su propio texto.
        for m in re.finditer(r'([a-z])\.\s+(.*?)(?=\n[a-z]\.\s|$)', col_b_text, re.DOTALL):
            letter = m.group(1)
            item = m.group(2).strip()
            item = re.sub(r'\n\s*', ' ', item)
            col_b_items[letter] = item

    if not col_a_items or not col_b_items:
        return None

    result = {"stem": stem, "col_a": col_a_items, "col_b": col_b_items}
    if from_table:
        result["from_table"] = True
    return result


def parse_cloze(q_text: str) -> Optional[dict]:
    """Parse a cloze question block (uses [A: option1 / option2] format)."""
    cloze_text = q_text.strip()
    cloze_text = re.sub(r'^Afirmación:\s*', '', cloze_text).strip()
    return {"text": cloze_text}


# ──────────────────────────────────────────────
#  SECTION 3: Dynamic dispatcher
# ──────────────────────────────────────────────

def build_questions(full_text: str, answer_key: Dict[int, dict]) -> List[dict]:
    """
    Dynamically dispatch parsing for each question number found in the
    answer_key, without any hardcoded ranges.
    """
    questions: List[dict] = []

    for num in sorted(answer_key.keys()):
        qtype = answer_key[num]["type"]
        q_text = extract_question_text(full_text, num)
        if not q_text:
            questions.append({
                "num": num,
                "type": qtype,
                "data": {},
                "error": f"No se pudo extraer el texto de la Pregunta {num} en el cuerpo del documento."
            })
            continue

        parsed = None
        if qtype == "multichoice":
            parsed = parse_multichoice(q_text)
        elif qtype == "truefalse":
            parsed = parse_truefalse(q_text)
        elif qtype == "matching":
            parsed = parse_matching(q_text)
        elif qtype == "cloze":
            parsed = parse_cloze(q_text)

        if not parsed:
            questions.append({
                "num": num,
                "type": qtype,
                "data": {},
                "error": f"La estructura de la Pregunta {num} no coincide con el formato esperado para '{qtype}'."
            })
        else:
            questions.append({"num": num, "type": qtype, "data": parsed})

    return questions
