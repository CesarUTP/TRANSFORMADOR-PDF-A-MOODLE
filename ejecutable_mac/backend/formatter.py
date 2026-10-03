"""
formatter.py — Orquestador de la lectura con IA y FACHADA de la capa de IA.

Dos modos (ver NORMALIZER_MODE en config.py):
  verify_and_format()   → texto con el formato propio → parser.py
  extract_structured()  → JSON restringido por RESPONSE_SCHEMA → schema_adapter.py
  extract_missing()     → solo las preguntas que la IA omitió (ia_seleccion.py)

Este archivo solo ARMA las llamadas y reparte el trabajo. Cada pieza vive en
su módulo, para que cambiar de proveedor de IA (p. ej. uno local) sea
agregar un módulo y no tocar la conversión:

  ia_proveedor.py   interfaz ProveedorIA, errores normalizados, proveedor_actual()
  ia_gemini.py      el proveedor Gemini (REST + SSE, errores HTTP, finishReason)
  ia_reintentos.py  una llamada lógica con reintentos, esperas y mensajes
  ia_seleccion.py   interpretar la respuesta, elegir el mejor intento, omitidas
  ia_cancelacion.py Cancelacion / ConversionCancelada
  ia_prompts.py     prompts y esquema de la respuesta

Los nombres de abajo se re-exportan porque los usan pipeline.py, main.py,
ayuda_ia.py, dev/eval.py y las pruebas. OJO: son alias de lectura. Para
SUSTITUIR una pieza en una prueba hay que parchear el módulo que la define
(p. ej. ia_reintentos.generar_con_reintentos, ia_gemini._stream_generate,
ia_reintentos._esperar), no este archivo.
"""

import logging
from typing import Callable, List, Optional

from PIL import Image

import ia_reintentos
from config import (
    GEMINI_MAX_RETRIES,
    GEMINI_REQUEST_TIMEOUT_SECONDS,
    GEMINI_REQUEST_TIMEOUT_SECONDS_JSON,
    GEMINI_TEMPERATURE,
    GEMINI_SIN_RESPUESTA_THRESHOLD,
    GEMINI_MAX_QUALITY_ATTEMPTS,
    GEMINI_MAX_OUTPUT_TOKENS,
)
from ia_prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_JSON, RESPONSE_SCHEMA, PREFIJO_FALTANTES as _PREFIJO_FALTANTES
from ia_seleccion import (
    ProgressFn,
    armar_solicitud,
    contador_de_progreso,
    elegir_mejor_intento,
    extract_missing,
    parse_structured_response,
    parser_de_texto,
    sin_respuesta_ratio,
    contar_preguntas_texto,
    unanswered_ratio,
    comprobar_finalizacion,
    no_es_examen_error,
    demasiado_largo_error,
)
from ia_proveedor import SolicitudIA

# ── Fachada: nombres que otros módulos y las pruebas ya usaban ──────────────
from ia_cancelacion import (  # noqa: F401
    Cancelacion, ConversionCancelada, comprobar_cancelacion, usar_cancelacion,
    cancelacion_actual as _cancelacion_actual, esperar as _esperar,
)
from ia_proveedor import (  # noqa: F401
    ErrorIA, IAErrorHTTP as GeminiHTTPError, IACuotaError, IASaturadaError as GeminiOverloadedError,
    IARechazadaError as GeminiRejectedError, RespuestaCortada, RespuestaInterrumpida, RespuestaVacia,
    RespuestaIA as _GenResult, _partes_imagen, parte_imagen as _image_part,
)
from ia_gemini import (  # noqa: F401
    GeminiQuotaError, _http_error, _post, _quota_retry_seconds, _stream_generate,
)
from ia_reintentos import (  # noqa: F401
    reset_call_log, get_call_log, _record_call, _throttle, _OVERLOAD_WAITS,
    notificar as _notify, _fallo_final, generar_con_reintentos as _generate_with_retries,
)

_progress_counter = contador_de_progreso
_sin_respuesta_ratio = sin_respuesta_ratio
_contar_preguntas_texto = contar_preguntas_texto
_unanswered_ratio = unanswered_ratio
_comprobar_finalizacion = comprobar_finalizacion
_not_an_exam_error = no_es_examen_error
_demasiado_largo_error = demasiado_largo_error
_parse_structured_response = parse_structured_response

logger = logging.getLogger(__name__)


def _call_gemini_with_retries(solicitud: SolicitudIA, raw_text: str, on_text=None, on_retry=None) -> tuple[str, bool]:
    """Modo texto: una llamada lógica que devuelve (texto_reformateado, fue_reformateado)."""
    return ia_reintentos.generar_con_reintentos(
        solicitud, len(raw_text), parser_de_texto(raw_text), GEMINI_REQUEST_TIMEOUT_SECONDS, on_text, on_retry)


def verify_and_format(raw_text: str, page_images: Optional[List[Image.Image]] = None,
                      progress: ProgressFn = None,
                      on_retry: Optional[Callable[[str], None]] = None,
                      permitir_reintento_calidad: bool = True) -> tuple[str, bool]:
    """
    Pasa el texto (y, si el documento es un PDF con imágenes incrustadas,
    esas páginas como imagen) por la IA para normalizar estructura.

    page_images permite que la IA vea código mostrado como captura de
    pantalla y respuestas marcadas solo por color de texto — contenido
    invisible para la extracción de texto plano (ver REGLA 8/9 del
    SYSTEM_PROMPT). Sigue funcionando igual que antes si se omite (.txt,
    o un PDF sin imágenes incrustadas).

    progress(n), si se pasa, recibe cuántas preguntas ("Pregunta N:") lleva
    escritas la IA mientras responde. on_retry(mensaje), si se pasa, recibe
    un aviso cada vez que hay que esperar y reintentar (servicio saturado,
    límite por minuto, respuesta cortada).

    Returns:
        (texto_para_parser, fue_reformateado)
        - En caso de error de API → lanza HTTPException 503 tras 3 intentos.
    """
    # temperature=0: mismo documento, misma salida — reduce (no elimina)
    # la inconsistencia observada entre corridas idénticas.
    solicitud = armar_solicitud(SYSTEM_PROMPT, raw_text, page_images, temperatura=GEMINI_TEMPERATURE)
    on_text = contador_de_progreso(r"(?m)^Pregunta\s+\d+:", progress)

    # Con imágenes, la petición puede tardar bastante más que una de solo
    # texto (se ha visto hasta ~2 minutos en pruebas reales) — es normal, no
    # es que esté colgado.
    # El reintento de calidad solo vale la pena cuando el llamador confirmó
    # que hay una marca de respuesta de por medio (permitir_reintento_calidad,
    # ver pipeline._hay_marca_de_respuestas) — es ahí, y solo ahí, donde se ha
    # visto que una corrida "lee mal" la marca. Un examen sin ninguna
    # respuesta marcada (el docente completa la clave después, en el editor)
    # da SIEMPRE ratio 1.0, y antes eso bastaba para pagar hasta 3 llamadas
    # completas por cualquier imagen del documento (una foto, un logo, un
    # membrete), sin relación con el color.
    quality_attempts = GEMINI_MAX_QUALITY_ATTEMPTS if (page_images and permitir_reintento_calidad) else 1

    def medir(resultado: tuple[str, bool]) -> tuple[int, float]:
        result_text = resultado[0]
        return (contar_preguntas_texto(result_text), sin_respuesta_ratio(result_text) if page_images else 0.0)

    return elegir_mejor_intento(
        lambda: _call_gemini_with_retries(solicitud, raw_text, on_text, on_retry),
        medir, intentos=quality_attempts, umbral=GEMINI_SIN_RESPUESTA_THRESHOLD,
        etiqueta="Gemini prefiltro", on_retry=on_retry,
    )


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
    solicitud = armar_solicitud(SYSTEM_PROMPT_JSON, raw_text, page_images, temperatura=GEMINI_TEMPERATURE,
                                esquema=RESPONSE_SCHEMA, max_tokens=GEMINI_MAX_OUTPUT_TOKENS)
    on_text = contador_de_progreso(r'"orden"\s*:', progress)

    # Ver el comentario equivalente en verify_and_format: sin
    # permitir_reintento_calidad=False, cualquier imagen (sin relación con
    # color) en un examen sin respuestas marcadas pagaba hasta 3 llamadas
    # completas por nada.
    quality_attempts = GEMINI_MAX_QUALITY_ATTEMPTS if (page_images and permitir_reintento_calidad) else 1

    def medir(data: dict) -> tuple[int, float]:
        return (len(data.get("preguntas") or []), unanswered_ratio(data) if page_images else 0.0)

    return elegir_mejor_intento(
        lambda: ia_reintentos.generar_con_reintentos(
            solicitud, len(raw_text), parse_structured_response,
            GEMINI_REQUEST_TIMEOUT_SECONDS_JSON, on_text, on_retry),
        medir, intentos=quality_attempts, umbral=GEMINI_SIN_RESPUESTA_THRESHOLD,
        etiqueta="Gemini prefiltro (JSON)", on_retry=on_retry,
    )
