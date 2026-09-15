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
