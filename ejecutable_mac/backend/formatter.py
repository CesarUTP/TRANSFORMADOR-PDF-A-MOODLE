"""
formatter.py — Prefiltro Gemini para normalizar la estructura
del documento antes de que llegue al parser regex.

Flujo:
  texto_extraido → verify_and_format() → texto_garantizado → parser
"""

import re
import time
import logging
from typing import Optional
from fastapi import HTTPException
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
    SYSTEM_PROMPT,
    NOT_AN_EXAM_SENTINEL,
)

logger = logging.getLogger(__name__)

# Errores que NO se arreglan reintentando (modelo inexistente, API key
# inválida, petición mal formada): fallar de inmediato con un mensaje claro
# en vez de agotar los 3 reintentos con 10s de espera cada uno para nada.
_NON_RETRYABLE_ERRORS = (NotFound, InvalidArgument, PermissionDenied, Unauthenticated, BadRequest)



def verify_and_format(raw_text: str) -> tuple[str, bool]:
    """
    Pasa el texto por Gemini para normalizar estructura.

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
    )

    max_retries = GEMINI_MAX_RETRIES
    wait_time = GEMINI_RETRY_WAIT_SECONDS

    for attempt in range(1, max_retries + 1):
        try:
            logger.info("Gemini prefiltro: enviando texto (%d chars)... Intento %d/%d", len(raw_text), attempt, max_retries)
            response = model.generate_content(raw_text)
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

            # Consideramos que hubo reformateo si el texto cambió de forma significativa
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
