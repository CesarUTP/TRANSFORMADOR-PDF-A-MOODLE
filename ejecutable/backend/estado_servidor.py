"""
estado_servidor.py — lo que comparten las rutas del servidor (rutas_*.py).

Antes vivía todo en main.py. Aquí quedan, sin cambios de comportamiento:
  - el registro de errores en archivo (errores.log) y la ruta ERROR_LOG_PATH;
  - los cupos de conversión y de ayudas de IA puntuales;
  - utilidades de respuesta (nombres NFC, Content-Disposition, detalle técnico);
  - el flujo NDJSON con progreso y cancelación real (_ndjson_progress_stream).

Es un módulo plano (sin paquetes): dev/sync_ejecutable.py solo copia los
backend/*.py de primer nivel.
"""

import asyncio
import inspect
import json
import logging
import queue
import re
import sys
import threading
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

import formatter

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
