"""
ia_reintentos.py — Una llamada «lógica» a la IA, con el reintento por fallo de
red/servicio de siempre. No sabe nada de Gemini: habla con el ProveedorIA que
devuelve ia_proveedor.proveedor_actual() y reacciona a los errores
NORMALIZADOS (cuota, saturación, rechazo, timeout, sin conexión, respuesta
vacía/cortada/interrumpida).

Lo usan formatter.py (conversión), ia_seleccion.py (preguntas omitidas) y
ayuda_ia.py (botones de IA del editor, con esperas más cortas).

También lleva dos utilidades de «llamada»: el registro por hilo de cada
llamada (dev/eval.py) y el límite de peticiones por minuto.
"""

import logging
import os
import threading
import time
from typing import Callable, List, Optional

from fastapi import HTTPException

from config import (
    GEMINI_MAX_RETRIES,
    GEMINI_RETRY_WAIT_SECONDS,
)
from ia_cancelacion import ConversionCancelada, comprobar_cancelacion, esperar as _esperar
from ia_proveedor import (
    ErrorConfiguracionIA, IACuotaError, IARechazadaError, IASaturadaError,
    IASinClaveError, IASinConexionError, RespuestaCortada, RespuestaIA,
    RespuestaInterrumpida, RespuestaVacia, SolicitudIA, proveedor_actual,
)

logger = logging.getLogger(__name__)

# Registro por hilo de cada llamada a la IA (tokens y segundos). Lo usa
# dev/eval.py para medir costo/latencia de cada documento; la app no lo
# lee. Es por hilo porque la evaluación procesa varios documentos en
# paralelo y cada uno debe ver solo sus propias llamadas.
_call_log = threading.local()


def reset_call_log() -> None:
    _call_log.entries = []


def get_call_log() -> List[dict]:
    return list(getattr(_call_log, "entries", []))


def _record_call(result: RespuestaIA, seconds: float) -> None:
    entry = {
        "seconds": round(seconds, 2),
        "prompt_tokens": result.prompt_tokens,
        "output_tokens": result.output_tokens,
    }
    if not hasattr(_call_log, "entries"):
        _call_log.entries = []
    _call_log.entries.append(entry)


# ── Límite de peticiones por minuto ─────────────────────────────────────────
# El plan gratuito de Gemini admite pocas peticiones por minuto (15 para
# flash-lite). GEMINI_MAX_RPM, si se define, espacia las llamadas de TODO
# el proceso (compartido entre hilos) para no llegar al límite: lo usa
# dev/eval.py, que procesa varios documentos en paralelo. La app no lo
# necesita normalmente (un usuario, una conversión a la vez).
_rpm_lock = threading.Lock()
_rpm_calls: List[float] = []


def _throttle() -> None:
    try:
        max_rpm = int(os.environ.get("GEMINI_MAX_RPM", "0"))
    except ValueError:
        max_rpm = 0
    if max_rpm <= 0:
        return
    while True:
        with _rpm_lock:
            now = time.monotonic()
            while _rpm_calls and now - _rpm_calls[0] > 60:
                _rpm_calls.pop(0)
            if len(_rpm_calls) < max_rpm:
                _rpm_calls.append(now)
                return
            wait = 60 - (now - _rpm_calls[0]) + 0.5
        _esperar(max(wait, 0.5))


# Esperas ante "el modelo está saturado" (503 de Google). Es habitual en
# el plan gratuito y suele durar segundos o pocos minutos, así que se
# espera cada vez más antes de rendirse (~1.5 min en total), avisando en
# pantalla para que el docente no crea que la app se colgó.
_OVERLOAD_WAITS = (5, 10, 20, 30, 30)


def notificar(on_retry: Optional[Callable[[str], None]], message: str) -> None:
    if on_retry is None:
        return
    try:
        on_retry(message)
    except Exception:  # noqa: BLE001 — el aviso nunca debe romper la conversión
        pass


def _fallo_final(clase: str, timeout: int, detalle: str = "") -> HTTPException:
    """Mensaje veraz según la CAUSA del último fallo (antes casi todo terminaba
    en «el servidor está muy concurrido», también un bloqueo de seguridad o un
    JSON inválido)."""
    if clase == "timeout":
        return HTTPException(status_code=503, detail=(
            f"La IA tardó demasiado en responder (más de {timeout} segundos). Puede que el "
            "documento sea muy largo o que el servicio esté lento: inténtalo de nuevo, o divide el examen en partes."))
    if clase == "bloqueo" and detalle.upper() == "MAX_TOKENS":
        return HTTPException(status_code=502, detail=(
            "La IA agotó su capacidad de respuesta sin llegar a escribir nada. "
            "Inténtalo de nuevo; si se repite con este archivo, prueba dividiéndolo."))
    if clase == "bloqueo":
        return HTTPException(status_code=502, detail=(
            "La IA no devolvió una respuesta para este documento"
            + (f" (motivo: {detalle})" if detalle else "")
            + ". Puede que su filtro de seguridad rechazara algún contenido; prueba con otro archivo o divídelo."))
    if clase == "interrumpida":
        return HTTPException(status_code=502, detail=(
            "La IA interrumpió su respuesta antes de terminarla"
            + (f" (motivo: {detalle})" if detalle else "")
            + ". Inténtalo de nuevo; si se repite con este archivo, prueba dividiéndolo."))
    if clase == "json":
        return HTTPException(status_code=502, detail=(
            "La IA devolvió una respuesta que no se pudo interpretar, incluso después de reintentar. "
            "Inténtalo de nuevo; si se repite con este archivo, envía el registro de errores al desarrollador."))
    if clase == "cortada":
        return HTTPException(status_code=503, detail=(
            "La respuesta de la IA se cortó varias veces a mitad de camino (conexión inestable). "
            "Revisa tu conexión a internet e inténtalo de nuevo."))
    return HTTPException(status_code=503, detail=(
        "No se pudo completar la lectura con la IA por un error inesperado. "
        "Inténtalo de nuevo en unos minutos."))


def generar_con_reintentos(solicitud: SolicitudIA, input_chars: int, parse, timeout: int, on_text=None,
                           on_retry: Optional[Callable[[str], None]] = None, *,
                           quota_waits: int = 5, overload_waits=None,
                           quota_max_seconds: Optional[float] = None):
    """
    Una llamada "lógica" a la IA, con el reintento por FALLO DE RED/API de
    siempre (no confundir con el reintento de calidad, que es sobre
    respuestas técnicamente exitosas pero de baja calidad). `parse` convierte
    la respuesta en el resultado; si lanza HTTPException se propaga tal
    cual, y cualquier otra excepción cuenta como un intento fallido más
    (ej. un JSON mal formado se reintenta igual que un error de red).

    quota_waits / overload_waits / quota_max_seconds acotan las esperas: las
    llamadas de UNA pregunta (botones de IA del editor) usan valores chicos
    para no dejar al docente esperando minutos sin feedback.

    Si hay una Cancelacion activa en este hilo (ver usar_cancelacion), todas
    las esperas y la lectura del stream se interrumpen con
    ConversionCancelada.
    """
    max_retries = GEMINI_MAX_RETRIES
    wait_time = GEMINI_RETRY_WAIT_SECONDS
    # Un 429 (cuota por minuto agotada) no es un fallo del servicio: basta
    # con esperar lo que el proveedor indica. Tiene su propio contador para no
    # gastar los reintentos normales esperando la cuota.
    quota_waits_left = quota_waits
    overload_waits = list(_OVERLOAD_WAITS if overload_waits is None else overload_waits)
    # Fallos deterministas (un timeout o un bloqueo de seguridad se repiten
    # igual con el mismo documento): se reintentan UNA vez, no todas las veces.
    timeouts = 0
    bloqueos = 0
    ultimo_fallo, ultimo_detalle = "otro", ""

    try:
        proveedor = proveedor_actual()
        proveedor.comprobar_listo()
    except IASinClaveError as exc:
        raise HTTPException(status_code=503, detail=exc.mensaje)
    except ErrorConfiguracionIA as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    attempt = 0
    while attempt < max_retries:
        attempt += 1
        try:
            comprobar_cancelacion()
            logger.info(
                "Gemini prefiltro: enviando contenido (%d chars de texto)... Intento %d/%d",
                input_chars, attempt, max_retries,
            )
            _throttle()
            t0 = time.monotonic()
            result = proveedor.generar(
                solicitud.partes, instruccion=solicitud.instruccion, esquema=solicitud.esquema,
                temperatura=solicitud.temperatura, max_tokens=solicitud.max_tokens,
                stream=True, on_texto=on_text, timeout=timeout,
            )
            _record_call(result, time.monotonic() - t0)
            return parse(result)

        except ConversionCancelada:
            raise

        except IACuotaError as exc:
            if exc.diaria:
                # Cuota DIARIA agotada (el plan gratuito admite 500
                # peticiones por día y por modelo): esperar un minuto no
                # sirve de nada, así que se avisa de inmediato en vez de
                # hacer esperar al docente ~5 minutos de reintentos inútiles.
                logger.error("Gemini prefiltro: cuota DIARIA agotada.")
                raise HTTPException(status_code=503, detail=proveedor.mensaje("cuota_diaria"))
            delay = exc.espera_segundos
            if quota_waits_left <= 0 or (quota_max_seconds is not None and delay > quota_max_seconds):
                logger.error("Gemini prefiltro: cuota agotada de forma persistente.")
                raise HTTPException(status_code=503, detail=proveedor.mensaje("cuota_persistente"))
            quota_waits_left -= 1
            attempt -= 1
            logger.warning("Gemini prefiltro: cuota por minuto agotada (429); esperando %.0fs.", delay)
            notificar(on_retry, f"Límite por minuto del servicio de IA alcanzado: se continúa en {delay:.0f} s…")
            _esperar(delay)

        except IASaturadaError as exc:
            # El servicio saturado o con un error interno: no es un problema
            # del documento, así que tiene su propio contador y esperas crecientes.
            if not overload_waits:
                logger.error("Gemini prefiltro: servicio saturado de forma persistente. Detalle: %s", exc)
                raise HTTPException(status_code=503, detail=proveedor.mensaje("saturada"))
            attempt -= 1
            delay = overload_waits.pop(0)
            logger.warning("Gemini prefiltro: servicio saturado (%s); reintento en %ds.", exc.code, delay)
            notificar(on_retry, f"El servicio de IA está saturado; reintentando en {delay} s…")
            _esperar(delay)

        except HTTPException:
            # Ya es un error nuestro con status/detail bien formados (ej. el
            # rechazo de "documento no es una prueba") — no es un fallo
            # transitorio de la IA, así que no debe reintentarse ni
            # convertirse en un 503 genérico por el "except Exception" de abajo.
            raise
        except IARechazadaError as exc:
            logger.error(
                "Gemini prefiltro: error no recuperable (%s). No se reintenta. Detalle: %s",
                type(exc).__name__, exc,
            )
            # 401/403: la clave no es válida o se la revocaron. En esta app el
            # docente ES quien administra su propia clave — antes se le
            # decía "contacta al administrador del sistema", un rol que aquí
            # no existe y no le decía qué hacer.
            if exc.code in (401, 403):
                raise HTTPException(status_code=502, detail=proveedor.mensaje("clave_rechazada"))
            raise HTTPException(status_code=502, detail=proveedor.mensaje("rechazada", code=exc.code))
        except TimeoutError as exc:
            # La IA (o la conexión) dejó de responder a tiempo. NO es "sin
            # internet" ni "muy concurrido", y con el mismo documento vuelve a
            # pasar: se reintenta una sola vez.
            timeouts += 1
            logger.warning("Gemini prefiltro: tiempo agotado en el intento %d/%d. Detalle: %s", attempt, max_retries, exc)
            if timeouts >= 2 or attempt >= max_retries:
                logger.error("Gemini prefiltro: tiempo agotado de forma repetida.")
                raise _fallo_final("timeout", timeout)
            notificar(on_retry, "La IA tardó demasiado en responder; reintentando una vez…")
            _esperar(wait_time)
        except IASinConexionError as exc:
            # Sin internet (o el servicio inalcanzable) NO es lo mismo que "el
            # servicio está saturado" — antes se agrupaba con el genérico
            # de abajo y el docente recibía un mensaje que apuntaba a
            # esperar, cuando lo que hacía falta era revisar su conexión.
            logger.warning(
                "Gemini prefiltro: sin conexión en el intento %d/%d. Detalle: %s",
                attempt, max_retries, exc
            )
            if attempt < max_retries:
                notificar(on_retry, "No se pudo conectar con el servicio de IA; reintentando…")
                _esperar(wait_time)
            else:
                logger.error("Gemini prefiltro: sin conexión tras %d intentos.", max_retries)
                raise HTTPException(status_code=503, detail=proveedor.mensaje("sin_conexion"))
        except Exception as exc:
            logger.warning(
                "Gemini prefiltro: fallo en el intento %d/%d. Detalle: %s",
                attempt, max_retries, exc
            )
            # Qué pasó de verdad, para el mensaje final y para no repetir
            # inútilmente lo que es determinista.
            if isinstance(exc, RespuestaVacia):
                ultimo_fallo, ultimo_detalle = "bloqueo", exc.motivo
                bloqueos += 1
            elif isinstance(exc, RespuestaInterrumpida):
                ultimo_fallo, ultimo_detalle = "interrumpida", exc.motivo
                bloqueos += 1
            elif isinstance(exc, RespuestaCortada):
                ultimo_fallo, ultimo_detalle = "cortada", ""
            elif isinstance(exc, ValueError):  # json.JSONDecodeError y afines
                ultimo_fallo, ultimo_detalle = "json", ""
            else:
                ultimo_fallo, ultimo_detalle = "otro", ""
            if attempt < max_retries and bloqueos < 2:
                logger.info("Esperando %d segundos antes de reintentar...", wait_time)
                notificar(on_retry, "La respuesta de la IA llegó incompleta; reintentando…")
                _esperar(wait_time)
            else:
                logger.error("Gemini prefiltro no disponible tras %d intento(s).", attempt)
                raise _fallo_final(ultimo_fallo, timeout, ultimo_detalle)
