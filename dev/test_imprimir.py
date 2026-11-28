"""
test_imprimir.py — qué se imprime y cómo (3.2): un documento cada vez y el «modo folleto».

    PYTHONUTF8=1 backend/venv/bin/python dev/test_imprimir.py

Sin red ni Gemini; la base es temporal.
  1. El orden de las páginas en las hojas (plegado.caras).
  2. Cada documento por separado trae lo suyo y nada más.
  3. El PDF en modo folleto: hojas a lo ancho, cada página en su mitad y en su sitio, sin salirse.
  4. El Word sale siempre normal (el folleto es solo del PDF) y trae solo el documento pedido.
  5. Las rutas: nombres de archivo, hojas, vista previa, versiones y lo que se rechaza.
"""

import io
import json
import logging
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

TMP = Path(tempfile.mkdtemp(prefix="conv imprimir "))
os.environ["HOME"] = str(TMP / "home")
os.environ["LOCALAPPDATA"] = str(TMP / "home" / "AppData")
(TMP / "datos" / "data").mkdir(parents=True)
import database  # noqa: E402

database.get_db_path = lambda: TMP / "datos" / "data" / "exams_history.db"  # ANTES de importar main

import docx  # noqa: E402
import pdfplumber  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import exportar_docx  # noqa: E402
import exportar_pdf  # noqa: E402
import main  # noqa: E402
import plegado  # noqa: E402
import seguridad  # noqa: E402
from plan_impreso import DatosExamen  # noqa: E402

logging.disable(logging.CRITICAL)
fallas = []


def ok(cond, texto):
    print(("  ok   " if cond else "  FALLA ") + texto)
    if not cond:
        fallas.append(texto)


def examen(n=40):
    qs, clave = [], {}
    for i in range(1, n + 1):
        if i == n:
            qs.append({"num": i, "type": "essay", "data": {"stem": f"MARCA-{i:03d} explique el alcance."}})
            clave[i] = {"type": "essay", "answer": ""}
        else:
            qs.append({"num": i, "type": "multichoice", "data": {"stem": f"MARCA-{i:03d} ¿cuál describe mejor la gestión del alcance de un proyecto de software?",
                                                                "options": {"A": "OPCION-BUENA la que lo controla", "B": "otra", "C": "ninguna"}}})
            clave[i] = {"type": "multichoice", "answer": "A"}
    return qs, clave


QS, CLAVE = examen()
BASE = dict(materia="Gerencia", docente="Prof. de ejemplo", partes=False, mezclar=False)


def pdf(qs=QS, clave=CLAVE, **kw):
    return exportar_pdf.generar_pdf(qs, clave, 100, DatosExamen(**{**BASE, **kw}))


def texto(b):
    with pdfplumber.open(io.BytesIO(b)) as d:
        return " ".join((p.extract_text() or "") for p in d.pages)


print("1. El orden de las páginas")
ok(plegado.caras(8) == [(7, 0), (1, 6), (5, 2), (3, 4)], "8 páginas: [8|1] [2|7] [6|3] [4|5]")
ok(plegado.caras(7) == [(None, 0), (1, 6), (5, 2), (3, 4)], "7 páginas: la octava queda en blanco")
ok(plegado.caras(1) == [(None, 0), (None, None)] and plegado.caras(2) == [(None, 0), (1, None)], "1 y 2 páginas: una hoja")
ok(all(len(plegado.caras(n)) % 2 == 0 and sorted(i for c in plegado.caras(n) for i in c if i is not None) == list(range(n))
       for n in range(1, 60)), "de 1 a 59 páginas: cada una sale una vez y las caras van de dos en dos")


def lectura(n):
    """Las páginas en el orden en que se leen al apilar las hojas y doblarlas."""
    c = plegado.caras(n)
    hojas = [(c[i], c[i + 1]) for i in range(0, len(c), 2)]
    delante = [x for frente, dorso in hojas for x in (frente[1], dorso[0])]
    detras = [x for frente, dorso in reversed(hojas) for x in (dorso[1], frente[0])]
    return delante + detras


ok(all([x for x in lectura(n) if x is not None] == list(range(n)) for n in range(1, 60)), "doblado, se lee 1, 2, 3… hasta el final")

print("2. Un documento cada vez")
for contenido, documento, debe, no_debe in (
        ("examen_y_clave", "examen", ["MARCA-001", "Seleccione una."], ["CLAVE DE RESPUESTAS"]),
        ("examen_y_clave", "clave", ["CLAVE DE RESPUESTAS", "MARCA-001"], ["Seleccione una."]),
        ("folleto_hoja_clave", "examen", ["NO ESCRIBA EN ESTA HOJA DE PREGUNTAS", "MARCA-001"], ["HOJA DE RESPUESTAS Escriba", "CLAVE DE RESPUESTAS"]),
        ("folleto_hoja_clave", "hoja", ["HOJA DE RESPUESTAS"], ["MARCA-001", "CLAVE DE RESPUESTAS"]),
        ("folleto_hoja_clave", "clave", ["CLAVE DE RESPUESTAS", "hoja de respuestas llena"], ["MARCA-001", "NO ESCRIBA"])):
    t = " ".join(texto(pdf(contenido=contenido, documento=documento).pdf).split())
    ok(all(x in t for x in debe) and not any(x in t for x in no_debe), f"{contenido} / {documento}: lo suyo y nada más")
todo = pdf(contenido="folleto_hoja_clave")
sueltos = [pdf(contenido="folleto_hoja_clave", documento=d) for d in ("examen", "hoja", "clave")]
ok(sum(s.paginas for s in sueltos) == todo.paginas, "las páginas de los tres suman las del archivo completo")
try:
    pdf(contenido="examen_y_clave", documento="hoja")
    ok(False, "sin hoja de respuestas no se puede pedir la hoja")
except ValueError:
    ok(True, "sin hoja de respuestas no se puede pedir la hoja")

print("3. PDF en modo folleto")
normal = pdf(contenido="folleto_hoja_clave", documento="examen")
fol = pdf(contenido="folleto_hoja_clave", documento="examen", plegado=True)
ok(fol.paginas % 2 == 0 and fol.hojas * 2 == fol.paginas and fol.hojas < normal.paginas, f"{fol.hojas} hojas frente a {normal.paginas} páginas normales")
with pdfplumber.open(io.BytesIO(fol.pdf)) as d:
    ok(len(d.pages) == fol.paginas and all(round(p.width) == 792 and round(p.height) == 612 for p in d.pages), "carta a lo ancho")
    mitades = []
    fuera = []
    for p in d.pages:
        w = p.extract_words()
        medio = p.width / 2
        fuera += [x["text"] for x in w if x["x0"] < 24 or x["x1"] > p.width - 24 or (x["x0"] < medio - 24 < x["x1"] and x["x1"] > medio)
                  or medio - 24 < x["x0"] < medio + 24 or x["bottom"] > p.height - 12]
        for izq in (True, False):
            mias = [x for x in w if (x["x0"] < medio) == izq]
            pie = re.search(r"Página (\d+) de (\d+)", " ".join(x["text"] for x in mias))
            mitades.append(int(pie.group(1)) if pie else None)
    ok(not fuera, f"nada pisa el lomo ni los bordes ({fuera[:4]})")
    total = max(x for x in mitades if x)
    esperado = [None if i is None else i + 1 for cara in plegado.caras(total) for i in cara]
    ok(mitades == esperado, f"cada página en su cara y su mitad ({mitades})")
    letras = [round(c["size"], 1) for c in d.pages[1].chars if c["text"] == "¿"]
    ok(letras and all(abs(x - 8.5) < 0.2 for x in letras), f"letra de 8,5 pt, sin encoger la página ({letras[:2]})")
t = texto(fol.pdf)
ok(all(f"MARCA-{i:03d}" in t for i in range(1, 41)), "están las 40 preguntas")
grande = pdf(contenido="folleto_hoja_clave", documento="examen", plegado=True, letra_plegado=11)
chica = pdf(contenido="folleto_hoja_clave", documento="examen", plegado=True, letra_plegado=7)
ok(chica.hojas <= fol.hojas <= grande.hojas and chica.hojas < grande.hojas, f"menos letra, menos papel ({chica.hojas} ≤ {fol.hojas} ≤ {grande.hojas})")
with pdfplumber.open(io.BytesIO(pdf(letra_plegado=99, plegado=True, documento="examen").pdf)) as d:
    tams = {round(c["size"], 1) for p in d.pages for c in p.chars if c["text"] == "¿"}
    ok(tams == {12.0}, f"un tamaño absurdo se acota a 12 pt ({tams})")
for papel, medida in (("a4", (842, 595)), ("legal", (1008, 612))):
    r = pdf(plegado=True, documento="examen", papel=papel)
    with pdfplumber.open(io.BytesIO(r.pdf)) as d:
        ok((round(d.pages[0].width), round(d.pages[0].height)) == medida, f"{papel} a lo ancho")
enorme = pdf(plegado=True, documento="examen", renglones_ensayo=24, procedimiento_numerica=True, renglones_procedimiento=24,
             institucion="Universidad Tecnológica de Panamá")
with pdfplumber.open(io.BytesIO(enorme.pdf)) as d:
    cajas = [r_ for p in d.pages for r_ in p.rects if r_["width"] > 150 and r_["height"] > 100]
    ok(cajas and all(r_["height"] < 530 for r_ in cajas), "un recuadro de 24 renglones se ajusta a la media hoja")
ok(pdf(plegado=True).hojas >= 1, "sin elegir documento también se puede plegar")

print("4. El Word sale siempre normal")


def word(**kw):
    return exportar_docx.generar_docx(QS, CLAVE, 100, DatosExamen(**{**BASE, **kw})).docx


def partes_word(b):
    z = zipfile.ZipFile(io.BytesIO(b))
    return z.read("word/document.xml").decode(), z.read("word/settings.xml").decode()


w = word(contenido="folleto_hoja_clave", documento="examen", plegado=True)
doc_xml, ajustes = partes_word(w)
ok("bookFoldPrinting" not in ajustes and 'w:orient="landscape"' not in doc_xml and 'w:w="12240" w:h="15840"' in doc_xml,
   "aunque se pida modo folleto: hoja carta entera, de pie y sin «Libro plegado»")
ok(partes_word(w)[0] == partes_word(word(contenido="folleto_hoja_clave", documento="examen"))[0], "idéntico al Word pedido sin folleto")
d = docx.Document(io.BytesIO(w))
parrafos = " ".join(p.text for p in d.paragraphs)
ok(len(d.sections) == 1 and "MARCA-001" in parrafos and "MARCA-040" in parrafos and "CLAVE DE RESPUESTAS" not in parrafos,
   "trae solo la hoja de preguntas")
for documento, debe, no_debe in (("hoja", "HOJA DE RESPUESTAS", "MARCA-001"), ("clave", "CLAVE DE RESPUESTAS", "MARCA-001")):
    t_ = " ".join(p.text for p in docx.Document(io.BytesIO(word(contenido="folleto_hoja_clave", documento=documento))).paragraphs)
    ok(debe in t_ and no_debe not in t_, f"documento «{documento}»: solo lo suyo")

print("5. Rutas")
cli = TestClient(main.app, base_url="http://127.0.0.1:8000")
H = {"X-Conversor-Token": seguridad.TOKEN}
cuerpo = {"filename": "mi examen.pdf", "total_points": 100, "questions": QS, "answer_key": {str(k): v for k, v in CLAVE.items()}}


def pedir(ruta="/api/exportar_examen", **datos):
    return cli.post(ruta, json={**cuerpo, "datos": datos}, headers=H)


for datos, nombre in (({"documento": "examen"}, "mi%20examen_evaluacion.pdf"),
                      ({"documento": "examen", "contenido": "folleto_hoja_clave"}, "mi%20examen_preguntas.pdf"),
                      ({"documento": "hoja", "contenido": "folleto_hoja_clave", "plegado": True}, "mi%20examen_hoja_de_respuestas_folleto.pdf"),
                      ({"documento": "clave", "formato": "word", "plegado": True}, "mi%20examen_clave.docx"),
                      ({"documento": "examen", "formato": "ambos", "plegado": True}, "mi%20examen_evaluacion_folleto_pdf_y_word.zip")):
    r = pedir(**datos)
    cd = r.headers.get("content-disposition", "")
    ok(r.status_code == 200 and (nombre in cd or nombre.replace("%20", " ") in cd), f"{nombre} ({r.status_code} {cd[-60:]})")
r = pedir(documento="examen", plegado=True)
info = json.loads(r.headers["x-pdf-info"])
ok(info["hojas"] * 2 == info["paginas"] and info["hojas"] >= 1, f"se informan las hojas {info}")
vp = pedir("/api/vista_previa_pdf", documento="examen", plegado=True)
ok(vp.status_code == 200 and int(vp.headers["x-pdf-paginas"]) == info["paginas"], "la vista previa es la del folleto")
malos = ({"documento": "otra"}, {"documento": "hoja"}, {"documento": "examen", "contenido": "solo_clave"}, {"plegado": True, "letra_plegado": 5},
         {"plegado": True, "letra_plegado": 20}, {"documento": "examen", "contenido": "nada"})
ok(all(pedir(**m).status_code == 422 for m in malos), "documento o letra no válidos: 422")
vs = [{"etiqueta": e, "nums": [1, 2, 3, 40], "total_points": 10} for e in ("A", "B")]
r = cli.post("/api/exportar_versiones", json={**cuerpo, "versiones": vs, "datos": {"documento": "hoja", "contenido": "folleto_hoja_clave",
                                                                                   "plegado": True, "formato": "ambos"}}, headers=H)
nombres = sorted(zipfile.ZipFile(io.BytesIO(r.content)).namelist()) if r.status_code == 200 else []
ok(nombres == sorted([f"mi examen_version_{e}_hoja_de_respuestas_folleto.pdf" for e in "AB"]
                     + [f"mi examen_version_{e}_hoja_de_respuestas.docx" for e in "AB"]),
   f"versiones: ese documento de cada una; «folleto» solo en el PDF ({nombres})")
r = pedir(documento="examen", formato="ambos", plegado=True)
dentro = zipfile.ZipFile(io.BytesIO(r.content))
ok(sorted(dentro.namelist()) == ["mi examen_evaluacion.docx", "mi examen_evaluacion_folleto.pdf"]
   and "bookFoldPrinting" not in partes_word(dentro.read("mi examen_evaluacion.docx"))[1], "PDF y Word con folleto: solo el PDF se pliega")
r = pedir(documento="hoja", contenido="folleto_hoja_clave", formato="word")
t_ = " ".join(p.text for p in docx.Document(io.BytesIO(r.content)).paragraphs)
ok(r.status_code == 200 and "HOJA DE RESPUESTAS" in t_ and "MARCA-001" not in t_ and json.loads(r.headers["x-pdf-info"])["hojas"] == 0,
   "descargar en Word un documento no trae los demás")
ok(cli.post("/api/exportar_examen", json={**cuerpo, "datos": {"documento": "examen"}}).status_code == 401, "sin token: 401")

print()
print("TODO OK" if not fallas else f"{len(fallas)} FALLA(S)")
sys.exit(1 if fallas else 0)
