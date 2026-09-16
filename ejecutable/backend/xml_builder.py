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
from answer_matching import is_truncated_answer_match

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


def strip_accents(s: str) -> str:
    return (s.replace('á', 'a').replace('é', 'e').replace('í', 'i')
             .replace('ó', 'o').replace('ú', 'u')
             .replace('Á', 'A').replace('É', 'E').replace('Í', 'I')
             .replace('Ó', 'O').replace('Ú', 'U')
             .replace('ñ', 'n').replace('Ñ', 'N'))


def convert_cloze_to_moodle(cloze_text: str, q_num: int, answer_key: Dict[int, dict]) -> str:
    """
    Convert [A: correct_option / option2 / option3] brackets to
    Moodle {1:MULTICHOICE_S:=correct~opt2~opt3} syntax.
    Handles multiple embedded gaps (A, B, C...) dynamically.

    Uses the "_S" (shuffled) variant deliberately: plain MULTICHOICE inside
    a Cloze question ignores the quiz's "shuffle within questions" setting
    and always shows options in the authored order — a well-known Moodle
    behavior (see MDL-10971). MULTICHOICE_S is the variant that actually
    responds to that setting, while still defaulting to unshuffled when the
    teacher leaves shuffling off, so this is a strict improvement with no
    downside for anyone who doesn't want shuffling.
    """

    def escape_cloze_syntax(s: str) -> str:
        """Escape Moodle's own Cloze delimiter characters (~ # { } and the
        backslash itself) so a literal occurrence in an option's text isn't
        misread as a syntax separator — e.g. an option like "50~60" would
        otherwise be parsed as two separate options."""
        return (s.replace('\\', '\\\\')
                 .replace('~', '\\~')
                 .replace('#', '\\#')
                 .replace('{', '\\{')
                 .replace('}', '\\}'))

    key_info = answer_key.get(q_num, {})
    raw_key_ans = str(key_info.get("answer", ""))

    # Parse slot answers if present (e.g., "A. respuesta A; B. respuesta B").
    # A slot can have MORE THAN ONE correct answer, joined with " | "
    # (e.g. "A. opt1 | opt3") — that's how the app's own Cloze editor marks
    # a "select several correct options" blank; a normal single-answer slot
    # is just a one-item list, so this stays fully backward compatible.
    slot_answers: Dict[str, List[str]] = {}
    for m in re.finditer(r'([A-Za-z])[\.:]\s*([^;\n]+)', raw_key_ans):
        parts = [p.strip() for p in m.group(2).split('|') if p.strip()]
        if parts:
            slot_answers[m.group(1).upper()] = parts

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

        # Determine which option(s) are correct for this slot — usually one,
        # but a "select several" slot can mark more than one.
        correct_indices: List[int] = []
        for target_ans in slot_answers.get(letter, []):
            target_ans = target_ans.strip()
            if not target_ans:
                continue
            match_idx = None
            for idx, opt in enumerate(options):
                if target_ans.lower() == opt.lower():
                    match_idx = idx
                    break
            if match_idx is None:
                for idx, opt in enumerate(options):
                    if target_ans.lower() in opt.lower() or opt.lower() in target_ans.lower():
                        match_idx = idx
                        break
            if match_idx is not None and match_idx not in correct_indices:
                correct_indices.append(match_idx)

        if not correct_indices and raw_key_ans:
            # Legacy fallback: check if raw_key_ans matches any option in this bracket
            for idx, opt in enumerate(options):
                if opt.lower() in raw_key_ans.lower() or raw_key_ans.lower() in opt.lower():
                    correct_indices.append(idx)
                    break

        if not correct_indices:
            correct_indices = [0]  # default to first option, same safety net as before

        moodle_options = [
            f"={escape_cloze_syntax(strip_accents(opt))}" if i in correct_indices else escape_cloze_syntax(strip_accents(opt))
            for i, opt in enumerate(options)
        ]
        slot_num = str(ord(letter) - ord('A') + 1) if 'A' <= letter <= 'Z' else "1"
        # Un solo "=" -> selección única (MULTICHOICE_S, radio/desplegable).
        # Dos o más -> varias respuestas correctas a la vez (MULTIRESPONSE_S,
        # casillas). Moodle reparte el 100% automáticamente entre las
        # marcadas con "=", no hace falta calcular porcentajes aquí.
        qtype_name = "MULTIRESPONSE_S" if len(correct_indices) > 1 else "MULTICHOICE_S"
        return f"{{{slot_num}:{qtype_name}:{'~'.join(moodle_options)}}}"

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

    # El banco de preguntas de Moodle no conserva el orden del archivo al
    # importar — a menudo re-lista las preguntas ordenadas alfabéticamente
    # por nombre. Sin relleno de ceros, "P10" y "P11" ordenan alfabéticamente
    # ANTES que "P2" (comportamiento documentado y muy reportado por
    # profesores). Rellenar con ceros según la cantidad de preguntas del
    # examen (P01, P02... P10) hace que el orden alfabético coincida con el
    # numérico sin importar cuántas preguntas tenga el examen.
    name_width = len(str(max((q["num"] for q in questions), default=1)))

    for q in questions:
        num: int = q["num"]
        qtype: str = q["type"]
        data: dict = q["data"]
        key_info = answer_key.get(num, {})
        correct_answer: str = key_info.get("answer", "")
        name = f"P{num:0{name_width}d}"

        # Puntaje: el docente puede fijar un valor propio por pregunta desde
        # el editor (ya no todas las preguntas de un tipo valen lo mismo a
        # la fuerza — necesario sobre todo para Ensayo/Respuesta Corta,
        # donde el peso "genérico por tipo" no tiene forma de acertar).
        # Si no llega (payload viejo o pregunta sin tocar), cae al reparto
        # por peso de tipo de siempre — nunca falta un <defaultgrade>.
        q_points = q.get("points")
        grade_val = q_points if isinstance(q_points, (int, float)) and q_points > 0 else grades.get(qtype, 1.0)

        # ── multichoice ──
        # Spec: <answer fraction="100"/"0"> for each choice, <single>, <shuffleanswers>
        if qtype == "multichoice":
            stem = data["stem"]
            options: Dict[str, str] = data["options"]

            # correct_answer puede listar MÁS DE UNA respuesta correcta,
            # separadas por " | " (pregunta de "selecciona todas las que
            # correspondan"). El caso normal de una sola respuesta es
            # simplemente una lista de un elemento, así que el comportamiento
            # de siempre queda intacto.
            correct_letters: List[str] = []
            for target in [t.strip() for t in correct_answer.split('|') if t.strip()]:
                ca_clean = target.lower()
                match_letter = None
                # Priority 1: exact match (letter or full option text). Checked
                # across ALL options before any fuzzy fallback, so an early
                # substring false-positive can't shadow the real exact match
                # that happens to sit in a later option.
                for letter, opt_text in options.items():
                    opt_clean = opt_text.strip().lower()
                    if ca_clean == letter.lower() or ca_clean == opt_clean:
                        match_letter = letter
                        break
                # Priority 2: fuzzy substring match, only as a last resort —
                # e.g. Gemini truncated/paraphrased the option text slightly.
                if match_letter is None:
                    for letter, opt_text in options.items():
                        opt_clean = opt_text.strip().lower()
                        if ca_clean in opt_clean or opt_clean in ca_clean:
                            match_letter = letter
                            break
                # Priority 3: mismo salvavidas que validator.py para una
                # respuesta cortada a mitad de palabra — solo se acepta si
                # coincide con EXACTAMENTE una opción (evita adivinar entre
                # varias). Sin esto, una pregunta que pasó validación
                # gracias a este mismo salvavidas podía llegar aquí y caer
                # en el default de abajo, marcando la opción equivocada.
                if match_letter is None:
                    prefix_matches = [
                        letter for letter, opt_text in options.items()
                        if is_truncated_answer_match(ca_clean, opt_text.strip().lower())
                    ]
                    if len(prefix_matches) == 1:
                        match_letter = prefix_matches[0]
                if match_letter is not None and match_letter not in correct_letters:
                    correct_letters.append(match_letter)

            if not correct_letters:
                correct_letters = ["A"]
                logger.warning(
                    "Pregunta %d: respuesta '%s' no coincide con opciones, "
                    "defaulting a 'A'.", num, correct_answer[:50],
                )

            is_single = len(correct_letters) == 1

            xml_parts.append('  <question type="multichoice">')
            xml_parts.append(f'    <name><text>{esc(name)}</text></name>')
            xml_parts.append('    <questiontext format="html">')
            xml_parts.append(f'      <text>{cdata(f"<p>{esc(stem)}</p>")}</text>')
            xml_parts.append('    </questiontext>')
            xml_parts.append(f'    <defaultgrade>{grade_val}</defaultgrade>')
            xml_parts.append(f'    <penalty>{MULTICHOICE_PENALTY}</penalty>')
            xml_parts.append('    <shuffleanswers>1</shuffleanswers>')
            xml_parts.append(f'    <single>{"true" if is_single else "false"}</single>')
            xml_parts.append('    <answernumbering>abc</answernumbering>')

            # Con varias respuestas correctas, Moodle sólo suma el puntaje
            # total si los fraction positivos de las correctas suman 100 —
            # se reparte parejo entre ellas (2 correctas -> 50% c/u, etc.),
            # igual que ya hacemos para "varias respuestas" en Cloze.
            correct_fraction = round(100.0 / len(correct_letters), 5) if not is_single else 100

            # Iterar dinámicamente sobre las opciones encontradas (no limitado a
            # A-D): una pregunta con opción E o más ya no se descarta en silencio.
            for letter in sorted(options.keys()):
                is_correct = letter in correct_letters
                fraction = correct_fraction if is_correct else 0
                feedback = FEEDBACK_CORRECT if is_correct else FEEDBACK_INCORRECT
                xml_parts.append(f'    <answer fraction="{fraction}">')
                xml_parts.append(f'      <text>{cdata(esc(options[letter]))}</text>')
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
            pairs_map: Dict[str, str] = key_info.get("pairs", {})

            pairs_ordered: list[tuple[str, str]] = []
            a_keys = sorted(col_a.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x))

            # Priority 1: use the explicit número→letra answer key, so each Columna A
            # item is matched to its ACTUAL correct Columna B item (not just by position).
            if pairs_map:
                for a_k in a_keys:
                    letter = pairs_map.get(str(a_k), "").strip().lower()
                    a_val = col_a[a_k].strip()
                    b_val = col_b.get(letter, "").strip()
                    if a_val and b_val:
                        pairs_ordered.append((a_val, b_val))
                    else:
                        logger.warning(
                            "Pregunta %d (matching): sin correspondencia para el "
                            "elemento %s de la Columna A (letra '%s' no encontrada "
                            "en la Columna B).", num, a_k, letter,
                        )

            # Fallback: no reliable número→letra key was found — assume the
            # documented order 1-a, 2-b, 3-c... (better than dropping the question).
            if not pairs_ordered:
                b_keys = sorted(col_b.keys())
                for idx, a_k in enumerate(a_keys):
                    a_val = col_a[a_k].strip()
                    b_k = b_keys[idx] if idx < len(b_keys) else None
                    b_val = col_b[b_k].strip() if b_k else ""
                    if a_val or b_val:
                        pairs_ordered.append((a_val, b_val))
                if pairs_ordered:
                    logger.warning(
                        "Pregunta %d (matching): no se encontró una clave de "
                        "respuestas 'número-letra' válida; se usó el orden "
                        "secuencial 1-a, 2-b, 3-c... por defecto.", num,
                    )

            stem = data.get("stem")
            if not stem:
                stem = DEFAULT_MATCHING_STEM

            xml_parts.append('  <question type="matching">')
            xml_parts.append(f'    <name><text>{esc(name)}</text></name>')
            xml_parts.append('    <questiontext format="html">')
            xml_parts.append(f'      <text>{cdata(f"<p>{esc(stem)}</p>")}</text>')
            xml_parts.append('    </questiontext>')
            xml_parts.append(f'    <defaultgrade>{grade_val}</defaultgrade>')
            xml_parts.append('    <shuffleanswers>true</shuffleanswers>')

            for col_a_text, col_b_text in pairs_ordered:
                xml_parts.append('    <subquestion format="html">')
                xml_parts.append(f'      <text>{cdata(esc(col_a_text))}</text>')
                xml_parts.append(f'      <answer><text>{cdata(esc(col_b_text))}</text></answer>')
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
            xml_parts.append(f'    <defaultgrade>{grade_val}</defaultgrade>')
            xml_parts.append('  </question>')
            stats.cloze += 1

        # ── essay ──
        # Spec: sin respuesta real ni grade que calificar — el docente
        # califica manualmente en Moodle.
        elif qtype == "essay":
            stem = data["stem"]

            xml_parts.append('  <question type="essay">')
            xml_parts.append(f'    <name><text>{esc(name)}</text></name>')
            xml_parts.append('    <questiontext format="html">')
            xml_parts.append(f'      <text>{cdata(f"<p>{esc(stem)}</p>")}</text>')
            xml_parts.append('    </questiontext>')
            xml_parts.append(f'    <defaultgrade>{grade_val}</defaultgrade>')
            xml_parts.append('    <answer fraction="0">')
            xml_parts.append('      <text></text>')
            xml_parts.append('    </answer>')
            xml_parts.append('  </question>')
            stats.essay += 1

        # ── shortanswer ──
        # Spec: <answer> con el texto esperado; <usecase>0</usecase> para no
        # exigir coincidencia exacta de mayúsculas/minúsculas.
        elif qtype == "shortanswer":
            stem = data["stem"]

            xml_parts.append('  <question type="shortanswer">')
            xml_parts.append(f'    <name><text>{esc(name)}</text></name>')
            xml_parts.append('    <questiontext format="html">')
            xml_parts.append(f'      <text>{cdata(f"<p>{esc(stem)}</p>")}</text>')
            xml_parts.append('    </questiontext>')
            xml_parts.append(f'    <defaultgrade>{grade_val}</defaultgrade>')
            xml_parts.append('    <usecase>0</usecase>')
            xml_parts.append('    <answer fraction="100">')
            xml_parts.append(f'      <text>{cdata(esc(correct_answer))}</text>')
            xml_parts.append(f'      <feedback><text>{cdata(FEEDBACK_CORRECT)}</text></feedback>')
            xml_parts.append('    </answer>')

            # Moodle NO ignora tildes automáticamente (<usecase> solo afecta
            # mayúsculas/minúsculas) — un estudiante que escriba la misma
            # respuesta sin tilde ("fotosintesis") quedaría marcado como
            # incorrecto frente a "Fotosíntesis". Se agrega la variante sin
            # tildes como segunda respuesta válida, con el mismo puntaje —
            # la forma recomendada por la propia documentación de Moodle
            # para aceptar más de una grafía de la misma respuesta.
            unaccented = strip_accents(correct_answer)
            if unaccented != correct_answer:
                xml_parts.append('    <answer fraction="100">')
                xml_parts.append(f'      <text>{cdata(esc(unaccented))}</text>')
                xml_parts.append(f'      <feedback><text>{cdata(FEEDBACK_CORRECT)}</text></feedback>')
                xml_parts.append('    </answer>')

            xml_parts.append('  </question>')
            stats.shortanswer += 1

        # ── numerical ──
        # Spec: <answer> con un valor numérico; <tolerance> (0 = coincidencia exacta).
        elif qtype == "numerical":
            stem = data["stem"]

            xml_parts.append('  <question type="numerical">')
            xml_parts.append(f'    <name><text>{esc(name)}</text></name>')
            xml_parts.append('    <questiontext format="html">')
            xml_parts.append(f'      <text>{cdata(f"<p>{esc(stem)}</p>")}</text>')
            xml_parts.append('    </questiontext>')
            xml_parts.append(f'    <defaultgrade>{grade_val}</defaultgrade>')
            xml_parts.append('    <answer fraction="100">')
            xml_parts.append(f'      <text>{esc(correct_answer.strip())}</text>')
            xml_parts.append('      <tolerance>0</tolerance>')
            xml_parts.append(f'      <feedback><text>{cdata(FEEDBACK_CORRECT)}</text></feedback>')
            xml_parts.append('    </answer>')
            xml_parts.append('  </question>')
            stats.numerical += 1

    xml_parts.append('</quiz>')
    return "\n".join(xml_parts), stats
