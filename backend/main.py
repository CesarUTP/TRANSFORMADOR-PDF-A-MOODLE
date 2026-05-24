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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from lxml import etree

from config import DEFAULT_CATEGORY, DEFAULT_TOTAL_POINTS
from extractor import extract_text_from_pdf, extract_text_from_txt
from formatter import verify_and_format
from parser import parse_answer_key, build_questions
from validator import validate_questions, generate_warnings_report, pre_validate_raw_text
from xml_builder import build_xml, compute_grades

logger = logging.getLogger(__name__)

app = FastAPI(title="PDF → Moodle XML", version="1.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Question-Stats", "X-Was-Reformatted", "Content-Disposition"],
)

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


@app.post("/convert")
async def convert(
    file: UploadFile = File(...),
    category: str = Form(default=DEFAULT_CATEGORY),
    total_points: float = Form(default=DEFAULT_TOTAL_POINTS),
):
    # ── 1. Validate file extension ──────────────────────────────────────
    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()

    if suffix not in (".pdf", ".txt"):
        raise HTTPException(
            status_code=400,
            detail=f"Formato no soportado '{suffix}'. Solo se aceptan archivos .pdf o .txt.",
        )

    # ── 2. Extract text ─────────────────────────────────────────────────
    raw_bytes = await file.read()

    try:
        if suffix == ".pdf":
            full_text = extract_text_from_pdf(raw_bytes)
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
            detail="El archivo no contiene texto legible. Si es un PDF escaneado, se requiere OCR (no soportado).",
        )

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

    # Extraer la clave de respuestas original antes del reformateo para evitar pérdida de preguntas
    original_answer_key = parse_answer_key(full_text)

    # ── 3. Gemini prefiltro: normalizar estructura ──────────────────────
    reformatted_text, was_reformatted = verify_and_format(full_text)

    # ── 4. Parse answer key del texto reformateado ──────────────────────
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

    # ── 6. Validate questions (Modo Estricto) ───────────────────────────
    validation = validate_questions(questions, effective_answer_key, strict=True)

    if not validation.is_valid:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Se detectaron errores de validación antes de generar el XML:",
                "errors": validation.errors
            }
        )

    # Si hay warnings (futuro Modo Tolerante), los registramos
    if validation.warnings:
        report = generate_warnings_report(validation)
        logger.warning(
            "Validación con %d warning(s):\n%s",
            len(validation.warnings), report,
        )

    # ── 7. Compute weighted grades & generate XML ───────────────────────
    grades = compute_grades(questions, total_points)
    xml_content, stats = build_xml(
        questions, effective_answer_key, category=category, grades=grades,
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

    # ── 9. Return as downloadable file ──────────────────────────────────
    stem = Path(filename).stem
    output_filename = f"{stem}.xml"

    stats_header = json.dumps({
        "multichoice": stats.multichoice,
        "truefalse":   stats.truefalse,
        "matching":    stats.matching,
        "cloze":       stats.cloze,
        "total_points": total_points,
        "grades": {
            "multichoice": grades["multichoice"],
            "truefalse":   grades["truefalse"],
            "matching":    grades["matching"],
            "cloze":       grades["cloze"],
        },
    })

    return Response(
        content=xml_content.encode("utf-8"),
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{output_filename}"',
            "X-Question-Stats": stats_header,
            "X-Was-Reformatted": "true" if was_reformatted else "false",
        },
    )
