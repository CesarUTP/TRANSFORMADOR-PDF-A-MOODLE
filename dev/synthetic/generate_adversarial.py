"""
generate_adversarial.py — Exámenes sintéticos ADVERSARIALES (x01…x13).

    backend/venv/bin/python dev/synthetic/generate_adversarial.py

Cada uno tiene entre 30 y 50 preguntas y está diseñado para romper una parte
distinta del sistema (numeración caótica, opciones con rótulos de todo tipo,
claves finales en formatos mezclados, marcas de color distractoras, dos
columnas, ruido documental, respuestas abiertas y numéricas ambiguas,
caracteres que chocan con la sintaxis interna, emparejamientos y Cloze
complejos, escaneado degradado, código en imágenes, y un examen donde falta
la mayoría de las respuestas). La verdad (golden) es exacta por construcción.

Escribe:
    samples/synthetic/x??_*.pdf
    samples/golden/x??_*.expected.json    (source = "adversarial")

Es determinista. En dev/eval.py estos documentos quedan FUERA de la corrida
por defecto (para no mover la línea base de los 18 originales): se corren
con `--adversarial` o con `--only x`.

CLAVES CONTRAFÁCTICAS: en todos los exámenes con marcas o clave, ~25 % de
las preguntas de opción múltiple y verdadero/falso llevan a propósito una
respuesta que NO es la correcta en la realidad (ver cf()). El sistema debe
transcribir lo que dice el documento, no resolver.
"""

import io
import json
import random
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image as RLImage, KeepTogether, PageBreak, PageTemplate,
    Paragraph, Preformatted, Spacer, Table, TableStyle,
)

sys.path.insert(0, str(Path(__file__).parent))
import generate as G  # noqa: E402  (reutiliza estilos, draw_question y golden_question)
import adversarial_bank as B  # noqa: E402

ROOT = G.ROOT
PDF_DIR = G.PDF_DIR
GOLDEN_DIR = G.GOLDEN_DIR
RED, BLUE = G.RED, G.BLUE
LETTERS = G.LETTERS

UNICODE_FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
MONO_FONT = "/System/Library/Fonts/Menlo.ttc"


# ── Expansión del banco ──────────────────────────────────────────────────────

def _keep_order(options) -> bool:
    return any(o[:1].isdigit() for o in options)


def mc(t, rng, shuffle=True) -> dict:
    stem, opts, ci = t
    idx = list(range(len(opts)))
    if shuffle and not _keep_order(opts):
        rng.shuffle(idx)
    return {"type": "multichoice", "stem": stem, "options": [opts[i] for i in idx], "correct": [idx.index(ci)]}


def multi(t, rng) -> dict:
    stem, opts, cs = t
    idx = list(range(len(opts)))
    rng.shuffle(idx)
    return {"type": "multichoice", "stem": stem, "options": [opts[i] for i in idx],
            "correct": sorted(idx.index(c) for c in cs)}


def tf(t) -> dict:
    return {"type": "truefalse", "stem": t[0], "answer": "Verdadero" if t[1] else "Falso"}


def sa(t) -> dict:
    return {"type": "shortanswer", "stem": t[0], "answer": t[1]}


def num(t) -> dict:
    return {"type": "numerical", "stem": t[0], "answer": t[1]}


def essay(s) -> dict:
    return {"type": "essay", "stem": s}


def match(t) -> dict:
    return {"type": "matching", "stem": t[0], "pairs": [list(p) for p in t[1]], "extra_right": list(t[2])}


def cloze(t) -> dict:
    return {"type": "cloze", "text": t[0],
            "blanks": [{"options": list(o), "correct": list(c)} for o, c in t[1]]}


def take(rng, seq, n):
    return [seq[i] for i in rng.sample(range(len(seq)), n)]


def cf(q, rng, rate=0.25):
    """Clave contrafáctica: el documento marca una respuesta distinta de la real."""
    q = dict(q)
    if q["type"] == "multichoice" and len(q["correct"]) == 1 and rng.random() < rate:
        wrong = [i for i in range(len(q["options"])) if i not in q["correct"]]
        q["correct"] = [rng.choice(wrong)]
    elif q["type"] == "truefalse" and rng.random() < rate:
        q["answer"] = "Falso" if q["answer"] == "Verdadero" else "Verdadero"
    return q


# ── Utilidades de dibujo ─────────────────────────────────────────────────────

def raw(markup: str, style=G.BODY) -> Paragraph:
    return Paragraph(markup, style)


def font(text: str, color=None, bold=False) -> str:
    t = escape(text)
    if bold:
        t = f"<b>{t}</b>"
    if color:
        t = f'<font color="{color}">{t}</font>'
    return t


def roman(i: int) -> str:
    return ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"][i]


def label_for(style: str, i: int) -> str:
    return {
        "A)": f"{LETTERS[i].upper()})", "A.": f"{LETTERS[i].upper()}.", "a.": f"{LETTERS[i]}.",
        "(a)": f"({LETTERS[i]})", "i.": f"{roman(i).lower()}.", "1-": f"{i + 1}-", "1.": f"{i + 1}.",
        "•": "•", "[ ]": "[ ]", "-": "-", "none": "",
    }[style]


def tf_line(label: str, q: dict, red_word: bool = False, x_marks: bool = False, suffix: str = "") -> Paragraph:
    """Verdadero/falso con la respuesta marcada dentro del propio documento."""
    v = q["answer"] == "Verdadero"
    if x_marks:
        body = (f"{font(q['stem'])}   ( {'X' if v else ' '} ) Verdadero   ( {' ' if v else 'X'} ) Falso")
    else:
        w_v = font("Verdadero", RED) if (v and red_word) else font("Verdadero")
        w_f = font("Falso", RED) if (not v and red_word) else font("Falso")
        body = f"{font(q['stem'])}   ( ) {w_v}   ( ) {w_f}"
    return raw(f"{escape(label)} {body}{suffix}".strip(), G.STEM)


def write_golden(name: str, questions: list, *, focus: str, notes: str, path: str = "parse") -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    doc = {"source": "adversarial", "reviewed": True, "file": f"synthetic/{name}.pdf", "path": path,
           "is_exam": True, "focus": focus, "notes": notes, "questions": questions}
    (GOLDEN_DIR / f"{name}.expected.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check_size(name: str, qs: list) -> None:
    assert 30 <= len(qs) <= 50, f"{name}: {len(qs)} preguntas (deben ser 30-50)"


def finish(name: str, story: list, qs: list, *, focus: str, notes: str, path: str = "parse") -> None:
    check_size(name, qs)
    G.build_pdf(name, story)
    write_golden(name, [G.golden_question(q) for q in qs], focus=focus, notes=notes, path=path)
    print(f"  {name}: {len(qs)} preguntas")


class font_swap:
    """Cambia temporalmente la tipografía de los estilos de generate.py."""
    STYLES = [G.BODY, G.STEM, G.OPT, G.HEAD, G.TITLE]

    def __init__(self, name):
        self.name, self.saved = name, []

    def __enter__(self):
        self.saved = [(s, s.fontName) for s in self.STYLES]
        for s in self.STYLES:
            s.fontName = self.name

    def __exit__(self, *exc):
        for s, f in self.saved:
            s.fontName = f


# ── x01 — Numeración caótica ────────────────────────────────────────────────

def x01():
    name = "x01_numeracion_caotica"
    rng = random.Random(name)
    qs = ([cf(mc(t, rng), rng) for t in take(rng, B.MC, 22)]
          + [multi(t, rng) for t in take(rng, B.MULTI, 2)]
          + [cf(tf(t), rng) for t in take(rng, B.TF, 8)]
          + [sa(t) for t in take(rng, B.SA, 4)]
          + [essay(s) for s in take(rng, B.ESSAY, 4)])
    rng.shuffle(qs)
    nums = [1, 2, 3, 3, 4, 6, 7, 7, 7, 8, 10, 11, 12, 12, 13, 14, 15, 16, 16, 17, 20, 21, 22, 22, 23]
    fmts = ["{n}.", "{n})", "({n})", "Pregunta {n}:", "{n}-"]

    story: list = []
    G.header(story, "Cuestionario Integrador", "Las respuestas correctas están marcadas con * (versión docente).")
    for i, q in enumerate(qs):
        numbered = i < len(nums)
        lab = fmts[i % 5].format(n=nums[i]) if numbered else ""
        stem = q.get("stem", "") + (" (marca todas las correctas)" if q["type"] == "multichoice" and len(q["correct"]) > 1 else "")
        if q["type"] == "truefalse":
            story.append(tf_line(lab, q, x_marks=True))
            continue
        story.append(raw(f"{escape(lab)} {escape(stem)}".strip(), G.STEM))
        if q["type"] == "multichoice":
            if numbered and i % 5 == 2:
                style = "1."          # opciones numeradas como si fueran preguntas
            elif numbered:
                style = ["A)", "none", "a."][i % 3]
            else:
                style = "none" if i % 2 else "A)"
            for k, opt in enumerate(q["options"]):
                mark = " *" if k in q["correct"] else ""
                story.append(raw(escape(f"{label_for(style, k)} {opt}{mark}".strip()), G.OPT))
        elif q["type"] == "shortanswer":
            story.append(raw(escape(f"R/ {q['answer']}"), G.OPT))
        elif q["type"] == "essay":
            story.append(G.p("_" * 80))
            story.append(G.p("_" * 80))
    finish(name, story, qs, focus="Numeración y rótulos",
           notes="40 preguntas con numeración repetida y salteada en 4 estilos distintos, opciones "
                 "numeradas como si fueran preguntas, opciones sin rótulo y, desde la 26, preguntas sin "
                 "ningún número. Respuestas con asterisco y V/F con ( X ); ~25 % con clave contrafáctica.")


# ── x02 — Opciones heterogéneas ─────────────────────────────────────────────

SYMBOL_MC = [
    ("¿Qué operador de Python eleva un número a una potencia?", ["+", "-", "**", "//"], 2),
    ("¿Qué operador compara si dos valores son distintos?", ["==", "!=", "=", ">="], 1),
    ("¿Qué símbolo se usa para acceder a un elemento por índice en Python?", ["( )", "{ }", "[ ]", "< >"], 2),
    ("¿Qué operador lógico significa «y» en Python?", ["and", "or", "not", "xor"], 0),
    ("¿Qué operador devuelve el residuo de una división?", ["/", "%", "//", "^"], 1),
    ("¿Cuál es el resultado de 10 // 3 en Python?", ["3", "3,33", "1", "4"], 0),
]
EXTRA_OPTS = ["Todas las anteriores", "Ninguna de las anteriores", "No se puede determinar"]


def x02():
    name = "x02_opciones_heterogeneas"
    rng = random.Random(name)
    long_pool = [t for t in B.MC if max(len(o) for o in t[1]) > 45]
    plain_pool = [t for t in B.MC if t not in long_pool]
    qs = ([mc(t, rng) for t in take(rng, plain_pool, 18)]
          + [mc(t, rng) for t in take(rng, long_pool, 6)]
          + [mc(t, rng, shuffle=False) for t in SYMBOL_MC]
          + [multi(t, rng) for t in take(rng, B.MULTI, 10)]
          + [tf(t) for t in take(rng, B.TF, 5)])
    rng.shuffle(qs)
    # Opciones extra: "Todas/Ninguna de las anteriores" y hasta 6 opciones.
    for q in qs:
        if q["type"] == "multichoice" and rng.random() < 0.3 and len(q["options"]) <= 5:
            q["options"] = q["options"] + [rng.choice(EXTRA_OPTS)]
    qs = [cf(q, rng, 0.2) for q in qs]
    styles = ["A)", "a.", "(a)", "i.", "1-", "•", "[ ]", "-", "none", "A."]

    story: list = []
    G.header(story, "Banco de Preguntas Variadas", "Las respuestas correctas aparecen en color rojo.")
    for i, q in enumerate(qs, 1):
        if q["type"] == "truefalse":
            story.append(tf_line(f"{i}.", q, red_word=True))
            continue
        story.append(raw(f"{i}. {escape(q['stem'])}" + (" (seleccione todas las que apliquen)" if len(q["correct"]) > 1 else ""), G.STEM))
        style = styles[i % len(styles)]
        for k, opt in enumerate(q["options"]):
            story.append(raw(font(f"{label_for(style, k)} {opt}".strip(), RED if k in q["correct"] else None), G.OPT))
    finish(name, story, qs, focus="Formatos de opciones",
           notes="45 preguntas donde cada una usa un estilo de rótulo distinto (A) a. (a) i. 1- • [ ] - sin rótulo), "
                 "hasta 6 opciones, 'Todas/Ninguna de las anteriores', opciones que son un símbolo (**, !=, %), "
                 "opciones de varias líneas y 10 de respuesta múltiple. Respuestas solo en rojo.")


# ── x03 — Claves finales heterogéneas ───────────────────────────────────────

def x03():
    name = "x03_claves_heterogeneas"
    rng = random.Random(name)
    qs = ([cf(mc(t, rng), rng) for t in take(rng, B.MC, 17)]
          + [multi(t, rng) for t in take(rng, B.MULTI, 1)]
          + [cf(tf(t), rng) for t in take(rng, B.TF, 6)]
          + [match(t) for t in take(rng, B.MATCH, 4)]
          + [cloze(t) for t in take(rng, B.CLOZE, 4)]
          + [essay(s) for s in take(rng, B.ESSAY, 2)]
          + [sa(t) for t in take(rng, B.SA, 3)]
          + [num(t) for t in take(rng, B.NUM, 3)])
    rng.shuffle(qs)
    story: list = []
    G.header(story, "Evaluación Parcial Integradora", "Instrucciones: responde todas las preguntas.")
    drawn = []
    for i, q in enumerate(qs, 1):
        line = G.draw_question(story, i, q, rng, mark="none")
        drawn.append(line.split(". ", 1)[1] if line else "")

    def fmt(i, q, body, section):
        t = q["type"]
        if t == "multichoice":
            letters = [x.strip() for x in body.split(",")]
            if section == "A":
                return ", ".join(letters)
            if section == "B":
                return ", ".join(x.upper() for x in letters)
            return " / ".join(f"{x}) {q['options'][LETTERS.index(x)]}" for x in letters)
        if t == "truefalse":
            return {"A": "V" if body == "Verdadero" else "F"}.get(section, body)
        if t == "matching":
            if section == "A":
                return body
            if section == "B":
                return body.replace("-", "→").replace(", ", "; ")
            return body.replace(", ", "  ")
        if t == "cloze":
            parts = [x.strip() for x in body.split(",")]
            if section == "A":
                return body
            if section == "B":
                return "  ".join(f"{LETTERS[k].upper()}) {v}" for k, v in enumerate(parts))
            return " ".join(f"[{LETTERS[k].upper()}] {v}" for k, v in enumerate(parts))
        return body

    story.append(PageBreak())
    story.append(G.p("HOJA DE RESPUESTAS DEL DOCENTE", G.HEAD))
    story.append(G.p("Sección A — preguntas 1 a 14", G.BODY))
    for i, q in enumerate(qs[:14], 1):
        story.append(G.p(f"{i}. {fmt(i, q, drawn[i - 1], 'A')}"))
    story.append(Spacer(1, 8))
    story.append(G.p("Sección B — preguntas 15 a 28", G.BODY))
    rows = [["Nº", "Respuesta"]] + [[str(i), fmt(i, qs[i - 1], drawn[i - 1], "B")] for i in range(15, 29)]
    tbl = Table(rows, colWidths=[1.6 * cm, 12 * cm])
    tbl.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                             ("FONT", (0, 1), (-1, -1), "Helvetica", 9)]))
    story.append(tbl)
    story.append(Spacer(1, 8))
    story.append(G.p("Sección C — preguntas 29 a 40", G.BODY))
    for i in range(29, len(qs) + 1):
        story.append(G.p(f"Pregunta {i}: {fmt(i, qs[i - 1], drawn[i - 1], 'C')}"))
    finish(name, story, qs, focus="Clave final en 3 formatos",
           notes="40 preguntas de los 7 tipos; la clave del final cambia de formato en cada sección (lista con "
                 "letras, tabla Nº|Respuesta con V/F completos y '→', 'Pregunta N: c) texto' con Cloze entre "
                 "corchetes). ~25 % de claves contrafácticas.")


# ── x04 — Marcas distractoras ───────────────────────────────────────────────

def _colored_stem(stem: str, how: str) -> str:
    words = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúñÑ]{6,}", stem)
    e = escape(stem)
    if not words:
        return e
    w = escape(max(words, key=len))
    rep = {"red": f'<font color="{RED}">{w}</font>', "blue": f'<font color="{BLUE}">{w}</font>', "bold": f"<b>{w}</b>"}[how]
    return e.replace(w, rep, 1)


def x04():
    name = "x04_marcas_distractoras"
    rng = random.Random(name)
    mcs = [cf(mc(t, rng), rng, 0.25) for t in take(rng, B.MC, 26)]
    all_red = {5, 16, 24}                        # TODAS las opciones en rojo: no señalan nada
    for i in all_red:
        mcs[i]["correct"] = []
        mcs[i]["unanswered"] = True
    qs = (mcs + [multi(t, rng) for t in take(rng, B.MULTI, 3)]
          + [cf(tf(t), rng, 0.3) for t in take(rng, B.TF, 7)] + [sa(t) for t in take(rng, B.SA, 4)])
    order = list(range(len(qs)))
    rng.shuffle(order)
    qs = [qs[i] for i in order]

    story: list = []
    G.header(story, "Examen con Marcas de Todo Tipo", "Las respuestas correctas están en rojo. Otros colores son solo énfasis.",
             title_color=RED)
    for i, q in enumerate(qs, 1):
        if i in (1, 11, 21, 31):
            story.append(raw(font(f"Sección {'ABCD'[i // 10]}: bloque de preguntas", RED, bold=True), G.HEAD))
        if q["type"] == "truefalse":
            story.append(tf_line(f"{i}.", q, red_word=True))
            continue
        how = ["red", "blue", "bold", None, None][i % 5]
        story.append(raw(f"{i}. {_colored_stem(q['stem'], how) if how else escape(q['stem'])}", G.STEM))
        if q["type"] == "shortanswer":
            story.append(raw(f"Respuesta: {font(q['answer'], RED)}", G.OPT))
            continue
        blue_wrong = (i % 7 == 3)
        for k, opt in enumerate(q["options"]):
            if q.get("unanswered"):
                story.append(raw(font(f"{LETTERS[k]}) {opt}", RED), G.OPT))
            elif k in q["correct"]:
                story.append(raw(font(f"{LETTERS[k]}) {opt}", RED), G.OPT))
            elif blue_wrong and k == (q["correct"][0] + 1) % len(q["options"]):
                story.append(raw(font(f"{LETTERS[k]}) {opt}", BLUE), G.OPT))
            else:
                story.append(raw(escape(f"{LETTERS[k]}) {opt}"), G.OPT))
    finish(name, story, qs, focus="Marcas distractoras",
           notes="Respuestas en rojo, pero también: palabras del enunciado en rojo/azul/negrita, opciones "
                 "equivocadas completas en azul, títulos de sección en rojo y 3 preguntas con TODAS las "
                 "opciones en rojo (no hay respuesta: deben omitirse). ~25 % de claves contrafácticas.")


# ── x05 — Dos columnas ──────────────────────────────────────────────────────

def two_column_doc(name: str, story: list) -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    w, h = letter
    margin, gap = 1.8 * cm, 0.9 * cm
    col_w = (w - 2 * margin - gap) / 2
    frames = [Frame(margin, 1.8 * cm, col_w, h - 3.6 * cm, id="c1", leftPadding=0, rightPadding=0),
              Frame(margin + col_w + gap, 1.8 * cm, col_w, h - 3.6 * cm, id="c2", leftPadding=0, rightPadding=0)]
    doc = BaseDocTemplate(buf, pagesize=letter, title=name, author="set sintético", creator="generate_adversarial.py")
    doc.addPageTemplates([PageTemplate(id="dos", frames=frames)])
    doc.build(story)
    (PDF_DIR / f"{name}.pdf").write_bytes(buf.getvalue())


def x05():
    name = "x05_dos_columnas"
    rng = random.Random(name)
    qs = ([cf(mc(t, rng), rng) for t in take(rng, B.MC, 26)] + [cf(tf(t), rng) for t in take(rng, B.TF, 8)]
          + [sa(t) for t in take(rng, B.SA, 3)] + [num(t) for t in take(rng, B.NUM, 3)])
    rng.shuffle(qs)
    story: list = [G.p("Examen Final — Formato de dos columnas", G.TITLE), G.p("Marca la respuesta correcta en cada caso."), Spacer(1, 6)]
    key = []
    for i, q in enumerate(qs, 1):
        line = G.draw_question(story, i, q, rng, mark="none")
        if line:
            key.append(line)
    story.append(Spacer(1, 10))
    story.append(G.p("CLAVE DE RESPUESTAS", G.HEAD))
    story += [G.p(k) for k in key]
    check_size(name, qs)
    two_column_doc(name, story)
    write_golden(name, [G.golden_question(q) for q in qs], focus="Diseño en dos columnas",
                 notes="40 preguntas en dos columnas: el texto se lee por líneas y mezcla ambas columnas "
                       "(la fila y de la izquierda se une a la de la derecha). Clave al final, también en dos columnas.")
    print(f"  {name}: {len(qs)} preguntas")


# ── x06 — Ruido documental ──────────────────────────────────────────────────

def x06():
    name = "x06_ruido_documental"
    rng = random.Random(name)
    passage = [mc(t, rng, shuffle=False) for t in B.PASAJE_QS]
    passage = [cf(q, rng, 0.25) for q in passage]
    sec1 = [cf(mc(t, rng), rng) for t in take(rng, B.MC, 16)]
    sec2 = passage + [cf(mc(t, rng), rng) for t in take(rng, B.MC, 12)]
    sec3 = [cf(tf(t), rng) for t in take(rng, B.TF, 6)]
    sec4 = [sa(t) for t in take(rng, B.SA, 4)] + [num(t) for t in take(rng, B.NUM, 3)]
    sec5 = [essay(s) for s in take(rng, B.ESSAY, 3)]
    qs = sec1 + sec2 + sec3 + sec4 + sec5

    def on_page(c, doc):
        w, h = letter
        c.saveState()
        c.setFont("Helvetica-Bold", 8)
        c.drawString(2 * cm, h - 1.2 * cm, "UNIVERSIDAD NACIONAL DEL SUR — DEPARTAMENTO DE CIENCIAS BÁSICAS")
        c.drawRightString(w - 2 * cm, h - 1.2 * cm, "PARCIAL 2 — GRUPO B — 2026-1")
        c.setFont("Helvetica", 7.5)
        c.drawString(2 * cm, 1.1 * cm, "Material confidencial. Prohibida su reproducción total o parcial. Cód. 0473-B")
        c.drawRightString(w - 2 * cm, 1.1 * cm, f"Página {doc.page}")
        c.setFillColor(colors.Color(0.85, 0.85, 0.85))
        c.setFont("Helvetica-Bold", 70)
        c.translate(w / 2, h / 2)
        c.rotate(45)
        c.drawCentredString(0, 0, "BORRADOR")
        c.restoreState()

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=letter, title=name, author="set sintético", creator="generate_adversarial.py")
    doc.addPageTemplates([PageTemplate(id="ruido", frames=[Frame(2 * cm, 2 * cm, letter[0] - 4 * cm, letter[1] - 4 * cm)], onPage=on_page)])
    story: list = []
    story.append(G.p("PARCIAL 2 — INTRODUCCIÓN A LAS CIENCIAS", G.TITLE))
    story.append(G.p("INSTRUCCIONES GENERALES", G.HEAD))
    for k, t in enumerate(["Apague su teléfono celular y guárdelo.", "Use únicamente lápiz o bolígrafo azul o negro.",
                           "No se permite el uso de calculadoras programables.",
                           "Cada pregunta indica su puntaje entre paréntesis.", "Tiempo máximo: 90 minutos."], 1):
        story.append(G.p(f"{k}. {t}"))
    story.append(Spacer(1, 6))

    key: list = []
    n = 0

    def section(title, questions, pts):
        nonlocal n
        story.append(G.p(title, G.HEAD))
        for q in questions:
            n += 1
            dq = dict(q)
            if "stem" in dq:
                dq["stem"] = f"{dq['stem']} ({pts} pts)"
            line = G.draw_question(story, n, dq, rng, mark="none")
            if line:
                key.append(line)
            if n == 10:
                story.append(Spacer(1, 6))
                t = Table([["Espacio para borrador"]], colWidths=[14 * cm], rowHeights=[2.2 * cm])
                t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                       ("FONT", (0, 0), (-1, -1), "Helvetica-Oblique", 8)]))
                story.append(t)
            if n == 20:
                story.append(raw(escape("Nota: el siguiente fragmento de código es solo ilustrativo y no corresponde a ninguna pregunta."), G.BODY))
                story.append(Preformatted("def saludar(nombre):\n    return 'Hola ' + nombre\n", G.BODY))
            if n == 26:
                story.append(PageBreak())

    section("SECCIÓN I — Conocimientos generales (2 pts c/u)", sec1, 2)
    story.append(G.p("SECCIÓN II — Comprensión de lectura", G.HEAD))
    story.append(G.p("Lea el siguiente texto y responda las preguntas 17 a 20:"))
    story.append(raw(f"<i>{escape(B.PASAJE)}</i>", G.BODY))
    n_before = n
    section("Preguntas de la sección II", sec2, 2)
    section("SECCIÓN III — Verdadero o falso (1 pt c/u)", sec3, 1)
    section("SECCIÓN IV — Respuesta corta y cálculo (3 pts c/u)", sec4, 3)
    section("SECCIÓN V — Desarrollo (5 pts c/u)", sec5, 5)
    story.append(PageBreak())
    story.append(G.p("CLAVE OFICIAL — USO EXCLUSIVO DEL DOCENTE", G.HEAD))
    story += [G.p(k) for k in key]
    check_size(name, qs)
    doc.build(story)
    (PDF_DIR / f"{name}.pdf").write_bytes(buf.getvalue())
    write_golden(name, [G.golden_question(q) for q in qs], focus="Ruido documental",
                 notes="48 preguntas con encabezado y pie en cada página, marca de agua 'BORRADOR' girada, lista "
                       "de instrucciones numerada (parece preguntas), puntajes '(2 pts)' en cada enunciado, "
                       "pasaje de lectura con 4 preguntas dependientes, código ilustrativo suelto, recuadro de "
                       "borrador y salto de página en medio de una pregunta.")
    print(f"  {name}: {len(qs)} preguntas")


# ── x07 — Abiertas y numéricas ambiguas ─────────────────────────────────────

def x07():
    name = "x07_abiertas_numericas"
    rng = random.Random(name)
    nums = [dict(num(t)) for t in B.NUM]
    words = {"180": "ciento ochenta", "32": "treinta y dos"}                       # número en palabras
    units = {"80": "80 km/h", "26": "26 cm"}                                      # con unidad
    for q in nums:
        q["key_text"] = words.get(q["answer"]) or units.get(q["answer"]) or q["answer"]
    qs = ([essay(s) for s in take(rng, B.ESSAY, 12)] + [sa(t) for t in B.SA[:14]] + nums
          + [cf(tf(t), rng) for t in take(rng, B.TF, 10)])
    rng.shuffle(qs)
    story: list = []
    G.header(story, "Preguntas Abiertas y de Cálculo", "Sin opciones múltiples: responde con tus palabras, una palabra o un número.")
    key = []
    for i, q in enumerate(qs, 1):
        if q["type"] == "truefalse":
            story.append(G.p(f"{i}. {q['stem']}   (   ) Verdadero   (   ) Falso", G.STEM))
            key.append(f"{i}. {q['answer']}")
        else:
            story.append(G.p(f"{i}. {q['stem']}  ______________" if q["type"] != "essay" else f"{i}. {q['stem']}", G.STEM))
            if q["type"] == "essay":
                story.append(G.p("_" * 80))
                story.append(G.p("_" * 80))
                key.append(f"{i}. Respuesta abierta (rúbrica).")
            else:
                key.append(f"{i}. {q.get('key_text', q['answer'])}")
    story.append(PageBreak())
    story.append(G.p("CLAVE DE RESPUESTAS", G.HEAD))
    story += [G.p(k) for k in key]
    finish(name, story, qs, focus="Abiertas y numéricas",
           notes="50 preguntas: 12 ensayo, 14 respuesta corta, 14 numéricas (coma decimal, negativo, y 4 casos "
                 "límite: 2 con el número escrito en palabras y 2 con unidad en la clave) y 10 V/F. "
                 "El golden espera el número puro ('180', '80').")


# ── x08 — Caracteres especiales ─────────────────────────────────────────────

SPECIAL_MC = [
    ("¿Qué operador bit a bit realiza la operación OR en Python?", ["&", "|", "^", "~"], 1),
    ("En HTML, ¿qué etiqueta define un párrafo?", ["<p>", "<br>", "<div>", "<span>"], 0),
    ("¿Cuál es el resultado de 5 > 3 && 2 < 1 en JavaScript?", ["true", "false", "undefined", "NaN"], 1),
    ("¿Qué símbolo se usa para comentarios de una línea en Python?", ["//", "#", "--", "/*"], 1),
    ("Una expresión regular que reconoce un dígito es:", ["\\d", "\\w", "\\s", "\\b"], 0),
    ("¿Cuál es la derivada de sen(x)?", ["cos(x)", "-cos(x)", "sen(x)", "-sen(x)"], 0),
    ("¿Qué desigualdad describe «x es mayor o igual que 5»?", ["x ≥ 5", "x ≤ 5", "x ≠ 5", "x < 5"], 0),
    ("El valor aproximado de π es:", ["π ≈ 3,14", "π ≈ 2,71", "π ≈ 1,61", "π ≈ 4,13"], 0),
    ("¿Cuál es la fórmula del área del círculo?", ["A = πr²", "A = 2πr", "A = πd", "A = r²/π"], 0),
    ("¿Qué representa la letra griega Σ en matemáticas?", ["Una sumatoria", "Un producto", "Una integral", "Un límite"], 0),
    ("¿Qué imprime print('Tom & Jerry')?", ["Tom & Jerry", "Tom &amp; Jerry", "Tom y Jerry", "Error"], 0),
    ("Un texto termina con la secuencia ]]> ¿Qué formato XML necesita escapar esa secuencia?", ["CDATA", "JSON", "YAML", "CSV"], 0),
    ("En la sintaxis de Moodle {1:MULTICHOICE:=Sí~No}, ¿qué carácter separa las opciones?", ["~", "#", "}", "="], 0),
    ("¿Cuál es el símbolo de la moneda del euro?", ["€", "$", "£", "¥"], 0),
    ("¿Qué frase está escrita entre comillas latinas?", ["«Hola»", "“Hola”", "'Hola'", "\"Hola\""], 0),
    ("¿Cuál es la temperatura de congelación del agua?", ["0 °C", "32 °C", "100 °C", "273 °C"], 0),
    ("¿Cuál es el resultado de 2 × 3 + 4 ÷ 2?", ["8", "7", "5", "10"], 0),
    ("¿Qué secuencia de escape representa un salto de línea en C?", ["\\n", "/n", "\\t", "\\r"], 0),
    ("¿Cuál palabra está escrita correctamente?", ["canción", "cancion", "canciõn", "cançión"], 0),
    ("¿Cuánto es 1/4 + 1/4?", ["1/2", "1/8", "2/8", "1/16"], 0),
]
SPECIAL_TF = [
    ("La secuencia «]]>» cierra una sección CDATA en XML.", True),
    ("En Python, 5 // 2 devuelve 2,5.", False),
    ("La etiqueta <br> inserta un salto de línea en HTML.", True),
    ("En SQL, el comodín % representa cualquier secuencia de caracteres.", True),
    ("El carácter ~ se usa en Cloze de Moodle para separar las opciones de una respuesta.", True),
    ("La expresión x ≠ y significa que x es igual a y.", False),
]
SPECIAL_CLOZE = [
    ("La velocidad se mide en {0} y la frecuencia en {1}.",
     [(["km/h", "m/s²", "kg/m"], [0]), (["Hz", "dB", "N/m"], [0])]),
    ("El protocolo {0} es la base de Internet.", [(["TCP/IP", "UDP", "HTTP/2"], [0])]),
    ("En Python, {0} compara igualdad y {1} asigna un valor.", [(["==", "=", "!="], [0]), (["=", "==", ":="], [0])]),
    ("En una lista de Python, el índice del primer elemento es {0}.", [(["0", "1", "-1"], [0])]),
    ("La fórmula del agua es {0} y la del dióxido de carbono es {1}.",
     [(["H₂O", "HO₂", "H₂O₂"], [0]), (["CO₂", "C₂O", "CO"], [0])]),
    ("En un archivo CSV el separador suele ser {0}; en Moodle las opciones de un Cloze se separan con {1}.",
     [(["la coma (,)", "el punto y coma (;)", "la barra (|)"], [1]), (["la tilde (~)", "el numeral (#)", "la barra (|)"], [0])]),
]


def x08():
    name = "x08_caracteres_especiales"
    rng = random.Random(name)
    qs = ([mc(t, rng) for t in SPECIAL_MC] + [tf(t) for t in SPECIAL_TF] + [cloze(t) for t in SPECIAL_CLOZE]
          + [sa(("¿Qué operador de Python realiza la comparación de igualdad?", "==")),
             sa(("Escribe el símbolo químico del oro.", "Au")),
             num(("¿Cuánto es 3² + 4²?", "25")), num(("¿Cuál es el resultado de 10 ÷ 4? (usa coma decimal)", "2,5"))])
    rng.shuffle(qs)
    pdfmetrics.registerFont(TTFont("AU", UNICODE_FONT))
    story: list = []
    with font_swap("AU"):
        G.header(story, "Cuestionario de Notación y Sintaxis", "Incluye símbolos, código y caracteres especiales.")
        key = []
        for i, q in enumerate(qs, 1):
            line = G.draw_question(story, i, q, rng, mark="none")
            if line:
                key.append(line)
        story.append(PageBreak())
        story.append(G.p("CLAVE DE RESPUESTAS", G.HEAD))
        story += [G.p(k) for k in key]
        finish(name, story, qs, focus="Caracteres especiales",
               notes="36 preguntas con &, <, >, ]]>, {1:MULTICHOICE:…}, ~, #, barras invertidas, '|' como opción "
                     "(el separador de respuestas múltiples), '/' dentro de las opciones de un Cloze (km/h, "
                     "TCP/IP), ';' y '|' dentro de opciones Cloze, símbolos matemáticos y subíndices Unicode.")


# ── x09 — Emparejamientos y Cloze complejos ─────────────────────────────────

EXTRA_CLOZE = [
    ("Son lenguajes de programación: {0}.", [(["Python", "HTML", "Java", "CSS"], [0, 2])]),
    ("Son planetas rocosos: {0} y también {1}.", [(["Mercurio", "Júpiter", "Venus", "Saturno"], [0, 2]), (["Marte", "Neptuno", "Urano"], [0])]),
]


def x09():
    name = "x09_emparejamiento_cloze"
    rng = random.Random(name)
    matches = [match(t) for t in take(rng, B.MATCH, 12)]
    clozes = [cloze(t) for t in take(rng, B.CLOZE, 12)] + [cloze(t) for t in EXTRA_CLOZE]
    qs: list = []
    slots = list(range(36))
    rng.shuffle(slots)
    pools = matches + clozes + [cf(mc(t, rng), rng) for t in take(rng, B.MC, 6)] + [cf(tf(t), rng) for t in take(rng, B.TF, 4)]
    rng.shuffle(pools)
    qs = pools
    bank_idx = [i for i, q in enumerate(qs) if q["type"] == "cloze" and len(q["blanks"]) == 1 and len(q["blanks"][0]["correct"]) == 1][:3]

    story: list = []
    G.header(story, "Relaciona y Completa", "Preguntas de emparejamiento y de completar.")
    key = []
    v = 0
    for i, q in enumerate(qs, 1):
        if q["type"] == "matching":
            variant = v % 4
            v += 1
            rights = [r for _, r in q["pairs"]] + q["extra_right"]
            order = rights[:]
            rng.shuffle(order)
            story.append(G.p(f"{i}. {q['stem']}", G.STEM))
            n_rows = max(len(q["pairs"]), len(order))
            a_lab = (lambda k: f"{LETTERS[k].upper()}.") if variant == 1 else (lambda k: f"{k + 1}.")
            b_lab = {0: lambda k: f"{LETTERS[k]}.", 1: lambda k: f"{k + 1}.", 2: lambda k: f"{roman(k)}.", 3: lambda k: f"{LETTERS[k]}."}[variant]
            if variant == 3:
                story.append(G.p("Columna A", G.HEAD))
                story += [G.p(f"{a_lab(k)} {p_[0]}", G.OPT) for k, p_ in enumerate(q["pairs"])]
                story.append(G.p("Columna B", G.HEAD))
                story += [G.p(f"{b_lab(k)} {o}", G.OPT) for k, o in enumerate(order)]
            else:
                rows = [["Columna A", "Columna B"]]
                for k in range(n_rows):
                    rows.append([f"{a_lab(k)} {q['pairs'][k][0]}" if k < len(q["pairs"]) else "", f"{b_lab(k)} {order[k]}" if k < len(order) else ""])
                t = Table(rows, colWidths=[7 * cm, 7.5 * cm])
                t.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 10), ("FONT", (0, 1), (-1, -1), "Helvetica", 10),
                                       ("LEFTPADDING", (0, 0), (-1, -1), 18)]))
                story.append(t)
            pairs_key = [(a_lab(k).rstrip("."), b_lab(order.index(r)).rstrip(".")) for k, (_, r) in enumerate(q["pairs"])]
            if variant == 0:
                key.append(f"{i}. " + ", ".join(f"{a}-{b}" for a, b in pairs_key))
            elif variant == 1:
                key.append(f"{i}. " + "; ".join(f"{a}→{b}" for a, b in pairs_key))
            elif variant == 2:
                key.append(f"{i}. " + ", ".join(f"{a}-{b}" for a, b in pairs_key))
            else:
                key.append(f"{i}. " + "  ".join(f"{a}{b}" for a, b in pairs_key))
        elif q["type"] == "cloze" and i - 1 in bank_idx:
            bank_start = i - 1 == bank_idx[0]
            if bank_start:
                words = [q2["blanks"][0]["options"][q2["blanks"][0]["correct"][0]] for q2 in (qs[j] for j in bank_idx)]
                extra = ["azul", "isla", "veloz"]
                bank = words + extra
                rng.shuffle(bank)
                story.append(G.p("Banco de palabras (para las preguntas siguientes que tengan espacios sin opciones): " + " · ".join(bank), G.BODY))
            story.append(G.p(f"{i}. Completa: " + q["text"].format(*["________"] * len(q["blanks"])), G.STEM))
            key.append(f"{i}. " + ", ".join(b["options"][b["correct"][0]] for b in q["blanks"]))
        elif q["type"] == "cloze":
            parts = ["________ (" + " / ".join(b["options"]) + ")" for b in q["blanks"]]
            story.append(G.p(f"{i}. Completa: " + q["text"].format(*parts), G.STEM))
            key.append(f"{i}. " + ", ".join(" y ".join(b["options"][c] for c in b["correct"]) for b in q["blanks"]))
        else:
            line = G.draw_question(story, i, q, rng, mark="none")
            key.append(line)
    story.append(PageBreak())
    story.append(G.p("CLAVE DE RESPUESTAS", G.HEAD))
    story += [G.p(k) for k in key]
    finish(name, story, qs, focus="Emparejamiento y Cloze complejos",
           notes="12 emparejamientos en 4 variantes (A numerada/B lettered; A con letras/B con números; B con "
                 "números romanos; columnas como listas), con distractores en la columna B y claves 'A→2', "
                 "'1-III', 'A2 B1'; 14 Cloze (hasta 3 huecos, respuestas múltiples y 3 con banco de palabras "
                 "compartido); 6 opción múltiple y 4 V/F.")


# ── x10 — Escaneado degradado con marcas de color ───────────────────────────

def degrade(img: Image.Image, rng: random.Random) -> Image.Image:
    img = img.convert("RGB").rotate(rng.uniform(-1.4, 1.4), resample=Image.BICUBIC, fillcolor=(255, 255, 255))
    img = img.filter(ImageFilter.GaussianBlur(0.7))
    px, (w, h) = img.load(), img.size
    for _ in range(int(w * h * 0.004)):
        x, y, val = rng.randrange(w), rng.randrange(h), rng.randrange(40, 200)
        px[x, y] = (val, val, val)
    return img


def x10():
    import pdfplumber
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    name = "x10_escaneado_degradado"
    rng = random.Random(name)
    qs = ([cf(mc(t, rng), rng) for t in take(rng, B.MC, 23)] + [multi(t, rng) for t in take(rng, B.MULTI, 3)]
          + [cf(tf(t), rng) for t in take(rng, B.TF, 6)])
    rng.shuffle(qs)
    story: list = []
    G.header(story, "Examen Escaneado (baja calidad)", "Las respuestas correctas están en rojo.")
    for i, q in enumerate(qs, 1):
        if q["type"] == "truefalse":
            story.append(tf_line(f"{i}.", q, red_word=True))
        else:
            G.draw_question(story, i, q, rng, mark="color")
    check_size(name, qs)
    clean = G.build_pdf(name + "__limpio", story)
    (PDF_DIR / f"{name}__limpio.pdf").unlink()          # solo se conserva la versión escaneada
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    w, h = letter
    with pdfplumber.open(io.BytesIO(clean)) as pdf:
        for page in pdf.pages:
            img = degrade(page.to_image(resolution=100).original, rng)
            b = io.BytesIO()
            img.save(b, "JPEG", quality=40)
            b.seek(0)
            c.drawImage(ImageReader(b), 0, 0, width=w, height=h)
            c.showPage()
    c.save()
    (PDF_DIR / f"{name}.pdf").write_bytes(buf.getvalue())
    write_golden(name, [G.golden_question(q) for q in qs], focus="Escaneado degradado", path="normalize_with_ai",
                 notes="32 preguntas como imagen pura (sin capa de texto): 100 dpi, JPEG calidad 40, giro de ±1,4°, "
                       "desenfoque y ruido. Respuestas solo en rojo (el color solo se puede leer viendo la imagen); "
                       "~25 % contrafácticas. Camino 'Normalizar con IA'.")
    print(f"  {name}: {len(qs)} preguntas")


# ── x11 — Código dentro de imágenes ─────────────────────────────────────────

SNIPPETS = [
    ("python", 'x = 5\ny = 3\nprint(x * y + 2)', "17", ["15", "13", "Error"]),
    ("python", 'nombres = ["Ana", "Luis", "Marta"]\nfor n in nombres:\n    if len(n) > 3:\n        print(n)', "Luis y Marta",
     ["Ana y Luis", "Solo Marta", "Ninguno"]),
    ("python", 'def f(n):\n    if n <= 1:\n        return 1\n    return n * f(n - 1)\n\nprint(f(4))', "24", ["10", "16", "12"]),
    ("python", 'd = {"a": 1, "b": 2}\nd["c"] = d["a"] + d["b"]\nprint(d["c"])', "3", ["1", "2", "KeyError"]),
    ("python", 'i = 0\nwhile i < 3:\n    print(i)\n    i += 1', "0 1 2", ["1 2 3", "0 1 2 3", "Bucle infinito"]),
    ("python", 's = "programacion"\nprint(s[0:4])', "prog", ["progr", "rogr", "ogra"]),
    ("python", 'print([x * 2 for x in range(4)])', "[0, 2, 4, 6]", ["[2, 4, 6, 8]", "[0, 1, 2, 3]", "[0, 2, 4]"]),
    ("python", 'try:\n    print(10 / 0)\nexcept ZeroDivisionError:\n    print("error")', "error", ["10", "0", "Nada"]),
    ("python", 'print(3 > 2 and 2 > 5)', "False", ["True", "None", "Error"]),
    ("python", 'a, b = 1, 2\na, b = b, a\nprint(a, b)', "2 1", ["1 2", "2 2", "1 1"]),
    ("python", 'def f(x, y=2):\n    return x ** y\n\nprint(f(3))', "9", ["6", "5", "Error"]),
    ("javascript", 'let n = 4;\nconsole.log(n % 3);', "1", ["0", "3", "4"]),
]
CODE_KW = {"def", "return", "if", "else", "for", "while", "in", "try", "except", "let", "print", "and", "or", "console"}
_TOK = re.compile(r'(#[^\n]*|//[^\n]*)|("[^"\n]*")|(\b\d+\b)|(\b[A-Za-z_]\w*\b)|(\s+)|(.)')


def code_png(code: str) -> tuple[bytes, int, int]:
    font_ = ImageFont.truetype(MONO_FONT, 20)
    lines = code.split("\n")
    lh, pad = 30, 16
    width = max(int(font_.getlength(ln)) for ln in lines) + 2 * pad + 40
    width = max(width, 420)
    img = Image.new("RGB", (width, lh * len(lines) + 2 * pad), (246, 248, 250))
    d = ImageDraw.Draw(img)
    for k, ln in enumerate(lines):
        y = pad + k * lh
        d.text((pad // 2, y), str(k + 1), font=font_, fill=(150, 150, 150))
        x = pad + 26
        for m in _TOK.finditer(ln):
            piece = m.group(0)
            color = (30, 30, 30)
            if m.group(1):
                color = (110, 120, 130)
            elif m.group(2):
                color = (6, 125, 23)
            elif m.group(3):
                color = (200, 100, 0)
            elif m.group(4) and piece in CODE_KW:
                color = (0, 0, 200)
            d.text((x, y), piece, font=font_, fill=color)
            x += font_.getlength(piece)
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue(), img.width, img.height


def x11():
    name = "x11_codigo_en_imagen"
    rng = random.Random(name)
    prompts = ["¿Qué se muestra en pantalla al ejecutar el siguiente código?", "Analiza el fragmento y elige la salida correcta:",
               "Observa el siguiente programa. ¿Cuál es su resultado?"]
    qs: list = []
    for k, (lang, code, out, wrong) in enumerate(SNIPPETS):
        opts = [out] + wrong
        idx = list(range(4))
        rng.shuffle(idx)
        q = {"type": "multichoice", "stem": prompts[k % 3], "code": code,
             "options": [opts[i] for i in idx], "correct": [idx.index(0)]}
        qs.append(cf(q, rng, 0.25))
    for k, (lang, code, out, wrong) in enumerate(SNIPPETS[:8]):
        truth = rng.random() < 0.5
        shown = out if truth else wrong[0]
        qs.append(cf({"type": "truefalse", "stem": f"El programa de la imagen imprime «{shown}».", "code": code,
                      "answer": "Verdadero" if truth else "Falso"}, rng, 0.25))
    prog = [t for t in B.MC if any(w in t[0] for w in ("Python", "SQL", "HTTP", "Git", "bits", "byte", "kernel", "CPU", "bucle"))]
    qs += [cf(mc(t, rng), rng) for t in take(rng, prog, 10)]
    rng.shuffle(qs)

    story: list = []
    G.header(story, "Examen de Programación (con capturas de código)", "Algunas preguntas incluyen una imagen con el código.")
    key = []
    for i, q in enumerate(qs, 1):
        if q["type"] == "truefalse":
            story.append(G.p(f"{i}. {q['stem']}   (   ) Verdadero   (   ) Falso", G.STEM))
            key.append(f"{i}. {q['answer']}")
        else:
            story.append(G.p(f"{i}. {q['stem']}", G.STEM))
        if q.get("code"):
            png, w_px, h_px = code_png(q["code"])
            story.append(RLImage(io.BytesIO(png), width=w_px * 0.5, height=h_px * 0.5, hAlign="LEFT"))
        if q["type"] == "multichoice":
            for k, opt in enumerate(q["options"]):
                story.append(G.p(f"{LETTERS[k]}) {opt}", G.OPT))
            key.append(f"{i}. " + ", ".join(LETTERS[x] for x in q["correct"]))
    story.append(PageBreak())
    story.append(G.p("CLAVE DE RESPUESTAS", G.HEAD))
    story += [G.p(k) for k in key]
    check_size(name, qs)
    G.build_pdf(name, story)
    golden = []
    for q in qs:
        g = G.golden_question(q)
        if q.get("code"):
            g["stem"] = f"{q['stem']}\n{q['code']}"       # el código solo existe en la imagen
        golden.append(g)
    write_golden(name, golden, focus="Código en imágenes",
                 notes="30 preguntas; 20 traen el código como IMAGEN incrustada (resaltado de sintaxis, números de "
                       "línea) y solo ahí; el golden exige el enunciado con el código transcrito (REGLA 9). "
                       "Incluye 8 V/F sobre la salida del programa. ~25 % contrafácticas.")
    print(f"  {name}: {len(qs)} preguntas")


# ── x12 — Clave parcial: la mayoría sin respuesta ───────────────────────────

def x12():
    name = "x12_clave_parcial"
    rng = random.Random(name)
    qs = ([cf(mc(t, rng), rng) for t in take(rng, B.MC, 14)] + [cf(tf(t), rng) for t in take(rng, B.TF, 6)]
          + [match(t) for t in take(rng, B.MATCH, 4)] + [cloze(t) for t in take(rng, B.CLOZE, 4)]
          + [sa(t) for t in take(rng, B.SA, 4)] + [num(t) for t in take(rng, B.NUM, 4)]
          + [essay(s) for s in take(rng, B.ESSAY, 4)])
    rng.shuffle(qs)
    gradable = [i for i, q in enumerate(qs) if q["type"] != "essay"]
    blank = set(rng.sample(gradable, round(len(gradable) * 0.55)))
    for i in blank:
        qs[i] = dict(qs[i], unanswered=True)
        if qs[i]["type"] == "multichoice":
            qs[i]["correct"] = []
    story: list = []
    G.header(story, "Borrador de Examen (clave incompleta)", "El docente todavía no completó todas las respuestas.")
    key = []
    for i, q in enumerate(qs, 1):
        line = G.draw_question(story, i, q, rng, mark="none")
        if line and (i - 1) not in blank:
            key.append(line)
    story.append(PageBreak())
    story.append(G.p("CLAVE PARCIAL — faltan las respuestas de varias preguntas", G.HEAD))
    story += [G.p(k) for k in key]
    finish(name, story, qs, focus="Clave incompleta (no inventar)",
           notes="40 preguntas de los 7 tipos donde ~55 % de las autocalificables NO tienen respuesta en el documento "
                 "(ni clave ni marca). Lo correcto es omitirlas; cualquier respuesta que salga es inventada.")


# ── x13 — Marcas mezcladas: cada pregunta usa la suya ──────────────────────

def x13():
    name = "x13_marcas_mixtas"
    rng = random.Random(name)
    qs = ([cf(mc(t, rng), rng) for t in take(rng, B.MC, 24)] + [multi(t, rng) for t in take(rng, B.MULTI, 4)]
          + [cf(tf(t), rng, 0.3) for t in take(rng, B.TF, 6)] + [sa(t) for t in take(rng, B.SA, 4)]
          + [dict(mc(t, rng), correct=[], unanswered=True) for t in take(rng, B.MC, 2)])
    rng.shuffle(qs)
    marks = ["color", "highlight", "underline", "bold"]        # una marca distinta por pregunta, en rotación
    story: list = []
    G.header(story, "Examen con Marcas Mezcladas", "Cada pregunta marca su respuesta a su manera (color, resaltado, subrayado, negrita o texto).")
    k = t = 0
    for i, q in enumerate(qs, 1):
        if i in (1, 14, 27):
            story.append(raw(font(f"Sección {'ABC'[(i - 1) // 13]}", bold=True), G.HEAD))       # títulos en negrita: no son respuestas
        if q["type"] == "truefalse":
            style = t % 3
            t += 1
            if style == 0:
                story.append(tf_line(f"{i}.", q, red_word=True))
            elif style == 1:
                story.append(tf_line(f"{i}.", q, x_marks=True))
            else:
                story.append(G.p(f"{i}. {q['stem']}   (   ) Verdadero   (   ) Falso", G.STEM))
                story.append(G.p(f"Respuesta: {q['answer']}", G.OPT))
        elif q["type"] == "shortanswer":
            story.append(G.p(f"{i}. {q['stem']}", G.STEM))
            story.append(G.p(f"Respuesta: {q['answer']}", G.OPT))
        else:
            story.append(G.p(f"{i}. {q['stem']}" + (" (seleccione todas las que apliquen)" if len(q["correct"]) > 1 else ""), G.STEM))
            mark = marks[k % 4]
            k += 1
            for j, opt in enumerate(q["options"]):
                on = j in q["correct"]
                story.append(G.p(f"{LETTERS[j]}) {opt}", G.OPT, RED if (on and mark == "color") else None,
                                 mark if (on and mark != "color") else None))
    finish(name, story, qs, focus="Marcas mezcladas",
           notes="40 preguntas donde cada una marca su respuesta de otra forma: color rojo, resaltado, subrayado o "
                 "negrita (en rotación), V/F con la palabra en rojo, con ( X ) o con una línea 'Respuesta: …', y "
                 "respuesta corta con 'Respuesta: …'. Títulos de sección en negrita como distractor y 2 preguntas "
                 "sin ninguna respuesta. ~25 % de claves contrafácticas.")


def main():
    print("Generando exámenes adversariales…")
    for fn in (x01, x02, x03, x04, x05, x06, x07, x08, x09, x10, x11, x12, x13):
        fn()
    for f in sorted(PDF_DIR.glob("x*.pdf")):
        print(f"  {f.relative_to(ROOT)}  ({f.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
