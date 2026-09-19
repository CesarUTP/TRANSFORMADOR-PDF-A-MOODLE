"""
generate.py — Genera los PDFs sintéticos del set de regresión y su golden.

    backend/venv/bin/python dev/synthetic/generate.py

Escribe:
    samples/synthetic/<nombre>.pdf
    samples/golden/<nombre>.expected.json

Cada PDF se dibuja a partir de los datos de exams.py, así que el golden
(la respuesta correcta de cada pregunta) es exacto por construcción.
Es determinista: correrlo dos veces produce los mismos archivos.

Requiere reportlab (dev/requirements-dev.txt).
"""

import io
import json
import random
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

sys.path.insert(0, str(Path(__file__).parent))
import exams as E  # noqa: E402

# Sin fecha de creación ni ID aleatorio en el PDF: regenerar produce
# exactamente los mismos bytes, así git no ve cambios si el contenido no
# cambió.
rl_config.invariant = 1

ROOT = Path(__file__).resolve().parents[2]
PDF_DIR = ROOT / "samples" / "synthetic"
GOLDEN_DIR = ROOT / "samples" / "golden"

LETTERS = "abcdefghijklmnopqrstuvwxyz"

BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=10.5, leading=14, spaceAfter=2)
STEM = ParagraphStyle("stem", parent=BODY, fontName="Helvetica", spaceBefore=8)
TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=15, leading=19, spaceAfter=6)
HEAD = ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=12, leading=16, spaceBefore=10, spaceAfter=4)
OPT = ParagraphStyle("opt", parent=BODY, leftIndent=18)

RED = "#c00000"
BLUE = "#1f4e9c"


def p(text: str, style=BODY, color: str | None = None) -> Paragraph:
    t = escape(text).replace("\n", "<br/>")
    if color:
        t = f'<font color="{color}">{t}</font>'
    return Paragraph(t, style)


def header(story: list, title: str, subtitle: str, title_color: str | None = None) -> None:
    story.append(p(title, TITLE, title_color))
    story.append(p(subtitle))
    story.append(p("Nombre: ______________________    Fecha: ____________"))
    story.append(Spacer(1, 8))


# ── Golden ───────────────────────────────────────────────────────────────────

def golden_question(q: dict) -> dict:
    """Convierte una pregunta de exams.py al formato del golden."""
    t = q["type"]
    g = {"type": t}
    if t == "multichoice":
        g["stem"] = q["stem"]
        g["answers"] = [q["options"][i] for i in q["correct"]]
        g["options"] = list(q["options"])
    elif t == "truefalse":
        g["stem"] = q["stem"]
        g["answers"] = [q["answer"]]
    elif t == "matching":
        g["stem"] = q.get("stem", "")
        g["pairs"] = [list(x) for x in q["pairs"]]
    elif t == "cloze":
        g["stem"] = q["text"].format(*["____"] * len(q["blanks"]))
        g["blanks"] = [[b["options"][i] for i in b["correct"]] for b in q["blanks"]]
    elif t == "essay":
        g["stem"] = q["stem"]
    elif t in ("shortanswer", "numerical"):
        g["stem"] = q["stem"]
        g["answers"] = [q["answer"]]
    if q.get("unanswered"):
        g["unanswered"] = True
    return g


def table_as_matching(tabla: dict) -> dict:
    return {
        "type": "matching", "stem": tabla["stem"], "from_table": True,
        "pairs": [[row, tabla["columns"][col]] for row, col in tabla["rows"]],
    }


def write_golden(name: str, questions: list, *, path: str = "parse", is_exam: bool = True,
                 notes: str = "") -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    doc = {
        "source": "synthetic",
        "reviewed": True,  # exacto por construcción
        "file": f"synthetic/{name}.pdf",
        "path": path,
        "is_exam": is_exam,
        "notes": notes,
        "questions": questions,
    }
    (GOLDEN_DIR / f"{name}.expected.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ── Dibujado de preguntas ────────────────────────────────────────────────────

def matching_layout(q: dict, rng: random.Random):
    """Columna B barajada de forma determinista; devuelve (orden_b, clave)."""
    rights = [r for _, r in q["pairs"]] + list(q.get("extra_right", []))
    order = rights[:]
    rng.shuffle(order)
    key = [f"{i + 1}-{LETTERS[order.index(r)]}" for i, (_, r) in enumerate(q["pairs"])]
    return order, ", ".join(key)


def draw_question(story: list, n: int, q: dict, rng: random.Random, *, mark: str = "none") -> str:
    """
    Dibuja una pregunta y devuelve su línea para la clave del final.
    mark: "none" (la respuesta va solo en la clave), "color" (opciones
    correctas en rojo), "asterisk" (opción correcta con *).
    """
    t = q["type"]
    if t == "multichoice":
        story.append(p(f"{n}. {q['stem']}", STEM))
        for i, opt in enumerate(q["options"]):
            is_ok = i in q["correct"]
            label = f"{LETTERS[i]}) {opt}"
            if mark == "asterisk" and is_ok:
                label = f"{LETTERS[i]}) {opt} *"
            story.append(p(label, OPT, RED if (mark == "color" and is_ok) else None))
        if q.get("unanswered"):
            return ""
        return f"{n}. " + ", ".join(LETTERS[i] for i in q["correct"])
    if t == "truefalse":
        story.append(p(f"{n}. {q['stem']}   (   ) Verdadero   (   ) Falso", STEM))
        return f"{n}. {q['answer']}"
    if t == "matching":
        story.append(p(f"{n}. {q['stem']}", STEM))
        order, key = matching_layout(q, rng)
        data = [["Columna A", "Columna B"]]
        for i in range(max(len(q["pairs"]), len(order))):
            left = f"{i + 1}. {q['pairs'][i][0]}" if i < len(q["pairs"]) else ""
            right = f"{LETTERS[i]}. {order[i]}" if i < len(order) else ""
            data.append([left, right])
        tbl = Table(data, colWidths=[7 * cm, 7 * cm])
        tbl.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 10),
            ("FONT", (0, 1), (-1, -1), "Helvetica", 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 18),
        ]))
        story.append(tbl)
        return f"{n}. {key}"
    if t == "cloze":
        parts = []
        for b in q["blanks"]:
            parts.append("________ (" + " / ".join(b["options"]) + ")")
        story.append(p(f"{n}. Completa: " + q["text"].format(*parts), STEM))
        if q.get("word_bank_only"):
            return ""
        answers = ", ".join(b["options"][b["correct"][0]] for b in q["blanks"])
        return f"{n}. {answers}"
    if t == "essay":
        story.append(p(f"{n}. {q['stem']}", STEM))
        story.append(p("_" * 80))
        story.append(p("_" * 80))
        return f"{n}. Respuesta abierta (se califica con rúbrica)."
    if t in ("shortanswer", "numerical"):
        story.append(p(f"{n}. {q['stem']}  ______________", STEM))
        return f"{n}. {q['answer']}"
    raise ValueError(t)


def build_pdf(name: str, story: list) -> bytes:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm,
                            title=name, author="set sintético", creator="dev/synthetic/generate.py")
    doc.build(story)
    data = buf.getvalue()
    (PDF_DIR / f"{name}.pdf").write_bytes(data)
    return data


def exam_with_key(name: str, title: str, questions: list, *, mark: str = "none",
                  key_title: str = "CLAVE DE RESPUESTAS", notes: str = "") -> bytes:
    rng = random.Random(name)
    story: list = []
    header(story, title, "Instrucciones: responde todas las preguntas.")
    key_lines = []
    for i, q in enumerate(questions, 1):
        line = draw_question(story, i, q, rng, mark=mark)
        if line:
            key_lines.append(line)
    if key_lines:
        story.append(PageBreak())
        story.append(p(key_title, HEAD))
        for line in key_lines:
            story.append(p(line))
    data = build_pdf(name, story)
    write_golden(name, [golden_question(q) for q in questions], notes=notes)
    return data


# ── Exámenes ─────────────────────────────────────────────────────────────────

def s01_limpio():
    return exam_with_key(
        "s01_limpio_clave_final", "Evaluación de Ciencias y Cultura General", E.BASE_MIXED,
        notes="Los 7 tipos, respuestas solo en la clave al final (formato típico de docente).")


def s02_color():
    name = "s02_color_sin_imagenes"
    story: list = []
    # Título y encabezado de sección TAMBIÉN en color (azul): no son respuestas.
    header(story, "Parcial de Fundamentos de Programación", "Las respuestas correctas están resaltadas.",
           title_color=BLUE)
    story.append(p("Sección 1: Tipos y estructuras de datos", HEAD, BLUE))
    rng = random.Random(name)
    for i, q in enumerate(E.COLOR_MC, 1):
        draw_question(story, i, q, rng, mark="color")
        if i == 4:
            story.append(p("Sección 2: Sintaxis y operadores", HEAD, BLUE))
    build_pdf(name, story)
    write_golden(name, [golden_question(q) for q in E.COLOR_MC],
                 notes="Respuestas marcadas SOLO con texto rojo, sin imágenes ni clave; títulos en azul "
                       "como distractor; 3 preguntas con varias correctas.")


def s03_afirmaciones():
    return exam_with_key(
        "s03_enunciados_con_lista_AB", "Cuestionario de Razonamiento", E.AFIRMACIONES,
        notes="Enunciados que contienen su propia lista A./B. antes de las opciones "
              "(el parser de texto los trunca en silencio).")


def s04_tabla():
    name = "s04_tabla_de_marcas"
    rng = random.Random(name)
    story: list = []
    header(story, "Práctica de Operadores", "Resuelve las siguientes preguntas.")
    story.append(p(f"1. {E.TABLA['stem']}", STEM))
    data = [["Situación"] + E.TABLA["columns"]]
    for row, col in E.TABLA["rows"]:
        data.append([row] + ["X" if j == col else "" for j in range(len(E.TABLA["columns"]))])
    tbl = Table(data, colWidths=[8.2 * cm] + [2.2 * cm] * len(E.TABLA["columns"]))
    tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(tbl)
    key_lines = []
    for i, q in enumerate(E.TABLA_EXTRA, 2):
        key_lines.append(draw_question(story, i, q, rng))
    story.append(Spacer(1, 12))
    story.append(p("CLAVE (preguntas 2 en adelante)", HEAD))
    for line in key_lines:
        story.append(p(line))
    build_pdf(name, story)
    write_golden(name, [table_as_matching(E.TABLA)] + [golden_question(q) for q in E.TABLA_EXTRA],
                 notes="Tabla con una X por fila (REGLA 10 → emparejamiento) + 2 preguntas normales.")


def s05_largo():
    return exam_with_key(
        "s05_largo_60_preguntas", "Examen Final de Aritmética", E.long_exam(60),
        notes="60 preguntas en varias páginas; mide si el modelo se salta preguntas en documentos largos.")


def s06_escaneado(clean_pdf: bytes):
    """Las páginas de s01 como imagen pura: sin capa de texto (PDF 'escaneado')."""
    import pdfplumber
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    name = "s06_escaneado_sin_texto"
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    w, h = letter
    with pdfplumber.open(io.BytesIO(clean_pdf)) as pdf:
        for page in pdf.pages:
            # Escala de grises + JPEG de baja calidad: se parece a un escaneo
            # real y, sobre todo, no deja NINGUNA capa de texto extraíble.
            img = page.to_image(resolution=110).original.convert("L")
            b = io.BytesIO()
            img.save(b, "JPEG", quality=70)
            b.seek(0)
            c.drawImage(ImageReader(b), 0, 0, width=w, height=h)
            c.showPage()
    c.save()
    (PDF_DIR / f"{name}.pdf").write_bytes(buf.getvalue())
    write_golden(name, [golden_question(q) for q in E.BASE_MIXED], path="normalize_with_ai",
                 notes="Mismo contenido que s01, pero solo imágenes (sin texto extraíble). "
                       "Se procesa por el camino 'Normalizar con IA'.")


def s07_no_examen():
    name = "s07_no_es_examen"
    story: list = []
    for i, par in enumerate(E.NO_EXAMEN_PARRAFOS):
        story.append(p(par, TITLE if i == 0 else BODY))
        story.append(Spacer(1, 6))
    build_pdf(name, story)
    write_golden(name, [], is_exam=False,
                 notes="Manual técnico con lista numerada y las palabras 'respuesta'/'preguntas'. "
                       "Debe rechazarse, nunca inventar preguntas.")


def s08_asterisco():
    return exam_with_key(
        "s08_asterisco_y_sin_marca", "Cuestionario de Historia y Ciencia", E.ASTERISCO, mark="asterisk",
        notes="Correctas marcadas con *; 2 preguntas sin ninguna marca (deben quedar sin respuesta).")


def s09_cloze():
    return exam_with_key(
        "s09_completar_y_banco", "Actividad de Completar", E.CLOZE,
        notes="Cloze con 1-2 huecos; el hueco de la pregunta 4 solo tiene banco de palabras "
              "y no está en la clave (REGLA 6: no se debe inventar).")


def s10_estres():
    return exam_with_key(
        "s10_estres_150_preguntas", "Banco Extenso de Aritmética", E.long_exam(150),
        notes="Prueba de estrés: 150 preguntas. Mide el techo del modo JSON (salida más larga) "
              "y si el modelo se salta preguntas en un documento muy largo.")


def main():
    clean = s01_limpio()
    s02_color()
    s03_afirmaciones()
    s04_tabla()
    s05_largo()
    s06_escaneado(clean)
    s07_no_examen()
    s08_asterisco()
    s09_cloze()
    s10_estres()
    for f in sorted(PDF_DIR.glob("*.pdf")):
        print(f"  {f.relative_to(ROOT)}  ({f.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
