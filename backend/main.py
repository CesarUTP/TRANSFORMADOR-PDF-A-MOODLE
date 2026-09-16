"""
main.py — FastAPI application for PDF → Moodle XML conversion.

Endpoints:
  GET  /         → serves index.html (frontend)
  POST /convert  → multipart upload (.pdf or .txt) → Moodle XML download
"""

import json
import logging
import sys
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from lxml import etree

from config import DEFAULT_CATEGORY, DEFAULT_TOTAL_POINTS
from extractor import (
    extract_text_and_images_from_pdf,
    extract_text_from_pdf,
    extract_text_from_txt,
    pdf_has_embedded_images,
    get_colored_text_pages,
    render_all_pages_as_images,
)
from formatter import verify_and_format
from parser import parse_answer_key, build_questions
from validator import (
    validate_questions,
    partition_questions,
    pre_validate_raw_text,
    estimate_question_count,
)
from xml_builder import build_xml, compute_grades
from database import init_db, save_conversion, get_history_list, get_xml_content, delete_history_item
from pydantic import BaseModel
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

app = FastAPI(title="PDF → Moodle XML", version="1.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # No usamos cookies/sesiones ni cabeceras de credenciales — "*" +
    # allow_credentials=True es una combinación inválida según el spec CORS
    # (los navegadores la rechazan si de verdad se envían credenciales).
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Question-Stats", "X-Was-Reformatted", "Content-Disposition"],
)

@app.on_event("startup")
def startup_event():
    init_db()

# ── Serve frontend static files ─────────────────────────────────────────────
# Works both in development (relative path) and inside a PyInstaller bundle.
def _frontend_dir() -> Path:
    if getattr(sys, "frozen", False):
        # Running as a PyInstaller bundle
        return Path(sys._MEIPASS) / "frontend"
    # Running as normal Python
    return Path(__file__).parent.parent / "frontend"

_fe = _frontend_dir()
if _fe.exists():
    app.mount("/static", StaticFiles(directory=str(_fe)), name="static")

@app.get("/", include_in_schema=False)
async def serve_index():
    index = _frontend_dir() / "index.html"
    return FileResponse(str(index))


@app.post("/api/check_special_cases")
async def api_check_special_cases(
    file: UploadFile = File(...),
):
    """
    Chequeo previo y barato (no llama a Gemini) para avisarle al usuario,
    ANTES de arrancar el procesamiento real, si el PDF trae imágenes
    incrustadas — caso especial (código en captura, marcas de color) que el
    prefiltro de IA no garantiza transcribir al 100%. El frontend usa esto
    para mostrar un disclaimer y dejar que el usuario decida cómo proceder.
    """
    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()

    if suffix != ".pdf":
        return {"has_special_images": False}

    raw_bytes = await file.read()
    try:
        has_images = await run_in_threadpool(pdf_has_embedded_images, raw_bytes)
    except Exception as exc:
        logger.warning("No se pudo chequear imágenes en '%s': %s", filename, exc)
        return {"has_special_images": False}

    return {"has_special_images": has_images}


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


@app.post("/api/parse")
async def api_parse(
    file: UploadFile = File(...),
):
    # ── 1. Validate file extension ──────────────────────────────────────
    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()

    if suffix not in (".pdf", ".txt"):
        raise HTTPException(
            status_code=400,
            detail=f"Formato no soportado '{suffix}'. Solo se aceptan archivos .pdf o .txt.",
        )

    # ── 2. Extract text (+ imágenes de páginas con contenido visual) ─────
    raw_bytes = await file.read()
    page_images: list = []

    try:
        if suffix == ".pdf":
            # Síncrono y puede tardar en PDFs grandes/con imágenes; se
            # ejecuta en threadpool para no bloquear el event loop de
            # FastAPI. Las imágenes son solo de páginas que de verdad
            # tienen una incrustada (código en captura, texto marcado por
            # color) — no se renderiza el documento completo.
            full_text, page_images = await run_in_threadpool(extract_text_and_images_from_pdf, raw_bytes)
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

    # ── 2.1 Aviso informativo (no bloqueante): respuestas marcadas por color ──
    # No es un "caso especial" — el sistema ya sabe interpretarlas — pero se
    # le recomienda al usuario revisarlas a mano por si la IA se equivocó.
    # colored_pages_text también se usa más abajo para marcar INDIVIDUALMENTE
    # las preguntas cuya página de origen tiene esa marca (ver
    # _tag_color_review_hints), en vez de un solo aviso genérico para todo
    # el documento.
    color_marks_notice = None
    colored_pages_text: list = []
    if suffix == ".pdf":
        try:
            colored_pages_text = await run_in_threadpool(get_colored_text_pages, raw_bytes)
            if colored_pages_text:
                color_marks_notice = (
                    "El documento original parece usar color para marcar respuestas "
                    "(por ejemplo texto en rojo). El sistema ya sabe interpretar esta marca, "
                    "pero no es 100% infalible — se recomienda revisar manualmente las "
                    "respuestas marcadas como correctas antes de aprobar, por si hubo algún "
                    "error de normalización."
                )
        except Exception as exc:
            logger.warning("No se pudo chequear texto de color en '%s': %s", filename, exc)

    # ── 2.5 Local Pre-validation ────────────────────────────────────────
    try:
        pre_validate_raw_text(full_text)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Validación previa fallida:",
                "errors": [str(exc)]
            }
        )

    # Techo aproximado de cuántas preguntas parece tener el documento
    # ORIGINAL (antes de la IA) — solo para poder avisar más abajo si el
    # prefiltro terminó devolviendo bastantes menos de las esperadas.
    estimated_question_count = estimate_question_count(full_text)

    # ── 3. Gemini prefiltro: normalizar estructura ──────────────────────
    # verify_and_format es síncrona y puede bloquear varios segundos (llamada
    # HTTP a Gemini, más aún si hay imágenes — se ha visto hasta ~2 min) o
    # hasta 30s en reintentos con time.sleep(); se ejecuta en threadpool
    # para que el event loop de FastAPI siga sirviendo otras peticiones
    # (p. ej. /api/history) mientras tanto.
    reformatted_text, was_reformatted = await run_in_threadpool(verify_and_format, full_text, page_images)

    return _finalize_parse_response(
        filename, full_text, reformatted_text, was_reformatted,
        estimated_question_count, colored_pages_text, color_marks_notice,
    )


def _finalize_parse_response(
    filename: str,
    full_text: str,
    reformatted_text: str,
    was_reformatted: bool,
    estimated_question_count: int,
    colored_pages_text: List[str],
    color_marks_notice: Any,
) -> Dict[str, Any]:
    """
    Cola común de /api/parse y /api/normalize_with_ai: ambos llegan aquí ya
    con el texto reformateado por Gemini (por texto normal o por imágenes
    completas del documento) — de aquí en adelante el procesamiento es
    idéntico sin importar cómo se obtuvo ese texto, así que se comparte en
    vez de duplicarlo.
    """
    # ── 4. Parse answer key del texto reformateado ──────────────────────
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

    # ── 5. Build question list usando el texto reformateado y la clave efectiva ─────────────────
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

    # ── 6. Modo Tolerante: separar preguntas válidas de las que hay que
    # omitir (ej. de respuesta abierta, sin ninguna opción/respuesta que la
    # IA pudiera identificar) en vez de bloquear TODA la conversión por una
    # sola pregunta problemática — el usuario revisa lo válido en el editor
    # de siempre, y ve un resumen de lo que se omitió y por qué.
    valid_questions, skipped_questions = partition_questions(questions, effective_answer_key)

    # Marca individualmente (no un aviso genérico) las preguntas de opción
    # múltiple cuya página de origen tiene texto de color — son las
    # candidatas reales a que la IA se haya saltado una segunda marca en
    # una pregunta de varias respuestas correctas.
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
    # más preguntas de las que se terminaron procesando + omitiendo — señal
    # de que el prefiltro de IA pudo haberse saltado contenido sin avisar.
    processed_total = len(valid_questions) + len(skipped_questions)
    completeness_notice = None
    if estimated_question_count >= 3 and processed_total < estimated_question_count * 0.6:
        completeness_notice = (
            f"El documento original parecía tener alrededor de {estimated_question_count} "
            f"preguntas, pero solo se identificaron {processed_total}. Puede que algunas se "
            f"hayan pasado por alto — revisa el documento original para confirmar que no falte nada."
        )

    # La clave de respuestas que se manda de vuelta se recorta a solo las
    # preguntas válidas: /api/generate_xml vuelve a validar más adelante
    # cruzando questions contra answer_key uno a uno, y con las entradas de
    # las preguntas omitidas todavía ahí (pero sin su pregunta correspondiente
    # en la lista) esa validación las marca como "falta el enunciado" —
    # bloqueando por error justo lo que el modo tolerante ya había filtrado.
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


@app.post("/api/normalize_with_ai")
async def api_normalize_with_ai(
    file: UploadFile = File(...),
):
    """
    Alternativa in-app al flujo externo de "copia este prompt y pégalo en
    tu IA de preferencia" (Guía → Prompt IA): renderiza el documento
    COMPLETO como imágenes y deja que Gemini lo lea visualmente, sin
    depender de que el PDF tenga una capa de texto extraíble. Pensado para
    los 2 casos especiales: PDF con imágenes incrustadas (el usuario elige
    esto en vez de "Continuar de todos modos") y PDF escaneado sin texto
    (hoy bloqueado en /api/parse con "se requiere OCR").

    Reutiliza exactamente el mismo verify_and_format() y la misma cola de
    procesamiento que /api/parse (_finalize_parse_response) — el resultado
    tiene la misma forma, así que el frontend lo muestra en el mismo editor.
    """
    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()

    if suffix != ".pdf":
        raise HTTPException(
            status_code=400,
            detail="Normalizar con IA solo aplica a archivos .pdf (un .txt ya es texto plano).",
        )

    raw_bytes = await file.read()

    try:
        full_text = await run_in_threadpool(extract_text_from_pdf, raw_bytes)
        page_images = await run_in_threadpool(render_all_pages_as_images, raw_bytes)
        colored_pages_text = await run_in_threadpool(get_colored_text_pages, raw_bytes)
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

    color_marks_notice = None
    if colored_pages_text:
        color_marks_notice = (
            "El documento original parece usar color para marcar respuestas "
            "(por ejemplo texto en rojo). El sistema ya sabe interpretar esta marca, "
            "pero no es 100% infalible — se recomienda revisar manualmente las "
            "respuestas marcadas como correctas antes de aprobar, por si hubo algún "
            "error de normalización."
        )

    # Sin pre_validate_raw_text aquí a propósito: esa validación exige
    # indicios de "pregunta"/"respuesta" en el TEXTO extraído, pero en el
    # caso escaneado (la razón de ser de este endpoint) ese texto está
    # vacío por definición — toda la lectura depende de las imágenes.
    estimated_question_count = estimate_question_count(full_text)

    reformatted_text, was_reformatted = await run_in_threadpool(verify_and_format, full_text, page_images)

    return _finalize_parse_response(
        filename, full_text, reformatted_text, was_reformatted,
        estimated_question_count, colored_pages_text, color_marks_notice,
    )


# ── Modelos Pydantic para Generación de XML ────────────────────────────────
class GenerateXmlRequest(BaseModel):
    filename: str
    category: str
    total_points: float
    questions: List[Dict[str, Any]]
    answer_key: Dict[str, Any]

@app.post("/api/generate_xml")
async def api_generate_xml(req: GenerateXmlRequest):
    # Convert string keys back to int for answer_key
    try:
        parsed_answer_key = {int(k): v for k, v in req.answer_key.items()}
    except ValueError:
        raise HTTPException(status_code=422, detail="Las claves de answer_key deben ser enteros.")

    # ── 6.5 Re-validate: el usuario pudo editar libremente en el navegador,
    # así que no podemos confiar en que los datos que llegan aquí sigan
    # cumpliendo el spec Moodle (p. ej. un emparejamiento sin pares, o una
    # opción de selección múltiple vacía). Sin esto, /api/parse podía
    # validar datos correctos y /api/generate_xml igual producir un XML
    # corrupto a partir de ediciones inválidas del usuario.
    validation = validate_questions(req.questions, parsed_answer_key, strict=True)
    if not validation.is_valid:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Se detectaron errores de validación en las preguntas editadas:",
                "errors": validation.errors,
            },
        )

    # ── 7. Compute weighted grades & generate XML ───────────────────────
    grades = compute_grades(req.questions, req.total_points)
    xml_content, stats = build_xml(
        req.questions, parsed_answer_key, category=req.category, grades=grades,
    )

    # ── 8. Validate XML well-formedness ─────────────────────────────────
    try:
        etree.fromstring(xml_content.encode("utf-8"))
    except etree.XMLSyntaxError as exc:
        logger.error("XML generado malformado: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"El XML generado tiene errores de sintaxis: {exc}",
        )

    # ── 8.5 Guardar en historial ─────────────────────────────────────────
    save_conversion(req.filename, req.category, req.total_points, xml_content)

    # ── 9. Return as downloadable file ──────────────────────────────────
    stem = Path(req.filename).stem
    output_filename = f"{stem}.xml"

    stats_header = json.dumps({
        "multichoice": stats.multichoice,
        "truefalse":   stats.truefalse,
        "matching":    stats.matching,
        "cloze":       stats.cloze,
        "total_points": req.total_points,
        "grades": {
            "multichoice": grades.get("multichoice", 1.0),
            "truefalse":   grades.get("truefalse", 1.0),
            "matching":    grades.get("matching", 1.0),
            "cloze":       grades.get("cloze", 1.0),
        },
    })

    return Response(
        content=xml_content.encode("utf-8"),
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{output_filename}"',
            "X-Question-Stats": stats_header,
        },
    )

@app.get("/api/history")
async def api_get_history():
    return get_history_list()

@app.get("/api/history/{record_id}/download")
async def api_download_history(record_id: int):
    record = get_xml_content(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
        
    stem = Path(record["filename"]).stem
    output_filename = f"{stem}.xml"
    
    return Response(
        content=record["xml_content"].encode("utf-8"),
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{output_filename}"',
        },
    )

@app.delete("/api/history/{record_id}")
async def api_delete_history(record_id: int):
    if not delete_history_item(record_id):
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    return {"deleted": True}
