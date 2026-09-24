"""
main.py — FastAPI application for PDF → Moodle XML conversion.

Endpoints:
  GET  /         → serves index.html (frontend)
  POST /convert  → multipart upload (.pdf or .txt) → Moodle XML download
"""

import json
import logging
import queue
import sys
import threading
import unicodedata
from urllib.parse import quote
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from lxml import etree

from config import DEFAULT_CATEGORY, DEFAULT_TOTAL_POINTS
import credenciales
from extractor import pdf_has_embedded_images
from pipeline import parse_document, normalize_document_with_ai
from validator import validate_questions
from xml_builder import build_xml, compute_grades
from database import init_db, save_conversion, get_history_list, get_xml_content, delete_history_item, get_editor_data
from pydantic import BaseModel
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
        handler = logging.FileHandler(ERROR_LOG_PATH, encoding="utf-8")
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
    ascii_ = ascii_.replace('"', "").replace("\\", "").strip() or "examen_moodle.xml"
    return f"attachment; filename=\"{ascii_}\"; filename*=UTF-8''{quote(nfc, safe='')}"


def _detalle_tecnico(exc: Exception) -> str:
    texto = str(exc).strip().replace("\n", " ")
    return f"{type(exc).__name__}: {texto[:160]}" if texto else type(exc).__name__

app = FastAPI(title="PDF → Moodle XML", version="1.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # No usamos cookies/sesiones ni cabeceras de credenciales — "*" +
    # allow_credentials=True es una combinación inválida según el spec CORS
    # (los navegadores la rechazan si de verdad se envían credenciales).
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Question-Stats", "X-Was-Reformatted", "Content-Disposition"],
)

@app.on_event("startup")
def startup_event():
    init_db()

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
    for _sub in ("css", "js", "img"):
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
    return await run_in_threadpool(parse_document, raw_bytes, _nombre_nfc(file.filename) or "upload")


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
    return await run_in_threadpool(normalize_document_with_ai, raw_bytes, _nombre_nfc(file.filename) or "upload")


def _ndjson_progress_stream(fn, raw_bytes: bytes, filename: str) -> StreamingResponse:
    """
    Corre la normalización en un hilo y va enviando al navegador una línea
    JSON por evento, a medida que ocurren:

        {"type": "stage", "key": "extract"|"ai"|"review", "message": ...}
        {"type": "progress", "done": 12, "expected": 40}
        {"type": "result", "data": {...}}         ← lo mismo que /api/parse
        {"type": "error", "status": 422, "detail": ...}
        {"type": "ping"}                          ← cada 15 s sin novedades

    Así la pantalla de carga muestra el avance real ("pregunta 12 de ~40")
    en vez de un temporizador que no sabe si el proceso sigue vivo. Los
    errores llegan como un evento más (la respuesta HTTP ya empezó con 200).
    """
    events: "queue.Queue" = queue.Queue()

    def worker() -> None:
        # Un fallo inesperado (no un error ya previsto, que llega como
        # HTTPException con su propio mensaje) se reintenta UNA vez: la IA
        # no responde igual dos veces, y lo más común es que una respuesta
        # puntual con una forma rara rompa algún paso posterior. Si vuelve
        # a fallar, el mensaje dice qué pasó y dónde quedó la traza.
        try:
            for intento in (1, 2):
                try:
                    result = fn(raw_bytes, filename, progress=events.put)
                    events.put({"type": "result", "data": result})
                    return
                except HTTPException as exc:
                    events.put({"type": "error", "status": exc.status_code, "detail": exc.detail})
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Error inesperado procesando '%s' (intento %d de 2)", filename, intento)
                    if intento == 1:
                        events.put({"type": "stage", "key": "retry",
                                    "message": "Hubo un problema inesperado; reintentando en 2 s…"})
                        time.sleep(2)
                        continue
                    events.put({"type": "error", "status": 500, "detail": (
                        "Ocurrió un error inesperado al procesar el archivo, incluso después de "
                        "reintentarlo. Vuelve a intentarlo en un momento; si se repite con este "
                        f"mismo archivo, envía al desarrollador el registro «{ERROR_LOG_PATH}». "
                        f"(Detalle técnico: {_detalle_tecnico(exc)})"
                    )})
        finally:
            events.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def lines():
        while True:
            try:
                event = events.get(timeout=15)
            except queue.Empty:
                yield '{"type": "ping"}\n'
                continue
            if event is None:
                return
            yield json.dumps(event, ensure_ascii=False, default=str) + "\n"

    return StreamingResponse(
        lines(), media_type="application/x-ndjson",
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
    total_points: float
    questions: List[Dict[str, Any]]
    answer_key: Dict[str, Any]

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
    xml_content, stats = build_xml(
        req.questions, parsed_answer_key, category=req.category, grades=grades,
    )

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
    save_conversion(req.filename, req.category, req.total_points, xml_content, editor_json)
    return xml_content, stats, grades


@app.post("/api/generate_xml")
async def api_generate_xml(req: GenerateXmlRequest):
    # Convert string keys back to int for answer_key
    try:
        parsed_answer_key = {int(k): v for k, v in req.answer_key.items()}
    except ValueError:
        raise HTTPException(status_code=422, detail="Las claves de answer_key deben ser enteros.")

    req.filename = _nombre_nfc(req.filename)
    try:
        xml_content, stats, grades = await run_in_threadpool(_generate_xml_sync, req, parsed_answer_key)

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

@app.get("/api/history")
async def api_get_history():
    return get_history_list()

@app.get("/api/history/{record_id}/download")
async def api_download_history(record_id: int):
    record = get_xml_content(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
        
    output_filename = f"{Path(record['filename']).stem}.xml"
    return Response(
        content=record["xml_content"].encode("utf-8"),
        media_type="application/xml",
        headers={"Content-Disposition": _content_disposition(output_filename)},
    )

@app.get("/api/history/{record_id}/editor")
async def api_history_editor(record_id: int):
    record = get_editor_data(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    if not record["editor_json"]:
        raise HTTPException(
            status_code=404,
            detail="Esta conversión es anterior a la opción de reabrir: solo se puede descargar.",
        )
    data = json.loads(record["editor_json"])
    return {
        "filename": record["filename"],
        "category": record["category"],
        "total_points": record["total_points"],
        "questions": data.get("questions", []),
        "answer_key": data.get("answer_key", {}),
    }

@app.delete("/api/history/{record_id}")
async def api_delete_history(record_id: int):
    if not delete_history_item(record_id):
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    return {"deleted": True}


# ── API de Gemini ───────────────────────────────────────────────────────────
# El docente pega su clave en el modal de bienvenida; se guarda cifrada en
# la carpeta de datos (ver credenciales.py). Nunca se devuelve completa.

# El CORS de arriba acepta cualquier origen; para la clave eso no basta:
# otra página web abierta en el navegador podría cambiarla o borrarla.
# Solo se aceptan peticiones de la propia app (mismo origen que el servidor).
def _solo_la_app(request: Request) -> None:
    origen = request.headers.get("origin")
    if origen is not None and origen != f"http://{request.headers.get('host', '')}":
        raise HTTPException(status_code=403, detail="Origen no permitido")


class ApiKeyBody(BaseModel):
    clave: str


@app.get("/api/api-key")
def api_key_status(request: Request):
    _solo_la_app(request)
    return credenciales.estado()


@app.post("/api/api-key")
def api_key_save(body: ApiKeyBody, request: Request):
    _solo_la_app(request)
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
    except Exception as exc:  # noqa: BLE001
        logger.exception("No se pudo guardar la clave de la API de Gemini")
        raise HTTPException(status_code=500, detail=f"La clave es válida, pero no se pudo guardar ({type(exc).__name__}).")
    return credenciales.estado()


@app.delete("/api/api-key")
def api_key_delete(request: Request):
    _solo_la_app(request)
    credenciales.borrar()
    return credenciales.estado()
