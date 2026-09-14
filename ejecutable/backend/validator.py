"""
validator.py — Validación de integridad de preguntas contra el spec Moodle XML.

Implementa dos modos de operación:
  - Modo Estricto:  lanza excepción bloqueante si falta un campo obligatorio.
  - Modo Tolerante: permite generar XML parcial y produce warnings_report.txt.

Reglas validadas (basadas en "Formato Moodle XML.txt"):
  - Toda pregunta REQUIERE <name> y <questiontext>  (tags comunes)
  - multichoice: al menos 2 <answer>, uno con fraction="100"
  - truefalse:   exactamente 2 <answer> (true + false), uno con fraction="100"
  - matching:    al menos 2 <subquestion>, cada uno con <text> y <answer><text>
  - cloze:       <questiontext> contiene sintaxis {N:TYPE:...} con opciones válidas
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any

from config import (
    REQUIRED_FIELDS,
    MIN_MULTICHOICE_OPTIONS,
    MIN_MATCHING_PAIRS,
    MIN_CLOZE_OPTIONS,
)

logger = logging.getLogger(__name__)


# ── Resultado de validación ─────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """Contenedor de errores y warnings producidos por la validación."""
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def total_issues(self) -> int:
        return len(self.errors) + len(self.warnings)


# ── Validador principal ─────────────────────────────────────────────────────

def validate_questions(
    questions: List[Dict[str, Any]],
    answer_key: Dict[int, Dict[str, Any]],
    strict: bool = True,
) -> ValidationResult:
    """
    Valida la integridad de las preguntas parseadas antes de generar XML.

    Args:
        questions:  Lista de dicts {"num": int, "type": str, "data": dict}.
        answer_key: Dict {num: {"type": str, "answer": str}}.
        strict:     True = errores bloqueantes; False = warnings permisivos.

    Returns:
        ValidationResult con errores y/o warnings.
    """
    result = ValidationResult()
    target = result.errors if strict else result.warnings

    # 1. Cruzar la clave de respuestas con las preguntas procesadas para encontrar faltantes o fallidas
    parsed_nums = {q["num"] for q in questions if "error" not in q}
    for num in sorted(answer_key.keys()):
        if num not in parsed_nums:
            # Buscar si el parser dejó un error registrado para este número
            q_err = next((q.get("error") for q in questions if q["num"] == num), None)
            if q_err:
                target.append(f"Error: {q_err}")
            else:
                target.append(f"Error: Pregunta {num} está en la clave de respuestas pero no se encontró su enunciado en el documento.")

    # 2. Validar detalladamente cada pregunta que se parseó sin error crítico previo
    for q in questions:
        if "error" in q:
            continue
        target.extend(_collect_question_errors(q["num"], q["type"], q["data"], answer_key.get(q["num"], {})))

    logger.info(
        "Validación completada: %d errores, %d warnings.",
        len(result.errors), len(result.warnings),
    )
    return result


def _collect_question_errors(
    num: int,
    qtype: str,
    data: Dict[str, Any],
    key_info: Dict[str, Any],
) -> List[str]:
    """
    Corre todas las validaciones de UNA sola pregunta (clave presente,
    respuesta especificada, campos obligatorios, reglas por tipo) y
    devuelve la lista de errores encontrados (vacía si la pregunta está
    bien). Reutilizada tanto por validate_questions (todo-o-nada, para
    /api/generate_xml) como por partition_questions (pregunta por
    pregunta, para /api/parse — ver Modo Tolerante más abajo).
    """
    errors: List[str] = []
    correct_answer = key_info.get("answer", "")

    if not key_info:
        errors.append(f"Error: falta la respuesta en la clave para el ítem Pregunta {num}.")
        return errors

    if not correct_answer.strip() or correct_answer.strip().upper() == "SIN_RESPUESTA":
        errors.append(f"Error: la Pregunta {num} ({qtype}) no tiene una respuesta correcta especificada en el examen.")
        return errors

    required = REQUIRED_FIELDS.get(qtype, [])
    for field_name in required:
        if field_name not in data or not data[field_name]:
            errors.append(f"Error: falta '{field_name}' en el ítem Pregunta {num} ({qtype}).")

    if qtype == "multichoice":
        _validate_multichoice(num, data, correct_answer, errors)
    elif qtype == "truefalse":
        _validate_truefalse(num, data, correct_answer, errors)
    elif qtype == "matching":
        _validate_matching(num, data, correct_answer, key_info.get("pairs", {}), errors)
    elif qtype == "cloze":
        _validate_cloze(num, data, correct_answer, errors)

    return errors


# ── Modo Tolerante ───────────────────────────────────────────────────────────

def partition_questions(
    questions: List[Dict[str, Any]],
    answer_key: Dict[int, Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Separa las preguntas parseadas en (válidas, omitidas) en vez de
    bloquear la conversión completa por una sola pregunta problemática —
    ej. una pregunta de respuesta abierta que el prefiltro de IA no pudo
    encajar en ninguno de los 4 tipos soportados, o una que perdió su
    respuesta correcta en el proceso. El usuario revisa lo válido en el
    editor de siempre, y ve un resumen de lo que se omitió y por qué.

    Returns:
        (preguntas_validas, preguntas_omitidas) — cada omitida es
        {"num": int, "type": str, "reasons": List[str]}.
    """
    valid: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for q in questions:
        num = q["num"]
        if "error" in q:
            skipped.append({
                "num": num, "type": q.get("type", "?"),
                "reasons": [q["error"]], "preview": _extract_preview(q),
            })
            continue

        errors = _collect_question_errors(num, q["type"], q["data"], answer_key.get(num, {}))
        if errors:
            skipped.append({
                "num": num, "type": q["type"],
                "reasons": errors, "preview": _extract_preview(q),
            })
        else:
            valid.append(q)

    logger.info(
        "Modo tolerante: %d pregunta(s) válida(s), %d omitida(s).",
        len(valid), len(skipped),
    )
    return valid, skipped


def _extract_preview(q: Dict[str, Any], max_len: int = 160) -> str:
    """
    Fragmento del enunciado real de una pregunta omitida, para mostrarlo
    en el resumen — identificar una pregunta SOLO por su número no
    alcanza: la IA renumera todo de forma secuencial y limpia (ver REGLA 7
    del SYSTEM_PROMPT), así que ese número no necesariamente coincide con
    el que tenía la pregunta en el documento original y puede confundir
    más de lo que ayuda.
    """
    data = q.get("data") or {}
    text = data.get("stem") or data.get("text") or q.get("raw_text") or ""
    text = " ".join(text.split())  # colapsa saltos de línea/espacios repetidos
    if len(text) > max_len:
        text = text[:max_len].rstrip() + "…"
    return text


# ── Validadores por tipo ────────────────────────────────────────────────────

def _validate_multichoice(
    num: int,
    data: Dict[str, Any],
    correct_answer: str,
    target: List[str],
) -> None:
    """
    Valida pregunta multichoice contra el spec Moodle XML:
    - Necesita al menos 2 opciones (spec: "one <answer> tag for each choice")
    - Al menos una opción debe quedar marcada como correcta
    - Cada respuesta de la clave debe coincidir con alguna opción — la clave
      puede listar MÁS DE UNA respuesta correcta separadas por " | "
      ("selecciona todas las que correspondan"); cada una se valida por
      separado para no rechazar en falso una pregunta de varias respuestas.
    """
    options = data.get("options", {})

    # Regla: al menos MIN_MULTICHOICE_OPTIONS opciones
    if len(options) < MIN_MULTICHOICE_OPTIONS:
        target.append(
            f"Error: falta opciones válidas en el ítem Pregunta {num} "
            f"(multichoice). Se encontraron {len(options)}, "
            f"se requieren al menos {MIN_MULTICHOICE_OPTIONS}."
        )

    # Regla: cada respuesta correcta listada debe coincidir con alguna opción
    if correct_answer and options:
        targets = [t.strip() for t in correct_answer.split('|') if t.strip()]
        for one_target in targets:
            found = any(
                one_target.lower() in opt.lower() or opt.lower() in one_target.lower()
                for opt in options.values()
            )
            if not found:
                target.append(
                    f"Error: la respuesta correcta '{one_target[:60]}' no coincide "
                    f"con ninguna de las opciones disponibles en la Pregunta {num}. "
                    f"Opciones: {list(options.values())}."
                )


def _validate_truefalse(
    num: int,
    data: Dict[str, Any],
    correct_answer: str,
    target: List[str],
) -> None:
    """
    Valida pregunta truefalse contra el spec Moodle XML:
    - Debe tener enunciado (stem)
    - La respuesta debe ser exactamente "Verdadero" o "Falso"
    - El XML generará exactamente 2 <answer>: true (fraction=100/0) y false (fraction=0/100)
    """
    if correct_answer.lower() not in ("verdadero", "falso"):
        target.append(
            f"Error: respuesta '{correct_answer}' inválida para el ítem "
            f"Pregunta {num} (truefalse). Se esperaba 'Verdadero' o 'Falso'."
        )


def _validate_matching(
    num: int,
    data: Dict[str, Any],
    correct_answer: str,
    pairs: Dict[str, str],
    target: List[str],
) -> None:
    """
    Valida pregunta matching contra el spec Moodle XML:
    - Necesita al menos MIN_MATCHING_PAIRS pares (spec: <subquestion> tags)
    - La clave debe contener pares "número-letra" (ej. "1-a; 2-b; 3-c")
    - Cada número y cada letra referenciados deben existir realmente en
      la Columna A / Columna B respectivamente (evita claves corruptas
      que "cuadran en cantidad" pero no corresponden a las columnas reales)
    - Cada <subquestion> necesita <text> (item) y <answer><text> (respuesta)
    """
    col_a = data.get("col_a", {})
    col_b = data.get("col_b", {})

    if not pairs:
        target.append(
            f"Error: no se encontró una clave de respuestas 'número-letra' "
            f"válida para el ítem Pregunta {num} (matching). Formato esperado: "
            f"'1-a; 2-b; 3-c'. Recibido: '{correct_answer[:80]}'."
        )
    elif len(pairs) < MIN_MATCHING_PAIRS:
        target.append(
            f"Error: se encontraron solo {len(pairs)} par(es) en la clave "
            f"del ítem Pregunta {num} (matching). Moodle requiere al menos "
            f"{MIN_MATCHING_PAIRS} pares (<subquestion>)."
        )

    if not col_a or not col_b:
        target.append(
            f"Error: no se pudieron extraer 'Columna A' y 'Columna B' en la "
            f"Pregunta {num} (matching)."
        )
        return

    if len(col_a) < MIN_MATCHING_PAIRS:
        target.append(
            f"Error: Columna A tiene solo {len(col_a)} elemento(s) en "
            f"Pregunta {num}. Se requieren al menos {MIN_MATCHING_PAIRS}."
        )
    if len(col_b) < MIN_MATCHING_PAIRS:
        target.append(
            f"Error: Columna B tiene solo {len(col_b)} elemento(s) en "
            f"Pregunta {num}. Se requieren al menos {MIN_MATCHING_PAIRS}."
        )

    if pairs:
        # Verificar si el número de pares coincide con la Columna A
        if len(pairs) != len(col_a):
            target.append(
                f"Error: el número de pares en la clave ({len(pairs)}) "
                f"no coincide con los elementos en la Columna A ({len(col_a)}) para la Pregunta {num}."
            )
        # Validación semántica: cada número/letra de la clave debe existir de verdad
        for a_num, letter in pairs.items():
            if a_num not in col_a:
                target.append(
                    f"Error: la clave de respuestas de la Pregunta {num} (matching) "
                    f"referencia el elemento '{a_num}' de la Columna A, que no existe."
                )
            if letter not in col_b:
                target.append(
                    f"Error: la clave de respuestas de la Pregunta {num} (matching) "
                    f"referencia la letra '{letter}' de la Columna B, que no existe."
                )


def _validate_cloze(
    num: int,
    data: Dict[str, Any],
    correct_answer: str,
    target: List[str],
) -> None:
    """
    Valida pregunta cloze contra el spec Moodle XML:
    - El questiontext debe contener al menos un espacio [A: opción1 / opción2]
    - Cada espacio debe tener al menos MIN_CLOZE_OPTIONS opciones
    - No deben existir etiquetas vacías {1:MULTICHOICE:}
    - Cada espacio debe tener una respuesta correcta identificada en la clave
      "A. respuesta; B. respuesta" — no solo dentro de los corchetes.
    """
    text = data.get("text", "")

    # Buscar corchetes [X: ...] (formato pre-conversión a Moodle)
    brackets = re.findall(r'\[([A-Za-z]:\s*[^\]]*)\]', text)

    # Caso: ya tiene etiquetas Moodle nativas vacías (error de Gemini)
    if not brackets and "{1:MULTICHOICE:" in text:
        target.append(
            f"Error: se detectó una etiqueta Moodle vacía o inválida "
            f"({{1:MULTICHOICE:}}) en el ítem Pregunta {num} (cloze). "
            f"Asegúrate de que la pregunta incluya sus opciones."
        )
        return

    # Caso: no tiene ningún espacio
    if not brackets:
        target.append(
            f"Error: no se detectaron espacios con opciones '[A: ...]' en "
            f"el ítem Pregunta {num} (cloze). Formato esperado: "
            f"'[A: correcta / incorrecta]'."
        )
        return

    # La clave de respuestas de un cloze documenta CADA espacio por separado
    # ("A. respuesta; B. respuesta"), a diferencia de los demás tipos donde
    # correct_answer es un único valor — así que un espacio sin respuesta
    # (SIN_RESPUESTA marcado solo aquí, no dentro de los corchetes) no lo
    # detecta la comparación de igualdad exacta que hace validate_questions
    # más arriba. Se parsea por separado para no dejarlo pasar en silencio.
    slot_key_answers: Dict[str, List[str]] = {}
    for m in re.finditer(r'([A-Za-z])[\.:]\s*([^;\n]+)', correct_answer):
        parts = [p.strip() for p in m.group(2).split('|') if p.strip()]
        if parts:
            slot_key_answers[m.group(1).upper()] = parts

    # Compatibilidad con el formato legado de un solo espacio sin prefijo de
    # letra en la clave (ej. correct_answer = "vegetal" a secas): si no se
    # detectó ningún par "Letra. respuesta" y la pregunta tiene un único
    # espacio, se usa la clave completa como la respuesta de ese espacio —
    # igual que ya hace convert_cloze_to_moodle en xml_builder.py.
    if not slot_key_answers and len(brackets) == 1 and correct_answer.strip():
        only_letter = re.split(r':\s*', brackets[0].strip(), maxsplit=1)[0].strip().upper()
        slot_key_answers[only_letter] = [correct_answer.strip()]

    # Validar cada espacio individualmente
    for bracket_content in brackets:
        parts = re.split(r':\s*', bracket_content.strip(), maxsplit=1)
        if len(parts) != 2:
            target.append(
                f"Error: formato inválido en espacio '[{bracket_content}]' "
                f"del ítem Pregunta {num} (cloze). Formato esperado: "
                f"'[A: opción1 / opción2]'."
            )
            continue

        slot_letter = parts[0].strip()
        options = [o.strip() for o in parts[1].split('/') if o.strip()]

        if len(options) < MIN_CLOZE_OPTIONS:
            target.append(
                f"Error: el espacio [{slot_letter}] está vacío y no tiene "
                f"opciones para elegir en el ítem Pregunta {num} (cloze)."
            )
            continue

        if any("SIN_RESPUESTA" in opt.upper() for opt in options):
            target.append(
                f"Error: el espacio [{slot_letter}] en la Pregunta {num} (cloze) no tiene una respuesta correcta especificada."
            )
            continue

        slot_answers = slot_key_answers.get(slot_letter.upper())
        if not slot_answers:
            target.append(
                f"Error: no se encontró la respuesta correcta del espacio [{slot_letter}] "
                f"en la clave de respuestas de la Pregunta {num} (cloze). Formato "
                f"esperado en RESPUESTAS: '{slot_letter}. respuesta_correcta'."
            )
        elif any(ans.strip().upper() == "SIN_RESPUESTA" for ans in slot_answers):
            target.append(
                f"Error: el espacio [{slot_letter}] en la Pregunta {num} (cloze) no tiene una respuesta correcta especificada."
            )


# ── Generador de reporte de warnings ────────────────────────────────────────

def generate_warnings_report(result: ValidationResult) -> str:
    """
    Genera el contenido del archivo warnings_report.txt para modo tolerante.

    Formato:
      === REPORTE DE ADVERTENCIAS (MODO TOLERANTE) ===

      ⚠ Error: falta 'stem' en el ítem Pregunta 5 (truefalse).
      ⚠ Error: la respuesta 'xxx' no coincide con ninguna opción en Pregunta 12.

      Total de incidencias: 2
    """
    lines = [
        "=" * 60,
        "  REPORTE DE ADVERTENCIAS (MODO TOLERANTE)",
        "=" * 60,
        "",
    ]

    for w in result.warnings:
        lines.append(f"  ⚠ {w}")

    lines.append("")
    lines.append(f"  Total de incidencias: {len(result.warnings)}")
    lines.append("=" * 60)

    return "\n".join(lines)


def pre_validate_raw_text(text: str) -> None:
    """
    Realiza una validación local previa del texto extraído antes de enviarlo a la API de Gemini.
    
    Verifica que:
      - El texto no esté vacío y tenga una longitud mínima (ej. 100 caracteres).
      - Contenga indicios de preguntas (ej. la palabra 'pregunta' o numeraciones)
      - Contenga indicios de clave de respuestas (ej. 'respuestas' o 'respuesta').
    """
    text_clean = text.strip()
    if len(text_clean) < 100:
        raise ValueError("El texto extraído es demasiado corto para ser un examen válido (mínimo 100 caracteres).")

    lower_text = text_clean.lower()

    # Comprobar si tiene patrones de numeración de preguntas o la palabra 'pregunta'.
    # La numeración puede venir como "1.", "1)", "1-" o "1:" — limitarse a "1."
    # rechazaba exámenes reales y válidos que simplemente usan otro separador
    # (ej. "1) ¿Cuál es...?"), antes incluso de darle la oportunidad a la IA
    # de normalizarlos.
    has_questions = (
        "pregunta" in lower_text
        or "nº" in lower_text
        or re.search(r'(?:^|\n)\s*[1-5]\s*[.\)\-:]', text_clean) is not None
    )
    
    # Comprobar si tiene sección de respuestas o respuestas correctas
    has_answers = "respuestas" in lower_text or "respuesta" in lower_text or "correcta" in lower_text

    if not has_questions:
        raise ValueError("No se encontraron indicios de preguntas en el documento (ej. 'Pregunta N:' o numeraciones).")

    if not has_answers:
        raise ValueError("No se encontraron indicios de la sección de respuestas en el documento (ej. 'RESPUESTAS').")


def estimate_question_count(raw_text: str) -> int:
    """
    Cuenta aproximada (por encima, no exacta) de cuántas preguntas parece
    tener el documento ORIGINAL, antes de pasarlo por el prefiltro de IA —
    cada línea numerada ("1.", "2)", etc.) cuenta como candidato, aunque
    algunas terminen siendo opciones de respuesta y no preguntas reales
    (por eso es un techo, no un número exacto).

    Sirve solo para detectar si el prefiltro de IA se saltó contenido real
    sin avisar (un riesgo real y ya observado: en documentos largos con
    numeración desordenada, el modelo puede procesar bastante menos
    preguntas de las que el documento realmente tiene) — no para bloquear
    nada, solo para poder mostrarle un aviso al usuario.
    """
    matches = re.findall(r'(?:^|\n)\s*\d{1,3}\s*[.\)]\s', raw_text)
    return len(matches)
