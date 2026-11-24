"""
test_xml_validador.py — Versión 1.8: resolución de la respuesta correcta
(validador y constructor deciden con la MISMA función y nunca inventan),
texto de Completar con saltos de línea y sangría, números estrictos,
matching con letras en mayúscula, Verdadero/Falso con alias, categoría
saneada y aviso de puntos en Completar.

    backend/venv/bin/python dev/test_xml_validador.py

No llama a Gemini ni toca el historial, la clave o la base de datos (no
importa main).
"""

import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from lxml import etree  # noqa: E402

from answer_matching import (  # noqa: E402
    RespuestaNoResuelta, clave_de_columna, normalizar_numero, resolver_hueco_cloze, resolver_opcion,
)
from validator import partition_questions, validate_questions  # noqa: E402
from xml_builder import build_xml, compute_grades, convert_cloze_to_moodle, sanear_categoria  # noqa: E402

logging.disable(logging.CRITICAL)

fallas = 0


def ok(cond, msg):
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


def q(num, tipo, data):
    return {"num": num, "type": tipo, "data": data}


def errores(preguntas, clave):
    return validate_questions(preguntas, clave).errors


def lanza(preguntas, clave, **kw):
    try:
        build_xml(preguntas, clave, **kw)
    except RespuestaNoResuelta:
        return True
    return False


def correctas_mc(xml):
    """Textos de las opciones con fracción > 0 de la primera multichoice."""
    raiz = etree.fromstring(xml.encode("utf-8"))
    return [a.findtext("text") for a in raiz.iter("answer") if float(a.get("fraction")) > 0]


def mc(respuesta, opciones):
    return [q(1, "multichoice", {"stem": "Enunciado", "options": opciones})], {1: {"type": "multichoice", "answer": respuesta}}


# ── 1. Multichoice: nunca se inventa la respuesta ─────────────────────────
print("Multichoice: la clave debe identificar UNA opción")
OPC = {"A": "Java", "B": "Python 2 basico", "C": "Python 3 basico"}
qs, ak = mc("Python", OPC)
e = errores(qs, ak)
ok(any("ambigua" in x for x in e), "«Python» con «Python 2»/«Python 3»: el validador lo reporta como ambigua")
ok(lanza(qs, ak), "el constructor no marca «Java» (la A) en su lugar: lanza RespuestaNoResuelta")
qs, ak = mc("Rust", OPC)
ok(any("no coincide con ninguna de las opciones disponibles" in x for x in errores(qs, ak)), "una respuesta que no está: error claro")
ok(lanza(qs, ak), "y el constructor tampoco elige la A")
_, omitidas = partition_questions(qs, ak)
ok(len(omitidas) == 1 and omitidas[0].get("recoverable_data"), "en el flujo tolerante queda omitida y rescatable en el editor")
qs, ak = mc("Python", OPC)
_, omitidas = partition_questions(qs, ak)
ok(len(omitidas) == 1 and omitidas[0].get("recoverable_data"), "la ambigua también es rescatable (solo falla la respuesta)")

casos_ok = [
    ("B", "Python 2 basico", "letra mayúscula"),
    ("b", "Python 2 basico", "letra minúscula"),
    ("(c)", "Python 3 basico", "letra entre paréntesis"),
    ("B)", "Python 2 basico", "letra con paréntesis"),
    ("Java", "Java", "texto exacto"),
    ("  PYTHON 3 BASICO ", "Python 3 basico", "mayúsculas y espacios"),
    ("python 3 básico", "Python 3 basico", "tilde de más en la clave"),
    ("Python   3  basico", "Python 3 basico", "espacios repetidos"),
]
for resp, esperada, etiqueta in casos_ok:
    qs, ak = mc(resp, OPC)
    xml, _ = build_xml(qs, ak)
    ok(not errores(qs, ak) and correctas_mc(xml) == [esperada], f"legítimo ({etiqueta}): «{resp}» → {esperada}")
qs, ak = mc("Madrid", {"A": "Lisboa", "B": "Madrid, España", "C": "Roma"})
xml, _ = build_xml(qs, ak)
ok(not errores(qs, ak) and correctas_mc(xml) == ["Madrid, España"], "coincidencia difusa ÚNICA sigue valiendo")
qs, ak = mc("C", {"A": "Python", "B": "Java", "C": "JavaScript", "D": "C"})
xml, _ = build_xml(qs, ak)
ok(correctas_mc(xml) == ["C"], "«C» es el TEXTO de la opción D antes que la letra C")
qs, ak = mc("A | C", {"A": "Uno", "B": "Dos", "C": "Tres"})
xml, _ = build_xml(qs, ak)
ok(not errores(qs, ak) and correctas_mc(xml) == ["Uno", "Tres"] and "<single>false</single>" in xml, "varias respuestas con « | »")
qs, ak = mc("A | Zzz", {"A": "Uno", "B": "Dos", "C": "Tres"})
ok(bool(errores(qs, ak)) and lanza(qs, ak), "varias respuestas: si UNA no resuelve, error (no se marca solo la otra)")
ok(resolver_opcion("2", {"A": "12", "B": "2 unidades", "C": "3"}) == (None, "ninguna"), "«2» no se adivina entre «12» y «2 unidades» (mínimo de longitud)")
ok(resolver_opcion("", {"A": "x"})[0] is None, "respuesta vacía no resuelve")

# ── 2. Cloze: resolución y texto HTML ─────────────────────────────────────
print("Cloze: la respuesta debe estar entre las opciones")
def cloze(texto, clave, num=1):
    return [q(num, "cloze", {"text": texto})], {num: {"type": "cloze", "answer": clave}}

qs, ak = cloze("La capital es [A: Lima / Quito / Bogota].", "A. Caracas")
ok(any("no coincide con ninguna de las opciones disponibles" in x for x in errores(qs, ak)), "«Caracas» fuera de las opciones: error de validación")
ok(lanza(qs, ak), "el constructor no marca «=Lima»")
qs, ak = cloze("Lenguaje: [A: Java / Python 2 / Python 3].", "A. Python")
ok(any("ambigua" in x for x in errores(qs, ak)) and lanza(qs, ak), "respuesta de Completar ambigua: error y no se elige")
qs, ak = cloze("Capital de Perú: [A: Lima / Quito / Bogota].", "A. lima")
xml, _ = build_xml(qs, ak)
ok(not errores(qs, ak) and "=Lima~Quito~Bogota" in xml, "legítimo: diferencia de mayúsculas")
qs, ak = cloze("País: [A: Perú / Chile / Bolivia].", "A. Peru")
xml, _ = build_xml(qs, ak)
ok(not errores(qs, ak) and "=Perú~Chile~Bolivia" in xml, "legítimo: la clave sin tilde marca la opción con tilde (y el texto conserva la tilde)")
qs, ak = cloze("Marca [A: uno / dos / tres] y [B: rojo / azul].", "A. uno | tres; B. azul")
xml, _ = build_xml(qs, ak)
ok(not errores(qs, ak) and "MULTIRESPONSE_S:=uno~dos~=tres" in xml and "MULTICHOICE_S:rojo~=azul" in xml, "varias correctas y varios huecos")
qs, ak = cloze("Es un [A: vegetal / mineral].", "vegetal")
xml, _ = build_xml(qs, ak)
ok(not errores(qs, ak) and "=vegetal~mineral" in xml, "formato legado sin letra: la clave completa")
qs, ak = cloze("Es un [A: vegetal / mineral].", "animal")
ok(bool(errores(qs, ak)) and lanza(qs, ak), "formato legado con respuesta que no está: error, no «=vegetal»")
ok(resolver_hueco_cloze("B", ["A", "B"]) == (1, None), "en un hueco, «B» es el texto de la opción (no una letra)")

print("Cloze: saltos de línea y sangría del enunciado")
codigo = "Complete el código:\ndef f(x):\n    return [A: x + 1 / x - 1]\n        # fin"
qs, ak = cloze(codigo, "A. x + 1")
xml, _ = build_xml(qs, ak)
qt = etree.fromstring(xml.encode("utf-8")).find("question/questiontext/text").text
ok("<br>" in qt and "\n" not in qt, "los \\n pasan a <br>")
ok("<br>&nbsp;&nbsp;&nbsp;&nbsp;return {" in qt, "la sangría del código se conserva con &nbsp;")
ok("<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;# fin" in qt, "sangría de segundo nivel")
ok("{1:MULTICHOICE_S:=x + 1~x - 1}" in qt, "el hueco queda intacto")
qs, ak = cloze('Elige [A: a<b / a&b / "c"] y [B: 50~60 / x/y / p\\q].\n  fin', 'A. a<b; B. x/y')
xml, _ = build_xml(qs, ak)
qt = etree.fromstring(xml.encode("utf-8")).find("question/questiontext/text").text
ok('=a&lt;b~a&amp;b~"c"' in qt, "dentro del hueco: < & se escapan y la comilla queda tal cual (Moodle no quita la barra)")
ok("50&#126;60" in qt and "=x/y" in qt and "p&#92;q" in qt, "dentro del hueco: ~ y \\ van como entidad (&#126; y &#92;) y «/» sin escapar")
ok(qt.endswith("<br>&nbsp;&nbsp;fin</p>"), "la sangría después de un hueco también")
ok(convert_cloze_to_moodle("a\n b [A: x / y]", 1, {1: {"answer": "A. x"}}) == "a\n b {1:MULTICHOICE_S:=x~y}", "por defecto convert_cloze_to_moodle no cambia su salida")

# ── 3. Numérica estricta ──────────────────────────────────────────────────
print("Numérica: solo números que Moodle entiende")
def num_q(resp):
    return [q(1, "numerical", {"stem": "¿Cuánto?"})], {1: {"type": "numerical", "answer": resp}}

for malo in ("nan", "inf", "-inf", "Infinity", "1_000", "٣", "１２", "1,2,3", "", "1 000", "0x10", "3.5.1", "e5"):
    qs, ak = num_q(malo)
    if malo == "":
        continue  # lo cubre «sin respuesta especificada»
    ok(any("no es un número válido" in x for x in errores(qs, ak)), f"«{malo}» se rechaza")
    ok(lanza(qs, ak), f"«{malo}»: el constructor tampoco lo escribe")
for bueno, esperado in (("42", "42"), ("-3,5", "-3.5"), ("+7", "+7"), (".5", ".5"), ("5.", "5."), ("1e3", "1e3"), ("2,5E-3", "2.5E-3"), (" 9,75 ", "9.75")):
    qs, ak = num_q(bueno)
    xml, _ = build_xml(qs, ak)
    ok(not errores(qs, ak) and f"<text>{esperado}</text>" in xml, f"«{bueno}» → {esperado}")
ok(normalizar_numero("nan") is None, "normalizar_numero(«nan») es None")

# ── 4. Matching: letras sin distinguir mayúsculas ─────────────────────────
print("Matching: la letra se normaliza igual en validador y constructor")
def matching(col_b, pares):
    return ([q(1, "matching", {"stem": "Une", "col_a": {"1": "Perú", "2": "Chile"}, "col_b": col_b})],
            {1: {"type": "matching", "answer": "x", "pairs": pares}})

qs, ak = matching({"A": "Lima", "B": "Santiago"}, {"1": "B", "2": "A"})
xml, _ = build_xml(qs, ak)
sub = re.findall(r"<subquestion.*?<text><!\[CDATA\[(.*?)\]\]></text>\s*<answer><text><!\[CDATA\[(.*?)\]\]>", xml, re.S)
ok(not errores(qs, ak) and sub == [("Perú", "Santiago"), ("Chile", "Lima")], "columna «A/B» con pares «B/A»: parejas correctas (no secuenciales)")
qs, ak = matching({"a": "Lima", "b": "Santiago"}, {"1": "b", "2": "a"})
xml, _ = build_xml(qs, ak)
ok(not errores(qs, ak) and "Santiago" in xml.split("Perú")[1].split("</subquestion>")[0], "columna «a/b» con pares «b/a» (flujo normal) sigue igual")
qs, ak = matching({"a": "Lima", "b": "Santiago"}, {"1": "z", "2": "a"})
ok(bool(errores(qs, ak)) and lanza(qs, ak), "letra que no existe: error y no se inventa el orden secuencial")
qs, ak = matching({"a": "Lima", "b": "Santiago"}, {})
ok(bool(errores(qs, ak)) and lanza(qs, ak), "sin clave de pares: error y no se inventa el orden secuencial")
ok(clave_de_columna({"a": "x"}, "A") == "a" and clave_de_columna({"a": "x"}, "b") is None, "clave_de_columna")

# ── 5. Verdadero/Falso ────────────────────────────────────────────────────
print("Verdadero/Falso: mismos alias en validador y constructor")
def tf(resp):
    return [q(1, "truefalse", {"stem": "El cielo es azul"})], {1: {"type": "truefalse", "answer": resp}}

for resp, verdadera in (("V", True), ("v", True), ("Verdadero ", True), (" verdadero", True), ("true", True),
                        ("F", False), ("Falso", False), ("falso  ", False), ("false", False)):
    qs, ak = tf(resp)
    xml, _ = build_xml(qs, ak)
    m = re.search(r'<answer fraction="100">\s*<text>(\w+)</text>', xml)
    ok(not errores(qs, ak) and m and m.group(1) == ("true" if verdadera else "false"), f"«{resp}» → {'true' if verdadera else 'false'}")
qs, ak = tf("quizás")
ok(bool(errores(qs, ak)) and lanza(qs, ak), "«quizás»: error, no se toma como falso")

# ── 6. Categoría ──────────────────────────────────────────────────────────
print("Categoría: sin subcategorías accidentales ni longitud sin límite")
def categoria_xml(cat):
    qs, ak = tf("V")
    xml, _ = build_xml(qs, ak, category=cat)
    return etree.fromstring(xml.encode("utf-8")).find("question/category/text").text

ok(categoria_xml("Parcial 1/2 2026") == "$course$/Parcial 1-2 2026", "un «/» ya no crea subcategorías")
ok(categoria_xml("  a//b/  ") == "$course$/a--b-", "espacios recortados y barras sustituidas")
ok(categoria_xml("mis-preguntas") == "$course$/mis-preguntas", "el nombre normal queda igual")
ok(categoria_xml("   ") == "$course$/mis-preguntas" and categoria_xml("") == "$course$/mis-preguntas", "vacía: nombre por defecto")
ok(len(sanear_categoria("x" * 5000)) == 200, "longitud acotada a 200")
ok(categoria_xml("Áé ñ <b> & \"c\"") == "$course$/Áé ñ <b> & \"c\"", "tildes conservadas y caracteres XML bien escapados (el XML sigue bien formado)")

# ── 7. Puntos de Completar: aviso ─────────────────────────────────────────
print("Completar con 0 puntos: se avisa (Moodle da mínimo 1 por hueco)")
def dos_clozes(puntos):
    qs = [
        {**q(1, "cloze", {"text": "[A: uno / dos] y [B: tres / cuatro] y [C: cinco / seis]"}), "points": puntos},
        {**q(2, "multichoice", {"stem": "q", "options": {"A": "x", "B": "y"}}), "points": 5},
    ]
    ak = {1: {"type": "cloze", "answer": "A. uno; B. tres; C. cinco"}, 2: {"type": "multichoice", "answer": "A"}}
    return qs, ak

qs, ak = dos_clozes(0)
_, stats = build_xml(qs, ak, grades=compute_grades(qs, 100))
ok(len(stats.avisos) == 1 and "Pregunta 1".lower() in stats.avisos[0].lower() and "0 punto" in stats.avisos[0] and "3" in stats.avisos[0],
   "0 puntos: un aviso que dice cuánto valdrá en Moodle")
qs, ak = dos_clozes(6)
_, stats = build_xml(qs, ak, grades=compute_grades(qs, 100))
ok(stats.avisos == [], "puntos normales: sin avisos")
ok(dos_clozes(3)[0][0]["points"] == 3 and build_xml(*dos_clozes(3), grades=compute_grades(dos_clozes(3)[0], 100))[1].avisos == [],
   "un punto por hueco exacto: sin avisos")

print("Completar: un espacio con una sola opción se rechaza; los puntos desiguales entre espacios se avisan")
def cloze_uno(texto, clave):
    return [q(1, "cloze", {"text": texto})], {1: {"type": "cloze", "answer": clave}}
for texto, clave, esperado in (
    ("La capital es [A: Roma]", "A. Roma", "una sola opción"),
    ("[A: uno / dos] y [B: tres]", "A. uno; B. tres", "[B] tiene una sola opción"),
    ("La capital es [A: ]", "A. x", "vacío"),
):
    qs1, ak1 = cloze_uno(texto, clave)
    errs = validate_questions(qs1, ak1).errors
    ok(any(esperado in e for e in errs), f"«{texto}»: se rechaza ({esperado})")
qs1, ak1 = cloze_uno("[A: Roma / Lima]", "A. Roma")
ok(validate_questions(qs1, ak1).is_valid, "dos opciones: se acepta")

qs, ak = dos_clozes(19)
_, stats = build_xml(qs, ak, grades=compute_grades(qs, 100))
ok(len(stats.avisos) == 1 and "la 1: 7, 6, 6" in stats.avisos[0] and "no cambia" in stats.avisos[0], f"19 puntos en 3 espacios: un aviso con el reparto 7, 6, 6 ({stats.avisos})")
qs, ak = dos_clozes(18)
_, stats = build_xml(qs, ak, grades=compute_grades(qs, 100))
ok(stats.avisos == [], "18 puntos en 3 espacios (6, 6, 6): sin avisos")

print("Respuesta corta: la variante sin tildes cubre todas las del español")
from xml_builder import strip_accents  # noqa: E402
for _con, _sin in (("Fotosíntesis", "Fotosintesis"), ("pingüino", "pinguino"), ("PINGÜINO", "PINGUINO"), ("niño", "nino"),
                   ("Ñandú", "Nandu"), ("lingüística", "linguistica"), ("café", "cafe"), ("ÁÉÍÓÚ", "AEIOU"), ("sin tildes", "sin tildes"), ("x²", "x²")):
    ok(strip_accents(_con) == _sin, f"«{_con}» → «{strip_accents(_con)}»")

print("Respuesta corta: la respuesta va como texto plano, sin escapes HTML (Moodle la compara tal cual)")
def respuestas_cortas(respuesta):
    qs = [{"num": 1, "type": "shortanswer", "data": {"stem": "¿Quién?"}}]
    ak = {1: {"type": "shortanswer", "answer": respuesta}}
    xml, _ = build_xml(qs, ak, grades=compute_grades(qs, 10))
    raiz = etree.fromstring(xml.encode("utf-8"))                     # el XML es válido
    return [(a.get("fraction"), a.get("format"), a.findtext("text")) for a in raiz.iter("answer")], xml
for resp in ("O'Higgins", "AT&T", "R&D", "x < y", 'dijo "hola"', "a]]>b", "Panamá", "2 * 3", "H₂O"):
    filas, xml = respuestas_cortas(resp)
    esperado = resp.replace("*", "\\*")
    ok(filas[0] == ("100", "plain_text", esperado), f"«{resp}»: Moodle recibe exactamente «{filas[0][2]}»")
    ok("&#x27;" not in xml and "&amp;amp;" not in xml and "&amp;T" not in xml.split("<answer", 1)[1], f"«{resp}»: sin entidades dentro del CDATA")
filas, _ = respuestas_cortas("Panamá")
ok([f[2] for f in filas] == ["Panamá", "Panama"], "la variante sin tildes sigue como segunda respuesta válida")

print("Puntos no válidos: se avisa (antes se sustituían en silencio por el reparto por tipo)")
def examen_puntos(puntos):
    qs = [{**q(i + 1, "multichoice", {"stem": f"p{i}", "options": {"A": "x", "B": "y"}}), "points": v} for i, v in enumerate(puntos)]
    for qq, v in zip(qs, puntos):
        if v == "AUSENTE":
            del qq["points"]
    ak = {i + 1: {"type": "multichoice", "answer": "A"} for i in range(len(puntos))}
    return build_xml(qs, ak, grades=compute_grades(qs, 30))
_, st = examen_puntos([10, 10, 10])
ok(st.avisos == [], "puntos válidos: sin avisos")
_, st = examen_puntos([0, 10, 20])
ok(st.avisos == [], "0 es un puntaje válido: sin avisos")
_, st = examen_puntos([10, -5, 10])
ok(len(st.avisos) == 1 and "la 2: '-5'" in st.avisos[0] and "reparto por tipo" in st.avisos[0], f"un puntaje negativo se avisa ({st.avisos})")
_, st = examen_puntos([10, "abc", float("nan"), float("inf"), True])
ok(len(st.avisos) == 1 and st.avisos[0].startswith("4 pregunta(s)"), f"texto, NaN, infinito y booleano: un aviso que cuenta 4 ({st.avisos[0][:60]})")
_, st = examen_puntos([10, "AUSENTE", 10])
ok(len(st.avisos) == 1 and "no traían puntaje (la 2)" in st.avisos[0], f"una pregunta sin puntaje cuando las demás sí lo traen se avisa ({st.avisos})")
_, st = examen_puntos(["AUSENTE", "AUSENTE"])
ok(st.avisos == [], "ninguna trae puntaje (se usa el reparto por tipo, como siempre): sin avisos")
xml_neg, _ = examen_puntos([10, -5, 10])
ok(re.findall(r"<defaultgrade>([\d.]+)</defaultgrade>", xml_neg)[1] != "-5.0", "el XML no lleva nunca un puntaje negativo")

print("Opción múltiple: las que dependen de su posición («todas las anteriores») no se mezclan en Moodle")
from answer_matching import OPCION_POSICIONAL  # noqa: E402
def mc_xml(opciones, respuesta="A"):
    qs = [q(1, "multichoice", {"stem": "¿Cuál?", "options": opciones})]
    ak = {1: {"type": "multichoice", "answer": respuesta}}
    return build_xml(qs, ak, grades=compute_grades(qs, 10))
for opciones, debe in (
    ({"A": "Uno", "B": "Dos", "C": "Todas las anteriores"}, False),
    ({"A": "Uno", "B": "Dos", "C": "A y B"}, False),
    ({"A": "Uno", "B": "Ninguna de las anteriores"}, False),
    ({"A": "Ambas son verdaderas", "B": "Ninguna"}, False),
    ({"A": "def", "B": "class", "C": "import"}, True),       # «def» NO es «D e F»
    ({"A": "Mercurio", "B": "Venus", "C": "Marte"}, True),
):
    xml, st = mc_xml(opciones)
    mezcla = "<shuffleanswers>1</shuffleanswers>" in xml
    ok(mezcla == debe, f"{list(opciones.values())}: {'se mezcla' if mezcla else 'NO se mezcla'}")
    ok(bool(st.avisos) == (not debe), f"…{'sin aviso' if debe else 'con un aviso que lo dice'}")
_, st = mc_xml({"A": "Uno", "B": "Dos", "C": "Todas las anteriores"})
ok("la 1" in st.avisos[0] and "NO se mezclan" in st.avisos[0], f"el aviso dice qué preguntas ({st.avisos[0][:80]}…)")
for t in ("def", "bed", "bee", "dye", "age", "Python", "H2O"):
    ok(not OPCION_POSICIONAL.search(t), f"«{t}» no es una opción posicional")
for t in ("A y B", "B, C", "A e I", "C o D", "A,B", "la opción C", "Todas las anteriores", "Ambas"):
    ok(OPCION_POSICIONAL.search(t), f"«{t}» sí lo es")

print("Numérica: «1,000» es ambiguo (mil o uno con tres decimales) y el separador de miles se explica")
from answer_matching import miles_ambiguo, sin_separador_de_miles  # noqa: E402
for _txt, _esperado in (("1,000", ("1.000", "1000")), ("1.000", ("1.000", "1000")), ("12,345", ("12.345", "12345")), ("-3.141", ("-3.141", "-3141")),
                        ("999,999", ("999.999", "999999")), ("+1,500", ("+1.500", "+1500")),
                        ("0,500", None), ("0.001", None), ("3,5", None), ("3.14", None), ("1000", None), ("1234,567", None), ("1,00", None), ("9.8", None), ("", None), ("abc", None)):
    ok(miles_ambiguo(_txt) == _esperado, f"miles_ambiguo({_txt!r}) = {miles_ambiguo(_txt)}")
for _txt, _esperado in (("1,234.5", "1234.5"), ("1.234,5", "1234.5"), ("1,234,567", "1234567"), ("12.345.678", "12345678"), ("1.234.567,89", "1234567.89"),
                        ("1,000", None), ("3,5", None), ("1234", None), ("1,2345", None), ("abc", None)):
    ok(sin_separador_de_miles(_txt) == _esperado, f"sin_separador_de_miles({_txt!r}) = {sin_separador_de_miles(_txt)}")

def numerica(resp):
    qs = [q(1, "numerical", {"stem": "¿Cuánto?"})]
    ak = {1: {"type": "numerical", "answer": resp}}
    return qs, ak
qs, ak = numerica("1,000")
xml, st = build_xml(qs, ak, grades=compute_grades(qs, 10))
ok("<text>1.000</text>" in xml and len(st.avisos) == 1 and "«1,000» se guardó como 1.000, no como 1000" in st.avisos[0] and "tolerancia 0" in st.avisos[0],
   f"«1,000»: se guarda como 1.000 y se AVISA ({st.avisos[:1]})")
for ok_txt in ("3,5", "1000", "0,500", "9.807"[:1] + "." + "8", "-12"):
    _, st = build_xml(*numerica(ok_txt), grades=compute_grades(numerica(ok_txt)[0], 10))
    ok(st.avisos == [], f"«{ok_txt}»: sin avisos")
r = validate_questions(*numerica("1,234.5"))
ok(not r.is_valid and "no es un número válido" in r.errors[0] and "(por ejemplo 1234.5)" in r.errors[0], f"«1,234.5» se rechaza y dice cómo escribirlo ({r.errors[:1]})")
r = validate_questions(*numerica("abc"))
ok(not r.is_valid and "separador de miles" not in r.errors[0], "un texto cualquiera se rechaza sin la pista de miles")

print()
print("TODO OK" if not fallas else f"{fallas} FALLA(S)")
sys.exit(1 if fallas else 0)
