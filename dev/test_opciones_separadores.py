"""
test_opciones_separadores.py — opciones cuyo PROPIO texto contiene los separadores
internos (« | » entre respuestas correctas, « / » entre opciones de un hueco).

    backend/venv/bin/python dev/test_opciones_separadores.py

Antes, una opción como `x | y` (típica de programación) se partía en dos al volver a
leer la clave ("x" y "y" no coinciden con ninguna opción: error de validación falso que
bloqueaba la exportación) y una de «Completar» como `10 / 2` se partía en `10` y `2`; y
schema_adapter además cambiaba « / » por «/» dentro del texto (alteraba el contenido del
docente). Ahora las correctas viajan además como ÍNDICES (answer_key[n]["correct_idx"] en
opción múltiple; answer_key[n]["huecos"] con las opciones como lista en «Completar») y
todo el camino los usa si existen, o analiza el texto como siempre si faltan.

No llama a Gemini ni a la red; no toca el historial, la clave ni los datos de la app.
"""

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "dev"))
sys.path.insert(0, str(ROOT / "dev" / "synthetic"))

import xml_fidelity as xf  # noqa: E402  (apaga el logging)
import test_xml_baseline as base  # noqa: E402
import mark_resolver  # noqa: E402
from answer_matching import (  # noqa: E402
    indices_utilizables, resolver_correctas_cloze, resolver_correctas_multichoice,
)
from modelo import Clave, HuecoClave, Pregunta, huecos_de_cloze  # noqa: E402
from schema_adapter import adapt  # noqa: E402
from validator import partition_questions, validate_questions  # noqa: E402
from xml_builder import build_xml, convert_cloze_to_moodle  # noqa: E402

fallas = 0


def ok(cond, msg):
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


def pregunta_ia(**kw):
    """Una pregunta como la entrega la IA (salida estructurada)."""
    return {"orden": kw.pop("orden", 1), "respuesta_marcada": True, "confianza": "alta", **kw}


def mc(orden, enunciado, opciones, correctas):
    return pregunta_ia(orden=orden, tipo="multichoice", enunciado=enunciado, opciones=[
        {"letra_original": "abcdef"[i], "texto": t, "correcta": i in correctas} for i, t in enumerate(opciones)])


def cloze(orden, texto, huecos):
    return pregunta_ia(orden=orden, tipo="cloze", enunciado=texto, huecos=[
        {"marcador": "ABCDEF"[k], "opciones": [{"letra_original": "", "texto": t, "correcta": i in c}
                                              for i, t in enumerate(ops)]}
        for k, (ops, c) in enumerate(huecos)])


def convertir(payload):
    questions, key = adapt(payload)
    validas, omitidas = partition_questions(questions, key)
    xml, _ = build_xml(validas, key)
    return questions, key, validas, omitidas, xml


# ── 1. Modelo: ida y vuelta exacta con los campos nuevos ────────────────────
print("Modelo: correct_idx y huecos")
entrada = {"type": "multichoice", "answer": "x | y", "from_key": True, "correct_idx": [1]}
c = Clave.desde_dict(entrada)
ok(c.correct_idx == [1] and c.a_dict() == entrada and list(c.a_dict()) == list(entrada), "Clave.correct_idx: ida y vuelta exacta, mismo orden")
entrada = {"type": "cloze", "answer": "A. 10 / 2", "huecos": [
    {"letra": "A", "options": ["10 / 2", "5"], "correct_idx": [0], "extra": 1}, {"letra": "B", "options": [], "correct_idx": []}]}
c = Clave.desde_dict(entrada)
ok(isinstance(c.huecos[0], HuecoClave) and c.huecos[0].options == ["10 / 2", "5"], "Clave.huecos: cada hueco es un HuecoClave tipado")
ok(c.a_dict() == entrada and list(c.a_dict()["huecos"][0]) == ["letra", "options", "correct_idx", "extra"],
   "Clave.huecos: ida y vuelta exacta (también campos desconocidos y su orden)")
for malo in ({"correct_idx": "1"}, {"correct_idx": [True]}, {"correct_idx": [1.5]}, {"huecos": {"A": 1}}, {"huecos": ["A"]}):
    c = Clave.desde_dict({"type": "multichoice", "answer": "x", **malo})
    ok(c.a_dict() == {"type": "multichoice", "answer": "x", **malo}, f"valor de tipo raro {malo} se conserva tal cual")
c = Clave.desde_dict({"type": "cloze", "answer": "A. x", "huecos": [{"letra": "A", "options": ["x", 3], "correct_idx": ["0"]}]})
ok(c.huecos[0].options is None and c.a_dict()["huecos"][0] == {"letra": "A", "options": ["x", 3], "correct_idx": ["0"]},
   "un hueco con tipos raros no se pierde ni se corrige")
ok(Clave.desde_dict({"type": "multichoice", "answer": "A"}).a_dict() == {"type": "multichoice", "answer": "A"},
   "campos ausentes no aparecen al volver a escribir (comportamiento de hoy)")
p = Pregunta.desde_dict({"num": 1, "type": "multichoice", "data": {"stem": "s", "options": {"A": "x | y", "B": "z"}}})
p.respuesta = Clave.desde_dict({"type": "multichoice", "answer": "x | y", "correct_idx": [0]})
ok(p.resolver_correctas() == (["A"], []), "PreguntaMultichoice.resolver_correctas usa correct_idx")

print("answer_matching: resolución por índices")
ok(indices_utilizables([2, 0, 2], 3) == [2, 0], "índices: sin repetir y en su orden")
ok(all(indices_utilizables(v, 3) is None for v in ([], None, "0", [3], [-1], [True], [0.0], [None])), "índices inválidos → None")
ops = {"A": "x | y", "B": "x", "C": "y"}
ok(resolver_correctas_multichoice(ops, "x | y", None) == (["B", "C"], []), "sin índices, «x | y» se parte (comportamiento de siempre)")
ok(resolver_correctas_multichoice(ops, "x | y", [0]) == (["A"], []), "con índices, «x | y» es UNA opción")
ok(resolver_correctas_multichoice(ops, "x", [0])[0] == ["B"], "índices que no concuerdan con el texto de la clave: manda el texto")
ok(resolver_correctas_multichoice(ops, "x | y", [7])[0] == ["B", "C"], "índices fuera de rango: manda el texto")
ok(resolver_correctas_cloze(["10 / 2", "5"], ["10", "2"], [0]) == ([0], []), "hueco: índices tal cual")
ok(resolver_correctas_cloze(["10 / 2", "5"], ["5"], None) == ([1], []), "hueco: sin índices, por texto")

# ── 2. adapt(): produce los índices y no altera las opciones ─────────────────
print("schema_adapter.adapt con separadores dentro de las opciones")
payload = {"es_examen": True, "preguntas": [
    mc(1, "¿Qué operador hace una O bit a bit?", ["x | y", "x & y", "a || b", "x ^ y"], [0]),
    mc(2, "Selecciona las expresiones con una O.", ["a || b", "a && b", "a | b", "a + b"], [0, 2]),
    mc(3, "Rutas.", ["C:\\ruta / otra", "C:\\ruta", "/usr/bin"], [0, 2]),
    mc(4, "Sin marcar.", ["x | y", "z"], []),
    cloze(5, "El resultado de [A] es cinco y la ruta es [B].",
          [(["10 / 2", "5 / 1", "2"], [0]), (["C:\\ruta / otra", "C:\\ruta"], [0])]),
    cloze(6, "Dos con una O: [A]. Sin marcar: [B].",
          [(["x | y", "z | w", "q"], [0, 1]), (["uno", "a / b"], [])]),
]}
questions, key, validas, omitidas, xml = convertir(payload)
ok(key[1]["correct_idx"] == [0] and key[2]["correct_idx"] == [0, 2] and key[3]["correct_idx"] == [0, 2],
   "multichoice: answer_key[n]['correct_idx'] sale de la bandera «correcta» de la IA")
ok("correct_idx" not in key[4] and key[4]["answer"] == "SIN_RESPUESTA", "multichoice sin marcar: sin correct_idx")
ok(key[2]["answer"] == "a || b | a | b", "el texto unido se sigue generando (compatibilidad)")
ok(questions[0]["data"]["options"]["A"] == "x | y" and questions[2]["data"]["options"]["A"] == "C:\\ruta / otra",
   "las opciones llegan intactas")
ok(key[5]["huecos"] == [{"letra": "A", "options": ["10 / 2", "5 / 1", "2"], "correct_idx": [0]},
                        {"letra": "B", "options": ["C:\\ruta / otra", "C:\\ruta"], "correct_idx": [0]}],
   "cloze: answer_key[n]['huecos'] con las opciones como lista y las correctas por índice")
ok("10 / 2" in questions[4]["data"]["text"] and "C:\\ruta / otra" in questions[4]["data"]["text"],
   "cloze: adapt ya no reemplaza « / » por «/» dentro de una opción")
ok(key[6]["huecos"][1] == {"letra": "B", "options": ["SIN_RESPUESTA", "uno", "a / b"], "correct_idx": []},
   "cloze sin marcar: la estructura lleva SIN_RESPUESTA como en el texto, sin índices")
ok(key[6]["answer"] == "A. x | y | z | w; B. SIN_RESPUESTA", "cloze: el texto de la clave se sigue generando")

print("Validación y XML con las opciones intactas")
v = validate_questions(questions[:3] + questions[4:5], {n: key[n] for n in (1, 2, 3, 5)}, strict=False)
ok(not v.errors, f"validación sin falsos errores ({v.errors[:1]})")
ok([q["num"] for q in validas] == [1, 2, 3, 5], f"válidas: {[q['num'] for q in validas]}")
ok(sorted(int(q["num"]) for q in omitidas) == [4, 6],
   f"omitidas por no tener respuesta (la 4 y la 6): {sorted(int(q['num']) for q in omitidas)}")
leido = xf.read_xml(xml)
ok(leido[1]["answers"] == [("x | y", 100.0), ("x & y", 0.0), ("a || b", 0.0), ("x ^ y", 0.0)],
   f"XML P1: «x | y» entera y única correcta ({leido[1]['answers']})")
ok(leido[2]["answers"] == [("a || b", 50.0), ("a && b", -50.0), ("a | b", 50.0), ("a + b", -50.0)],
   "XML P2: varias correctas, «a || b» y «a | b» intactas")
ok([a[0] for a in leido[3]["answers"]] == ["C:\\ruta / otra", "C:\\ruta", "/usr/bin"]
   and [a[0] for a in leido[3]["answers"] if a[1] > 0] == ["C:\\ruta / otra", "/usr/bin"], "XML P3: 'C:\\ruta / otra' intacta y marcada")
slots = xf.read_cloze(re.search(r"<questiontext[^>]*>\s*<text>(.*?)</text>", xml.split('name><text>P5')[1], re.S).group(1).replace("<![CDATA[", "").replace("]]>", ""))
ok(slots[0] == ("MULTICHOICE_S", [("10 / 2", True), ("5 / 1", False), ("2", False)]),
   f"XML P5 hueco A: «10 / 2» entera y correcta ({slots[0]})")
ok(slots[1] == ("MULTICHOICE_S", [("C:\\ruta / otra", True), ("C:\\ruta", False)]), f"XML P5 hueco B ({slots[1]})")

# Todos los bancos nuevos de la línea base, de punta a punta, leídos como lo haría Moodle.
for nombre in ("s_sep_opcion_multiple", "s_sep_completar"):
    qs = base.bancos()[nombre]
    qn, kn, va, om, xml_n = convertir(xf.perfect_model(qs))
    ok(len(va) == len(qs) and not om, f"{nombre}: las {len(qs)} preguntas válidas, ninguna omitida")
    rd = xf.read_xml(xml_n)
    if nombre == "s_sep_opcion_multiple":
        bien = all([t for t, f in rd[i + 1]["answers"] if f > 0] == [q["options"][c] for c in q["correct"]]
                   and [t for t, _ in rd[i + 1]["answers"]] == q["options"] for i, q in enumerate(qs))
        ok(bien, f"{nombre}: cada opción y cada correcta del XML son las del examen, sin partir")
    else:
        textos = re.findall(r"<questiontext[^>]*>\s*<text><!\[CDATA\[(.*?)\]\]></text>", xml_n, re.S)
        bien = True
        for q, t in zip(qs, textos):
            got = xf.read_cloze(t.replace("&amp;", "&"))
            esperado = [[(o, i in b["correct"]) for i, o in enumerate(b["options"])] for b in q["blanks"]]
            bien &= [[x for x in s[1]] for s in got] == esperado
        ok(bien, f"{nombre}: cada hueco del XML tiene las opciones y correctas del examen (con ~ }} # / \\ escapados)")

# ── 3. Retrocompatibilidad: datos sin índices ────────────────────────────────
print("Retrocompatibilidad: sin índices se analiza el texto como siempre")
q_viejo = [{"num": 1, "type": "multichoice", "data": {"stem": "Capital de Perú", "options": {"A": "Lima", "B": "Quito", "C": "Bogotá"}}},
           {"num": 2, "type": "multichoice", "data": {"stem": "Elige las pares", "options": {"A": "dos", "B": "tres", "C": "cuatro"}}},
           {"num": 3, "type": "cloze", "data": {"text": "El sol sale por el [A: este / oeste] y se oculta por el [B: oeste / este]."}},
           {"num": 4, "type": "cloze", "data": {"text": "La velocidad se mide en [A: km/h / kg]."}}]
k_viejo = {1: {"type": "multichoice", "answer": "B"}, 2: {"type": "multichoice", "answer": "dos | cuatro"},
           3: {"type": "cloze", "answer": "A. este; B. oeste"}, 4: {"type": "cloze", "answer": "A. km/h"}}
v = validate_questions(copy.deepcopy(q_viejo), copy.deepcopy(k_viejo), strict=True)
ok(not v.errors, f"editor_json antiguo (sin correct_idx ni huecos) valida ({v.errors[:1]})")
xml_v, _ = build_xml(copy.deepcopy(q_viejo), copy.deepcopy(k_viejo))
r = xf.read_xml(xml_v)
ok([t for t, f in r[1]["answers"] if f > 0] == ["Quito"] and [t for t, f in r[2]["answers"] if f > 0] == ["dos", "cuatro"],
   "XML de un historial viejo: respuestas por letra y por texto")
ok(":=este~oeste}" in xml_v and ":=oeste~este}" in xml_v and ":=km\\/h~kg}" in xml_v, "XML de un historial viejo: Completar por texto")

# Un historial viejo reabierto: lo que guardó rutas_xml es JSON con claves de texto.
guardado = json.dumps({"questions": q_viejo, "answer_key": k_viejo}, ensure_ascii=False)
d = json.loads(guardado)
ak = {int(k): v for k, v in d["answer_key"].items()}   # como hace /api/generate_xml
ok(not validate_questions(d["questions"], ak, strict=True).errors and build_xml(d["questions"], ak)[0] == xml_v,
   "un historial viejo reabierto sigue generando el MISMO XML")
# Y uno nuevo (con índices) sobrevive al JSON del historial.
nuevo = json.loads(json.dumps({"questions": questions, "answer_key": key}, ensure_ascii=False))
ak = {int(k): v for k, v in nuevo["answer_key"].items()}
validas_n = [q for q in nuevo["questions"] if q["num"] in (1, 2, 3, 5, 6)]
ok(not validate_questions(validas_n, ak, strict=False).errors and "x | y" in build_xml(validas_n, ak)[0],
   "un historial NUEVO (con índices) reabierto valida y conserva «x | y»")

print("Clave en texto sin índices con separadores: sigue siendo el comportamiento de antes")
q_sep = [{"num": 1, "type": "multichoice", "data": {"stem": "s", "options": {"A": "x | y", "B": "z"}}}]
v = validate_questions(q_sep, {1: {"type": "multichoice", "answer": "x | y"}}, strict=True)
ok(len(v.errors) >= 1, "sin correct_idx, «x | y» sigue partiéndose (el error falso solo desaparece con índices)")
v = validate_questions(q_sep, {1: {"type": "multichoice", "answer": "x | y", "correct_idx": [0]}}, strict=True)
ok(not v.errors, "con correct_idx la misma pregunta valida")
xml_c, _ = build_xml(q_sep, {1: {"type": "multichoice", "answer": "x | y", "correct_idx": [0]}})
ok([t for t, f in xf.read_xml(xml_c)[1]["answers"] if f > 0] == ["x | y"], "y el XML marca «x | y» como correcta")

print("Índices desactualizados: manda el texto")
q_ed = [{"num": 1, "type": "multichoice", "data": {"stem": "s", "options": {"A": "uno", "B": "dos"}}}]
xml_e, _ = build_xml(q_ed, {1: {"type": "multichoice", "answer": "dos", "correct_idx": [0]}})
ok([t for t, f in xf.read_xml(xml_e)[1]["answers"] if f > 0] == ["dos"], "texto «dos» con correct_idx [0] (otro): se respeta el texto")
hs = huecos_de_cloze("Es [A: uno / dos]", "A. dos", [HuecoClave("A", ["uno", "dos"], [0])])
ok(hs[0].resolver() == ([1], []), "cloze: índices que no coinciden con la clave en texto: manda el texto")
hs = huecos_de_cloze("Es [A: uno / dos / tres]", "A. tres", [HuecoClave("A", ["uno", "dos"], [1])])
ok(hs[0].opciones == ["uno", "dos", "tres"] and hs[0].resolver() == ([2], []), "cloze: enunciado editado aparte: se ignora la estructura vieja")
ok(huecos_de_cloze("Es [A: 10 / 2 / 5]", "A. 10 / 2")[0].opciones == ["10", "2", "5"], "sin estructura, «10 / 2» se parte (por eso viaja la lista)")
xml_cz = convert_cloze_to_moodle("Es [A: 10 / 2 / 5]", 1, {1: {"answer": "A. 10 / 2", "huecos": [{"letra": "A", "options": ["10 / 2", "5"], "correct_idx": [0]}]}})
ok(xml_cz == "Es {1:MULTICHOICE_S:=10 \\/ 2~5}", f"convert_cloze_to_moodle usa la estructura ({xml_cz})")

# ── 4. mark_resolver: la respuesta por marcas también escribe los índices ─────
print("mark_resolver escribe correct_idx")


def _mcq(n, opciones):
    return {"num": n, "type": "multichoice", "data": {"stem": f"Enunciado número {n} de la prueba de marcas", "options": dict(zip("ABCD", opciones))}}


opciones_m = ["a || b", "x | y", "x & y", "x ^ y"]
qs_m = [_mcq(n, opciones_m) for n in (1, 2, 3)]
clave_m = {n: {"type": "multichoice", "answer": "a || b"} for n in (1, 2, 3)}
lineas = []
for n in (1, 2, 3):
    lineas.append(f"{n}. Enunciado número {n} de la prueba de marcas")
    for L, t in zip("ABCD", opciones_m):
        lineas.append(f"⟦negrita⟧{L}. {t}⟦/negrita⟧" if t == "x | y" else f"{L}. {t}")
res = mark_resolver.resolve_answer_marks(qs_m, clave_m, ["\n".join(lineas)])
ok(res["applied"] == 3 and all(clave_m[n]["answer"] == "x | y" and clave_m[n]["correct_idx"] == [1] for n in (1, 2, 3)),
   "la opción «x | y» marcada en negrita queda como respuesta Y como correct_idx [1]")
ok(not validate_questions(qs_m, clave_m, strict=True).errors, "y la pregunta valida sin falso error")
xml_m, _ = build_xml(qs_m, clave_m)
ok([t for t, f in xf.read_xml(xml_m)[1]["answers"] if f > 0] == ["x | y"], "el XML marca «x | y»")
clave_doc = {n: {"type": "multichoice", "answer": "a || b", "from_key": True} for n in (1, 2, 3)}
mark_resolver.resolve_answer_marks(qs_m, clave_doc, ["\n".join(lineas)])
ok(all("correct_idx" not in clave_doc[n] for n in clave_doc), "la clave explícita del documento no se toca (ni su correct_idx)")

print()
print("TODO OK" if not fallas else f"{fallas} FALLA(S)")
sys.exit(1 if fallas else 0)
