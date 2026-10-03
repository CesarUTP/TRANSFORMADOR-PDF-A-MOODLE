"""
rutas_historial.py — el Historial de conversiones guardadas en este equipo.

  GET    /api/history
  GET    /api/history/{record_id}/download
  GET    /api/history/{record_id}/editor
  DELETE /api/history/{record_id}
"""

import json
import logging
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from database import get_history_list, get_xml_content, delete_history_item, get_editor_data
from estado_servidor import ERROR_LOG_PATH, _content_disposition

logger = logging.getLogger(__name__)

router = APIRouter()


def _historial(operacion, *args):
    """Ejecuta una operación del Historial. Un fallo de la base (bloqueada,
    disco lleno, permisos) es un error claro para el docente, no un 500 sin
    explicación; la base misma la repara database.py cuando puede."""
    try:
        return operacion(*args)
    except (sqlite3.Error, OSError) as exc:
        logger.exception("Error en el historial (%s)", getattr(operacion, "__name__", operacion))
        raise HTTPException(status_code=503, detail=(
            "No se pudo acceder al historial guardado en este equipo "
            f"({type(exc).__name__}). Cierra y vuelve a abrir la aplicación; si se repite, envía al "
            f"desarrollador el registro «{ERROR_LOG_PATH}». Convertir y descargar siguen funcionando."
        ))


# Estas rutas son `def` (no `async def`): hacen SQLite y json.loads síncronos, y
# como corrutinas bloqueaban el event loop (y con él las conversiones en curso).
# FastAPI corre las `def` en su threadpool; la seguridad (token, Host, Origin)
# la aplica el middleware antes, sin cambios.
@router.get("/api/history")
def api_get_history():
    return _historial(get_history_list)

@router.get("/api/history/{record_id}/download")
def api_download_history(record_id: int):
    record = _historial(get_xml_content, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Registro no encontrado")

    output_filename = f"{Path(record['filename']).stem}.xml"
    return Response(
        content=record["xml_content"].encode("utf-8"),
        media_type="application/xml",
        headers={"Content-Disposition": _content_disposition(output_filename)},
    )

@router.get("/api/history/{record_id}/editor")
def api_history_editor(record_id: int):
    record = _historial(get_editor_data, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    if not record["editor_json"]:
        raise HTTPException(
            status_code=404,
            detail="Esta conversión es anterior a la opción de reabrir: solo se puede descargar.",
        )
    try:
        data = json.loads(record["editor_json"])
    except ValueError:
        logger.error("El registro %s del historial tiene datos de revisión ilegibles", record_id)
        raise HTTPException(
            status_code=422,
            detail="Los datos guardados para reabrir esta conversión están dañados: solo se puede descargar.",
        )
    if not isinstance(data, dict):
        data = {}
    return {
        "filename": record["filename"],
        "category": record["category"],
        "total_points": record["total_points"],
        "questions": data.get("questions", []),
        "answer_key": data.get("answer_key", {}),
    }

@router.delete("/api/history/{record_id}")
def api_delete_history(record_id: int):
    if not _historial(delete_history_item, record_id):
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    return {"deleted": True}
