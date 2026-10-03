"""
test_modelo.py — Modelo tipado de pregunta (backend/modelo.py).

    backend/venv/bin/python dev/test_modelo.py

Sin red, sin Gemini, sin tocar el historial ni la clave. Comprueba:
  * ida y vuelta EXACTA dict → modelo → dict (mismo contenido y mismo orden de
    claves) con todo lo que produce adapt() para los exámenes de dev/synthetic,
    con cada uno de los 7 tipos, con campos desconocidos y con valores de tipo
    inesperado (nada se pierde ni se corrige: va a `extra`);
  * los campos reservados (origen_respuesta, confianza, pagina, recuadro) no
    se serializan mientras son None;
  * las vistas tipadas y las reglas que comparten validator y xml_builder;
  * que las funciones públicas (adapt, validate/partition, build_xml) siguen
    recibiendo y devolviendo los dicts de siempre, sin mutar la entrada.
"""

import copy
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "dev"))
sys.path.insert(0, str(ROOT / "dev" / "synthetic"))

import xml_fidelity as xf  # noqa: E402  (apaga el logging; NO se llama a xf.run)
import exams  # noqa: E402
from modelo import (  # noqa: E402
    Clave, Imagen, Pregunta, PreguntaCloze, PreguntaEssay, PreguntaMatching, PreguntaMultichoice,
    PreguntaNumerical, PreguntaShortanswer, PreguntaTruefalse, huecos_de_cloze,
    preguntas_a_dicts, preguntas_desde_dicts,
)
from schema_adapter import adapt  # noqa: E402
from validator import partition_questions, validate_questions  # noqa: E402
from xml_builder import build_xml  # noqa: E402
from answer_matching import RespuestaNoResuelta  # noqa: E402

fallas = 0


def ok(cond, msg):
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


def ida_y_vuelta(d):
    """El dict vuelve igual: mismo contenido y mismo orden de claves (también anidado)."""
    return json.dumps(Pregunta.desde_dict(d).a_dict()) == json.dumps(d)


def ida_y_vuelta_clave(d):
    return json.dumps(Clave.desde_dict(d).a_dict()) == json.dumps(d)


# ── 1. Todo lo que produce adapt() con los exámenes sintéticos ───────────────
print("Ida y vuelta con los exámenes de dev/synthetic")
bancos = dict(xf.load_exams())
for nombre in ("BASE_MIXED", "COLOR_MC", "AFIRMACIONES", "ASTERISCO", "CLOZE", "RESALTADO_MC", "NEGRITA_MC", "SUBRAYADO_MC"):
    if hasattr(exams, nombre):
        bancos["s_" + nombre.lower()] = getattr(exams, nombre)
bancos["s_largo_60"] = exams.long_exam(60)

total_q = total_k = 0
malas = []
tipos_vistos = set()
for nombre, qs in bancos.items():
    base = xf.perfect_model(qs)
    for variante in range(4):
        payload = copy.deepcopy(base)
        for i, q in enumerate(payload["preguntas"]):
            if variante == 1 and i % 3 == 0:
                q["confianza"] = "baja"                     # low_confidence / marcador de transcripción
            if variante == 2:
                q["comparte_imagen_anterior"] = (i % 2 == 0)
                q["retroalimentacion"] = f"porque sí {i}\nsegunda línea"
            if variante == 3:
                q["pagina"] = i + 1
                if i % 7 == 0:
                    q["tipo"] = "zzz"                        # entrada con "error"
        questions, key = adapt(payload)
        for q in questions:
            total_q += 1
            tipos_vistos.add(q["type"])
            if not ida_y_vuelta(q):
                malas.append((nombre, variante, q.get("num")))
        for k, entry in key.items():
            total_k += 1
            if not ida_y_vuelta_clave(entry):
                malas.append((nombre, variante, "clave", k))
ok(total_q > 500 and not malas, f"{total_q} preguntas y {total_k} claves de adapt(): ida y vuelta exacta {malas[:3]}")
ok({"multichoice", "truefalse", "matching", "cloze", "essay", "shortanswer", "numerical"} <= tipos_vistos,
   "los 7 tipos están entre ellas")

# ── 2. Cada tipo, con su clase y sus campos ─────────────────────────────────
print("Los 7 tipos")
img = {"name": "pregunta1-1.png", "mime": "image/png", "b64": "QUJD"}
casos = {
    "multichoice": ({"stem": "¿?", "options": {"A": "x", "B": "y"}, "feedback": "f", "images": [img], "page": 3,
                     "low_confidence": True, "answer_from_marks": True, "color_review_hint": True,
                     "_comparte_imagen": False}, PreguntaMultichoice),
    "truefalse": ({"stem": "afirmación"}, PreguntaTruefalse),
    "matching": ({"stem": "", "col_a": {"1": "a"}, "col_b": {"a": "b"}, "from_table": True}, PreguntaMatching),
    "cloze": ({"text": "La [A: x / y] es"}, PreguntaCloze),
    "essay": ({"stem": "explica"}, PreguntaEssay),
    "shortanswer": ({"stem": "¿capital?"}, PreguntaShortanswer),
    "numerical": ({"stem": "2+2"}, PreguntaNumerical),
}
for tipo, (data, clase) in casos.items():
    d = {"num": 1, "type": tipo, "data": data, "points": 2.5}
    p = Pregunta.desde_dict(d)
    ok(type(p) is clase and p.tipo == tipo and p.num == 1 and p.points == 2.5 and ida_y_vuelta(d),
       f"{tipo}: clase {clase.__name__} e ida y vuelta")
    ok(p.extra == {} and p.extra_data == {}, f"{tipo}: nada cayó en extra")
d = {"num": 1, "type": "multichoice", "data": casos["multichoice"][0]}
p = Pregunta.desde_dict(d)
ok(p.stem == "¿?" and p.options == {"A": "x", "B": "y"} and p.feedback == "f" and p.pagina == 3
   and p.low_confidence and p.answer_from_marks and p.color_review_hint and p.comparte_imagen is False
   and isinstance(p.images[0], Imagen) and p.images[0].b64 == "QUJD",
   "multichoice: todos los campos de data son atributos tipados")
ok(type(Pregunta.desde_dict({"num": 1, "type": "description", "data": {"stem": "x"}})) is Pregunta,
   "un tipo sin clase propia (description) usa la base")

# ── 3. Campos desconocidos y valores de tipo inesperado: nada se pierde ──────
print("Campos desconocidos y datos raros")
raros = [
    {"num": 1, "type": "truefalse", "data": {"stem": "s", "campo_nuevo": [1, {"a": 2}]}, "otra_cosa": {"x": 1}},
    {"num": 1, "type": "truefalse", "data": {"stem": "s"}, "points": "3"},
    {"num": 1, "type": "truefalse", "data": {"stem": "s"}, "points": True},
    {"num": 1, "type": "truefalse", "data": {"stem": "s"}, "points": float("inf")},
    {"num": 1, "type": "truefalse", "data": {"stem": "s"}, "points": -1},
    {"num": 1, "type": "truefalse", "data": {"stem": 5}},
    {"num": 1, "type": "truefalse", "data": {"stem": None, "feedback": None}},
    {"num": 1, "type": "multichoice", "data": {"stem": "s", "options": ["a", "b"]}},
    {"num": 1, "type": "truefalse", "data": {"stem": "s", "options": {"A": "x"}, "col_a": {"1": "a"}, "from_table": True}},
    {"num": 1, "type": "multichoice", "data": {"stem": "s", "col_a": {"1": "a"}}},
    {"num": 1, "type": "truefalse", "data": {"stem": "s", "page": "2"}},
    {"num": 1, "type": "truefalse", "data": {"stem": "s", "page": True}},
    {"num": 1, "type": "truefalse", "data": {"stem": "s", "images": [1, "x"]}},
    {"num": 1, "type": "truefalse", "data": {"stem": "s", "images": [{"name": "a.png", "extra_img": 1}, {}]}},
    {"num": 1, "type": "truefalse", "data": {"stem": "s", "images": []}},
    {"num": 1, "type": "truefalse", "data": "no soy un dict"},
    {"num": 1, "type": "truefalse", "data": None},
    {"num": 1, "type": "truefalse", "data": []},
    {"num": 1, "type": "truefalse"},
    {"num": 1, "type": "truefalse", "data": {}},
    {"num": "1", "type": "truefalse", "data": {"stem": "s"}},
    {"num": True, "type": 5, "data": {"stem": "s"}},
    {"num": 1, "type": "zzz", "data": {"stem": "s"}, "error": "no se reconoce"},
    {"num": 2, "type": "?", "raw_text": "texto crudo", "error": "falló"},
    {"num": 2, "type": "?", "error": None},
    {"data": {"stem": "sin número"}},
    {},
    {"data": {"stem": "s", "origen_respuesta": "adivinado", "confianza": "altísima", "recuadro": [1, 2, 3]}},
    {"data": {"stem": "s", "recuadro": [1, 2, 3, "x"], "origen_respuesta": None, "confianza": 3}},
    {"type": "cloze", "data": {"text": "[A: x / y]", "stem": "también stem"}},
    {"data": {"z": 1, "stem": "s", "a": 2, "feedback": "f", "page": 1}},        # orden de claves propio
]
for d in raros:
    ok(ida_y_vuelta(d), f"ida y vuelta exacta: {json.dumps(d, default=str)[:90]}")
p = Pregunta.desde_dict({"num": 1, "type": "truefalse", "data": {"stem": "s", "campo_nuevo": 7}, "otra": 1})
ok(p.extra == {"otra": 1} and p.extra_data == {"campo_nuevo": 7}, "los desconocidos quedan en extra (pregunta) y extra_data (data)")
orig = {"num": 1, "type": "truefalse", "data": {"stem": "s", "x": [1, 2]}}
copia = copy.deepcopy(orig)
p = Pregunta.desde_dict(orig)
p.extra_data["x"].append(99)
p.a_dict()["data"]["x"].append(77)
ok(orig == copia, "desde_dict/a_dict copian: modificar el modelo o su dict no toca el original")
try:
    Pregunta.desde_dict("no es dict")
    ok(False, "desde_dict rechaza lo que no es un dict")
except TypeError:
    ok(True, "desde_dict rechaza lo que no es un dict")

# Fuzz con semilla fija: cualquier mezcla de claves y valores vuelve igual.
rnd = random.Random(2026)
valores = [None, True, False, 0, 3, -2, 2.5, "", "txt", "Verdadero", [], [1, 2], ["a"], {}, {"A": "x"}, {"1": "a"},
           {"name": "i.png", "mime": "image/png", "b64": "QQ=="}, [{"name": "i.png"}], [1, 2, 3, 4], "alta", "ia"]
claves_top = ["num", "type", "data", "error", "points", "raw_text", "otro"]
claves_data = ["stem", "text", "options", "col_a", "col_b", "from_table", "feedback", "images", "page", "low_confidence",
               "answer_from_marks", "color_review_hint", "_comparte_imagen", "origen_respuesta", "confianza",
               "recuadro", "x"]
tipos = ["multichoice", "truefalse", "matching", "cloze", "essay", "shortanswer", "numerical", "description", "?", 7]
malos = 0
for _ in range(3000):
    d = {}
    for k in rnd.sample(claves_top, rnd.randint(0, len(claves_top))):
        d[k] = rnd.choice(tipos) if k == "type" else (rnd.randint(1, 9) if k == "num" and rnd.random() < .8 else rnd.choice(valores))
    if rnd.random() < .85:
        d["data"] = {k: rnd.choice(valores) for k in rnd.sample(claves_data, rnd.randint(0, len(claves_data)))}
    malos += 0 if ida_y_vuelta(d) else 1
    e = {k: rnd.choice(valores) for k in rnd.sample(["type", "answer", "pairs", "from_key", "otro"], rnd.randint(0, 5))}
    malos += 0 if ida_y_vuelta_clave(e) else 1
ok(malos == 0, f"3000 preguntas y 3000 claves al azar: ida y vuelta exacta ({malos} fallas)")

# ── 4. Campos reservados ────────────────────────────────────────────────────
print("Campos reservados")
p = Pregunta.desde_dict({"num": 1, "type": "truefalse", "data": {"stem": "s"}})
ok(p.origen_respuesta is None and p.confianza is None and p.pagina is None and p.recuadro is None,
   "por defecto son None")
ok(p.a_dict() == {"num": 1, "type": "truefalse", "data": {"stem": "s"}}, "None no se serializa: el dict no cambia")
p.origen_respuesta, p.confianza, p.pagina, p.recuadro = "marca", "media", 4, (10, 20.5, 30, 40)
d = p.a_dict()
ok(d["data"] == {"stem": "s", "origen_respuesta": "marca", "confianza": "media", "page": 4, "recuadro": [10, 20.5, 30, 40]},
   "con valor, viajan en data (pagina como data['page'], recuadro como lista)")
p2 = Pregunta.desde_dict(json.loads(json.dumps(d)))
ok(p2.origen_respuesta == "marca" and p2.confianza == "media" and p2.pagina == 4 and p2.recuadro == (10, 20.5, 30, 40)
   and ida_y_vuelta(d), "al volver del JSON se leen como atributos y la ida y vuelta es exacta")
p2.origen_respuesta = None
ok("origen_respuesta" not in p2.a_dict()["data"], "volver a ponerlo en None lo quita del dict")
p3 = Pregunta.desde_dict({"data": {"origen_respuesta": "adivinado", "confianza": "altísima", "recuadro": [1, 2, 3], "page": "2"}})
ok(p3.origen_respuesta is None and p3.confianza is None and p3.recuadro is None and p3.pagina is None
   and set(p3.extra_data) == {"origen_respuesta", "confianza", "recuadro", "page"},
   "un valor reservado inválido no se interpreta ni se pierde: queda en extra_data")
qs, _ = adapt({"preguntas": [{"orden": 1, "tipo": "truefalse", "enunciado": "e", "respuesta_texto": "Verdadero",
                              "respuesta_marcada": True, "pagina": 6, "confianza": "alta"}]})
ok(qs[0]["data"] == {"stem": "e", "page": 6}, "adapt: pagina sigue en data['page'] y 'alta' no genera campos nuevos")

# ── 5. Clave y unión pregunta + respuesta ───────────────────────────────────
print("Clave y unión")
c = Clave.desde_dict({"type": "matching", "answer": "1-a; 2-b", "pairs": {"1": "a", "2": "b"}, "from_key": True, "x": 1})
ok(c.tipo == "matching" and c.answer == "1-a; 2-b" and c.pairs == {"1": "a", "2": "b"} and c.from_key and c.extra == {"x": 1},
   "Clave: campos tipados y extra")
ok(not Clave.desde_dict({}) and Clave.desde_dict({"answer": ""}) and Clave.desde_dict({"z": 0}),
   "una clave vacía ({}) cuenta como no tener clave; con cualquier dato, no")
ok(Clave.desde_dict({"answer": 5}).texto == "" and Clave.desde_dict({"answer": 5}).a_dict() == {"answer": 5},
   "un answer que no es texto no se interpreta pero se conserva")
qs = [{"num": 1, "type": "truefalse", "data": {"stem": "s"}}, {"num": 2, "type": "essay", "data": {"stem": "e"}}]
ak = {1: {"type": "truefalse", "answer": "Falso"}, 2: "basura", 3: {"answer": "x"}}
ps = preguntas_desde_dicts(qs, ak)
ok(ps[0].respuesta_texto == "Falso" and ps[1].respuesta is None and ps[1].respuesta_texto == "",
   "preguntas_desde_dicts adjunta la clave de cada número (una entrada que no es dict, ausente)")
q2, k2 = preguntas_a_dicts(ps)
ok(q2 == qs and k2 == {1: {"type": "truefalse", "answer": "Falso"}}, "preguntas_a_dicts devuelve (questions, answer_key)")

# ── 6. Vistas tipadas y reglas compartidas ──────────────────────────────────
print("Vistas tipadas y reglas compartidas")
mc = Pregunta.desde_dict({"num": 1, "type": "multichoice", "data": {"stem": "s", "options": {"A": "Java", "B": "Python 2", "C": "Python 3"}}})
mc.respuesta = Clave(answer="B | c")
letras, fallos = mc.resolver_correctas()
ok(letras == ["B", "C"] and fallos == [], "multichoice: «B | c» → letras B y C (resolver_opcion)")
mc.respuesta = Clave(answer="Python")
ok(mc.resolver_correctas() == ([], [("Python", "ambigua")]), "multichoice: «Python» es ambigua, no se adivina")
mc.respuesta = Clave(answer="Ruby")
ok(mc.resolver_correctas() == ([], [("Ruby", "ninguna")]), "multichoice: una respuesta que no está → «ninguna»")
mc.respuesta = Clave(answer="A")
ok([(o.letra, o.correcta) for o in mc.lista_opciones()] == [("A", True), ("B", False), ("C", False)],
   "multichoice: lista_opciones marca la correcta")

tf = Pregunta.desde_dict({"num": 1, "type": "truefalse", "data": {"stem": "s"}})
res = {}
for texto in ("Verdadero", " v ", "TRUE", "Falso", "f", "quizá", ""):
    tf.respuesta = Clave(answer=texto)
    res[texto] = tf.es_verdadero()
ok(res == {"Verdadero": True, " v ": True, "TRUE": True, "Falso": False, "f": False, "quizá": None, "": None},
   "truefalse: los alias de answer_matching.TRUEFALSE_ALIAS (única fuente)")

nu = Pregunta.desde_dict({"num": 1, "type": "numerical", "data": {"stem": "s"}})
nu.respuesta = Clave(answer="3,5")
ok(nu.valor_numerico() == "3.5", "numerical: «3,5» → «3.5»")
nu.respuesta = Clave(answer="tres")
ok(nu.valor_numerico() is None, "numerical: «tres» no es número")

ma = Pregunta.desde_dict({"num": 1, "type": "matching", "data": {"stem": "", "col_a": {"1": "uno", "2": "dos"}, "col_b": {"a": "A", "b": "B"}}})
ma.respuesta = Clave(answer="1-B; 2-a", pairs={"1": "B", "2": "a"})
ok(ma.letra_de(1) == "b" and ma.letra_de("2") == "a" and ma.letra_de(3) is None, "matching: letra_de ignora mayúsculas")
ok([(x.num, x.izquierda, x.letra, x.derecha) for x in ma.lista_parejas()] == [("1", "uno", "b", "B"), ("2", "dos", "a", "A")],
   "matching: lista_parejas")

cl = Pregunta.desde_dict({"num": 1, "type": "cloze", "data": {"text": "La [A: x / y] y [B: arr[0] / km/h]"}})
cl.respuesta = Clave(answer="A. y; B. arr[0] | km/h")
hs = cl.huecos()
ok([h.letra for h in hs] == ["A", "B"] and hs[1].opciones == ["arr[0]", "km/h"] and hs[0].respuestas == ["y"],
   "cloze: huecos con corchetes anidados y opciones")
ok(hs[0].resolver() == ([1], []) and hs[1].resolver() == ([0, 1], []), "cloze: Hueco.resolver devuelve los índices correctos")
cl.respuesta = Clave(answer="A. z")
ok(cl.huecos()[0].resolver() == ([], [("z", "ninguna")]) and cl.huecos()[1].respuestas == [], "cloze: respuesta que no está / hueco sin clave")
ok(huecos_de_cloze("Una [A: sí / no] sola", "sí")[0].respuestas == ["sí"], "cloze: formato legado de un solo hueco sin letra")

pt = lambda v: Pregunta.desde_dict({"num": 1, "type": "essay", "data": {"stem": "e"}, **({} if v is None else {"points": v})}).puntos_validos  # noqa: E731
ok([pt(None), pt(0), pt(2.5), pt(-1), pt(float("inf")), pt(float("nan")), pt(True), pt("3")] == [None, 0, 2.5, None, None, None, None, None],
   "puntos_validos: solo números finitos y ≥ 0 (como _nota_de)")

# ── 7. Las funciones públicas siguen hablando en dicts ──────────────────────
print("Contratos públicos")
payload = xf.perfect_model(exams.BASE_MIXED)
questions, key = adapt(payload)
ok(all(type(q) is dict and type(q["data"]) is dict for q in questions) and all(type(v) is dict for v in key.values()),
   "adapt devuelve dicts")
antes = copy.deepcopy((questions, key))
validas, omitidas = partition_questions(questions, key)
ok(all(any(v is q for q in questions) for v in validas), "partition_questions devuelve los MISMOS dicts de entrada")
ok((questions, key) == antes, "partition_questions no modifica lo que recibe")
xml, stats = build_xml(validas, key)
ok((questions, key) == antes and stats.total == len(validas), "build_xml no modifica lo que recibe")
ok(validate_questions(validas, key, strict=True).is_valid, "validate_questions acepta lo que adapt produjo")

# Entrada rara del navegador: errores de validación, no excepciones.
raros_val = [
    ({"num": 1, "type": "multichoice", "data": {"stem": "s", "options": ["a", "b"]}}, {1: {"type": "multichoice", "answer": "a"}}),
    ({"num": 1, "type": "truefalse", "data": {"stem": 5}}, {1: {"type": "truefalse", "answer": "Verdadero"}}),
    ({"num": 1, "type": "matching", "data": {"stem": "", "col_a": {"1": "a", "2": "b"}, "col_b": {"a": "x", "b": "y"}}},
     {1: {"type": "matching", "answer": "1-a; 2-b", "pairs": ["no", "dict"]}}),
    ({"num": 1, "type": "numerical", "data": {"stem": "s"}}, {1: {"type": "numerical", "answer": 7}}),
    ({"num": 1, "type": "truefalse", "data": {"stem": "s"}}, {1: "no soy dict"}),
]
for q, ak in raros_val:
    try:
        r = validate_questions([q], ak, strict=True)
        ok(not r.is_valid, f"validate_questions con datos raros da errores, no excepción: {r.errors[0][:70]}")
    except Exception as e:  # noqa: BLE001
        ok(False, f"validate_questions con datos raros lanzó {type(e).__name__}: {e}")

# build_xml no inventa nada: sin enunciado o sin respuesta resoluble, falla como antes.
try:
    build_xml([{"num": 1, "type": "truefalse", "data": {}}], {1: {"type": "truefalse", "answer": "Verdadero"}})
    ok(False, "build_xml sin 'stem' falla")
except KeyError:
    ok(True, "build_xml sin 'stem' lanza KeyError (nunca escribe «None» en el XML)")
try:
    build_xml([{"num": 1, "type": "multichoice", "data": {"stem": "s", "options": {"A": "a", "B": "b"}}}],
              {1: {"type": "multichoice", "answer": "zzz"}})
    ok(False, "build_xml con respuesta que no está falla")
except RespuestaNoResuelta:
    ok(True, "build_xml con una respuesta que no identifica una opción lanza RespuestaNoResuelta")

print()
print("TODO OK" if not fallas else f"{fallas} FALLA(S)")
sys.exit(1 if fallas else 0)
