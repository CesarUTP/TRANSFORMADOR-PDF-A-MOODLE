"""
rutas_convertir.py — del archivo del docente a las preguntas revisables.

  POST /api/check_special_cases        chequeo previo (sin Gemini)
  POST /api/parse                      conversión de una vez
  POST /api/normalize_with_ai          lectura del documento como imágenes
  POST /api/parse_stream               igual que /api/parse, con progreso NDJSON
  POST /api/normalize_with_ai_stream   igual que normalize_with_ai, con progreso
  POST /api/importar_xml               importa un Moodle XML ya existente al editor (sin IA)

Los cupos, la cancelación y el flujo NDJSON viven en estado_servidor.py.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, File, UploadFile
from fastapi.concurrency import run_in_threadpool

from extractor import pdf_has_embedded_images
from extractor_docx import docx_tiene_imagenes
from importar_xml import importar_xml
from pipeline import parse_document, normalize_document_with_ai
from estado_servidor import _con_cupo, _nombre_nfc, _ndjson_progress_stream

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/check_special_cases")
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
    filename = _nombre_nfc(file.filename) or "upload"
    suffix = Path(filename).suffix.lower()

    if suffix == ".docx":
        # Abrir y recorrer el Word es trabajo síncrono: fuera del event loop.
        return {"has_special_images": await run_in_threadpool(docx_tiene_imagenes, await file.read())}
    if suffix != ".pdf":
        return {"has_special_images": False}

    raw_bytes = await file.read()
    try:
        has_images = await run_in_threadpool(pdf_has_embedded_images, raw_bytes)
    except Exception as exc:
        logger.warning("No se pudo chequear imágenes en '%s': %s", filename, exc)
        return {"has_special_images": False}

    return {"has_special_images": has_images}


@router.post("/api/parse")
async def api_parse(
    file: UploadFile = File(...),
):
    # La lógica completa vive en pipeline.parse_document (compartida con
    # dev/eval.py). Es síncrona y puede tardar (pdfplumber + Gemini, hasta
    # ~2 min con imágenes), así que corre en threadpool para no bloquear
    # el event loop de FastAPI.
    raw_bytes = await file.read()
    return await run_in_threadpool(_con_cupo, parse_document, raw_bytes, _nombre_nfc(file.filename) or "upload")


@router.post("/api/normalize_with_ai")
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
    return await run_in_threadpool(_con_cupo, normalize_document_with_ai, raw_bytes, _nombre_nfc(file.filename) or "upload")


@router.post("/api/parse_stream")
async def api_parse_stream(file: UploadFile = File(...)):
    """Igual que /api/parse, pero informando el avance (ver _ndjson_progress_stream)."""
    raw_bytes = await file.read()
    return _ndjson_progress_stream(parse_document, raw_bytes, _nombre_nfc(file.filename) or "upload")


@router.post("/api/normalize_with_ai_stream")
async def api_normalize_with_ai_stream(file: UploadFile = File(...)):
    """Igual que /api/normalize_with_ai, pero informando el avance."""
    raw_bytes = await file.read()
    return _ndjson_progress_stream(normalize_document_with_ai, raw_bytes, _nombre_nfc(file.filename) or "upload")


@router.post("/api/importar_xml")
async def api_importar_xml(file: UploadFile = File(...)):
    """Abre un Moodle XML existente en el editor. No usa IA ni gasta cuota: lee el XML
    (ver importar_xml.py) y devuelve lo mismo que /api/parse."""
    raw_bytes = await file.read()
    return await run_in_threadpool(importar_xml, raw_bytes, _nombre_nfc(file.filename) or "importado.xml")
