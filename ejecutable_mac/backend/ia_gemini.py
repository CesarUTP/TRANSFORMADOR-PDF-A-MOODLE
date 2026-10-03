"""
ia_gemini.py — Proveedor de IA: Gemini (Google AI Studio).

La llamada se hace directo contra la API REST con streaming (SSE), no con
el SDK: el SDK en modo REST junta toda la respuesta antes de entregarla,
así que no hay forma de saber cuántas preguntas lleva procesadas. Con SSE
las preguntas llegan a medida que se generan y la pantalla de carga puede
mostrar el avance real ("pregunta 12 de ~40, faltan ~20 s").

Aquí vive TODO lo propio de Gemini: la URL y las cabeceras, el formato del
cuerpo (systemInstruction / contents / generationConfig), la lectura del SSE,
la clasificación de los errores HTTP y de finishReason. La clave se obtiene
con credenciales.get_api_key. El resto de la app solo ve ia_proveedor.
"""

import json
import logging
import re
import threading
import time
from typing import List, Optional

import requests

from credenciales import get_api_key
from config import GEMINI_MODEL_NAME, MISSING_API_KEY_MESSAGE
from ia_cancelacion import ConversionCancelada, cancelacion_actual
from ia_proveedor import (
    ErrorIA, IAErrorHTTP, IACuotaError, IASaturadaError, IARechazadaError,
    IASinClaveError, IATimeoutError, IASinConexionError,
    OnTexto, ParteIA, ProveedorIA, RespuestaCortada, RespuestaIA, RespuestaVacia,
    normalizar_finish,
)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

logger = logging.getLogger(__name__)


# ── Errores HTTP de la API de Gemini ─────────────────────────────────────────
# Tres familias, según qué conviene hacer con cada una (ver
# ia_reintentos.generar_con_reintentos). El texto de la excepción lleva el
# cuerpo completo de la respuesta de Google: ahí vienen "Please retry in 38s"
# y el nombre de la cuota agotada ("...PerDay...").

# Nombres de siempre (los usan las pruebas y el registro de errores).
GeminiHTTPError = IAErrorHTTP
GeminiOverloadedError = IASaturadaError   # 500/502/503/504: Google saturado o con un error interno
GeminiRejectedError = IARechazadaError    # 400/401/403/404: modelo inexistente, API key inválida o petición mal formada


def _quota_retry_seconds(exc: Exception) -> float:
    """Segundos que Google pide esperar tras un 429 ("Please retry in 38.7s")."""
    m = re.search(r"retry in ([\d.]+)s", str(exc))
    return min(float(m.group(1)) + 1.0, 65.0) if m else 30.0


class GeminiQuotaError(IACuotaError):
    """429: cuota por minuto o por día agotada. Lee del cuerpo cuál de las dos
    y cuánto pide esperar Google."""

    def __init__(self, code: int, body: str):
        super().__init__(code, body, diaria="PerDay" in f"{code} {body}")
        self.espera_segundos = _quota_retry_seconds(self)


def _http_error(code: int, body: str) -> IAErrorHTTP:
    if code == 429:
        return GeminiQuotaError(code, body)
    if code in (500, 502, 503, 504):
        return IASaturadaError(code, body)
    if code in (400, 401, 403, 404):
        return IARechazadaError(code, body)
    return IAErrorHTTP(code, body)


# ── Cuerpo de la petición ───────────────────────────────────────────────────

def _parte_gemini(parte: ParteIA) -> dict:
    if parte.es_imagen:
        return {"inline_data": {"mime_type": parte.mime, "data": parte.datos_b64}}
    return {"text": parte.texto}


def construir_cuerpo(partes: List[ParteIA], *, instruccion: str = "", esquema: Optional[dict] = None,
                     temperatura: float = 0.0, max_tokens: Optional[int] = None) -> dict:
    """El JSON que espera streamGenerateContent. Sin esquema, salida de texto;
    con esquema, JSON restringido por él (decodificación con esquema)."""
    config_gen: dict = {"temperature": temperatura}
    if esquema is not None:
        config_gen["responseMimeType"] = "application/json"
        config_gen["responseSchema"] = esquema
    if max_tokens is not None:
        config_gen["maxOutputTokens"] = max_tokens
    return {
        "systemInstruction": {"parts": [{"text": instruccion}]},
        "contents": [{"role": "user", "parts": [_parte_gemini(p) for p in partes]}],
        "generationConfig": config_gen,
    }


# ── Llamada REST con streaming ──────────────────────────────────────────────

def _post(url: str, headers: dict, body: dict, timeout: int):
    """requests.post que se puede abandonar al cancelar: la petición corre en
    un hilo aparte cuando hay una Cancelacion activa, porque esperar las
    cabeceras de la respuesta puede tardar bastante y no hay otra forma de
    interrumpirlo. Si se abandona, ese hilo cierra la respuesta al recibirla."""
    kwargs = dict(
        headers=headers, json=body, stream=True,
        # (conexión, lectura entre fragmentos): una respuesta que deja de
        # llegar se corta sin esperar el tope total.
        timeout=(20, min(timeout, 120)),
    )
    canc = cancelacion_actual()
    if canc is None:
        return requests.post(url, **kwargs)
    canc.comprobar()
    estado: dict = {"resp": None, "exc": None, "abandonado": False}
    lock = threading.Lock()

    def run() -> None:
        try:
            r = requests.post(url, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — se re-lanza en el hilo que espera
            with lock:
                estado["exc"] = exc
            return
        with lock:
            abandonada = estado["abandonado"]
            if not abandonada:
                estado["resp"] = r
        if abandonada:
            try:
                r.close()
            except Exception:  # noqa: BLE001
                pass

    hilo = threading.Thread(target=run, daemon=True)
    hilo.start()
    while True:
        hilo.join(0.25)
        if not hilo.is_alive():
            break
        if canc.cancelada:
            with lock:
                estado["abandonado"] = True
            raise ConversionCancelada()
    if estado["exc"] is not None:
        raise estado["exc"]
    return estado["resp"]


def _stream_generate(body: dict, timeout: int, on_text: OnTexto) -> RespuestaIA:
    """
    Una llamada a streamGenerateContent (SSE). Va acumulando el texto y
    llama a on_text(texto_acumulado) con cada fragmento. Los errores HTTP se
    convierten en IACuotaError / IASaturadaError / IARechazadaError para el
    manejo de reintentos de ia_reintentos.
    """
    url = f"{_API_BASE}/models/{GEMINI_MODEL_NAME}:streamGenerateContent?alt=sse"
    deadline = time.monotonic() + timeout
    canc = cancelacion_actual()
    resp = _post(url, {"x-goog-api-key": get_api_key(), "Content-Type": "application/json"}, body, timeout)
    if resp.status_code != 200:
        try:
            body = resp.text
        finally:
            resp.close()
        raise _http_error(resp.status_code, body)
    # El stream SSE llega como "text/event-stream" sin charset, y requests
    # asume ISO-8859-1 en ese caso: las tildes salían como "Â¿CuÃ¡nto" en
    # vez de "¿Cuánto" (lo detectó dev/eval.py). La API siempre responde
    # en UTF-8.
    resp.encoding = "utf-8"
    if canc is not None:
        canc.registrar(resp.close)  # cancelar cierra la conexión y desbloquea la lectura

    text, finish, prompt_tokens, output_tokens, block = "", "", 0, 0, ""
    try:
        # Se parte solo por "\n" (bytes) y se decodifica a mano: con
        # decode_unicode=True, requests usa str.splitlines(), que también
        # corta en U+2028, U+2029 y U+0085 — caracteres que pueden ir dentro
        # del texto de una pregunta — y el evento JSON llegaba partido.
        for raw in resp.iter_lines(delimiter=b"\n"):
            if canc is not None:
                canc.comprobar()
            if time.monotonic() > deadline:
                raise IATimeoutError(f"La respuesta de la IA superó {timeout} s")
            line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            line = line.rstrip("\r")
            if not line or not line.startswith("data:"):
                continue
            event = json.loads(line[5:])
            if event.get("error"):
                # Un error que llega DENTRO del stream (ya con status 200),
                # típicamente la sobrecarga del modelo a mitad de respuesta.
                err = event["error"]
                raise _http_error(int(err.get("code") or 500), json.dumps(err, ensure_ascii=False))
            block = (event.get("promptFeedback") or {}).get("blockReason") or block
            for cand in event.get("candidates") or []:
                for part in (cand.get("content") or {}).get("parts") or []:
                    text += part.get("text", "")
                finish = cand.get("finishReason") or finish
            usage = event.get("usageMetadata") or {}
            prompt_tokens = usage.get("promptTokenCount", prompt_tokens) or prompt_tokens
            output_tokens = usage.get("candidatesTokenCount", output_tokens) or output_tokens
            if on_text:
                on_text(text)
    except ConversionCancelada:
        raise
    except Exception:
        # Cancelar cierra la conexión y la lectura falla con un error
        # cualquiera: eso no es un fallo que reintentar.
        if canc is not None and canc.cancelada:
            raise ConversionCancelada() from None
        raise
    finally:
        if canc is not None:
            canc.quitar(resp.close)
        resp.close()

    if not text:
        # Bloqueo de seguridad, respuesta vacía, etc.: cuenta como un intento
        # fallido más y se reintenta.
        raise RespuestaVacia(finish, block)
    if not finish:
        # El stream terminó sin finishReason: la conexión se cortó a mitad
        # de la respuesta. Sin esto, el texto truncado llegaba al parser
        # como un JSON mal formado ("Expecting value: line 50…").
        raise RespuestaCortada(f"La respuesta de la IA llegó cortada ({len(text)} caracteres)")
    return RespuestaIA(text=text, finish_reason=normalizar_finish(finish),
                       prompt_tokens=prompt_tokens, output_tokens=output_tokens)


class GeminiProveedor(ProveedorIA):
    nombre = "gemini"

    def comprobar_listo(self) -> None:
        if not get_api_key():
            raise IASinClaveError(MISSING_API_KEY_MESSAGE)

    def generar(self, partes: List[ParteIA], *, instruccion: str = "", esquema: Optional[dict] = None,
                temperatura: float = 0.0, max_tokens: Optional[int] = None, stream: bool = True,
                on_texto: OnTexto = None, timeout: int = 180) -> RespuestaIA:
        # `stream` se ignora: Gemini siempre se lee por SSE (también es lo que
        # permite cancelar y mostrar el avance).
        body = construir_cuerpo(partes, instruccion=instruccion, esquema=esquema,
                                temperatura=temperatura, max_tokens=max_tokens)
        try:
            return _stream_generate(body, timeout, on_texto)
        except (ErrorIA, ConversionCancelada):
            raise
        except requests.exceptions.ReadTimeout as exc:
            # La IA (o la conexión) dejó de responder a tiempo.
            raise IATimeoutError(str(exc)) from exc
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            # Sin internet (o Google inalcanzable): no es «servicio saturado».
            raise IASinConexionError(str(exc)) from exc
