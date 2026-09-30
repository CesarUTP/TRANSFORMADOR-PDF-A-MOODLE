"""
test_v18_extraccion.py — regresiones de la versión 1.8 en la lectura del
documento: marcas de respuesta (color, resaltado, Verdadero/Falso), imágenes,
Word (.docx), .txt y el adaptador del modo JSON.

    PYTHONUTF8=1 backend/venv/bin/python dev/test_v18_extraccion.py

No llama a Gemini, no toca el historial ni la clave guardada. Los PDF y Word
de prueba se generan en memoria.
"""

import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import pdfplumber  # noqa: E402
import pdfplumber.display  # noqa: E402
from PIL import Image  # noqa: E402
from reportlab.lib.utils import ImageReader  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

import extractor  # noqa: E402
import extractor_docx  # noqa: E402
import imagenes  # noqa: E402
import mark_resolver  # noqa: E402
import parser as parser_legacy  # noqa: E402
import schema_adapter  # noqa: E402
from validator import partition_questions  # noqa: E402

fallas = 0


def ok(cond, msg):
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


# ── 1. Verdadero/Falso: «f(x)» y «v[x]» no son marcas ──────────────────────
print("Verdadero/Falso: f(x) y v[x] no son una casilla marcada")
tf = mark_resolver._tf_mark
ok(tf(["Si f(x)=2x entonces la derivada es 2"]) is None, "«f(x)=2x» no devuelve Falso")
ok(tf(["El arreglo v[x] tiene n elementos"]) is None, "«v[x]» no devuelve Verdadero")
ok(tf(["Sea f(x) = 3. (X) Verdadero  ( ) Falso"]) == "Verdadero", "la casilla real sigue leyéndose junto a una f(x)")
ok(tf(["( X ) Verdadero   (   ) Falso"]) == "Verdadero", "«( X ) Verdadero ( ) Falso»")
ok(tf(["Verdadero (X)   Falso ( )"]) == "Verdadero", "casilla después de la palabra")
ok(tf(["(  ) Verdadero  (X) Falso"]) == "Falso", "«( ) Verdadero (X) Falso» sigue dando Falso")
ok(tf(["( ) V   (x) F"]) == "Falso", "«( ) V (x) F»")
ok(tf(["[x] Falso"]) == "Falso", "«[x] Falso»")
ok(tf(["(X) por lo tanto es Verdadero"]) is None, "casilla y palabra separadas por texto: no se emparejan")
qs_tf = [{"num": 1, "type": "truefalse", "data": {"stem": "Si la función es f(x)=2x entonces su derivada vale dos"}}]
key_tf = {1: {"type": "truefalse", "answer": "SIN_RESPUESTA"}}
n = mark_resolver.resolve_tf_marks(qs_tf, key_tf, ["Si la función es f(x)=2x entonces su derivada vale dos"])
ok(n == 0 and key_tf[1]["answer"] == "SIN_RESPUESTA", "resolve_tf_marks no escribe una respuesta inventada en la clave")

# ── 2. Imágenes de PDF ─────────────────────────────────────────────────────
print("Imágenes de PDF: logo repetido vs capturas distintas en el mismo lugar")


def _foto(color, n=300, alto=200):
    """Imagen con detalle (no un color plano) para que cada una tenga datos propios."""
    im = Image.new("RGB", (n, alto), color)
    for i in range(0, n, 7):
        for j in range(0, alto, 7):
            im.putpixel((i, j), ((i * 3 + color[0]) % 256, (j * 5 + color[1]) % 256, color[2]))
    return im


def pdf_paginas(paginas, tam=(612, 792)):
    """paginas: lista de listas de (PIL.Image, x, y, ancho, alto) en puntos."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=tam)
    for k, imgs in enumerate(paginas, 1):
        c.drawString(72, tam[1] - 60, f"{k}. Pregunta de la pagina {k} con texto suficiente para ubicarla")
        for im, x, y, w, h in imgs:
            c.drawImage(ImageReader(im), x, y, w, h)
        c.showPage()
    c.save()
    return buf.getvalue()


rojo, azul, verde = _foto((200, 0, 0)), _foto((0, 0, 200)), _foto((0, 120, 0))
distintas = pdf_paginas([[(rojo, 72, 400, 300, 200)], [(azul, 72, 400, 300, 200)], [(verde, 72, 400, 300, 200)]])
ub = imagenes.extraer_imagenes_pdf(distintas)
ok(len(ub.imagenes) == 3, f"3 capturas distintas en el mismo lugar y tamaño se conservan (hay {len(ub.imagenes)})")
logo = _foto((10, 10, 10), 120, 60)
con_logo = pdf_paginas([[(logo, 400, 700, 100, 50), (rojo, 72, 300, 300, 200)],
                        [(logo, 400, 700, 100, 50), (azul, 72, 300, 300, 200)]])
ub = imagenes.extraer_imagenes_pdf(con_logo)
ok(len(ub.imagenes) == 2, f"el logo idéntico repetido en cada página se descarta (quedan {len(ub.imagenes)} de 4)")

print("Imágenes de PDF: una sola renderización por página")
llamadas = []
_orig = pdfplumber.display.get_page_image


def _espia(stream, path, page_ix, resolution, password, antialias=False):
    llamadas.append((page_ix, resolution))
    return _orig(stream, path, page_ix, resolution, password, antialias)


pdfplumber.display.get_page_image = _espia
try:
    tres = pdf_paginas([[(rojo, 72, 500, 200, 120), (azul, 72, 300, 200, 120), (verde, 72, 100, 200, 120)]])
    ub = imagenes.extraer_imagenes_pdf(tres)
    ok(len(ub.imagenes) == 3 and len(llamadas) == 1,
       f"3 imágenes en una página: {len(llamadas)} render de página (antes 3)")
    recorte = ub.imagenes[0].imagen
    ok(abs(recorte.width - 200 * 150 / 72) <= 2 and abs(recorte.height - 120 * 150 / 72) <= 2,
       f"el recorte conserva la escala de 150 DPI ({recorte.size})")

    llamadas.clear()
    gigante = pdf_paginas([[(rojo, 100, 100, 300, 200)]], tam=(5000, 5000))
    ub = imagenes.extraer_imagenes_pdf(gigante)
    pixeles = max((5000 * res / 72) ** 2 for _, res in llamadas) if llamadas else 0
    ok(len(ub.imagenes) == 1 and pixeles <= extractor.MAX_PIXELES_RENDER * 1.02,
       f"página de 5000 pt con imagen pequeña: se renderiza a ≤ {extractor.MAX_PIXELES_RENDER // 1_000_000} MP ({pixeles / 1e6:.1f} MP)")
finally:
    pdfplumber.display.get_page_image = _orig

print("Imágenes para la IA: un logo repetido no gasta el tope de páginas")
n_pag = extractor.MAX_IMAGE_PAGES + 4
paginas = []
for k in range(n_pag):
    extra = [(_foto((40 * (k % 5), 90, 30 + k)), 72, 300, 250, 150)] if k >= n_pag - 2 else []
    paginas.append([(logo, 450, 720, 90, 45)] + extra)
_, imgs = extractor.extract_text_and_images_from_pdf(pdf_paginas(paginas))
ok(len(imgs) == 2, f"solo se renderizan las 2 páginas con imagen propia, no las {extractor.MAX_IMAGE_PAGES} del logo (hay {len(imgs)})")
_, imgs = extractor.extract_text_and_images_from_pdf(pdf_paginas([[(rojo, 72, 300, 250, 150)]]))
ok(len(imgs) == 1, "una página con una imagen sí se renderiza")
_, imgs = extractor.extract_text_and_images_from_pdf(pdf_paginas([[(_foto((1, 2, 3), 20, 10), 72, 300, 20, 10)]]))
ok(len(imgs) == 0, "un ícono diminuto no cuenta como imagen")

# ── 3. Marcas de color ─────────────────────────────────────────────────────
print("Color en PDF: CMYK y gris")
ok(extractor._char_has_color({"text": "A", "non_stroking_color": (0, 1, 1, 0)}), "rojo CMYK (0,1,1,0) es color")
ok(extractor._color_name((0, 1, 1, 0)) == "rojo", "el rojo CMYK se llama «rojo»")
ok(not extractor._char_has_color({"text": "A", "non_stroking_color": (0, 0, 0, 1)}), "negro CMYK no es color")
ok(not extractor._char_has_color({"text": "A", "non_stroking_color": (0.75, 0.68, 0.67, 0.9)}), "negro «rico» CMYK no es color")
ok(not extractor._char_has_color({"text": "A", "non_stroking_color": (0.5,)}), "gris de un valor no es color")
ok(not extractor._char_has_color({"text": "A", "non_stroking_color": (0, 0, 0)}), "negro RGB no es color")
ok(extractor._char_has_color({"text": "A", "non_stroking_color": (1, 0, 0)}), "rojo RGB sigue siendo color")
ok(extractor._is_marker_fill((0, 0, 1, 0)), "relleno amarillo CMYK es de marcador")
ok(not extractor._is_marker_fill((0.5,)), "relleno gris no es de marcador")


def pdf_cmyk():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 792))
    c.setFillColorCMYK(0, 0, 0, 1)
    c.drawString(72, 700, "1. Cual es la capital de Francia hoy en dia")
    c.drawString(72, 680, "a) Madrid")
    c.setFillColorCMYK(0, 1, 1, 0)
    c.drawString(72, 660, "b) Paris")
    c.setFillColorCMYK(0, 0, 0, 1)
    c.drawString(72, 640, "c) Roma")
    c.showPage()
    c.save()
    return buf.getvalue()


raw_cmyk = pdf_cmyk()
ok(extractor.get_colored_page_numbers(raw_cmyk) == [1], "una respuesta en rojo CMYK marca la página como coloreada")
ok("⟦rojo⟧b) Paris⟦/rojo⟧" in "\n".join(extractor.extract_pages_text_enriched(raw_cmyk)),
   "el texto enriquecido envuelve la respuesta CMYK en ⟦rojo⟧")

print("Marcas: la clave explícita del documento no se pisa con marcas espurias")


def _mc(num, stem, opciones):
    return {"num": num, "type": "multichoice", "data": {"stem": stem, "options": dict(zip("ABC", opciones))}}


preguntas = [_mc(k, f"Pregunta numero {k} sobre un tema distinto cualquiera", [f"opcion uno {k}", f"opcion dos {k}", f"opcion tres {k}"])
             for k in (1, 2, 3, 4)]
pagina = "\n".join(
    f"{k}. Pregunta numero {k} sobre un tema distinto cualquiera\n"
    f"a) opcion uno {k}\nb) ⟦negrita⟧opcion dos {k}⟦/negrita⟧\nc) opcion tres {k}" for k in (1, 2, 3, 4))
clave_doc = {k: {"type": "multichoice", "answer": f"opcion uno {k}", "from_key": True} for k in (1, 2, 3, 4)}
r = mark_resolver.resolve_answer_marks(preguntas, clave_doc, [pagina])
ok(all(clave_doc[k]["answer"] == f"opcion uno {k}" for k in clave_doc) and r["applied"] == 0,
   "con clave explícita, las negritas de la opción B no la sobrescriben")
sin_clave = {k: {"type": "multichoice", "answer": f"opcion uno {k}"} for k in (1, 2, 3, 4)}
r = mark_resolver.resolve_answer_marks(preguntas, sin_clave, [pagina])
ok(all(sin_clave[k]["answer"] == f"opcion dos {k}" for k in sin_clave) and r["applied"] == 4,
   "sin clave del documento (respuesta de la IA), la marca sigue mandando")
mixta = {1: {"type": "multichoice", "answer": "opcion uno 1", "from_key": True},
         2: {"type": "multichoice", "answer": "opcion uno 2"}, 3: {"type": "multichoice", "answer": "opcion uno 3"},
         4: {"type": "multichoice", "answer": "opcion uno 4"}}
mark_resolver.resolve_answer_marks(preguntas, mixta, [pagina])
ok(mixta[1]["answer"] == "opcion uno 1" and mixta[2]["answer"] == "opcion dos 2",
   "clave parcial: la pregunta con clave se respeta, las demás leen la marca")

payload = {"es_examen": True, "preguntas": [
    {"orden": 1, "tipo": "multichoice", "enunciado": "Capital de Francia", "clave_texto": "b", "respuesta_marcada": True,
     "opciones": [{"letra_original": "a", "texto": "Madrid", "correcta": False}, {"letra_original": "b", "texto": "París", "correcta": True}]},
    {"orden": 2, "tipo": "multichoice", "enunciado": "Capital de Italia", "respuesta_marcada": True,
     "opciones": [{"letra_original": "a", "texto": "Roma", "correcta": True}, {"letra_original": "b", "texto": "Milán", "correcta": False}]},
]}
_, clave_json = schema_adapter.adapt(payload)
ok(clave_json[1].get("from_key") is True and not clave_json[2].get("from_key"),
   "el adaptador marca como «from_key» solo la respuesta que salió de la clave del documento")

print("Marcas: etiqueta que cruza un salto de línea")
ln = mark_resolver._Line("⟦rojo⟧b) primera parte")
ok(ln.colors == "rojo", "etiqueta abierta sin cerrar cuenta como color en su línea")

# ── 4. Word (.docx) ────────────────────────────────────────────────────────
_W = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
      'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
      'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
      'xmlns:v="urn:schemas-microsoft-com:vml" '
      'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"')


def _run(t, props=""):
    return f'<w:r><w:rPr>{props}</w:rPr><w:t xml:space="preserve">{t}</w:t></w:r>'


def _p(contenido):
    return f"<w:p>{contenido}</w:p>"


def word(cuerpo, extra=None, estilos=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", f'<w:document {_W}><w:body>{cuerpo}</w:body></w:document>')
        if estilos:
            z.writestr("word/styles.xml", estilos)
        for nombre, datos in (extra or {}).items():
            z.writestr(nombre, datos)
    return buf.getvalue()


print("Word: sombreado")
gris = '<w:shd w:val="clear" w:color="auto" w:fill="D9D9D9"/>'
amar = '<w:shd w:val="clear" w:color="auto" w:fill="FFFF00"/>'
d = extractor_docx.leer_docx(word(_p(_run("codigo gris", gris)) + _p(_run("marcada amarilla", amar))))
ok("⟦" not in d.texto_enriquecido.split("\n")[0], "el sombreado gris (estilo de código) no es una marca")
ok("⟦resaltado⟧marcada amarilla⟦/resaltado⟧" in d.texto_enriquecido, "el sombreado amarillo sí es resaltado")
estilo_codigo = ('<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                 '<w:style w:type="paragraph" w:styleId="Codigo"><w:rPr><w:shd w:val="clear" w:fill="F2F2F2"/></w:rPr></w:style></w:styles>')
d = extractor_docx.leer_docx(word('<w:p><w:pPr><w:pStyle w:val="Codigo"/></w:pPr>' + _run("print(1)") + "</w:p>", estilos=estilo_codigo))
ok("⟦" not in d.texto_enriquecido, "un estilo de párrafo de código con fondo gris no marca el texto")

print("Word: salto suave dentro de una opción coloreada")
roja = '<w:color w:val="FF0000"/>'
salto = ('<w:r><w:rPr>' + roja + '</w:rPr><w:t>primera parte</w:t><w:br/><w:t>segunda parte</w:t></w:r>')
d = extractor_docx.leer_docx(word(_p(_run("Pregunta uno de prueba")) + _p(salto) + _p(_run("otra opcion"))))
ok("⟦rojo⟧primera parte⟦/rojo⟧\n⟦rojo⟧segunda parte⟦/rojo⟧" in d.texto_enriquecido, "cada línea lleva su etiqueta cerrada")
ok("primera parte\nsegunda parte" in d.texto_plano, "el texto plano conserva el salto sin marcas")
lineas = mark_resolver._lines([d.texto_enriquecido])
ok([l.colors for l in lineas if "parte" in l.plain] == ["rojo", "rojo"], "mark_resolver ve ambas líneas como rojas")

print("Word: símbolos, guion sin corte, cuadros de texto y AlternateContent")
sym = '<w:r><w:sym w:font="Wingdings" w:char="F0FC"/><w:t xml:space="preserve"> Roma</w:t></w:r>'
d = extractor_docx.leer_docx(word(_p(sym)))
ok(d.texto_plano.strip() == "✓ Roma", f"w:sym de Wingdings F0FC se lee como ✓ ({d.texto_plano.strip()!r})")
d = extractor_docx.leer_docx(word(_p('<w:r><w:sym w:font="Symbol" w:char="F0B7"/><w:t>viñeta</w:t></w:r>')))
ok(d.texto_plano.strip() == "viñeta", "un símbolo ilegible (viñeta de Symbol) no deja basura")
d = extractor_docx.leer_docx(word(_p('<w:r><w:t>Vale </w:t><w:noBreakHyphen/><w:t>5 grados</w:t></w:r>')))
ok(d.texto_plano.strip() == "Vale -5 grados", f"w:noBreakHyphen conserva el signo menos ({d.texto_plano.strip()!r})")

caja = '<w:txbxContent>' + _p(_run("Texto dentro del cuadro")) + '</w:txbxContent>'
choice = ('<w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing><wp:anchor><a:graphic><a:graphicData>'
          '<wps:wsp><wps:txbx>' + caja + '</wps:txbx></wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice>'
          '<mc:Fallback><w:pict><v:shape><v:textbox>' + caja + '</v:textbox></v:shape></w:pict></mc:Fallback>'
          '</mc:AlternateContent></w:r>')
d = extractor_docx.leer_docx(word(_p(_run("Antes ") + choice)))
ok(d.texto_plano.count("Texto dentro del cuadro") == 1, "cuadro de texto en AlternateContent: se lee una sola vez (sin duplicar Choice/Fallback)")
ok("Antes" in d.texto_plano, "el texto del párrafo que contiene el cuadro se conserva")
vml = '<w:r><w:pict><v:shape><v:textbox>' + caja + '</v:textbox></v:shape></w:pict></w:r>'
d = extractor_docx.leer_docx(word(_p(vml)))
ok("Texto dentro del cuadro" in d.texto_plano, "cuadro de texto VML directo")

print("Word: archivos dañados o con contraseña")
for etiqueta, contenido in (
    ("contenedor cifrado (OLE)", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 200),
    ("ZIP truncado", word(_p(_run("hola")))[:60]),
    ("XML mal formado", word("<w:p><w:r>")),
):
    try:
        extractor_docx.leer_docx(contenido)
        ok(False, f"{etiqueta}: se rechaza")
    except extractor_docx.DocxInvalido as e:
        ok(True, f"{etiqueta}: DocxInvalido con mensaje en español ({str(e)[:50]}…)")
    except Exception as e:  # noqa: BLE001
        ok(False, f"{etiqueta}: salió {type(e).__name__} en vez de DocxInvalido")
try:
    extractor_docx.leer_docx(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 200)
except extractor_docx.DocxInvalido as e:
    ok("contraseña" in str(e), "el mensaje del Word cifrado habla de la contraseña")

print("Word: imágenes grandes se guardan reducidas")
png = io.BytesIO()
Image.effect_noise((3000, 2000), 60).convert("RGB").save(png, "PNG")  # 6 MP
rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdImg" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/></Relationships>')
img_xml = ('<w:r><w:drawing><wp:inline><a:graphic><a:graphicData><pic:pic><pic:blipFill><a:blip r:embed="rIdImg"/>'
           '</pic:blipFill></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>')
d = extractor_docx.leer_docx(word(_p(_run("1. Pregunta con imagen")) + _p(img_xml),
                                  extra={"word/_rels/document.xml.rels": rels, "word/media/image1.png": png.getvalue()}))
im = d.ubicaciones.imagenes[0].imagen
ok(len(d.ubicaciones.imagenes) == 1 and im.width * im.height <= imagenes.MAX_PIXELES_GUARDADA,
   f"imagen de 6 MP guardada a {im.width * im.height / 1e6:.1f} MP")
ok(abs(im.width / im.height - 1.5) < 0.01, "conserva la proporción")
ac_img = ('<w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing><wp:inline><a:graphic><a:graphicData><pic:pic><pic:blipFill>'
          '<a:blip r:embed="rIdImg"/></pic:blipFill></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></mc:Choice>'
          '<mc:Fallback><w:pict><v:shape><v:imagedata r:id="rIdImg"/></v:shape></w:pict></mc:Fallback></mc:AlternateContent></w:r>')
d = extractor_docx.leer_docx(word(_p(_run("1. Pregunta con imagen")) + _p(ac_img),
                                  extra={"word/_rels/document.xml.rels": rels, "word/media/image1.png": png.getvalue()}))
ok(len(d.ubicaciones.imagenes) == 1, "imagen dentro de mc:AlternateContent: se lee una sola vez (Choice, no Fallback)")
chica = Image.new("RGB", (800, 600), (5, 5, 5))
ok(imagenes.reducir_imagen(chica) is chica, "una imagen ≤ 2 MP no se toca")

# ── 5. Imágenes: transparencia al guardar ──────────────────────────────────
print("Imágenes: la transparencia no se vuelve negro")
ruido = Image.effect_noise((700, 700), 80).convert("RGBA")
ruido.putalpha(255)
transparente = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
ruido.paste(transparente, (0, 0))
cod = imagenes.codificar(ruido)
ok(cod["ext"] == "jpg", "un PNG con transparencia de más de 350 KB se guarda como JPEG")
import base64  # noqa: E402
salida = Image.open(io.BytesIO(base64.b64decode(cod["b64"]))).convert("RGB")
r_, g_, b_ = salida.getpixel((20, 20))
ok(min(r_, g_, b_) > 235, f"lo transparente queda blanco, no negro ({(r_, g_, b_)})")

# ── 6. .txt ────────────────────────────────────────────────────────────────
print(".txt: codificaciones")
tx = extractor.extract_text_from_txt
ok(tx("¿Qué es «Moodle»? — Ñandú".encode("utf-8")) == "¿Qué es «Moodle»? — Ñandú", "UTF-8")
ok(tx("hola".encode("utf-8-sig")) == "hola", "UTF-8 con BOM: sin el carácter BOM")
ok(tx("¿Qué?\nñ".encode("utf-16")) == "¿Qué?\nñ", "UTF-16 con BOM: sin NUL")
ok(tx("“Comillas” – guión … fin".encode("cp1252")) == "“Comillas” – guión … fin", "Windows-1252: comillas y guiones tipográficos")
ok(tx(b"caf\xe9 \x81") == "café \x81", "bytes que ni cp1252 define: último recurso latin-1")

# ── 7. Adaptador del modo JSON ─────────────────────────────────────────────
print("Adaptador JSON: tipo desconocido, retroalimentación y LaTeX en cloze")
payload = {"es_examen": True, "preguntas": [
    {"orden": 1, "tipo": "essay", "enunciado": "Explica la fotosíntesis con tus palabras"},
    {"orden": 2, "tipo": "ordering", "enunciado": "Ordena los pasos del ciclo del agua correctamente"},
    {"orden": 3, "tipo": "essay", "enunciado": "Comenta el texto", "retroalimentacion": "x" * 3000},
]}
qs, clave = schema_adapter.adapt(payload)
ok(len(qs) == 3 and qs[1]["num"] == 2 and "error" in qs[1], "la pregunta de tipo desconocido se conserva con un error")
validas, omitidas = partition_questions(qs, clave)
ok(len(validas) == 2 and len(omitidas) == 1 and "Ordena los pasos" in omitidas[0]["preview"] and omitidas[0]["num"] == 2,
   "sale entre las omitidas, con su enunciado, en vez de desaparecer")
ok(len(qs[2]["data"]["feedback"]) == 3000, "una retroalimentación de 3000 caracteres ya no se corta a 2000")
qs, _ = schema_adapter.adapt({"preguntas": [{"orden": 1, "tipo": "essay", "enunciado": "e", "retroalimentacion": "y" * 6000}]})
ok(len(qs[0]["data"]["feedback"]) == schema_adapter.MAX_FEEDBACK == 5000, "solo se corta lo que el validador rechazaría (5000)")
cl = {"orden": 1, "tipo": "cloze", "enunciado": "Vale \\(\x0crac{1}{2}\\) en [A]", "respuesta_marcada": True,
      "huecos": [{"marcador": "A", "opciones": [{"texto": "medio", "correcta": True}, {"texto": "uno", "correcta": False}]}]}
qs, _ = schema_adapter.adapt({"preguntas": [cl]})
ok("\\frac{1}{2}" in qs[0]["data"]["text"], "el enunciado del cloze repara el LaTeX dañado por el JSON")

# ── 8. Modo texto (parser) ─────────────────────────────────────────────────
print("Modo texto: fila de clave sin respuesta")
k = parser_legacy.parse_answer_key("RESPUESTAS\n1 truefalse\n2 multichoice B\n3 truefalse Falso\n")
ok(k.get(1) == {"type": "truefalse", "answer": ""}, f"«1 truefalse» queda sin respuesta, no con la línea siguiente ({k.get(1)})")
ok(k.get(2, {}).get("answer") == "B" and k.get(3, {}).get("answer") == "Falso", "las filas vecinas se leen bien")

print()
print("TODO OK" if not fallas else f"{fallas} FALLA(S)")
sys.exit(1 if fallas else 0)
