"""
xml_builder.py — Converts parsed question data into Moodle XML.

Generates XML that conforms to the Moodle XML Question Format spec:
  - UTF-8 encoding
  - CDATA sections for HTML content
  - Correct tag structure per question type (multichoice, truefalse, matching, cloze)
"""

import re
import html
import logging
from typing import Dict, List, Optional

from config import (
    TYPE_WEIGHTS,
    MULTICHOICE_PENALTY,
    FEEDBACK_CORRECT,
    FEEDBACK_INCORRECT,
    DEFAULT_MATCHING_STEM,
)
from models import QuestionStats

logger = logging.getLogger(__name__)


def compute_grades(
    questions: List[dict],
    total_points: float,
) -> Dict[str, float]:
    """
    Calculate the grade (defaultgrade) per question type so that
    all questions together sum exactly to `total_points`.

    Formula:
        unit = total_points / Σ(weight_i × count_i)
        grade_type = weight_type × unit
    """
    counts: Dict[str, int] = {t: 0 for t in TYPE_WEIGHTS}
    for q in questions:
        t = q["type"]
        if t in counts:
            counts[t] += 1

    total_weight = sum(TYPE_WEIGHTS[t] * counts[t] for t in TYPE_WEIGHTS)
    if total_weight == 0:
        return {t: 1.0 for t in TYPE_WEIGHTS}

    unit = total_points / total_weight
    return {t: round(TYPE_WEIGHTS[t] * unit, 7) for t in TYPE_WEIGHTS}


def esc(text: str) -> str:
    """HTML-escape text for safe embedding in XML."""
    return html.escape(str(text), quote=True)


def cdata(text: str) -> str:
    """Wrap text in a CDATA section (required by Moodle for HTML content)."""
    return f"<![CDATA[{text}]]>"


def convert_cloze_to_moodle(cloze_text: str, q_num: int, answer_key: Dict[int, dict]) -> str:
    """
    Convert [A: correct_option / option2 / option3] brackets to
    Moodle {1:MULTICHOICE:=correct~opt2~opt3} syntax.
    Handles multiple embedded gaps (A, B, C...) dynamically.
    """
    def strip_accents(s: str) -> str:
        return (s.replace('á', 'a').replace('é', 'e').replace('í', 'i')
                 .replace('ó', 'o').replace('ú', 'u')
                 .replace('Á', 'A').replace('É', 'E').replace('Í', 'I')
                 .replace('Ó', 'O').replace('Ú', 'U')
                 .replace('ñ', 'n').replace('Ñ', 'N'))

    key_info = answer_key.get(q_num, {})
    raw_key_ans = str(key_info.get("answer", ""))

    # Parse slot answers if present (e.g., "A. respuesta A; B. respuesta B" or "A: respuesta A; B: respuesta B")
    slot_answers: Dict[str, str] = {}
    for m in re.finditer(r'([A-Za-z])[\.:]\s*([^;\n]+)', raw_key_ans):
        slot_answers[m.group(1).upper()] = m.group(2).strip()

    def replace_bracket(match):
        inner = match.group(1).strip()
        parts = re.split(r':\s*', inner, maxsplit=1)
        if len(parts) != 2:
            return match.group(0)

        letter = parts[0].strip().upper()
        options_raw = parts[1].strip()
        options = [o.strip() for o in options_raw.split('/') if o.strip()]

        if not options:
            return match.group(0)

        # Determine which option is correct for this slot
        correct_idx = 0  # default to first option
        target_ans = slot_answers.get(letter, "").strip()

        if target_ans:
            for idx, opt in enumerate(options):
                if target_ans.lower() == opt.lower() or target_ans.lower() in opt.lower() or opt.lower() in target_ans.lower():
                    correct_idx = idx
                    break
        elif raw_key_ans:
            # Fallback: check if raw_key_ans matches any option in this bracket
            for idx, opt in enumerate(options):
                if opt.lower() in raw_key_ans.lower() or raw_key_ans.lower() in opt.lower():
                    correct_idx = idx
                    break

        moodle_options = [
            f"={strip_accents(opt)}" if i == correct_idx else strip_accents(opt)
            for i, opt in enumerate(options)
        ]
        slot_num = str(ord(letter) - ord('A') + 1) if 'A' <= letter <= 'Z' else "1"
        return f"{{{slot_num}:MULTICHOICE:{'~'.join(moodle_options)}}}"

    return re.sub(r'\[([A-Za-z]:\s*[^\]]+)\]', replace_bracket, cloze_text)



def build_xml(
    questions: List[dict],
    answer_key: Dict[int, dict],
    category: str = "mis-preguntas",
    grades: Optional[Dict[str, float]] = None,
) -> tuple[str, QuestionStats]:
    """
    Generate the full Moodle XML string from the list of parsed questions.

    The output conforms to the Moodle XML Question Format:
      - <?xml version="1.0" encoding="UTF-8"?> header
      - <quiz> root element
      - Category header as dummy <question type="category">
      - Each question with required tags: <name>, <questiontext>, <defaultgrade>
      - CDATA sections for all HTML content

    Args:
        grades: dict mapping question type → defaultgrade value.
                If None, defaults to 1.0 for all types.
    Returns:
        (xml_string, QuestionStats)
    """
    if grades is None:
        grades = {t: 1.0 for t in TYPE_WEIGHTS}
    stats = QuestionStats()
    xml_parts: List[str] = []
    xml_parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    xml_parts.append('<quiz>')

    # Category header (spec: dummy question with type="category")
    xml_parts.append('  <question type="category">')
    xml_parts.append(f'    <category><text>$course$/{esc(category)}</text></category>')
    xml_parts.append('  </question>')

    for q in questions:
        num: int = q["num"]
        qtype: str = q["type"]
        data: dict = q["data"]
        key_info = answer_key.get(num, {})
        correct_answer: str = key_info.get("answer", "")
        name = f"P{num}"

        # ── multichoice ──
        # Spec: <answer fraction="100"/"0"> for each choice, <single>, <shuffleanswers>
        if qtype == "multichoice":
            stem = data["stem"]
            options: Dict[str, str] = data["options"]

            correct_letter = None
            if correct_answer:
                ca_clean = correct_answer.strip().lower()
                for letter, opt_text in options.items():
                    opt_clean = opt_text.strip().lower()
                    if (ca_clean == letter.lower() or
                        ca_clean == opt_clean or
                        ca_clean in opt_clean or
                        opt_clean in ca_clean):
                        correct_letter = letter
                        break

            if correct_letter is None:
                correct_letter = "A"
                logger.warning(
                    "Pregunta %d: respuesta '%s' no coincide con opciones, "
                    "defaulting a 'A'.", num, correct_answer[:50],
                )

            xml_parts.append('  <question type="multichoice">')
            xml_parts.append(f'    <name><text>{esc(name)}</text></name>')
            xml_parts.append('    <questiontext format="html">')
            xml_parts.append(f'      <text>{cdata(f"<p>{esc(stem)}</p>")}</text>')
            xml_parts.append('    </questiontext>')
            grade_val = grades.get("multichoice", 1.0)
            xml_parts.append(f'    <defaultgrade>{grade_val}</defaultgrade>')
            xml_parts.append(f'    <penalty>{MULTICHOICE_PENALTY}</penalty>')
            xml_parts.append('    <shuffleanswers>1</shuffleanswers>')
            xml_parts.append('    <single>true</single>')
            xml_parts.append('    <answernumbering>abc</answernumbering>')

            for letter in ["A", "B", "C", "D"]:
                if letter in options:
                    fraction = "100" if letter == correct_letter else "0"
                    feedback = FEEDBACK_CORRECT if letter == correct_letter else FEEDBACK_INCORRECT
                    xml_parts.append(f'    <answer fraction="{fraction}">')
                    xml_parts.append(f'      <text>{cdata(options[letter])}</text>')
                    xml_parts.append(f'      <feedback><text>{cdata(feedback)}</text></feedback>')
                    xml_parts.append('    </answer>')

            xml_parts.append('  </question>')
            stats.multichoice += 1

        # ── truefalse ──
        # Spec: exactly 2 <answer> tags (true + false), fraction 100/0
        elif qtype == "truefalse":
            stem = data["stem"]
            is_true = correct_answer.strip().lower() in ("verdadero", "true", "v")

            xml_parts.append('  <question type="truefalse">')
            xml_parts.append(f'    <name><text>{esc(name)}</text></name>')
            xml_parts.append('    <questiontext format="html">')
            xml_parts.append(f'      <text>{cdata(f"<p>{esc(stem)}</p>")}</text>')
            xml_parts.append('    </questiontext>')
            grade_val = grades.get("truefalse", 1.0)
            xml_parts.append(f'    <defaultgrade>{grade_val}</defaultgrade>')

            if is_true:
                xml_parts.append('    <answer fraction="100">')
                xml_parts.append('      <text>true</text>')
                xml_parts.append(f'      <feedback><text>{cdata(FEEDBACK_CORRECT)}</text></feedback>')
                xml_parts.append('    </answer>')
                xml_parts.append('    <answer fraction="0">')
                xml_parts.append('      <text>false</text>')
                xml_parts.append(f'      <feedback><text>{cdata(FEEDBACK_INCORRECT)}</text></feedback>')
                xml_parts.append('    </answer>')
            else:
                xml_parts.append('    <answer fraction="0">')
                xml_parts.append('      <text>true</text>')
                xml_parts.append(f'      <feedback><text>{cdata(FEEDBACK_INCORRECT)}</text></feedback>')
                xml_parts.append('    </answer>')
                xml_parts.append('    <answer fraction="100">')
                xml_parts.append('      <text>false</text>')
                xml_parts.append(f'      <feedback><text>{cdata(FEEDBACK_CORRECT)}</text></feedback>')
                xml_parts.append('    </answer>')

            xml_parts.append('  </question>')
            stats.truefalse += 1

        # ── matching ──
        # Spec: <subquestion> with <text> + <answer><text>, <shuffleanswers>
        elif qtype == "matching":
            col_a: Dict[str, str] = data.get("col_a", {})
            col_b: Dict[str, str] = data.get("col_b", {})

            pairs_ordered: list[tuple[str, str]] = []

            # Priority 1: Use col_a & col_b directly from data (reflects live user edits in UI)
            if col_a and col_b:
                a_keys = sorted(col_a.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x))
                b_keys = sorted(col_b.keys())
                for idx, a_k in enumerate(a_keys):
                    a_val = col_a[a_k].strip()
                    b_k = b_keys[idx] if idx < len(b_keys) else None
                    b_val = col_b[b_k].strip() if b_k else ""
                    if a_val or b_val:
                        pairs_ordered.append((a_val, b_val))

            # Priority 2: Fallback to parsing key_pairs from correct_answer string
            if not pairs_ordered and correct_answer:
                key_pairs = re.findall(
                    r'\d+\.\s*([^→;\n]+?)\s*→\s*([^;\n]+?)(?=;\s*\d+\.|\s*$)',
                    correct_answer,
                )
                for a_text, b_text in key_pairs:
                    pairs_ordered.append((a_text.strip(), b_text.strip()))
            else:
                # Fallback: zip col_a with col_b in order
                a_vals = [col_a[k] for k in sorted(col_a.keys(), key=lambda x: int(x))]
                b_vals = [col_b[k] for k in sorted(col_b.keys())]
                for a_text, b_text in zip(a_vals, b_vals):
                    pairs_ordered.append((a_text, b_text))

            stem = data.get("stem")
            if not stem:
                stem = DEFAULT_MATCHING_STEM

            xml_parts.append('  <question type="matching">')
            xml_parts.append(f'    <name><text>{esc(name)}</text></name>')
            xml_parts.append('    <questiontext format="html">')
            xml_parts.append(f'      <text>{cdata(f"<p>{esc(stem)}</p>")}</text>')
            xml_parts.append('    </questiontext>')
            grade_val = grades.get("matching", 1.0)
            xml_parts.append(f'    <defaultgrade>{grade_val}</defaultgrade>')
            xml_parts.append('    <shuffleanswers>true</shuffleanswers>')

            for col_a_text, col_b_text in pairs_ordered:
                xml_parts.append('    <subquestion format="html">')
                xml_parts.append(f'      <text>{cdata(col_a_text)}</text>')
                xml_parts.append(f'      <answer><text>{cdata(col_b_text)}</text></answer>')
                xml_parts.append('    </subquestion>')

            xml_parts.append('  </question>')
            stats.matching += 1

        # ── cloze ──
        # Spec: questiontext contains {N:TYPE:...} syntax, no separate <answer> tags
        elif qtype == "cloze":
            raw_text = data["text"]
            cloze_text = convert_cloze_to_moodle(raw_text, num, answer_key)

            xml_parts.append('  <question type="cloze">')
            xml_parts.append(f'    <name><text>{esc(name)}</text></name>')
            xml_parts.append('    <questiontext format="html">')
            xml_parts.append(f'      <text>{cdata(f"<p>{esc(cloze_text)}</p>")}</text>')
            xml_parts.append('    </questiontext>')
            grade_val = grades.get("cloze", 1.0)
            xml_parts.append(f'    <defaultgrade>{grade_val}</defaultgrade>')
            xml_parts.append('  </question>')
            stats.cloze += 1

    xml_parts.append('</quiz>')
    return "\n".join(xml_parts), stats
