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

from config import ENRICH_PDF_TEXT, MISSING_API_KEY_MESSAGE, NORMALIZER_MODE, NORMALIZER_MODE_AI
from credenciales import get_api_key
from extractor import (
    MAX_IMAGE_PAGES,
    DocumentoDemasiadoGrande,
    comprobar_paginas,
    extract_pages_text,
    extract_pages_enriched_and_tables,
    get_colored_pages,
    join_pages_with_markers,
    extract_text_and_images_from_pdf,
    extract_text_from_pdf,
    extract_text_from_txt,
    render_all_pages_as_images,
)
from extractor_docx import DocxInvalido, leer_docx
from formatter import verify_and_format, extract_structured, extract_missing
from imagenes import asignar_imagenes, candidatas_omitidas_numeradas, extraer_imagenes_pdf
from schema_adapter import adapt
from mark_resolver import resolve_answer_marks, resolve_table_marks, resolve_tf_marks
from parser import parse_answer_key, build_questions
from validator import (
    partition_questions,
    pre_validate_raw_text,
    estimate_notice_count,
    estimate_expected_questions,
)

logger = logging.getLogger(__name__)

# Aviso genérico cuando el PDF tiene texto en color pero todavía no se sabe
# (o no se pudo determinar) si ese color marca respuestas. _marks_notice lo
# reemplaza por uno concreto cuando las marcas se resolvieron en código.
COLOR_MARKS_NOTICE = "Hay marcas de color que no se pudieron leer. Revisa las preguntas con «revisar marca»."

# Un PDF escaneado no tiene capa de texto: ni el color ni ninguna otra marca se
# puede leer en código, solo la ve el modelo en la imagen. Medido (dev/eval x10,
# marcas en rojo contrafácticas): devolvió lo que él cree correcto en 8,7 de 9
# preguntas en vez de lo que el docente marcó. El aviso lo dice sin rodeos.
SCANNED_MARKS_NOTICE = (
    "Documento escaneado: si las respuestas están marcadas por color u otra marca, la IA las lee "
    "de la imagen y puede reemplazarlas por lo que ella cree correcto. Revisa TODAS las respuestas "
    "antes de aprobar."
)

# Nombre de la marca en el aviso: cualquier color es simplemente "color".
_MARK_LABELS = {"resaltado": "resaltado", "subrayado": "subrayado", "negrita": "negrita", "mixta": "marcas"}


def _marks_notice(mark: Any, applied: int, n_table: int, n_uncertain: int,
                  fallback: Any, n_tf: int = 0) -> Any:
    """Aviso corto cuando las respuestas salieron de marcas del documento
    (color, resaltado, subrayado, negrita o X en un cuadro). applied y
    n_table cuentan las preguntas que llegan al editor con la respuesta
    leída de la marca; n_uncertain no se usa en el texto (esas preguntas ya
    llevan su propia etiqueta «revisar marca»)."""
    kinds = []
    if mark and applied:
        kinds.append(_MARK_LABELS.get(mark, "color"))
    if n_table:
        kinds.append("cuadro con X")
    if n_tf:
        kinds.append("marca en verdadero/falso")
    if not kinds:
        return fallback
    return f"Respuestas identificadas por {' y '.join(kinds)}. Revísalas antes de aprobar."


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


def _comprobar_entrada(raw_bytes: bytes, suffix: str) -> None:
    """Antes de leer el documento (lo más caro después de Gemini): sin
    clave de la API no hay conversión posible, y un PDF con demasiadas
    páginas se rechaza sin procesarlo."""
    if not get_api_key():
        raise HTTPException(status_code=503, detail=MISSING_API_KEY_MESSAGE)
    if suffix == ".pdf":
        try:
            comprobar_paginas(raw_bytes)
        except DocumentoDemasiadoGrande as exc:
            raise HTTPException(status_code=413, detail=str(exc))
        except Exception:  # noqa: BLE001 — un PDF dañado lo informa la extracción, como siempre
            pass


def parse_document(raw_bytes: bytes, filename: str, progress: ProgressCallback = None) -> Dict[str, Any]:
    """Flujo de /api/parse: texto (+ imágenes de páginas con imagen incrustada)."""
    suffix = Path(filename).suffix.lower()
    if suffix not in (".pdf", ".txt", ".docx"):
        raise HTTPException(
            status_code=400,
            detail=f"Formato no soportado '{suffix}'. Se aceptan archivos .pdf, .docx (Word) o .txt.",
        )
    _comprobar_entrada(raw_bytes, suffix)

    # ── Extraer texto (+ imágenes de páginas con contenido visual) ─────
    # Las imágenes son solo de páginas que de verdad tienen una incrustada
    # (código en captura, texto marcado por color) — no se renderiza el
    # documento completo.
    _emit(progress, type="stage", key="extract", message="Leyendo el documento…")
    page_images: list = []
    # Imágenes de las preguntas, con el texto que las precede: después de la
    # IA se asignan a su pregunta y llegan a Moodle (ver imagenes.py).
    imagenes_preguntas = None
    docx = None
    try:
        if suffix == ".pdf":
            full_text, page_images = extract_text_and_images_from_pdf(raw_bytes)
            try:
                imagenes_preguntas = extraer_imagenes_pdf(raw_bytes)
            except Exception as exc:  # noqa: BLE001 — sin imágenes, la conversión sigue igual
                logger.warning("No se pudieron extraer las imágenes de '%s': %s", filename, exc)
        elif suffix == ".docx":
            docx = leer_docx(raw_bytes)
            full_text = docx.texto_plano
            imagenes_preguntas = docx.ubicaciones
            # Las mismas imágenes van a la IA (código en captura, gráficos).
            page_images = [im.imagen for im in docx.ubicaciones.imagenes[:MAX_IMAGE_PAGES]]
        else:
            full_text = extract_text_from_txt(raw_bytes)
    except DocxInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc))
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
    # colored_page_numbers se calcula aquí mismo (mismo pdfplumber.open())
    # y se reutiliza más abajo en el modo JSON — antes se recalculaba con
    # una segunda pasada por todo el PDF (_colored_pages) más adelante.
    color_marks_notice = None
    colored_pages_text: list = []
    colored_page_numbers: List[int] = []
    if suffix == ".pdf":
        try:
            colored_page_numbers, colored_pages_text = get_colored_pages(raw_bytes)
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

    # Cuántas preguntas parece tener el documento ORIGINAL (antes de la IA)
    # — solo para poder avisar si el prefiltro terminó devolviendo bastantes
    # menos de las esperadas.
    estimated_question_count = estimate_notice_count(full_text)

    # ── Gemini prefiltro: normalizar estructura ──────────────────────────
    if suffix == ".pdf":
        marks = _deterministic_marks(raw_bytes)
    elif docx is not None:
        # Word ya trae sus marcas y tablas: mismo formato que un PDF de una página.
        marks = ([docx.texto_enriquecido], docx.tablas)
    else:
        marks = None

    expected = estimate_expected_questions(full_text)
    _emit(progress, type="stage", key="ai", mode=NORMALIZER_MODE, expected=expected,
          images=len(page_images), message="La IA está ordenando las preguntas…")
    on_ai = _ai_progress(progress, expected)

    if NORMALIZER_MODE == "json":
        if suffix == ".pdf":
            model_text = _model_text_json(raw_bytes, marks)
        elif docx is not None:
            model_text = join_pages_with_markers([docx.texto_enriquecido])
        else:
            model_text = full_text
        payload = extract_structured(model_text, page_images, progress=on_ai, on_retry=_ai_retry(progress),
                                   permitir_reintento_calidad=bool(colored_pages_text))
        payload = _completar_omitidas(payload, imagenes_preguntas, page_images, _ai_retry(progress))
        _emit(progress, type="stage", key="review", message="Revisando respuestas y marcas del documento…")
        return _finalize_structured(
            filename, payload,
            estimated_question_count, colored_pages_text, color_marks_notice,
            colored_page_numbers, marks, imagenes_preguntas,
        )

    model_text = "\n".join(marks[0]) if marks else full_text
    reformatted_text, was_reformatted = verify_and_format(model_text, page_images, progress=on_ai, on_retry=_ai_retry(progress),
                                   permitir_reintento_calidad=bool(colored_pages_text))
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
    _comprobar_entrada(raw_bytes, suffix)

    _emit(progress, type="stage", key="extract", message="Preparando las páginas del documento…")
    try:
        full_text = extract_text_from_pdf(raw_bytes)
        page_images = render_all_pages_as_images(raw_bytes)
        colored_page_numbers, colored_pages_text = get_colored_pages(raw_bytes)
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

    if not full_text.strip():
        color_marks_notice = SCANNED_MARKS_NOTICE
    else:
        color_marks_notice = COLOR_MARKS_NOTICE if colored_pages_text else None

    # Sin pre_validate_raw_text aquí a propósito: esa validación exige
    # indicios de "pregunta"/"respuesta" en el TEXTO extraído, pero en el
    # caso escaneado (la razón de ser de este flujo) ese texto está vacío
    # por definición — toda la lectura depende de las imágenes.
    estimated_question_count = estimate_notice_count(full_text)

    marks = _deterministic_marks(raw_bytes)
    # En un escaneado no hay texto del que estimar cuántas preguntas vienen:
    # expected=0 y la pantalla muestra solo el avance, sin "de ~N".
    expected = estimate_expected_questions(full_text) if full_text.strip() else 0
    _emit(progress, type="stage", key="ai", mode=NORMALIZER_MODE_AI, expected=expected,
          images=len(page_images), message="La IA está leyendo las páginas del documento…")
    on_ai = _ai_progress(progress, expected)

    if NORMALIZER_MODE_AI == "json":
        model_text = _model_text_json(raw_bytes, marks)
        payload = extract_structured(model_text, page_images, progress=on_ai, on_retry=_ai_retry(progress),
                                   permitir_reintento_calidad=bool(colored_pages_text))
        _emit(progress, type="stage", key="review", message="Revisando respuestas y marcas del documento…")
        return _finalize_structured(
            filename, payload,
            estimated_question_count, colored_pages_text, color_marks_notice,
            colored_page_numbers, marks,
        )

    reformatted_text, was_reformatted = verify_and_format(full_text, page_images, progress=on_ai, on_retry=_ai_retry(progress),
                                   permitir_reintento_calidad=bool(colored_pages_text))
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
        return extract_pages_enriched_and_tables(raw_bytes)
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


# Cuántas preguntas omitidas hace falta detectar para intentar
# completarlas con una llamada dirigida (ver _completar_omitidas). Con
# más que esto, en la práctica el detector se está confundiendo con
# opciones numeradas o con la columna de un emparejamiento (probado con
# 3 exámenes reales sin ninguna omisión real: dio 9 "candidatas" en cada
# uno), no con omisiones de verdad — mejor no arriesgar una llamada de
# más y dejar la recuperación manual de siempre ("preguntas no
# incluidas" en el editor) como única red de seguridad, igual que si
# esta función no existiera.
MAX_OMITIDAS_A_COMPLETAR = 3


def _completar_omitidas(payload: Dict[str, Any], imagenes_preguntas, page_images, on_retry) -> Dict[str, Any]:
    """
    Antes de adaptar la respuesta de la IA: revisa en código (sin gastar
    otra llamada) si hay preguntas NUMERADAS del documento que la IA se
    saltó por completo (ver imagenes.candidatas_omitidas_numeradas) y, si
    son pocas, le pide a la IA SOLO esas en una llamada pequeña y las
    inserta en su lugar — mucho más barato que repetir la conversión
    entera, y ataca el fallo real más común observado en la práctica (la
    IA omite una pregunta que es solo una imagen con un enunciado corto).

    Es "mejor esfuerzo" de punta a punta: cualquier problema (sin
    candidatas, demasiadas, la detección falla, o la llamada de la IA no
    ayuda) deja `payload` intacto y la conversión sigue exactamente como
    si esta función no existiera — el aviso de "preguntas no incluidas"
    del editor sigue cubriendo lo que quede sin resolver.
    """
    if not imagenes_preguntas or not getattr(imagenes_preguntas, "lineas", None):
        return payload
    preguntas_raw = payload.get("preguntas") or []
    if not preguntas_raw:
        return payload
    # "data" con options/col_a/col_b (no solo el enunciado): el detector
    # necesita comparar contra las opciones YA devueltas para no confundir
    # una pregunta de verdad omitida con una opción numerada de la
    # pregunta anterior (ver el comentario en candidatas_omitidas_numeradas).
    def _liviana(p: Dict[str, Any]) -> Dict[str, Any]:
        opciones = {str(k): o.get("texto", "") for k, o in enumerate(p.get("opciones") or [])}
        izq = {str(k + 1): v for k, v in enumerate(p.get("items_izquierda") or [])}
        der = {chr(97 + k): v for k, v in enumerate(p.get("items_derecha") or [])}
        return {"stem": p.get("enunciado") or "", "options": opciones, "col_a": izq, "col_b": der}
    livianas = [{"num": i, "data": _liviana(p)} for i, p in enumerate(preguntas_raw, 1)]
    try:
        candidatas = candidatas_omitidas_numeradas(livianas, imagenes_preguntas, max_candidatas=MAX_OMITIDAS_A_COMPLETAR)
    except Exception as exc:  # noqa: BLE001 — nunca debe romper la conversión
        logger.warning("No se pudieron revisar preguntas omitidas: %s", exc)
        return payload
    if not (1 <= len(candidatas) <= MAX_OMITIDAS_A_COMPLETAR):
        return payload

    logger.info("Posibles preguntas omitidas por la IA: %d. Pidiendo solo esas…", len(candidatas))
    nuevas = extract_missing([c["texto"] for c in candidatas], page_images, on_retry=on_retry)
    if not nuevas:
        return payload

    # Cada una se inserta justo después de la pregunta que la precede (la
    # misma que ya estaba en el documento), con un "orden" propio a mitad
    # de camino hacia la siguiente — no hace falta tocar el de las demás.
    ordenes = [p.get("orden") or 0 for p in preguntas_raw]
    for candidata, nueva in zip(candidatas, nuevas):
        despues_de = candidata["despues_de"]
        if despues_de and 1 <= despues_de <= len(preguntas_raw):
            anterior_orden = preguntas_raw[despues_de - 1].get("orden") or despues_de
        else:
            anterior_orden = 0
        posteriores = [o for o in ordenes if o > anterior_orden]
        siguiente_orden = min(posteriores) if posteriores else anterior_orden + 1
        nueva["orden"] = (anterior_orden + siguiente_orden) / 2
        preguntas_raw.append(nueva)
        ordenes.append(nueva["orden"])
    payload["preguntas"] = preguntas_raw
    return payload


def _model_text_json(raw_bytes: bytes, marks) -> str:
    """Texto para el modo JSON: por página con "[Página N]", y enriquecido
    (color y tablas) si ENRICH_PDF_TEXT está activo."""
    if marks:
        return join_pages_with_markers(marks[0])
    return join_pages_with_markers(extract_pages_text(raw_bytes))


def _finalize_structured(
    filename: str,
    payload: Dict[str, Any],
    estimated_question_count: int,
    colored_pages_text: List[str],
    color_marks_notice: Any,
    colored_page_numbers: List[int] = (),
    marks=None,
    imagenes_preguntas=None,
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
        imagenes_preguntas,
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
    imagenes_preguntas=None,
) -> Dict[str, Any]:
    """Cola compartida por ambos modos: marcas resueltas en código, modo
    tolerante, avisos y recorte de la clave a las preguntas válidas."""
    mark_result: Dict[str, Any] = {"mark": None, "applied": 0, "changed": 0}
    n_table = 0
    n_tf = 0
    if marks:
        pages, tables = marks
        # Siempre, no solo con texto en color: resaltado, subrayado y
        # negrita también son marcas. resolve_answer_marks decide si el
        # documento de verdad marca respuestas así (ver su docstring).
        mark_result = resolve_answer_marks(questions, effective_answer_key, pages)
        n_table = resolve_table_marks(questions, effective_answer_key, tables) if tables else 0
        n_tf = resolve_tf_marks(questions, effective_answer_key, pages)
        if mark_result["applied"] or n_table or n_tf:
            logger.info("Marcas resueltas en código: %d por marca (%s), %d por tabla, %d en verdadero/falso.",
                        mark_result["applied"], mark_result["mark"], n_table, n_tf)

    # Modo Tolerante: separar preguntas válidas de las que hay que omitir
    # en vez de bloquear TODA la conversión por una sola pregunta
    # problemática — el usuario revisa lo válido en el editor, y ve un
    # resumen de lo que se omitió y por qué.
    # Imágenes: se ubican con TODAS las preguntas (también las que se van a
    # omitir), para que la de una omitida no caiga en la anterior.
    # Siempre se llama: además quita la marca interna _comparte_imagen de la IA.
    omitidas_por_ia: List[Dict[str, Any]] = []
    n_img = asignar_imagenes(questions, imagenes_preguntas, omitidas_por_ia)
    if imagenes_preguntas and imagenes_preguntas.imagenes:
        logger.info("Imágenes asignadas a preguntas: %d de %d.", n_img, len(imagenes_preguntas.imagenes))

    valid_questions, skipped_questions = partition_questions(questions, effective_answer_key)
    # Preguntas con imagen que la IA no devolvió: se ofrecen para rescatar.
    skipped_questions.extend(omitidas_por_ia)

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
        sum(1 for q in from_marks if q["type"] == "truefalse"),
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
