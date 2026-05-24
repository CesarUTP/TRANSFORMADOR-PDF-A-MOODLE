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

        num = q["num"]
        qtype = q["type"]
        data = q["data"]
        key_info = answer_key.get(num, {})
        correct_answer = key_info.get("answer", "")

        # ── Validación universal: ¿existe en la clave de respuestas? ────────
        if not key_info:
            target.append(
                f"Error: falta la respuesta en la clave para el ítem Pregunta {num}."
            )
            continue  # sin clave no podemos validar más

        # ── Validación universal: ¿tiene respuesta correcta especificada? ──
        if not correct_answer.strip() or correct_answer.strip().upper() == "SIN_RESPUESTA":
            target.append(
                f"Error: la Pregunta {num} ({qtype}) no tiene una respuesta correcta especificada en el examen."
            )
            continue

        # ── Validación universal: campos obligatorios según tipo ────────────
        required = REQUIRED_FIELDS.get(qtype, [])
        for field_name in required:
            if field_name not in data or not data[field_name]:
                target.append(
                    f"Error: falta '{field_name}' en el ítem Pregunta {num} ({qtype})."
                )

        # ── Validaciones específicas por tipo ───────────────────────────────
        if qtype == "multichoice":
            _validate_multichoice(num, data, correct_answer, target)

        elif qtype == "truefalse":
            _validate_truefalse(num, data, correct_answer, target)

        elif qtype == "matching":
            _validate_matching(num, data, correct_answer, target)

        elif qtype == "cloze":
            _validate_cloze(num, data, correct_answer, target)

    logger.info(
        "Validación completada: %d errores, %d warnings.",
        len(result.errors), len(result.warnings),
    )
    return result


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
    - Exactamente una opción debe ser fraction="100"
    - La respuesta de la clave debe coincidir con alguna opción
    """
    options = data.get("options", {})

    # Regla: al menos MIN_MULTICHOICE_OPTIONS opciones
    if len(options) < MIN_MULTICHOICE_OPTIONS:
        target.append(
            f"Error: falta opciones válidas en el ítem Pregunta {num} "
            f"(multichoice). Se encontraron {len(options)}, "
            f"se requieren al menos {MIN_MULTICHOICE_OPTIONS}."
        )

    # Regla: la respuesta de la clave debe coincidir con alguna opción
    if correct_answer and options:
        found = any(
            correct_answer.lower() in opt.lower()
            for opt in options.values()
        )
        if not found:
            target.append(
                f"Error: la respuesta correcta '{correct_answer[:60]}' no coincide "
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
    target: List[str],
) -> None:
    """
    Valida pregunta matching contra el spec Moodle XML:
    - Necesita al menos MIN_MATCHING_PAIRS pares (spec: <subquestion> tags)
    - La clave debe contener pares en formato "1. A → B; 2. C → D"
    - Cada <subquestion> necesita <text> (item) y <answer><text> (respuesta)
    """
    # Validar que la clave contenga pares → (formato requerido por el parser)
    key_pairs = re.findall(
        r'\d+\.\s*([^→;\n]+?)\s*→\s*([^;\n]+?)(?=;\s*\d+\.|\s*$)',
        correct_answer,
    )

    if not key_pairs:
        target.append(
            f"Error: falta pares 'Elemento → Descripción' en la clave del "
            f"ítem Pregunta {num} (matching). Formato esperado: "
            f"'1. Elemento → Descripción; 2. Elemento → Descripción'."
        )
    elif len(key_pairs) < MIN_MATCHING_PAIRS:
        target.append(
            f"Error: se encontraron solo {len(key_pairs)} par(es) en la clave "
            f"del ítem Pregunta {num} (matching). Moodle requiere al menos "
            f"{MIN_MATCHING_PAIRS} pares (<subquestion>)."
        )

    # Validar datos de columnas parseados
    col_a = data.get("col_a", {})
    col_b = data.get("col_b", {})

    if col_a and col_b:
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
        # Verificar si el número de respuestas correctas coincide con la Columna A
        if len(key_pairs) != len(col_a):
            target.append(
                f"Error: el número de respuestas correctas en la clave ({len(key_pairs)}) "
                f"no coincide con los elementos en la Columna A ({len(col_a)}) para la Pregunta {num}."
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
        elif any("SIN_RESPUESTA" in opt.upper() for opt in options):
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
    
    # Comprobar si tiene patrones de numeración de preguntas o la palabra 'pregunta'
    has_questions = "pregunta" in lower_text or "nº" in lower_text or any(f"{i}." in lower_text for i in range(1, 6))
    
    # Comprobar si tiene sección de respuestas o respuestas correctas
    has_answers = "respuestas" in lower_text or "respuesta" in lower_text or "correcta" in lower_text

    if not has_questions:
        raise ValueError("No se encontraron indicios de preguntas en el documento (ej. 'Pregunta N:' o numeraciones).")

    if not has_answers:
        raise ValueError("No se encontraron indicios de la sección de respuestas en el documento (ej. 'RESPUESTAS').")
