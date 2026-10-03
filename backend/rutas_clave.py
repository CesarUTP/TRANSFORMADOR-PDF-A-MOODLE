"""
rutas_clave.py — la clave de Gemini, «Acerca de» y las actualizaciones.

  GET    /api/salud          firma para el launcher (sin token, ver seguridad.py)
  GET    /api/actualizacion  ¿hay una versión nueva?
  GET    /api/acerca         versión y dónde guarda la app lo del docente
  GET    /api/api-key        estado de la clave (nunca se devuelve completa)
  POST   /api/api-key        valida y guarda la clave (cifrada, ver credenciales.py)
  DELETE /api/api-key
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import actualizaciones
import credenciales
import seguridad
from config import APP_VERSION
from database import get_db_path
from estado_servidor import ERROR_LOG_PATH

logger = logging.getLogger(__name__)

router = APIRouter()


# El launcher confirma con esta firma que quien responde en el puerto es
# este servidor y no otro programa (ver launcher._wait_for_server).
@router.get(seguridad.RUTA_SALUD, include_in_schema=False)
def api_salud(n: str = ""):
    return {"firma": seguridad.firma_salud(n)}


# ¿Hay una versión nueva? (ver actualizaciones.py). Corre en threadpool: la
# consulta a internet puede tardar unos segundos.
@router.get("/api/actualizacion")
def api_actualizacion(forzar: bool = False):
    return actualizaciones.comprobar(forzar)


# Datos para «Acerca de»: versión y dónde guarda la app lo del docente.
@router.get("/api/acerca")
def api_acerca():
    casa = str(Path.home())

    def corta(p) -> str:  # "~/Library/…" en vez de "/Users/nombre/Library/…"
        p = str(p)
        return "~" + p[len(casa):] if casa and p.startswith(casa) else p

    return {
        "version": APP_VERSION,
        "historial": corta(get_db_path()),
        "clave": corta(credenciales.ARCHIVO),
        "registro": corta(ERROR_LOG_PATH),
    }


class ApiKeyBody(BaseModel):
    clave: str


@router.get("/api/api-key")
def api_key_status():
    return credenciales.estado()


@router.post("/api/api-key")
def api_key_save(body: ApiKeyBody):
    # Al copiar suelen colarse espacios o saltos de línea.
    clave = "".join(body.clave.split())
    if not clave:
        raise HTTPException(status_code=422, detail="Pega tu clave en el cuadro de texto.")
    if len(clave) < 20:
        raise HTTPException(status_code=422, detail="Esa clave es demasiado corta. Revisa que la copiaste completa.")
    try:
        credenciales.validar(clave)
    except credenciales.ClaveInvalida:
        raise HTTPException(status_code=422, detail="Google no aceptó esa clave. Revisa que la copiaste completa, sin espacios de más.")
    except credenciales.SinConexion as exc:
        logger.warning("No se pudo comprobar la clave de la API de Gemini: %s", exc)
        raise HTTPException(status_code=503, detail="No se pudo comprobar la clave con Google. Revisa tu conexión a internet e inténtalo otra vez.")
    try:
        credenciales.guardar(clave)
    except OSError as exc:
        logger.exception("No se pudo escribir la clave de la API de Gemini")
        raise HTTPException(status_code=500, detail=(
            "La clave es válida, pero no se pudo guardar en este equipo (falta permiso o espacio en la "
            f"carpeta de datos de la aplicación: {type(exc).__name__}). Revisa el permiso de esa carpeta e inténtalo de nuevo."))
    except Exception as exc:  # noqa: BLE001
        logger.exception("No se pudo guardar la clave de la API de Gemini")
        raise HTTPException(status_code=500, detail=f"La clave es válida, pero no se pudo guardar ({type(exc).__name__}).")
    return credenciales.estado()


@router.delete("/api/api-key")
def api_key_delete():
    try:
        credenciales.borrar()
    except OSError as exc:
        logger.exception("No se pudo borrar la clave de la API de Gemini")
        raise HTTPException(status_code=500, detail=(
            "No se pudo borrar la clave guardada (falta permiso en la carpeta de datos de la aplicación: "
            f"{type(exc).__name__}). Revisa el permiso de esa carpeta e inténtalo de nuevo."))
    return credenciales.estado()
