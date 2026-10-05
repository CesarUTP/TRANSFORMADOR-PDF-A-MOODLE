"""
test_exportar_pdf.py — Versión 2.1: el examen revisado como PDF imprimible.

    PYTHONUTF8=1 backend/venv/bin/python dev/test_exportar_pdf.py

Sin red ni Gemini. Se lee el PDF de vuelta (pdfplumber) y se dibuja (pypdfium2):
  1. Fórmulas \\( … \\) → Unicode, y que la fuente tenga CADA carácter que se escribe.
  2. Los 25 exámenes sintéticos: el PDF sale, trae todas las preguntas y su clave coincide con
     la que decide el modelo (la misma que usa el XML).
  3. El examen NO trae las respuestas; la clave sola y el examen solo traen lo suyo.
  4. Una pregunta no se parte entre páginas, nada se sale del margen.
  5. Imágenes, fórmulas, caracteres que la fuente no tiene, texto raro (nada se rompe ni se inventa).
  6. La ruta /api/exportar_pdf: token, validación igual que el XML, nombre y cabecera.
"""

import io
import json
import logging
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "dev"))
sys.path.insert(0, str(ROOT / "dev" / "synthetic"))

TMP = Path(tempfile.mkdtemp(prefix="conv pdf "))
os.environ["HOME"] = str(TMP / "home")
os.environ["LOCALAPPDATA"] = str(TMP / "home" / "AppData")
(TMP / "datos" / "data").mkdir(parents=True)
import database  # noqa: E402

database.get_db_path = lambda: TMP / "datos" / "data" / "exams_history.db"  # ANTES de importar main

import pdfplumber  # noqa: E402
import pypdfium2 as pdfium  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFontFile  # noqa: E402

import xml_fidelity as xf  # noqa: E402  (apaga el logging)
import test_xml_baseline as base  # noqa: E402
import exportar_pdf as ep  # noqa: E402
import latex_texto as lt  # noqa: E402
import main  # noqa: E402
import seguridad  # noqa: E402
from modelo import Clave, Pregunta  # noqa: E402
from schema_adapter import adapt  # noqa: E402
from validator import partition_questions  # noqa: E402

logging.disable(logging.CRITICAL)
fallas = 0


def ok(cond, msg):
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


def paginas_de(pdf: bytes) -> list:
    with pdfplumber.open(io.BytesIO(pdf)) as d:
        return [p.extract_text() or "" for p in d.pages]


def texto_de(pdf: bytes) -> str:
    return "\n".join(paginas_de(pdf))


def plano(s: str) -> str:
    return " ".join(s.split())


def mc(n, stem, opciones, correctas, **extra):
    letras = "ABCDEFGHIJ"
    q = {"num": n, "type": "multichoice", "data": {"stem": stem, "options": {letras[i]: o for i, o in enumerate(opciones)}, **extra}}
    return q, {"type": "multichoice", "answer": " | ".join(letras[i] for i in correctas)}


def pdf_de(qs, key, total=20, **kw):
    return ep.generar_pdf(qs, key, total, ep.DatosExamen(**kw))


# ══════════════════════════════════════════════════════════════════════════
print("1. Fórmulas a texto y cobertura de la fuente")
# ══════════════════════════════════════════════════════════════════════════
casos = {
    r"Si \(x^2 + \alpha \leq 3\)": "Si x² + α ≤ 3", r"\(\frac{1}{2}\)": "½", r"\(\frac{x^2}{2}\)": "x²/2",
    r"\(\frac{a+b}{c}\)": "(a+b)/c", r"\(\sqrt{3}\) y \(\sqrt[3]{8}\)": "√3 y ∛8", r"\(H_2O\)": "H₂O",
    r"\(e^{-x}\)": "e^(-x)", r"\(a_{n+1}\)": "aₙ₊₁", r"\(\int_0^1 x\,dx\)": "∫₀¹ x dx", r"\(\mathbb{R}\)": "ℝ",
    r"\(x \to \infty\)": "x → ∞", r"\(\{1,2\}\)": "{1,2}", r"\(\text{si } x>0\)": "si x>0",
    "sin fórmulas ni nada raro": "sin fórmulas ni nada raro",
}
for entrada, esperado in casos.items():
    ok(lt.formulas_a_texto(entrada)[0] == esperado, f"{entrada!r} → {esperado!r}")
for dificil in (r"\(\begin{matrix}1\\2\end{matrix}\)", r"\(\hat{x}\)", r"\(\frac{1}{\sqrt{x}\)", r"\(\foo{3}\)", r"\(x^\)"):
    salida, n_ok, n_crudas = lt.formulas_a_texto(dificil)
    ok(salida == dificil and n_crudas == 1 and n_ok == 0, f"lo que no se entiende queda tal cual: {dificil!r}")
font = TTFontFile(str(ROOT / "backend" / "fuentes" / "DejaVuSans.ttf"))
faltan = [c for c in lt.simbolos_usados() if ord(c) not in font.charToGlyph]
ok(not faltan, f"DejaVu Sans tiene los {len(lt.simbolos_usados())} símbolos que escribe el conversor ({faltan})")
ok(all(ord(c) in font.charToGlyph for c in "áéíóúüñÁÉÍÓÚÜÑ¿¡«»—–·…°±×÷≤≥≠≈→←✓"), "y las letras y signos del español")

# ══════════════════════════════════════════════════════════════════════════
print("2. Los 25 exámenes sintéticos: preguntas completas y clave igual a la del modelo")
# ══════════════════════════════════════════════════════════════════════════
t0 = time.time()
total_pdfs = 0
for nombre, qs in base.bancos().items():
    questions, key = adapt(xf.perfect_model(qs))
    validas, _ = partition_questions(questions, key)
    if not validas:
        continue
    r = pdf_de(validas, key, materia="Prueba", docente="Docente de prueba")
    paginas = paginas_de(r.pdf)
    t = "\n".join(paginas)
    total_pdfs += 1
    problemas = []
    if r.preguntas != len(validas):
        problemas.append(f"{r.preguntas} de {len(validas)} preguntas")
    if r.avisos:
        problemas.append(f"avisos {r.avisos}")
    corte = t.index("CLAVE DE RESPUESTAS")
    examen, clave = t[:corte], t[corte:]
    for q in validas:
        p = Pregunta.desde_dict(q)
        p.respuesta = Clave.desde_dict(key[q["num"]])
        if q["type"] == "multichoice":
            letras, _ = p.resolver_correctas()
            for L in letras:
                texto = plano(q["data"]["options"][L])
                if texto and texto not in plano(clave):
                    problemas.append(f"clave sin la opción correcta de la pregunta {q['num']}: {texto[:30]!r}")
                    break
    for i in range(1, len(validas) + 1):
        if not re.search(rf"(?m)^{i}\.", examen) or not re.search(rf"(?m)^{i}\.", clave):
            problemas.append(f"falta la pregunta {i} en el examen o en la clave")
            break
    ok(not problemas, f"{nombre}: {len(validas)} preguntas, {r.paginas} págs {problemas or ''}")
ok(total_pdfs >= 20, f"se probaron {total_pdfs} exámenes en {time.time() - t0:.1f} s")

# ══════════════════════════════════════════════════════════════════════════
print("3. El examen no trae las respuestas; la clave sola y el examen solo traen lo suyo")
# ══════════════════════════════════════════════════════════════════════════
pares = [mc(n, f"Enunciado TOK{n}", [f"TOK{n}NO1", f"TOK{n}OK", f"TOK{n}NO2"], [1]) for n in range(1, 13)]
qs, key = [p[0] for p in pares], {p[0]["num"]: p[1] for p in pares}
vf = {"num": 13, "type": "truefalse", "data": {"stem": "Afirmación TOK13"}}
qs.append(vf); key[13] = {"type": "truefalse", "answer": "Falso"}
cierre = {"num": 14, "type": "cloze", "data": {"text": "Completa TOK14 [A: TOK14OK / TOK14NO1 / TOK14NO2] fin."}}
qs.append(cierre); key[14] = {"type": "cloze", "answer": "A. TOK14OK"}
casa = {"num": 15, "type": "matching", "data": {"stem": "Une TOK15", "col_a": {"1": "izqTOK15a", "2": "izqTOK15b"},
                                                   "col_b": {"a": "derTOK15a", "b": "derTOK15b"}}}
qs.append(casa); key[15] = {"type": "matching", "answer": "1-b; 2-a", "pairs": {"1": "b", "2": "a"}}

e = pdf_de(qs, key, contenido="solo_examen")
te = texto_de(e.pdf)
ok("CLAVE DE RESPUESTAS" not in te and "CLAVE" not in te, "solo_examen: no hay página de clave")
ok(all(f"TOK{n}OK" in te and f"TOK{n}NO1" in te for n in range(1, 13)), "solo_examen: todas las opciones están, sin marcar")
ok("Verdadero" in te and "Falso" in te and "Afirmación TOK13" in te, "solo_examen: el V/F muestra sus dos opciones")
ok(te.index("TOK14OK") != te.index("TOK14NO1") and set(re.findall(r"TOK14\w+", te)) >= {"TOK14OK", "TOK14NO1", "TOK14NO2"},
   "solo_examen: el «Completar» lista todas sus opciones")
ok("derTOK15a" in te and "derTOK15b" in te, "solo_examen: el emparejamiento trae ambas columnas")
m_ex = re.search(r"([a-z])\) TOK14OK", te)
primera = re.search(r"a\) (TOK14\w+)", te).group(1)
ok(m_ex is not None and primera != "TOK14OK", f"las opciones del «Completar» van con letra y la correcta no va siempre primera (a: {primera})")
ok(re.search(r"\(1\)\s+" + m_ex.group(1) + r"\) TOK14OK", texto_de(pdf_de(qs, key, contenido="solo_clave").pdf)) is not None,
   f"la clave del «Completar» usa la MISMA letra que el examen ({m_ex.group(1)})")
ok(texto_de(pdf_de(qs, key, contenido="solo_examen").pdf).count("TOK14") == te.count("TOK14"), "y siempre salen en el mismo orden")

c = pdf_de(qs, key, contenido="solo_clave")
tc = texto_de(c.pdf)
ok("CLAVE DE RESPUESTAS" in tc and all(f"TOK{n}OK" in tc for n in range(1, 13)), "solo_clave: las respuestas correctas están")
ok(not any(f"TOK{n}NO" in tc for n in range(1, 13)), "solo_clave: ninguna opción incorrecta")
ok("Selecciona una." not in tc and "Respuesta: ____" not in tc and c.paginas < e.paginas, "solo_clave: no repite el examen")
ley = re.search(r"([a-z])\) derTOK15b", te).group(1)        # la letra con que salió impresa la pareja del elemento 1
ok(f"izqTOK15a → {re.search(r'([a-z])[)] derTOK15a', te).group(1)})" in tc.replace("  ", " ") or f"→ {ley})" in tc.replace("  ", " "), f"la clave del emparejamiento une cada elemento con la letra IMPRESA de su pareja ({ley})")
ok("TOK14OK" in tc and "TOK14NO1" not in tc, "la clave del «Completar» solo dice la correcta")

j = pdf_de(qs, key)
tj = paginas_de(j.pdf)
ultima_examen = max(i for i, p in enumerate(tj) if "Enunciado TOK12" in p and "CLAVE DE RESPUESTAS" not in p)
primera_clave = min(i for i, p in enumerate(tj) if "CLAVE DE RESPUESTAS" in p)
ok(primera_clave > ultima_examen and "Afirmación TOK13" not in tj[primera_clave].split("CLAVE DE RESPUESTAS")[0], "examen y clave: la clave empieza en página aparte")
ok(not any("TOK1NO" in p and "CLAVE DE RESPUESTAS" in p for p in tj[primera_clave:]), "…y no mezcla opciones incorrectas con la clave")
ok(f"Página 1 de {primera_clave}" in tj[0].replace("\n", " ") and f"Página 1 de {j.paginas - primera_clave}" in tj[primera_clave].replace("\n", " "),
   f"cada sección numera sus páginas (el examen «Página 1 de {primera_clave}», la clave «Página 1 de {j.paginas - primera_clave}»)")

# ══════════════════════════════════════════════════════════════════════════
print("4. Maquetación: preguntas enteras, márgenes, papel")
# ══════════════════════════════════════════════════════════════════════════
grandes = [mc(n, f"Enunciado BLOQ{n:03d} " + "texto " * 10, [f"BLOQ{n:03d}opt{L}" for L in "ABCD"], [n % 4]) for n in range(1, 80)]
qs2, key2 = [g[0] for g in grandes], {g[0]["num"]: g[1] for g in grandes}
r = pdf_de(qs2, key2, contenido="solo_examen")
pags = paginas_de(r.pdf)
partidas = []
for n in range(1, 80):
    donde = {i for i, p in enumerate(pags) if f"BLOQ{n:03d}" in p}
    if len(donde) != 1:
        partidas.append(n)
ok(not partidas and len(pags) >= 3, f"79 preguntas en {len(pags)} páginas y ninguna partida entre dos ({partidas})")
with pdfplumber.open(io.BytesIO(r.pdf)) as d:
    ancho, alto = d.pages[0].width, d.pages[0].height
    fuera = [(i, round(w["x0"]), round(w["x1"])) for i, p in enumerate(d.pages) for w in p.extract_words()
             if w["x0"] < 53.5 or w["x1"] > p.width - 53.5 or w["bottom"] > p.height - 20]   # márgenes «moderados» (1,91 cm)
lg = pdf_de(qs2[:5], key2, papel="legal")
with pdfplumber.open(io.BytesIO(lg.pdf)) as d:
    ok(abs(d.pages[0].width - 612) < 1 and abs(d.pages[0].height - 1008) < 1, "Legal (21,59 x 35,56 cm) si se pide")
ok(abs(ancho - 612) < 1 and abs(alto - 792) < 1, f"papel Carta por defecto ({ancho:.0f}x{alto:.0f})")
ok(not fuera, f"ninguna palabra fuera de los márgenes ({fuera[:3]})")
import base64 as _b64
_buf = io.BytesIO(); Image.new("RGB", (60, 60), (30, 90, 200)).save(_buf, "PNG"); logo_demo = _b64.b64encode(_buf.getvalue()).decode()
for nombre_m, (m_ar, m_ab, m_iz, m_de) in ep.MARGENES.items():
    c28 = 72 / 2.54
    rm_ = pdf_de(qs2[:40], key2, margenes=nombre_m, logo_izquierdo=logo_demo, logo_derecho=logo_demo, contenido="folleto_hoja_clave")
    with pdfplumber.open(io.BytesIO(rm_.pdf)) as d:
        malas = []
        for i, pg in enumerate(d.pages):
            ws_ = pg.extract_words()
            malas += [(i, round(w["x0"]), round(w["x1"])) for w in ws_ if w["x0"] < m_iz * c28 - 1 or w["x1"] > pg.width - m_de * c28 + 1 or w["bottom"] > pg.height - 4]
            lineas_ = sorted({round(w["top"]) for w in ws_})
            if i == 1 and len(lineas_) > 2:                   # el encabezado corrido no pisa el texto
                cab = max(w["bottom"] for w in ws_ if round(w["top"]) == lineas_[0])
                if cab + 1 >= lineas_[1]:
                    malas.append((i, "encabezado pisa el texto"))
            imgs_ = [im for im in pg.images if im["x1"] > pg.width - m_de * c28 + 1 or im["x0"] < m_iz * c28 - 1]
            malas += [(i, "imagen fuera") for _ in imgs_]
    ok(not malas, f"márgenes «{nombre_m}» ({m_ar}/{m_iz} cm): nada fuera, ni el encabezado ni el pie, con logos y hoja de respuestas ({malas[:2]})")
with pdfplumber.open(io.BytesIO(pdf_de(qs2[:3], key2, margenes="estrechos").pdf)) as d:
    ok(min(w["x0"] for w in d.pages[0].extract_words()) < 40, "«Estrechos» (1,27 cm) de verdad usa más hoja que «Moderados»")
with pdfplumber.open(io.BytesIO(pdf_de(qs2[:3], key2, margenes="anchos").pdf)) as d:
    ok(min(w["x0"] for w in d.pages[0].extract_words()) > 140, "«Anchos» (5,08 cm a los lados) deja los lados anchos")
ok(len(paginas_de(pdf_de(qs2, key2, margenes="estrechos", contenido="solo_examen").pdf)) < len(paginas_de(pdf_de(qs2, key2, margenes="anchos", contenido="solo_examen").pdf)), "con márgenes estrechos caben más preguntas por página")
a4 = pdf_de(qs2[:5], key2, papel="a4")
with pdfplumber.open(io.BytesIO(a4.pdf)) as d:
    ok(abs(d.pages[0].width - 595.3) < 1 and abs(d.pages[0].height - 841.9) < 1, "A4 si se pide")
hoja = pdfium.PdfDocument(r.pdf)[0].render(scale=0.5).to_pil().convert("L")
oscuros = sum(1 for px in hoja.tobytes() if px < 128)
ok(oscuros > 200, f"la página 1 se dibuja con contenido ({oscuros} píxeles oscuros)")

largo = [mc(1, "Pregunta larga " + "palabra " * 700, ["A" * 150 + " " + "B" * 150, "C" * 500, "otra"], [0])]
r = pdf_de([largo[0][0]], {1: largo[0][1]})
ok(r.paginas >= 2 and len(r.pdf) > 1000, f"una pregunta de varias páginas no rompe la maquetación ({r.paginas} págs)")
palabra = mc(1, "Una_sola_palabra_muy_larga_sin_espacios_" * 12, ["x" * 400, "y"], [0])
with pdfplumber.open(io.BytesIO(pdf_de([palabra[0]], {1: palabra[1]}).pdf)) as d:
    ok(all(w["x1"] <= d.pages[0].width - 53.5 for w in d.pages[0].extract_words()), "una palabra sin espacios se parte en vez de salirse de la hoja")

t0 = time.time()
muchas = [mc(n, f"Pregunta {n} con su enunciado", ["uno", "dos", "tres", "cuatro"], [n % 4]) for n in range(1, 151)]
rr = pdf_de([m[0] for m in muchas], {m[0]["num"]: m[1] for m in muchas})
ok(time.time() - t0 < 5 and rr.paginas > 5, f"150 preguntas en {time.time() - t0:.2f} s ({rr.paginas} págs, {len(rr.pdf) // 1024} KB)")
with pdfplumber.open(io.BytesIO(rr.pdf)) as d:
    palabras = [w for pg in d.pages for w in pg.extract_words()]
n100 = next(w for w in palabras if w["text"] == "100.")
sig = min((w for w in palabras if abs(w["top"] - n100["top"]) < 3 and w["x0"] > n100["x0"]), key=lambda w: w["x0"])
ok(sig["x0"] - n100["x1"] > 1.5, f"el número de pregunta de tres cifras no se monta sobre el enunciado ({sig['x0'] - n100['x1']:.1f} pt de espacio)")

# ══════════════════════════════════════════════════════════════════════════
print("   Una sola línea para el docente y «Completar» legible")
def linea_docente(nombre, **kw):
    with pdfplumber.open(io.BytesIO(pdf_de(qs2[:3], key2, contenido="solo_examen", docente=nombre, **kw).pdf)) as d:
        ws = d.pages[0].extract_words()
    fac = next(w for w in ws if w["text"] == "FACILITADOR:")
    misma = [w for w in ws if abs(w["top"] - fac["top"]) < 3]
    return fac, misma, ws
fac, misma, ws = linea_docente("Ing. César O. González C.")
ok(any(w["text"].startswith("C.") for w in misma) and any(w["text"].startswith("CALIFICACI") for w in misma), "el nombre normal y la calificación van en la misma línea")
largo = "Ing. Ana María de los Ángeles Fernández Rodríguez"
fac, misma, ws = linea_docente(largo)
ok(any(w["text"].startswith("Rodríguez") for w in misma) and not any(w["top"] > fac["top"] + 3 and w["top"] < fac["top"] + 14 for w in ws), "un nombre largo achica la letra pero sigue en una sola línea")
fac, misma, ws = linea_docente("X" * 300)
ok(any("…" in w["text"] for w in misma) and any(w["text"].startswith("CALIFICACI") for w in misma), "uno absurdo se corta con «…» sin saltar de línea")
fac, misma, ws = linea_docente(largo, campos_estudiante=False, grupo="3A", fecha="1 de enero")
ok(any(w["text"].startswith("enero") for w in misma) or any("…" in w["text"] for w in misma), "sin cuadro, docente, grupo y fecha también en una línea")

cl = {"num": 1, "type": "cloze", "data": {"text": "El [A: " + " / ".join(f"opción larga número {i} del primer espacio" for i in range(1, 5)) + "] y el [B: sí / no] y escribe [C: Panamá]."}}
rc = pdf_de([cl], {1: {"type": "cloze", "answer": "A. opción larga número 2 del primer espacio; B. no; C. Panamá"}}, contenido="solo_examen")
tcl = texto_de(rc.pdf)
ok(all(f"{x}) opción larga número" in tcl for x in "abcd"), "las opciones largas van una por línea con su letra")
ok(re.search(r"a\) \w+\s+b\) \w+", tcl) is not None, "las opciones cortas van juntas en una línea")
ok(re.search(r"\(3\)\s+_{15,}", tcl) is not None and re.search(r"\(1\)\s+_{5,}", tcl) is not None, "el espacio de escribir lleva una raya larga y el de elegir, un hueco para la letra")
ok("ESCRIBA EN CADA ESPACIO CON OPCIONES LA LETRA" in tcl and "Escribe en cada espacio la letra" not in tcl, "la indicación de la parte distingue espacios con opciones y espacios de escribir (y no se repite en la pregunta)")
rs = pdf_de([cl], {1: {"type": "cloze", "answer": "A. opción larga número 2 del primer espacio; B. no; C. Panamá"}}, contenido="solo_examen", partes=False)
ok("Escribe en cada" in texto_de(rs.pdf) or "En los espacios con opciones" in texto_de(rs.pdf), "sin partes, la ayuda va en cada pregunta como antes")
ok("3." not in tcl.split("Escribe")[-1], "el espacio de escribir no genera lista")
ok(re.search(r"(?m)^1\. a\)", tcl) and re.search(r"(?m)^2\. a\)", tcl), "las listas se numeran 1., 2. y sus opciones a), b)")

# ══════════════════════════════════════════════════════════════════════════
print("   Partes del examen")
mezcla = [
    {"num": 1, "type": "essay", "data": {"stem": "ENS-UNO"}}, mc(2, "MC-UNO", ["a", "b"], [0])[0], {"num": 3, "type": "truefalse", "data": {"stem": "TF-UNO"}},
    mc(4, "MC-DOS", ["a", "b"], [1])[0], {"num": 5, "type": "truefalse", "data": {"stem": "TF-DOS"}},
    {"num": 6, "type": "shortanswer", "data": {"stem": "SA-UNO"}}, {"num": 7, "type": "numerical", "data": {"stem": "NU-UNO"}},
    {"num": 8, "type": "matching", "data": {"stem": "MT-UNO", "col_a": {"1": "x"}, "col_b": {"a": "y"}}}]
mezcla[1]["points"] = 4; mezcla[3]["points"] = 6; mezcla[0]["points"] = 10
for i, q in enumerate(mezcla):
    q.setdefault("points", 5)
kmez = {1: {"type": "essay", "answer": ""}, 2: {"type": "multichoice", "answer": "A"}, 3: {"type": "truefalse", "answer": "Verdadero"},
        4: {"type": "multichoice", "answer": "B"}, 5: {"type": "truefalse", "answer": "Falso"}, 6: {"type": "shortanswer", "answer": "uno"},
        7: {"type": "numerical", "answer": "3"}, 8: {"type": "matching", "answer": "1-a", "pairs": {"1": "a"}}}
rm = pdf_de(mezcla, kmez, contenido="solo_examen")
tm = plano(texto_de(rm.pdf))
orden = [tm.index(x) for x in ("I PARTE: DESARROLLO", "II PARTE: SELECCIÓN MÚLTIPLE", "III PARTE: VERDADERO O FALSO", "IV PARTE: RESPUESTA CORTA",
                               "V PARTE: RESPUESTA NUMÉRICA", "VI PARTE: EMPAREJAMIENTO")]
ok(orden == sorted(orden), "las partes siguen el orden en que aparece cada tipo y se numeran con romanos")
ok("II PARTE: SELECCIÓN MÚLTIPLE: MARQUE CON UNA X EL CÍRCULO DE LA OPCIÓN QUE USTED CONSIDERE COMO RESPUESTA CORRECTA. VALOR: 10 PTS" in tm,
   "cada parte lleva su indicación y su valor (suma de sus preguntas)")
ok("VALOR: 10 PTS" in tm.split("III PARTE")[0] and "III PARTE: VERDADERO O FALSO: MARQUE CON UNA X EL CÍRCULO DE «VERDADERO» O «FALSO», SEGÚN CORRESPONDA. VALOR: 10 PTS" in tm,
   "…y el valor de las preguntas agrupadas se suma")
ok(tm.index("MC-UNO") < tm.index("MC-DOS") < tm.index("TF-UNO") and tm.index("MC-DOS") < tm.index("TF-UNO"), "las preguntas del mismo tipo quedan juntas")
ok(all(re.search(rf"(?m)^{i}\.", texto_de(rm.pdf)) for i in range(1, 9)), "la numeración sigue corrida de 1 a 8")
ok("Selecciona una." not in tm, "la ayuda por pregunta ya no se repite cuando hay indicación de parte")
mixto = [mc(1, "UNA-SOLA", ["a", "b"], [0])[0], mc(2, "VARIAS", ["a", "b", "c"], [0, 1])[0]]
tmx = plano(texto_de(pdf_de(mixto, {1: {"type": "multichoice", "answer": "A"}, 2: {"type": "multichoice", "answer": "A | B"}}, contenido="solo_examen").pdf))
ok("CÍRCULO (UNA SOLA RESPUESTA) O EL CUADRO" in tmx and "Selecciona todas las que correspondan." in tmx, "una parte con preguntas de una y de varias respuestas lo dice y conserva la ayuda por pregunta")
sueltos = []
for relleno in range(1, 15):          # el título de la parte cae en distintos puntos de la hoja
  for extra in range(0, 4):           # …y con distinto sobrante al pie (el enunciado del último relleno crece)
    qsr = [mc(k, f"RELLENO{k:02d} " + "texto " * (12 + (extra * 14 if k == relleno else 0)), ["a", "b", "c", "d"], [0])[0] for k in range(1, relleno + 1)]
    keyr = {q["num"]: {"type": "multichoice", "answer": "A"} for q in qsr}
    qsr.append({"num": relleno + 1, "type": "matching", "data": {"stem": "PRIMERAEMPAREJ", "col_a": {str(j): f"x{j}" for j in range(1, 6)}, "col_b": {c: "y" for c in "abcde"}}})
    keyr[relleno + 1] = {"type": "matching", "answer": "1-a; 2-b; 3-c; 4-d; 5-e", "pairs": {"1": "a", "2": "b", "3": "c", "4": "d", "5": "e"}}
    for contenido in ("solo_examen", "solo_clave"):
        for i, pg in enumerate(paginas_de(pdf_de(qsr, keyr, contenido=contenido).pdf)):
            if "II PARTE" in pg and "PRIMERAEMPAREJ" not in pg:
                sueltos.append((relleno, extra, contenido, i + 1))
ok(not sueltos, f"el título de una parte nunca queda solo al final de una hoja ({sueltos[:3]})")
tcm = plano(texto_de(pdf_de(mezcla, kmez, contenido="solo_clave").pdf))
ok("I PARTE: DESARROLLO VALOR" in tcm and "II PARTE: SELECCIÓN MÚLTIPLE VALOR: 10 PTS" in tcm and "MARQUE" not in tcm, "la clave sigue las mismas partes, sin las indicaciones")
sp = plano(texto_de(pdf_de(mezcla, kmez, contenido="solo_examen", partes=False).pdf))
ok("PARTE:" not in sp and sp.index("ENS-UNO") < sp.index("MC-UNO") < sp.index("TF-UNO") < sp.index("MC-DOS"), "sin partes: el orden del editor y sin encabezados")

print("   Folleto, hoja de respuestas y clave")
def tiene_relleno(pagina):
    objetos = list(pagina.curves) + list(pagina.rects)
    return sum(1 for o in objetos if o.get("fill") and o.get("non_stroking_color") in ((0,), (0, 0, 0), [0], [0, 0, 0], 0, (0.0, 0.0, 0.0), (0.0,)))
fq = [mc(1, "FOLL-MC1", ["a1", "b1", "c1"], [0])[0], mc(2, "FOLL-MC2", ["a2", "b2", "c2"], [2])[0], mc(3, "FOLL-MC3", ["a3", "b3", "c3"], [1])[0],
      mc(4, "FOLL-MULTI", ["a4", "b4", "c4"], [0, 2])[0],
      {"num": 5, "type": "truefalse", "data": {"stem": "FOLL-TF1"}}, {"num": 6, "type": "truefalse", "data": {"stem": "FOLL-TF2"}},
      {"num": 7, "type": "matching", "data": {"stem": "FOLL-MT", "col_a": {"1": "izq1", "2": "izq2"}, "col_b": {"a": "der-a", "b": "der-b"}}},
      {"num": 8, "type": "cloze", "data": {"text": "FOLL-CL [A: TOKOK / TOKNO1 / TOKNO2] y [B: Panamá]"}},
      {"num": 9, "type": "shortanswer", "data": {"stem": "FOLL-SA"}}, {"num": 10, "type": "numerical", "data": {"stem": "FOLL-NU"}},
      {"num": 11, "type": "essay", "data": {"stem": "FOLL-ES", "feedback": "ORIENTA-FOLL"}}]
fk = {1: {"type": "multichoice", "answer": "A"}, 2: {"type": "multichoice", "answer": "C"}, 3: {"type": "multichoice", "answer": "B"},
      4: {"type": "multichoice", "answer": "A | C"}, 5: {"type": "truefalse", "answer": "Verdadero"}, 6: {"type": "truefalse", "answer": "Falso"},
      7: {"type": "matching", "answer": "1-b; 2-a", "pairs": {"1": "b", "2": "a"}}, 8: {"type": "cloze", "answer": "A. TOKOK; B. Panamá"},
      9: {"type": "shortanswer", "answer": "RESP-CORTA"}, 10: {"type": "numerical", "answer": "42"}, 11: {"type": "essay", "answer": ""}}
rf = pdf_de(fq, fk, contenido="folleto_hoja_clave", docente="Ana", grupo="3A", instrucciones="Sin calculadora.")
pf = paginas_de(rf.pdf)
i_hoja = next(i for i, g in enumerate(pf) if "HOJA DE RESPUESTAS" in g and "NOMBRE:" in g)
i_clave = next(i for i, g in enumerate(pf) if "CLAVE DE RESPUESTAS" in g and i > i_hoja)
folleto, hoja, clave = pf[:i_hoja], pf[i_hoja:i_clave], pf[i_clave:]
tf_, th_, tk_ = plano("\n".join(folleto)), plano("\n".join(hoja)), plano("\n".join(clave))
ok(i_hoja >= 1 and i_clave > i_hoja, f"tres secciones, cada una en su página: folleto {len(folleto)}, hoja {len(hoja)}, clave {len(clave)}")
ok(all(x in tf_ for x in ("FOLL-MC1", "FOLL-TF1", "FOLL-MT", "FOLL-CL", "FOLL-SA", "FOLL-ES", "Sin calculadora.", "NO ESCRIBA EN ESTE FOLLETO")), "el folleto trae todas las preguntas y las indicaciones")
ok("NOMBRE:" not in tf_ and "CÉDULA" not in tf_ and "CALIFICACIÓN" not in tf_ and "FECHA:" not in tf_, "el folleto no tiene nombre, cédula ni calificación")
ok("Respuesta:" not in tf_ and "______ 1." not in tf_ and "Verdadero" not in tf_, "…ni espacios para responder")
ok("HOJA DE RESPUESTAS" in tf_ and "MARQUE EN LA HOJA DE RESPUESTAS «V»" in tf_ and "EN LA HOJA DE RESPUESTAS LA LETRA DE LA COLUMNA B" in tf_, "las indicaciones de cada parte remiten a la hoja de respuestas")
ok(all(x in th_ for x in ("NOMBRE:", "CÉDULA:", "GRUPO: 3A", "CALIFICACIÓN:")) and "FOLL-" not in th_, "la hoja de respuestas lleva el cuadro del estudiante y NO repite las preguntas")
ok(tiene_relleno(pdfplumber.open(io.BytesIO(rf.pdf)).pages[i_hoja]) == 0, "la hoja de respuestas para llenar no trae nada relleno")
ok(tiene_relleno(pdfplumber.open(io.BytesIO(rf.pdf)).pages[i_clave]) == 3 + 2 + 2, "la clave rellena una burbuja por respuesta (3 simples, 2 de verdadero/falso y 2 de la múltiple)")
ok("CLAVE" in tk_ and "NOMBRE:" in tk_, "la clave es la hoja de respuestas con «CLAVE» como nombre")
orden_cloze = re.findall(r"([a-z])\) (TOK\w+)", tf_)
letra_ok = next(le for le, tx in orden_cloze if tx == "TOKOK")
ok(re.search(r"\(1\)\s*" + letra_ok + r"\s", tk_) is not None and "(2) Panamá" in tk_.replace("  ", " "), f"la clave del «Completar» escribe la MISMA letra que el folleto ({letra_ok}) y el texto del espacio libre")
let_b = re.search(r"([a-z])\) der-b", tf_).group(1); let_a = re.search(r"([a-z])\) der-a", tf_).group(1)
ok(re.search(r"1\.\s*" + let_b + r"\s+2\.\s*" + let_a, tk_) is not None, f"la clave del emparejamiento escribe la letra impresa de cada elemento (1→{let_b}, 2→{let_a})")
ok("RESP-CORTA" in tk_ and "42" in tk_ and "ORIENTA-FOLL" in tk_, "la clave trae la respuesta corta, la numérica y la orientación del desarrollo")
ok("Página 1 de" in pf[0] and f"Página 1 de {len(hoja)}" in hoja[0].replace("\n", " ") and f"Página 1 de {len(clave)}" in clave[0].replace("\n", " "), "cada sección numera sus páginas")
ok(len(paginas_de(pdf_de(fq, fk, contenido="folleto_hoja_clave", partes=False).pdf)) >= 3, "también sin dividir en partes")
cli_pdf = pdf_de(fq, fk, contenido="folleto_hoja_clave", campos_estudiante=False)
ok("NOMBRE:" not in texto_de(cli_pdf.pdf) and "HOJA DE RESPUESTAS" in texto_de(cli_pdf.pdf), "sin cuadro de estudiante, la hoja no lo lleva (y sigue siendo la hoja)")

print("   Orden mezclado: la clave no forma un patrón")
def pareos(n_pares, **kw):
    q = {"num": 1, "type": "matching", "data": {"stem": "MEZ-PAREO", "col_a": {str(i): f"item{i}" for i in range(1, n_pares + 1)},
                                                 "col_b": {chr(96 + i): f"pareja{i}" for i in range(1, n_pares + 1)}}}
    k = {1: {"type": "matching", "answer": "; ".join(f"{i}-{chr(96 + i)}" for i in range(1, n_pares + 1)),
             "pairs": {str(i): chr(96 + i) for i in range(1, n_pares + 1)}}}      # el documento trae 1-a, 2-b, 3-c…
    return pdf_de([q], k, **kw)
for n_p in (3, 5, 8):
    r_ = pareos(n_p, contenido="folleto_hoja_clave")
    pg_ = paginas_de(r_.pdf)
    ex = plano("\n".join(pg_[:next(i for i, g in enumerate(pg_) if "HOJA DE RESPUESTAS" in g and "NOMBRE:" in g)]))
    letra_de = {int(m.group(2)): m.group(1) for m in re.finditer(r"([a-z])\) pareja(\d+)", ex)}       # letra impresa de cada pareja
    clave_ = plano(pg_[-1]) if "CLAVE" in pg_[-1] else plano("\n".join(pg_))
    dada = [re.search(rf"(?<![\d])({i})\.\s*([a-z])\b", clave_.split("CLAVE DE RESPUESTAS")[-1]) for i in range(1, n_p + 1)]
    seq = [ord(letra_de[i]) - 96 for i in range(1, n_p + 1)]
    ok(seq != sorted(seq) and seq != sorted(seq, reverse=True) and sum(1 for i, s_ in enumerate(seq, 1) if i == s_) <= n_p // 3,
       f"{n_p} pares con la clave del documento 1-a, 2-b…: las respuestas impresas son {''.join(map(chr, [96 + x for x in seq]))} (sin patrón)")
    ok(all(d_ and d_.group(2) == letra_de[i] for i, d_ in enumerate(dada, 1)), f"…y la clave/hoja llena escribe esas mismas letras ({n_p} pares)")
sin = plano(texto_de(pareos(5, contenido="solo_examen", mezclar=False).pdf))
ok(all(f"{chr(96 + i)}) pareja{i}" in sin for i in range(1, 6)), "con «mezclar» desactivado la Columna B sale en el orden del documento")
ok(texto_de(pareos(5, contenido="solo_examen").pdf) == texto_de(pareos(5, contenido="solo_examen").pdf), "el mismo examen sale siempre con el mismo orden")

mcs = [mc(k, f"MEZ-MC{k:02d}", [f"opcion{k}A", f"opcion{k}B", f"opcion{k}C", f"opcion{k}D"], [0])[0] for k in range(1, 31)]        # la correcta SIEMPRE es la A del documento
kmc = {q["num"]: {"type": "multichoice", "answer": "A"} for q in mcs}
rmc = pdf_de(mcs, kmc, contenido="folleto_hoja_clave")
pmc_ = paginas_de(rmc.pdf)
i_h = next(i for i, g in enumerate(pmc_) if "HOJA DE RESPUESTAS" in g and "NOMBRE:" in g)
ex_mc = plano("\n".join(pmc_[:i_h]))
impresa = [re.search(rf"([A-D])\) opcion{k}A", ex_mc).group(1) for k in range(1, 31)]
ok(len(set(impresa)) >= 3 and impresa != sorted(impresa) and impresa.count("A") < 20, f"30 preguntas con la correcta siempre en A: impresas {''.join(impresa)} (sin patrón)")
clave_mc = pdf_de(mcs, kmc, contenido="solo_clave")
tcl_ = plano(texto_de(clave_mc.pdf))
ok(all(re.search(rf"\b{impresa[k - 1]}\) opcion{k}A", tcl_) for k in range(1, 31)), "la clave dice la letra IMPRESA de la opción correcta, con su texto")
with pdfplumber.open(io.BytesIO(rmc.pdf)) as d_:
    ok(tiene_relleno(d_.pages[i_h]) == 0, "la hoja de respuestas para llenar sigue en blanco")
sm = pdf_de(mcs[:3], kmc, contenido="solo_examen", mezclar=False)
ok(all(re.search(rf"A\) opcion{k}A\s+B\) opcion{k}B", plano(texto_de(sm.pdf))) for k in (1, 2, 3)), "con «mezclar» desactivado las opciones salen en su orden")
posicional = [mc(1, "MEZ-POS", ["Python", "Java", "Ninguna de las anteriores"], [2])[0], mc(2, "MEZ-POS2", ["x", "y", "A y B"], [2])[0], mc(3, "MEZ-POS3", ["x", "y", "Ambas son correctas"], [2])[0]]
tpos = plano(texto_de(pdf_de(posicional, {1: {"type": "multichoice", "answer": "C"}, 2: {"type": "multichoice", "answer": "C"}, 3: {"type": "multichoice", "answer": "C"}}, contenido="solo_examen").pdf))
ok("A) Python B) Java C) Ninguna de las anteriores" in tpos and "C) A y B" in tpos and "C) Ambas son correctas" in tpos, "las preguntas con «ninguna de las anteriores», «A y B»… conservan su orden")
pat = plano(texto_de(pdf_de([mc(1, "MEZ-X", ["opciónA", "opciónB", "opciónC", "opciónD"], [1])[0]], {1: {"type": "multichoice", "answer": "B"}}, contenido="solo_examen", mezclar=True).pdf))
ok(re.search(r"A\) \S+ B\) \S+ C\) \S+ D\) \S+", pat) is not None, "al mezclar, las letras se reasignan A, B, C, D en orden")

# ══════════════════════════════════════════════════════════════════════════
print("   Tipo de letra y tamaño")
def letras(pdf_bytes, contiene, pagina=0):
    """(tamaño, nombre de la fuente) de los caracteres de la primera palabra que contiene `contiene`."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as d:
        cs = d.pages[pagina].chars
    texto = "".join(c["text"] for c in cs)
    i = texto.index(contiene)
    sel = cs[i:i + len(contiene)]
    return round(sum(c["size"] for c in sel) / len(sel), 1), sel[0]["fontname"]
base_q = [mc(1, "FUENTE-ENUNCIADO", ["opcion uno", "opcion dos"], [0])[0]]
base_k = {1: {"type": "multichoice", "answer": "A"}}
r0 = pdf_de(base_q, base_k, contenido="solo_examen", institucion="Universidad X")
tam_h, fu_h = letras(r0.pdf, "UNIVERSIDAD")
tam_q, fu_q = letras(r0.pdf, "FUENTE-ENUNCIADO")
ok(abs(tam_h - 11) < 0.2 and abs(tam_q - 10) < 0.2 and "DejaVu" in fu_h and "DejaVu" in fu_q, f"por defecto: encabezado {tam_h} pt y preguntas {tam_q} pt en DejaVu (como siempre)")
r1 = pdf_de(base_q, base_k, contenido="solo_examen", institucion="Universidad X", fuente_titulos="arial", tam_titulos=14, fuente_preguntas="times", tam_preguntas=12)
tam_h, fu_h = letras(r1.pdf, "UNIVERSIDAD")
tam_q, fu_q = letras(r1.pdf, "FUENTE-ENUNCIADO")
tam_p, fu_p = letras(r1.pdf, "I PARTE")
ok(abs(tam_h - 14) < 0.2 and "LiberationSans" in fu_h, f"el encabezado sale a 14 pt en Arial ({tam_h}, {fu_h})")
ok(abs(tam_q - 12) < 0.2 and "LiberationSerif" in fu_q, f"las preguntas salen a 12 pt en Times ({tam_q}, {fu_q})")
ok(abs(tam_p - 14 * 10.5 / 11) < 0.3 and "LiberationSans" in fu_p, f"el título de la parte sigue el grupo del encabezado ({tam_p} pt, {fu_p})")
tam_o, fu_o = letras(r1.pdf, "opcion uno")
ok(abs(tam_o - 12) < 0.2 and "LiberationSerif" in fu_o, "las opciones siguen el tamaño de las preguntas")
rj = pdf_de(base_q, base_k, contenido="folleto_hoja_clave", fuente_titulos="times", tam_titulos=12, fuente_preguntas="arial", tam_preguntas=10, institucion="Universidad X")
ok(len(paginas_de(rj.pdf)) == 3, "también el folleto, la hoja de respuestas y la clave")
fq = [mc(1, "Para \\(\\forall x \\in A\\) con α y β", ["a", "b"], [0])[0]]
rf_ = pdf_de(fq, base_k, contenido="solo_examen", fuente_titulos="arial", fuente_preguntas="arial")
with pdfplumber.open(io.BytesIO(rf_.pdf)) as d:
    cs = d.pages[0].chars
fuentes_de = {c["text"]: c["fontname"] for c in cs}
ok("∀" in fuentes_de and "DejaVu" in fuentes_de["∀"] and "LiberationSans" in fuentes_de["α"], f"lo que Arial no tiene (∀) se escribe con DejaVu y el resto sigue en Arial")
for fam_ in ("dejavu", "arial", "times"):
    rg = pdf_de(qs2[:30], key2, contenido="folleto_hoja_clave", fuente_titulos=fam_, tam_titulos=16, fuente_preguntas=fam_, tam_preguntas=14,
                institucion="Universidad Tecnológica de Panamá", facultad="Facultad de Ingeniería de Sistemas Computacionales", docente="Ing. César O. González C.",
                logo_izquierdo=logo_demo, logo_derecho=logo_demo)
    with pdfplumber.open(io.BytesIO(rg.pdf)) as d:
        fuera_ = [(i, round(w["x1"])) for i, pg in enumerate(d.pages) for w in pg.extract_words() if w["x0"] < 53 or w["x1"] > pg.width - 53]
        ws_ = d.pages[0].extract_words()
    ok(not fuera_ and len(d.pages) >= 4, f"{fam_} a 16 y 14 pt: nada se sale de los márgenes ({len(d.pages)} págs)")
r_chico = pdf_de(base_q, base_k, contenido="solo_examen", tam_titulos=8, tam_preguntas=8)
ok(abs(letras(r_chico.pdf, "FUENTE-ENUNCIADO")[0] - 8) < 0.2, "tamaños pequeños (8 pt)")
rfa = pdf_de(base_q, base_k, contenido="folleto_hoja_clave", docente="Ing. Ana María de los Ángeles Fernández", tam_titulos=16, fuente_titulos="times")
with pdfplumber.open(io.BytesIO(rfa.pdf)) as d:
    ws2 = [w for pg in d.pages for w in pg.extract_words() if w["text"] in ("FACILITADOR:", "CALIFICACIÓN:")]
ok(len(ws2) >= 2, "el facilitador y la calificación siguen en el encabezado con tamaños grandes")

print("5. Imágenes, fórmulas y texto raro")
# ══════════════════════════════════════════════════════════════════════════
import base64  # noqa: E402


def png(w, h, modo="RGB", color=(30, 90, 200)):
    b = io.BytesIO()
    Image.new(modo, (w, h), color).save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode()


def imagen(nombre, b64, mime="image/png"):
    return {"name": nombre, "mime": mime, "b64": b64}


q1, k1 = mc(1, "Mira la imagen", ["a", "b"], [0], images=[imagen("g.png", png(1600, 900)), imagen("p.png", png(40, 30, "RGBA", (255, 0, 0, 128)))])
q2, k2 = mc(2, "Imagen dañada", ["a", "b"], [1], images=[imagen("x.png", base64.b64encode(b"no es una imagen").decode())])
r = pdf_de([q1, q2], {1: k1, 2: k2}, contenido="solo_examen")
with pdfplumber.open(io.BytesIO(r.pdf)) as d:
    imgs = [im for p in d.pages for im in p.images]
ok(len(imgs) == 2, f"las dos imágenes válidas están en el PDF ({len(imgs)})")
ok(all(im["x1"] <= 612 - 54 + 1 for im in imgs) and max(im["height"] for im in imgs) <= 7.5 * 28.35 + 1, "la imagen grande se ajusta a la hoja")
ok(min(im["width"] for im in imgs) < 40, "la imagen pequeña no se agranda")
ok(any("pregunta 2" in a for a in r.avisos), f"la imagen ilegible se avisa y no rompe nada ({r.avisos})")

qf, kf = mc(1, r"Calcula \(x^2 + \alpha\) y \(\frac{1}{2}\) pero no \(\begin{matrix}1\\2\end{matrix}\)", [r"\(\sqrt{2}\)", "otra"], [0])
r = pdf_de([qf], {1: kf}, contenido="solo_examen")
tf = texto_de(r.pdf)
ok("x² + α" in tf and "½" in tf and "√2" in tf, "las fórmulas sencillas salen como texto")
ok(r"\(\begin{matrix}1" in tf and any("fórmula" in a for a in r.avisos), "la que no se entiende queda en LaTeX y se avisa")

qe, ke = mc(1, "Ideogramas 漢字 y <b>etiqueta</b> & más; código:\n    for i in range(3):\n        print(i)", ["a < b", "a & b"], [0])
r = pdf_de([qe], {1: ke}, contenido="solo_examen")
te2 = texto_de(r.pdf)
ok("<b>etiqueta</b>" in te2 and "a < b" in te2 and "a & b" in te2, "el texto se muestra literal (no se interpreta como marcado)")
ok("?" in te2 and any("carácter" in a for a in r.avisos), f"el carácter que la fuente no tiene se avisa ({r.avisos})")
ok("for i in range(3):" in te2 and "print(i)" in te2, "el código conserva sus líneas")

ensayo = {"num": 1, "type": "essay", "data": {"stem": "Explica", "feedback": "Debe mencionar A y B"}}
r = pdf_de([ensayo], {1: {"type": "essay", "answer": ""}})
ok("Debe mencionar A y B" in texto_de(r.pdf).split("CLAVE DE RESPUESTAS")[-1], "el ensayo trae su retroalimentación como orientación en la clave")
r = pdf_de([ensayo], {1: {"type": "essay", "answer": ""}}, contenido="solo_examen")
ok("Debe mencionar" not in texto_de(r.pdf), "…y NO en el examen")

# ══════════════════════════════════════════════════════════════════════════
print("6. Portada y datos")
# ══════════════════════════════════════════════════════════════════════════
r = pdf_de(qs2[:3], key2, institucion="Univ. de Prueba", materia="Física", docente="Ana Pérez", actividad="Parcial 2", grupo="3A", fecha="12/10/2026",
           instrucciones="Sin calculadora.")
t1 = paginas_de(r.pdf)[0]
ok(all(x in t1 for x in ("UNIV. DE PRUEBA", "FÍSICA", "PARCIAL 2", "FACILITADOR: Ana Pérez", "GRUPO: 3A", "12/10/2026", "NOMBRE:", "CÉDULA:", "CALIFICACIÓN:", "INDICACIONES GENERALES:", "Sin calculadora.")), "la portada trae el encabezado de la institución con los datos escritos")
ok("CALIFICACIÓN: ________/20" in t1.replace("  ", " "), "la calificación lleva el total de puntos")
ok("DOCENTE: Ana Pérez" in paginas_de(pdf_de(qs2[:3], key2, docente="Ana Pérez", rotulo_docente="docente").pdf)[0], "el rótulo del docente se puede cambiar")
sin = paginas_de(pdf_de(qs2[:3], key2, campos_estudiante=False, docente="Ana", grupo="3A").pdf)[0]
ok("NOMBRE:" not in sin and "CALIFICACIÓN" not in sin and "3A" in sin, "sin el cuadro del estudiante si no se pide (el grupo sigue a la vista)")
tk = paginas_de(pdf_de(qs2[:3], key2, docente="Ana", instrucciones="Una indicación", contenido="solo_clave").pdf)[0]
ok("CLAVE" in tk and "NOMBRE:" in tk and "INDICACIONES" not in tk and "CALIFICACIÓN" not in tk, "la clave repite el encabezado con «CLAVE» como nombre, sin calificación ni indicaciones")
ind = paginas_de(pdf_de(qs2[:3], key2, instrucciones="- Uno\n• Dos\n\nTres").pdf)[0]
ok(all(x in ind for x in ("• Uno", "• Dos", "• Tres")), "cada línea de las indicaciones es una viñeta")
t1 = paginas_de(pdf_de(qs2[:3], key2, titulo_respaldo="mi archivo").pdf)[0]
ok("MI ARCHIVO" in t1, "sin datos tampoco falla (usa el nombre del archivo como título)")
ok("Ana Pérez" in paginas_de(pdf_de(qs2[:30], key2, docente="Ana Pérez").pdf)[1].split("\n")[0], "el encabezado de las demás páginas lleva el docente")
meta = pdfplumber.open(io.BytesIO(r.pdf)).metadata
ok(meta.get("Author") == "Ana Pérez" and "Parcial 2" in (meta.get("Title") or ""), f"metadatos del PDF ({meta.get('Author')}, {meta.get('Title')})")

print("   Logos")
logo_a, logo_b = png(300, 300, "RGBA", (0, 120, 60, 255)), png(80, 200, "RGB", (120, 30, 140))
def n_imagenes(**kw):
    with pdfplumber.open(io.BytesIO(pdf_de(qs2[:3], key2, contenido="solo_examen", **kw).pdf)) as d:
        return [im for im in d.pages[0].images]
ok(len(n_imagenes()) == 0, "sin logos, sin imágenes")
uno = n_imagenes(logo_derecho=logo_a)
ok(len(uno) == 1 and uno[0]["x1"] > 612 / 2, "un logo (el derecho) queda a la derecha")
dos = n_imagenes(logo_izquierdo=logo_a, logo_derecho=logo_b)
ok(len(dos) == 2 and min(i["x0"] for i in dos) < 100 and max(i["x1"] for i in dos) > 612 - 100, "dos logos, a cada lado del título")
ok(all(i["height"] <= 2.5 * 28.35 + 1 and i["width"] <= 2.5 * 28.35 + 1 for i in dos), "los logos caben en su caja sin deformarse")
al = [i for i in dos if i["width"] < i["height"]][0]
ok(abs(al["width"] / al["height"] - 80 / 200) < 0.02, "el logo alto conserva su proporción")
r = pdf_de(qs2[:3], key2, logo_izquierdo="eso no es una imagen")
ok(any("logo izquierdo" in a for a in r.avisos), f"un logo ilegible se avisa y se omite ({r.avisos})")

# ══════════════════════════════════════════════════════════════════════════
print("7. La ruta /api/exportar_pdf")
# ══════════════════════════════════════════════════════════════════════════
main.init_db()
cli = TestClient(main.app, base_url="http://127.0.0.1:8000")
H = {"X-Conversor-Token": seguridad.TOKEN}
cuerpo = {"filename": "mi examen.docx", "total_points": 20, "questions": qs, "answer_key": {str(k): v for k, v in key.items()},
          "datos": {"docente": "Ana", "materia": "Física"}}
r = cli.post("/api/exportar_pdf", json=cuerpo, headers=H)
ok(r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:5] == b"%PDF-", f"200 con un PDF ({r.status_code})")
ok("mi%20examen_examen_y_clave.pdf" in r.headers["content-disposition"] or "mi examen_examen_y_clave.pdf" in r.headers["content-disposition"], f"nombre {r.headers['content-disposition']}")
info = json.loads(r.headers["x-pdf-info"])
ok(info["preguntas"] == 15 and info["paginas"] >= 2 and info["avisos"] == [], f"cabecera X-PDF-Info {info}")
ok("_folleto_hoja_y_clave.pdf" in cli.post("/api/exportar_pdf", json={**cuerpo, "datos": {"contenido": "folleto_hoja_clave"}}, headers=H).headers["content-disposition"], "folleto, hoja y clave: _folleto_hoja_y_clave.pdf")
ok("_clave.pdf" in cli.post("/api/exportar_pdf", json={**cuerpo, "datos": {"contenido": "solo_clave"}}, headers=H).headers["content-disposition"], "solo la clave: _clave.pdf")
ok(cli.post("/api/exportar_pdf", json=cuerpo).status_code == 401, "sin token: 401")
ok(cli.post("/api/exportar_pdf", json={**cuerpo, "datos": {"contenido": "otra cosa"}}, headers=H).status_code == 422, "contenido desconocido: 422")
ok(cli.post("/api/exportar_pdf", json={**cuerpo, "datos": {"fuente_titulos": "comic"}}, headers=H).status_code == 422, "tipo de letra desconocido: 422")
ok(cli.post("/api/exportar_pdf", json={**cuerpo, "datos": {"tam_preguntas": 5}}, headers=H).status_code == 422 and cli.post("/api/exportar_pdf", json={**cuerpo, "datos": {"tam_titulos": 40}}, headers=H).status_code == 422, "tamaños fuera de 7 a 20 pt: 422")
ok(cli.post("/api/exportar_pdf", json={**cuerpo, "datos": {"fuente_titulos": "times", "tam_titulos": 12.5, "fuente_preguntas": "arial", "tam_preguntas": 10}}, headers=H).status_code == 200, "tipo de letra y tamaños válidos: 200")
ok(cli.post("/api/exportar_pdf", json={**cuerpo, "datos": {"margenes": "enormes"}}, headers=H).status_code == 422, "márgenes desconocidos: 422")
ok(cli.post("/api/exportar_pdf", json={**cuerpo, "datos": {"margenes": "estrechos"}}, headers=H).status_code == 200, "márgenes «estrechos»: 200")
ok(cli.post("/api/exportar_pdf", json={**cuerpo, "datos": {"papel": "folio"}}, headers=H).status_code == 422, "papel desconocido: 422")
ok(cli.post("/api/exportar_pdf", json={**cuerpo, "datos": {"docente": "x" * 500}}, headers=H).status_code == 422, "un dato demasiado largo: 422")
malo = {**cuerpo, "questions": [{"num": 1, "type": "inventado", "data": {"stem": "a"}}], "answer_key": {"1": {"type": "essay", "answer": ""}}}
ok(cli.post("/api/exportar_pdf", json=malo, headers=H).status_code == 422, "la misma validación que el XML: tipo desconocido -> 422")
sin_clave = {**cuerpo, "questions": [{"num": 1, "type": "truefalse", "data": {"stem": "a"}}], "answer_key": {"1": {"type": "truefalse", "answer": "quizá"}}}
ok(cli.post("/api/exportar_pdf", json=sin_clave, headers=H).status_code == 422, "una respuesta que el XML rechazaría tampoco sale en el PDF")
ok(cli.post("/api/exportar_pdf", json={**cuerpo, "answer_key": {"x": {}}}, headers=H).status_code == 422, "claves de answer_key no enteras -> 422")
ok(cli.post("/api/exportar_pdf", json={**cuerpo, "total_points": 0}, headers=H).status_code == 422, "total de puntos 0 -> 422")
ok(cli.post("/api/exportar_pdf", json={**cuerpo, "datos": {"rotulo_docente": "jefe"}}, headers=H).status_code == 422, "rótulo desconocido: 422")
con_logo = cli.post("/api/exportar_pdf", json={**cuerpo, "datos": {"logo_izquierdo": logo_a, "docente": "Ana"}}, headers=H)
ok(con_logo.status_code == 200 and json.loads(con_logo.headers["x-pdf-info"])["avisos"] == [], "la ruta acepta un logo en base64")
ok(cli.post("/api/exportar_pdf", json={**cuerpo, "datos": {"logo_derecho": "A" * 2_000_001}}, headers=H).status_code == 422, "un logo demasiado grande: 422")
ok(len(cli.get("/api/history", headers=H).json()) == 0, "exportar el PDF no guarda nada en el Historial")

print()
print("TODO OK" if not fallas else f"{fallas} FALLA(S)")
sys.exit(1 if fallas else 0)
