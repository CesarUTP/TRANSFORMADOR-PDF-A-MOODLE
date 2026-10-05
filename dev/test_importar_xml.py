"""
test_importar_xml.py — Versión 2.0: importar un Moodle XML existente al editor.

    PYTHONUTF8=1 backend/venv/bin/python dev/test_importar_xml.py

Sin red ni Gemini. La prueba principal es el VIAJE DE IDA Y VUELTA: cada uno de los 25
exámenes sintéticos (y el XML de conformidad con Moodle) se genera con xml_builder, se
importa con importar_xml y debe volver con las mismas preguntas, opciones, respuestas,
parejas y huecos. Además: un XML hecho como los que exporta Moodle, los tipos que no se
pueden editar (van a «no incluidas» con su motivo), imágenes, y la seguridad (XML
dañado, entidades externas, «billion laughs», el tamaño).
"""

import base64
import io
import logging
import os
import re
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "dev"))
sys.path.insert(0, str(ROOT / "dev" / "synthetic"))

TMP = Path(tempfile.mkdtemp(prefix="conv importar "))
os.environ["HOME"] = str(TMP / "home")
os.environ["LOCALAPPDATA"] = str(TMP / "home" / "AppData")
(TMP / "datos" / "data").mkdir(parents=True)
import database  # noqa: E402

database.get_db_path = lambda: TMP / "datos" / "data" / "exams_history.db"  # ANTES de importar main

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import xml_fidelity as xf  # noqa: E402  (apaga el logging)
import test_xml_baseline as base  # noqa: E402
import importar_xml as ix  # noqa: E402
import main  # noqa: E402
import seguridad  # noqa: E402
from modelo import Clave, Pregunta, huecos_de_cloze  # noqa: E402
from schema_adapter import adapt  # noqa: E402
from validator import partition_questions  # noqa: E402
from xml_builder import build_xml  # noqa: E402

logging.disable(logging.CRITICAL)
fallas = 0


def ok(cond, msg):
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


def lineas(t):
    return re.sub(r"\n{3,}", "\n\n", "\n".join(ln.rstrip() for ln in str(t or "").strip().split("\n")))


def canon(q, clave):
    """La pregunta como la entiende el docente: sin depender de letras, orden de claves ni formato interno."""
    d = q["data"]
    tipo = q["type"]
    if tipo == "multichoice":
        p = Pregunta.desde_dict(q)
        p.respuesta = Clave.desde_dict(clave)
        letras, fallos = p.resolver_correctas()
        opciones = [d["options"][k] for k in sorted(d["options"])]
        return (tipo, lineas(d["stem"]), opciones, sorted(d["options"][L] for L in letras))
    if tipo == "truefalse":
        return (tipo, lineas(d["stem"]), clave["answer"].strip().lower())
    if tipo == "matching":
        pares = {d["col_a"][n]: d["col_b"][L] for n, L in (clave.get("pairs") or {}).items()}
        return (tipo, lineas(d["stem"]), sorted(pares.items()))
    if tipo == "cloze":
        hs = huecos_de_cloze(d["text"], clave.get("answer", ""), Clave.desde_dict(clave).huecos)
        return (tipo, lineas(re.sub(r"\[[A-Za-z]:[^\]]*\]", "[·]", d["text"])),
                [(h.opciones, sorted(h.opciones[i] for i in h.resolver()[0])) for h in hs])
    if tipo == "numerical":
        # Moodle pide punto decimal: xml_builder escribe «9,75» como «9.75» (a propósito).
        return (tipo, lineas(d["stem"]), clave["answer"].strip().replace(",", "."))
    if tipo == "shortanswer":
        return (tipo, lineas(d["stem"]), clave["answer"].strip())
    return (tipo, lineas(d["stem"]))


def viaje(validas, key, categoria="Prueba"):
    xml, _ = build_xml(validas, key, category=categoria)
    return xml, ix.importar_xml(xml.encode("utf-8"), "x.xml")


# ══════════════════════════════════════════════════════════════════════════
print("1. Ida y vuelta: build_xml → importar_xml (los 25 exámenes sintéticos)")
# ══════════════════════════════════════════════════════════════════════════
total = 0
for nombre, qs in base.bancos().items():
    questions, key = adapt(xf.perfect_model(qs))
    validas, _ = partition_questions(questions, key)
    if not validas:
        continue
    xml, imp = viaje(validas, key)
    a = [canon(q, key[q["num"]]) for q in validas]
    b = [canon(q, imp["answer_key"][q["num"]]) for q in imp["questions"]]
    iguales = a == b and not imp["skipped_questions"]
    if not iguales:
        malas = [(i + 1, x, y) for i, (x, y) in enumerate(zip(a, b)) if x != y][:1]
        ok(False, f"{nombre}: {len(a)}→{len(b)} preguntas, omitidas {len(imp['skipped_questions'])}, primera diferencia {malas}")
    else:
        ok(True, f"{nombre}: {len(a)} preguntas vuelven idénticas")
    total += len(a)
ok(total > 300, f"en total {total} preguntas hicieron el viaje")

conf = (ROOT / "dev" / "conformidad_moodle" / "conformidad_moodle.xml").read_bytes()
imp = ix.importar_xml(conf, "conformidad.xml")
ok(len(imp["questions"]) == 10 and not imp["skipped_questions"], "el XML de conformidad con Moodle (10 preguntas, con los caracteres difíciles) se importa entero")
cl = next(q for q in imp["questions"] if q["type"] == "cloze")
ok(imp["answer_key"][cl["num"]]["huecos"][1]["options"] == ['dijo "hola"', "{llave}", "a~b", "c#d", "e}f", "g\\h", "R&D", "x < y"],
   "«Completar» con / \" { } ~ # \\ & < vuelve exacto")
ok(next(q for q in imp["questions"] if q["data"].get("images"))["data"]["images"][0]["mime"] == "image/png", "la imagen en base64 vuelve como PNG")
ok(imp["categoria"] == "PRUEBA-conformidad (borrar)", "la categoría se lee de «$course$/…»")
_g = [float(x) for x in re.findall(r"<defaultgrade>([\d.]+)</defaultgrade>", conf.decode())]
ok(abs(imp["puntos_total"] - sum(_g)) < 1e-6 and [q["points"] for q in imp["questions"]] == _g, f"los puntos (defaultgrade) se conservan ({imp['puntos_total']})")
ok(all(q["data"].get("origen_respuesta") == "documento" and q["data"].get("confianza") == "alta"
       for q in imp["questions"] if q["type"] != "essay"), "toda respuesta importada es «documento / alta» (ninguna IA la interpretó)")
ok(imp["importado"] is True and imp["escaneado"] is False and imp["was_reformatted"] is False, "marcas de la importación")

# ══════════════════════════════════════════════════════════════════════════
print("2. Un XML como los que exporta Moodle")
# ══════════════════════════════════════════════════════════════════════════
MOODLE = """<?xml version="1.0" encoding="UTF-8"?>
<quiz>
<question type="category"><category><text>$course$/top/Biología/Células</text></category></question>
<question type="multichoice">
  <name><text>Pregunta de célula</text></name>
  <questiontext format="html"><text><![CDATA[<p>¿Qué organelo produce energía?<br></p><p>Piensa&nbsp;bien.</p>]]></text></questiontext>
  <generalfeedback format="html"><text><![CDATA[<p>Es la <b>mitocondria</b>.</p>]]></text></generalfeedback>
  <defaultgrade>3.0000000</defaultgrade><penalty>0.3333333</penalty><hidden>0</hidden>
  <single>false</single><shuffleanswers>true</shuffleanswers><answernumbering>abc</answernumbering>
  <answer fraction="50" format="html"><text><![CDATA[<p>Mitocondria</p>]]></text><feedback format="html"><text></text></feedback></answer>
  <answer fraction="50" format="html"><text><![CDATA[<p>Cloroplasto</p>]]></text><feedback format="html"><text></text></feedback></answer>
  <answer fraction="-33.33333" format="html"><text><![CDATA[<p>Núcleo</p>]]></text><feedback format="html"><text></text></feedback></answer>
  <answer fraction="-33.33333" format="html"><text><![CDATA[<p>Ribosoma</p>]]></text><feedback format="html"><text></text></feedback></answer>
</question>
<question type="truefalse"><name><text>TF</text></name>
  <questiontext format="html"><text><![CDATA[<p>La célula es la unidad básica.</p>]]></text></questiontext>
  <defaultgrade>1.0</defaultgrade>
  <answer fraction="100" format="moodle_auto_format"><text>true</text></answer>
  <answer fraction="0" format="moodle_auto_format"><text>false</text></answer>
</question>
<question type="matching"><name><text>M</text></name>
  <questiontext format="html"><text><![CDATA[<p>Relaciona.</p>]]></text></questiontext><defaultgrade>2.0</defaultgrade>
  <subquestion format="html"><text><![CDATA[<p>ADN</p>]]></text><answer><text>Núcleo</text></answer></subquestion>
  <subquestion format="html"><text><![CDATA[<p>ATP</p>]]></text><answer><text>Mitocondria</text></answer></subquestion>
  <subquestion format="html"><text></text><answer><text>Pared celular</text></answer></subquestion>
</question>
<question type="shortanswer"><name><text>SA</text></name>
  <questiontext format="html"><text><![CDATA[<p>Organelo de la fotosíntesis</p>]]></text></questiontext>
  <answer fraction="100" format="plain_text"><text>cloroplasto</text></answer>
  <answer fraction="100" format="plain_text"><text>Cloroplasto</text></answer>
  <answer fraction="0" format="plain_text"><text>*</text></answer>
</question>
<question type="numerical"><name><text>N</text></name>
  <questiontext format="html"><text><![CDATA[<p>Pares de cromosomas humanos</p>]]></text></questiontext>
  <answer fraction="100" format="plain_text"><text>23</text><tolerance>0</tolerance></answer>
</question>
<question type="essay"><name><text>E</text></name>
  <questiontext format="html"><text><![CDATA[<p>Describe la mitosis.</p>]]></text></questiontext><responseformat>editor</responseformat>
</question>
<question type="cloze"><name><text>C</text></name>
  <questiontext format="html"><text><![CDATA[<p>La {1:MULTICHOICE:=mitocondria#bien~ribosoma#no~%100%núcleo} produce {2:MULTIRESPONSE:=ATP~=energía~agua} y el {1:SHORTANSWER:=ADN}.</p>]]></text></questiontext>
</question>
<question type="cloze"><name><text>C2</text></name>
  <questiontext format="html"><text><![CDATA[<p>La {1:MC:=mitocondria~ribosoma} es del {1:MCV:=núcleo~=citoplasma}.</p>]]></text></questiontext>
</question>
<question type="calculated"><name><text>Calc</text></name>
  <questiontext format="html"><text><![CDATA[<p>{a} + {b}</p>]]></text></questiontext>
</question>
<question type="description"><name><text>D</text></name>
  <questiontext format="html"><text><![CDATA[<p>Lee el texto.</p>]]></text></questiontext>
</question>
<question type="multichoice"><name><text>SinClave</text></name>
  <questiontext format="html"><text><![CDATA[<p>¿Sin respuesta marcada?</p>]]></text></questiontext>
  <answer fraction="0" format="html"><text>Uno</text></answer><answer fraction="0" format="html"><text>Dos</text></answer>
</question>
</quiz>"""
m = ix.importar_xml(MOODLE.encode("utf-8"), "banco.xml")
por_tipo = [(q["num"], q["type"]) for q in m["questions"]]
ok(por_tipo == [(1, "multichoice"), (2, "truefalse"), (3, "matching"), (4, "shortanswer"), (5, "numerical"), (6, "essay"), (7, "cloze")],
   f"se importan los 7 tipos que se editan, en orden ({por_tipo})")
ok(m["categoria"] == "Células", f"la subcategoría ({m['categoria']})")
q1 = m["questions"][0]
ok(q1["data"]["stem"] == "¿Qué organelo produce energía?\n\nPiensa bien." and q1["points"] == 3.0, f"HTML → texto: párrafos, <br>, &nbsp; ({q1['data']['stem']!r})")
ok(q1["data"]["options"] == {"A": "Mitocondria", "B": "Cloroplasto", "C": "Núcleo", "D": "Ribosoma"}, "las opciones pierden su <p>")
ok(m["answer_key"][1]["answer"] == "Mitocondria | Cloroplasto", "varias correctas por fracción positiva (50 + 50)")
ok(q1["data"]["feedback"] == "Es la mitocondria.", "la retroalimentación general")
ok(m["answer_key"][2]["answer"] == "Verdadero", "verdadero/falso")
c = m["answer_key"][3]
ok(c["pairs"] == {"1": "a", "2": "b"} and m["questions"][2]["data"]["col_b"] == {"a": "Núcleo", "b": "Mitocondria", "c": "Pared celular"},
   "emparejamiento: el elemento sin pregunta (distractor) queda en la columna B sin pareja")
ok(m["answer_key"][4]["answer"] == "cloroplasto", "respuesta corta: la primera correcta")
ok(m["answer_key"][5]["answer"] == "23", "numérica")
ok(m["questions"][6]["data"]["text"].startswith("La [A: "), "completar: el hueco vuelve como [A: opciones]")
ok(len(m["skipped_questions"]) >= 3, f"no incluidas: {[ (s['type'], s['reasons'][0][:50]) for s in m['skipped_questions']]}")
tipos_omitidos = {s["type"] for s in m["skipped_questions"]}
ok({"calculated", "description"} <= tipos_omitidos, "las calculadas y las descripciones van a «no incluidas» con su motivo")
ok(any("respuesta corta o numérica" in r for s in m["skipped_questions"] for r in s["reasons"]), "un «Completar» con un hueco de texto (SHORTANSWER) también, explicado")
sin_clave = [s for s in m["skipped_questions"] if "Sin" in s["preview"] or "marcada" in s["preview"]]
ok(sin_clave and sin_clave[0].get("recoverable_data"), "una opción múltiple sin respuesta marcada: omitida pero RESCATABLE en el editor")
ok(all(isinstance(s["despues_de"], int) for s in m["skipped_questions"]), "cada no incluida dice después de qué pregunta iba")
ok(sorted((s["type"], s["despues_de"]) for s in m["skipped_questions"]) == sorted([("cloze", 6), ("calculated", 7), ("description", 7), ("multichoice", 7)]),
   f"…contando solo las INCLUIDAS ({sorted((s['type'], s['despues_de']) for s in m['skipped_questions'])})")

# El segundo cloze (MC/MCV) sí es editable
m2 = ix.importar_xml(MOODLE.replace('{1:SHORTANSWER:=ADN}', 'x').encode("utf-8"), "banco2.xml")
cl1 = next(q for q in m2["questions"] if q["type"] == "cloze")
h1 = m2["answer_key"][cl1["num"]]["huecos"]
ok(h1[0]["options"] == ["mitocondria", "ribosoma", "núcleo"] and h1[0]["correct_idx"] == [0, 2] and h1[1]["options"] == ["ATP", "energía", "agua"] and h1[1]["correct_idx"] == [0, 1],
   f"completar de Moodle: «=», «%100%», «#comentario» y MULTIRESPONSE ({h1})")
ok("#" not in str(h1) and "bien" not in str(h1), "la retroalimentación del hueco (#…) no se mezcla con las opciones")

# ══════════════════════════════════════════════════════════════════════════
print("3. Imágenes")
# ══════════════════════════════════════════════════════════════════════════
def png(n=8):
    def trozo(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    filas = b"".join(b"\x00" + b"\x20\x80\xd0" * n for _ in range(n))
    return (b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0))
            + trozo(b"IDAT", zlib.compress(filas)) + trozo(b"IEND", b""))


def con_imagen(nombre, datos, extra=""):
    return f"""<quiz><question type="essay"><name><text>I</text></name><questiontext format="html">
<text><![CDATA[<p>Mira<img src="@@PLUGINFILE@@/{nombre}" alt="x"></p>]]></text>
<file name="{nombre}" path="/" encoding="base64">{base64.b64encode(datos).decode()}</file>{extra}</questiontext></question></quiz>""".encode("utf-8")


r = ix.importar_xml(con_imagen("figura 1.png", png()))
ok(r["questions"][0]["data"]["images"][0]["name"] == "pregunta1-1.png" and r["questions"][0]["data"]["stem"] == "Mira", "PNG: se importa con un nombre válido y el <img> sale del texto")
r = ix.importar_xml(con_imagen("a.gif", b"GIF89a" + b"\x00" * 30))
ok("images" not in r["questions"][0]["data"] and "no es PNG ni JPEG" in (r["completeness_notice"] or ""), "GIF: no se importa y se avisa")
r = ix.importar_xml(con_imagen("grande.png", png() + b"\x00" * (2 * 1024 * 1024 + 10)))
ok("images" not in r["questions"][0]["data"] and "2 MB" in (r["completeness_notice"] or ""), "imagen de más de 2 MB: se avisa")
r = ix.importar_xml(con_imagen("rota.png", b"\x89PNG\r\n\x1a\nbasura"))
ok("images" not in r["questions"][0]["data"] and "no se pudo leer" in (r["completeness_notice"] or ""), "PNG dañado: se avisa")

# ══════════════════════════════════════════════════════════════════════════
print("4. Seguridad y errores")
# ══════════════════════════════════════════════════════════════════════════
def rechaza(raw, contiene):
    try:
        ix.importar_xml(raw)
        return False
    except HTTPException as e:
        d = e.detail if isinstance(e.detail, str) else (e.detail.get("message", "") + " ".join(e.detail.get("errors", [])))
        return e.status_code == 422 and contiene in d


ok(rechaza(b"esto no es xml", "dañado o incompleto"), "texto que no es XML: 422 claro")
ok(rechaza(b"<quiz><question type='essay'>", "dañado o incompleto"), "XML cortado: 422 claro")
ok(rechaza(b"<html><body>hola</body></html>", "no es un archivo de preguntas de Moodle"), "un XML que no es un quiz: 422")
ok(rechaza(b"<quiz></quiz>", "ninguna pregunta"), "un quiz vacío: 422")
ok(rechaza(b"<quiz><question type='calculated'><questiontext><text>x</text></questiontext></question></quiz>", "calculada"), "solo tipos que no se editan: 422 con el motivo")
secreto = TMP / "secreto.txt"
secreto.write_text("CONTENIDO-SECRETO-123", encoding="utf-8")
xxe = f"""<?xml version="1.0"?><!DOCTYPE q [<!ENTITY leer SYSTEM "file://{secreto}">]>
<quiz><question type="essay"><name><text>x</text></name><questiontext><text>A &leer; B</text></questiontext></question></quiz>""".encode()
try:
    r = ix.importar_xml(xxe)
    ok("CONTENIDO-SECRETO" not in str(r), "una entidad externa (XXE) NO lee archivos del equipo")
except HTTPException:
    ok(True, "una entidad externa (XXE) se rechaza")
bomba = ("""<?xml version="1.0"?><!DOCTYPE b [<!ENTITY a "AAAAAAAAAA"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">
<!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;"><!ENTITY e "&d;&d;&d;&d;&d;&d;&d;&d;&d;&d;"><!ENTITY f "&e;&e;&e;&e;&e;&e;&e;&e;&e;&e;">]>
<quiz><question type="essay"><name><text>x</text></name><questiontext><text>&f;&f;&f;&f;&f;&f;&f;&f;&f;&f;</text></questiontext></question></quiz>""").encode()
t0 = time.time()
try:
    r = ix.importar_xml(bomba)
    largo = len(r["questions"][0]["data"]["stem"])
except HTTPException:
    largo = 0
ok(time.time() - t0 < 2 and largo < 1000, f"«billion laughs»: no se expande ({largo} caracteres, {time.time() - t0:.2f} s)")
muchas = ("<quiz>" + "<question type='essay'><name><text>x</text></name><questiontext><text>p</text></questiontext></question>" * (ix.MAX_PREGUNTAS + 1) + "</quiz>").encode()
ok(rechaza(muchas, "máximo"), f"más de {ix.MAX_PREGUNTAS} preguntas: 422")

# ══════════════════════════════════════════════════════════════════════════
print("5. Ruta /api/importar_xml")
# ══════════════════════════════════════════════════════════════════════════
c = TestClient(main.app, base_url="http://127.0.0.1:8000")
H = {"X-Conversor-Token": seguridad.TOKEN}
r = c.post("/api/importar_xml", files={"file": ("conformidad.xml", conf, "text/xml")}, headers=H)
j = r.json()
ok(r.status_code == 200 and len(j["questions"]) == 10 and j["importado"] and j["filename"] == "conformidad.xml", f"200 con el resultado del editor ({r.status_code})")
r = c.post("/api/importar_xml", files={"file": ("mal.xml", b"nada", "text/xml")}, headers=H)
ok(r.status_code == 422 and "dañado" in r.json()["detail"], "XML dañado: 422 con mensaje")
ok(c.post("/api/importar_xml", files={"file": ("a.xml", conf, "text/xml")}).status_code == 401, "sin token: 401")
r = c.post("/api/importar_xml", files={"file": ("a.xml", conf, "text/xml")}, headers=H)
xml_de_vuelta = c.post("/api/generate_xml", json={
    "questions": r.json()["questions"], "answer_key": {str(k): v for k, v in r.json()["answer_key"].items()},
    "filename": "a.xml", "category": r.json()["categoria"], "total_points": 18,
}, headers=H)
ok(xml_de_vuelta.status_code == 200, f"lo importado vuelve a pasar por «Generar XML» ({xml_de_vuelta.status_code})")
ok("a_editado.xml" in xml_de_vuelta.headers.get("content-disposition", ""), "y el XML que sale no se llama igual que el original (a_editado.xml)")

print()
print("TODO OK" if not fallas else f"{fallas} FALLA(S)")
sys.exit(1 if fallas else 0)
