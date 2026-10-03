"""
ia_seleccion.py — Qué hacer con lo que devuelve la IA: leerlo, decidir si es
completo, elegir entre varios intentos y pedir lo que faltó.

Es la parte «de criterio» de la conversión, independiente del proveedor:

  · interpretar la respuesta (texto con formato propio o JSON con esquema),
    rechazar lo que no es un examen y lo que llegó cortado;
  · el reintento de CALIDAD: si demasiadas respuestas salen SIN_RESPUESTA
    (señal de que esa corrida «leyó mal» las marcas de color), se vuelve a
    pedir y se elige el mejor intento — primero por CANTIDAD de preguntas y
    solo después por menos SIN_RESPUESTA;
  · la llamada dirigida de seguimiento por las preguntas omitidas
    (extract_missing).

formatter.py arma las llamadas y re-exporta estos nombres.
"""

import json
import logging
import re
from typing import Callable, List, Optional, Tuple, TypeVar

from fastapi import HTTPException
from PIL import Image

import ia_reintentos
from config import (
    GEMINI_REQUEST_TIMEOUT_SECONDS_JSON,
    GEMINI_TEMPERATURE,
    GEMINI_MAX_OUTPUT_TOKENS,
    NOT_AN_EXAM_SENTINEL,
)
from ia_cancelacion import ConversionCancelada
from ia_prompts import PREFIJO_FALTANTES, RESPONSE_SCHEMA, SYSTEM_PROMPT_JSON
from ia_proveedor import (
    ParteIA, RespuestaInterrumpida, RespuestaIA, SolicitudIA, parte_imagen, parte_texto,
)

logger = logging.getLogger(__name__)

# Recibe el número de preguntas que la IA ya terminó de escribir.
ProgressFn = Optional[Callable[[int], None]]


# ── La solicitud de un documento ────────────────────────────────────────────

def armar_solicitud(instruccion: str, texto: str, page_images, *, temperatura: float,
                    esquema: Optional[dict] = None, max_tokens: Optional[int] = None) -> SolicitudIA:
    """El texto del documento + (si las hay) sus páginas como imagen."""
    partes: List[ParteIA] = [parte_texto(texto)] + [parte_imagen(img) for img in (page_images or [])]
    return SolicitudIA(instruccion=instruccion, partes=partes, temperatura=temperatura,
                       esquema=esquema, max_tokens=max_tokens)


# ── Progreso ────────────────────────────────────────────────────────────────

def contador_de_progreso(pattern: str, progress: ProgressFn) -> Optional[Callable[[str], None]]:
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


# ── Medidas de calidad ──────────────────────────────────────────────────────

def sin_respuesta_ratio(text: str) -> float:
    """
    Proporción de líneas de la sección RESPUESTAS marcadas SIN_RESPUESTA —
    una señal aproximada de qué tan bien "leyó" la IA el documento en esta
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


def contar_preguntas_texto(texto: str) -> int:
    return len(re.findall(r"(?m)^Pregunta\s+\d+:", texto))


def unanswered_ratio(data: dict) -> float:
    """Equivalente estructurado de sin_respuesta_ratio: proporción de
    preguntas autocalificables que salieron sin respuesta marcada."""
    graded = [q for q in data.get("preguntas") or [] if q.get("tipo") != "essay"]
    if not graded:
        return 1.0
    return sum(1 for q in graded if not q.get("respuesta_marcada")) / len(graded)


# ── Respuestas inservibles como respuesta completa ──────────────────────────

def no_es_examen_error() -> HTTPException:
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


def demasiado_largo_error() -> HTTPException:
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


def comprobar_finalizacion(result: RespuestaIA) -> None:
    """La respuesta solo es completa si la IA terminó por STOP. MAX_TOKENS
    (texto o JSON cortado a la mitad) no se arregla reintentando: se falla con
    un mensaje claro. Cualquier otro motivo (SAFETY, RECITATION, OTHER…) se
    trata como un intento fallido, no como una respuesta parcial que
    parecería completa: se perdería contenido del examen sin avisar."""
    finish = (result.finish_reason or "").upper()
    if finish in ("", "STOP"):
        return
    if finish == "MAX_TOKENS":
        raise demasiado_largo_error()
    raise RespuestaInterrumpida(finish)


# ── Interpretar la respuesta ────────────────────────────────────────────────

def parser_de_texto(raw_text: str) -> Callable[[RespuestaIA], Tuple[str, bool]]:
    """Modo texto: devuelve (texto_reformateado, fue_reformateado)."""

    def parse(result: RespuestaIA) -> Tuple[str, bool]:
        comprobar_finalizacion(result)
        result_text = result.text.strip()
        logger.info(
            "Gemini prefiltro: respuesta recibida (%d chars). Primeros 400 chars:\n%s",
            len(result_text), result_text[:400]
        )
        # La IA responde con este centinela cuando el documento no es una
        # prueba real (ver PASO 0 del SYSTEM_PROMPT) — se detecta por un
        # texto corto que contiene el centinela para no dar falsos
        # positivos si por alguna razón apareciera dentro de un examen
        # legítimo (muchísimo más largo).
        if len(result_text) < 200 and NOT_AN_EXAM_SENTINEL in result_text:
            logger.info("Gemini prefiltro: el documento no parece ser una prueba/examen.")
            raise no_es_examen_error()
        return (result_text, result_text.strip() != raw_text.strip())

    return parse


def parse_structured_response(result: RespuestaIA) -> dict:
    # MAX_TOKENS: JSON cortado a la mitad, no se puede leer y reintentar da
    # lo mismo. Cualquier otro motivo distinto de STOP (SAFETY…) es un
    # intento fallido con su propio mensaje (ver comprobar_finalizacion).
    comprobar_finalizacion(result)
    data = json.loads(result.text)
    logger.info(
        "Gemini prefiltro (JSON): es_examen=%s, %d pregunta(s).",
        data.get("es_examen"), len(data.get("preguntas") or []),
    )
    if data.get("es_examen") is False:
        logger.info("Gemini prefiltro: el documento no parece ser una prueba/examen.")
        raise no_es_examen_error()
    return data


# ── Reintento de calidad: elegir el mejor de varios intentos ────────────────

R = TypeVar("R")


def elegir_mejor_intento(llamar: Callable[[], R], medir: Callable[[R], Tuple[int, float]], *,
                         intentos: int, umbral: float, etiqueta: str,
                         on_retry: Optional[Callable[[str], None]] = None) -> R:
    """
    Llama hasta `intentos` veces y devuelve el mejor resultado. `medir(r)` da
    (cantidad_de_preguntas, proporción_sin_respuesta). Se corta en cuanto la
    proporción baja del umbral.

    Se elige primero por CANTIDAD de preguntas y solo después por menos «sin
    respuesta»: elegir solo por la proporción premiaba al intento que omitía
    las preguntas sin marca — la proporción baja justamente porque esas
    preguntas desaparecen.

    Si un intento posterior falla y ya hay un resultado, ese fallo no lo
    pierde (se usa el mejor obtenido); sin ningún resultado, el error se
    propaga. Cancelar siempre se propaga.
    """
    best: Optional[R] = None
    hay_mejor = False
    best_score = None
    for quality_attempt in range(1, intentos + 1):
        try:
            resultado = llamar()
        except ConversionCancelada:
            raise
        except Exception as exc:  # noqa: BLE001 — con un resultado ya bueno, un fallo de la relectura no lo pierde
            if not hay_mejor:
                raise
            logger.warning(
                "%s: falló el intento de calidad %d/%d (%s); se usa el mejor resultado ya obtenido.",
                etiqueta, quality_attempt, intentos, exc,
            )
            break
        n, ratio = medir(resultado)
        logger.info(
            "%s: intento de calidad %d/%d - %d preguntas, sin respuesta %.2f",
            etiqueta, quality_attempt, intentos, n, ratio,
        )
        score = (n, -ratio)
        if best_score is None or score > best_score:
            best, best_score, hay_mejor = resultado, score, True
        if ratio <= umbral:
            break
        if quality_attempt < intentos:
            logger.warning(
                "%s: %.0f%% de las respuestas salieron sin respuesta marcada "
                "- reintentando por calidad (%d/%d)...",
                etiqueta, ratio * 100, quality_attempt, intentos,
            )
            # Sin este aviso, la barra de progreso volvía a 0 preguntas de
            # golpe sin explicación — parecía que la conversión se hubiera
            # reiniciado sola.
            ia_reintentos.notificar(on_retry, "Verificando la calidad de la lectura de las marcas de color; releyendo el documento…")
    return best  # type: ignore[return-value]


# ── Preguntas omitidas: llamada dirigida de seguimiento ─────────────────────
# Cuando el código detecta (ver imagenes.candidatas_omitidas_numeradas) que
# la IA se saltó una o dos preguntas puntuales, se le pide SOLO esas — mucho
# más barato y rápido que repetir la conversión entera, y ataca el fallo
# real más común observado en la práctica (la IA omite una pregunta que es
# solo una imagen con un enunciado corto, tipo "17. Del siguiente código…").

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
    solicitud = armar_solicitud(PREFIJO_FALTANTES + SYSTEM_PROMPT_JSON, texto, page_images,
                                temperatura=GEMINI_TEMPERATURE, esquema=RESPONSE_SCHEMA,
                                max_tokens=GEMINI_MAX_OUTPUT_TOKENS)
    try:
        data = ia_reintentos.generar_con_reintentos(solicitud, len(texto), parse_structured_response,
                                                    GEMINI_REQUEST_TIMEOUT_SECONDS_JSON, None, on_retry)
    except ConversionCancelada:
        raise
    except Exception as exc:  # noqa: BLE001 — ver el docstring: nunca debe romper la conversión
        logger.warning("No se pudieron completar las preguntas omitidas: %s", exc)
        return []
    return list(data.get("preguntas") or [])
