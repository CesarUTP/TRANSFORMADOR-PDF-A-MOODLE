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
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException

from config import ENRICH_PDF_TEXT, NORMALIZER_MODE, NORMALIZER_MODE_AI
from extractor import (
    extract_pages_text,
    extract_pages_text_enriched,
    extract_tables,
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
from mark_resolver import resolve_answer_marks, resolve_table_marks
from parser import parse_answer_key, build_questions
from validator import (
    partition_questions,
    pre_validate_raw_text,
    estimate_question_count,
    estimate_expected_questions,
)

logger = logging.getLogger(__name__)

# Aviso genérico cuando el PDF tiene texto en color pero todavía no se sabe
# (o no se pudo determinar) si ese color marca respuestas. _marks_notice lo
# reemplaza por uno concreto cuando las marcas se resolvieron en código.
COLOR_MARKS_NOTICE = (
    "El documento tiene texto en color que no se pudo leer como marca de "
    "respuesta. Revisa las preguntas con «revisar marca»."
)

# Cómo se nombra cada marca en el aviso ("leídas del texto en rojo").
_MARK_LABELS = {
    "resaltado": "del resaltado",
    "subrayado": "del subrayado",
    "negrita": "de la negrita",
}


def _marks_notice(mark: Any, applied: int, n_table: int, n_uncertain: int,
                  fallback: Any) -> Any:
    """Aviso corto de dónde salieron las respuestas cuando el documento las
    marca (color, resaltado, subrayado, negrita o X en un cuadro). applied y
    n_table cuentan las preguntas que llegan al editor con la respuesta
    leída de la marca."""
    tables = f"{n_table} emparejamiento{'s' if n_table != 1 else ''} desde un cuadro con X"
    if mark and applied:
        label = _MARK_LABELS.get(mark, f"del texto en {mark}")
        head = f"Respuestas leídas {label} ({applied} pregunta{'s' if applied != 1 else ''})"
        head += f" y {tables}." if n_table else "."
    elif n_table:
        head = f"Respuestas leídas de un cuadro con X ({n_table} emparejamiento{'s' if n_table != 1 else ''})."
    else:
        return fallback
    tail = "Revísalas antes de aprobar" + (", sobre todo las marcadas «revisar marca»." if n_uncertain else ".")
    return f"{head} {tail}"


_COLOR_HINT_MIN_LEN = 20  # evita anclar con un enunciado demasiado corto/genérico

# Recibe eventos de avance para la pantalla de carga (ver main.py, los
# endpoints *_stream). Nunca es obligatorio: sin él, el flujo es idéntico.
ProgressCallback = Optional[Callable[[Dict[str, Any]], None]]


def _emit(progress: ProgressCallback, **event: Any) -> None:
    if progress is None:
        return
    try:
        progress(event)
    except Exception:  # noqa: BLE001 — un aviso de progreso nunca debe romper la conversión
        logger.debug("No se pudo emitir un evento de progreso", exc_info=True)


def _ai_progress(progress: ProgressCallback, expected: int):
    """Adapta el conteo de preguntas que reporta formatter al evento que
    consume la pantalla de carga."""
    if progress is None:
        return None
    return lambda done: _emit(progress, type="progress", done=done, expected=expected)


def _ai_retry(progress: ProgressCallback):
    """Aviso de "esperando y reintentando" (Google saturado, límite por
    minuto): la pantalla lo muestra para que no parezca que se colgó."""
    if progress is None:
        return None
    return lambda message: _emit(progress, type="stage", key="retry", message=message)


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


def parse_document(raw_bytes: bytes, filename: str, progress: ProgressCallback = None) -> Dict[str, Any]:
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
    _emit(progress, type="stage", key="extract", message="Leyendo el documento…")
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
    marks = _deterministic_marks(raw_bytes) if suffix == ".pdf" else None

    expected = estimate_expected_questions(full_text)
    _emit(progress, type="stage", key="ai", mode=NORMALIZER_MODE, expected=expected,
          images=len(page_images), message="La IA está ordenando las preguntas…")
    on_ai = _ai_progress(progress, expected)

    if NORMALIZER_MODE == "json":
        model_text = _model_text_json(raw_bytes, marks) if suffix == ".pdf" else full_text
        payload = extract_structured(model_text, page_images, progress=on_ai, on_retry=_ai_retry(progress))
        _emit(progress, type="stage", key="review", message="Revisando respuestas y marcas del documento…")
        return _finalize_structured(
            filename, payload,
            estimated_question_count, colored_pages_text, color_marks_notice,
            _colored_pages(raw_bytes) if suffix == ".pdf" else [], marks,
        )

    model_text = "\n".join(marks[0]) if marks else full_text
    reformatted_text, was_reformatted = verify_and_format(model_text, page_images, progress=on_ai, on_retry=_ai_retry(progress))
    _emit(progress, type="stage", key="review", message="Revisando respuestas y marcas del documento…")

    return finalize_parse_response(
        filename, full_text, reformatted_text, was_reformatted,
        estimated_question_count, colored_pages_text, color_marks_notice, marks,
    )


def normalize_document_with_ai(raw_bytes: bytes, filename: str, progress: ProgressCallback = None) -> Dict[str, Any]:
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

    _emit(progress, type="stage", key="extract", message="Preparando las páginas del documento…")
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

    marks = _deterministic_marks(raw_bytes)
    # En un escaneado no hay texto del que estimar cuántas preguntas vienen:
    # expected=0 y la pantalla muestra solo el avance, sin "de ~N".
    expected = estimate_expected_questions(full_text) if full_text.strip() else 0
    _emit(progress, type="stage", key="ai", mode=NORMALIZER_MODE_AI, expected=expected,
          images=len(page_images), message="La IA está leyendo las páginas del documento…")
    on_ai = _ai_progress(progress, expected)

    if NORMALIZER_MODE_AI == "json":
        model_text = _model_text_json(raw_bytes, marks)
        payload = extract_structured(model_text, page_images, progress=on_ai, on_retry=_ai_retry(progress))
        _emit(progress, type="stage", key="review", message="Revisando respuestas y marcas del documento…")
        return _finalize_structured(
            filename, payload,
            estimated_question_count, colored_pages_text, color_marks_notice,
            _colored_pages(raw_bytes), marks,
        )

    reformatted_text, was_reformatted = verify_and_format(full_text, page_images, progress=on_ai, on_retry=_ai_retry(progress))
    _emit(progress, type="stage", key="review", message="Revisando respuestas y marcas del documento…")

    return finalize_parse_response(
        filename, full_text, reformatted_text, was_reformatted,
        estimated_question_count, colored_pages_text, color_marks_notice, marks,
    )


def _deterministic_marks(raw_bytes: bytes):
    """(páginas enriquecidas, tablas) si ENRICH_PDF_TEXT está activo, o
    None. Se calcula una vez y sirve para el texto que va al modelo y para
    resolver las marcas en código después (mark_resolver)."""
    if not ENRICH_PDF_TEXT:
        return None
    try:
        return extract_pages_text_enriched(raw_bytes), extract_tables(raw_bytes)
    except Exception as exc:  # noqa: BLE001 — sin enriquecer, el flujo sigue igual que antes
        logger.warning("No se pudo enriquecer el texto del PDF: %s", exc)
        return None


def finalize_parse_response(
    filename: str,
    full_text: str,
    reformatted_text: str,
    was_reformatted: bool,
    estimated_question_count: int,
    colored_pages_text: List[str],
    color_marks_notice: Any,
    marks=None,
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
        estimated_question_count, colored_pages_text, color_marks_notice, marks,
    )


def _model_text_json(raw_bytes: bytes, marks) -> str:
    """Texto para el modo JSON: por página con "[Página N]", y enriquecido
    (color y tablas) si ENRICH_PDF_TEXT está activo."""
    if marks:
        return join_pages_with_markers(marks[0])
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
    marks=None,
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
        estimated_question_count, colored_pages_text, color_marks_notice, marks,
    )


def _finalize_common(
    filename: str,
    questions: List[Dict[str, Any]],
    effective_answer_key: Dict[int, Dict[str, Any]],
    was_reformatted: bool,
    estimated_question_count: int,
    colored_pages_text: List[str],
    color_marks_notice: Any,
    marks=None,
) -> Dict[str, Any]:
    """Cola compartida por ambos modos: marcas resueltas en código, modo
    tolerante, avisos y recorte de la clave a las preguntas válidas."""
    mark_result: Dict[str, Any] = {"mark": None, "applied": 0, "changed": 0}
    n_table = 0
    if marks:
        pages, tables = marks
        # Siempre, no solo con texto en color: resaltado, subrayado y
        # negrita también son marcas. resolve_answer_marks decide si el
        # documento de verdad marca respuestas así (ver su docstring).
        mark_result = resolve_answer_marks(questions, effective_answer_key, pages)
        n_table = resolve_table_marks(questions, effective_answer_key, tables) if tables else 0
        if mark_result["applied"] or n_table:
            logger.info("Marcas resueltas en código: %d por marca (%s), %d por tabla.",
                        mark_result["applied"], mark_result["mark"], n_table)

    # Modo Tolerante: separar preguntas válidas de las que hay que omitir
    # en vez de bloquear TODA la conversión por una sola pregunta
    # problemática — el usuario revisa lo válido en el editor, y ve un
    # resumen de lo que se omitió y por qué.
    valid_questions, skipped_questions = partition_questions(questions, effective_answer_key)

    if colored_pages_text:
        _tag_color_review_hints(valid_questions, colored_pages_text)
    # Una respuesta leída de la marca en código no necesita "revisar marca":
    # el aviso queda solo para las que la IA tuvo que interpretar.
    for q in valid_questions:
        if q["data"].get("answer_from_marks"):
            q["data"].pop("color_review_hint", None)
    n_uncertain = sum(1 for q in valid_questions if q["data"].get("color_review_hint"))
    from_marks = [q for q in valid_questions if q["data"].get("answer_from_marks")]
    color_marks_notice = _marks_notice(
        mark_result["mark"],
        sum(1 for q in from_marks if q["type"] == "multichoice"),
        sum(1 for q in from_marks if q["type"] == "matching"),
        n_uncertain, color_marks_notice,
    )

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
