"""
rutas_pdf.py — el examen revisado como PDF imprimible (2.1).

  POST /api/exportar_pdf   mismas preguntas y clave que /api/generate_xml, más los
                           datos de la portada; devuelve el PDF (cabecera X-PDF-Info
                           con páginas, preguntas y avisos).

Es un documento de apoyo: no se guarda en el Historial ni cambia el XML.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field

import exportar_pdf
from estado_servidor import ERROR_LOG_PATH, _avisos_para_cabecera, _content_disposition, _detalle_tecnico, _nombre_nfc
from rutas_xml import validar_para_exportar

logger = logging.getLogger(__name__)

router = APIRouter()


class DatosPortada(BaseModel):
    """Lo que el docente escribe en el diálogo «Exportar examen en PDF»."""
    institucion: str = Field("", max_length=exportar_pdf.LIMITE_CAMPO)
    facultad: str = Field("", max_length=exportar_pdf.LIMITE_CAMPO)
    departamento: str = Field("", max_length=exportar_pdf.LIMITE_CAMPO)
    materia: str = Field("", max_length=exportar_pdf.LIMITE_CAMPO)
    docente: str = Field("", max_length=exportar_pdf.LIMITE_CAMPO)
    actividad: str = Field("", max_length=exportar_pdf.LIMITE_CAMPO)
    grupo: str = Field("", max_length=exportar_pdf.LIMITE_CAMPO)
    fecha: str = Field("", max_length=exportar_pdf.LIMITE_CAMPO)
    instrucciones: str = Field("", max_length=exportar_pdf.LIMITE_INSTRUCCIONES)
    contenido: str = "examen_y_clave"
    papel: str = "carta"
    campos_estudiante: bool = True
    rotulo_docente: str = "facilitador"
    partes: bool = True
    # Logos en base64 (el diálogo los reduce antes de enviarlos); "" = sin logo.
    logo_izquierdo: str = Field("", max_length=exportar_pdf.LIMITE_LOGO)
    logo_derecho: str = Field("", max_length=exportar_pdf.LIMITE_LOGO)


class ExportarPdfRequest(BaseModel):
    filename: str
    total_points: float = Field(gt=0, le=100_000, allow_inf_nan=False)
    questions: List[Dict[str, Any]]
    answer_key: Dict[str, Any]
    datos: DatosPortada = DatosPortada()


def _exportar_sync(req: ExportarPdfRequest, clave: Dict[int, Any]):
    validar_para_exportar(req.questions, clave)
    d = req.datos
    if d.contenido not in exportar_pdf.CONTENIDOS or d.papel not in exportar_pdf.PAPELES or d.rotulo_docente not in exportar_pdf.ROTULOS:
        raise HTTPException(status_code=422, detail="Opciones de exportación no válidas.")
    datos = exportar_pdf.DatosExamen(
        institucion=d.institucion, facultad=d.facultad, departamento=d.departamento, materia=d.materia, docente=d.docente, actividad=d.actividad,
        grupo=d.grupo, fecha=d.fecha, instrucciones=d.instrucciones,
        titulo_respaldo=Path(req.filename).stem, contenido=d.contenido, papel=d.papel,
        campos_estudiante=d.campos_estudiante, rotulo_docente=d.rotulo_docente, partes=d.partes,
        logo_izquierdo=d.logo_izquierdo, logo_derecho=d.logo_derecho)
    return exportar_pdf.generar_pdf(req.questions, clave, req.total_points, datos)


_SUFIJO = {"examen_y_clave": "_examen_y_clave", "solo_examen": "_examen", "solo_clave": "_clave",
           "folleto_hoja_clave": "_folleto_hoja_y_clave"}


@router.post("/api/exportar_pdf")
async def api_exportar_pdf(req: ExportarPdfRequest):
    try:
        clave = {int(k): v for k, v in req.answer_key.items()}
    except ValueError:
        raise HTTPException(status_code=422, detail="Las claves de answer_key deben ser enteros.")
    req.filename = _nombre_nfc(req.filename)
    try:
        r = await run_in_threadpool(_exportar_sync, req, clave)
        nombre = f"{Path(req.filename).stem}{_SUFIJO.get(req.datos.contenido, '')}.pdf"
        info = json.dumps({"paginas": r.paginas, "preguntas": r.preguntas, "avisos": _avisos_para_cabecera(r.avisos)})
        return Response(content=r.pdf, media_type="application/pdf",
                        headers={"Content-Disposition": _content_disposition(nombre), "X-PDF-Info": info})
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error inesperado generando el PDF de '%s'", req.filename)
        raise HTTPException(status_code=500, detail=(
            "Ocurrió un error inesperado al generar el PDF. Tu revisión sigue intacta y el XML no se ve afectado: "
            f"vuelve a intentarlo. Si se repite, envía al desarrollador el registro «{ERROR_LOG_PATH}». "
            f"(Detalle técnico: {_detalle_tecnico(exc)})"))
