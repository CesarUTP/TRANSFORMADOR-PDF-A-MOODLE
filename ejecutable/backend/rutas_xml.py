"""
rutas_xml.py — de las preguntas revisadas al Moodle XML.

  POST /api/generate_xml   valida, construye el XML, lo guarda en el historial
                           y lo devuelve como descarga (cabecera X-Question-Stats)
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from lxml import etree
from pydantic import BaseModel, Field

import answer_matching
from database import save_conversion
from validator import validate_questions
from xml_builder import build_xml, compute_grades
from estado_servidor import (
    ERROR_LOG_PATH, _avisos_para_cabecera, _content_disposition, _detalle_tecnico, _nombre_nfc,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Modelos Pydantic para Generación de XML ────────────────────────────────
class GenerateXmlRequest(BaseModel):
    filename: str
    category: str
    # gt=0 y un tope razonable, y allow_inf_nan=False rechaza Infinity/NaN:
    # un total "Infinity" se guardaba en el historial (SQLite lo admite) y
    # /api/history quedaba con ese registro dentro para siempre — el JSON
    # de la respuesta ya no era válido y el docente perdía el historial.
    total_points: float = Field(gt=0, le=100_000, allow_inf_nan=False)
    questions: List[Dict[str, Any]]
    answer_key: Dict[str, Any]
    # Mis materias: a qué materia pertenece el examen (None = «Sin materia») y cómo se llama la actividad.
    materia_id: Optional[int] = None
    actividad: Optional[str] = Field(None, max_length=320)

def validar_para_exportar(questions: List[Dict[str, Any]], parsed_answer_key: Dict[int, Any]) -> None:
    """Lo que debe cumplir lo que llega del editor antes de generar el XML o el PDF (2.1: el PDF
    sale de la misma revisión y rechaza lo mismo, así nunca muestra algo que el XML no aceptaría).
    Lanza HTTPException 422 con la lista de errores."""
    # ── 6.5 Re-validate: el usuario pudo editar libremente en el navegador,
    # así que no podemos confiar en que los datos que llegan aquí sigan
    # cumpliendo el spec Moodle (p. ej. un emparejamiento sin pares, o una
    # opción de selección múltiple vacía). Sin esto, /api/parse podía
    # validar datos correctos y /api/generate_xml igual producir un XML
    # corrupto a partir de ediciones inválidas del usuario.
    # Una pregunta con la clave interna "error" es la que el propio backend
    # marca como omitida en el Modo Tolerante (partition_questions) — el
    # editor nunca la reenvía (esas quedan en skipped_questions, aparte).
    # validate_questions la salta sin revisar su forma (type/data/imágenes),
    # así que aceptarla aquí tal cual dejaría pasar cualquier dato sin
    # validar, viniendo directo de la petición HTTP.
    campos_no_permitidos = [q.get("num", "?") for q in questions if isinstance(q, dict) and "error" in q]
    if campos_no_permitidos:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Se detectaron errores de validación en las preguntas editadas:",
                "errors": [f"Error: la Pregunta {n} trae un campo interno no permitido." for n in campos_no_permitidos],
            },
        )

    validation = validate_questions(questions, parsed_answer_key, strict=True)
    if not validation.is_valid:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Se detectaron errores de validación en las preguntas editadas:",
                "errors": validation.errors,
            },
        )



def _generate_xml_sync(req: GenerateXmlRequest, parsed_answer_key: Dict[int, Any]):
    """
    Todo el trabajo síncrono de /api/generate_xml (validar, construir el
    XML, parsearlo de vuelta para chequear que quedó bien formado, guardar
    en el historial). Corre en threadpool — igual que parse_document en
    /api/parse — para no bloquear el event loop de FastAPI: con un examen
    grande (150 preguntas) este trabajo, hecho directo en la corrutina,
    retrasaba los eventos NDJSON de OTRAS conversiones en curso en
    /api/parse_stream.
    """
    validar_para_exportar(req.questions, parsed_answer_key)

    # ── 7. Compute weighted grades & generate XML ───────────────────────
    grades = compute_grades(req.questions, req.total_points)
    try:
        xml_content, stats = build_xml(
            req.questions, parsed_answer_key, category=req.category, grades=grades,
        )
    except answer_matching.RespuestaNoResuelta as exc:
        # La validación ya rechaza estas preguntas; si llegara alguna aquí (una
        # petición que se saltó la revisión), es un error del contenido, no del
        # servidor: se dice cuál y se pide corregirlo en la revisión.
        raise HTTPException(status_code=422, detail={
            "message": "Se detectaron errores de validación en las preguntas editadas:",
            "errors": [f"Una respuesta no identifica UNA opción de la pregunta: {exc}. Corrígela en la revisión."],
        })

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
    # Junto al XML se guardan las preguntas tal como quedaron en el editor,
    # para que el docente pueda reabrir la revisión desde el Historial.
    editor_json = json.dumps(
        {"questions": req.questions, "answer_key": req.answer_key}, ensure_ascii=False
    )
    # El guardado en el Historial NO puede tumbar la exportación: el XML ya está
    # listo y, si esto fallara, el docente lo perdía con un error 500 (visto en
    # errores.log: «no such table: history»). Si no se pudo guardar se avisa, y
    # el XML se devuelve igual. database.save_conversion ya se recupera solo de
    # una tabla ausente; aquí se cubre lo demás (disco lleno, base bloqueada,
    # permisos).
    aviso_historial = None
    historial_id = None
    try:
        historial_id = save_conversion(
            req.filename, req.category, req.total_points, xml_content, editor_json,
            req.materia_id, " ".join((req.actividad or "").split())[:160] or None,
        )
    except (sqlite3.Error, OSError) as exc:
        logger.exception("No se pudo guardar '%s' en el historial", req.filename)
        aviso_historial = (
            "El XML se generó bien, pero no se pudo guardar en el Historial de esta aplicación "
            f"({type(exc).__name__}). Descárgalo ahora: no podrás reabrirlo desde el Historial."
        )
    return xml_content, stats, grades, aviso_historial, historial_id


@router.post("/api/generate_xml")
async def api_generate_xml(req: GenerateXmlRequest):
    # Convert string keys back to int for answer_key
    try:
        parsed_answer_key = {int(k): v for k, v in req.answer_key.items()}
    except ValueError:
        raise HTTPException(status_code=422, detail="Las claves de answer_key deben ser enteros.")

    req.filename = _nombre_nfc(req.filename)
    try:
        xml_content, stats, grades, aviso_historial, historial_id = await run_in_threadpool(_generate_xml_sync, req, parsed_answer_key)

        # ── 9. Return as downloadable file ──────────────────────────────
        # Un XML de Moodle importado y vuelto a generar no debe llamarse igual que el original
        # (se pisaría al guardarlo en la misma carpeta).
        _origen = Path(req.filename)
        output_filename = f"{_origen.stem}_editado.xml" if _origen.suffix.lower() == ".xml" else f"{_origen.stem}.xml"
        stats_header = json.dumps({
            "multichoice": stats.multichoice,
            "truefalse":   stats.truefalse,
            "matching":    stats.matching,
            "cloze":       stats.cloze,
            "essay":       stats.essay,
            "shortanswer": stats.shortanswer,
            "numerical":   stats.numerical,
            "total_points": req.total_points,
            "escala": stats.escala,
            # Avisos del constructor (texto) y estado del guardado en el Historial.
            "avisos": _avisos_para_cabecera(getattr(stats, "avisos", None)),
            "historial_guardado": aviso_historial is None,
            # El examen guardado (para cambiarle la materia desde la pantalla final).
            "historial_id": historial_id,
            "aviso_historial": aviso_historial,
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
                "Content-Disposition": _content_disposition(output_filename),
                "X-Question-Stats": stats_header,
            },
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        # Cubre TODO el endpoint, también armar la respuesta: antes un fallo
        # ahí salía como 500 sin cuerpo y sin rastro en ningún registro.
        logger.exception("Error inesperado generando el XML de '%s'", req.filename)
        raise HTTPException(status_code=500, detail=(
            "Ocurrió un error inesperado al generar el XML. Tu revisión sigue intacta: vuelve a "
            f"la revisión e inténtalo de nuevo. Si se repite, envía al desarrollador el registro "
            f"«{ERROR_LOG_PATH}». (Detalle técnico: {_detalle_tecnico(exc)})"
        ))
