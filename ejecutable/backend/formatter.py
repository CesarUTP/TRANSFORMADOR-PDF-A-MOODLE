"""
formatter.py — Prefiltro Gemini para normalizar la estructura
del documento antes de que llegue al parser regex.

Flujo:
  texto_extraido → verify_and_format() → texto_garantizado → parser
"""

import re
import time
import logging
from typing import Optional, List
from fastapi import HTTPException
from PIL import Image
import google.generativeai as genai
from google.api_core.exceptions import (
    NotFound,
    InvalidArgument,
    PermissionDenied,
    Unauthenticated,
    BadRequest,
)

from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL_NAME,
    GEMINI_MAX_RETRIES,
    GEMINI_RETRY_WAIT_SECONDS,
    GEMINI_TEMPERATURE,
    GEMINI_SIN_RESPUESTA_THRESHOLD,
    GEMINI_MAX_QUALITY_ATTEMPTS,
    SYSTEM_PROMPT,
    NOT_AN_EXAM_SENTINEL,
)

logger = logging.getLogger(__name__)

# Errores que NO se arreglan reintentando (modelo inexistente, API key
# inválida, petición mal formada): fallar de inmediato con un mensaje claro
# en vez de agotar los 3 reintentos con 10s de espera cada uno para nada.
_NON_RETRYABLE_ERRORS = (NotFound, InvalidArgument, PermissionDenied, Unauthenticated, BadRequest)


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



def verify_and_format(raw_text: str, page_images: Optional[List[Image.Image]] = None) -> tuple[str, bool]:
    """
    Pasa el texto (y, si el documento es un PDF con imágenes incrustadas,
    esas páginas como imagen) por Gemini para normalizar estructura.

    page_images permite que Gemini vea código mostrado como captura de
    pantalla y respuestas marcadas solo por color de texto — contenido
    invisible para la extracción de texto plano (ver REGLA 8/9 del
    SYSTEM_PROMPT). Sigue funcionando igual que antes si se omite (.txt,
    o un PDF sin imágenes incrustadas).

    Returns:
        (texto_para_parser, fue_reformateado)
        - En caso de error de API → lanza HTTPException 503 tras 3 intentos.
    """
    # transport="rest" en vez del gRPC por defecto: en algunas redes
    # (proxies corporativos/universitarios, ciertas configuraciones de
    # Windows) el protocolo HTTP/2 de gRPC negocia la conexión mucho más
    # lento que REST plano sobre HTTPS — mismo resultado, sin el retraso.
    genai.configure(api_key=GEMINI_API_KEY, transport="rest")
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL_NAME,
        system_instruction=SYSTEM_PROMPT,
        # temperature=0: mismo documento, misma salida — reduce (no elimina)
        # la inconsistencia observada entre corridas idénticas.
        generation_config=genai.GenerationConfig(temperature=GEMINI_TEMPERATURE),
    )

    # Con imágenes, la petición a Gemini puede tardar bastante más que una
    # de solo texto (se ha visto hasta ~2 minutos en pruebas reales) — es
    # normal, no es que esté colgado.
    content = [raw_text, *page_images] if page_images else raw_text

    # Reintento de CALIDAD: solo tiene sentido cuando hay imágenes de por
    # medio — es ahí donde se ha visto que una corrida "lee mal" el color
    # de las marcas aunque técnicamente no haya ningún error de API. Con
    # texto plano no hay nada que una segunda lectura idéntica vaya a
    # mejorar, así que no vale la pena gastar la llamada extra.
    quality_attempts = GEMINI_MAX_QUALITY_ATTEMPTS if page_images else 1
    best_text: Optional[str] = None
    best_ratio = 1.1  # peor que cualquier ratio real (0.0-1.0)
    best_was_reformatted = False

    for quality_attempt in range(1, quality_attempts + 1):
        result_text, was_reformatted = _call_gemini_with_retries(model, content, raw_text)

        ratio = _sin_respuesta_ratio(result_text) if page_images else 0.0
        logger.info(
            "Gemini prefiltro: intento de calidad %d/%d - SIN_RESPUESTA ratio %.2f",
            quality_attempt, quality_attempts, ratio,
        )
        if ratio < best_ratio:
            best_text, best_ratio, best_was_reformatted = result_text, ratio, was_reformatted

        if ratio <= GEMINI_SIN_RESPUESTA_THRESHOLD:
            break
        if quality_attempt < quality_attempts:
            logger.warning(
                "Gemini prefiltro: %.0f%% de las respuestas salieron SIN_RESPUESTA "
                "(umbral %.0f%%) - reintentando por calidad (%d/%d)...",
                ratio * 100, GEMINI_SIN_RESPUESTA_THRESHOLD * 100,
                quality_attempt, quality_attempts,
            )

    return (best_text, best_was_reformatted)


def _call_gemini_with_retries(model, content, raw_text: str) -> tuple[str, bool]:
    """
    Una llamada "lógica" a Gemini, con el reintento por FALLO DE RED/API de
    siempre (no confundir con el reintento de calidad de verify_and_format,
    que es sobre respuestas técnicamente exitosas pero de baja calidad).
    """
    max_retries = GEMINI_MAX_RETRIES
    wait_time = GEMINI_RETRY_WAIT_SECONDS

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                "Gemini prefiltro: enviando texto (%d chars)... Intento %d/%d",
                len(raw_text), attempt, max_retries,
            )
            response = model.generate_content(content)
            result_text = response.text.strip()

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
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "El archivo no parece ser una prueba o examen:",
                        "errors": [
                            "No se detectaron preguntas y respuestas reales, destinadas a evaluar, en el documento.",
                            "Verifica que subiste el archivo correcto (no una presentación, un manual, un artículo, etc.).",
                        ],
                    },
                )

            was_reformatted = result_text.strip() != raw_text.strip()
            return (result_text, was_reformatted)

        except HTTPException:
            # Ya es un error nuestro con status/detail bien formados (ej. el
            # rechazo de "documento no es una prueba") — no es un fallo
            # transitorio de Gemini, así que no debe reintentarse ni
            # convertirse en un 503 genérico por el "except Exception" de abajo.
            raise
        except _NON_RETRYABLE_ERRORS as exc:
            logger.error(
                "Gemini prefiltro: error no recuperable (%s). No se reintenta. Detalle: %s",
                type(exc).__name__, exc,
            )
            raise HTTPException(
                status_code=502,
                detail=(
                    "El servicio de IA rechazó la solicitud (posible configuración "
                    "inválida del modelo o de la API key). Contacta al administrador "
                    f"del sistema. Detalle técnico: {type(exc).__name__}."
                ),
            )
        except Exception as exc:
            logger.warning(
                "Gemini prefiltro: fallo en el intento %d/%d. Detalle: %s",
                attempt, max_retries, exc
            )
            if attempt < max_retries:
                logger.info("Esperando %d segundos antes de reintentar...", wait_time)
                time.sleep(wait_time)
            else:
                logger.error("Gemini prefiltro no disponible tras %d intentos.", max_retries)
                raise HTTPException(
                    status_code=503,
                    detail="El servidor de procesamiento está muy concurrido en este momento. Por favor, intenta de nuevo más tarde."
                )
