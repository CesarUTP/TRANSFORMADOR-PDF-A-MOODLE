"""
main.py — FastAPI application for PDF → Moodle XML conversion.

Endpoints:
  GET  /         → serves index.html (frontend)
  POST /convert  → multipart upload (.pdf or .txt) → Moodle XML download
"""

import asyncio
import inspect
import json
import logging
import math
import re
import queue
import sqlite3
import sys
import threading
import unicodedata
from urllib.parse import quote
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from lxml import etree

from config import APP_VERSION, DEFAULT_CATEGORY, DEFAULT_TOTAL_POINTS, SERVER_PORT
import actualizaciones
import answer_matching
import credenciales
import ayuda_ia
import formatter
import seguridad
from extractor import pdf_has_embedded_images
from extractor_docx import docx_tiene_imagenes
from pipeline import parse_document, normalize_document_with_ai
from validator import validate_questions
from xml_builder import build_xml, compute_grades
from database import get_db_path, init_db, save_conversion, get_history_list, get_xml_content, delete_history_item, get_editor_data
from pydantic import BaseModel, Field
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


# ── Registro de errores en archivo ─────────────────────────────────────────
# El launcher arranca uvicorn con log_level="critical" y sin consola: una
# excepción inesperada se perdía sin dejar rastro, y el docente solo veía
# "Ocurrió un error inesperado". Ahora todo error (con su traza completa)
# queda en errores.log: junto a la base de datos en el ejecutable, o en la
# raíz del proyecto al correr desde el código.
def _error_log_path() -> Path:
    if getattr(sys, "frozen", False):
        from database import _app_data_dir
        return _app_data_dir() / "errores.log"
    return Path(__file__).resolve().parent.parent / "errores.log"


ERROR_LOG_PATH = _error_log_path()


def _configurar_log_de_errores() -> None:
    root = logging.getLogger()
    if any(getattr(h, "_conversor_errores", False) for h in root.handlers):
        return  # --reload vuelve a importar el módulo: sin handlers duplicados
    try:
        ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Con tope (1 MB + una copia anterior): nunca crece sin límite en el
        # disco del docente.
        from logging.handlers import RotatingFileHandler
        handler = RotatingFileHandler(ERROR_LOG_PATH, maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    except OSError:
        return
    handler.setLevel(logging.ERROR)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    handler._conversor_errores = True
    root.addHandler(handler)


_configurar_log_de_errores()


def _nombre_nfc(nombre: str) -> str:
    """macOS entrega los nombres de archivo en forma descompuesta (NFD):
    "Panamá" llega como "Panama" + tilde combinada (U+0301). Se normaliza a
    la forma compuesta (NFC) para guardarlo y mostrarlo siempre igual."""
    return unicodedata.normalize("NFC", nombre or "")


def _content_disposition(nombre: str) -> str:
    """
    Cabecera de descarga que acepta cualquier nombre (tildes, ñ, emojis).
    Las cabeceras HTTP solo admiten latin-1: con un nombre NFD de macOS
    ("Panamá" descompuesto) armar la respuesta lanzaba UnicodeEncodeError
    DESPUÉS de generar el XML, y el docente veía "error inesperado". Se
    envía una versión ASCII (filename) y la real en UTF-8 (filename*,
    RFC 6266/5987), que es la que usan los navegadores.
    """
    nfc = _nombre_nfc(nombre)
    ascii_ = unicodedata.normalize("NFKD", nfc).encode("ascii", "ignore").decode("ascii")
    # \r o \n en el nombre (guardado tal cual en el historial desde una
    # subida antigua, o un nombre armado a mano) rompía la cabecera HTTP
    # ("Invalid HTTP header value") y esa descarga quedaba inservible para
    # siempre. re.sub por si acaso quedara algún otro control además de \r\n.
    ascii_ = re.sub(r"[\x00-\x1f\x7f]", "", ascii_).replace('"', "").replace("\\", "").strip() or "examen_moodle.xml"
    return f"attachment; filename=\"{ascii_}\"; filename*=UTF-8''{quote(nfc, safe='')}"


def _detalle_tecnico(exc: Exception) -> str:
    texto = str(exc).strip().replace("\n", " ")
    return f"{type(exc).__name__}: {texto[:160]}" if texto else type(exc).__name__

app = FastAPI(title="PDF → Moodle XML", version=APP_VERSION)

# Sin CORS: la interfaz se sirve desde este mismo servidor, así que ninguna
# otra página necesita (ni debe poder) leer sus respuestas. Host, Origin,
# token por arranque, tamaño máximo y CSP: ver seguridad.py.
app.add_middleware(seguridad.SoloLaApp)


def _sin_infinito(obj):
    """Reemplaza Infinity/NaN por su texto antes de volver a JSON: un valor
    inválido que el docente (o una petición manual) mandó en el cuerpo
    vuelve TAL CUAL dentro del detalle del error 422 de FastAPI — y
    Starlette rechaza a su vez ESE JSON de salida porque no admite
    Infinity/NaN, así que el 422 legible se convertía en un 500 sin
    detalle."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _sin_infinito(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sin_infinito(v) for v in obj]
    return obj


@app.exception_handler(RequestValidationError)
async def _error_de_validacion(request, exc: RequestValidationError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422, content={"detail": _sin_infinito(exc.errors())})


@app.on_event("startup")
def startup_event():
    # El historial es secundario: si no se puede preparar, la app arranca igual
    # (convertir y descargar no dependen de él) y el motivo queda en el
    # registro; las pantallas del historial y el guardado avisan por su lado.
    try:
        if init_db() is False:
            logger.error("No se pudo preparar la base del historial en %s; la app arranca sin historial.", get_db_path())
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo preparar la base del historial; la app arranca sin historial.")
    if not seguridad.EN_LAUNCHER:
        # Arrancado a mano (uvicorn, ver README): sin el token en la URL la
        # interfaz no puede usar la API.
        print(f"\n  Abre la app en: http://127.0.0.1:{SERVER_PORT}/#t={seguridad.TOKEN}\n"
              "  (si arrancaste uvicorn con otro --port, cambia el número)\n", flush=True)


# El launcher confirma con esta firma que quien responde en el puerto es
# este servidor y no otro programa (ver launcher._wait_for_server).
@app.get(seguridad.RUTA_SALUD, include_in_schema=False)
def api_salud(n: str = ""):
    return {"firma": seguridad.firma_salud(n)}


# ¿Hay una versión nueva? (ver actualizaciones.py). Corre en threadpool: la
# consulta a internet puede tardar unos segundos.
@app.get("/api/actualizacion")
def api_actualizacion(forzar: bool = False):
    return actualizaciones.comprobar(forzar)


# Datos para «Acerca de»: versión y dónde guarda la app lo del docente.
@app.get("/api/acerca")
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


# Conversiones a la vez: cada una lee el PDF, renderiza páginas y llama a
# Gemini. Las demás esperan su turno en vez de agotar memoria e hilos.
_CUPOS_CONVERSION = threading.BoundedSemaphore(2)

# Los botones de IA del editor («Escribir con IA», «Mejorar redacción») son
# llamadas de UNA pregunta: con el mismo cupo que las conversiones largas
# podían esperar minutos detrás de ellas sin ningún aviso. Tienen el suyo.
_CUPOS_IA_PUNTUAL = threading.BoundedSemaphore(2)
_ESPERA_CUPO_PUNTUAL_S = 20


def _con_cupo(fn, *args, **kwargs):
    with _CUPOS_CONVERSION:
        return fn(*args, **kwargs)


def _con_cupo_puntual(fn, *args, **kwargs):
    if not _CUPOS_IA_PUNTUAL.acquire(timeout=_ESPERA_CUPO_PUNTUAL_S):
        raise HTTPException(status_code=429, detail=(
            "Ya hay dos ayudas de IA en curso. Espera unos segundos e inténtalo de nuevo."))
    try:
        return fn(*args, **kwargs)
    finally:
        _CUPOS_IA_PUNTUAL.release()


# ── Serve frontend static files ─────────────────────────────────────────────
# Works both in development (relative path) and inside a PyInstaller bundle.
def _frontend_dir() -> Path:
    if getattr(sys, "frozen", False):
        # Running as a PyInstaller bundle
        return Path(sys._MEIPASS) / "frontend"
    # Running as normal Python
    return Path(__file__).parent.parent / "frontend"

_fe = _frontend_dir()
if _fe.exists():
    app.mount("/static", StaticFiles(directory=str(_fe)), name="static")
    # index.html se sirve en "/", así que sus rutas relativas ("css/base.css",
    # "js/app.js") caen en la raíz: cada carpeta del frontend se monta ahí.
    for _sub in ("css", "js", "img", "fonts", "legal"):
        _dir = _fe / _sub
        if _dir.is_dir():
            app.mount(f"/{_sub}", StaticFiles(directory=str(_dir)), name=_sub)

@app.get("/", include_in_schema=False)
async def serve_index():
    index = _frontend_dir() / "index.html"
    return FileResponse(str(index))


@app.post("/api/check_special_cases")
async def api_check_special_cases(
    file: UploadFile = File(...),
):
    """
    Chequeo previo y barato (no llama a Gemini) para avisarle al usuario,
    ANTES de arrancar el procesamiento real, si el PDF trae imágenes
    incrustadas — caso especial (código en captura, marcas de color) que el
    prefiltro de IA no garantiza transcribir al 100%. El frontend usa esto
    para mostrar un disclaimer y dejar que el usuario decida cómo proceder.
    """
    filename = _nombre_nfc(file.filename) or "upload"
    suffix = Path(filename).suffix.lower()

    if suffix == ".docx":
        # Abrir y recorrer el Word es trabajo síncrono: fuera del event loop.
        return {"has_special_images": await run_in_threadpool(docx_tiene_imagenes, await file.read())}
    if suffix != ".pdf":
        return {"has_special_images": False}

    raw_bytes = await file.read()
    try:
        has_images = await run_in_threadpool(pdf_has_embedded_images, raw_bytes)
    except Exception as exc:
        logger.warning("No se pudo chequear imágenes en '%s': %s", filename, exc)
        return {"has_special_images": False}

    return {"has_special_images": has_images}


@app.post("/api/parse")
async def api_parse(
    file: UploadFile = File(...),
):
    # La lógica completa vive en pipeline.parse_document (compartida con
    # dev/eval.py). Es síncrona y puede tardar (pdfplumber + Gemini, hasta
    # ~2 min con imágenes), así que corre en threadpool para no bloquear
    # el event loop de FastAPI.
    raw_bytes = await file.read()
    return await run_in_threadpool(_con_cupo, parse_document, raw_bytes, _nombre_nfc(file.filename) or "upload")


@app.post("/api/normalize_with_ai")
async def api_normalize_with_ai(
    file: UploadFile = File(...),
):
    """
    Alternativa in-app al flujo externo de "copia este prompt y pégalo en
    tu IA de preferencia" (Guía → Prompt IA): lee el documento COMPLETO
    como imágenes (ver pipeline.normalize_document_with_ai). Pensado para
    PDFs con imágenes incrustadas y PDFs escaneados sin capa de texto.
    """
    raw_bytes = await file.read()
    return await run_in_threadpool(_con_cupo, normalize_document_with_ai, raw_bytes, _nombre_nfc(file.filename) or "upload")


class _RespuestaCancelable(StreamingResponse):
    """StreamingResponse que activa la cancelación de la conversión cuando la
    respuesta termina por cualquier motivo: el navegador cerró la conexión
    («Cancelar», cerrar la ventana), un error al escribir, o el final normal.
    El `finally` del generador cubre la mayoría de los casos; esto cubre el
    resto (p. ej. una desconexión que corta la tarea mientras el generador
    está suspendido)."""

    def __init__(self, *args, cancelacion, **kwargs):
        super().__init__(*args, **kwargs)
        self._cancelacion = cancelacion

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._cancelacion.cancelar()


def _acepta_ia_cache(fn) -> bool:
    try:
        return "ia_cache" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _ndjson_progress_stream(fn, raw_bytes: bytes, filename: str) -> StreamingResponse:
    """
    Corre la normalización en un hilo y va enviando al navegador una línea
    JSON por evento, a medida que ocurren:

        {"type": "stage", "key": "queue", "message": ...}   ← esperando un cupo libre
        {"type": "stage", "key": "extract"|"ai"|"review", "message": ...}
        {"type": "progress", "done": 12, "expected": 40}
        {"type": "result", "data": {...}}         ← lo mismo que /api/parse
        {"type": "error", "status": 422, "detail": ...}
        {"type": "ping"}                          ← cada 15 s sin novedades

    Así la pantalla de carga muestra el avance real ("pregunta 12 de ~40")
    en vez de un temporizador que no sabe si el proceso sigue vivo. Los
    errores llegan como un evento más (la respuesta HTTP ya empezó con 200).

    Cancelar de verdad: cuando el navegador se desconecta, se activa la
    Cancelacion de esta conversión; el hilo deja de esperar cupo, corta la
    llamada a Gemini en curso y libera su cupo.
    """
    events: "queue.Queue" = queue.Queue()
    cancelacion = formatter.Cancelacion()
    con_cache = _acepta_ia_cache(fn)

    def worker() -> None:
        formatter.usar_cancelacion(cancelacion)
        con_cupo = False
        try:
            # Con los 2 cupos ocupados, la conversión espera su turno: se le
            # dice al docente (antes la pantalla quedaba muda, sin saber por
            # qué) y se sigue pudiendo cancelar mientras espera.
            if _CUPOS_CONVERSION.acquire(blocking=False):
                con_cupo = True
            else:
                events.put({"type": "stage", "key": "queue", "message": (
                    "Hay otras conversiones en curso; la tuya empieza en cuanto termine una…")})
                while not cancelacion.cancelada:
                    if _CUPOS_CONVERSION.acquire(timeout=0.5):
                        con_cupo = True
                        break
            if not con_cupo:
                return

            # Un fallo inesperado (no un error ya previsto, que llega como
            # HTTPException con su propio mensaje) se reintenta UNA vez: la IA
            # no responde igual dos veces, y lo más común es que una respuesta
            # puntual con una forma rara rompa algún paso posterior. La
            # respuesta de la IA se guarda en ia_cache: si lo que falló fue el
            # postproceso, el reintento NO vuelve a llamar a la IA (un error
            # determinista costaba el doble de llamadas). Si vuelve a fallar,
            # el mensaje dice qué pasó y dónde quedó la traza.
            ia_cache: dict = {}
            kwargs = {"ia_cache": ia_cache} if con_cache else {}
            for intento in (1, 2):
                try:
                    result = fn(raw_bytes, filename, progress=events.put, **kwargs)
                    events.put({"type": "result", "data": result})
                    return
                except formatter.ConversionCancelada:
                    return
                except HTTPException as exc:
                    events.put({"type": "error", "status": exc.status_code, "detail": exc.detail})
                    return
                except Exception as exc:  # noqa: BLE001
                    if cancelacion.cancelada:
                        return
                    logger.exception("Error inesperado procesando '%s' (intento %d de 2)", filename, intento)
                    if intento == 1:
                        events.put({"type": "stage", "key": "retry",
                                    "message": "Hubo un problema inesperado; reintentando en 2 s…"})
                        try:
                            cancelacion.esperar(2)
                        except formatter.ConversionCancelada:
                            return
                        continue
                    events.put({"type": "error", "status": 500, "detail": (
                        "Ocurrió un error inesperado al procesar el archivo, incluso después de "
                        "reintentarlo. Vuelve a intentarlo en un momento; si se repite con este "
                        f"mismo archivo, envía al desarrollador el registro «{ERROR_LOG_PATH}». "
                        f"(Detalle técnico: {_detalle_tecnico(exc)})"
                    )})
        finally:
            formatter.usar_cancelacion(None)
            if con_cupo:
                _CUPOS_CONVERSION.release()
            events.put(None)

    threading.Thread(target=worker, daemon=True).start()

    async def lines():
        # Generador asíncrono (no síncrono): al desconectarse el navegador,
        # Starlette cancela la tarea y el `finally` corre de inmediato aquí
        # (con un generador síncrono bloqueado en queue.get, nunca corría).
        ultimo = time.monotonic()
        try:
            while True:
                try:
                    event = events.get_nowait()
                except queue.Empty:
                    if time.monotonic() - ultimo >= 15:
                        ultimo = time.monotonic()
                        yield '{"type": "ping"}\n'
                    await asyncio.sleep(0.1)
                    continue
                if event is None:
                    return
                ultimo = time.monotonic()
                if isinstance(event, dict) and event.get("type") == "result":
                    # El resultado lleva las imágenes en base64 (varios MB):
                    # serializarlo aquí frenaría el progreso de otras
                    # conversiones, así que se hace en un hilo.
                    yield await run_in_threadpool(_evento_ndjson, event)
                else:
                    yield _evento_ndjson(event)
        finally:
            cancelacion.cancelar()

    return _RespuestaCancelable(
        lines(), media_type="application/x-ndjson", cancelacion=cancelacion,
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.post("/api/parse_stream")
async def api_parse_stream(file: UploadFile = File(...)):
    """Igual que /api/parse, pero informando el avance (ver _ndjson_progress_stream)."""
    raw_bytes = await file.read()
    return _ndjson_progress_stream(parse_document, raw_bytes, _nombre_nfc(file.filename) or "upload")


@app.post("/api/normalize_with_ai_stream")
async def api_normalize_with_ai_stream(file: UploadFile = File(...)):
    """Igual que /api/normalize_with_ai, pero informando el avance."""
    raw_bytes = await file.read()
    return _ndjson_progress_stream(normalize_document_with_ai, raw_bytes, _nombre_nfc(file.filename) or "upload")


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

def _evento_ndjson(event) -> str:
    return json.dumps(event, ensure_ascii=False, default=str) + "\n"


MAX_AVISOS_CABECERA = 5


def _avisos_para_cabecera(avisos) -> list:
    """Los avisos viajan en una cabecera HTTP: con muchos «Completar» de
    puntos dudosos podría crecer demasiado, así que se dejan los primeros y
    se resume el resto."""
    avisos = list(avisos or [])
    if len(avisos) <= MAX_AVISOS_CABECERA:
        return avisos
    resto = len(avisos) - MAX_AVISOS_CABECERA
    return avisos[:MAX_AVISOS_CABECERA] + [f"… y {resto} aviso{'s' if resto != 1 else ''} más."]


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
    campos_no_permitidos = [q.get("num", "?") for q in req.questions if isinstance(q, dict) and "error" in q]
    if campos_no_permitidos:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Se detectaron errores de validación en las preguntas editadas:",
                "errors": [f"Error: la Pregunta {n} trae un campo interno no permitido." for n in campos_no_permitidos],
            },
        )

    validation = validate_questions(req.questions, parsed_answer_key, strict=True)
    if not validation.is_valid:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Se detectaron errores de validación en las preguntas editadas:",
                "errors": validation.errors,
            },
        )

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
    try:
        save_conversion(req.filename, req.category, req.total_points, xml_content, editor_json)
    except (sqlite3.Error, OSError) as exc:
        logger.exception("No se pudo guardar '%s' en el historial", req.filename)
        aviso_historial = (
            "El XML se generó bien, pero no se pudo guardar en el Historial de esta aplicación "
            f"({type(exc).__name__}). Descárgalo ahora: no podrás reabrirlo desde el Historial."
        )
    return xml_content, stats, grades, aviso_historial


@app.post("/api/generate_xml")
async def api_generate_xml(req: GenerateXmlRequest):
    # Convert string keys back to int for answer_key
    try:
        parsed_answer_key = {int(k): v for k, v in req.answer_key.items()}
    except ValueError:
        raise HTTPException(status_code=422, detail="Las claves de answer_key deben ser enteros.")

    req.filename = _nombre_nfc(req.filename)
    try:
        xml_content, stats, grades, aviso_historial = await run_in_threadpool(_generate_xml_sync, req, parsed_answer_key)

        # ── 9. Return as downloadable file ──────────────────────────────
        output_filename = f"{Path(req.filename).stem}.xml"
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
@app.get("/api/history")
def api_get_history():
    return _historial(get_history_list)

@app.get("/api/history/{record_id}/download")
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

@app.get("/api/history/{record_id}/editor")
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

@app.delete("/api/history/{record_id}")
def api_delete_history(record_id: int):
    if not _historial(delete_history_item, record_id):
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    return {"deleted": True}


# ── API de Gemini ───────────────────────────────────────────────────────────
# El docente pega su clave en el modal de bienvenida; se guarda cifrada en
# la carpeta de datos (ver credenciales.py). Nunca se devuelve completa.

class RetroalimentacionBody(BaseModel):
    pregunta: Dict[str, Any]
    respuesta: Any = None


# Botón «Escribir con IA» del editor: la retroalimentación de UNA pregunta.
# Tiene su propio cupo (no espera detrás de una conversión larga).
@app.post("/api/retroalimentacion")
def api_retroalimentacion(body: RetroalimentacionBody):
    return {"retroalimentacion": _con_cupo_puntual(ayuda_ia.generar, body.pregunta, body.respuesta)}


class EnunciadoBody(BaseModel):
    pregunta: Dict[str, Any]


# Botón «Mejorar redacción» del editor: el enunciado de UNA pregunta.
@app.post("/api/mejorar_enunciado")
def api_mejorar_enunciado(body: EnunciadoBody):
    return _con_cupo_puntual(ayuda_ia.mejorar_enunciado, body.pregunta)


class ApiKeyBody(BaseModel):
    clave: str


@app.get("/api/api-key")
def api_key_status():
    return credenciales.estado()


@app.post("/api/api-key")
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


@app.delete("/api/api-key")
def api_key_delete():
    try:
        credenciales.borrar()
    except OSError as exc:
        logger.exception("No se pudo borrar la clave de la API de Gemini")
        raise HTTPException(status_code=500, detail=(
            "No se pudo borrar la clave guardada (falta permiso en la carpeta de datos de la aplicación: "
            f"{type(exc).__name__}). Revisa el permiso de esa carpeta e inténtalo de nuevo."))
    return credenciales.estado()
