"""
rutas_pdf.py — el examen revisado como PDF imprimible (2.1).

  POST /api/exportar_pdf   mismas preguntas y clave que /api/generate_xml, más los
                           datos de la portada; devuelve el PDF (cabecera X-PDF-Info
                           con páginas, preguntas y avisos).

  POST /api/vista_previa_pdf?pagina=N   lo mismo, pero devuelve la página N como imagen PNG (cabecera X-PDF-Paginas)
  GET    /api/perfiles_pdf              los perfiles de encabezado guardados
  PUT    /api/perfiles_pdf/{nombre}     crea o reemplaza un perfil (institución, logos, formato…)
  POST   /api/perfiles_pdf/{nombre}/renombrar   cambia el nombre (y lo que apuntaba a él)
  DELETE /api/perfiles_pdf/{nombre}

Es un documento de apoyo: no se guarda en el Historial ni cambia el XML.
"""

import io
import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field

import exportar_pdf
import pypdfium2 as pdfium
import versiones
from database import MAX_PERFILES, delete_perfil, list_perfiles, rename_perfil, save_perfil
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
    version: str = Field("", max_length=exportar_pdf.LIMITE_VERSION)     # «A», «B»… (solo en las versiones de un examen)
    papel: str = "carta"
    margenes: str = "moderados"
    # Tipo de letra y tamaño (pt) de los títulos/encabezados/indicaciones y de las preguntas.
    fuente_titulos: str = "dejavu"
    tam_titulos: float = Field(11.0, ge=exportar_pdf.TAM_MIN, le=exportar_pdf.TAM_MAX, allow_inf_nan=False)
    fuente_preguntas: str = "dejavu"
    tam_preguntas: float = Field(10.0, ge=exportar_pdf.TAM_MIN, le=exportar_pdf.TAM_MAX, allow_inf_nan=False)
    campos_estudiante: bool = True
    rotulo_docente: str = "facilitador"
    partes: bool = True
    mezclar: bool = True
    puntos_por_pregunta: bool = True
    puntos_enteros: bool = False      # el diálogo lo manda activado por defecto; una llamada sin él conserva los puntos tal cual
    renglones_ensayo: int = Field(6, ge=exportar_pdf.RENGLONES_MIN, le=exportar_pdf.RENGLONES_MAX)
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
    if d.contenido not in exportar_pdf.CONTENIDOS or d.papel not in exportar_pdf.PAPELES or d.margenes not in exportar_pdf.MARGENES or d.fuente_titulos not in exportar_pdf.FUENTES or d.fuente_preguntas not in exportar_pdf.FUENTES or d.rotulo_docente not in exportar_pdf.ROTULOS:
        raise HTTPException(status_code=422, detail="Opciones de exportación no válidas.")
    datos = exportar_pdf.DatosExamen(
        institucion=d.institucion, facultad=d.facultad, departamento=d.departamento, materia=d.materia, docente=d.docente, actividad=d.actividad,
        grupo=d.grupo, fecha=d.fecha, instrucciones=d.instrucciones,
        titulo_respaldo=Path(req.filename).stem, version=d.version, contenido=d.contenido, papel=d.papel, margenes=d.margenes,
        fuente_titulos=d.fuente_titulos, tam_titulos=d.tam_titulos, fuente_preguntas=d.fuente_preguntas, tam_preguntas=d.tam_preguntas,
        campos_estudiante=d.campos_estudiante, rotulo_docente=d.rotulo_docente, partes=d.partes, mezclar=d.mezclar,
        puntos_por_pregunta=d.puntos_por_pregunta, puntos_enteros=d.puntos_enteros, renglones_ensayo=d.renglones_ensayo,
        logo_izquierdo=d.logo_izquierdo, logo_derecho=d.logo_derecho)
    try:
        return exportar_pdf.generar_pdf(req.questions, clave, req.total_points, datos)
    except exportar_pdf.PuntosNoEnteros as exc:
        raise HTTPException(status_code=422, detail=str(exc))


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


# ── Versiones de un examen (2.5) ────────────────────────────────────────────
class VersionPdf(BaseModel):
    """Una versión: qué preguntas del examen lleva (en qué orden) y, si el docente los ajustó, sus puntos."""
    etiqueta: str = Field(min_length=1, max_length=exportar_pdf.LIMITE_VERSION)
    nums: List[int] = Field(min_length=1, max_length=2000)
    puntos: Dict[str, float] = Field(default_factory=dict)
    total_points: float = Field(gt=0, le=100_000, allow_inf_nan=False)


class ExportarVersionesRequest(BaseModel):
    """El examen COMPLETO (el mismo del XML) y las versiones que se sacan de él."""
    filename: str
    total_points: float = Field(gt=0, le=100_000, allow_inf_nan=False)
    questions: List[Dict[str, Any]]
    answer_key: Dict[str, Any]
    datos: DatosPortada = DatosPortada()
    versiones: List[VersionPdf] = Field(min_length=1, max_length=versiones.MAX_VERSIONES)


def _exportar_versiones_sync(req: ExportarVersionesRequest, clave: Dict[int, Any]):
    d = req.datos
    if d.contenido not in exportar_pdf.CONTENIDOS or d.papel not in exportar_pdf.PAPELES or d.margenes not in exportar_pdf.MARGENES or d.fuente_titulos not in exportar_pdf.FUENTES or d.fuente_preguntas not in exportar_pdf.FUENTES or d.rotulo_docente not in exportar_pdf.ROTULOS:
        raise HTTPException(status_code=422, detail="Opciones de exportación no válidas.")
    validar_para_exportar(req.questions, clave)          # el examen completo cumple lo mismo que para el XML
    etiquetas = [v.etiqueta.strip() for v in req.versiones]
    if len({e.upper() for e in etiquetas}) != len(etiquetas) or not all(etiquetas):
        raise HTTPException(status_code=422, detail="Cada versión necesita un nombre distinto.")
    archivos, resumen, avisos = [], [], []
    sufijo = _SUFIJO.get(d.contenido, "")
    stem = Path(req.filename).stem
    for v, etiqueta in zip(req.versiones, etiquetas):
        try:
            qs, clave_v = versiones.subconjunto(req.questions, clave, v.nums, {int(k): p for k, p in v.puntos.items()})
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Versión {etiqueta}: {exc}")
        datos = exportar_pdf.DatosExamen(
            institucion=d.institucion, facultad=d.facultad, departamento=d.departamento, materia=d.materia, docente=d.docente,
            actividad=d.actividad, grupo=d.grupo, fecha=d.fecha, instrucciones=d.instrucciones, titulo_respaldo=stem,
            version=etiqueta, contenido=d.contenido, papel=d.papel, margenes=d.margenes,
            fuente_titulos=d.fuente_titulos, tam_titulos=d.tam_titulos, fuente_preguntas=d.fuente_preguntas, tam_preguntas=d.tam_preguntas,
            campos_estudiante=d.campos_estudiante, rotulo_docente=d.rotulo_docente, partes=d.partes, mezclar=d.mezclar,
            puntos_por_pregunta=d.puntos_por_pregunta, puntos_enteros=d.puntos_enteros, renglones_ensayo=d.renglones_ensayo,
            logo_izquierdo=d.logo_izquierdo, logo_derecho=d.logo_derecho)
        try:
            r = exportar_pdf.generar_pdf(qs, clave_v, v.total_points, datos)
        except exportar_pdf.PuntosNoEnteros as exc:
            raise HTTPException(status_code=422, detail=f"Versión {etiqueta}: {exc}")
        archivos.append((f"{stem}_version_{versiones.etiqueta_para_archivo(etiqueta)}{sufijo}.pdf", r.pdf))
        resumen.append({"etiqueta": etiqueta, "paginas": r.paginas, "preguntas": r.preguntas})
        avisos += [f"Versión {etiqueta}: {a}" for a in r.avisos]
    return versiones.empaquetar(archivos), resumen, avisos


@router.post("/api/exportar_versiones")
async def api_exportar_versiones(req: ExportarVersionesRequest):
    try:
        clave = {int(k): v for k, v in req.answer_key.items()}
    except ValueError:
        raise HTTPException(status_code=422, detail="Las claves de answer_key deben ser enteros.")
    req.filename = _nombre_nfc(req.filename)
    try:
        contenido, resumen, avisos = await run_in_threadpool(_exportar_versiones_sync, req, clave)
        nombre = f"{Path(req.filename).stem}_versiones.zip"
        info = json.dumps({"versiones": resumen, "avisos": _avisos_para_cabecera(avisos)})
        return Response(content=contenido, media_type="application/zip",
                        headers={"Content-Disposition": _content_disposition(nombre), "X-PDF-Info": info})
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error inesperado generando las versiones de '%s'", req.filename)
        raise HTTPException(status_code=500, detail=(
            "Ocurrió un error inesperado al generar las versiones. Tu revisión sigue intacta y el XML no se ve afectado: "
            f"vuelve a intentarlo. Si se repite, envía al desarrollador el registro «{ERROR_LOG_PATH}». "
            f"(Detalle técnico: {_detalle_tecnico(exc)})"))


# ── Vista previa ────────────────────────────────────────────────────────────
_CERROJO_RENDER = threading.Lock()      # PDFium no es seguro entre hilos


def _vista_previa_sync(req: ExportarPdfRequest, clave: Dict[int, Any], pagina: int):
    r = _exportar_sync(req, clave)
    with _CERROJO_RENDER:
        doc = pdfium.PdfDocument(r.pdf)
        try:
            n = len(doc)
            pag = doc[min(max(pagina, 1), n) - 1]
            imagen = pag.render(scale=1.4).to_pil().convert("RGB")
        finally:
            doc.close()
    salida = io.BytesIO()
    imagen.save(salida, "PNG", optimize=False)
    return salida.getvalue(), n


@router.post("/api/vista_previa_pdf")
async def api_vista_previa_pdf(req: ExportarPdfRequest, pagina: int = Query(1, ge=1, le=2000)):
    try:
        clave = {int(k): v for k, v in req.answer_key.items()}
    except ValueError:
        raise HTTPException(status_code=422, detail="Las claves de answer_key deben ser enteros.")
    req.filename = _nombre_nfc(req.filename)
    try:
        png, paginas = await run_in_threadpool(_vista_previa_sync, req, clave, pagina)
        return Response(content=png, media_type="image/png", headers={"X-PDF-Paginas": str(paginas), "Cache-Control": "no-store"})
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error inesperado en la vista previa del PDF de '%s'", req.filename)
        raise HTTPException(status_code=500, detail=f"No se pudo preparar la vista previa. (Detalle técnico: {_detalle_tecnico(exc)})")


# ── Perfiles de encabezado ──────────────────────────────────────────────────
LIMITE_LOGO_PERFIL = 400_000      # base64: el diálogo reduce los logos a 320 px (unos pocos KB)


class PerfilPdf(BaseModel):
    """Lo que se guarda en un perfil: el encabezado y el formato, NO lo propio de cada examen
    (materia, actividad, grupo, fecha, qué incluir)."""
    institucion: str = Field("", max_length=exportar_pdf.LIMITE_CAMPO)
    facultad: str = Field("", max_length=exportar_pdf.LIMITE_CAMPO)
    departamento: str = Field("", max_length=exportar_pdf.LIMITE_CAMPO)
    docente: str = Field("", max_length=exportar_pdf.LIMITE_CAMPO)
    rotulo_docente: str = "facilitador"
    instrucciones: str = Field("", max_length=exportar_pdf.LIMITE_INSTRUCCIONES)
    logo_izquierdo: str = Field("", max_length=LIMITE_LOGO_PERFIL)
    logo_derecho: str = Field("", max_length=LIMITE_LOGO_PERFIL)
    papel: str = "carta"
    margenes: str = "moderados"
    fuente_titulos: str = "dejavu"
    tam_titulos: float = Field(11.0, ge=exportar_pdf.TAM_MIN, le=exportar_pdf.TAM_MAX, allow_inf_nan=False)
    fuente_preguntas: str = "dejavu"
    tam_preguntas: float = Field(10.0, ge=exportar_pdf.TAM_MIN, le=exportar_pdf.TAM_MAX, allow_inf_nan=False)
    campos_estudiante: bool = True
    partes: bool = True
    mezclar: bool = True
    puntos_por_pregunta: bool = True
    puntos_enteros: bool = True        # los perfiles nuevos (y los viejos, al leerlos) usan puntos enteros
    renglones_ensayo: int = Field(6, ge=exportar_pdf.RENGLONES_MIN, le=exportar_pdf.RENGLONES_MAX)


def _nombre_perfil(nombre: str) -> str:
    n = " ".join(str(nombre or "").split())
    if not n or len(n) > 60 or "/" in n or "\\" in n:
        raise HTTPException(status_code=422, detail="El nombre del perfil debe tener entre 1 y 60 caracteres y no puede llevar «/» ni «\\».")
    return n


def _perfiles(operacion, *args):
    try:
        return operacion(*args)
    except (sqlite3.Error, OSError) as exc:
        logger.exception("Error en los perfiles del PDF")
        raise HTTPException(status_code=503, detail=f"No se pudo acceder a los perfiles guardados ({type(exc).__name__}).")


@router.get("/api/perfiles_pdf")
def api_perfiles_pdf():
    salida = []
    for fila in _perfiles(list_perfiles):
        try:
            datos = json.loads(fila["datos"])
        except ValueError:
            continue                    # un perfil dañado no impide ver los demás
        if isinstance(datos, dict):
            salida.append({"nombre": fila["nombre"], "datos": datos, "actualizado": fila["actualizado"]})
    return salida


@router.put("/api/perfiles_pdf/{nombre}")
def api_guardar_perfil_pdf(nombre: str, body: PerfilPdf):
    n = _nombre_perfil(nombre)
    if (body.rotulo_docente not in exportar_pdf.ROTULOS or body.papel not in exportar_pdf.PAPELES
            or body.margenes not in exportar_pdf.MARGENES or body.fuente_titulos not in exportar_pdf.FUENTES
            or body.fuente_preguntas not in exportar_pdf.FUENTES):
        raise HTTPException(status_code=422, detail="El perfil trae opciones no válidas.")
    if not _perfiles(save_perfil, n, body.model_dump_json()):
        raise HTTPException(status_code=422, detail=f"Ya hay {MAX_PERFILES} perfiles guardados: borra alguno para crear otro.")
    return {"nombre": n}


class RenombrarPerfil(BaseModel):
    nuevo: str


@router.post("/api/perfiles_pdf/{nombre}/renombrar")
def api_renombrar_perfil_pdf(nombre: str, body: RenombrarPerfil):
    res = _perfiles(rename_perfil, _nombre_perfil(nombre), _nombre_perfil(body.nuevo))
    if res == "no_existe":
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    if res == "ya_existe":
        raise HTTPException(status_code=409, detail="Ya tienes un perfil con ese nombre.")
    return {"nombre": _nombre_perfil(body.nuevo)}


@router.delete("/api/perfiles_pdf/{nombre}")
def api_borrar_perfil_pdf(nombre: str):
    if not _perfiles(delete_perfil, _nombre_perfil(nombre)):
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    return {"deleted": True}
