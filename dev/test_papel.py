"""
test_papel.py — lo que el papel ganó en la 3.2: fórmulas dibujadas, cuadro de puntos, partes en hoja nueva y
tamaño de las imágenes, en el PDF y en el Word.

    PYTHONUTF8=1 backend/venv/bin/python dev/test_papel.py

Sin red ni Gemini; la base es temporal.
"""

import base64
import io
import logging
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

TMP = Path(tempfile.mkdtemp(prefix="conv papel "))
os.environ["HOME"] = str(TMP / "home")
os.environ["LOCALAPPDATA"] = str(TMP / "home" / "AppData")
(TMP / "datos" / "data").mkdir(parents=True)
import database  # noqa: E402

database.get_db_path = lambda: TMP / "datos" / "data" / "exams_history.db"  # ANTES de importar main

import docx  # noqa: E402
import pdfplumber  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

import exportar_docx  # noqa: E402
import exportar_pdf  # noqa: E402
import formulas  # noqa: E402
import latex_texto  # noqa: E402
import main  # noqa: E402
import seguridad  # noqa: E402
from plan_impreso import DatosExamen, SaltoPagina, TablaPuntos, construir_plan  # noqa: E402

logging.disable(logging.CRITICAL)
fallas = []


def ok(cond, texto):
    print(("  ok   " if cond else "  FALLA ") + texto)
    if not cond:
        fallas.append(texto)


def paginas_de(pdf: bytes):
    with pdfplumber.open(io.BytesIO(pdf)) as d:
        return [(p.extract_text() or "", [(im["width"], im["height"], im["x0"], im["x1"], p.width) for im in p.images]) for p in d.pages]


def texto(pdf: bytes) -> str:
    return "\n".join(t for t, _ in paginas_de(pdf))


def imagenes(pdf: bytes):
    return [im for _, ims in paginas_de(pdf) for im in ims]


# ── 1. Qué fórmulas se dibujan ──────────────────────────────────────────────
print("1. Fórmulas: cuáles se dibujan")
DIBUJADAS = [r"\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}", r"\begin{vmatrix} x & y \\ z & w \end{vmatrix}",
             r"f(x)=\begin{cases} x & x\ge 0 \\ -x & x<0 \end{cases}", r"\int_{0}^{\infty} e^{-x^2}\,dx",
             r"\lim_{x \to 0} \frac{\sin x}{x}", r"\sum_{i=1}^{n} i^2", r"\frac{x^2+1}{x-1}", r"\sqrt[3]{\frac{a+b}{c}}",
             r"\vec{v} = \hat{i} + 2\hat{j}", r"\binom{n}{k}", r"\overline{AB}"]
for f in DIBUJADAS:
    d = formulas.dibujar(f, 11.5, 400.0)
    ok(formulas.conviene_dibujar(f, latex_texto.latex_a_texto(f)) and d is not None and d.png[:8] == b"\x89PNG\r\n\x1a\n"
       and 0 < d.ancho <= 400 and d.alto > 0 and -0.01 <= d.bajo <= d.alto, f"se dibuja: {f}")
for f in (r"x^2 + \alpha \leq 3", r"\frac{1}{2}", r"\mathbb{R}", r"\sqrt{2}", r"a_1 + b_2"):
    ok(not formulas.conviene_dibujar(f, latex_texto.latex_a_texto(f)), f"sigue como texto: {f}")
for f in (r"\comandoinventado{3}", r"\frac{1}{", r"x^{", "", "x" * 2000):
    ok(formulas.dibujar(f, 11.5, 400.0) is None, f"no se adivina: {f[:30]!r}")
d = formulas.dibujar(DIBUJADAS[0], 11.5, 20.0)
ok(d is not None and abs(d.ancho - 20.0) < 0.01, "una fórmula más ancha que su sitio se reduce")
im = Image.open(io.BytesIO(d.png))
ok(im.mode == "RGBA" and im.getchannel("A").getextrema() == (0, 255), "la imagen tiene trazos y fondo transparente")


# ── 2. El examen impreso ────────────────────────────────────────────────────
def png(w, h):
    b = io.BytesIO()
    Image.new("RGB", (w, h), (30, 90, 160)).save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode()


FIGURA = {"name": "g.png", "mime": "image/png", "b64": png(400, 240)}
QS = [
    {"num": 1, "type": "multichoice", "points": 4, "data": {
        "stem": r"MARCA-001 Calcule \(\int_{0}^{1} \frac{x}{x+1}\,dx\).",
        "options": {"A": r"\(\frac{x^2+1}{x-1}\)", "B": "uno", "C": "dos"}, "images": [FIGURA]}},
    {"num": 2, "type": "matching", "points": 6, "data": {
        "stem": "MARCA-002 Relacione.", "col_a": {"1": r"\(\sum_{i=1}^{n} i\)", "2": "cero"},
        "col_b": {"a": r"\(\frac{n(n+1)}{2}\)", "b": "0"}}},
    {"num": 3, "type": "essay", "points": 10, "data": {
        "stem": r"MARCA-003 Demuestre \[\int_{-\infty}^{\infty} e^{-x^2}\,dx = \sqrt{\pi}\] con un comando \(\comandoinventado{3}\)."}},
]
CLAVE = {1: {"type": "multichoice", "answer": "A"},
         2: {"type": "matching", "answer": "1-a; 2-b", "pairs": {"1": "a", "2": "b"}},
         3: {"type": "essay", "answer": ""}}
BASE = dict(materia="Cálculo", docente="Prof. de ejemplo", mezclar=False, documento="examen")


def pdf(**kw):
    return exportar_pdf.generar_pdf(QS, CLAVE, 20, DatosExamen(**{**BASE, **kw}))


def plan(**kw):
    return construir_plan(QS, CLAVE, 20, DatosExamen(**{**BASE, **kw}))


print("2. Fórmulas en el examen")
r = pdf()
t = texto(r.pdf)
ok(r"\int" not in t and r"\frac" not in t and r"\sum" not in t, "ninguna fórmula dibujada queda escrita en LaTeX")
ok(len(imagenes(r.pdf)) == 6, f"la figura y las cinco fórmulas están como imágenes ({len(imagenes(r.pdf))})")
ok(all(x0 >= 0 and x1 <= ancho for _w, _h, x0, x1, ancho in imagenes(r.pdf)), "ninguna se sale de la hoja")
ok(r"\(\comandoinventado" in t and any("1 fórmula" in a for a in r.avisos), f"la desconocida queda tal cual y se avisa ({r.avisos})")
for extra, nombre in ((dict(documento="clave"), "la clave"), (dict(contenido="folleto_hoja_clave", documento="examen"), "la hoja de preguntas"),
                      (dict(plegado=True), "el modo folleto"), (dict(fuente_preguntas="times", tam_preguntas=14), "con Times a 14 pt")):
    x = pdf(**extra)
    ok(x.paginas >= 1 and r"\frac" not in texto(x.pdf), f"también en {nombre}")
largo = exportar_pdf.generar_pdf(
    [{"num": 1, "type": "essay", "data": {"stem": "Una pregunta cuyo comienzo es bastante largo antes de la fórmula \\(\\frac{a+b}{c+d}\\) final."}}],
    {1: {"type": "essay", "answer": ""}}, 5, DatosExamen(documento="clave"))
ok("\\(" not in texto(largo.pdf), "el resumen de la clave no corta una fórmula por la mitad")

print("3. Cuadro de puntos")
sin, con = pdf(), pdf(cuadro_puntos=True)
ok("OBTENIDO" not in texto(sin.pdf) and "CALIFICACIÓN" in texto(sin.pdf), "sin pedirlo no sale (y queda «Calificación»)")
tc = texto(con.pdf)
ok("OBTENIDO" in tc and "TOTAL" in tc and "CALIFICACIÓN" not in tc, "con el cuadro, la línea del docente ya no repite «Calificación»")
tabla = [b for b in plan(cuadro_puntos=True).secciones[0].bloques if isinstance(b, TablaPuntos)]
ok(len(tabla) == 1 and [c.marcado for c in tabla[0].filas[0][1:]] == ["I", "II", "III", "TOTAL"]
   and [c.marcado for c in tabla[0].filas[1][1:]] == ["4", "6", "10", "20"], "una columna por parte, con su valor y el total")
ok(abs(sum(tabla[0].anchos) - plan().geo.ancho) < 0.01, "ocupa todo el ancho")
ok(not any(isinstance(b, TablaPuntos) for s in plan(cuadro_puntos=True, partes=False).secciones for b in s.bloques), "sin partes no hay cuadro")
ok("OBTENIDO" not in texto(pdf(cuadro_puntos=True, documento="clave").pdf), "la clave no lo lleva")
ok("OBTENIDO" in texto(pdf(cuadro_puntos=True, contenido="folleto_hoja_clave", documento="hoja").pdf)
   and "OBTENIDO" not in texto(pdf(cuadro_puntos=True, contenido="folleto_hoja_clave", documento="examen").pdf),
   "con hoja aparte va en la hoja de respuestas, no en la de preguntas")
ok("OBTENIDO" in texto(pdf(cuadro_puntos=True, campos_estudiante=False).pdf), "no depende del cuadro de nombre")

print("4. Partes en hoja nueva")
base_paginas = paginas_de(pdf().pdf)
nuevas = paginas_de(pdf(saltos_partes=["matching", "essay"]).pdf)
ok(len(nuevas) > len(base_paginas) and any(t.startswith("II PARTE") for t, _ in nuevas) and any(t.startswith("III PARTE") for t, _ in nuevas),
   f"cada parte pedida empieza su página ({len(base_paginas)} → {len(nuevas)})")
primera = paginas_de(pdf(saltos_partes=["multichoice"]).pdf)
ok("MARCA-001" not in primera[0][0] and primera[1][0].startswith("I PARTE"), "la primera parte en hoja nueva deja la portada sola")
cuantos = lambda p: sum(isinstance(b, SaltoPagina) for s in p.secciones for b in s.bloques)
ok(cuantos(plan(saltos_partes=["essay"], partes=False)) == 0 and cuantos(plan(saltos_partes=["essay"], documento="clave")) == 0,
   "sin partes, o en la clave, no hay saltos")
ok(cuantos(plan(saltos_partes=["numerical"])) == 0, "un tipo que el examen no tiene se ignora")

print("5. Tamaño de las imágenes")


def figura(**kw):
    solo = [{"num": 1, "type": "essay", "points": 5, "data": {"stem": "Mira.", "images": [FIGURA]}}]
    x = exportar_pdf.generar_pdf(solo, {1: {"type": "essay", "answer": ""}}, 5, DatosExamen(documento="examen", **kw))
    return imagenes(x.pdf)[0]


mediana, chica, grande = figura(), figura(tam_imagenes={"1:0": "pequena"}), figura(tam_imagenes={"1:0": "grande"})
ok(abs(chica[0] - mediana[0] * 0.6) < 1 and grande[0] > mediana[0] * 1.15,
   f"pequeña < mediana < grande ({chica[0]:.0f} < {mediana[0]:.0f} < {grande[0]:.0f} pt de ancho)")
ok(abs(grande[0] / grande[1] - mediana[0] / mediana[1]) < 0.01 and grande[1] <= 13 * 28.35 + 1 and grande[3] <= grande[4], "sin deformarla ni salirse")
ok(figura(tam_imagenes={"9:0": "grande"})[:2] == mediana[:2], "lo elegido para otra pregunta no la cambia")
ok(figura(tam_imagenes={"1:0": "grande"}, plegado=True)[3] <= figura(plegado=True)[4], "en modo folleto la grande cabe en la media hoja")
centro, derecha = figura(alin_imagenes={"1:0": "centro"}), figura(alin_imagenes={"1:0": "derecha"})
_, _, x0, x1, hoja_ancho = mediana
ok(abs((centro[2] + centro[3]) / 2 - hoja_ancho / 2) < 1.5, f"centrada: en medio de la hoja ({centro[2]:.0f}-{centro[3]:.0f} de {hoja_ancho:.0f})")
margen = hoja_ancho - derecha[3]
ok(derecha[2] > centro[2] > x0 and abs(derecha[:2][0] - mediana[0]) < 1 and margen < hoja_ancho / 6, f"a la derecha: contra el margen ({margen:.0f} pt), mismo tamaño")
completa = figura(tam_imagenes={"1:0": "completo"})
ok(completa[0] > grande[0] and abs((completa[2] + completa[3]) / 2 - hoja_ancho / 2) < 1.5 and abs(completa[2] - margen) < 1.5,
   f"a todo el ancho: de margen a margen ({completa[2]:.0f}-{completa[3]:.0f})")
ok(figura(tam_imagenes={"1:0": "completo"}, alin_imagenes={"1:0": "derecha"})[:4] == completa[:4], "…sin importar la posición pedida")
ok(figura(tam_imagenes={"1:0": "completo"}, plegado=True)[3] <= figura(plegado=True)[4], "en modo folleto tampoco se sale")
for pos, esperado in (("centro", "center"), ("derecha", "right")):
    wd = exportar_docx.generar_docx(QS, CLAVE, 20, DatosExamen(**BASE, alin_imagenes={"1:0": pos}))
    ok(f'<w:jc w:val="{esperado}"/>' in docx.Document(io.BytesIO(wd.docx)).element.xml, f"Word: imagen alineada ({pos})")

print("6. En el Word")
w = exportar_docx.generar_docx(QS, CLAVE, 20, DatosExamen(**BASE, cuadro_puntos=True, saltos_partes=["essay"], tam_imagenes={"1:0": "pequena"}))
d = docx.Document(io.BytesIO(w.docx))
xml = d.element.xml
todo = "\n".join(p.text for p in d.paragraphs) + "\n".join(c.text for tb in d.tables for f in tb.rows for c in f.cells)
ok(xml.count("<pic:pic") >= 6 and "data:image" not in todo and "\\frac" not in todo and "￼" not in todo, "las fórmulas van como imágenes, no como texto")
ok("w:position" in xml and 'w:lineRule="atLeast"' in xml, "colocadas sobre la línea, que crece para que quepan")
ok("OBTENIDO" in todo and "CALIFICACIÓN" not in todo, "el cuadro de puntos está")
antes = [p for p in d.paragraphs if p.paragraph_format.page_break_before]
ok(len(antes) == 1 and antes[0].text.startswith("III PARTE"), "el salto de página va en el título de la parte pedida")
with zipfile.ZipFile(io.BytesIO(w.docx)) as z:
    ok(z.testzip() is None, "el archivo está entero")

print("7. Las rutas")
cli = TestClient(main.app, base_url="http://127.0.0.1:8000")
H = {"X-Conversor-Token": seguridad.TOKEN}
examen = {"filename": "x.pdf", "total_points": 20, "questions": QS, "answer_key": {str(k): v for k, v in CLAVE.items()}}
con_todo = {"cuadro_puntos": True, "saltos_partes": ["essay"], "tam_imagenes": {"1:0": "grande"}}
for ruta in ("/api/exportar_examen", "/api/vista_previa_pdf"):
    res = cli.post(ruta, json={**examen, "datos": con_todo}, headers=H)
    ok(res.status_code == 200, f"{ruta} acepta lo nuevo ({res.status_code})")
for bueno in ({"tam_imagenes": {"1:0": "completo"}}, {"alin_imagenes": {"1:0": "centro"}}):
    ok(cli.post("/api/vista_previa_pdf", json={**examen, "datos": bueno}, headers=H).status_code == 200, f"se acepta {bueno}")
for malo in ({"saltos_partes": ["inventada"]}, {"tam_imagenes": {"1:0": "enorme"}}, {"tam_imagenes": {"uno": "grande"}},
             {"alin_imagenes": {"1:0": "arriba"}}, {"alin_imagenes": {"uno": "centro"}},
             {"tam_imagenes": {f"{i}:0": "grande" for i in range(501)}}):
    res = cli.post("/api/exportar_examen", json={**examen, "datos": malo}, headers=H)
    ok(res.status_code == 422, f"se rechaza {str(malo)[:60]} ({res.status_code})")
res = cli.post("/api/exportar_versiones", json={**examen, "datos": con_todo, "versiones": [{"etiqueta": "A", "nums": [3, 1, 2], "total_points": 20}]}, headers=H)
ok(res.status_code == 200, f"las versiones también ({res.status_code})")
ok(cli.put("/api/perfiles_pdf/P", json={"cuadro_puntos": True, "saltos_partes": ["essay"]}, headers=H).status_code == 200
   and cli.get("/api/perfiles_pdf", headers=H).json()[0]["datos"]["saltos_partes"] == ["essay"]
   and cli.get("/api/perfiles_pdf", headers=H).json()[0]["datos"]["cuadro_puntos"] is True, "un perfil guarda el cuadro y los saltos")
ok(cli.put("/api/perfiles_pdf/Q", json={"saltos_partes": ["inventada"]}, headers=H).status_code == 422, "un perfil con una parte inventada se rechaza")

print()
print("TODO OK" if not fallas else f"{len(fallas)} FALLA(S)")
sys.exit(1 if fallas else 0)
