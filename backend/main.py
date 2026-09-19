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
from extractor import pdf_has_embedded_images
from pipeline import parse_document, normalize_document_with_ai
from validator import validate_questions
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


@app.post("/api/parse")
async def api_parse(
    file: UploadFile = File(...),
):
    # La lógica completa vive en pipeline.parse_document (compartida con
    # dev/eval.py). Es síncrona y puede tardar (pdfplumber + Gemini, hasta
    # ~2 min con imágenes), así que corre en threadpool para no bloquear
    # el event loop de FastAPI.
    raw_bytes = await file.read()
    return await run_in_threadpool(parse_document, raw_bytes, file.filename or "upload")


@app.post("/api/normalize_with_ai")
async def api_normalize_with_ai(
    file: UploadFile = File(...),
):
    """
    Alternativa in-app al flujo externo de "copia este prompt y pégalo en
    tu IA de preferencia" (Guía → Prompt IA): lee el documento COMPLETO
    como imágenes (ver pipeline.normalize_document_with_ai). Pensado para
    PDFs con imágenes incrustadas y PDFs escaneados sin capa de texto.
    """
    raw_bytes = await file.read()
    return await run_in_threadpool(normalize_document_with_ai, raw_bytes, file.filename or "upload")


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
        "essay":       stats.essay,
        "shortanswer": stats.shortanswer,
        "numerical":   stats.numerical,
        "total_points": req.total_points,
        "grades": {
            "multichoice": grades.get("multichoice", 1.0),
            "truefalse":   grades.get("truefalse", 1.0),
            "matching":    grades.get("matching", 1.0),
            "cloze":       grades.get("cloze", 1.0),
            "essay":       grades.get("essay", 1.0),
            "shortanswer": grades.get("shortanswer", 1.0),
            "numerical":   grades.get("numerical", 1.0),
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
