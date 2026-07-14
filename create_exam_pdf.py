"""
Genera prueba_examen.pdf — examen de práctica para el convertidor PDF→Moodle.
Usa Arial TTF para soporte completo de Unicode (incluye flecha → requerida por matching).
"""
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

OUTPUT = "prueba_examen.pdf"

# Registrar Arial con soporte Unicode completo (necesario para la flecha →)
pdfmetrics.registerFont(TTFont("Arial",      r"C:\Windows\Fonts\arial.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Bold", r"C:\Windows\Fonts\arialbd.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Italic", r"C:\Windows\Fonts\ariali.ttf"))

W, H = letter

def add_page_number(canvas, doc):
    canvas.saveState()
    canvas.setFont("Arial", 9)
    canvas.setFillColor(colors.grey)
    canvas.drawCentredString(W / 2, 0.45 * inch, f"— {doc.page} —")
    canvas.restoreState()


# ── Estilos ──────────────────────────────────────────────────────────────────
s = getSampleStyleSheet()

def st(name, **kw):
    base = kw.pop("parent", s["Normal"])
    return ParagraphStyle(name, parent=base, **kw)

title   = st("T",  fontName="Arial-Bold",   fontSize=14, alignment=TA_CENTER, spaceAfter=3)
sub     = st("S",  fontName="Arial",         fontSize=10, alignment=TA_CENTER, spaceAfter=14,
             textColor=colors.HexColor("#555555"))
field   = st("F",  fontName="Arial",         fontSize=10, spaceAfter=4)
section = st("SC", fontName="Arial-Bold",    fontSize=11, spaceBefore=10, spaceAfter=5,
             textColor=colors.HexColor("#1a237e"),
             borderPad=3, backColor=colors.HexColor("#e8eaf6"),
             borderWidth=0, leftIndent=-2)
instr   = st("IN", fontName="Arial-Italic",  fontSize=9.5, spaceAfter=8,
             textColor=colors.HexColor("#444444"))
qlabel  = st("QL", fontName="Arial-Bold",    fontSize=10.5, spaceAfter=2)
body    = st("B",  fontName="Arial",         fontSize=10.5, spaceAfter=2)
opt     = st("O",  fontName="Arial",         fontSize=10.5, spaceAfter=2, leftIndent=22)
colhdr  = st("CH", fontName="Arial-Bold",    fontSize=10.5, spaceAfter=2, leftIndent=10)
colitem = st("CI", fontName="Arial",         fontSize=10.5, spaceAfter=2, leftIndent=24)
note    = st("N",  fontName="Arial-Italic",  fontSize=9, spaceAfter=6,
             textColor=colors.HexColor("#555555"))
rhdr    = st("RH", fontName="Arial-Bold",    fontSize=10.5, spaceAfter=4)
rline   = st("RL", fontName="Arial",         fontSize=10,   spaceAfter=2, leftIndent=10)
rtitle  = st("RT", fontName="Arial-Bold",    fontSize=12,   spaceAfter=6)

# ── Documento ─────────────────────────────────────────────────────────────────
doc = SimpleDocTemplate(
    OUTPUT, pagesize=letter,
    rightMargin=inch, leftMargin=inch,
    topMargin=0.9 * inch, bottomMargin=0.75 * inch,
)

def HR(thick=0.8, color="#bbbbbb", before=6, after=8):
    return HRFlowable(width="100%", thickness=thick,
                      color=colors.HexColor(color),
                      spaceBefore=before, spaceAfter=after)

story = []

# ── Cabecera ──────────────────────────────────────────────────────────────────
story += [
    Paragraph("EXAMEN: HISTORIA Y GEOGRAFÍA GENERAL", title),
    Paragraph("Educación Media | Total: 100 puntos | Tiempo: 60 minutos", sub),
    HR(1.5, "#1a237e", 0, 6),
    Paragraph("Nombre: _________________________________    Fecha: ___________    Puntaje: _______ / 100", field),
    HR(after=10),
]

# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 1 — SELECCIÓN MÚLTIPLE
# ══════════════════════════════════════════════════════════════════════════════
story += [
    Paragraph("SECCIÓN 1 — SELECCIÓN MÚLTIPLE   (5 preguntas × 6 pts = 30 pts)", section),
    Paragraph("Instrucciones: Marque con una X la letra de la respuesta correcta.", instr),
]

mc_qs = [
    ("Pregunta 1:", "¿Cuál es el país más extenso del mundo por superficie?",
     ["A. China", "B. Canadá", "C. Rusia", "D. Brasil"]),
    ("Pregunta 2:", "¿En qué continente se encuentra el río Amazonas?",
     ["A. África", "B. Asia", "C. América del Sur", "D. Europa"]),
    ("Pregunta 3:", "¿Cuál es el océano más grande del mundo?",
     ["A. Atlántico", "B. Índico", "C. Ártico", "D. Pacífico"]),
    ("Pregunta 4:", "¿Cuál fue el primer país en enviar un ser humano al espacio?",
     ["A. Estados Unidos", "B. China", "C. Alemania", "D. Unión Soviética"]),
    ("Pregunta 5:", "¿Cuántos continentes tiene el planeta Tierra?",
     ["A. 5", "B. 6", "C. 7", "D. 8"]),
]

for label, stem, opts in mc_qs:
    story.append(Paragraph(label, qlabel))
    story.append(Paragraph(stem, body))
    for o in opts:
        story.append(Paragraph(o, opt))
    story.append(Spacer(1, 6))

# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 2 — CIERTO O FALSO
# ══════════════════════════════════════════════════════════════════════════════
story += [
    HR(),
    Paragraph("SECCIÓN 2 — CIERTO O FALSO   (5 preguntas × 6 pts = 30 pts)", section),
    Paragraph("Instrucciones: Escriba V si la afirmación es verdadera o F si es falsa.", instr),
]

tf_qs = [
    ("Pregunta 6:",  "La capital de Australia es Sídney."),
    ("Pregunta 7:",  "El Nilo es el río más largo del continente africano."),
    ("Pregunta 8:",  "El Sol es una estrella de tipo espectral G ubicada en el centro del sistema solar."),
    ("Pregunta 9:",  "La Gran Muralla China puede verse a simple vista desde el espacio."),
    ("Pregunta 10:", "El español es la lengua con más hablantes nativos en el mundo."),
]

for label, stem in tf_qs:
    story.append(Paragraph(label, qlabel))
    story.append(Paragraph(stem, body))
    story.append(Spacer(1, 6))

# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 3 — EMPAREJAMIENTO
# ══════════════════════════════════════════════════════════════════════════════
story += [
    HR(),
    Paragraph("SECCIÓN 3 — EMPAREJAMIENTO   (2 preguntas × 10 pts = 20 pts)", section),
    Paragraph("Instrucciones: Una con una línea cada elemento de la Columna A con su par correcto en la Columna B.", instr),
]

story.append(Paragraph("Pregunta 11:", qlabel))
story.append(Paragraph("Una cada capital con el país al que pertenece.", body))
story.append(Paragraph("Columna A:", colhdr))
for item in ["1. París", "2. Tokio", "3. Brasilia", "4. El Cairo"]:
    story.append(Paragraph(item, colitem))
story.append(Paragraph("Columna B:", colhdr))
for item in ["a. Francia", "b. Japón", "c. Brasil", "d. Egipto"]:
    story.append(Paragraph(item, colitem))
story.append(Spacer(1, 6))

story.append(Paragraph("Pregunta 12:", qlabel))
story.append(Paragraph("Una cada científico con su aportación más destacada.", body))
story.append(Paragraph("Columna A:", colhdr))
for item in ["1. Isaac Newton", "2. Marie Curie", "3. Albert Einstein", "4. Charles Darwin"]:
    story.append(Paragraph(item, colitem))
story.append(Paragraph("Columna B:", colhdr))
for item in [
    "a. Ley de la gravitación universal",
    "b. Descubrimiento de la radioactividad",
    "c. Teoría de la relatividad",
    "d. Teoría de la evolución",
]:
    story.append(Paragraph(item, colitem))
story.append(Spacer(1, 6))

# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 4 — COMPLETA LOS ESPACIOS
# ══════════════════════════════════════════════════════════════════════════════
story += [
    HR(),
    Paragraph("SECCIÓN 4 — COMPLETA LOS ESPACIOS   (3 preguntas × ~6.7 pts = 20 pts)", section),
    Paragraph(
        "Instrucciones: Elija la opción correcta de las que aparecen entre corchetes para completar cada oración.",
        instr,
    ),
    Paragraph(
        "Nota: el formato [A: opción correcta / alternativa / alternativa] indica un espacio a completar.",
        note,
    ),
]

story.append(Paragraph("Pregunta 13:", qlabel))
story.append(Paragraph(
    "El continente [A: Antártida / América del Sur / África] "
    "es el más frío del planeta y está cubierto casi en su totalidad por hielo.",
    body,
))
story.append(Spacer(1, 6))

story.append(Paragraph("Pregunta 14:", qlabel))
story.append(Paragraph(
    "Las plantas producen alimento mediante la fotosíntesis, "
    "un proceso que requiere [A: luz solar / lluvia / temperatura] "
    "y que libera [B: oxígeno / nitrógeno / hidrógeno] como subproducto.",
    body,
))
story.append(Spacer(1, 6))

story.append(Paragraph("Pregunta 15:", qlabel))
story.append(Paragraph(
    "El [A: Monte Everest / K2 / Monte Kilimanjaro], ubicado en el Himalaya, "
    "es la montaña más alta del mundo con [B: 8849 / 7500 / 9000] metros sobre el nivel del mar.",
    body,
))
story.append(Spacer(1, 6))

# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN DE RESPUESTAS
# ══════════════════════════════════════════════════════════════════════════════
story += [
    HR(1.5, "#1a237e", 12, 8),
    Paragraph("RESPUESTAS   (Para uso del docente únicamente)", rtitle),
    Paragraph("Nº   Tipo            Respuesta correcta", rhdr),
]

# Respuestas multichoice: texto completo de la opción correcta (no la letra)
# Respuestas truefalse: "Verdadero" o "Falso"
# Respuestas matching: pares con flecha → (Unicode U+2192, soportado por Arial)
# Respuestas cloze: informativas (el parser usa el texto embedded en la pregunta)
respuestas = [
    "1   multichoice   Rusia",
    "2   multichoice   América del Sur",
    "3   multichoice   Pacífico",
    "4   multichoice   Unión Soviética",
    "5   multichoice   7",
    "6   truefalse     Falso",
    "7   truefalse     Verdadero",
    "8   truefalse     Verdadero",
    "9   truefalse     Falso",
    "10  truefalse     Falso",
    "11  matching      1. París → Francia; 2. Tokio → Japón; 3. Brasilia → Brasil; 4. El Cairo → Egipto",
    "12  matching      1. Isaac Newton → Ley de la gravitación universal; 2. Marie Curie → Descubrimiento de la radioactividad; 3. Albert Einstein → Teoría de la relatividad; 4. Charles Darwin → Teoría de la evolución",
    "13  cloze         Antártida",
    "14  cloze         luz solar; oxígeno",
    "15  cloze         Monte Everest; 8849",
]

for r in respuestas:
    story.append(Paragraph(r, rline))

# ── Build ─────────────────────────────────────────────────────────────────────
doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
print(f"PDF generado: {OUTPUT}")
