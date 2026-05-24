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

    # ── multichoice ──
    mc_entries = re.findall(r'(?:^|\n)(\d+)\s+multichoice\s+(.+)', clean_key)
    for num_str, answer_rest in mc_entries:
        num = int(num_str)
        answer = re.split(r'\n\d+\s+\w', answer_rest)[0].strip()
        answer = re.sub(r'\n\s+', ' ', answer).strip()
        answer_key[num] = {"type": "multichoice", "answer": answer}

    # ── truefalse ──
    tf_entries = re.findall(r'(?:^|\n)(\d+)\s+truefalse\s+(.+)', clean_key)
    for num_str, answer_rest in tf_entries:
        num = int(num_str)
        answer = answer_rest.split()[0].strip()
        answer_key[num] = {"type": "truefalse", "answer": answer}

    # ── matching ──
    # Each matching line: "N  matching  1. A → B; 2. C → D"
    # We capture ONLY the text after the word "matching" up to the next answer line.
    mt_pattern = re.compile(
        r'(?:^|\n)(\d+)\s+matching\s+([^\n]+(?:\n(?!\d+\s+\w+\s+).*)*)',
        re.MULTILINE
    )
    for m in mt_pattern.finditer(clean_key):
        num = int(m.group(1))
        raw = m.group(2).strip()
        # Collapse wrapped lines, stop at next numbered answer line
        raw = re.sub(r'\n(?!\d+\s)', ' ', raw)
        raw = re.sub(r'\s{2,}', ' ', raw).strip()
        answer_key[num] = {"type": "matching", "answer": raw}

    # ── cloze ──
    cl_entries = re.findall(r'(?:^|\n)(\d+)\s+cloze\s+(.+)', clean_key)
    for num_str, answer_rest in cl_entries:
        num = int(num_str)
        answer = answer_rest.strip()
        answer = re.sub(r'\n\s+', ' ', answer).strip()
        answer = re.split(r'\n\d+\s+\w', answer)[0].strip()
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

    next_q_match = re.search(rf'\nPregunta {q_num + 1}:', text[start_pos:])
    if next_q_match:
        end_candidates.append(next_q_match.start())

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
    opt_pattern = r'\n([A-D])\.\s+(.*?)(?=\n[A-D]\.\s|\n*$)'
    for match in re.finditer(opt_pattern, q_text, re.DOTALL):
        letter = match.group(1)
        opt_text = match.group(2).strip()
        opt_text = re.sub(r'\n\s+', ' ', opt_text)
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
    """Parse a matching question block with Columna A / Columna B."""
    col_a_start = q_text.find("Columna A:")
    stem = ""
    if col_a_start > 0:
        stem = q_text[:col_a_start].strip()
        stem = re.sub(r'^Afirmaci\u00f3n:\s*', '', stem).strip()

    col_a_match = re.search(r'Columna A:\s*\n(.*?)Columna B:', q_text, re.DOTALL)
    col_b_match = re.search(r'Columna B:\s*\n(.*)', q_text, re.DOTALL)

    col_a_items: Dict[str, str] = {}
    col_b_items: Dict[str, str] = {}

    if col_a_match:
        col_a_text = col_a_match.group(1).strip()
        for m in re.finditer(r'(\d+)\.\s+(.*?)$', col_a_text, re.MULTILINE):
            col_a_items[m.group(1)] = m.group(2).strip()

    if col_b_match:
        col_b_text = col_b_match.group(1).strip()
        col_b_text = re.sub(r'\n(truefalse|matching|cloze|RESPUESTAS)\n', '\n', col_b_text)
        for m in re.finditer(r'([a-d])\.\s+(.*?)(?=\n[a-d]\.\s|$)', col_b_text, re.DOTALL):
            letter = m.group(1)
            item = m.group(2).strip()
            item = re.sub(r'\n\s+', ' ', item)
            col_b_items[letter] = item

    return {"stem": stem, "col_a": col_a_items, "col_b": col_b_items}


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
