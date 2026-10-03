"""
test_confianza.py — Versión 1.9: de dónde salió cada respuesta (origen_respuesta),
cuánta confianza da (confianza) y dónde está cada pregunta en el PDF original
(page verificada + recuadro).

    PYTHONUTF8=1 backend/venv/bin/python dev/test_confianza.py

Sin red ni Gemini (la IA se simula con la respuesta de una IA «perfecta»), sin
tocar el historial ni la clave. Solo usa los PDF sintéticos de
samples/synthetic/ y PDF armados en memoria con reportlab; no abre ningún
documento personal.

Qué cubre
  1. confianza.evaluar: tabla de casos (origen y confianza).
  2. Las señales del modo JSON y del modo texto (rescatadas, clave del documento).
  3. origen_pdf.ubicar_preguntas en los PDF sintéticos: el recuadro cae sobre el
     texto de ESA pregunta (enunciado y opciones) y no sobre el de la vecina.
  4. Casos límite armados en memoria: pregunta que continúa en otra página,
     pregunta del documento que la IA no devolvió, texto repetido, varias
     columnas, escaneado/sin texto.
  5. De punta a punta (pipeline.parse_document con la IA simulada): los campos
     nuevos están y el XML de Moodle es IDÉNTICO al de antes.
  6. pipeline._comprobar_entrada pregunta al proveedor de IA, no a Gemini.
"""

import copy
import io
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "dev"))
sys.path.insert(0, str(ROOT / "dev" / "synthetic"))

# ── Aislamiento: nada de la máquina real ────────────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="conv confianza "))
os.environ["HOME"] = str(TMP / "home")
os.environ["LOCALAPPDATA"] = str(TMP / "home" / "AppData")
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("XDG_DATA_HOME", None)
os.environ.pop("CONVERSOR_PROVEEDOR_IA", None)

import pdfplumber  # noqa: E402
import requests  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import xml_fidelity as xf  # noqa: E402  (apaga el logging, que es lo que se quiere)
import exams  # noqa: E402
import confianza  # noqa: E402
import ia_gemini  # noqa: E402
import ia_proveedor  # noqa: E402
import imagenes  # noqa: E402
import origen_pdf  # noqa: E402
import pipeline  # noqa: E402
from ia_proveedor import IASinClaveError, ProveedorIA  # noqa: E402
from modelo import SIN_RESPUESTA  # noqa: E402
from schema_adapter import adapt  # noqa: E402
from xml_builder import build_xml  # noqa: E402

logging.disable(logging.CRITICAL)
requests.post = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe haber red"))

SINTETICOS = ROOT / "samples" / "synthetic"
fallas = 0


def ok(cond, msg):
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


# ══════════════════════════════════════════════════════════════════════════
print("1. confianza.evaluar — origen y confianza")
# ══════════════════════════════════════════════════════════════════════════

def P(tipo="multichoice", **data):
    return {"num": 1, "type": tipo, "data": {"stem": "¿Algo?", "options": {"A": "uno", "B": "dos"}, **data}}


def K(answer="B", **extra):
    return {"type": "multichoice", "answer": answer, **extra}


CASOS = [
    # (descripción, pregunta, clave, contexto, esperado)
    ("clave explícita del documento", P(), K(from_key=True), None, ("documento", "alta")),
    ("marca leída por el código", P(answer_from_marks=True), K(), None, ("marca", "alta")),
    ("IA sin respaldo ni dudas", P(), K(), None, ("ia", "media")),
    ("IA con «revisar marca de color»", P(color_review_hint=True), K(), None, ("ia", "baja")),
    ("IA que dijo confianza baja (low_confidence)", P(low_confidence=True), K(), None, ("ia", "baja")),
    ("IA, pregunta rescatada por un reintento", P(), K(), {"rescatada": True}, ("ia", "baja")),
    ("documento, pero rescatada por un reintento", P(), K(from_key=True), {"rescatada": True}, ("documento", "baja")),
    ("marca, pero low_confidence", P(answer_from_marks=True, low_confidence=True), K(), None, ("marca", "baja")),
    ("la clave del documento manda sobre la marca", P(answer_from_marks=True), K(from_key=True), None, ("documento", "alta")),
    ("el contexto afirma que viene del documento", P(), K(), {"desde_documento": True}, ("documento", "alta")),
    ("pero una marca que pisó la respuesta es «marca»", P(answer_from_marks=True), K(), {"desde_documento": True}, ("marca", "alta")),
    ("verdadero/falso por marca", P("truefalse", answer_from_marks=True), {"type": "truefalse", "answer": "Falso"}, None, ("marca", "alta")),
    ("emparejamiento de la IA", P("matching"), {"type": "matching", "answer": "1-a; 2-b"}, None, ("ia", "media")),
    ("completar de la IA", P("cloze"), {"type": "cloze", "answer": "A. París"}, None, ("ia", "media")),
    ("respuesta corta con clave del documento", P("shortanswer"), {"type": "shortanswer", "answer": "Sena"}, {"desde_documento": True}, ("documento", "alta")),
    ("numérica de la IA", P("numerical"), {"type": "numerical", "answer": "50"}, None, ("ia", "media")),
    ("ensayo: nada que fiar", P("essay"), {"type": "essay", "answer": "respuesta abierta, se califica manualmente"}, None, (None, None)),
    ("sin respuesta (SIN_RESPUESTA)", P(), K(SIN_RESPUESTA), None, (None, None)),
    ("sin clave", P(), None, None, (None, None)),
    ("cloze con un hueco sin respuesta", P("cloze"), {"type": "cloze", "answer": f"A. {SIN_RESPUESTA}; B. x"}, None, (None, None)),
    ("tipo desconocido", P("raro"), K(), None, (None, None)),
    ("pregunta con error del parser", {**P(), "error": "x"}, K(), None, (None, None)),
]
for desc, preg, clave, ctx, esperado in CASOS:
    ok(confianza.evaluar(preg, clave, ctx) == esperado, f"{desc} → {esperado}")

ambigua = {"num": 1, "type": "multichoice", "data": {"stem": "¿Qué?", "options": {"A": "Sol de día", "B": "Sol de noche", "C": "Luna"}}}
ok(confianza.evaluar(ambigua, K("Sol de"), None) == ("ia", "baja"), "respuesta ambigua (coincide con varias opciones) → baja")
ok(confianza.evaluar(ambigua, K("Luna"), None) == ("ia", "media"), "la misma pregunta con una respuesta clara → media")
ok(confianza.evaluar(ambigua, K("Sol de", from_key=True), None) == ("documento", "baja"), "ambigua también baja la confianza de la clave del documento")

original = copy.deepcopy(P(color_review_hint=True))
confianza.evaluar(original, K(), {"rescatada": True})
ok(original == P(color_review_hint=True), "evaluar no modifica la pregunta (función pura)")
ok(confianza.evaluar(None, None, None) == (None, None) and confianza.evaluar({"type": "multichoice", "data": "x"}, K(), None) == ("ia", "media"),
   "entradas raras no lanzan excepción")

# etiquetar: escribe en data, y quita lo que ya no corresponde
qs = [P(), {"num": 2, "type": "essay", "data": {"stem": "Explica", "origen_respuesta": "ia", "confianza": "media"}}]
qs[0]["num"] = 1
n_et = confianza.etiquetar(qs, {1: K(), 2: {"type": "essay", "answer": "respuesta abierta"}})
ok(n_et == 1 and qs[0]["data"]["origen_respuesta"] == "ia" and qs[0]["data"]["confianza"] == "media",
   "etiquetar escribe origen_respuesta y confianza en data")
ok("origen_respuesta" not in qs[1]["data"] and "confianza" not in qs[1]["data"], "etiquetar no deja los campos en un ensayo")
ok("low_confidence" not in qs[0]["data"], "etiquetar no inventa ni mezcla low_confidence")

# ══════════════════════════════════════════════════════════════════════════
print("2. Señales del modo JSON y del modo texto")
# ══════════════════════════════════════════════════════════════════════════

payload_sig = {"preguntas": [
    {"orden": 2, "tipo": "shortanswer", "clave_texto": "Sena"},
    {"orden": 1, "tipo": "multichoice", "clave_texto": "b"},
    {"orden": 3, "tipo": "numerical", "clave_texto": "  "},
    {"orden": 4, "tipo": "shortanswer", "clave_texto": "", "_rescatada": True},
    {"orden": 5, "tipo": "numerical", "clave_texto": "50", "_rescatada": True},
]}
resc, doc = confianza.senales_del_payload(payload_sig)
ok(resc == {4, 5}, "rescatadas: numeradas como schema_adapter (por «orden»)")
ok(doc == {2, 5}, "respuesta corta o numérica con clave_texto → desde el documento (no la de opción múltiple, que ya trae from_key)")

ok(confianza.clave_documento_coincide({1: {"answer": "B"}, 2: {"answer": "Verdadero"}},
                                      {1: {"answer": "b"}, 2: {"answer": "verdadero"}}) == {1, 2},
   "modo texto: la clave del documento coincide con la de la IA → documento")
ok(confianza.clave_documento_coincide({1: {"answer": "B"}, 2: {"answer": "A"}}, {1: {"answer": "B"}, 2: {"answer": "C"}}) == set(),
   "modo texto: una sola respuesta distinta → ninguna se atribuye al documento")
ok(confianza.clave_documento_coincide({1: {"answer": "B"}}, {1: {"answer": "B"}, 2: {"answer": "A"}}) == set(),
   "modo texto: la IA renumeró o agregó preguntas → ninguna se atribuye al documento")
ok(confianza.clave_documento_coincide({}, {1: {"answer": "B"}}) == set(), "modo texto: el documento no trae clave → vacío")

# ══════════════════════════════════════════════════════════════════════════
print("3. Ubicación en los PDF sintéticos")
# ══════════════════════════════════════════════════════════════════════════

def norm(t):
    return origen_pdf._norm_sin_numero(t)


def texto_en_caja(pdf, u):
    pg = pdf.pages[u["page"] - 1]
    w, h = pg.width, pg.height
    x0, y0, x1, y1 = u["recuadro"]
    caja = pg.crop((x0 * w, y0 * h, x1 * w, y1 * h))
    return norm(caja.extract_text() or "")


def revisar(nombre, qs_examen):
    """(preguntas, ubicadas, fallos) de un PDF sintético con su examen conocido."""
    pdf_bytes = (SINTETICOS / f"{nombre}.pdf").read_bytes()
    preguntas, _ = adapt(xf.perfect_model(qs_examen))
    t0 = time.perf_counter()
    ubic = origen_pdf.ubicar_preguntas(pdf_bytes, preguntas)
    seg = time.perf_counter() - t0
    fallos = []
    stems = {q["num"]: norm((q["data"].get("stem") or (q["data"].get("text") or "").split("[")[0])) for q in preguntas}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for q in preguntas:
            u = ubic.get(q["num"])
            if not u:
                continue
            x0, y0, x1, y1 = u["recuadro"]
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1) or u["page"] < 1:
                fallos.append((q["num"], "recuadro fuera de la página"))
                continue
            txt = texto_en_caja(pdf, u)
            d = q["data"]
            cabeza = stems[q["num"]].split()[:4]
            # x06 tiene una marca de agua cuyas letras se cuelan dentro de las palabras
            if sum(w in txt for w in cabeza) < (2 if nombre.startswith("x06") else len(cabeza)):
                fallos.append((q["num"], "no contiene el enunciado"))
            al_final = y1 > 0.84  # empieza abajo y sigue en la página siguiente: solo se exige el enunciado
            if not al_final:
                for o in (d.get("options") or {}).values():
                    if norm(o) and norm(o) not in txt:
                        fallos.append((q["num"], f"falta la opción «{o[:20]}»"))
            for otra, st in stems.items():
                if otra != q["num"] and len(st) >= 20 and st in txt and st not in stems[q["num"]]:
                    fallos.append((q["num"], f"contiene el enunciado de la {otra}"))
            # la página es donde está el enunciado
            if stems[q["num"]].split()[0] not in norm(pdf.pages[u["page"] - 1].extract_text() or ""):
                fallos.append((q["num"], "página equivocada"))
    return preguntas, ubic, fallos, seg


PARES = {"s01_limpio_clave_final": exams.BASE_MIXED,
         "s05_largo_60_preguntas": exams.long_exam(60),
         "s10_estres_150_preguntas": exams.long_exam(150)}
adversariales = xf.load_exams()
for clave_ex, qs_ex in adversariales.items():
    candidatos = sorted(SINTETICOS.glob(f"{clave_ex}_*.pdf"))
    if candidatos:
        PARES[candidatos[0].stem] = qs_ex

total = ubicadas = 0
tiempos = {}
for nombre, qs_ex in PARES.items():
    preguntas, ubic, fallos, seg = revisar(nombre, qs_ex)
    tiempos[nombre] = seg
    total += len(preguntas)
    ubicadas += len(ubic)
    if nombre.startswith(("x05", "x10")):
        ok(not ubic, f"{nombre}: dos columnas / escaneado → no ubica nada")
        continue
    ok(not fallos, f"{nombre}: {len(ubic)} de {len(preguntas)} ubicadas; el recuadro cae sobre su texto y no el de la vecina"
       + (f" — {fallos[:3]}" if fallos else ""))
ok(ubicadas / total >= 0.8, f"cobertura global ≥ 80 % en los sintéticos ({ubicadas} de {total})")

for nombre, esperado in (("s01_limpio_clave_final", 10), ("s05_largo_60_preguntas", 60), ("s10_estres_150_preguntas", 150)):
    _, ubic, _, _ = revisar(nombre, PARES[nombre])
    ok(len(ubic) == esperado, f"{nombre}: ubica las {esperado} preguntas")
ok(tiempos["s10_estres_150_preguntas"] < 3.0, f"150 preguntas / 19 páginas en {tiempos['s10_estres_150_preguntas']:.2f} s (< 3 s)")

s06 = (SINTETICOS / "s06_escaneado_sin_texto.pdf").read_bytes()
preg_s06, _ = adapt(xf.perfect_model(exams.BASE_MIXED))
ok(origen_pdf.ubicar_preguntas(s06, preg_s06) == {}, "s06 escaneado (sin capa de texto) → {}")
ok(origen_pdf.ubicar_preguntas(b"esto no es un pdf", preg_s06) == {}, "bytes que no son un PDF → {} (sin excepción)")
ok(origen_pdf.ubicar_preguntas(b"", preg_s06) == {} and origen_pdf.ubicar_preguntas(s06, []) == {}, "entradas vacías → {}")

# ══════════════════════════════════════════════════════════════════════════
print("4. Casos límite armados en memoria")
# ══════════════════════════════════════════════════════════════════════════

from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

ALTO = letter[1]


def pdf_de_paginas(paginas, columnas=None):
    """paginas: lista de listas de (y, texto) o de textos (se apilan desde arriba)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for pag in paginas:
        y = ALTO - 72
        for item in pag:
            if isinstance(item, tuple):
                y, texto = item
            else:
                texto = item
                y -= 16
            c.setFont("Helvetica", 11)
            c.drawString(72, y, texto)
        c.showPage()
    c.save()
    return buf.getvalue()


def Q(num, stem, opciones=(), tipo="multichoice"):
    d = {"stem": stem}
    if opciones:
        d["options"] = {chr(65 + i): o for i, o in enumerate(opciones)}
    return {"num": num, "type": tipo, "data": d}


Q1 = Q(1, "¿Cuál es el río más largo de Sudamérica?", ["Amazonas", "Orinoco", "Paraná", "Magdalena"])
Q2 = Q(2, "¿Qué gas respiramos principalmente en el aire?", ["Oxígeno", "Nitrógeno", "Helio", "Argón"])
Q4 = Q(4, "¿Cuántos lados tiene un hexágono regular?", ["Cinco", "Seis", "Siete", "Ocho"])
Q5 = Q(5, "¿Quién escribió Cien años de soledad?", ["García Márquez", "Borges", "Neruda", "Paz"])
Q6 = Q(6, "¿Cuál es correcta?", ["Una", "Dos"])
Q7 = Q(7, "¿Cuál es correcta?", ["Tres", "Cuatro"])
Q8 = Q(8, "¿Cuál es la capital de Portugal?", ["Lisboa", "Oporto", "Faro"])

pagina1 = [
    "Examen de prueba", "Instrucciones: marque una sola respuesta.",
    "1. ¿Cuál es el río más largo de Sudamérica?", "a) Amazonas", "b) Orinoco", "c) Paraná", "d) Magdalena",
    "2. ¿Qué gas respiramos principalmente en el aire?", "a) Oxígeno", "b) Nitrógeno", "c) Helio", "d) Argón",
    # La 3 está en el documento pero la IA no la devolvió:
    "3. ¿Cuál es el planeta más cercano al Sol?", "a) Venus", "b) Mercurio", "c) Marte",
    "4. ¿Cuántos lados tiene un hexágono regular?", "a) Cinco", "b) Seis", "c) Siete", "d) Ocho",
    (95, "5. ¿Quién escribió Cien años de soledad?"), (80, "a) García Márquez"),
]
pagina2 = ["b) Borges", "c) Neruda", "d) Paz",
           "6. ¿Cuál es correcta?", "a) Una", "b) Dos",
           "7. ¿Cuál es correcta?", "a) Tres", "b) Cuatro",
           "8. ¿Cuál es la capital de Portugal?", "a) Lisboa", "b) Oporto", "c) Faro"]
pagina3 = ["RESPUESTAS", "1. a", "2. b", "4. b", "5. a", "8. a"]
pdf_mem = pdf_de_paginas([pagina1, pagina2, pagina3])
lista = [Q1, Q2, Q4, Q5, Q6, Q7, Q8]
ub = origen_pdf.ubicar_preguntas(pdf_mem, lista)
with pdfplumber.open(io.BytesIO(pdf_mem)) as pdf:
    t1 = texto_en_caja(pdf, ub[1]) if 1 in ub else ""
    t2 = texto_en_caja(pdf, ub[2]) if 2 in ub else ""
    t4 = texto_en_caja(pdf, ub[4]) if 4 in ub else ""
    t5 = texto_en_caja(pdf, ub[5]) if 5 in ub else ""
    t8 = texto_en_caja(pdf, ub[8]) if 8 in ub else ""

ok(1 in ub and ub[1]["page"] == 1 and all(norm(x) in t1 for x in ["río más largo", "Amazonas", "Magdalena"]) and "gas respiramos" not in t1,
   "pregunta normal: el recuadro tiene su enunciado y sus 4 opciones, no las de la vecina")
ok(2 in ub and norm("Argón") in t2 and "planeta" not in t2 and "mercurio" not in t2,
   "la pregunta 3 del documento (que la IA no devolvió) queda FUERA del recuadro de la 2")
ok(4 in ub and "ocho" in t4 and "mercurio" not in t4 and "hexagono" in t4, "la pregunta siguiente a la que falta tampoco se contamina")
ok(5 in ub and ub[5]["page"] == 1 and "cien anos" in t5 and ub[5]["recuadro"][3] > 0.9 and "borges" not in t5,
   "pregunta que empieza al pie de la página 1 y sigue en la 2: page = 1 y el recuadro llega al fondo de esa página")
ok(8 in ub and ub[8]["page"] == 2 and "lisboa" in t8 and "respuestas" not in t8 and "faro" in t8,
   "la última pregunta no absorbe la hoja de respuestas de la página siguiente")
ok(6 not in ub and 7 not in ub, "dos preguntas con el mismo enunciado → ninguna se ubica (ancla ambigua)")
ok(all(len(v["recuadro"]) == 4 and v["page"] >= 1 for v in ub.values()), "todas devuelven page ≥ 1 y 4 fracciones")

# Enunciado que la IA reescribió (código transcrito de una imagen) → no hay ancla
otra = [Q(1, "Ejemplo: print(3+4). ¿Qué muestra la pantalla?", ["7", "34"]), Q2]
ub_o = origen_pdf.ubicar_preguntas(pdf_mem, otra)
ok(1 not in ub_o, "enunciado que no aparece en el PDF (reescrito por la IA) → no se ubica")

# Una pregunta cuya siguiente no se ubica y que NO está numerada → se omite (no se sabe dónde termina)
sin_numeros = [["Preguntas sin numerar", "¿Cuál es el río más largo de Sudamérica?", "a) Amazonas", "b) Orinoco", "",
                "¿Cuál es el metal líquido a temperatura ambiente?", "a) Mercurio", "b) Hierro"]]
pdf_sn = pdf_de_paginas(sin_numeros)
ub_sn = origen_pdf.ubicar_preguntas(pdf_sn, [Q(1, "¿Cuál es el río más largo de Sudamérica?", ["Amazonas", "Orinoco"]),
                                            Q(2, "Pregunta distinta que la IA reescribió por completo", ["x"]),
                                            Q(3, "¿Cuál es el metal líquido a temperatura ambiente?", ["Mercurio", "Hierro"])])
ok(1 not in ub_sn, "sin numeración y con la siguiente sin ubicar → no adivina el final")
ok(3 in ub_sn, "la última de ese documento sí se ubica")

# Páginas de varias columnas
col = []
for i in range(14):
    col.append((ALTO - 90 - i * 40, f"{i + 1}. Pregunta de la columna izquierda número {i + 1} aquí"))
buf = io.BytesIO()
cv = canvas.Canvas(buf, pagesize=letter)
cv.setFont("Helvetica", 11)
for i in range(14):
    y = ALTO - 90 - i * 40
    cv.drawString(60, y, f"{i + 1}. Pregunta de la columna izquierda número {i + 1} aquí")
    cv.drawString(340, y, f"{i + 20}. Pregunta de la columna derecha número {i + 20} acá")
    cv.drawString(60, y - 14, "a) opción uno")
    cv.drawString(340, y - 14, "a) opción uno")
cv.showPage()
cv.save()
dos_col = [Q(i + 1, f"Pregunta de la columna izquierda número {i + 1} aquí", ["opción uno"]) for i in range(14)]
ok(origen_pdf.ubicar_preguntas(buf.getvalue(), dos_col) == {}, "página de dos columnas → no ubica nada")

# Escaneado: una página con solo una imagen
from PIL import Image  # noqa: E402
from reportlab.lib.utils import ImageReader  # noqa: E402
img = Image.new("RGB", (400, 500), "white")
buf2 = io.BytesIO()
cv2 = canvas.Canvas(buf2, pagesize=letter)
for _ in range(3):
    cv2.drawImage(ImageReader(img), 0, 0, width=letter[0], height=letter[1])
    cv2.showPage()
cv2.save()
ok(origen_pdf.ubicar_preguntas(buf2.getvalue(), lista) == {}, "PDF de solo imágenes (escaneado) → {}")

# «Completa:» en el documento y no en el enunciado de la IA (cloze)
pdf_cl = pdf_de_paginas([["Examen", "1. Completa: La capital de Francia es ________ (París / Lyon / Marsella) y su río", "principal es el Sena.",
                          "2. ¿Cuál es el metal líquido a temperatura ambiente?", "a) Mercurio", "b) Hierro"]])
cl = {"num": 1, "type": "cloze", "data": {"text": "La capital de Francia es [A: París / Lyon / Marsella] y su río principal es el Sena."}}
ub_cl = origen_pdf.ubicar_preguntas(pdf_cl, [cl, Q(2, "¿Cuál es el metal líquido a temperatura ambiente?", ["Mercurio", "Hierro"])])
ok(1 in ub_cl and 2 in ub_cl and ub_cl[1]["recuadro"][3] < ub_cl[2]["recuadro"][1] + 1e-6, "cloze: se ubica por lo que va antes del primer hueco, aunque el documento diga «Completa:»")

# ══════════════════════════════════════════════════════════════════════════
print("5. De punta a punta: pipeline.parse_document con la IA simulada")
# ══════════════════════════════════════════════════════════════════════════

_claves = (pipeline.get_api_key, ia_gemini.get_api_key)
pipeline.get_api_key = lambda: "clave-falsa"
ia_gemini.get_api_key = lambda: "clave-falsa"
_extract = pipeline.extract_structured
_missing = pipeline.extract_missing
_ubicar = origen_pdf.ubicar_preguntas
_etiquetar = confianza.etiquetar
_modo = pipeline.NORMALIZER_MODE
pipeline.NORMALIZER_MODE = "json"
llamadas_missing = []
pipeline.extract_missing = lambda *a, **k: llamadas_missing.append(1) or []


def convertir(nombre, payload, con_campos):
    pipeline.extract_structured = lambda *a, **k: copy.deepcopy(payload)
    if con_campos:
        origen_pdf.ubicar_preguntas, confianza.etiquetar = _ubicar, _etiquetar
    else:
        origen_pdf.ubicar_preguntas = lambda *a, **k: {}
        confianza.etiquetar = lambda *a, **k: 0
    try:
        return pipeline.parse_document((SINTETICOS / f"{nombre}.pdf").read_bytes(), f"{nombre}.pdf")
    finally:
        origen_pdf.ubicar_preguntas, confianza.etiquetar = _ubicar, _etiquetar


try:
    payload = xf.perfect_model(exams.BASE_MIXED)
    # La clave explícita del documento en dos preguntas (la 1 es «c) Saturno»), y una de ellas «rescatada».
    payload["preguntas"][0]["clave_texto"] = "c"
    payload["preguntas"][1]["clave_texto"] = "c"
    payload["preguntas"][1]["_rescatada"] = True
    con = convertir("s01_limpio_clave_final", payload, True)
    sin = convertir("s01_limpio_clave_final", payload, False)
    xml_con, _ = build_xml(con["questions"], con["answer_key"])
    xml_sin, _ = build_xml(sin["questions"], sin["answer_key"])
    ok(xml_con == xml_sin, "el XML de Moodle es IDÉNTICO con y sin los campos nuevos (s01)")
    ok([q["num"] for q in con["questions"]] == [q["num"] for q in sin["questions"]] and con["answer_key"] == sin["answer_key"],
       "mismas preguntas y misma clave de respuestas")

    por_num = {q["num"]: q for q in con["questions"]}
    d1, d2 = por_num[1]["data"], por_num[2]["data"]
    ok(d1.get("origen_respuesta") == "documento" and d1.get("confianza") == "alta", "pregunta 1: clave del documento → documento / alta")
    ok(d2.get("origen_respuesta") == "documento" and d2.get("confianza") == "baja", "pregunta 2: rescatada por un reintento → baja, aunque venga de la clave")
    ok(por_num[3]["data"].get("origen_respuesta") == "ia" and por_num[3]["data"].get("confianza") == "media", "pregunta 3 (sin clave ni marca): ia / media")
    ensayos = [q for q in con["questions"] if q["type"] == "essay"]
    ok(ensayos and all("origen_respuesta" not in q["data"] and "confianza" not in q["data"] for q in ensayos), "el ensayo no lleva origen_respuesta ni confianza")
    ok(all(q["data"].get("origen_respuesta") in ("documento", "marca", "ia") and q["data"].get("confianza") in ("alta", "media", "baja")
           for q in con["questions"] if q["type"] != "essay"), "toda pregunta con respuesta lleva un origen y una confianza válidos")
    ok(all("origen_respuesta" not in q["data"] and "recuadro" not in q["data"] for q in sin["questions"]), "con la ubicación y el etiquetado apagados no aparece ningún campo nuevo")
    ok(all("low_confidence" not in q["data"] for q in con["questions"]), "low_confidence sigue igual (no se mezcla con confianza)")

    # La página verificada reemplaza a la de la IA; el recuadro aparece
    equivocada = copy.deepcopy(payload)
    for p in equivocada["preguntas"]:
        p["pagina"] = 2          # la IA dice «página 2» para todas
    r_pag = convertir("s01_limpio_clave_final", equivocada, True)
    ok(all(q["data"].get("page") == 1 for q in r_pag["questions"]), "la página verificada (1) reemplaza a la «2» que dijo la IA")
    ok(all(isinstance(q["data"].get("recuadro"), list) and len(q["data"]["recuadro"]) == 4 for q in r_pag["questions"]), "cada pregunta ubicada lleva su recuadro (4 fracciones)")
    r_sin_ub = convertir("s01_limpio_clave_final", equivocada, False)
    ok(all(q["data"].get("page") == 2 and "recuadro" not in q["data"] for q in r_sin_ub["questions"]), "si no se ubica, queda la página que dijo la IA y no hay recuadro")

    # Los demás PDF: XML idéntico
    for nombre in ("s05_largo_60_preguntas", next(p.stem for p in SINTETICOS.glob("x07_*.pdf"))):
        qs_ex = PARES[nombre]
        pl = xf.perfect_model(qs_ex)
        a = convertir(nombre, pl, True)
        b = convertir(nombre, pl, False)
        xa, _ = build_xml(a["questions"], a["answer_key"])
        xb, _ = build_xml(b["questions"], b["answer_key"])
        ok(xa == xb and len(a["questions"]) > 10, f"{nombre}: XML idéntico con y sin los campos nuevos ({len(a['questions'])} preguntas)")

    # Escaneado (s06): no hay capa de texto; sin recuadros y sin romper
    pipeline.extract_structured = lambda *a, **k: copy.deepcopy(payload)
    origen_pdf.ubicar_preguntas = _ubicar
    pipeline.NORMALIZER_MODE_AI, _m_ai = "json", pipeline.NORMALIZER_MODE_AI
    try:
        r6 = pipeline.normalize_document_with_ai(s06, "s06.pdf")
    finally:
        pipeline.NORMALIZER_MODE_AI = _m_ai
    ok(r6["questions"] and all("recuadro" not in q["data"] for q in r6["questions"]), "PDF escaneado por el camino «normalizar con IA»: sin recuadros, la conversión sigue")
    ok(all(q["data"].get("origen_respuesta") in (None, "ia", "documento", "marca") for q in r6["questions"]), "y los campos de origen se calculan igual")
finally:
    pipeline.get_api_key, ia_gemini.get_api_key = _claves
    pipeline.extract_structured = _extract
    pipeline.extract_missing = _missing
    pipeline.NORMALIZER_MODE = _modo
    origen_pdf.ubicar_preguntas, confianza.etiquetar = _ubicar, _etiquetar

# Preguntas que rescata el reintento de omitidas (_completar_omitidas) llevan la marca
ub_img = imagenes.Ubicaciones(lineas=[
    imagenes.Linea((1, 100.0), "1. ¿Cuál es la capital de Francia?"), imagenes.Linea((1, 114.0), "a) París"),
    imagenes.Linea((1, 140.0), "2. ¿Cuál es el río más largo de Asia?"), imagenes.Linea((1, 154.0), "a) Yangtsé"),
    imagenes.Linea((1, 180.0), "3. ¿Cuál es la capital de Italia?"), imagenes.Linea((1, 194.0), "a) Roma"),
])
payload_om = {"preguntas": [
    {"orden": 1, "tipo": "multichoice", "enunciado": "¿Cuál es la capital de Francia?", "opciones": [{"texto": "París"}]},
    {"orden": 2, "tipo": "multichoice", "enunciado": "¿Cuál es la capital de Italia?", "opciones": [{"texto": "Roma"}]},
]}
_m2 = pipeline.extract_missing
pipeline.extract_missing = lambda frags, imgs, on_retry=None: [
    {"orden": 1, "tipo": "multichoice", "enunciado": "¿Cuál es el río más largo de Asia?", "opciones": [{"letra_original": "a", "texto": "Yangtsé", "correcta": False}]}]
try:
    res = pipeline._completar_omitidas(copy.deepcopy(payload_om), ub_img, [], None)
finally:
    pipeline.extract_missing = _m2
marcadas = [p for p in res["preguntas"] if p.get("_rescatada")]
ok(len(res["preguntas"]) == 3 and len(marcadas) == 1 and "Asia" in marcadas[0]["enunciado"], "_completar_omitidas marca como «_rescatada» solo la pregunta que recuperó")
resc2, _ = confianza.senales_del_payload(res)
ok(len(resc2) == 1, "y senales_del_payload la numera como schema_adapter (por «orden»)")

# ══════════════════════════════════════════════════════════════════════════
print("6. _comprobar_entrada pregunta al proveedor de IA, no a Gemini")
# ══════════════════════════════════════════════════════════════════════════

class ProveedorFalso(ProveedorIA):
    nombre = "falso"

    def __init__(self):
        self.sin_clave = False
        self.comprobaciones = 0

    def comprobar_listo(self):
        self.comprobaciones += 1
        if self.sin_clave:
            raise IASinClaveError("Falta la credencial del proveedor falso.")


falso = ProveedorFalso()
ia_proveedor.registrar_proveedor("falso", lambda: falso)
os.environ["CONVERSOR_PROVEEDOR_IA"] = "falso"
_ia_key = ia_gemini.get_api_key
ia_gemini.get_api_key = lambda: ""          # SIN clave de Gemini
try:
    try:
        pipeline._comprobar_entrada(b"", ".txt")
        listo = True
    except HTTPException:
        listo = False
    ok(listo and falso.comprobaciones == 1, "otro proveedor listo no queda bloqueado por la falta de clave de Gemini")
    falso.sin_clave = True
    try:
        pipeline._comprobar_entrada(b"", ".txt")
        codigo, detalle = None, None
    except HTTPException as exc:
        codigo, detalle = exc.status_code, exc.detail
    ok(codigo == 503 and detalle == "Falta la credencial del proveedor falso.", "si el proveedor no está listo: 503 con SU mensaje")
    os.environ.pop("CONVERSOR_PROVEEDOR_IA", None)
    try:
        pipeline._comprobar_entrada(b"", ".txt")
        codigo, detalle = None, None
    except HTTPException as exc:
        codigo, detalle = exc.status_code, exc.detail
    from config import MISSING_API_KEY_MESSAGE
    ok(codigo == 503 and detalle == MISSING_API_KEY_MESSAGE, "Gemini sin clave: 503 con el MISMO mensaje de siempre (config.MISSING_API_KEY_MESSAGE)")
    os.environ["CONVERSOR_PROVEEDOR_IA"] = "no-existe"
    try:
        pipeline._comprobar_entrada(b"", ".txt")
        codigo = None
    except HTTPException as exc:
        codigo = exc.status_code
    ok(codigo == 503, "proveedor desconocido: 503 con el aviso de configuración (no un error 500)")
finally:
    os.environ.pop("CONVERSOR_PROVEEDOR_IA", None)
    ia_proveedor.quitar_proveedor("falso")
    ia_gemini.get_api_key = _ia_key

print()
print("TODO OK" if not fallas else f"{fallas} FALLA(S)")
sys.exit(1 if fallas else 0)
