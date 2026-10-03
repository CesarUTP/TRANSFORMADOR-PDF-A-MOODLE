"""
rutas_ayuda.py — ayudas de IA del editor, de UNA pregunta cada una.

  POST /api/retroalimentacion   «Escribir con IA»
  POST /api/mejorar_enunciado   «Mejorar redacción»

Tienen su propio cupo (_CUPOS_IA_PUNTUAL en estado_servidor.py): no esperan
detrás de una conversión larga.
"""

from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel

import ayuda_ia
from estado_servidor import _con_cupo_puntual

router = APIRouter()


class RetroalimentacionBody(BaseModel):
    pregunta: Dict[str, Any]
    respuesta: Any = None


# Botón «Escribir con IA» del editor: la retroalimentación de UNA pregunta.
# Tiene su propio cupo (no espera detrás de una conversión larga).
@router.post("/api/retroalimentacion")
def api_retroalimentacion(body: RetroalimentacionBody):
    return {"retroalimentacion": _con_cupo_puntual(ayuda_ia.generar, body.pregunta, body.respuesta)}


class EnunciadoBody(BaseModel):
    pregunta: Dict[str, Any]


# Botón «Mejorar redacción» del editor: el enunciado de UNA pregunta.
@router.post("/api/mejorar_enunciado")
def api_mejorar_enunciado(body: EnunciadoBody):
    return _con_cupo_puntual(ayuda_ia.mejorar_enunciado, body.pregunta)
