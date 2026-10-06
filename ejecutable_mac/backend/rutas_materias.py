"""
rutas_materias.py — «Mis materias»: las materias del docente y sus valores por defecto (2.3).

  GET    /api/materias            las materias con cuántos exámenes tiene cada una
  POST   /api/materias            crea una (nombre, color, perfil de encabezado, docente, grupo)
  PATCH  /api/materias/{id}       cambia lo que se envíe (también archivarla)
  DELETE /api/materias/{id}       la borra; sus exámenes NO se borran: pasan a «Sin materia»

A qué materia pertenece cada examen se cambia en rutas_historial.py (PATCH /api/history/{id}).
"""

import re
import unicodedata
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from database import (
    COLORES_MATERIA, LIMITE_CAMPO_MATERIA, LIMITE_NOMBRE_MATERIA, MAX_MATERIAS,
    LimiteDeMaterias, MateriaDuplicada, create_materia, delete_materia, list_materias, update_materia,
)
from rutas_historial import _historial

router = APIRouter()


def _linea(texto: Optional[str], tope: int) -> Optional[str]:
    """Una línea sin saltos ni espacios de sobra, en forma NFC (macOS entrega nombres descompuestos)."""
    if texto is None:
        return None
    t = unicodedata.normalize("NFC", re.sub(r"\s+", " ", texto)).strip()
    return t[:tope] or None


class MateriaNueva(BaseModel):
    nombre: str = Field(max_length=LIMITE_NOMBRE_MATERIA * 2)
    color: str = "azul"
    # Nombre de un perfil de encabezado del PDF (rutas_pdf.py); si el perfil se borra después, se ignora.
    perfil: Optional[str] = Field(None, max_length=60)
    docente: Optional[str] = Field(None, max_length=LIMITE_CAMPO_MATERIA * 2)
    grupo: Optional[str] = Field(None, max_length=LIMITE_CAMPO_MATERIA * 2)


class MateriaCambios(BaseModel):
    """Solo cambia lo que viene en la petición; null en perfil, docente o grupo lo vacía."""
    nombre: Optional[str] = Field(None, max_length=LIMITE_NOMBRE_MATERIA * 2)
    color: Optional[str] = None
    perfil: Optional[str] = Field(None, max_length=60)
    docente: Optional[str] = Field(None, max_length=LIMITE_CAMPO_MATERIA * 2)
    grupo: Optional[str] = Field(None, max_length=LIMITE_CAMPO_MATERIA * 2)
    archivada: Optional[bool] = None


def _nombre_valido(n: Optional[str]) -> str:
    nombre = _linea(n, LIMITE_NOMBRE_MATERIA)
    if not nombre:
        raise HTTPException(status_code=422, detail="Escribe el nombre de la materia.")
    return nombre


def _color_valido(c: str) -> str:
    if c not in COLORES_MATERIA:
        raise HTTPException(status_code=422, detail="Ese color no está disponible.")
    return c


@router.get("/api/materias")
def api_listar_materias():
    return _historial(list_materias)


@router.post("/api/materias", status_code=201)
def api_crear_materia(body: MateriaNueva):
    try:
        return _historial(
            create_materia, _nombre_valido(body.nombre), _color_valido(body.color),
            _linea(body.perfil, 60), _linea(body.docente, LIMITE_CAMPO_MATERIA), _linea(body.grupo, LIMITE_CAMPO_MATERIA),
        )
    except MateriaDuplicada:
        raise HTTPException(status_code=409, detail="Ya tienes una materia con ese nombre.")
    except LimiteDeMaterias:
        raise HTTPException(status_code=422, detail=f"Ya tienes {MAX_MATERIAS} materias: archiva o borra alguna para crear otra.")


@router.patch("/api/materias/{materia_id}")
def api_cambiar_materia(materia_id: int, body: MateriaCambios):
    enviados = body.model_fields_set
    cambios = {}
    if "nombre" in enviados:
        cambios["nombre"] = _nombre_valido(body.nombre)
    if "color" in enviados:
        cambios["color"] = _color_valido(body.color or "")
    if "perfil" in enviados:
        cambios["perfil"] = _linea(body.perfil, 60)
    if "docente" in enviados:
        cambios["docente"] = _linea(body.docente, LIMITE_CAMPO_MATERIA)
    if "grupo" in enviados:
        cambios["grupo"] = _linea(body.grupo, LIMITE_CAMPO_MATERIA)
    if "archivada" in enviados:
        if body.archivada is None:
            raise HTTPException(status_code=422, detail="«archivada» debe ser verdadero o falso.")
        cambios["archivada"] = body.archivada
    try:
        materia = _historial(update_materia, materia_id, cambios)
    except MateriaDuplicada:
        raise HTTPException(status_code=409, detail="Ya tienes una materia con ese nombre.")
    if materia is None:
        raise HTTPException(status_code=404, detail="Materia no encontrada")
    return materia


@router.delete("/api/materias/{materia_id}")
def api_borrar_materia(materia_id: int):
    movidos = _historial(delete_materia, materia_id)
    if movidos is None:
        raise HTTPException(status_code=404, detail="Materia no encontrada")
    return {"deleted": True, "examenes_sin_materia": movidos}
