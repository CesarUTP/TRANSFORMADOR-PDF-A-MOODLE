"""
rutas_historial.py — el Historial de conversiones guardadas en este equipo.

  GET    /api/history
  GET    /api/history/{record_id}/download
  GET    /api/history/{record_id}/editor
  DELETE /api/history/{record_id}
  PATCH  /api/history/{record_id}   cambia su materia y/o su actividad (Mis materias)
  POST   /api/history/borrar        borra varios exámenes a la vez
  POST   /api/history/mover         pasa varios exámenes a una materia (o a «sin materia»)
  GET    /api/history/uso           cuánto del Historial está usado y cuánto no tiene materia
"""

import json
import logging
import sqlite3
from pathlib import Path

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from database import (
    LIMITE_CAMPO_MATERIA, delete_history_item, delete_history_items, get_editor_data, get_history_list, get_uso, get_xml_content,
    move_history_items, update_history_item,
)
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
        "materia_id": record.get("materia_id"),
        "actividad": record.get("actividad"),
        "questions": data.get("questions", []),
        "answer_key": data.get("answer_key", {}),
    }

@router.delete("/api/history/{record_id}")
def api_delete_history(record_id: int):
    if not _historial(delete_history_item, record_id):
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    return {"deleted": True}


class CambiosDeExamen(BaseModel):
    """Solo cambia lo que viene en la petición; materia_id null lo deja «sin materia»."""
    materia_id: Optional[int] = None
    actividad: Optional[str] = Field(None, max_length=LIMITE_CAMPO_MATERIA * 2)


@router.patch("/api/history/{record_id}")
def api_cambiar_examen(record_id: int, body: CambiosDeExamen):
    enviados = body.model_fields_set
    if not enviados & {"materia_id", "actividad"}:
        raise HTTPException(status_code=422, detail="No hay nada que cambiar.")
    kwargs = {}
    if "materia_id" in enviados:
        kwargs["materia_id"] = body.materia_id
    if "actividad" in enviados:
        kwargs["actividad"] = " ".join((body.actividad or "").split())[:LIMITE_CAMPO_MATERIA] or None
    res = _historial(lambda: update_history_item(record_id, **kwargs))
    if res is None:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    if res is False:
        raise HTTPException(status_code=404, detail="Esa materia ya no existe.")
    return {"updated": True}


class MoverExamenes(BaseModel):
    ids: List[int] = Field(min_length=1, max_length=1000)
    materia_id: Optional[int] = None


@router.post("/api/history/mover")
def api_mover_examenes(body: MoverExamenes):
    movidos = _historial(move_history_items, list(dict.fromkeys(body.ids)), body.materia_id)
    if movidos is None:
        raise HTTPException(status_code=404, detail="Esa materia ya no existe.")
    return {"movidos": movidos}


class BorrarExamenes(BaseModel):
    ids: List[int] = Field(min_length=1, max_length=1000)


@router.post("/api/history/borrar")
def api_borrar_examenes(body: BorrarExamenes):
    return {"borrados": _historial(delete_history_items, list(dict.fromkeys(body.ids)))}


@router.get("/api/history/uso")
def api_uso_historial():
    return _historial(get_uso)
