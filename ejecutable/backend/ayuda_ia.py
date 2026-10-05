"""
ayuda_ia.py — Botones de IA del editor, para UNA pregunta a la vez:

  «Escribir con IA»      la retroalimentación (opcional: la conversión solo
                         copia la que trae el documento, nunca la inventa).
  «Mejorar redacción»    ortografía, tildes, signos y claridad del
                         enunciado, sin cambiar su contenido. El código
                         comprueba que números, fórmulas y líneas de código
                         siguen iguales; si no, no se aplica.
  «Sugerir respuesta»    (2.0) cuando la clave falta, la IA PROPONE una
                         respuesta con su motivo. El código la valida contra
                         las opciones de la pregunta (una letra que no existe,
                         una pareja repetida o un hueco sin opción se descartan)
                         y el docente decide: nunca se aplica sola.

El docente la pide, la revisa y puede deshacerla. Llamadas pequeñas con
salida de texto plano: con JSON, la IA escribía «\\frac» sin escapar y
«\\f» se leía como un salto de página («rac{4}{4}»).
"""

import base64
import binascii
import difflib
import itertools
import re
import unicodedata
from collections import Counter
from typing import Any, Dict, List

from fastapi import HTTPException

import ia_reintentos
from ia_prompts import PROMPT_RETRO, PROMPT_REDACCION, PROMPT_SUGERIR  # noqa: F401 — los textos viven en ia_prompts.py
from ia_proveedor import ParteIA, SolicitudIA, parte_imagen_b64, parte_texto

MAX_CARACTERES = 600
_TIMEOUT = 60
# Tokens de salida: en los modelos que "piensan", los tokens de razonamiento
# cuentan dentro del tope de tokens de salida, y con un tope justo la respuesta salía
# cortada (o vacía). Holgura amplia: lo que se escribe de verdad es corto.
_TOKENS_RETRO = 4096
_TOKENS_REDACCION = 8192
_TOKENS_SUGERIR = 4096
_TIPOS = {"multichoice", "truefalse", "matching", "cloze", "essay", "shortanswer", "numerical"}
_MIME = {"image/png", "image/jpeg"}

_TIPO_ES = {
    "multichoice": "Opción múltiple", "truefalse": "Verdadero o falso",
    "matching": "Emparejamiento", "cloze": "Completar espacios",
    "essay": "Ensayo (respuesta abierta)", "shortanswer": "Respuesta corta",
    "numerical": "Respuesta numérica",
}


def _s(v: Any, limite: int = 4000) -> str:
    return str(v if v is not None else "").strip()[:limite]


def texto_pregunta(q: Dict[str, Any], respuesta: Any) -> str:
    """La pregunta en texto legible para la IA."""
    tipo = q.get("type")
    data = q.get("data") or {}
    r = respuesta.get("answer") if isinstance(respuesta, dict) else respuesta
    r = _s(r, 2000)
    lineas = [f"PREGUNTA ({_TIPO_ES.get(tipo, tipo)})"]

    if tipo == "cloze":
        lineas.append("Texto con espacios [letra: opciones]: " + _s(data.get("text")))
    else:
        lineas.append("Enunciado: " + _s(data.get("stem")))

    if tipo == "multichoice":
        opciones = data.get("options") or {}
        if isinstance(opciones, dict):
            for letra, texto in list(opciones.items())[:12]:
                lineas.append(f"  {_s(letra, 3)}) {_s(texto, 500)}")
    elif tipo == "matching":
        col_a = data.get("col_a") or {}
        col_b = data.get("col_b") or {}
        pares = (respuesta.get("pairs") if isinstance(respuesta, dict) else None) or {}
        if isinstance(col_a, dict) and isinstance(col_b, dict) and isinstance(pares, dict):
            lineas.append("Parejas correctas:")
            for k, izq in list(col_a.items())[:20]:
                der = col_b.get(str(pares.get(k, "")), "")
                lineas.append(f"  {_s(izq, 300)} → {_s(der, 300)}")
            r = ""

    if tipo == "essay":
        pass
    elif r and "SIN_RESPUESTA" not in r:
        lineas.append("Respuesta correcta: " + r)
    elif tipo != "matching":
        lineas.append("Respuesta correcta: (no indicada)")
    return "\n".join(lineas)


def _imagenes(q: Dict[str, Any]) -> List[ParteIA]:
    partes = []
    for im in ((q.get("data") or {}).get("images") or [])[:5]:
        if not isinstance(im, dict) or im.get("mime") not in _MIME:
            continue
        b64 = im.get("b64") or ""
        if not isinstance(b64, str) or len(b64) > 3_000_000:
            continue
        try:
            base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError):
            continue
        partes.append(parte_imagen_b64(im["mime"], b64))
    return partes


def _limpiar(texto: str) -> str:
    texto = texto.strip().strip('"“”').strip()
    texto = re.sub(r"^retroalimentaci[oó]n\s*:\s*", "", texto, flags=re.I)
    texto = re.sub(r"\*\*(.+?)\*\*", r"\1", texto)
    return texto.strip().strip('"“”').strip()[:MAX_CARACTERES]


def _comprobar_fin(resultado) -> None:
    """Una respuesta cortada (MAX_TOKENS) o interrumpida (SAFETY…) no se
    aplica: se vería como un texto completo y no lo es."""
    finish = str(getattr(resultado, "finish_reason", "") or "").upper()
    if finish in ("", "STOP"):
        return
    if finish == "MAX_TOKENS":
        detalle = "La IA no alcanzó a terminar de escribir. Inténtalo de nuevo."
    else:
        detalle = f"La IA interrumpió su respuesta (motivo: {finish}). Inténtalo de nuevo o escríbelo a mano."
    raise HTTPException(status_code=502, detail=detalle)


def _leer(resultado) -> str:
    _comprobar_fin(resultado)
    texto = _limpiar(resultado.text)
    if not texto:
        raise ValueError("retroalimentación vacía")
    return texto


def _llamar(prompt: str, texto: str, imagenes: List[ParteIA], leer, temperatura: float, max_tokens: int) -> str:
    solicitud = SolicitudIA(instruccion=prompt, partes=[parte_texto(texto)] + imagenes,
                            temperatura=temperatura, max_tokens=max_tokens)
    # Una sola pregunta: pocas esperas de cuota o saturación (el docente
    # está mirando el botón), en vez de los minutos de una conversión larga.
    return ia_reintentos.generar_con_reintentos(solicitud, len(texto), leer, _TIMEOUT,
                                                quota_waits=1, overload_waits=(4, 8), quota_max_seconds=20)


def _comprobar(q: Dict[str, Any]) -> None:
    if q.get("type") not in _TIPOS:
        raise HTTPException(status_code=422, detail="Tipo de pregunta desconocido.")
    data = q.get("data") or {}
    if not _s(data.get("stem") if q.get("type") != "cloze" else data.get("text")):
        raise HTTPException(status_code=422, detail="Escribe primero el enunciado de la pregunta.")


def generar(q: Dict[str, Any], respuesta: Any) -> str:
    """«Escribir con IA»: la retroalimentación de la pregunta."""
    _comprobar(q)
    return _llamar(PROMPT_RETRO, texto_pregunta(q, respuesta), _imagenes(q), _leer, 0.3, _TOKENS_RETRO)


# ── «Mejorar redacción» ─────────────────────────────────────────────────

MAX_ENUNCIADO = 6000


_FORMULA = re.compile(r"\\\(.*?\\\)", re.S)
_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")
_CODIGO = re.compile(r"[=(){}\[\];<>]|^\s{2,}\S|\b(?:print|def|return|if|else|for|while|import|class|console|int|float|var|let|const)\b")
# Operadores de código: "==" vs "=", "2**3" vs "2*3", "<" vs ">"… cambian el
# resultado del programa y son fáciles de colar en una corrección de
# redacción. Se comparan como conjunto EN TODO el enunciado (no solo en las
# líneas ya tratadas como "código"), porque un fragmento de código puede ir
# también en una sola línea ("¿Qué imprime print(2**3)?"), donde antes no
# se revisaba nada de esto.
_OPERADOR = re.compile(r"==|!=|<=|>=|\*\*|\+\+|--|[+\-*/%<>=]")
# Negaciones y palabras que invierten el sentido de la pregunta ("NO es" →
# "es", "excepto" → nada): un cambio aquí invierte lo que se pregunta.
_NEGACION = re.compile(r"\b(no|nunca|ningun[ao]?|excepto|salvo|incorrect[ao]|falso|false)\b", re.I)


def _lineas_codigo(texto: str) -> List[str]:
    return [ln for ln in texto.splitlines() if ln.strip() and _CODIGO.search(ln)]


def _conteo(rx: "re.Pattern", texto: str) -> "Counter":
    return Counter(m.lower() if isinstance(m, str) else m for m in rx.findall(texto))


# ── Comparación de sentido ──────────────────────────────────────────────
# Una redacción "mejorada" puede cambiar lo que se pregunta sin tocar números
# ni operadores: «incorrectas» → «correctas», «siempre» → «a veces», «mayor» →
# «menor», «sin» → «con», o un nombre propio por otro. Se comparan, palabra
# por palabra (sin tildes ni mayúsculas), las que cambian el sentido.

def _sin_tildes(p: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", p.lower()) if not unicodedata.combining(c))


_TOKEN = re.compile(r"[^\W_]+")

# (clave, regex sobre la palabra ya sin tildes). Palabras de la misma clave
# son intercambiables (plural, género); claves distintas NO lo son.
_SENTIDO = [(clave, re.compile(rx)) for clave, rx in [
    ("no", r"^(?:no|not)$"), ("nunca", r"^(?:nunca|jamas|never)$"),
    ("ningun", r"^(?:ningun\w*|none|nobody)$"), ("nada", r"^(?:nada|nadie|tampoco|nothing)$"),
    ("sin", r"^(?:sin|without)$"), ("con", r"^(?:con|with)$"),
    ("excepto", r"^(?:excepto|salvo|except|unless)$"),
    ("todo", r"^(?:tod[oa]s?|all|every|each)$"), ("algun", r"^(?:algun\w*|some)$"),
    ("siempre", r"^(?:siempre|always)$"), ("veces", r"^(?:veces|sometimes)$"),
    ("casi", r"^(?:casi|almost)$"), ("solo", r"^(?:solo|solos|solamente|unicamente|unic[oa]s?|only)$"),
    ("cada", r"^cada$"), ("vari", r"^(?:vari[oa]s|several)$"), ("ambos", r"^(?:ambos|ambas|both)$"),
    ("mayoria", r"^(?:mayoria|majority)$"), ("minoria", r"^minoria$"), ("mitad", r"^(?:mitad|half)$"),
    ("mucho", r"^(?:much[oa]s?|many|much)$"), ("poco", r"^(?:poc[oa]s?|few|little)$"),
    ("cualquier", r"^(?:cualquier\w*|any)$"),
    ("mas", r"^(?:mas|more)$"), ("menos", r"^(?:menos|less|fewer)$"),
    ("mayor", r"^(?:mayor(?:es)?|greater|larger|bigger|higher)$"),
    ("menor", r"^(?:menor(?:es)?|smaller|lower)$"),
    ("maximo", r"^(?:maxim[oa]s?|maximum|largest|highest)$"),
    ("minimo", r"^(?:minim[oa]s?|minimum|smallest|lowest)$"),
    ("mejor", r"^(?:mejor(?:es)?|best|better)$"), ("peor", r"^(?:peor(?:es)?|worst|worse)$"),
    ("superior", r"^superior(?:es)?$"), ("inferior", r"^inferior(?:es)?$"),
    ("primero", r"^(?:primer[oa]?s?|first)$"), ("ultimo", r"^(?:ultim[oa]s?|last)$"),
    ("antes", r"^(?:antes|before)$"), ("despues", r"^(?:despues|after)$"),
    ("durante", r"^(?:durante|during)$"),
    ("igual", r"^(?:igual(?:es)?|same|equal)$"),
    ("distinto", r"^(?:distint[oa]s?|diferent(?:e|es)|different)$"),
    ("correcto", r"^(?:correct[oa]s?|correct)$"), ("incorrecto", r"^(?:incorrect[oa]s?|incorrect|wrong)$"),
    ("verdadero", r"^(?:verdader[oa]s?|true)$"), ("falso", r"^(?:fals[oa]s?|false)$"),
    ("cierto", r"^ciert[oa]s?$"),
    ("valido", r"^valid[oa]s?$"), ("invalido", r"^invalid[oa]s?$"),
    ("posible", r"^posibles?$"), ("imposible", r"^imposibles?$"),
    ("necesario", r"^necesari[oa]s?$"), ("innecesario", r"^innecesari[oa]s?$"),
    ("puede", r"^(?:puede\w*|pueden|podria\w*|can|may|could)$"), ("debe", r"^(?:debe\w*|deben|must|should)$"),
    ("aumenta", r"^(?:aument\w+|increas\w*|incrementa\w*)$"), ("disminuye", r"^(?:disminu\w+|reduc\w+|decreas\w*)$"),
    ("suma", r"^(?:suma\w*|sum|add)$"), ("resta", r"^(?:resta\w*|subtract\w*)$"),
    ("multiplica", r"^(?:multiplic\w+|multiply)$"), ("divide", r"^(?:divid\w+|division|divide)$"),
]]

# Palabras funcionales o típicas del inicio de un enunciado: escritas con
# mayúscula al comienzo de la oración no son nombres propios.
_FUNCION = frozenset(_sin_tildes(w) for w in """
el la los las un una unos unas lo al del de en con sin por para que cual cuales cuando como donde quien quienes cuanto
cuantos cuanta cuantas qué cuál cuáles cuándo cómo dónde quién cuánto según segun si no ni y o u e pero sino aunque
porque pues entre sobre bajo hasta desde hacia ante tras durante mediante este esta estos estas ese esa esos esas aquel
aquella su sus mi mis tu tus nuestro nuestra es son fue fueron era eran será serán ser esta están estar hay había
seleccione indique identifique marque señale escriba complete relacione elija escoja determine explique describa defina
mencione enumere cite calcule resuelva analice compare argumente justifique responda lea observe considere suponga dado
dada dados dadas todo toda todos todas algún alguno alguna algunos algunas ningún ninguno ninguna cada varios varias
uno dos tres cuatro cinco seis siete ocho nueve diez primero segundo tercero pregunta opción opciones enunciado
the a an of in on to is are which what who how when where why select choose identify state explain describe define
""".split())

_MAYUSCULA = re.compile(r"[A-ZÁÉÍÓÚÑÜ][\wáéíóúñüÁÉÍÓÚÑÜ]*")
_INICIO_ORACION = ".?!¿¡:;\n\"“«"


def _palabras(texto: str) -> List[str]:
    return [_sin_tildes(m.group()) for m in _TOKEN.finditer(texto)]


def _claves_sentido(texto: str) -> "Counter":
    """Cuántas veces aparece cada palabra que cambia el sentido, con un
    ejemplo de cómo estaba escrita (para el mensaje)."""
    cuenta: Counter = Counter()
    for m in _TOKEN.finditer(texto):
        p = _sin_tildes(m.group())
        for clave, rx in _SENTIDO:
            if rx.match(p):
                cuenta[(clave, m.group())] += 1
                break
    return cuenta


def _por_clave(cuenta: "Counter") -> "tuple[Counter, dict]":
    total: Counter = Counter()
    ejemplo: dict = {}
    for (clave, palabra), n in cuenta.items():
        total[clave] += n
        ejemplo.setdefault(clave, palabra)
    return total, ejemplo


def _nombres_propios(texto: str) -> Dict[str, str]:
    """Palabras que parecen nombres propios o siglas: con mayúscula inicial
    (salvo la primera palabra de una oración, si es una palabra funcional) o
    en mayúsculas. {forma_normalizada: como_se_escribió}."""
    out: Dict[str, str] = {}
    for m in _MAYUSCULA.finditer(texto):
        palabra = m.group()
        norm = _sin_tildes(palabra)
        previo = texto[:m.start()].rstrip(" \t")
        inicio = (not previo) or previo[-1] in _INICIO_ORACION
        siglas = len(palabra) >= 2 and palabra.isupper()
        if siglas or not (inicio and norm in _FUNCION):
            out.setdefault(norm, palabra)
    return out


def _se_parece(norm: str, otros) -> bool:
    """¿`norm` está entre `otros`, o solo difiere por una errata (Celcius →
    Celsius)? Un nombre distinto (Einstein → Newton) no se le parece."""
    if norm in otros:
        return True
    return any(abs(len(o) - len(norm)) <= 1 and difflib.SequenceMatcher(None, norm, o).ratio() >= 0.85
               for o in otros)


def _raices_contenido(texto: str) -> set:
    return {p[:5] for p in _palabras(texto) if len(p) >= 5 and p not in _FUNCION and not p.isdigit()}


def cambios_indebidos(original: str, nuevo: str) -> List[str]:
    """Qué cambió la IA que no debía cambiar (vacío = se puede aplicar)."""
    motivos = []
    sin_formulas = lambda t: _FORMULA.sub(" ", t)
    if sorted(_FORMULA.findall(original)) != sorted(_FORMULA.findall(nuevo)):
        motivos.append("fórmulas")
    if sorted(_NUMERO.findall(sin_formulas(original))) != sorted(_NUMERO.findall(sin_formulas(nuevo))):
        motivos.append("números")
    if _conteo(_OPERADOR, original) != _conteo(_OPERADOR, nuevo):
        motivos.append("operadores")
    if _conteo(_NEGACION, original) != _conteo(_NEGACION, nuevo):
        motivos.append("negaciones")
    # Palabras que cambian el sentido (negaciones, cuantificadores,
    # comparativos, «sin»/«con», antónimos): deben quedar EXACTAMENTE igual
    # en cantidad — o cambia lo que se pregunta.
    sin_o, sin_n = sin_formulas(original), sin_formulas(nuevo)
    tot_o, ej_o = _por_clave(_claves_sentido(sin_o))
    tot_n, ej_n = _por_clave(_claves_sentido(sin_n))
    difieren = [c for c in set(tot_o) | set(tot_n) if tot_o[c] != tot_n[c]]
    if difieren:
        quitadas_p = [ej_o[c] for c in sorted(difieren) if tot_o[c] > tot_n[c]]
        puestas_p = [ej_n[c] for c in sorted(difieren) if tot_n[c] > tot_o[c]]
        pares = [f"«{a}» → «{b}»" for a, b in itertools.zip_longest(quitadas_p, puestas_p, fillvalue="(nada)")]
        motivos.append("palabras que cambian el sentido (" + ", ".join(pares[:3]) + ")")
    # Nombres propios y siglas: cada uno del original debe seguir (con tildes o
    # mayúsculas corregidas, o a lo sumo una errata), y no debe aparecer
    # ninguno nuevo.
    prop_o, prop_n = _nombres_propios(sin_o), _nombres_propios(sin_n)
    todas_o, todas_n = set(_palabras(sin_o)), set(_palabras(sin_n))
    perdidos = [w for k, w in prop_o.items() if not _se_parece(k, todas_n)]
    nuevos = [w for k, w in prop_n.items() if not _se_parece(k, todas_o)]
    if perdidos or nuevos:
        motivos.append("nombres propios (" + ", ".join(f"«{w}»" for w in (perdidos + nuevos)[:3]) + ")")
    # Contenido: no se pueden borrar ni inventar demasiadas ideas (palabras de
    # contenido, comparadas por su raíz).
    raices_o, raices_n = _raices_contenido(sin_o), _raices_contenido(sin_n)
    quitadas, agregadas = raices_o - raices_n, raices_n - raices_o
    if len(quitadas) > max(1, 0.35 * len(raices_o)) or len(agregadas) > max(1, 0.35 * len(raices_n)):
        motivos.append("demasiadas palabras del contenido")
    # Código en sus propias líneas (enunciado de varias líneas): cada una
    # debe seguir idéntica, SANGRÍA incluida (en Python cambia el
    # significado del programa). En una sola línea ("¿Qué imprime
    # print(2)?") el texto alrededor sí se puede corregir; ahí ya cuidan
    # números, fórmulas y operadores.
    if "\n" in original.strip():
        lineas_nuevas = {ln.rstrip() for ln in nuevo.splitlines()}
        if any(ln.rstrip() not in lineas_nuevas for ln in _lineas_codigo(original)):
            motivos.append("código")
    # Un enunciado muy corto puede crecer más (agregar «¿Cuál es…?»); uno
    # normal, no debe perder ni ganar mucho.
    largo = len(nuevo) / max(1, len(original))
    minimo, maximo = (0.5, 1.8) if len(original.strip()) < 30 else (0.7, 1.4)
    if not (minimo <= largo <= maximo):
        motivos.append("longitud")
    return motivos


def _leer_enunciado(resultado) -> str:
    _comprobar_fin(resultado)
    texto = (resultado.text or "").strip()
    texto = re.sub(r"^(?:enunciado|pregunta)\s*:\s*", "", texto, flags=re.I)
    if len(texto) >= 2 and texto[0] in "\"“«" and texto[-1] in "\"”»":
        texto = texto[1:-1].strip()
    texto = re.sub(r"^```\w*\n|\n```$", "", texto)
    if not texto:
        raise ValueError("enunciado vacío")
    return texto


def mejorar_enunciado(q: Dict[str, Any]) -> Dict[str, Any]:
    """«Mejorar redacción»: {"enunciado": texto, "cambio": bool}."""
    _comprobar(q)
    if q.get("type") == "cloze":
        raise HTTPException(status_code=422, detail="Las preguntas de completar se editan en su propio constructor.")
    data = q.get("data") or {}
    original = str(data.get("stem") or "")
    if len(original) > MAX_ENUNCIADO:
        raise HTTPException(status_code=422, detail="El enunciado es demasiado largo para mejorarlo de una vez.")
    contexto = ""
    opciones = data.get("options")
    if isinstance(opciones, dict) and opciones:
        contexto = "\n\nOPCIONES (solo contexto, no las devuelvas):\n" + "\n".join(
            f"{_s(k, 3)}) {_s(v, 300)}" for k, v in list(opciones.items())[:12])
    nuevo = _llamar(PROMPT_REDACCION, "ENUNCIADO:\n" + original + contexto, [], _leer_enunciado, 0.2, _TOKENS_REDACCION)
    motivos = cambios_indebidos(original, nuevo)
    if motivos:
        raise HTTPException(status_code=422, detail=(
            "La IA cambió " + ", ".join(motivos) + " del enunciado, así que no se aplicó. "
            "Puedes intentarlo otra vez o corregirlo a mano."))
    return {"enunciado": nuevo, "cambio": nuevo.strip() != original.strip()}


# ── «Sugerir respuesta» (IA asistida, 2.0) ───────────────────────────────

_RESPUESTA = re.compile(r"^\s*RESPUESTA\s*:\s*(.*?)\s*$", re.I | re.M)
_MOTIVO = re.compile(r"^\s*MOTIVO\s*:\s*(.*?)\s*$", re.I | re.M)
_NUMERO_SOLO = re.compile(r"^[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?$")
_VERDADERO = {"verdadero", "cierto", "true", "v", "si", "sí"}
_FALSO = {"falso", "false", "f", "no"}
MAX_MOTIVO = 240


def _huecos_de(q: Dict[str, Any], respuesta: Any):
    """Los huecos de «Completar» con sus opciones como lista (la estructura de
    la clave manda sobre partir el texto: una opción puede llevar « / »)."""
    from modelo import Clave, huecos_de_cloze
    clave = Clave.desde_dict(respuesta) if isinstance(respuesta, dict) else Clave()
    return huecos_de_cloze(str((q.get("data") or {}).get("text") or ""), "", clave.huecos)


def _texto_sugerir(q: Dict[str, Any], respuesta: Any) -> str:
    """La pregunta para la IA SIN la respuesta que haya ahora (podría estar mal o vacía)."""
    tipo = q.get("type")
    data = q.get("data") or {}
    lineas = [f"PREGUNTA ({_TIPO_ES.get(tipo, tipo)})"]
    if tipo == "cloze":
        lineas.append("Texto con espacios [A], [B]…: " + re.sub(r"\[([A-Za-z]):[^\]]*\]", r"[\1]", _s(data.get("text"))))
        for h in _huecos_de(q, respuesta)[:20]:
            lineas.append(f"Hueco {h.letra.upper()}:")
            lineas += [f"  {i}) {_s(o, 300)}" for i, o in enumerate(h.opciones[:12], start=1)]
        return "\n".join(lineas)
    lineas.append("Enunciado: " + _s(data.get("stem")))
    if tipo == "multichoice":
        opciones = data.get("options") or {}
        if isinstance(opciones, dict):
            lineas += [f"  {_s(l, 3)}) {_s(t, 500)}" for l, t in list(opciones.items())[:12]]
    elif tipo == "matching":
        col_a, col_b = data.get("col_a") or {}, data.get("col_b") or {}
        if isinstance(col_a, dict) and isinstance(col_b, dict):
            lineas.append("Columna A:")
            lineas += [f"  {_s(k, 4)}. {_s(v, 300)}" for k, v in list(col_a.items())[:20]]
            lineas.append("Columna B:")
            lineas += [f"  {_s(k, 4)}. {_s(v, 300)}" for k, v in list(col_b.items())[:20]]
    return "\n".join(lineas)


def _motivo(texto: str) -> str:
    m = _MOTIVO.search(texto)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:MAX_MOTIVO] if m else ""


def interpretar_sugerencia(texto: str, q: Dict[str, Any], respuesta: Any = None) -> Dict[str, Any]:
    """Texto de la IA → {"tipo", "sugerencia", "motivo"}, validado contra la pregunta.

    «NO_SE» es una respuesta legítima (HTTP 422 con el motivo). Todo lo demás que no
    encaje con las opciones de la pregunta es un ValueError: se reintenta como una
    respuesta mal formada y, si persiste, el docente ve un error, nunca una respuesta
    inventada por el código."""
    tipo = q.get("type")
    data = q.get("data") or {}
    m = _RESPUESTA.search(texto)
    if not m or not m.group(1).strip():
        raise ValueError("sin línea RESPUESTA")
    bruto = m.group(1).strip().strip("`\"“”«»").strip()
    motivo = _motivo(texto)
    if re.fullmatch(r"NO[_ ]?SE|NO SÉ", bruto, re.I):
        raise HTTPException(status_code=422, detail=(
            "La IA no pudo decidir la respuesta con seguridad" + (f": {motivo}" if motivo else ".") + " Márcala tú."))

    if tipo == "multichoice":
        opciones = data.get("options") or {}
        validas = {str(k).upper(): k for k in opciones} if isinstance(opciones, dict) else {}
        letras = []
        for tok in re.findall(r"[A-Za-z]+", bruto):
            if tok.upper() in validas and validas[tok.upper()] not in letras:
                letras.append(validas[tok.upper()])
            elif tok.lower() not in ("y", "e", "o", "la", "las", "opcion", "opción", "opciones", "respuesta"):
                raise ValueError(f"letra fuera de las opciones: {tok}")
        if not letras:
            raise ValueError("ninguna letra válida")
        return {"tipo": tipo, "sugerencia": {"letras": letras}, "motivo": motivo}

    if tipo == "truefalse":
        v = bruto.strip(" .").lower()
        if v in _VERDADERO:
            return {"tipo": tipo, "sugerencia": {"respuesta": "Verdadero"}, "motivo": motivo}
        if v in _FALSO:
            return {"tipo": tipo, "sugerencia": {"respuesta": "Falso"}, "motivo": motivo}
        raise ValueError("ni verdadero ni falso")

    if tipo == "numerical":
        n = bruto.replace(" ", "")
        if not _NUMERO_SOLO.match(n):
            raise ValueError("no es un número")
        return {"tipo": tipo, "sugerencia": {"respuesta": n.replace(",", ".")}, "motivo": motivo}

    if tipo == "shortanswer":
        texto_resp = re.sub(r"\s+", " ", bruto).strip()
        if not texto_resp or len(texto_resp) > 200:
            raise ValueError("respuesta corta vacía o demasiado larga")
        return {"tipo": tipo, "sugerencia": {"respuesta": texto_resp}, "motivo": motivo}

    if tipo == "matching":
        col_a, col_b = data.get("col_a") or {}, data.get("col_b") or {}
        izq = {str(k): k for k in col_a} if isinstance(col_a, dict) else {}
        der = {str(k).lower(): str(k).lower() for k in col_b} if isinstance(col_b, dict) else {}
        pares: Dict[str, str] = {}
        for n, letra in re.findall(r"(\d+)\s*[-=:→>]+\s*([A-Za-z])\b", bruto):
            if n not in izq or letra.lower() not in der or n in pares or letra.lower() in pares.values():
                raise ValueError("pareja inválida o repetida")
            pares[n] = letra.lower()
        if not izq or set(pares) != set(izq):
            raise ValueError("faltan parejas")
        return {"tipo": tipo, "sugerencia": {"pares": {k: pares[k] for k in sorted(pares, key=int)}}, "motivo": motivo}

    if tipo == "cloze":
        huecos = {h.letra.upper(): h for h in _huecos_de(q, respuesta)}
        elegidos: Dict[str, int] = {}
        for letra, pos in re.findall(r"([A-Za-z])\s*[=:]\s*(\d+)", bruto):
            h = huecos.get(letra.upper())
            if h is None or letra.upper() in elegidos or not 1 <= int(pos) <= len(h.opciones):
                raise ValueError("hueco u opción inválidos")
            elegidos[letra.upper()] = int(pos) - 1
        if not huecos or set(elegidos) != set(huecos):
            raise ValueError("faltan huecos")
        return {"tipo": tipo, "sugerencia": {"huecos": elegidos}, "motivo": motivo}

    raise HTTPException(status_code=422, detail="Este tipo de pregunta no tiene una respuesta que sugerir.")


def sugerir_respuesta(q: Dict[str, Any], respuesta: Any = None) -> Dict[str, Any]:
    """«Sugerir respuesta»: la IA propone la respuesta de una pregunta SIN clave."""
    _comprobar(q)
    if q.get("type") == "essay":
        raise HTTPException(status_code=422, detail="Un ensayo se califica a mano: no tiene respuesta correcta que sugerir.")

    def leer(resultado):
        _comprobar_fin(resultado)
        return interpretar_sugerencia(resultado.text or "", q, respuesta)

    return _llamar(PROMPT_SUGERIR, _texto_sugerir(q, respuesta), _imagenes(q), leer, 0.0, _TOKENS_SUGERIR)
