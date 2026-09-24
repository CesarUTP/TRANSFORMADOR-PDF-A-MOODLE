"""
answer_matching.py — Coincidencia difusa de respuesta-contra-opción,
compartida entre validator.py (decide si una pregunta pasa o se omite) y
xml_builder.py (decide qué opción marcar como correcta en el XML final).

Antes cada archivo tenía su propia lógica de fallback, y solo validator.py
tenía el salvavidas de "respuesta truncada" — una pregunta podía pasar la
validación gracias a ese salvavidas pero luego xml_builder.py, sin la misma
lógica, le asignaba la opción incorrecta por defecto en el XML generado.
Centralizarlo aquí evita que los dos vuelvan a divergir.
"""

import difflib
import re
from typing import List, Tuple

_PREFIX_FALLBACK_MIN_LEN = 20  # evita falsos positivos con fragmentos cortos/genéricos


def is_truncated_answer_match(target: str, option: str) -> bool:
    """
    Salvavidas contra un fallo de generación ya observado en la práctica:
    Gemini a veces corta una respuesta larga a mitad de palabra al
    transcribirla a RESPUESTAS (ej. "...propósito d" en vez de
    "...propósito de su empleo...") en vez de completarla — no es un
    problema del documento original ni de nuestro parser (ambos probados),
    es la IA cortando su propia respuesta. Un fragmento de al menos
    _PREFIX_FALLBACK_MIN_LEN caracteres que coincide casi exactamente con
    el INICIO de una opción es prácticamente inequívoco: ningún examen
    legítimo repite el mismo inicio largo en dos opciones distintas.

    Se espera que `target` y `option` ya vengan en minúsculas (el llamador
    decide la normalización — aquí no se asume nada sobre mayúsculas).
    """
    if len(target) < _PREFIX_FALLBACK_MIN_LEN:
        return False
    prefix_len = min(len(target), len(option))
    return difflib.SequenceMatcher(None, target[:prefix_len], option[:prefix_len]).ratio() > 0.9


# ── Separadores de la forma interna ──────────────────────────────────────────
# La clave guarda varias respuestas correctas de una misma pregunta unidas con
# " | ", y las opciones de un hueco Cloze van unidas con " / ". Antes se
# separaba por "|" y "/" a secas, y un texto que contiene esos caracteres
# (la opción "|" de un examen de programación, "km/h", "TCP/IP") se partía en
# pedazos o se perdía (medido en dev/eval_results/RESULTADOS.md, x08). Ahora el
# separador es el carácter CON espacios a ambos lados: "|" solo, "km/h" o
# "la barra (|)" son texto, no separador.
_ANSWER_SEP = re.compile(r"\s+\|\s+")
_OPTION_SEP = re.compile(r"\s+/\s+")


def split_answers(text: str) -> List[str]:
    """"B | D" → ["B", "D"]; "|" → ["|"]; "| | &" → ["|", "&"]."""
    return [p.strip() for p in _ANSWER_SEP.split((text or "").strip()) if p.strip()]


def split_options(text: str) -> List[str]:
    """"a / b / c" → ["a", "b", "c"]; "km/h / m/s" → ["km/h", "m/s"]."""
    return [p.strip() for p in _OPTION_SEP.split((text or "").strip()) if p.strip()]


# ── Espacios de un Cloze: "[Letra: opción1 / opción2]" ──────────────────────
_CLOZE_SLOT_OPEN = re.compile(r"([A-Za-z]):\s*")


def find_cloze_brackets(text: str) -> List[Tuple[int, int, str, str]]:
    """
    Ubica cada espacio "[Letra: opción1 / opción2 / ...]" de un Cloze en
    `text`, para validator.py, xml_builder.py y el constructor visual del
    frontend (cloze.js, misma lógica en JS).

    Un "[" y "]" balanceados DENTRO de una opción (ej. una opción de código
    como "arr[0]") NO cierran el espacio a mitad de camino: antes se usaba
    una expresión regular que se detenía en el PRIMER "]" que encontrara,
    así que "[A: arr[0] / arr[1]]" se leía como el espacio "[A: arr[0]]"
    seguido de basura suelta "/ arr[1]]" — perdiendo la segunda opción y
    dejando el enunciado con un corchete de más (dev/eval_results/
    RESULTADOS.md, casos con código de programación).

    Devuelve una lista de (inicio, fin, letra, opciones_crudas) — "fin" es
    el índice justo después del "]" de cierre; "opciones_crudas" es el
    texto entre "Letra:" y ese "]", todavía sin partir por " / "
    (usar split_options para eso).
    """
    # Una sola pasada con una pila empareja cada "[" con su "]" (antes se
    # buscaba el cierre desde cada "[", y un texto con miles de "[A:" sin
    # cerrar tardaba minutos). Da lo mismo: "Letra:" no tiene corchetes.
    cierre_de = {}
    pila: List[int] = []
    for idx, ch in enumerate(text):
        if ch == "[":
            pila.append(idx)
        elif ch == "]" and pila:
            cierre_de[pila.pop()] = idx

    out: List[Tuple[int, int, str, str]] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "[":
            i += 1
            continue
        m = _CLOZE_SLOT_OPEN.match(text, i + 1)
        j = cierre_de.get(i)
        if not m or j is None:
            i += 1  # sin cierre — no es un espacio válido, sigue buscando
            continue
        out.append((i, j + 1, m.group(1), text[m.end():j]))
        i = j + 1
    return out
