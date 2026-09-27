"""
test_mejoras.py — Word (.docx), imágenes en Moodle, retroalimentación
opcional (y el botón «Escribir con IA») y fórmulas (LaTeX).

    backend/venv/bin/python dev/test_mejoras.py

No llama a Gemini: la respuesta de la IA se simula con lo que devolvería
para el documento de prueba, así se prueba todo lo que hace el código
(lectura, marcas, asignación de imágenes, validación y XML). No toca el
historial ni la clave guardada.
"""

import base64
import io
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from lxml import etree  # noqa: E402
from PIL import Image  # noqa: E402

import extractor  # noqa: E402
import extractor_docx  # noqa: E402
import imagenes  # noqa: E402
import formatter  # noqa: E402
import pipeline  # noqa: E402
import ayuda_ia  # noqa: E402
import schema_adapter  # noqa: E402
from validator import validate_questions  # noqa: E402
from xml_builder import build_xml  # noqa: E402

fallas = 0


def ok(cond, msg):
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


# ── Word de prueba (OOXML armado a mano) ───────────────────────────────────
_W = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
      'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"')


def _run(t, props=""):
    return f'<w:r><w:rPr>{props}</w:rPr><w:t xml:space="preserve">{t}</w:t></w:r>'


def _p(contenido, num=None):
    np_ = f'<w:pPr><w:numPr><w:ilvl w:val="{num[1]}"/><w:numId w:val="{num[0]}"/></w:numPr></w:pPr>' if num else ""
    return f"<w:p>{np_}{contenido}</w:p>"


_IMG = ('<w:r><w:drawing><wp:inline><wp:extent cx="900000" cy="900000"/><wp:docPr id="1" name="i"/><a:graphic>'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr>'
        '<pic:cNvPr id="1" name="i.png"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="rIdImg"/>'
        '</pic:blipFill><pic:spPr/></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>')
_EQ = ('<m:oMath><m:f><m:num><m:sSup><m:e><m:r><m:t>x</m:t></m:r></m:e><m:sup><m:r><m:t>2</m:t></m:r></m:sup>'
       '</m:sSup></m:num><m:den><m:r><m:t>2</m:t></m:r></m:den></m:f></m:oMath>')


def word_de_prueba(mezcladas: bool = True) -> bytes:
    """`mezcladas`: cada respuesta con una marca distinta (para probar que el
    lector las reconoce todas); si no, todas en rojo, como un examen real."""
    resaltado = '<w:highlight w:val="yellow"/>' if mezcladas else '<w:color w:val="FF0000"/>'
    subrayado = '<w:u w:val="single"/>' if mezcladas else '<w:color w:val="FF0000"/>'
    cuerpo = "".join([
        _p(_run("Parcial de prueba")),
        _p(_run("¿Cuánto vale ") + _EQ + _run(" si x = 2?"), (1, 0)), _p(_run("1"), (1, 1)), _p(_run("2", '<w:rStyle w:val="Resp"/>'), (1, 1)),
        _p(_run("¿Capital de Francia?"), (1, 0)), _p(_run("París", '<w:color w:val="FF0000"/>'), (1, 1)), _p(_run("Madrid"), (1, 1)),
        _p(_run("¿Capital de Italia?"), (1, 0)), _p(_run("Milán"), (1, 1)), _p(_run("Roma", resaltado), (1, 1)),
        _p(_run("¿Qué muestra la figura?"), (1, 0)), _p(_IMG), _p(_run("Un ícono", subrayado), (1, 1)), _p(_run("Un mapa"), (1, 1)),
        '<w:tbl><w:tr><w:tc><w:p/></w:tc><w:tc>' + _p(_run("Mamífero")) + '</w:tc><w:tc>' + _p(_run("Ave")) + '</w:tc></w:tr>'
        '<w:tr><w:tc>' + _p(_run("Delfín")) + '</w:tc><w:tc>' + _p(_run("X")) + '</w:tc><w:tc><w:p/></w:tc></w:tr></w:tbl>',
    ])
    numeracion = ('<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:abstractNum w:abstractNumId="0">'
                  '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>'
                  '<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/><w:lvlText w:val="%2)"/></w:lvl>'
                  '</w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>')
    estilos = ('<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
               '<w:style w:type="character" w:styleId="Base"><w:rPr><w:color w:val="C00000"/></w:rPr></w:style>'
               '<w:style w:type="character" w:styleId="Resp"><w:basedOn w:val="Base"/></w:style></w:styles>')
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rIdImg" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>'
            '</Relationships>')
    png = io.BytesIO()
    Image.new("RGB", (120, 80), (30, 120, 200)).save(png, "PNG")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", f'<w:document {_W}><w:body>{cuerpo}</w:body></w:document>')
        z.writestr("word/numbering.xml", numeracion)
        z.writestr("word/styles.xml", estilos)
        z.writestr("word/_rels/document.xml.rels", rels)
        z.writestr("word/media/image1.png", png.getvalue())
    return buf.getvalue()


print("Word (.docx)")
d = extractor_docx.leer_docx(word_de_prueba())
t = d.texto_enriquecido
ok("1. ¿Cuánto vale" in t and "2. ¿Capital de Francia?" in t and "a) " in t, "numeración automática reconstruida (1., 2., a), b))")
ok("⟦rojo⟧París⟦/rojo⟧" in t and "⟦resaltado⟧Roma⟦/resaltado⟧" in t and "⟦subrayado⟧Un ícono⟦/subrayado⟧" in t, "marcas de color, resaltado y subrayado")
ok("b) ⟦rojo⟧2⟦/rojo⟧" in t, "color heredado de un estilo (basedOn)")
ok(r"\(\frac{{x}^{2}}{2}\)" in t, "ecuación de Word convertida a LaTeX")
ok("[Tabla]" in t and d.tablas == [[["", "Mamífero", "Ave"], ["Delfín", "X", ""]]], "tabla con su estructura")
ub = d.ubicaciones
parrafo = next(l.pos for l in ub.lineas if l.texto.startswith("4. ¿Qué muestra"))
ok(len(ub.imagenes) == 1 and ub.imagenes[0].inicio > parrafo, "imagen ubicada después del enunciado de la pregunta 4")
ok("⟦" not in d.texto_plano, "texto plano sin marcas")

for malo, motivo in ((b"no es un zip", "no es ZIP"), (b"PK\x03\x04basura", "ZIP roto")):
    try:
        extractor_docx.leer_docx(malo)
        ok(False, f"archivo inválido rechazado ({motivo})")
    except extractor_docx.DocxInvalido:
        ok(True, f"archivo inválido rechazado ({motivo})")
bomba = io.BytesIO()
with zipfile.ZipFile(bomba, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("word/document.xml", "<a/>")
    z.writestr("word/relleno.bin", b"\0" * (extractor_docx.MAX_DESCOMPRIMIDO + 1))
try:
    extractor_docx.leer_docx(bomba.getvalue())
    ok(False, "ZIP que se infla al abrirse rechazado")
except extractor_docx.DocxInvalido:
    ok(True, f"ZIP que se infla al abrirse rechazado ({len(bomba.getvalue()) // 1024} KB → >80 MB)")
entidad = io.BytesIO()
with zipfile.ZipFile(entidad, "w") as z:
    z.writestr("word/document.xml", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
               f'<w:document {_W}><w:body><w:p><w:r><w:t>&e;</w:t></w:r></w:p></w:body></w:document>')
try:
    ok("root:" not in extractor_docx.leer_docx(entidad.getvalue()).texto_plano, "XML con entidad externa: no lee archivos del equipo")
except Exception:
    ok(True, "XML con entidad externa: rechazado")

print("Ecuaciones (OMML → LaTeX)")
M = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
casos = {
    f'<m:oMath {M}><m:nary><m:naryPr><m:chr m:val="∑"/></m:naryPr><m:sub><m:r><m:t>i=1</m:t></m:r></m:sub><m:sup><m:r><m:t>n</m:t></m:r></m:sup><m:e><m:r><m:t>i</m:t></m:r></m:e></m:nary></m:oMath>': r"\(\sum_{i=1}^{n}{i}\)",
    f'<m:oMath {M}><m:func><m:fName><m:r><m:t>sin</m:t></m:r></m:fName><m:e><m:r><m:t>α</m:t></m:r></m:e></m:func></m:oMath>': r"\(\sin{\alpha }\)",
    f'<m:oMath {M}><m:d><m:e><m:r><m:t>a+b</m:t></m:r></m:e></m:d><m:sSup><m:e><m:r><m:t></m:t></m:r></m:e><m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSup></m:oMath>': r"\(\left( a+b \right){}^{2}\)",
}
for xml, esperado in casos.items():
    obtenido = extractor_docx._ecuacion(etree.fromstring(xml))
    ok(obtenido == esperado, f"{esperado}  (obtenido {obtenido})")


print("Flujo completo con Word (IA simulada)")
# Lo que devolvería la IA: sin marcar la correcta (la decide el código por
# las marcas del documento), con la fórmula en LaTeX y una justificación.
def op(letra, texto, correcta=False):
    return {"letra_original": letra, "texto": texto, "correcta": correcta}


def preg(orden, enunciado, opciones, retro=""):
    return {"orden": orden, "tipo": "multichoice", "enunciado": enunciado, "opciones": opciones,
            "items_izquierda": [], "items_derecha": [], "parejas": [], "huecos": [], "clave_texto": "",
            "respuesta_texto": "", "retroalimentacion": retro, "respuesta_marcada": True,
            "origen_tabla": False, "pagina": 1, "confianza": "alta"}


respuesta_ia = {"es_examen": True, "preguntas": [
    preg(1, r"¿Cuánto vale \(\frac{x^2}{2}\) si x = 2?", [op("a", "1"), op("b", "2")], "Porque 2²/2 = 2."),
    preg(2, "¿Capital de Francia?", [op("a", "París"), op("b", "Madrid")]),
    preg(3, "¿Capital de Italia?", [op("a", "Milán"), op("b", "Roma")]),
    preg(4, "¿Qué muestra la figura?", [op("a", "Un ícono"), op("b", "Un mapa")]),
]}
pipeline.get_api_key = lambda: "clave-de-prueba"
pipeline.extract_structured = lambda *a, **k: respuesta_ia
r = pipeline.parse_document(word_de_prueba(mezcladas=False), "prueba.docx")
qs = {q["num"]: q for q in r["questions"]}
ak = r["answer_key"]
ok(ak[1]["answer"] == "2" and ak[2]["answer"] == "París" and ak[3]["answer"] == "Roma" and ak[4]["answer"] == "Un ícono",
   "respuestas tomadas de las marcas de Word (rojo directo y rojo heredado de un estilo)")
ok(len(qs[4]["data"].get("images", [])) == 1 and not any(qs[n]["data"].get("images") for n in (1, 2, 3)), "la imagen quedó solo en la pregunta 4")
ok(qs[1]["data"].get("feedback") == "Porque 2²/2 = 2." and "feedback" not in qs[2]["data"], "retroalimentación: solo donde el documento la traía")
ok(r"\(\frac{x^2}{2}\)" in qs[1]["data"]["stem"], "la fórmula en LaTeX se conserva")

print("XML para Moodle")
preguntas = r["questions"]
for q in preguntas:
    q["points"] = 1
val = validate_questions(preguntas, ak, strict=True)
ok(val.is_valid, f"las preguntas pasan la validación estricta {val.errors[:2]}")
xml, _ = build_xml(preguntas, ak, category="prueba")
raiz = etree.fromstring(xml.encode("utf-8"))
p4 = [q for q in raiz.findall("question") if q.get("type") == "multichoice"][3]
f = p4.find("questiontext/file")
ok(f is not None and f.get("encoding") == "base64" and f.get("path") == "/", "<file encoding=\"base64\"> dentro de <questiontext>")
ok(f is not None and f'@@PLUGINFILE@@/{f.get("name")}' in p4.find("questiontext/text").text, "el texto cita la imagen con @@PLUGINFILE@@")
ok(f is not None and Image.open(io.BytesIO(base64.b64decode(f.text))).size == (120, 80), "la imagen incrustada se decodifica intacta")
gfs = [q.find("generalfeedback") for q in raiz.findall("question") if q.get("type") == "multichoice"]
ok(gfs[0] is not None and "Porque 2" in gfs[0].find("text").text and all(g is None for g in gfs[1:]),
   "<generalfeedback> solo en la pregunta que la tiene (es opcional)")
ok(r"\(\frac{x^2}{2}\)" in raiz.findall("question")[1].find("questiontext/text").text, "LaTeX intacto en el XML (Moodle lo muestra con MathJax)")

print("Validación de lo que vuelve del editor")
def con(**datos):
    q = json.loads(json.dumps(preguntas[3]))
    q["data"].update(datos)
    return validate_questions([q], {4: ak[4]}, strict=True)
img = preguntas[3]["data"]["images"][0]
ok(not con(images=[{**img, "name": "../../x.png"}]).is_valid, "nombre de imagen con ruta: rechazado")
ok(not con(images=[{**img, "b64": "<script>"}]).is_valid, "contenido que no es base64: rechazado")
ok(not con(images=[{**img, "mime": "text/html"}]).is_valid, "tipo que no es imagen: rechazado")
ok(not con(feedback=["no", "texto"]).is_valid, "retroalimentación que no es texto: rechazada")
ok(con(feedback="").is_valid and con(images=[]).is_valid, "sin retroalimentación ni imágenes: válido (son opcionales)")


print("Imágenes de un PDF")
pdf = ROOT / "samples" / "synthetic" / "x11_codigo_en_imagen.pdf"
def _con_imagenes(ruta, golden):
    g = json.loads((ROOT / "samples" / "golden" / f"{golden}.expected.json").read_text(encoding="utf-8"))
    qs_ = [{"num": i, "type": q["type"], "data": {"stem": q.get("stem") or q.get("text") or ""}}
           for i, q in enumerate(g["questions"], 1)]
    ub_ = imagenes.extraer_imagenes_pdf(ruta.read_bytes())
    n = imagenes.asignar_imagenes(qs_, ub_)
    return n, len(ub_.imagenes), {q["num"]: len(q["data"]["images"]) for q in qs_ if q["data"].get("images")}


n, total, mapa = _con_imagenes(pdf, "x11_codigo_en_imagen")
esperado_x11 = {k: 1 for k in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 16, 17, 19, 20, 23, 24, 25, 27, 29)}
ok(n == total == 20, f"x11: las 20 imágenes asignadas ({n} de {total})")
ok(mapa == esperado_x11, "x11: cada imagen en la pregunta con su mismo número (hay enunciados repetidos)")
real = next(ROOT.glob("samples/**/Parcial #1_ Computacion.pdf"), None)
if real:
    n, total, mapa = _con_imagenes(real, "real_parcial_1_computacion")
    # Posiciones verificadas en el PDF: 9 y 10 con la imagen en el renglón de
    # su número; el código del punto «14.» (solo imagen) es de «15. Cuantos
    # errores en total tiene el código» (la 20 aquí), no de la tabla de
    # arriba («Rellenar el cuadro…», que la IA corrige de «coreponda»); el
    # código de la 17 («Del siguiente código»); y dos preguntas SIN número
    # (25 y 28) cuya imagen antes caía en la pregunta numerada anterior.
    ok(n == total == 8 and mapa == {8: 1, 9: 1, 20: 1, 22: 1, 24: 1, 25: 1, 26: 1, 28: 1},
       f"examen real de Computación: 8 imágenes, una por pregunta y en la correcta ({mapa})")
# Imagen entre dos preguntas: el enunciado decide.
def _vecinas(arriba, abajo):
    qa = {"num": 1, "type": "essay", "data": {"stem": arriba}}
    qb = {"num": 2, "type": "essay", "data": {"stem": abajo}}
    return imagenes._elegir(qa, qb)["num"]
ok(_vecinas("Rellenar el cuadro con la función", "Cuantos errores en total tiene el código") == 2,
   "la de arriba no habla de código y la de abajo sí: la imagen es de la de abajo")
ok(_vecinas("Del siguiente código cual seria el resultado", "Crear un ciclo FOR para imprimir") == 1,
   "«del siguiente código»: la imagen es de la de arriba")
ok(_vecinas("El programa de la imagen imprime 17", "Analiza el fragmento y elige la salida") == 1,
   "ambas hablan de código: la de arriba (enunciado y luego su imagen)")
qs_marca = [{"num": 1, "type": "essay", "data": {"stem": "x", "_comparte_imagen": False}}]
imagenes.asignar_imagenes(qs_marca, None)
ok("_comparte_imagen" not in qs_marca[0]["data"], "la marca interna no llega al editor ni al XML (aunque no haya imágenes)")
ok(imagenes._empieza(imagenes._normalizar("Rellenar el cuadro con la función que coreponda"),
                     imagenes._normalizar("Rellenar el cuadro con la función que corresponda")),
   "el enunciado se ubica aunque la IA haya corregido una falta del documento")
ok(not imagenes._empieza(imagenes._normalizar("Qué imprime el siguiente código en Python"),
                         imagenes._normalizar("Qué imprime el siguiente código en JavaScript")),
   "…pero no confunde dos enunciados que solo se parecen")
# Preguntas encadenadas sobre la misma imagen ("15. ¿Cuántos errores tiene el
# código? / 6 / Escribe cuáles son los errores"): las dos llevan la imagen.
_IM = {"name": "pregunta1-1.png", "mime": "image/png", "b64": "iVBORw0KGgo="}
def _cadena(stems, flags, inicios=None):
    qs_c = [{"num": n, "type": "essay", "data": {"stem": st}} for n, st in enumerate(stems, 1)]
    qs_c[0]["data"]["images"] = [dict(_IM)]
    for q, f in zip(qs_c, flags):
        if f is not None:
            q["data"]["_comparte_imagen"] = f
    imagenes._compartir(qs_c, inicios or list(range(0, 3 * len(stems), 3)))
    return [[im["name"] for im in q["data"].get("images", [])] for q in qs_c]
ok(_cadena(["¿Cuántos errores tiene el código?", "Escribe cuáles son los errores", "¿Qué es una lista?"], [True, True, False])
   == [["pregunta1-1.png"], ["pregunta2-1.png"], []], "la IA marca la 2.ª: recibe la misma imagen; la 3.ª no")
ok(_cadena(["¿Cuántos errores tiene el código?", "¿Qué es una variable?"], [True, False]) == [["pregunta1-1.png"], []],
   "la IA dice que no es la misma (comparte_imagen_anterior=false): no la recibe")
ok(_cadena(["¿Qué imprime?", "Corrige el código para que imprima 10"], [None, None]) == [["pregunta1-1.png"], ["pregunta2-1.png"]],
   "sin marca de la IA: «el código» a pocas líneas la comparte")
ok(_cadena(["¿Qué imprime?", "¿Qué es un código fuente?"], [None, None]) == [["pregunta1-1.png"], []],
   "…pero «un código» (en general) no")
ok(_cadena(["¿Qué imprime?", "Corrige el código"], [None, None], inicios=[0, 30]) == [["pregunta1-1.png"], []],
   "…ni si la pregunta empieza lejos")
ok(sum(map(bool, _cadena(["a el código"] * 6, [True] * 6))) == 1 + imagenes._MAX_CADENA,
   f"como mucho {imagenes._MAX_CADENA} preguntas seguidas comparten una imagen")
if real:
    # La IA a veces omite «17. Del siguiente código…» (solo tiene una imagen
    # debajo): se simula quitándola del golden. La pregunta se ofrece para
    # rescatar, con su imagen y su lugar.
    g = json.loads((ROOT / "samples" / "golden" / "real_parcial_1_computacion.expected.json").read_text(encoding="utf-8"))
    qs_o = [{"num": i, "type": q["type"], "data": {"stem": q.get("stem") or q.get("text") or ""}}
            for i, q in enumerate(g["questions"], 1)]
    quitada = next(q for q in qs_o if q["data"]["stem"].startswith("Del siguiente código"))
    qs_o.remove(quitada)
    omitidas = []
    imagenes.asignar_imagenes(qs_o, imagenes.extraer_imagenes_pdf(real.read_bytes()), omitidas)
    o = omitidas[0] if len(omitidas) == 1 else {}
    ok(o.get("preview", "").startswith("Del siguiente código cual seria el resultado") and o.get("despues_de") == quitada["num"] - 1
       and len(o["recoverable_data"]["images"]) == 1 and o["type"] == "essay",
       f"pregunta con imagen que la IA omitió: se ofrece para rescatar en su lugar ({[x.get('preview', '')[:40] for x in omitidas]})")
    ok(not any(q["data"].get("images") and q["num"] in (quitada["num"] - 1, quitada["num"] + 1) for q in qs_o),
       "…y su imagen no se pega a la de arriba ni a la de abajo")
escaneado = ROOT / "samples" / "synthetic" / "s06_escaneado_sin_texto.pdf"
if escaneado.exists():
    ok(imagenes.extraer_imagenes_pdf(escaneado.read_bytes()).imagenes == [], "PDF escaneado: la hoja entera no se toma como imagen de una pregunta")

print("Código transcrito de una imagen ya adjunta: no se repite en el enunciado")
_CODIGO_STEM = 'a = 1 while a<=5: print(a) a+=1 print("Fin") ¿Cuántos errores tiene el código?'
ok(imagenes._sin_prefijo_transcrito(_CODIGO_STEM, "15. ¿Cuántos errores tiene el código?") == "¿Cuántos errores tiene el código?",
   "quita el código transcrito delante de la pregunta real del documento")
ok(imagenes._sin_prefijo_transcrito("¿Cuántos errores tiene el código?", "15. ¿Cuántos errores tiene el código?") is None,
   "…pero no toca un enunciado que ya viene limpio (nada que quitar)")
ok(imagenes._sin_prefijo_transcrito("a = 1 ¿Qué imprime este programa?", "9. ¿Cuántos errores tiene el código?") is None,
   "…ni si la línea del documento no calza con el final del enunciado (mejor no arriesgarse)")

# _quitar_transcripciones_redundantes: solo actúa en la pregunta que de
# verdad terminó con una imagen adjunta; la que se quedó sin ninguna
# conserva el código transcrito completo (es su única red de seguridad).
qs_transcrito = [{"num": 1, "type": "essay", "data": {"stem": _CODIGO_STEM, "images": [
                     {"name": "pregunta1-1.png", "mime": "image/png", "b64": "iVBORw0KGgo="}]}},
                  {"num": 2, "type": "essay", "data": {"stem": _CODIGO_STEM}}]
lineas_transcrito = [imagenes.Linea((1, 10.0), "15. ¿Cuántos errores tiene el código?"),
                     imagenes.Linea((1, 5.0), "16. ¿Cuántos errores tiene el código?")]
imagenes._quitar_transcripciones_redundantes(qs_transcrito, lineas_transcrito, [0, 1])
ok(qs_transcrito[0]["data"]["stem"] == "¿Cuántos errores tiene el código?",
   "con la imagen ya adjunta, el enunciado se queda solo con la pregunta real")
ok(qs_transcrito[1]["data"]["stem"] == _CODIGO_STEM,
   "sin imagen asignada, el código transcrito se conserva tal cual (red de seguridad)")

# De punta a punta con asignar_imagenes(): la imagen llega por la vía
# normal (mismo renglón que su pregunta) y el mismo paso limpia el
# enunciado, sin que el llamador tenga que hacer nada aparte.
_img_1x1 = Image.new("RGB", (10, 10), "white")
q_e2e = [{"num": 1, "type": "essay", "data": {"stem": _CODIGO_STEM}}]
ub_e2e = imagenes.Ubicaciones(
    lineas=[imagenes.Linea((1, 100.0), "15. ¿Cuántos errores tiene el código?")],
    imagenes=[imagenes.ImagenUbicada(imagen=_img_1x1, inicio=(1, 100.0), fin=(1, 100.0))])
imagenes.asignar_imagenes(q_e2e, ub_e2e)
ok(bool(q_e2e[0]["data"].get("images")) and q_e2e[0]["data"]["stem"] == "¿Cuántos errores tiene el código?",
   "de punta a punta (asignar_imagenes): imagen asignada y código transcrito quitado del enunciado")

print("Preguntas omitidas por número: detectarlas y pedirle a la IA solo esas")
if real:
    g = json.loads((ROOT / "samples" / "golden" / "real_parcial_1_computacion.expected.json").read_text(encoding="utf-8"))
    ub_real = imagenes.extraer_imagenes_pdf(real.read_bytes())

    def _con_options(q):
        opts = q.get("options")
        data = {"stem": q.get("stem") or q.get("text") or ""}
        if isinstance(opts, list):
            data["options"] = {chr(97 + i): o for i, o in enumerate(opts)}
        return data
    qs_num = [{"num": i, "type": q["type"], "data": _con_options(q)} for i, q in enumerate(g["questions"], 1)]

    # «22. Del siguiente código…» SÍ tiene su propio número como texto en
    # el PDF (a diferencia de otras preguntas de este mismo documento, que
    # no lo traen extraíble) y no depende de ninguna imagen huérfana — un
    # caso distinto al de arriba. Se quita para simular que la IA la omitió.
    # El enunciado del golden trae, además, el código que la IA transcribió
    # de la imagen ("(a = 1, while a<=5…)"); el texto PLANO del PDF (lo que
    # el detector puede leer) es solo el principio de esa misma frase.
    quitada = next(q for q in qs_num if q["data"]["stem"].startswith("Del siguiente código"))
    idx = qs_num.index(quitada)
    qs_num.remove(quitada)
    candidatas = imagenes.candidatas_omitidas_numeradas(qs_num, ub_real)
    ok(len(candidatas) == 1 and quitada["data"]["stem"].startswith(candidatas[0]["texto"])
       and candidatas[0]["despues_de"] == qs_num[idx - 1]["num"],
       f"pregunta numerada omitida (sin imagen): se detecta con su lugar correcto ({candidatas})")

    # La opción "2. Entero (int)" de la primera pregunta (este documento
    # numera esa opción igual que una pregunta) NO debe confundirse con una
    # pregunta nueva — es el caso real que motivó este chequeo.
    ok(not any("entero" in c["texto"].lower() and len(c["texto"]) < 20 for c in candidatas),
       "una opción numerada igual que otra pregunta no se confunde con una pregunta omitida")

    # pipeline._completar_omitidas: la inserta en su lugar con la respuesta
    # que traiga la IA, sin tocar nada más (mismo "orden" relativo).
    payload_num = {"es_examen": True, "preguntas": [
        {"orden": i, "tipo": q["type"], "enunciado": q["data"]["stem"], "opciones": [
            {"letra_original": k, "texto": v, "correcta": False} for k, v in (q["data"].get("options") or {}).items()],
         "items_izquierda": [], "items_derecha": [], "parejas": [], "huecos": [], "clave_texto": "",
         "respuesta_texto": "", "retroalimentacion": "", "respuesta_marcada": True, "origen_tabla": False,
         "pagina": 1, "confianza": "alta"}
        for i, q in enumerate(qs_num, 1)
    ]}
    _pedido = {}
    def _falso_extract_missing(fragmentos, page_images=None, on_retry=None):
        _pedido["fragmentos"] = fragmentos
        return [{"orden": 1, "tipo": "essay", "enunciado": fragmentos[0], "opciones": [],
                 "items_izquierda": [], "items_derecha": [], "parejas": [], "huecos": [], "clave_texto": "",
                 "respuesta_texto": "", "retroalimentacion": "", "respuesta_marcada": True, "origen_tabla": False,
                 "pagina": 6, "confianza": "alta"}]
    pipeline.extract_missing = _falso_extract_missing
    completo = pipeline._completar_omitidas(json.loads(json.dumps(payload_num)), ub_real, [], None)
    ok(len(_pedido.get("fragmentos") or []) == 1 and quitada["data"]["stem"].startswith(_pedido["fragmentos"][0]),
       "se le pide a la IA SOLO la pregunta detectada, no las demás")
    ok(len(completo["preguntas"]) == len(qs_num) + 1, "la pregunta recuperada se agrega a las que ya había")
    en_orden = sorted(completo["preguntas"], key=lambda p: p["orden"])
    pos = next(i for i, p in enumerate(en_orden) if p["enunciado"].startswith("Del siguiente código"))
    ok(en_orden[pos - 1]["enunciado"] == qs_num[idx - 1]["data"]["stem"]
       and en_orden[pos + 1]["enunciado"] == qs_num[idx]["data"]["stem"],
       "queda insertada en su lugar, entre sus dos vecinas originales del documento")

    # Con muchas "candidatas" (documento donde el detector se confunde con
    # opciones u otra columna), no se arriesga ninguna llamada de más.
    _pedido.clear()
    lineas_falsas = [imagenes.Linea((1, float(i)), f"{i}. Pregunta inventada número {i} para la prueba") for i in range(1, 10)]
    ub_vacio = imagenes.Ubicaciones(lineas=lineas_falsas, imagenes=[])
    pipeline._completar_omitidas(json.loads(json.dumps(payload_num)), ub_vacio, [], None)
    ok(not _pedido, "con demasiadas candidatas (>3), no se pide nada — se desiste, como si no existiera esta mejora")

    # Si la llamada de la IA no ayuda (falla o no devuelve nada), la
    # conversión sigue exactamente igual que sin este mecanismo.
    pipeline.extract_missing = lambda *a, **k: []
    sin_cambios = pipeline._completar_omitidas(json.loads(json.dumps(payload_num)), ub_real, [], None)
    ok(len(sin_cambios["preguntas"]) == len(qs_num), "si la IA no puede completarla, la conversión sigue igual que antes")


print("Fórmulas en PDF")
class _Pagina:
    def __init__(self, fuentes):
        self.chars = [{"fontname": f} for f in fuentes]
ok(extractor.pagina_con_formulas(_Pagina(["ABCDEE+CambriaMath"] * 5)), "fuente Cambria Math (Word): se envía como imagen a la IA")
ok(extractor.pagina_con_formulas(_Pagina(["CMMI10"] * 3)), "fuente de LaTeX (CMMI): se envía como imagen")
ok(not extractor.pagina_con_formulas(_Pagina(["Symbol"] * 20 + ["Calibri"] * 50)), "viñetas en Symbol: no cuentan como fórmula")

print("Escribir retroalimentación con IA (Gemini simulado)")
from fastapi import HTTPException  # noqa: E402
_enviado = {}
class _Resp:
    text = '"Retroalimentación: **Al sumar** se obtiene \\(\\frac{4}{4}\\) = 1."'
def _falso(body, n, parse, timeout, **_):
    _enviado["body"] = body
    return parse(_Resp())
_original = formatter._generate_with_retries
formatter._generate_with_retries = _falso
try:
    pq = {"type": "multichoice", "data": {"stem": "¿Cuánto vale \\(\\frac{3}{4}+\\frac{1}{4}\\)?",
          "options": {"A": "\\(\\frac{1}{2}\\)", "B": "1"},
          "images": [{"mime": "image/png", "b64": "iVBORw0KGgo="}, {"mime": "text/html", "b64": "PGI+"}]}}
    fb = ayuda_ia.generar(pq, {"type": "multichoice", "answer": "1"})
    ok(fb == "Al sumar se obtiene \\(\\frac{4}{4}\\) = 1.", f"texto limpio, sin prefijo ni markdown, con la fórmula intacta ({fb!r})")
    partes = _enviado["body"]["contents"][0]["parts"]
    ok("Respuesta correcta: 1" in partes[0]["text"] and "B) 1" in partes[0]["text"], "la IA recibe opciones y respuesta correcta")
    ok(len(partes) == 2, "solo se envían imágenes PNG/JPEG válidas")
    ok("responseSchema" not in _enviado["body"]["generationConfig"], "salida en texto plano (en JSON la IA rompía «\\frac»)")
    texto = ayuda_ia.texto_pregunta({"type": "matching", "data": {"stem": "Une", "col_a": {"1": "Delfín"}, "col_b": {"a": "Mamífero"}}}, {"pairs": {"1": "a"}})
    ok("Delfín → Mamífero" in texto, "emparejamiento: se envían las parejas correctas")
    ok("(no indicada)" in ayuda_ia.texto_pregunta({"type": "truefalse", "data": {"stem": "X"}}, {"answer": "SIN_RESPUESTA"}),
       "sin respuesta marcada: la IA no debe afirmar cuál es")
    for mala, motivo in [({"type": "otro", "data": {"stem": "x"}}, "tipo desconocido"), ({"type": "essay", "data": {"stem": " "}}, "sin enunciado")]:
        try:
            ayuda_ia.generar(mala, None)
            ok(False, f"{motivo}: se rechaza")
        except HTTPException as e:
            ok(e.status_code == 422, f"{motivo}: se rechaza sin llamar a la IA")
finally:
    formatter._generate_with_retries = _original

print("Mejorar redacción (Gemini simulado)")
_respuesta_ia = {}
class _RespE:
    @property
    def text(self):
        return _respuesta_ia["t"]
def _falso_e(body, n, parse, timeout, **_):
    _enviado["body"] = body
    return parse(_RespE())
formatter._generate_with_retries = _falso_e
try:
    pe = {"type": "multichoice", "data": {"stem": "que imprime el siguiente codigo\nx = 5\nprint(x*2)", "options": {"A": "10", "B": "52"}}}
    _respuesta_ia["t"] = "Enunciado: ¿Qué imprime el siguiente código?\nx = 5\nprint(x*2)"
    r = ayuda_ia.mejorar_enunciado(pe)
    ok(r == {"enunciado": "¿Qué imprime el siguiente código?\nx = 5\nprint(x*2)", "cambio": True}, "corrige tildes y signos, sin el prefijo «Enunciado:»")
    ok("A) 10" in _enviado["body"]["contents"][0]["parts"][0]["text"], "las opciones van como contexto")
    for malo, motivo in [("¿Qué imprime el siguiente código?\nx = 5\nprint(x * 2)", "código"),
                         ("¿Qué imprime el siguiente código?\nx = 6\nprint(x*2)", "números")]:
        _respuesta_ia["t"] = malo
        try:
            ayuda_ia.mejorar_enunciado(pe)
            ok(False, f"si la IA cambia {motivo}: no se aplica")
        except HTTPException as e:
            ok(e.status_code == 422 and motivo in e.detail, f"si la IA cambia {motivo}: no se aplica ({e.detail[:60]}…)")
    _respuesta_ia["t"] = "¿Cuánto es \\(\\frac{1}{3}\\)?"
    try:
        ayuda_ia.mejorar_enunciado({"type": "essay", "data": {"stem": "cuanto es \\(\\frac{1}{2}\\)"}})
        ok(False, "fórmula cambiada: no se aplica")
    except HTTPException as e:
        ok("fórmulas" in e.detail, "fórmula cambiada: no se aplica")
    _respuesta_ia["t"] = "Explique qué es una variable."
    ok(ayuda_ia.mejorar_enunciado({"type": "essay", "data": {"stem": "Explique qué es una variable."}})["cambio"] is False,
       "si ya estaba bien, se avisa que no hubo cambios")
    try:
        ayuda_ia.mejorar_enunciado({"type": "cloze", "data": {"text": "El [A] es…"}})
        ok(False, "completar: no aplica")
    except HTTPException as e:
        ok(e.status_code == 422, "preguntas de completar: se editan en su constructor")
finally:
    formatter._generate_with_retries = _original

print("Mejorar redacción: cambios de significado que 'el código comprueba'")
casos_significado = [
    ("print(2**3)", "print(2*3)", "operadores", "exponente convertido en multiplicación"),
    ("¿Cuál NO es una fruta?", "¿Cuál es una fruta?", "negaciones", "se quita el NO y cambia lo que se pregunta"),
    ("x == 5", "x = 5", "operadores", "igualdad convertida en asignación"),
    ("3 < 5", "3 > 5", "operadores", "operador de comparación invertido"),
    ("x++", "x--", "operadores", "incremento convertido en decremento"),
    ("¿Qué imprime?\nif x > 0:\n    print(x)", "¿Qué imprime?\nif x > 0:\nprint(x)", "código", "sangría de Python quitada"),
]
for original, nuevo, motivo, etiqueta in casos_significado:
    ok(motivo in ayuda_ia.cambios_indebidos(original, nuevo), f"{etiqueta}: se detecta y no se aplica")
for original, nuevo, etiqueta in [
    ("cuanto es 1+1", "¿Cuánto es 1+1?", "signos de interrogación agregados"),
    ("el metodo es rapido", "El método es rápido", "tildes agregadas"),
]:
    ok(ayuda_ia.cambios_indebidos(original, nuevo) == [], f"corrección legítima ({etiqueta}) sí se aplica")

print("LaTeX dañado por el JSON de la IA")
ok(schema_adapter._line("\\(\x0crac{3}{4}\\) y \\(\x08eta + \theta\\)") == "\\(\\frac{3}{4}\\) y \\(\\beta + \\theta\\)",
   "\\f, \\b y \\t convertidos en control se reparan dentro de la fórmula")
ok(schema_adapter._text("uno\ndos\tfin") == "uno\ndos\tfin", "fuera de una fórmula, saltos y tabulaciones reales no se tocan")

print()
print("TODO OK" if not fallas else f"{fallas} FALLA(S)")
sys.exit(1 if fallas else 0)
