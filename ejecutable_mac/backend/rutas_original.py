"""
rutas_original.py — «Revisión con el original»: el recorte de la página de una pregunta.

  GET /api/original/{original_id}/pagina/{pagina}   PNG de la página (o de la zona de la pregunta)

El PDF vive solo en memoria mientras la app está abierta (ver originales.py).
Si el id ya no existe (la app se reabrió, o otra conversión lo desplazó) es un
404 con un mensaje que la interfaz muestra tal cual.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

import originales

router = APIRouter()

MENSAJE_NO_DISPONIBLE = (
    "El original ya no está disponible: solo se conserva mientras la aplicación está abierta, "
    "y no se guarda en el Historial. Vuelve a convertir el examen para verlo."
)


@router.get("/api/original/{original_id}/pagina/{pagina}")
async def api_original_pagina(
    original_id: str,
    pagina: int,
    vista: str = Query("recorte", pattern="^(recorte|pagina)$"),
    recuadro: Optional[str] = Query(None, max_length=80),
    zoom: float = Query(1.0, ge=1.0, le=3.0),
):
    try:
        png = await run_in_threadpool(
            originales.renderizar, original_id, pagina, originales.parsear_recuadro(recuadro), vista, zoom)
    except originales.OriginalNoDisponible:
        raise HTTPException(status_code=404, detail=MENSAJE_NO_DISPONIBLE)
    except IndexError:
        raise HTTPException(status_code=404, detail="Esa página no existe en el documento.")
    except Exception:  # noqa: BLE001 — un PDF raro no debe tumbar la revisión
        raise HTTPException(status_code=422, detail="No se pudo dibujar esa página del original.")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})
