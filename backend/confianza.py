"""
confianza.py — De dónde salió la respuesta de cada pregunta y cuánto conviene
fiarse de ella. Dos datos INFORMATIVOS que el editor muestra al docente:

    origen_respuesta   "documento" | "marca" | "ia"      (el editor añade
                       "docente" cuando el profesor la edita)
    confianza          "alta" | "media" | "baja"

Nunca cambian ni bloquean una respuesta: el principio del producto es que la
clave o marca del documento manda, que sin marca no se inventa respuesta y que
todo lo que hace la IA queda visible. Esto solo lo hace visible.

Reglas (función PURA `evaluar`, sin leer archivos ni llamar a la IA)
-------------------------------------------------------------------
Origen — el primero que se cumpla:
  1. «documento»: la respuesta salió de una clave explícita del propio
     documento (answer_key[n]["from_key"], que fija schema_adapter).
  2. «marca»: la leyó el código de una marca (color, resaltado, subrayado,
     negrita, cuadro con X, X en verdadero/falso): data["answer_from_marks"].
  3. «documento» también si el llamador lo afirma con
     contexto["desde_documento"] y ninguna marca pisó la respuesta (respuesta
     corta o numérica copiada de la clave; en el modo texto, clave del
     documento que coincide con la que devolvió la IA).
  4. «ia»: la interpretó la IA sin respaldo determinista.
  Sin origen (None) en las preguntas de respuesta abierta (essay), en tipos
  desconocidos, en las omitidas por error y en las que no tienen respuesta
  (SIN_RESPUESTA): no hay nada que fiar ni que dudar.

Confianza:
  · «baja» si hay UNA señal de duda, sea cual sea el origen:
      - data["color_review_hint"]: la página tenía color y la IA tuvo que
        interpretarlo («revisar marca»);
      - data["low_confidence"]: la IA misma declaró confianza baja (imagen
        borrosa, cortada…);
      - la pregunta fue rescatada o recuperada por un reintento
        (contexto["rescatada"]): se pidió aparte porque la IA la había omitido;
      - la respuesta es ambigua: en opción múltiple, una respuesta de la clave
        que coincide con varias opciones por igual.
  · «alta» si el origen es «documento» o «marca» y no hay señal de duda.
  · «media» si el origen es «ia» y no hay señal de duda.

`low_confidence` NO se toca: sigue siendo la señal propia de la IA que ya
usaban el validador y el editor; aquí solo se LEE como una de las señales.
"""

from typing import Any, Dict, Optional, Tuple

from modelo import SIN_RESPUESTA, Clave, Pregunta

# Tipos con una respuesta correcta que elegir (essay y desconocidos, no).
TIPOS_CON_RESPUESTA = ("multichoice", "truefalse", "matching", "cloze", "shortanswer", "numerical")

ORIGEN_DOCUMENTO = "documento"
ORIGEN_MARCA = "marca"
ORIGEN_IA = "ia"

CONFIANZA_ALTA = "alta"
CONFIANZA_MEDIA = "media"
CONFIANZA_BAJA = "baja"


def _sin_respuesta(clave: Optional[Dict[str, Any]]) -> bool:
    respuesta = (clave or {}).get("answer")
    if not isinstance(respuesta, str):
        return True
    respuesta = respuesta.strip()
    return not respuesta or SIN_RESPUESTA in respuesta


def _ambigua(pregunta: Dict[str, Any], clave: Dict[str, Any]) -> bool:
    """¿Alguna respuesta de la clave coincide con varias opciones por igual?
    Solo opción múltiple (en los demás tipos la respuesta no se elige por texto)."""
    if pregunta.get("type") != "multichoice":
        return False
    try:
        p = Pregunta.desde_dict(pregunta)
        p.respuesta = Clave.desde_dict(clave)
        _, fallos = p.resolver_correctas()
    except Exception:  # noqa: BLE001 — una pregunta rara nunca debe romper la conversión
        return False
    return any(motivo == "ambigua" for _, motivo in fallos)


def evaluar(pregunta: Dict[str, Any], clave: Optional[Dict[str, Any]] = None,
            contexto: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], Optional[str]]:
    """(origen, confianza) de una pregunta. Ver el docstring del módulo.

    pregunta  {"num", "type", "data": {...}} (la forma interna de siempre)
    clave     answer_key[num] ({"type", "answer", "from_key"?…}) o None
    contexto  {"rescatada": bool, "desde_documento": bool}; todo opcional
    """
    contexto = contexto or {}
    if not isinstance(pregunta, dict) or pregunta.get("type") not in TIPOS_CON_RESPUESTA or "error" in pregunta:
        return None, None
    if _sin_respuesta(clave):
        return None, None
    data = pregunta.get("data")
    data = data if isinstance(data, dict) else {}

    if clave.get("from_key"):
        origen = ORIGEN_DOCUMENTO
    elif data.get("answer_from_marks"):
        origen = ORIGEN_MARCA   # una marca leída en código pisó la respuesta de la IA
    elif contexto.get("desde_documento"):
        origen = ORIGEN_DOCUMENTO
    else:
        origen = ORIGEN_IA

    duda = (bool(data.get("color_review_hint")) or bool(data.get("low_confidence"))
            or bool(contexto.get("rescatada")) or _ambigua(pregunta, clave))
    if duda:
        return origen, CONFIANZA_BAJA
    return origen, (CONFIANZA_MEDIA if origen == ORIGEN_IA else CONFIANZA_ALTA)


def etiquetar(preguntas, answer_key: Dict[Any, Dict[str, Any]],
              rescatadas=(), desde_documento=()) -> int:
    """Escribe origen_respuesta y confianza en el `data` de cada pregunta que
    los tenga (los quita si ya no corresponden). `rescatadas` y
    `desde_documento` son conjuntos de números de pregunta. Devuelve cuántas
    quedaron etiquetadas."""
    rescatadas, desde_documento = set(rescatadas), set(desde_documento)
    n = 0
    for q in preguntas:
        data = q.get("data")
        if not isinstance(data, dict):
            continue
        num = q.get("num")
        origen, confianza = evaluar(
            q, (answer_key or {}).get(num),
            {"rescatada": num in rescatadas, "desde_documento": num in desde_documento},
        )
        if origen is None:
            data.pop("origen_respuesta", None)
            data.pop("confianza", None)
            continue
        data["origen_respuesta"] = origen
        data["confianza"] = confianza
        n += 1
    return n


def clave_documento_coincide(original: Dict[Any, Dict[str, Any]], reformada: Dict[Any, Dict[str, Any]]) -> set:
    """Modo texto: números cuya respuesta se puede atribuir al documento.
    Solo si el propio documento trae su clave (sección RESPUESTAS) y la que
    devolvió la IA es la misma en TODAS las preguntas (mismas numeraciones,
    mismas respuestas): ahí la IA no renumeró ni cambió nada y la clave es la
    del documento. En cualquier otro caso, conjunto vacío (la respuesta se
    cuenta como de la IA: ante la duda, no se atribuye al documento)."""
    def _n(d: Dict[str, Any]) -> str:
        return " ".join(str(d.get("answer") or "").lower().split())
    if not original or set(original) != set(reformada):
        return set()
    if any(_n(original[k]) != _n(reformada[k]) for k in original):
        return set()
    return set(original)


def senales_del_payload(payload: Dict[str, Any]) -> Tuple[set, set]:
    """Modo JSON: (rescatadas, desde_documento) por número de pregunta, con la
    misma numeración que schema_adapter.adapt (posición según «orden»).
    rescatadas: las que trajo el reintento de preguntas omitidas
    (pipeline._completar_omitidas las marca con «_rescatada»).
    desde_documento: respuesta corta o numérica con clave explícita copiada
    del documento (para opción múltiple, V/F y emparejamiento ya lo dice
    answer_key[n]["from_key"])."""
    crudas = sorted(payload.get("preguntas") or [], key=lambda q: (q.get("orden") or 0))
    rescatadas, desde_documento = set(), set()
    for num, q in enumerate(crudas, start=1):
        if q.get("_rescatada"):
            rescatadas.add(num)
        if q.get("tipo") in ("shortanswer", "numerical") and str(q.get("clave_texto") or "").strip():
            desde_documento.add(num)
    return rescatadas, desde_documento
