"""
test_enunciado_compartido.py — un enunciado compartido por varias preguntas («Del siguiente caso responda
las preguntas 1 a 5»).

    PYTHONUTF8=1 backend/venv/bin/python dev/test_enunciado_compartido.py

Sin red ni Gemini y sin base de datos (la IA se simula con su JSON):
  1. De la respuesta de la IA a las preguntas (schema_adapter): grupos, grupos de una sola y preguntas rescatadas.
  2. Moodle XML: el enunciado va dentro de cada pregunta del grupo, y al importar el XML se recupera.
  3. PDF y Word: sale una sola vez, con los números impresos; repartido entre partes se avisa.
  4. Imágenes del enunciado compartido y ayudas con IA.
"""

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import docx  # noqa: E402
import pdfplumber  # noqa: E402
from PIL import Image  # noqa: E402

import ayuda_ia  # noqa: E402
import exportar_docx  # noqa: E402
import exportar_pdf  # noqa: E402
import imagenes  # noqa: E402
import importar_xml  # noqa: E402
import schema_adapter  # noqa: E402
import xml_builder  # noqa: E402
from modelo import preguntas_desde_dicts, tramos_compartidos  # noqa: E402
from plan_impreso import DatosExamen  # noqa: E402

fallas = []


def ok(cond, texto):
    print(("  ok   " if cond else "  FALLA ") + texto)
    if not cond:
        fallas.append(texto)


CASO = "La empresa ACME evalúa un proyecto {1:MC:=trampa} de TI.\nCosto: 10 000 & plazo < 6 meses."


def mc(orden, **extra):
    return {"orden": orden, "tipo": "multichoice", "enunciado": f"PREGUNTA-{orden} sobre el caso",
            "opciones": [{"texto": "Alfa", "correcta": True}, {"texto": "Beta", "correcta": False}], **extra}


def cloze(orden, **extra):
    return {"orden": orden, "tipo": "cloze", "enunciado": "El plazo es [A].",
            "huecos": [{"marcador": "A", "opciones": [{"texto": "corto", "correcta": True},
                                                      {"texto": "largo", "correcta": False}]}], **extra}


SIGUE = {"sigue_enunciado_compartido": True}


def contextos(preguntas):
    return [q["data"].get("contexto") for q in schema_adapter.adapt({"preguntas": preguntas})[0]]


print("1. De la respuesta de la IA a las preguntas")
payload = [mc(1, enunciado_compartido=CASO), mc(2, **SIGUE), cloze(3, **SIGUE), mc(4),
           {"orden": 5, "tipo": "essay", "enunciado": "Explique", "enunciado_compartido": "Caso de una sola"}]
qs, ak = schema_adapter.adapt({"preguntas": payload})
ok([q["data"].get("contexto") for q in qs] == [CASO, CASO, CASO, None, None], "el grupo es la primera y las que lo siguen")
ok(qs[4]["data"]["stem"] == "Caso de una sola\nExplique", "un «grupo» de una sola pregunta vuelve a su enunciado: no se pierde nada")
ok(contextos([mc(1, **SIGUE), mc(2)]) == [None, None], "«sigue» sin un enunciado antes no inventa un grupo")
ok(contextos([mc(1, enunciado_compartido="A"), mc(2, **SIGUE), mc(3, enunciado_compartido="B"), mc(4, **SIGUE)]) == ["A", "A", "B", "B"],
   "dos grupos seguidos no se mezclan")
ok(contextos([mc(1, enunciado_compartido="A"), mc(2, enunciado_compartido="A")]) == ["A", "A"], "repetido en cada una: el mismo grupo")
ok(contextos([mc(1, enunciado_compartido="A"), mc(2, _rescatada=True), mc(3, **SIGUE)]) == ["A", "A", "A"],
   "una pregunta recuperada por un reintento no parte el grupo")
ok(contextos([mc(1, enunciado_compartido="A"), mc(2, **SIGUE), mc(3, _rescatada=True)]) == ["A", "A", None],
   "…y al final del grupo no se le añade")
rep, _ = schema_adapter.adapt({"preguntas": [{**mc(1, enunciado_compartido="CASO X"), "enunciado": "CASO X\n¿Cuál?"}, mc(2, **SIGUE)]})
ok(rep[0]["data"]["stem"] == "¿Cuál?", "si la IA lo repitió en el enunciado, se quita de ahí")
ok([(a, b) for a, b, _ in tramos_compartidos(preguntas_desde_dicts(qs, ak))] == [(0, 3)], "tramos_compartidos")

print("2. Moodle XML")
xml, _ = xml_builder.build_xml(qs, ak)
ok(xml.count(f'class="{xml_builder.CLASE_CONTEXTO}"') == 3, "va dentro de cada pregunta del grupo (y solo de esas)")
ok("10 000 &amp; plazo &lt; 6 meses" in xml, "el texto va escapado")
bloque_cloze = xml.split('<question type="cloze">')[1].split("</question>")[0]
ok("{1:MC:=trampa}" not in bloque_cloze and "&#123;1:MC:=trampa}" in bloque_cloze, "en «Completar», una llave del caso no crea un espacio")
vuelta = importar_xml.importar_xml(xml.encode("utf-8"), "a.xml")["questions"]
ok([q["data"].get("contexto") for q in vuelta] == [CASO, CASO, CASO, None, None], "al importar el XML se recupera el grupo")
ok([q["data"].get("stem") or q["data"].get("text") for q in vuelta] == [q["data"].get("stem") or q["data"].get("text") for q in qs],
   "…sin que quede repetido en el enunciado")
sin = [{**q, "data": {k: v for k, v in q["data"].items() if k != "contexto"}} for q in qs]
vacio = [{**q, "data": {**q["data"], "contexto": "   "}} for q in sin]
ok(xml_builder.build_xml(vacio, ak)[0] == xml_builder.build_xml(sin, ak)[0], "uno vacío (recién creado en el editor) no cambia el XML")

print("3. PDF y Word")


def pdf(preguntas, clave, **datos):
    r = exportar_pdf.generar_pdf(preguntas, clave, 100, DatosExamen(campos_estudiante=False, **datos))
    with pdfplumber.open(io.BytesIO(r.pdf)) as d:
        return "\n".join(p.extract_text() or "" for p in d.pages), r.avisos


texto, avisos = pdf(qs[:3], ak, partes=False, contenido="solo_examen")
ok(texto.count("Con base en el siguiente enunciado") == 1 and "responda las preguntas 1 a 3:" in texto and texto.count("ACME") == 1,
   "sale una sola vez, con su rango")
ok(texto.index("ACME") < texto.index("PREGUNTA-1"), "va antes de la primera pregunta del grupo")
ok(not avisos, "sin avisos")
texto, avisos = pdf(qs, ak, partes=True, contenido="solo_examen")
ok(texto.count("ACME") == 1 and "responda las preguntas 1 a 3:" in texto and not avisos,
   "con tipos distintos y «Agrupar por tipo» sale UNA vez, con sus tres preguntas")
junto = " ".join(texto.split())
orden = [junto.index(x) for x in ("responda las preguntas 1 a 3:", "I PARTE: SELECCIÓN MÚLTIPLE", "PREGUNTA-1", "PREGUNTA-2",
                                    "II PARTE: COMPLETAR", "III PARTE: SELECCIÓN MÚLTIPLE", "PREGUNTA-4", "IV PARTE: DESARROLLO")]
ok(orden == sorted(orden), f"…el enunciado delante, sus partes por tipo seguidas y después las independientes ({orden})")
al_reves, _ = pdf([qs[3], *qs[:3]], ak, partes=True, contenido="solo_examen")
junto = " ".join(al_reves.split())
ok(junto.index("PREGUNTA-4") < junto.index("ACME") < junto.index("PREGUNTA-1") and "responda las preguntas 2 a 4:" in junto,
   "un enunciado que va después de las independientes sale después")
hoja_, _ = pdf(qs, ak, partes=True, contenido="folleto_hoja_clave")
ok(hoja_.count("ACME") == 1, "en la hoja de preguntas también una sola vez")
partidos = [qs[0], qs[3], qs[1]]
texto, avisos = pdf(partidos, ak, partes=False, contenido="solo_examen")
ok(texto.count("ACME") == 2 and any("sale más de una vez" in a and "juntas en el editor" in a for a in avisos),
   "si en el editor no van seguidas, se repite y se avisa")
folleto, _ = pdf(qs[:3], ak, partes=False, contenido="folleto_hoja_clave")
ok(folleto.count("ACME") == 1, "en folleto + hoja + clave sale solo en el folleto")
clave_sola, _ = pdf(qs[:3], ak, contenido="solo_clave")
ok("ACME" not in clave_sola, "la clave no lo repite")
subconjunto, _ = pdf([qs[1]], ak, partes=False, contenido="solo_examen")
ok("responda la pregunta 1:" in subconjunto and "ACME" in subconjunto, "una versión con una sola del grupo lleva el enunciado")
w = exportar_docx.generar_docx(qs[:3], ak, 100, DatosExamen(partes=False, contenido="solo_examen"))
parrafos = "\n".join(p.text for p in docx.Document(io.BytesIO(w.docx)).paragraphs)
ok(parrafos.count("ACME") == 1 and "responda las preguntas 1 a 3:" in parrafos, "el Word dice lo mismo")

print("4. Imágenes y ayudas con IA")


def png(color):
    s = io.BytesIO()
    Image.new("RGB", (120, 60), color).save(s, "PNG")
    import base64
    return base64.b64encode(s.getvalue()).decode("ascii")


comun, propia = png("red"), png("blue")
con_img = [{**q, "data": {**q["data"], "images": [{"name": f"c{q['num']}.png", "mime": "image/png", "b64": comun}]}} for q in qs[:3]]
con_img[1]["data"]["images"].append({"name": "p.png", "mime": "image/png", "b64": propia})


def n_imagenes(preguntas):
    r = exportar_pdf.generar_pdf(preguntas, ak, 100, DatosExamen(partes=False, contenido="solo_examen", campos_estudiante=False))
    with pdfplumber.open(io.BytesIO(r.pdf)) as d:
        return sum(len(p.images) for p in d.pages)


ok(n_imagenes(con_img) == 2, "la imagen de todo el grupo se imprime una vez; la propia de una pregunta, en la suya")

lineas = [imagenes.Linea((0, y), t) for y, t in ((10, "1. Pregunta anterior sobre otra cosa"),
                                                 (20, "Observe el diagrama de la red de ACME"),
                                                 (60, "2. Cuántos equipos hay"), (70, "3. Cuántos enlaces hay"))]
grupo = [{"num": 1, "type": "essay", "data": {"stem": "Pregunta anterior sobre otra cosa"}},
         {"num": 2, "type": "essay", "data": {"stem": "Cuántos equipos hay", "contexto": "Observe el diagrama de la red de ACME"}},
         {"num": 3, "type": "essay", "data": {"stem": "Cuántos enlaces hay", "contexto": "Observe el diagrama de la red de ACME"}}]
ub = imagenes.Ubicaciones(lineas, [imagenes.ImagenUbicada(Image.new("RGB", (200, 100), "green"), (0, 30), (0, 50))])
imagenes.asignar_imagenes(grupo, ub)
ok([len(q["data"].get("images") or []) for q in grupo] == [0, 1, 1], "una imagen dentro del enunciado compartido va a todo su grupo")

texto_ia = ayuda_ia.texto_pregunta(qs[0], ak[1])
ok("ACME" in texto_ia and "ACME" in ayuda_ia._texto_sugerir(qs[0], ak[1]) and "ACME" in ayuda_ia._texto_sugerir(qs[2], ak[3]),
   "las ayudas con IA reciben el enunciado compartido")

print("5. Imágenes adjuntas al enunciado (3.2)")
figura = {"name": "pregunta1-1.png", "mime": "image/png", "b64": comun, "compartida": True}
suya = {"name": "pregunta1-2.png", "mime": "image/png", "b64": propia}


def con_figura(preguntas, texto, extra=()):
    return [{**q, "data": {**q["data"], "contexto": texto, "images": [{**figura, "name": f"pregunta{q['num']}-1.png"}, *extra]}}
            for q in preguntas]


una = con_figura([qs[0]], "Caso con figura", [suya])
xml, _ = xml_builder.build_xml(una, ak)
trozo = xml.split('<question type="multichoice">')[1]
div = trozo.split(f'class="{xml_builder.CLASE_CONTEXTO}">')[1].split("</div>")[0]
ok("Caso con figura" in div and "pregunta1-1.png" in div and "pregunta1-2.png" not in div,
   "XML: la imagen del enunciado va dentro de su bloque, antes del enunciado de la pregunta; la propia, fuera")
ok(trozo.count("pregunta1-2.png") == 2 and trozo.count("pregunta1-1.png") == 2, "cada imagen va una vez en el texto y con su archivo")
vuelta = importar_xml.importar_xml(xml.encode("utf-8"), "a.xml")["questions"][0]["data"]
ok(vuelta.get("contexto") == "Caso con figura" and [bool(i.get("compartida")) for i in vuelta["images"]] == [True, False],
   f"al importar, el grupo de una sola pregunta se conserva y sabe cuál imagen es del enunciado ({vuelta.get('contexto')!r})")
solo = con_figura(qs[:2], "")
ok([(a, b, c) for a, b, c in tramos_compartidos(preguntas_desde_dicts(solo, ak))] == [(0, 2, "")], "un enunciado puede ser solo una imagen")
ok([(a, b) for a, b, _ in tramos_compartidos(preguntas_desde_dicts([solo[0], {**solo[1], "data": {**solo[1]["data"], "images": [{**suya, "compartida": True}]}}], ak))] == [(0, 1), (1, 2)],
   "el mismo texto con otra imagen es otro enunciado")
xml_solo, _ = xml_builder.build_xml(solo, ak)
ok(xml_solo.count(f'class="{xml_builder.CLASE_CONTEXTO}"><p><img') == 2, "XML: sin texto, el bloque lleva solo la imagen")
vuelta = importar_xml.importar_xml(xml_solo.encode("utf-8"), "a.xml")["questions"]
ok([(q["data"].get("contexto"), bool(q["data"]["images"][0].get("compartida"))) for q in vuelta] == [("", True), ("", True)],
   "…y al importar sigue siendo un enunciado de solo imagen")
ok(n_imagenes(solo) == 1 and n_imagenes(con_figura([qs[0]], "Caso", [suya])) == 2, "PDF: la del enunciado sale una vez, aunque sea de una sola pregunta")
texto, _ = pdf(solo, ak, partes=False, contenido="solo_examen")
ok("Con base en la siguiente imagen, responda las preguntas 1 y 2:" in texto, "PDF: sin texto lo dice como imagen")
texto, _ = pdf(una, ak, partes=False, contenido="solo_examen")
ok(texto.index("Caso con figura") < texto.index("PREGUNTA-1"), "PDF: el enunciado va antes")
mezclado = con_figura(qs[:3], "Caso con figura")
ok(n_imagenes(mezclado) == 1, "sin partes, una sola imagen para las tres")
r = exportar_pdf.generar_pdf(mezclado, ak, 100, DatosExamen(partes=True, contenido="solo_examen", campos_estudiante=False))
with pdfplumber.open(io.BytesIO(r.pdf)) as d_:
    ok(sum(len(p.images) for p in d_.pages) == 1, "con partes y tipos distintos, la imagen sale UNA vez")
w = exportar_docx.generar_docx(solo, ak, 100, DatosExamen(partes=False, contenido="solo_examen"))
d = docx.Document(io.BytesIO(w.docx))
ok(len(d.inline_shapes) >= 1 and "Con base en la siguiente imagen" in "\n".join(p.text for p in d.paragraphs), "Word: igual")

print()
print("TODO OK" if not fallas else f"{len(fallas)} FALLA(S)")
sys.exit(1 if fallas else 0)
