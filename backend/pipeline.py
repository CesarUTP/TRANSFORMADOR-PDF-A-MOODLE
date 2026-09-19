"""
pipeline.py — Normalización de un documento subido (PDF/TXT) hasta la
respuesta que consume el editor: {questions, answer_key, ...}.

Vive fuera de main.py para que la MISMA lógica la usen tanto los
endpoints HTTP (/api/parse, /api/normalize_with_ai) como el script de
evaluación (dev/eval.py) — así la evaluación mide exactamente lo que
ejecuta la app, no una copia que se pueda desincronizar.

Todas las funciones son síncronas (pdfplumber y la llamada a Gemini
bloquean); main.py las corre en threadpool.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List

from fastapi import HTTPException

from config import ANNOTATE_COLOR_MARKS, NORMALIZER_MODE
from extractor import (
    extract_pages_text,
    extract_pages_text_with_color_marks,
    get_colored_page_numbers,
    join_pages_with_markers,
    extract_text_and_images_from_pdf,
    extract_text_from_pdf,
    extract_text_from_txt,
    get_colored_text_pages,
    render_all_pages_as_images,
)
from formatter import verify_and_format, extract_structured
from schema_adapter import adapt
from parser import parse_answer_key, build_questions
from validator import (
    partition_questions,
    pre_validate_raw_text,
    estimate_question_count,
)

logger = logging.getLogger(__name__)

COLOR_MARKS_NOTICE = (
    "El documento original parece usar color para marcar respuestas "
    "(por ejemplo texto en rojo). El sistema ya sabe interpretar esta marca, "
    "pero no es 100% infalible — se recomienda revisar manualmente las "
    "respuestas marcadas como correctas antes de aprobar, por si hubo algún "
    "error de normalización."
)

_COLOR_HINT_MIN_LEN = 20  # evita anclar con un enunciado demasiado corto/genérico


def _tag_color_review_hints(valid_questions: List[Dict[str, Any]], colored_pages_text: List[str]) -> None:
    """
    Marca in-place cada pregunta multichoice cuya página de origen tenía
    texto de color, agregando data["color_review_hint"] = True. Se ubica la
    página de origen por coincidencia del ENUNCIADO (no de las opciones:
    muchos exámenes reutilizan el mismo set de opciones A/B/C/D en varias
    preguntas distintas — anclar por opción daba falsos positivos casi
    universales; el enunciado, en cambio, es prácticamente único por
    pregunta). Es un heurístico aproximado, no exacto, ya que el prefiltro
    de IA renumera y reescribe el documento (ver REGLA 7) y no conserva de
    qué página vino cada pregunta. Sirve solo para dirigir la revisión
    manual del usuario, no para bloquear nada, así que un falso positivo
    ocasional no es grave.
    """
    normalized_pages = [" ".join(t.split()).lower() for t in colored_pages_text]

    for q in valid_questions:
        if q.get("type") != "multichoice":
            continue
        stem = (q.get("data") or {}).get("stem", "")
        candidate = " ".join(stem.split()).lower()
        if len(candidate) < _COLOR_HINT_MIN_LEN:
            continue
        if any(candidate in page_text for page_text in normalized_pages):
            q["data"]["color_review_hint"] = True


def parse_document(raw_bytes: bytes, filename: str) -> Dict[str, Any]:
    """Flujo de /api/parse: texto (+ imágenes de páginas con imagen incrustada)."""
    suffix = Path(filename).suffix.lower()
    if suffix not in (".pdf", ".txt"):
        raise HTTPException(
            status_code=400,
            detail=f"Formato no soportado '{suffix}'. Solo se aceptan archivos .pdf o .txt.",
        )

    # ── Extraer texto (+ imágenes de páginas con contenido visual) ─────
    # Las imágenes son solo de páginas que de verdad tienen una incrustada
    # (código en captura, texto marcado por color) — no se renderiza el
    # documento completo.
    page_images: list = []
    try:
        if suffix == ".pdf":
            full_text, page_images = extract_text_and_images_from_pdf(raw_bytes)
        else:
            full_text = extract_text_from_txt(raw_bytes)
    except Exception as exc:
        logger.error("Error extrayendo texto de '%s': %s", filename, exc)
        raise HTTPException(
            status_code=422,
            detail=f"Error al extraer el texto del archivo: {exc}",
        )

    if not full_text.strip():
        raise HTTPException(
            status_code=422,
            detail="El archivo no contiene texto legible.",
        )

    # ── Aviso informativo (no bloqueante): respuestas marcadas por color ──
    # colored_pages_text también se usa para marcar INDIVIDUALMENTE las
    # preguntas cuya página de origen tiene esa marca (ver
    # _tag_color_review_hints), en vez de un solo aviso genérico.
    color_marks_notice = None
    colored_pages_text: list = []
    if suffix == ".pdf":
        try:
            colored_pages_text = get_colored_text_pages(raw_bytes)
            if colored_pages_text:
                color_marks_notice = COLOR_MARKS_NOTICE
        except Exception as exc:
            logger.warning("No se pudo chequear texto de color en '%s': %s", filename, exc)

    # ── Pre-validación local ─────────────────────────────────────────────
    try:
        pre_validate_raw_text(full_text)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": "Validación previa fallida:", "errors": [str(exc)]},
        )

    # Techo aproximado de cuántas preguntas parece tener el documento
    # ORIGINAL (antes de la IA) — solo para poder avisar si el prefiltro
    # terminó devolviendo bastantes menos de las esperadas.
    estimated_question_count = estimate_question_count(full_text)

    # ── Gemini prefiltro: normalizar estructura ──────────────────────────
    if NORMALIZER_MODE == "json":
        model_text = _model_text_json(raw_bytes, colored_pages_text) if suffix == ".pdf" else full_text
        return _finalize_structured(
            filename, extract_structured(model_text, page_images),
            estimated_question_count, colored_pages_text, color_marks_notice,
            _colored_pages(raw_bytes) if suffix == ".pdf" else [],
        )

    model_text = full_text
    if suffix == ".pdf" and ANNOTATE_COLOR_MARKS and colored_pages_text:
        model_text = "\n".join(extract_pages_text_with_color_marks(raw_bytes))
    reformatted_text, was_reformatted = verify_and_format(model_text, page_images)

    return finalize_parse_response(
        filename, full_text, reformatted_text, was_reformatted,
        estimated_question_count, colored_pages_text, color_marks_notice,
    )


def normalize_document_with_ai(raw_bytes: bytes, filename: str) -> Dict[str, Any]:
    """
    Flujo de /api/normalize_with_ai: renderiza el documento COMPLETO como
    imágenes y deja que Gemini lo lea visualmente, sin depender de que el
    PDF tenga una capa de texto extraíble (PDF escaneado, o con contenido
    visual que el modo normal no capturó).
    """
    suffix = Path(filename).suffix.lower()
    if suffix != ".pdf":
        raise HTTPException(
            status_code=400,
            detail="Normalizar con IA solo aplica a archivos .pdf (un .txt ya es texto plano).",
        )

    try:
        full_text = extract_text_from_pdf(raw_bytes)
        page_images = render_all_pages_as_images(raw_bytes)
        colored_pages_text = get_colored_text_pages(raw_bytes)
    except Exception as exc:
        logger.error("Error extrayendo contenido de '%s' para normalizar: %s", filename, exc)
        raise HTTPException(
            status_code=422,
            detail=f"Error al leer el archivo: {exc}",
        )

    if not full_text.strip() and not page_images:
        raise HTTPException(
            status_code=422,
            detail="No se pudo extraer ningún contenido (ni texto ni páginas) del archivo.",
        )

    color_marks_notice = COLOR_MARKS_NOTICE if colored_pages_text else None

    # Sin pre_validate_raw_text aquí a propósito: esa validación exige
    # indicios de "pregunta"/"respuesta" en el TEXTO extraído, pero en el
    # caso escaneado (la razón de ser de este flujo) ese texto está vacío
    # por definición — toda la lectura depende de las imágenes.
    estimated_question_count = estimate_question_count(full_text)

    if NORMALIZER_MODE == "json":
        model_text = _model_text_json(raw_bytes, colored_pages_text)
        return _finalize_structured(
            filename, extract_structured(model_text, page_images),
            estimated_question_count, colored_pages_text, color_marks_notice,
            _colored_pages(raw_bytes),
        )

    reformatted_text, was_reformatted = verify_and_format(full_text, page_images)

    return finalize_parse_response(
        filename, full_text, reformatted_text, was_reformatted,
        estimated_question_count, colored_pages_text, color_marks_notice,
    )


def finalize_parse_response(
    filename: str,
    full_text: str,
    reformatted_text: str,
    was_reformatted: bool,
    estimated_question_count: int,
    colored_pages_text: List[str],
    color_marks_notice: Any,
) -> Dict[str, Any]:
    """
    Cola común de ambos flujos: ya con el texto reformateado por Gemini, de
    aquí en adelante el procesamiento es idéntico sin importar cómo se
    obtuvo ese texto.
    """
    # ── Parse answer key del texto reformateado ──────────────────────────
    original_answer_key = parse_answer_key(full_text)
    answer_key = parse_answer_key(reformatted_text)

    # Combinar ambas claves para tener la lista completa (origen de verdad de lo que el usuario cargó)
    effective_answer_key = {**original_answer_key, **answer_key}

    if not effective_answer_key:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Error de estructura en el examen:",
                "errors": [
                    "No se encontró la sección RESPUESTAS o no pudo parsearse ninguna respuesta.",
                    "Verifica que el archivo contenga la sección 'RESPUESTAS' con el formato correcto."
                ]
            }
        )

    questions = build_questions(reformatted_text, effective_answer_key)

    if not questions:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Error de extracción:",
                "errors": [
                    f"Se encontraron {len(effective_answer_key)} respuestas en la clave pero no se pudo extraer ninguna pregunta del cuerpo del documento.",
                    "Verifica que las preguntas tengan el formato 'Pregunta N:'."
                ]
            }
        )

    return _finalize_common(
        filename, questions, effective_answer_key, was_reformatted,
        estimated_question_count, colored_pages_text, color_marks_notice,
    )


def _model_text_json(raw_bytes: bytes, colored_pages_text: List[str]) -> str:
    """Texto para el modo JSON: por página con "[Página N]", y con las
    marcas de color anotadas si ANNOTATE_COLOR_MARKS está activo."""
    if ANNOTATE_COLOR_MARKS and colored_pages_text:
        return join_pages_with_markers(extract_pages_text_with_color_marks(raw_bytes))
    return join_pages_with_markers(extract_pages_text(raw_bytes))


def _colored_pages(raw_bytes: bytes) -> List[int]:
    try:
        return get_colored_page_numbers(raw_bytes)
    except Exception:  # noqa: BLE001 — solo sirve para un aviso
        return []


def _finalize_structured(
    filename: str,
    payload: Dict[str, Any],
    estimated_question_count: int,
    colored_pages_text: List[str],
    color_marks_notice: Any,
    colored_page_numbers: List[int] = (),
) -> Dict[str, Any]:
    """Modo JSON: la salida del modelo ya viene estructurada; el adaptador
    la deja en la misma forma que produce parser.py en el modo texto."""
    questions, answer_key = adapt(payload)
    # Con la página de origen que informa el modelo, el aviso "revisar marca
    # de color" deja de ser un heurístico por texto: es exacto por página.
    colored = set(colored_page_numbers)
    for q in questions:
        if q["type"] == "multichoice" and q["data"].get("page") in colored:
            q["data"]["color_review_hint"] = True
    if not questions:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Error de extracción:",
                "errors": ["No se identificó ninguna pregunta en el documento."],
            },
        )
    return _finalize_common(
        filename, questions, answer_key, True,
        estimated_question_count, colored_pages_text, color_marks_notice,
    )


def _finalize_common(
    filename: str,
    questions: List[Dict[str, Any]],
    effective_answer_key: Dict[int, Dict[str, Any]],
    was_reformatted: bool,
    estimated_question_count: int,
    colored_pages_text: List[str],
    color_marks_notice: Any,
) -> Dict[str, Any]:
    """Cola compartida por ambos modos: modo tolerante, avisos y recorte de
    la clave a las preguntas válidas."""
    # Modo Tolerante: separar preguntas válidas de las que hay que omitir
    # en vez de bloquear TODA la conversión por una sola pregunta
    # problemática — el usuario revisa lo válido en el editor, y ve un
    # resumen de lo que se omitió y por qué.
    valid_questions, skipped_questions = partition_questions(questions, effective_answer_key)

    if colored_pages_text:
        _tag_color_review_hints(valid_questions, colored_pages_text)

    if not valid_questions:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "No se pudo procesar ninguna pregunta del examen:",
                "errors": [r for sq in skipped_questions for r in sq["reasons"]] or [
                    "Ninguna pregunta del documento coincidió con un tipo soportado (opción múltiple, verdadero/falso, emparejamiento o completar)."
                ],
            }
        )

    # Aviso suave (no bloqueante) si el documento parecía tener bastantes
    # más preguntas de las que se terminaron procesando + omitiendo.
    processed_total = len(valid_questions) + len(skipped_questions)
    completeness_notice = None
    if estimated_question_count >= 3 and processed_total < estimated_question_count * 0.6:
        completeness_notice = (
            f"El documento original parecía tener alrededor de {estimated_question_count} "
            f"preguntas, pero solo se identificaron {processed_total}. Puede que algunas se "
            f"hayan pasado por alto — revisa el documento original para confirmar que no falte nada."
        )

    # La clave que se manda de vuelta se recorta a solo las preguntas
    # válidas: /api/generate_xml vuelve a validar cruzando questions contra
    # answer_key uno a uno, y con las entradas de las omitidas todavía ahí
    # esa validación las marcaría como "falta el enunciado".
    valid_nums = {q["num"] for q in valid_questions}
    trimmed_answer_key = {num: info for num, info in effective_answer_key.items() if num in valid_nums}

    return {
        "filename": filename,
        "questions": valid_questions,
        "answer_key": trimmed_answer_key,
        "was_reformatted": was_reformatted,
        "skipped_questions": skipped_questions,
        "completeness_notice": completeness_notice,
        "color_marks_notice": color_marks_notice,
    }
