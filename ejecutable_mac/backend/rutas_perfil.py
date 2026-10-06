"""
rutas_perfil.py — «Mi perfil»: los datos del docente que se usan en los encabezados del PDF (2.3).

  GET /api/yo    nombre, cómo se le llama («Facilitador», «Docente»…) y su perfil de encabezado predeterminado
  PUT /api/yo    cambia lo que se envíe

Los perfiles de encabezado en sí (institución, logos, formato) están en rutas_pdf.py (/api/perfiles_pdf).
"""

import re
import unicodedata
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import exportar_pdf
from database import get_ajustes, list_perfiles, set_ajustes
from rutas_historial import _historial

router = APIRouter()


class YoCambios(BaseModel):
    """Solo cambia lo que viene en la petición; perfil_predeterminado null lo quita."""
    nombre: Optional[str] = Field(None, max_length=exportar_pdf.LIMITE_CAMPO * 2)
    rotulo_docente: Optional[str] = None
    perfil_predeterminado: Optional[str] = Field(None, max_length=60)


@router.get("/api/yo")
def api_yo():
    return _historial(get_ajustes)


@router.put("/api/yo")
def api_cambiar_yo(body: YoCambios):
    enviados = body.model_fields_set
    cambios = {}
    if "nombre" in enviados:
        cambios["nombre"] = unicodedata.normalize("NFC", re.sub(r"\s+", " ", body.nombre or "")).strip()[:exportar_pdf.LIMITE_CAMPO]
    if "rotulo_docente" in enviados:
        if body.rotulo_docente not in exportar_pdf.ROTULOS:
            raise HTTPException(status_code=422, detail="Ese rótulo no está disponible.")
        cambios["rotulo_docente"] = body.rotulo_docente
    if "perfil_predeterminado" in enviados:
        p = body.perfil_predeterminado
        if p is not None and p not in {f["nombre"] for f in _historial(list_perfiles)}:
            raise HTTPException(status_code=404, detail="Ese perfil de encabezado ya no existe.")
        cambios["perfil_predeterminado"] = p
    _historial(set_ajustes, cambios)
    return _historial(get_ajustes)
