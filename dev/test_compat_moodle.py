"""
test_compat_moodle.py — Versión 1.10: el XML que se genera lo ACEPTA Moodle (no solo «sale igual»).

    PYTHONUTF8=1 backend/venv/bin/python dev/test_compat_moodle.py

Sin red ni Gemini. Cubre los dos defectos que se hallaron en un Moodle real
(el de la UTP, 3-oct-2026) y que las pruebas anteriores no podían ver porque
solo comprobaban que el XML fuera el mismo:

  1. Fracciones de opción múltiple. El importador de Moodle rechaza cualquier
     `fraction` que no esté en su lista; con «Detenerse en error = Sí» (lo
     normal) UNA pregunta así hace que NO se importe NINGUNA del archivo.
     100/n solo está en la lista para n de 1 a 10 y 20.
  2. Escapes de «Completar». Moodle des-escapa únicamente «\\}» y «\\#» (y aplica
     html_entity_decode): cualquier otra barra se ve en pantalla («TCP\\/IP»).

Para (2) hay un «oráculo»: un lector de las opciones de un hueco escrito como lo
hace Moodle (question/type/multianswer/questiontype.php, Moodle 4.5). Cada
opción tiene que volver EXACTAMENTE igual a como se escribió.
"""

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "dev"))
sys.path.insert(0, str(ROOT / "dev" / "synthetic"))

import xml_fidelity as xf  # noqa: E402  (apaga el logging)
from xml_builder import _repartir_fraccion, build_xml, convert_cloze_to_moodle  # noqa: E402

fallas = 0


def ok(cond, msg):
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


# Porcentajes que acepta el importador de Moodle (y sus negativos), medidos en el Moodle real.
VALIDAS = {100, 90, 83.33333, 80, 75, 70, 66.66667, 60, 50, 40, 33.33333, 30, 25, 20, 16.66667,
           14.28571, 12.5, 11.11111, 10, 5}
VALIDAS |= {-v for v in VALIDAS} | {0}


# ══════════════════════════════════════════════════════════════════════════
print("1. Fracciones de opción múltiple: todas válidas para Moodle")
# ══════════════════════════════════════════════════════════════════════════

def xml_mc(total, correctas):
    opciones = {chr(65 + i): f"Opción {i + 1}" for i in range(total)}
    q = {"num": 1, "type": "multichoice", "data": {"stem": "¿Cuáles?", "options": opciones}}
    clave = {1: {"type": "multichoice", "answer": " | ".join(opciones[chr(65 + i)] for i in range(correctas)),
                 "correct_idx": list(range(correctas))}}
    xml, stats = build_xml([q], clave)
    return xml, stats, [float(f) for f in re.findall(r'<answer fraction="([^"]+)"', xml)]


malas = []
for total in range(2, 31):
    for correctas in range(1, total):
        _, _, fracs = xml_mc(total, correctas)
        if any(f not in VALIDAS for f in fracs):
            malas.append((total, correctas, sorted(set(f for f in fracs if f not in VALIDAS))))
ok(not malas, f"ninguna combinación de 2 a 30 opciones produce un porcentaje fuera de la lista de Moodle ({malas[:3]})")

# Las que antes funcionaban no cambian: mismas fracciones que con 100/n.
_, _, f = xml_mc(8, 3)
ok(f[:3] == [33.33333] * 3 and set(f[3:]) == {-20.0}, "3 correctas de 8: 33,33333 y -20 (igual que siempre)")
_, _, f = xml_mc(6, 2)
ok(sorted(f) == [-25.0] * 4 + [50.0] * 2, "2 correctas de 6: 50 y -25 (igual que siempre)")
_, _, f = xml_mc(4, 1)
ok(sorted(f) == [0.0] * 3 + [100.0], "una sola correcta: 100 y 0 (igual que siempre)")

# Con 11 a 19 correctas: 10 % y 5 %, sumando exactamente 100.
for k in range(11, 20):
    r = _repartir_fraccion(k)
    ok(len(r) == k and sum(r) == 100 and set(r) <= {10.0, 5.0} and r == sorted(r, reverse=True),
       f"{k} correctas: {r.count(10.0)}×10 % + {r.count(5.0)}×5 % = 100")
xml, stats, f = xml_mc(25, 12)
pos = [x for x in f if x > 0]
neg = [x for x in f if x < 0]
ok(abs(sum(pos) - 100) < 1e-6 and abs(sum(neg) + 100) < 1e-6, "12 correctas y 13 incorrectas: positivas suman 100 y negativas -100")
ok(len(stats.avisos) == 2 and all("10 % y 5 %" in a for a in stats.avisos), "y se avisa al docente (una vez por grupo)")
_, stats_ok, _ = xml_mc(8, 3)
ok(not stats_ok.avisos, "sin reparto especial no hay aviso")
r = _repartir_fraccion(21)
ok(set(r) == {5.0} and len(r) == 21, "más de 20: todas 5 % (válido; el archivo se importa)")
_, stats21, _ = xml_mc(45, 22)
ok(any("más de las 20" in a for a in stats21.avisos), "y se avisa de que son más de 20")


# ══════════════════════════════════════════════════════════════════════════
print("2. «Completar»: lo que escribe la app es lo que lee Moodle")
# ══════════════════════════════════════════════════════════════════════════

def _termina_aqui(texto, i):
    """¿El delimitador de la posición i cuenta? No si lleva «\\» delante ni si el texto
    anterior termina en «&» o «&amp;» (así lo lee Moodle)."""
    previo = texto[:i]
    return not (previo.endswith("\\") or previo.endswith("&") or previo.endswith("&amp;"))


def moodle_lee_hueco(hueco):
    """{n:MULTICHOICE_S:=a~b} → [(texto, correcta)], como lo interpreta Moodle."""
    m = re.match(r"\{\d+:MULTI(?:CHOICE|RESPONSE)_S:", hueco)
    cuerpo = hueco[m.end():]
    opciones, actual, i = [], "", 0
    while i < len(cuerpo):
        c = cuerpo[i]
        if c in "~#}" and _termina_aqui(actual, len(actual)):
            if c == "}":
                break
            if c == "~":
                opciones.append(actual)
                actual = ""
                i += 1
                continue
        actual += c
        i += 1
    else:
        raise AssertionError("el hueco no se cierra")
    opciones.append(actual)
    salida = []
    for o in opciones:
        correcta = o.startswith("=")
        if correcta:
            o = o[1:]
        o = o.replace("\\}", "}").replace("\\#", "#")
        salida.append((html.unescape(o), correcta))
    return salida, cuerpo[i + 1:]


BATERIA = [
    "TCP/IP", "10 / 2", "km/h", 'dijo "hola"', "{llave}", "a~b", "c#d", "e}f", "g\\h", "\\", "~", "#", "}", "{",
    "R&", "AT&", "x & y", "&amp;", "&#126;", "a &amp; b", "<b>negrita</b>", "a < b > c", "50%", "C:\\ruta\\x",
    "\\}", "\\#", "\\~", "a\\", "a~", "~a", "dos  espacios", "tilde á ñ", "100 / 3 = 33,33",
]
for modo in (True, False):
    etiqueta = "HTML" if modo else "texto plano"
    errores = []
    for i, opcion in enumerate(BATERIA):
        otras = ["otra uno", "otra dos"]
        correctas = [opcion]
        clave = {1: {"answer": f"A. {opcion}", "huecos": [{"letra": "A", "options": [opcion] + otras, "correct_idx": [0]}]}}
        texto = "[A: " + " / ".join([opcion] + otras) + "]"  # el enunciado coincide con la estructura
        slot = convert_cloze_to_moodle(texto, 1, clave, como_html=modo)
        if modo:
            # En HTML el hueco va dentro de <p>…</p> sin más cambios: es el texto tal cual.
            pass
        try:
            leidas, resto = moodle_lee_hueco(slot)
        except AssertionError as e:
            errores.append((opcion, slot, str(e)))
            continue
        if resto != "" or [t for t, _ in leidas] != [opcion] + otras or [c for _, c in leidas] != [True, False, False]:
            errores.append((opcion, slot, leidas))
    ok(not errores, f"las {len(BATERIA)} opciones difíciles vuelven idénticas al leerlas como Moodle ({etiqueta}) {errores[:2]}")

_ops = ["TCP/IP", 'a"b', "{x}", "p~q", "r\\s", "u#v", "w}z"]
slot = convert_cloze_to_moodle("[A: " + " / ".join(_ops) + "]", 1, {1: {"answer": "A. TCP/IP", "huecos": [
    {"letra": "A", "options": _ops, "correct_idx": [0]}]}})
ok(slot == '{1:MULTICHOICE_S:=TCP/IP~a"b~{x\\}~p&#126;q~r&#92;s~u\\#v~w\\}z}', f"forma exacta del hueco ({slot})")
ok("\\/" not in slot and '\\"' not in slot and "\\{" not in slot, "ya no quedan «\\/», «\\\"» ni «\\{» (se veían en el desplegable)")

# De punta a punta: el XML completo con esos caracteres sigue siendo XML válido y trae el hueco bien.
q = {"num": 1, "type": "cloze", "data": {"text": "Elige [A: TCP/IP / R&D / a<b]."}}
xml, _ = build_xml([q], {1: {"type": "cloze", "answer": "A. TCP/IP", "huecos": [
    {"letra": "A", "options": ["TCP/IP", "R&D", "a<b"], "correct_idx": [0]}]}})
xf.read_xml(xml)  # lanza si no es XML bien formado
cuerpo = re.search(r"<!\[CDATA\[<p>(.*?)</p>\]\]>", xml, re.S).group(1)
leidas, resto = moodle_lee_hueco(re.search(r"\{[^}]*\}", cuerpo).group(0))
ok([t for t, _ in leidas] == ["TCP/IP", "R&D", "a<b"] and resto == "", f"XML completo: opciones leídas por Moodle = {[t for t, _ in leidas]}")

print()
print("TODO OK" if not fallas else f"{fallas} FALLA(S)")
sys.exit(1 if fallas else 0)
