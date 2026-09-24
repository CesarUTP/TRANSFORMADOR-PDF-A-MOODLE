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
    TRANSCRIPTION_FAILED_MARKER,
)
from answer_matching import find_cloze_brackets, is_truncated_answer_match, split_answers, split_options

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

    # Marca explícita de REGLA 11: la IA vio una imagen que necesitaba para
    # esta pregunta pero no pudo leerla con confianza (borrosa, cortada,
    # ilegible) — se revisa ANTES que cualquier otra cosa porque, a
    # diferencia de "no tiene respuesta especificada" (que suena a que el
    # documento original no marcó nada), este es un motivo distinto y más
    # accionable: hay que ir a revisar esa imagen a mano.
    stem_or_text = data.get("stem") or data.get("text") or ""
    if TRANSCRIPTION_FAILED_MARKER in stem_or_text:
        errors.append(
            f"Error: la Pregunta {num} ({qtype}) contiene una imagen que la IA no "
            f"pudo transcribir con confianza (borrosa, cortada o ilegible). Revisa "
            f"el documento original y complétala manualmente si quieres incluirla."
        )
        return errors

    if not key_info:
        errors.append(f"Error: falta la respuesta en la clave para el ítem Pregunta {num}.")
        return errors

    # essay (ensayo) se califica manualmente en Moodle — nunca tiene una
    # "respuesta correcta" que validar, así que se salta por completo el
    # chequeo universal de abajo, sin importar qué texto (o ninguno) haya
    # quedado en la clave para esta pregunta.
    if qtype != "essay":
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
    elif qtype == "numerical":
        _validate_numerical(num, correct_answer, errors)

    return errors


# ── Modo Tolerante ───────────────────────────────────────────────────────────

# Patrones de errores que son ÚNICAMENTE sobre la respuesta correcta (falta,
# no coincide, no es válida) — no sobre el enunciado, las opciones o las
# columnas, que ya se parsearon bien si la pregunta llegó hasta aquí sin
# "error" de estructura. Cuando TODOS los errores de una pregunta calzan con
# alguno de estos patrones, el frontend puede ofrecer "añadirla con lo que
# ya se extrajo" en vez de obligar al usuario a reconstruirla desde cero —
# solo falta que marque/escriba la respuesta correcta.
_ANSWER_ONLY_PATTERNS = [
    r"no tiene una respuesta correcta especificada",
    r"falta la respuesta en la clave",
    r"no coincide con ninguna de las opciones disponibles",
    r"respuesta '.*' inválida.*Verdadero.*Falso",
    r"no es un número válido",
    r"no se encontró una clave de respuestas 'número-letra' válida",
    r"se encontraron solo \d+ par\(es\) en la clave",
    r"el número de pares en la clave .* no coincide con los elementos en la Columna A",
    r"referencia el elemento '.*' de la Columna A, que no existe",
    r"referencia la letra '.*' de la Columna B, que no existe",
    r"no se encontró la respuesta correcta del espacio",
    r"el espacio \[.*\] en la Pregunta \d+ \(cloze\) no tiene una respuesta correcta especificada",
]


def _is_answer_only_issue(errors: List[str]) -> bool:
    return bool(errors) and all(
        any(re.search(p, e) for p in _ANSWER_ONLY_PATTERNS) for e in errors
    )


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
            entry = {
                "num": num, "type": q["type"],
                "reasons": errors, "preview": _extract_preview(q),
            }
            # Si el enunciado/opciones/columnas ya se parsearon bien y lo
            # único que falla es la respuesta, se manda esa data completa
            # para que el usuario pueda "rescatar" la pregunta en el editor
            # con un clic, en vez de reconstruirla desde cero a mano.
            if _is_answer_only_issue(errors):
                entry["recoverable_data"] = q["data"]
            skipped.append(entry)
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
    text = text.replace(TRANSCRIPTION_FAILED_MARKER, "").strip()
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

    # Regla: ninguna opción puede quedar con texto vacío (ej. "A. \nB. algo"
    # — una letra sin contenido después, típico de un corte al copiar el
    # documento) — el conteo de arriba no lo detecta porque la letra sí
    # cuenta como opción, solo que sin texto.
    for letter, opt_text in options.items():
        if not opt_text.strip():
            target.append(
                f"Error: la opción '{letter}' de la Pregunta {num} "
                f"(multichoice) no tiene texto."
            )

    # Regla: cada respuesta correcta listada debe coincidir con alguna opción
    if correct_answer and options:
        targets = split_answers(correct_answer)
        for one_target in targets:
            found = any(
                one_target.lower() in opt.lower() or opt.lower() in one_target.lower()
                for opt in options.values()
            )
            if not found:
                # Antes de rechazarla, revisa si es un caso de respuesta
                # cortada a mitad de palabra (ver is_truncated_answer_match)
                # — solo se acepta si coincide con EXACTAMENTE una opción,
                # para no arriesgar una coincidencia ambigua.
                prefix_matches = [
                    opt for opt in options.values()
                    if is_truncated_answer_match(one_target.lower(), opt.lower())
                ]
                found = len(prefix_matches) == 1
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

    # Regla: ningún elemento de las columnas puede quedar con texto vacío
    # (ej. "3.\n4. algo" — un número/letra sin contenido después) — el
    # conteo de arriba no lo detecta porque el número/letra sí cuenta como
    # elemento, solo que sin texto.
    for a_num, item_text in col_a.items():
        if not item_text.strip():
            target.append(
                f"Error: el elemento '{a_num}' de la Columna A en la "
                f"Pregunta {num} (matching) no tiene texto."
            )
    for letter, item_text in col_b.items():
        if not item_text.strip():
            target.append(
                f"Error: el elemento '{letter}' de la Columna B en la "
                f"Pregunta {num} (matching) no tiene texto."
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

    # Buscar corchetes [X: ...] (formato pre-conversión a Moodle). Balanceados:
    # un "[0]" dentro de una opción (código, ej. "arr[0]") no cierra el
    # espacio a mitad de camino (ver find_cloze_brackets).
    brackets = find_cloze_brackets(text)

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
        parts = split_answers(m.group(2))
        if parts:
            slot_key_answers[m.group(1).upper()] = parts

    # Compatibilidad con el formato legado de un solo espacio sin prefijo de
    # letra en la clave (ej. correct_answer = "vegetal" a secas): si no se
    # detectó ningún par "Letra. respuesta" y la pregunta tiene un único
    # espacio, se usa la clave completa como la respuesta de ese espacio —
    # igual que ya hace convert_cloze_to_moodle en xml_builder.py.
    if not slot_key_answers and len(brackets) == 1 and correct_answer.strip():
        only_letter = brackets[0][2].upper()
        slot_key_answers[only_letter] = [correct_answer.strip()]

    # Validar cada espacio individualmente
    for _start, _end, slot_letter, options_raw in brackets:
        options = split_options(options_raw)

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


def _validate_numerical(
    num: int,
    correct_answer: str,
    target: List[str],
) -> None:
    """
    Valida pregunta numerical contra el spec Moodle XML:
    - La respuesta debe poder interpretarse como un número (Moodle exige un
      valor numérico real en el <answer>, no texto libre ni un número
      escrito con palabras).
    """
    normalized = correct_answer.strip().replace(',', '.')
    try:
        float(normalized)
    except ValueError:
        target.append(
            f"Error: la respuesta '{correct_answer[:60]}' de la Pregunta {num} "
            f"(numerical) no es un número válido."
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
    Validación local previa del texto extraído, antes de enviarlo a Gemini.

    Solo descarta lo obvio: un documento vacío o casi sin texto. Ya NO se
    buscan "indicios de preguntas" (numeración, la palabra "pregunta",
    signos "¿?"): cada regla así rechazaba exámenes reales antes de que la
    IA los viera — preguntas sin número (samples/parcial 2.pdf, exportado
    de un formulario), sin signos de interrogación ("Mencione…",
    "Seleccione…", "Complete: …") o una clave de respuestas sin la palabra
    "respuesta" (samples/golden/s04). Decidir si el documento es una prueba
    lo hace la IA (NOT_AN_EXAM_SENTINEL), que sí entiende el contenido; el
    costo de mandarle un documento que no lo es resulta despreciable.
    """
    if len(text.strip()) < 100:
        raise ValueError("El texto extraído es demasiado corto para ser un examen válido (mínimo 100 caracteres).")


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


def estimate_expected_questions(raw_text: str) -> int:
    """
    Estimación del número de preguntas ANTES de llamar a la IA, para que la
    pantalla de carga pueda decir "pregunta 12 de ~40" y calcular el tiempo
    restante. A diferencia de estimate_question_count (un techo, que cuenta
    cualquier línea numerada), busca la secuencia 1, 2, 3… N más larga de
    números de pregunta: una clave al final repite los mismos números (no
    los duplica) y un número suelto (un año, una opción numerada) no
    extiende la secuencia. Sin numeración, cuenta los enunciados que
    terminan en "?". Es aproximada a propósito (se muestra con "~"):
    exacta en 14 de 16 exámenes del set de regresión, y el mayor desvío
    medido fue de ±30 %.
    """
    nums = {int(n) for n in re.findall(r"(?im)^\s*pregunta\s*(\d{1,3})\b", raw_text)}
    nums |= {int(n) for n in re.findall(r"(?m)^\s*(\d{1,3})\s*[.):\-]", raw_text)}
    k = 0
    while k + 1 in nums:
        k += 1
    lines = [ln.strip() for ln in raw_text.splitlines()]
    question_marks = sum(1 for ln in lines if ln.endswith("?"))
    if not k:
        return question_marks
    # Preguntas SIN número intercaladas entre las numeradas (medido en
    # Computación: 27 numeradas + 6 sueltas tras la 13, y la pantalla
    # decía "de ~27" hasta que llegaba a 33). Un "?" cuenta como pregunta
    # aparte solo si la pregunta numerada anterior ya se cerró con su
    # propio "?"; si no, es la segunda línea de ese mismo enunciado. Una
    # opción rotulada ("A. ¿Cómo…") abre su propio bloque por la misma
    # razón: su "?" en la línea siguiente no es una pregunta nueva.
    numbered = re.compile(r"(?i)^(?:pregunta\s*\d{1,3}\b|\d{1,3}\s*[.):\-]|[a-z]\s*[.)]\s)")
    extra, closed = 0, True
    for ln in lines:
        if numbered.match(ln):
            closed = ln.endswith("?")
        elif ln.endswith("?"):
            if closed:
                extra += 1
            closed = True
    return max(k + extra, question_marks)
