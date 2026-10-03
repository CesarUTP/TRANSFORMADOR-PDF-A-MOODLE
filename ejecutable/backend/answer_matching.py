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
import unicodedata
from typing import Dict, List, Optional, Sequence, Tuple

_PREFIX_FALLBACK_MIN_LEN = 20  # evita falsos positivos con fragmentos cortos/genéricos
_SUBSTRING_FALLBACK_MIN_LEN = 4  # ver is_substring_match


def is_substring_match(target: str, option: str) -> bool:
    """
    Salvavidas de "una cadena contiene a la otra" (paráfrasis, mayúsculas o
    palabras de más: la clave dice "Madrid" y la opción "Madrid, España").
    Solo se acepta si la más CORTA de las dos ya tiene sentido por sí sola
    (≥ _SUBSTRING_FALLBACK_MIN_LEN caracteres); si no, cualquier número o
    palabra corta calza como subcadena de casi cualquier opción y marca la
    incorrecta — visto en la práctica: opciones {"12", "2 unidades", "3"}
    con la respuesta "2" marcaba "12" como correcta ("2" está en "12").
    La igualdad exacta no pasa por aquí (no tiene este mínimo).
    """
    if min(len(target), len(option)) < _SUBSTRING_FALLBACK_MIN_LEN:
        return False
    return target in option or option in target


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


# ── Resolución de «¿cuál opción es la respuesta correcta?» ───────────────────
# UNA sola función que usan validator.py (¿se puede resolver?) y
# xml_builder.py (¿cuál marcar?). Antes cada uno tenía su propia lógica: el
# validador aceptaba cualquier coincidencia difusa y el constructor exigía
# coincidencia única y, si no la hallaba, marcaba la «A» (o la primera opción
# de un hueco Cloze) en silencio: una respuesta inventada. Ahora, si no se
# puede decidir sin adivinar, devuelve None y quien llama lo trata como error.

class RespuestaNoResuelta(ValueError):
    """La respuesta de la clave no identifica UNA opción. Nunca se adivina."""


def plegar(texto: str) -> str:
    """Forma comparable: sin tildes, sin mayúsculas, espacios colapsados."""
    d = unicodedata.normalize("NFKD", str(texto or ""))
    d = "".join(c for c in d if not unicodedata.combining(c))
    return " ".join(d.casefold().split())


_LETRA_CON_SIGNO = re.compile(r"^\(?([A-Za-z])[.):]?\)?$")


def resolver_opcion(
    respuesta: str,
    opciones: Dict[str, str],
    permitir_letra: bool = True,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Decide cuál de `opciones` ({clave: texto}) es la que nombra `respuesta`.

    Devuelve (clave, None) si hay UNA opción clara, o (None, motivo) con
    motivo "ninguna" (no coincide con nada) o "ambigua" (varias por igual).
    Orden de prioridad (la primera etapa que decide, gana):
      1. texto completo igual (sin importar mayúsculas ni espacios de los
         bordes): con {A: Python, B: Java, C: JavaScript, D: C}, «C» es la
         opción cuyo TEXTO es «C» (D), no la letra C;
      2. la letra de la opción («b», «B», «B)», «(b)») — solo si
         `permitir_letra` (los huecos de Completar no tienen letras);
      3. texto igual sin tildes/mayúsculas/espacios repetidos (único);
      4. una contiene a la otra (is_substring_match, con su mínimo) (único);
      5. respuesta cortada a mitad de palabra (is_truncated_answer_match) (único).
    Una etapa con 2+ coincidencias no decide: pasa a la siguiente y, si
    ninguna decide, el resultado es "ambigua".
    """
    obj = str(respuesta or "").strip()
    if not obj or not opciones:
        return None, "ninguna"
    low = obj.lower()
    textos = {k: str(v).strip().lower() for k, v in opciones.items()}

    for k, t in textos.items():
        if low == t:
            return k, None

    if permitir_letra:
        for k in opciones:
            if low == str(k).lower():
                return k, None
        m = _LETRA_CON_SIGNO.match(obj)
        if m:
            for k in opciones:
                if m.group(1).lower() == str(k).lower():
                    return k, None

    hubo_varias = False
    plegado = plegar(obj)
    plegados = {k: plegar(v) for k, v in opciones.items()}
    etapas = (
        lambda k: bool(plegado) and plegado == plegados[k],
        lambda k: is_substring_match(plegado, plegados[k]),
        lambda k: is_truncated_answer_match(low, textos[k]),
    )
    for cumple in etapas:
        halladas = [k for k in opciones if cumple(k)]
        if len(halladas) == 1:
            return halladas[0], None
        if len(halladas) > 1:
            hubo_varias = True
    return None, ("ambigua" if hubo_varias else "ninguna")


def resolver_hueco_cloze(respuesta: str, opciones: Sequence[str]) -> Tuple[Optional[int], Optional[str]]:
    """Igual que resolver_opcion para las opciones de un hueco Cloze; devuelve
    el ÍNDICE de la opción. Sin letras: aquí «B» solo cuenta si es el texto."""
    clave, motivo = resolver_opcion(respuesta, {str(i): o for i, o in enumerate(opciones)}, permitir_letra=False)
    return (int(clave) if clave is not None else None), motivo


# ── Respuestas por ÍNDICE (la fuente de verdad cuando existen) ────────────────
# Las respuestas correctas viajan como TEXTO con separadores (« | » entre
# respuestas, « / » entre opciones de un hueco), y una opción cuyo propio texto
# contiene « | » o « / » ("x | y", "10 / 2") se partía mal. Por eso, junto al
# texto, viajan los ÍNDICES (base 0) de las opciones correctas: con ellos no
# hay nada que partir. Se usan solo si son válidos y COINCIDEN con el texto de
# la clave (si alguien editó el texto sin tocar los índices, manda el texto, que
# es lo de siempre); si faltan (historiales viejos, claves del documento en
# texto) se analiza el texto como antes.

def indices_utilizables(indices: object, n: int) -> Optional[List[int]]:
    """Los índices sin repetir y en su orden, o None si no sirven: no es una
    lista, está vacía, o algún valor no es un entero dentro de 0..n-1."""
    if not isinstance(indices, (list, tuple)) or not indices:
        return None
    out: List[int] = []
    for i in indices:
        if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < n:
            return None
        if i not in out:
            out.append(i)
    return out


def _colapsar(texto: str) -> str:
    return " ".join(str(texto or "").split())


def indices_coinciden_con_texto(textos: Sequence[str], respuesta: str) -> bool:
    """¿Las opciones señaladas por los índices, unidas con « | », son lo que dice
    el texto de la clave (sin importar espacios repetidos)?"""
    return _colapsar(" | ".join(textos)) == _colapsar(respuesta)


def resolver_correctas_multichoice(
    opciones: Dict[str, str], respuesta: str, indices: object = None,
) -> Tuple[List[str], List[Tuple[str, str]]]:
    """(letras correctas sin repetir, fallos) de una pregunta de opción múltiple.
    `indices` son posiciones (base 0) en las letras ORDENADAS de `opciones`.
    Con índices utilizables y que coinciden con `respuesta`, se usan tal cual;
    si no, se parte `respuesta` por « | » y cada parte pasa por resolver_opcion."""
    letras_ordenadas = sorted(opciones)
    usables = indices_utilizables(indices, len(letras_ordenadas))
    if usables is not None and indices_coinciden_con_texto(
            [opciones[letras_ordenadas[i]] for i in usables], respuesta):
        return [letras_ordenadas[i] for i in usables], []
    letras: List[str] = []
    fallos: List[Tuple[str, str]] = []
    for objetivo in split_answers(respuesta):
        letra, motivo = resolver_opcion(objetivo, opciones)
        if letra is None:
            fallos.append((objetivo, motivo or "ninguna"))
        elif letra not in letras:
            letras.append(letra)
    return letras, fallos


def resolver_correctas_cloze(
    opciones: Sequence[str], respuestas: Sequence[str], indices: object = None,
) -> Tuple[List[int], List[Tuple[str, str]]]:
    """(índices de las opciones correctas de un hueco sin repetir, fallos). Con
    `indices` utilizables se devuelven tal cual; si no, cada respuesta de la
    clave pasa por resolver_hueco_cloze."""
    usables = indices_utilizables(indices, len(opciones))
    if usables is not None:
        return usables, []
    out: List[int] = []
    fallos: List[Tuple[str, str]] = []
    for resp in respuestas:
        resp = resp.strip()
        if not resp:
            continue
        idx, motivo = resolver_hueco_cloze(resp, opciones)
        if idx is None:
            fallos.append((resp, motivo or "ninguna"))
        elif idx not in out:
            out.append(idx)
    return out, fallos


def clave_de_huecos(respuesta_clave: str, n_huecos: int, letra_unica: str = "") -> Dict[str, List[str]]:
    """
    {"A": ["resp", ...], ...} a partir de la clave de un Cloze
    («A. respuesta; B. resp1 | resp2»). Compartida por validator.py y
    xml_builder.py. Formato legado: sin ningún «Letra. respuesta» y con un
    único hueco, toda la clave es la respuesta de ese hueco (`letra_unica`).
    """
    por_hueco: Dict[str, List[str]] = {}
    for m in re.finditer(r"([A-Za-z])[\.:]\s*([^;\n]+)", respuesta_clave or ""):
        partes = split_answers(m.group(2))
        if partes:
            por_hueco[m.group(1).upper()] = partes
    if not por_hueco and n_huecos == 1 and (respuesta_clave or "").strip():
        por_hueco[letra_unica.upper()] = [respuesta_clave.strip()]
    return por_hueco


# Verdadero/Falso: lo que acepta el validador es lo que entiende el constructor
# (antes el validador rechazaba «V» que el constructor sí aceptaba). Se consulta
# con la respuesta ya sin espacios de los bordes y en minúscula.
TRUEFALSE_ALIAS = {"verdadero": True, "true": True, "v": True, "falso": False, "false": False, "f": False}


def clave_de_columna(columna: Dict[str, str], letra: str) -> Optional[str]:
    """La clave real de `columna` para la letra de la clave de respuestas, sin
    distinguir mayúsculas («B» de la clave y «b» de la columna, o al revés);
    None si no existe. Compartida por validator.py y xml_builder.py: antes el
    validador comparaba la letra tal cual y el constructor la pasaba a
    minúscula, así que con la Columna B rotulada «A/B» el examen validaba y el
    XML salía con parejas equivocadas."""
    l = str(letra or "").strip()
    if l in columna:
        return l
    for k in columna:
        if str(k).lower() == l.lower():
            return k
    return None


# Número aceptado en una pregunta numérica: signo opcional, dígitos ASCII, punto
# o coma decimal, exponente opcional. float() de Python daba por buenos «nan»,
# «inf», «1_000» y dígitos de otros alfabetos (٣), que Moodle no reconoce como
# número. Los separadores de miles («1,000») nunca se admitieron.
_NUMERO = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def normalizar_numero(texto: str) -> Optional[str]:
    """«3,5» → «3.5» (la coma decimal es común al copiar un documento en
    español, pero Moodle solo entiende el punto); None si no es un número."""
    t = str(texto or "").strip().replace(",", ".")
    return t if _NUMERO.fullmatch(t) else None
