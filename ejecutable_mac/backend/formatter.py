"""
formatter.py — Llamada a Gemini que normaliza la estructura del documento.

Dos modos (ver NORMALIZER_MODE en config.py):
  verify_and_format()   → texto con el formato propio → parser.py
  extract_structured()  → JSON restringido por RESPONSE_SCHEMA → schema_adapter.py

La llamada se hace directo contra la API REST con streaming (SSE), no con
el SDK: el SDK en modo REST junta toda la respuesta antes de entregarla,
así que no hay forma de saber cuántas preguntas lleva procesadas. Con SSE
las preguntas llegan a medida que se generan y la pantalla de carga puede
mostrar el avance real ("pregunta 12 de ~40, faltan ~20 s").
"""

import base64
import io
import json
import os
import re
import threading
import time
import logging
import weakref
from dataclasses import dataclass
from typing import Callable, List, Optional

import requests
from fastapi import HTTPException
from PIL import Image

from credenciales import get_api_key
from config import (
    MISSING_API_KEY_MESSAGE,
    GEMINI_MODEL_NAME,
    GEMINI_MAX_RETRIES,
    GEMINI_REQUEST_TIMEOUT_SECONDS,
    GEMINI_REQUEST_TIMEOUT_SECONDS_JSON,
    GEMINI_RETRY_WAIT_SECONDS,
    GEMINI_TEMPERATURE,
    GEMINI_SIN_RESPUESTA_THRESHOLD,
    GEMINI_MAX_QUALITY_ATTEMPTS,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_JSON,
    RESPONSE_SCHEMA,
    GEMINI_MAX_OUTPUT_TOKENS,
    NOT_AN_EXAM_SENTINEL,
)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Recibe el número de preguntas que la IA ya terminó de escribir.
ProgressFn = Optional[Callable[[int], None]]

logger = logging.getLogger(__name__)

# Registro por hilo de cada llamada a Gemini (tokens y segundos). Lo usa
# dev/eval.py para medir costo/latencia de cada documento; la app no lo
# lee. Es por hilo porque la evaluación procesa varios documentos en
# paralelo y cada uno debe ver solo sus propias llamadas.
_call_log = threading.local()


def reset_call_log() -> None:
    _call_log.entries = []


def get_call_log() -> List[dict]:
    return list(getattr(_call_log, "entries", []))


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


# ── Cancelación de una conversión ───────────────────────────────────────────
# «Cancelar» en la pantalla de carga cierra la conexión del navegador, pero el
# hilo que llama a Gemini seguía trabajando (y ocupando uno de los 2 cupos de
# conversión) hasta terminar la llamada y sus reintentos. Cada conversión
# tiene ahora una Cancelacion: main.py la activa al desconectarse el cliente
# y este módulo la revisa en cada línea del stream, en cada espera de
# reintento y antes de cada llamada. Va por hilo (threading.local) para no
# cambiar la firma de todas las funciones intermedias.

class ConversionCancelada(Exception):
    """El docente canceló (o cerró) la conversión: se abandona sin reintentos."""


class Cancelacion:
    def __init__(self) -> None:
        self._evento = threading.Event()
        self._lock = threading.Lock()
        self._cierres: list = []

    @property
    def cancelada(self) -> bool:
        return self._evento.is_set()

    def cancelar(self) -> None:
        """Activa la cancelación y corta cualquier conexión en curso."""
        self._evento.set()
        with self._lock:
            cierres, self._cierres = self._cierres, []
        for cierre in cierres:
            try:
                cierre()
            except Exception:  # noqa: BLE001
                pass

    def comprobar(self) -> None:
        if self._evento.is_set():
            raise ConversionCancelada()

    def esperar(self, segundos: float) -> None:
        """Como time.sleep, pero se interrumpe al cancelar."""
        if self._evento.wait(max(0.0, segundos)):
            raise ConversionCancelada()

    def registrar(self, cierre) -> None:
        """Función que corta una conexión abierta; si ya se canceló, se
        ejecuta de inmediato y se lanza ConversionCancelada."""
        with self._lock:
            if not self._evento.is_set():
                self._cierres.append(cierre)
                return
        try:
            cierre()
        except Exception:  # noqa: BLE001
            pass
        raise ConversionCancelada()

    def quitar(self, cierre) -> None:
        with self._lock:
            if cierre in self._cierres:
                self._cierres.remove(cierre)


_cancel_local = threading.local()


def usar_cancelacion(cancelacion: Optional[Cancelacion]) -> None:
    """Asocia una Cancelacion al hilo actual (None la quita)."""
    _cancel_local.actual = cancelacion


def _cancelacion_actual() -> Optional[Cancelacion]:
    return getattr(_cancel_local, "actual", None)


def comprobar_cancelacion() -> None:
    """Lanza ConversionCancelada si la conversión de este hilo se canceló."""
    c = _cancelacion_actual()
    if c is not None:
        c.comprobar()


def _esperar(segundos: float) -> None:
    c = _cancelacion_actual()
    if c is not None:
        c.esperar(segundos)
    else:
        time.sleep(max(0.0, segundos))


def _quota_retry_seconds(exc: Exception) -> float:
    """Segundos que Google pide esperar tras un 429 ("Please retry in 38.7s")."""
    m = re.search(r"retry in ([\d.]+)s", str(exc))
    return min(float(m.group(1)) + 1.0, 65.0) if m else 30.0


def _record_call(result: "_GenResult", seconds: float) -> None:
    entry = {
        "seconds": round(seconds, 2),
        "prompt_tokens": result.prompt_tokens,
        "output_tokens": result.output_tokens,
    }
    if not hasattr(_call_log, "entries"):
        _call_log.entries = []
    _call_log.entries.append(entry)

# ── Errores HTTP de la API de Gemini ─────────────────────────────────────────
# Tres familias, según qué conviene hacer con cada una (ver
# _generate_with_retries). El texto de la excepción lleva el cuerpo completo
# de la respuesta de Google: ahí vienen "Please retry in 38s" y el nombre de
# la cuota agotada ("...PerDay...").

class GeminiHTTPError(Exception):
    def __init__(self, code: int, body: str):
        self.code = code
        super().__init__(f"{code} {body}")


class GeminiQuotaError(GeminiHTTPError):
    """429: cuota por minuto o por día agotada."""


class GeminiOverloadedError(GeminiHTTPError):
    """500/502/503/504: Google saturado o con un error interno."""


class GeminiRejectedError(GeminiHTTPError):
    """400/401/403/404: modelo inexistente, API key inválida o petición
    mal formada. No se arregla reintentando: se falla de inmediato."""


def _http_error(code: int, body: str) -> GeminiHTTPError:
    if code == 429:
        return GeminiQuotaError(code, body)
    if code in (500, 502, 503, 504):
        return GeminiOverloadedError(code, body)
    if code in (400, 401, 403, 404):
        return GeminiRejectedError(code, body)
    return GeminiHTTPError(code, body)


# ── Llamada REST con streaming ──────────────────────────────────────────────

@dataclass
class _GenResult:
    text: str
    finish_reason: str
    prompt_tokens: int
    output_tokens: int


# Partes de imagen ya codificadas, por imagen (mientras la imagen exista):
# codificar una página en WebP sin pérdida es lento, y la misma lista de
# páginas se enviaba de nuevo en cada reintento de calidad y en la llamada de
# preguntas omitidas. La entrada se borra sola cuando la imagen se libera.
_partes_imagen: dict = {}


def _image_part(img: Image.Image) -> dict:
    clave = id(img)
    hit = _partes_imagen.get(clave)
    if hit is not None and hit[0]() is img:
        return hit[1]
    # WebP sin pérdida: el mismo formato que usa el SDK de Gemini, para que
    # las páginas con imágenes (código en captura, marcas de color) lleguen
    # con la misma calidad que antes de dejar el SDK.
    buf = io.BytesIO()
    img.save(buf, format="webp", lossless=True)
    parte = {"inline_data": {"mime_type": "image/webp", "data": base64.b64encode(buf.getvalue()).decode()}}
    try:
        def _olvidar(ref, clave=clave):
            actual = _partes_imagen.get(clave)
            if actual is not None and actual[0] is ref:
                _partes_imagen.pop(clave, None)
        _partes_imagen[clave] = (weakref.ref(img, _olvidar), parte)
    except TypeError:  # objeto sin soporte de weakref: simplemente no se guarda
        pass
    return parte


def _build_request(system_prompt: str, raw_text: str, page_images, generation_config: dict) -> dict:
    parts = [{"text": raw_text}] + [_image_part(img) for img in (page_images or [])]
    return {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": generation_config,
    }


class RespuestaVacia(RuntimeError):
    """Sin texto: bloqueo de seguridad u otra respuesta vacía."""

    def __init__(self, finish: str, block: str):
        self.motivo = block or finish or "desconocido"
        super().__init__(f"Respuesta vacía de la IA (finish={finish or '-'}, block={block or '-'})")


class RespuestaCortada(RuntimeError):
    """El stream terminó sin finishReason: la conexión se cortó a mitad."""


class RespuestaInterrumpida(RuntimeError):
    """La IA terminó por un motivo distinto de STOP (SAFETY, RECITATION…)."""

    def __init__(self, motivo: str):
        self.motivo = motivo
        super().__init__(f"La IA interrumpió la respuesta (finish={motivo})")


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
    canc = _cancelacion_actual()
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


def _stream_generate(body: dict, timeout: int, on_text: Optional[Callable[[str], None]]) -> _GenResult:
    """
    Una llamada a streamGenerateContent (SSE). Va acumulando el texto y
    llama a on_text(texto_acumulado) con cada fragmento. Los errores HTTP se
    convierten en GeminiQuotaError / GeminiOverloadedError /
    GeminiRejectedError para el manejo de reintentos de más abajo.
    """
    url = f"{_API_BASE}/models/{GEMINI_MODEL_NAME}:streamGenerateContent?alt=sse"
    deadline = time.monotonic() + timeout
    canc = _cancelacion_actual()
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
                raise TimeoutError(f"La respuesta de la IA superó {timeout} s")
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
    return _GenResult(text=text, finish_reason=finish, prompt_tokens=prompt_tokens, output_tokens=output_tokens)


def _progress_counter(pattern: str, progress: ProgressFn) -> Optional[Callable[[str], None]]:
    """Convierte el texto acumulado en "preguntas terminadas" y avisa solo
    cuando el número cambia. Cuenta de forma incremental: cada fragmento
    solo busca desde donde terminó la última coincidencia (antes repetía
    findall sobre todo el texto acumulado en cada fragmento: O(n²) con una
    respuesta larga)."""
    if progress is None:
        return None
    rx = re.compile(pattern)
    contadas = [0]
    desde = [0]
    largo = [0]
    last = [-1]

    def on_text(acc: str) -> None:
        if len(acc) < largo[0]:  # texto nuevo (reintento): se empieza de cero
            contadas[0], desde[0] = 0, 0
        largo[0] = len(acc)
        for m in rx.finditer(acc, desde[0]):
            contadas[0] += 1
            desde[0] = m.end()
        n = contadas[0]
        if n != last[0]:
            last[0] = n
            try:
                progress(n)
            except Exception:  # noqa: BLE001 — el aviso de progreso nunca debe romper la conversión
                pass
    return on_text


def _sin_respuesta_ratio(text: str) -> float:
    """
    Proporción de líneas de la sección RESPUESTAS marcadas SIN_RESPUESTA —
    una señal aproximada de qué tan bien "leyó" Gemini el documento en esta
    corrida en particular (más relevante detectando color en imágenes, que
    ha mostrado ser inconsistente entre llamadas idénticas). No es un
    conteo exacto de preguntas (una con varios espacios cloze puede sumar
    más de una línea), pero alcanza como señal de calidad relativa.
    """
    idx = text.find("RESPUESTAS")
    section = text[idx:] if idx >= 0 else text
    lines = re.findall(r'(?:^|\n)\d+\s+\S+', section)
    if not lines:
        return 1.0
    return section.upper().count("SIN_RESPUESTA") / len(lines)



def _contar_preguntas_texto(texto: str) -> int:
    return len(re.findall(r"(?m)^Pregunta\s+\d+:", texto))


def verify_and_format(raw_text: str, page_images: Optional[List[Image.Image]] = None,
                      progress: ProgressFn = None,
                      on_retry: Optional[Callable[[str], None]] = None,
                      permitir_reintento_calidad: bool = True) -> tuple[str, bool]:
    """
    Pasa el texto (y, si el documento es un PDF con imágenes incrustadas,
    esas páginas como imagen) por Gemini para normalizar estructura.

    page_images permite que Gemini vea código mostrado como captura de
    pantalla y respuestas marcadas solo por color de texto — contenido
    invisible para la extracción de texto plano (ver REGLA 8/9 del
    SYSTEM_PROMPT). Sigue funcionando igual que antes si se omite (.txt,
    o un PDF sin imágenes incrustadas).

    progress(n), si se pasa, recibe cuántas preguntas ("Pregunta N:") lleva
    escritas la IA mientras responde. on_retry(mensaje), si se pasa, recibe
    un aviso cada vez que hay que esperar y reintentar (Google saturado,
    límite por minuto, respuesta cortada).

    Returns:
        (texto_para_parser, fue_reformateado)
        - En caso de error de API → lanza HTTPException 503 tras 3 intentos.
    """
    # temperature=0: mismo documento, misma salida — reduce (no elimina)
    # la inconsistencia observada entre corridas idénticas.
    body = _build_request(SYSTEM_PROMPT, raw_text, page_images, {"temperature": GEMINI_TEMPERATURE})
    on_text = _progress_counter(r"(?m)^Pregunta\s+\d+:", progress)

    # Con imágenes, la petición a Gemini puede tardar bastante más que una
    # de solo texto (se ha visto hasta ~2 minutos en pruebas reales) — es
    # normal, no es que esté colgado.
    # El reintento de calidad solo vale la pena cuando el llamador confirmó
    # que hay una marca de respuesta de por medio (permitir_reintento_calidad,
    # ver pipeline._hay_marca_de_respuestas) — es ahí, y solo ahí, donde se ha
    # visto que una corrida "lee mal" la marca. Un examen sin ninguna
    # respuesta marcada (el docente completa la clave después, en el editor)
    # da SIEMPRE ratio 1.0, y antes eso bastaba para pagar hasta 3 llamadas
    # completas por cualquier imagen del documento (una foto, un logo, un
    # membrete), sin relación con el color.
    quality_attempts = GEMINI_MAX_QUALITY_ATTEMPTS if (page_images and permitir_reintento_calidad) else 1
    best_text: Optional[str] = None
    best_score = None
    best_was_reformatted = False

    for quality_attempt in range(1, quality_attempts + 1):
        try:
            result_text, was_reformatted = _call_gemini_with_retries(body, raw_text, on_text, on_retry)
        except ConversionCancelada:
            raise
        except Exception as exc:  # noqa: BLE001 — con un resultado ya bueno, un fallo de la relectura no lo pierde
            if best_text is None:
                raise
            logger.warning(
                "Gemini prefiltro: falló el intento de calidad %d/%d (%s); se usa el mejor resultado ya obtenido.",
                quality_attempt, quality_attempts, exc,
            )
            break

        ratio = _sin_respuesta_ratio(result_text) if page_images else 0.0
        n = _contar_preguntas_texto(result_text)
        logger.info(
            "Gemini prefiltro: intento de calidad %d/%d - %d preguntas, SIN_RESPUESTA ratio %.2f",
            quality_attempt, quality_attempts, n, ratio,
        )
        # Igual que en extract_structured: primero por CANTIDAD de preguntas
        # y solo después por menos SIN_RESPUESTA (el ratio baja también
        # cuando el intento omite las preguntas sin marca).
        score = (n, -ratio)
        if best_score is None or score > best_score:
            best_text, best_score, best_was_reformatted = result_text, score, was_reformatted

        if ratio <= GEMINI_SIN_RESPUESTA_THRESHOLD:
            break
        if quality_attempt < quality_attempts:
            logger.warning(
                "Gemini prefiltro: %.0f%% de las respuestas salieron SIN_RESPUESTA "
                "(umbral %.0f%%) - reintentando por calidad (%d/%d)...",
                ratio * 100, GEMINI_SIN_RESPUESTA_THRESHOLD * 100,
                quality_attempt, quality_attempts,
            )
            # Sin este aviso, la barra de progreso volvía a 0 preguntas de
            # golpe sin explicación — parecía que la conversión se hubiera
            # reiniciado sola.
            _notify(on_retry, "Verificando la calidad de la lectura de las marcas de color; releyendo el documento…")

    return (best_text, best_was_reformatted)


def _not_an_exam_error() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "message": "El archivo no parece ser una prueba o examen:",
            "errors": [
                "No se detectaron preguntas y respuestas reales, destinadas a evaluar, en el documento.",
                "Verifica que subiste el archivo correcto (no una presentación, un manual, un artículo, etc.).",
            ],
        },
    )


def _demasiado_largo_error() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "message": "El documento es demasiado largo para procesarlo de una sola vez:",
            "errors": [
                "La respuesta de la IA superó el tamaño máximo permitido.",
                "Divide el examen en partes más pequeñas y súbelas por separado.",
            ],
        },
    )


def _comprobar_finalizacion(result: "_GenResult") -> None:
    """La respuesta solo es completa si la IA terminó por STOP. MAX_TOKENS
    (texto o JSON cortado a la mitad) no se arregla reintentando: se falla con
    un mensaje claro. Cualquier otro motivo (SAFETY, RECITATION, OTHER…) se
    trata como un intento fallido, no como una respuesta parcial que
    parecería completa: se perdería contenido del examen sin avisar."""
    finish = (result.finish_reason or "").upper()
    if finish in ("", "STOP"):
        return
    if finish == "MAX_TOKENS":
        raise _demasiado_largo_error()
    raise RespuestaInterrumpida(finish)


def _call_gemini_with_retries(body: dict, raw_text: str, on_text=None, on_retry=None) -> tuple[str, bool]:
    """Modo texto: una llamada lógica que devuelve (texto_reformateado, fue_reformateado)."""

    def parse(result: _GenResult) -> tuple[str, bool]:
        _comprobar_finalizacion(result)
        result_text = result.text.strip()
        logger.info(
            "Gemini prefiltro: respuesta recibida (%d chars). Primeros 400 chars:\n%s",
            len(result_text), result_text[:400]
        )
        # Gemini responde con este centinela cuando el documento no es una
        # prueba real (ver PASO 0 del SYSTEM_PROMPT) — se detecta por un
        # texto corto que contiene el centinela para no dar falsos
        # positivos si por alguna razón apareciera dentro de un examen
        # legítimo (muchísimo más largo).
        if len(result_text) < 200 and NOT_AN_EXAM_SENTINEL in result_text:
            logger.info("Gemini prefiltro: el documento no parece ser una prueba/examen.")
            raise _not_an_exam_error()
        return (result_text, result_text.strip() != raw_text.strip())

    return _generate_with_retries(body, len(raw_text), parse, GEMINI_REQUEST_TIMEOUT_SECONDS, on_text, on_retry)


# Esperas ante "el modelo está saturado" (503 de Google). Es habitual en
# el plan gratuito y suele durar segundos o pocos minutos, así que se
# espera cada vez más antes de rendirse (~1.5 min en total), avisando en
# pantalla para que el docente no crea que la app se colgó.
_OVERLOAD_WAITS = (5, 10, 20, 30, 30)


def _notify(on_retry: Optional[Callable[[str], None]], message: str) -> None:
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


def _generate_with_retries(body: dict, input_chars: int, parse, timeout: int, on_text=None,
                           on_retry: Optional[Callable[[str], None]] = None, *,
                           quota_waits: int = 5, overload_waits=None,
                           quota_max_seconds: Optional[float] = None):
    """
    Una llamada "lógica" a Gemini, con el reintento por FALLO DE RED/API de
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
    # con esperar lo que Google indica. Tiene su propio contador para no
    # gastar los reintentos normales esperando la cuota.
    quota_waits_left = quota_waits
    overload_waits = list(_OVERLOAD_WAITS if overload_waits is None else overload_waits)
    # Fallos deterministas (un timeout o un bloqueo de seguridad se repiten
    # igual con el mismo documento): se reintentan UNA vez, no todas las veces.
    timeouts = 0
    bloqueos = 0
    ultimo_fallo, ultimo_detalle = "otro", ""

    if not get_api_key():
        raise HTTPException(status_code=503, detail=MISSING_API_KEY_MESSAGE)

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
            result = _stream_generate(body, timeout, on_text)
            _record_call(result, time.monotonic() - t0)
            return parse(result)

        except ConversionCancelada:
            raise

        except GeminiQuotaError as exc:
            if "PerDay" in str(exc):
                # Cuota DIARIA agotada (el plan gratuito admite 500
                # peticiones por día y por modelo): esperar un minuto no
                # sirve de nada, así que se avisa de inmediato en vez de
                # hacer esperar al docente ~5 minutos de reintentos inútiles.
                logger.error("Gemini prefiltro: cuota DIARIA agotada.")
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Se alcanzó el límite diario de uso del servicio de IA. "
                        "Se restablece automáticamente cada día (medianoche, hora del Pacífico). "
                        "Si esto ocurre seguido, conviene usar una API key con facturación activada."
                    ),
                )
            delay = _quota_retry_seconds(exc)
            if quota_waits_left <= 0 or (quota_max_seconds is not None and delay > quota_max_seconds):
                logger.error("Gemini prefiltro: cuota agotada de forma persistente.")
                raise HTTPException(
                    status_code=503,
                    detail="Se alcanzó el límite de uso del servicio de IA. Espera un minuto e intenta de nuevo.",
                )
            quota_waits_left -= 1
            attempt -= 1
            logger.warning("Gemini prefiltro: cuota por minuto agotada (429); esperando %.0fs.", delay)
            _notify(on_retry, f"Límite por minuto del servicio de IA alcanzado: se continúa en {delay:.0f} s…")
            _esperar(delay)

        except GeminiOverloadedError as exc:
            # Google saturado o con un error interno: no es un problema del
            # documento, así que tiene su propio contador y esperas crecientes.
            if not overload_waits:
                logger.error("Gemini prefiltro: servicio saturado de forma persistente. Detalle: %s", exc)
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "El servicio de IA de Google está saturado en este momento (no es un "
                        "problema del documento). Intenta de nuevo en unos minutos."
                    ),
                )
            attempt -= 1
            delay = overload_waits.pop(0)
            logger.warning("Gemini prefiltro: servicio saturado (%s); reintento en %ds.", exc.code, delay)
            _notify(on_retry, f"El servicio de IA está saturado; reintentando en {delay} s…")
            _esperar(delay)

        except HTTPException:
            # Ya es un error nuestro con status/detail bien formados (ej. el
            # rechazo de "documento no es una prueba") — no es un fallo
            # transitorio de Gemini, así que no debe reintentarse ni
            # convertirse en un 503 genérico por el "except Exception" de abajo.
            raise
        except GeminiRejectedError as exc:
            logger.error(
                "Gemini prefiltro: error no recuperable (%s). No se reintenta. Detalle: %s",
                type(exc).__name__, exc,
            )
            # 401/403: la clave no es válida o Google se la revocó. En esta
            # app el docente ES quien administra su propia clave — antes se
            # le decía "contacta al administrador del sistema", un rol que
            # aquí no existe y no le decía qué hacer.
            if exc.code in (401, 403):
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Google rechazó tu clave de la API de Gemini (no es válida o fue "
                        "revocada). Ábrela desde «Acerca de → API de Gemini» y pega una "
                        "clave nueva de https://aistudio.google.com/apikey."
                    ),
                )
            raise HTTPException(
                status_code=502,
                detail=(
                    "El servicio de IA rechazó la solicitud (posible configuración "
                    f"inválida del modelo o del documento). Detalle técnico: error HTTP {exc.code}."
                ),
            )
        except (TimeoutError, requests.exceptions.ReadTimeout) as exc:
            # La IA (o la conexión) dejó de responder a tiempo. NO es "sin
            # internet" ni "muy concurrido", y con el mismo documento vuelve a
            # pasar: se reintenta una sola vez.
            timeouts += 1
            logger.warning("Gemini prefiltro: tiempo agotado en el intento %d/%d. Detalle: %s", attempt, max_retries, exc)
            if timeouts >= 2 or attempt >= max_retries:
                logger.error("Gemini prefiltro: tiempo agotado de forma repetida.")
                raise _fallo_final("timeout", timeout)
            _notify(on_retry, "La IA tardó demasiado en responder; reintentando una vez…")
            _esperar(wait_time)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            # Sin internet (o Google inalcanzable) NO es lo mismo que "el
            # servicio está saturado" — antes se agrupaba con el genérico
            # de abajo y el docente recibía un mensaje que apuntaba a
            # esperar, cuando lo que hacía falta era revisar su conexión.
            logger.warning(
                "Gemini prefiltro: sin conexión en el intento %d/%d. Detalle: %s",
                attempt, max_retries, exc
            )
            if attempt < max_retries:
                _notify(on_retry, "No se pudo conectar con el servicio de IA; reintentando…")
                _esperar(wait_time)
            else:
                logger.error("Gemini prefiltro: sin conexión tras %d intentos.", max_retries)
                raise HTTPException(
                    status_code=503,
                    detail="No se pudo conectar con el servicio de IA de Google. Revisa tu conexión a internet e inténtalo de nuevo."
                )
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
                _notify(on_retry, "La respuesta de la IA llegó incompleta; reintentando…")
                _esperar(wait_time)
            else:
                logger.error("Gemini prefiltro no disponible tras %d intento(s).", attempt)
                raise _fallo_final(ultimo_fallo, timeout, ultimo_detalle)


# ══════════════════════════════════════════════════════════════════════════
# Modo JSON: salida estructurada con esquema (NORMALIZER_MODE="json")
# ══════════════════════════════════════════════════════════════════════════

def _parse_structured_response(result: _GenResult) -> dict:
    # MAX_TOKENS: JSON cortado a la mitad, no se puede leer y reintentar da
    # lo mismo. Cualquier otro motivo distinto de STOP (SAFETY…) es un
    # intento fallido con su propio mensaje (ver _comprobar_finalizacion).
    _comprobar_finalizacion(result)
    data = json.loads(result.text)
    logger.info(
        "Gemini prefiltro (JSON): es_examen=%s, %d pregunta(s).",
        data.get("es_examen"), len(data.get("preguntas") or []),
    )
    if data.get("es_examen") is False:
        logger.info("Gemini prefiltro: el documento no parece ser una prueba/examen.")
        raise _not_an_exam_error()
    return data


def _unanswered_ratio(data: dict) -> float:
    """Equivalente estructurado de _sin_respuesta_ratio: proporción de
    preguntas autocalificables que salieron sin respuesta marcada."""
    graded = [q for q in data.get("preguntas") or [] if q.get("tipo") != "essay"]
    if not graded:
        return 1.0
    return sum(1 for q in graded if not q.get("respuesta_marcada")) / len(graded)


def extract_structured(raw_text: str, page_images: Optional[List[Image.Image]] = None,
                       progress: ProgressFn = None,
                       on_retry: Optional[Callable[[str], None]] = None,
                       permitir_reintento_calidad: bool = True) -> dict:
    """
    Igual que verify_and_format, pero el modelo devuelve JSON restringido por
    RESPONSE_SCHEMA (decodificación con esquema: la forma de la salida está
    garantizada), que schema_adapter convierte a lo que consume el editor.
    Mismo reintento de calidad que el modo texto cuando hay imágenes.
    progress(n) recibe cuántas preguntas lleva escritas la IA ("orden" es
    el primer campo de cada pregunta en el esquema).
    """
    body = _build_request(SYSTEM_PROMPT_JSON, raw_text, page_images, {
        "temperature": GEMINI_TEMPERATURE,
        "responseMimeType": "application/json",
        "responseSchema": RESPONSE_SCHEMA,
        "maxOutputTokens": GEMINI_MAX_OUTPUT_TOKENS,
    })
    on_text = _progress_counter(r'"orden"\s*:', progress)

    # Ver el comentario equivalente en verify_and_format: sin
    # permitir_reintento_calidad=False, cualquier imagen (sin relación con
    # color) en un examen sin respuestas marcadas pagaba hasta 3 llamadas
    # completas por nada.
    quality_attempts = GEMINI_MAX_QUALITY_ATTEMPTS if (page_images and permitir_reintento_calidad) else 1
    best: Optional[dict] = None
    best_score = None
    for quality_attempt in range(1, quality_attempts + 1):
        try:
            data = _generate_with_retries(body, len(raw_text), _parse_structured_response,
                                          GEMINI_REQUEST_TIMEOUT_SECONDS_JSON, on_text, on_retry)
        except ConversionCancelada:
            raise
        except Exception as exc:  # noqa: BLE001 — con un resultado ya bueno, un fallo de la relectura no lo pierde
            if best is None:
                raise
            logger.warning(
                "Gemini prefiltro (JSON): falló el intento de calidad %d/%d (%s); se usa el mejor resultado ya obtenido.",
                quality_attempt, quality_attempts, exc,
            )
            break
        ratio = _unanswered_ratio(data) if page_images else 0.0
        n = len(data.get("preguntas") or [])
        logger.info(
            "Gemini prefiltro (JSON): intento de calidad %d/%d - %d preguntas, sin respuesta %.2f",
            quality_attempt, quality_attempts, n, ratio,
        )
        # Se elige primero por CANTIDAD de preguntas y solo después por
        # menos "sin respuesta": elegir solo por el ratio premiaba al
        # intento que omitía las preguntas sin marca — el ratio baja
        # justamente porque esas preguntas desaparecen.
        score = (n, -ratio)
        if best_score is None or score > best_score:
            best, best_score = data, score
        if ratio <= GEMINI_SIN_RESPUESTA_THRESHOLD:
            break
        if quality_attempt < quality_attempts:
            _notify(on_retry, "Verificando la calidad de la lectura de las marcas de color; releyendo el documento…")
    return best


# ── Preguntas omitidas: llamada dirigida de seguimiento ─────────────────────
# Cuando el código detecta (ver imagenes.candidatas_omitidas_numeradas) que
# la IA se saltó una o dos preguntas puntuales, se le pide SOLO esas — mucho
# más barato y rápido que repetir la conversión entera, y ataca el fallo
# real más común observado en la práctica (la IA omite una pregunta que es
# solo una imagen con un enunciado corto, tipo "17. Del siguiente código…").

_PREFIJO_FALTANTES = """CONTEXTO ESPECIAL: ya se transcribió casi todo un examen a la estructura de abajo. A continuación tienes SOLO los fragmentos de las preguntas que faltaron, tal como aparecen en el documento original, separados por "=== FRAGMENTO N ===".

Devuelve una entrada en "preguntas" por CADA fragmento, EN EL MISMO ORDEN, con "orden" igual al número de fragmento (1, 2, 3…) — ni una más, ni una menos. Si un fragmento no alcanza para transcribirlo con confianza (quedó cortado, o no se entiende sin más contexto), igual devuélvelo como "tipo":"essay" con el texto tal cual y "confianza":"baja" — nunca lo omitas. No repitas ninguna otra pregunta del examen ni agregues ninguna que no esté en un fragmento.

"es_examen" debe ser SIEMPRE true en esta respuesta: ya se confirmó que el documento completo es un examen: no vuelvas a evaluarlo con estos fragmentos sueltos, que por sí solos pueden no parecerlo.

El resto de las reglas de abajo (tipos de pregunta, fórmulas, marcas de color, código en imagen, etc.) aplica exactamente igual que en la conversión completa.

"""


def extract_missing(fragmentos: List[str], page_images: Optional[List[Image.Image]] = None,
                    on_retry: Optional[Callable[[str], None]] = None) -> List[dict]:
    """
    Pide SOLO las preguntas de `fragmentos` (mismo esquema que
    extract_structured, sin reintento de calidad: no vale la pena para una
    llamada tan chica). Devuelve la lista "preguntas" del esquema TAL COMO
    la devolvió la IA: cada una lleva en "orden" el número (1, 2, 3…) del
    fragmento que transcribe, y es el llamador quien las empareja con sus
    fragmentos por ese campo (ver pipeline._completar_omitidas) — emparejar
    por posición ponía el texto de un fragmento en el hueco de otro si la
    IA devolvía menos preguntas o las reordenaba.

    Es "mejor esfuerzo": cualquier fallo (red, cuota, JSON inválido) se
    registra y devuelve [] en vez de propagar la excepción — el llamador
    (pipeline._completar_omitidas) sigue sin esta mejora, exactamente como
    si no se hubiera intentado. Nunca debe ser la causa de que una
    conversión que sí venía bien termine en error. (Cancelar sí se propaga.)
    """
    if not fragmentos:
        return []
    texto = "\n\n".join(f"=== FRAGMENTO {i} ===\n{f}" for i, f in enumerate(fragmentos, 1))
    body = _build_request(_PREFIJO_FALTANTES + SYSTEM_PROMPT_JSON, texto, page_images, {
        "temperature": GEMINI_TEMPERATURE,
        "responseMimeType": "application/json",
        "responseSchema": RESPONSE_SCHEMA,
        "maxOutputTokens": GEMINI_MAX_OUTPUT_TOKENS,
    })
    try:
        data = _generate_with_retries(body, len(texto), _parse_structured_response,
                                      GEMINI_REQUEST_TIMEOUT_SECONDS_JSON, None, on_retry)
    except ConversionCancelada:
        raise
    except Exception as exc:  # noqa: BLE001 — ver el docstring: nunca debe romper la conversión
        logger.warning("No se pudieron completar las preguntas omitidas: %s", exc)
        return []
    return list(data.get("preguntas") or [])
