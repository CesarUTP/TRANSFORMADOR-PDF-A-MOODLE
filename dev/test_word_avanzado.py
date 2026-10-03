"""
test_word_avanzado.py — Word (.docx): numeración que viene del ESTILO del
párrafo, contadores por lista (abstractNum), reinicios, y tablas con celdas
combinadas (gridSpan / vMerge) que se leen como la rejilla que se ve en Word.

    backend/venv/bin/python dev/test_word_avanzado.py

Los .docx se arman a mano en memoria (OOXML). No llama a Gemini, no usa la
red ni toca el historial ni la clave guardada.
"""

import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import extractor_docx  # noqa: E402
import mark_resolver  # noqa: E402

fallas = 0


def ok(cond, msg):
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


_NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f'xmlns:w="{_NS_W}"'


def word(cuerpo, numeracion=None, estilos=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", f"<w:document {_W}><w:body>{cuerpo}</w:body></w:document>")
        if numeracion:
            z.writestr("word/numbering.xml", f"<w:numbering {_W}>{numeracion}</w:numbering>")
        if estilos:
            z.writestr("word/styles.xml", f"<w:styles {_W}>{estilos}</w:styles>")
    return buf.getvalue()


def p(texto, estilo=None, num=None):
    """Párrafo; `num` = (numId, ilvl) propios (None en uno de los dos: se omite)."""
    ppr = ""
    if estilo:
        ppr += f'<w:pStyle w:val="{estilo}"/>'
    if num:
        nid, lvl = num
        ppr += "<w:numPr>" + (f'<w:ilvl w:val="{lvl}"/>' if lvl is not None else "") + \
               (f'<w:numId w:val="{nid}"/>' if nid is not None else "") + "</w:numPr>"
    return f'<w:p>{"<w:pPr>" + ppr + "</w:pPr>" if ppr else ""}<w:r><w:t xml:space="preserve">{texto}</w:t></w:r></w:p>'


def lvl(i, fmt, texto, inicio=1, extra=""):
    return (f'<w:lvl w:ilvl="{i}"><w:start w:val="{inicio}"/><w:numFmt w:val="{fmt}"/>{extra}'
            f'<w:lvlText w:val="{texto}"/></w:lvl>')


def lineas(raw):
    return extractor_docx.leer_docx(raw).texto_plano.split("\n")


# ── 1. Numeración declarada por el estilo (con herencia basedOn) ───────────
print("Numeración por estilo")
ABS_0 = f'<w:abstractNum w:abstractNumId="0">{lvl(0, "decimal", "%1.")}{lvl(1, "lowerLetter", "%2)")}</w:abstractNum>'
NUM_1 = '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
est = (
    '<w:style w:type="paragraph" w:styleId="ListaNum"><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr></w:style>'
    # hereda el numId de ListaNum y pone su propio nivel
    '<w:style w:type="paragraph" w:styleId="ListaNum2"><w:basedOn w:val="ListaNum"/><w:pPr><w:numPr><w:ilvl w:val="1"/></w:numPr></w:pPr></w:style>'
    # dos niveles de herencia, sin declarar nada propio
    '<w:style w:type="paragraph" w:styleId="Opcion"><w:basedOn w:val="ListaNum2"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Normalito"/>'
)
cuerpo = "".join([
    p("Pregunta uno", "ListaNum"), p("opción x", "ListaNum2"), p("opción y", "Opcion"),
    p("Pregunta dos", "ListaNum"), p("opción z", "Opcion"),
    p("Texto suelto", "Normalito"), p("Sin estilo"),
])
r = lineas(word(cuerpo, ABS_0 + NUM_1, est))
ok(r == ["1. Pregunta uno", "a) opción x", "b) opción y", "2. Pregunta dos", "a) opción z", "Texto suelto", "Sin estilo"],
   "estilo con numId, nivel propio y herencia de dos niveles (reinicia el nivel b tras la pregunta 2)")

# Un numId propio (incluido el 0, «sin lista») manda sobre el del estilo.
r = lineas(word(p("con estilo", "ListaNum") + p("sin lista", "ListaNum", (0, 0)) + p("con estilo otra vez", "ListaNum"),
                ABS_0 + NUM_1, est))
ok(r == ["1. con estilo", "sin lista", "2. con estilo otra vez"], "numId 0 en el párrafo quita la numeración del estilo")

# Solo el nivel propio; el numId viene del estilo.
r = lineas(word(p("uno", "ListaNum") + p("sub", "ListaNum", (None, 1)), ABS_0 + NUM_1, est))
ok(r == ["1. uno", "a) sub"], "ilvl propio con el numId del estilo")

# Estilo sin ilvl: el nivel lo da el w:pStyle de la lista (estilos ligados).
ABS_V = (f'<w:abstractNum w:abstractNumId="3">{lvl(0, "upperRoman", "%1.", extra="<w:pStyle w:val=\"Titulo1\"/>")}'
         f'{lvl(1, "upperLetter", "%2.", extra="<w:pStyle w:val=\"Titulo2\"/>")}</w:abstractNum>'
         '<w:num w:numId="7"><w:abstractNumId w:val="3"/></w:num>')
est_v = ('<w:style w:type="paragraph" w:styleId="Titulo1"><w:pPr><w:numPr><w:numId w:val="7"/></w:numPr></w:pPr></w:style>'
         '<w:style w:type="paragraph" w:styleId="Titulo2"><w:pPr><w:numPr><w:numId w:val="7"/></w:numPr></w:pPr></w:style>')
r = lineas(word(p("Parte", "Titulo1") + p("Sección", "Titulo2") + p("Sección bis", "Titulo2") + p("Otra parte", "Titulo1"),
                 ABS_V, est_v))
ok(r == ["I. Parte", "A. Sección", "B. Sección bis", "II. Otra parte"], "nivel ligado al estilo por w:lvl/w:pStyle")

# Ciclo basedOn y estilo inexistente: no se cuelga ni inventa números.
est_c = ('<w:style w:type="paragraph" w:styleId="A"><w:basedOn w:val="B"/></w:style>'
         '<w:style w:type="paragraph" w:styleId="B"><w:basedOn w:val="A"/></w:style>')
r = lineas(word(p("x", "A") + p("y", "NoExiste"), ABS_0 + NUM_1, est_c))
ok(r == ["x", "y"], "ciclo en basedOn y estilo inexistente: sin numeración")

# El estilo ligado a una lista con viñetas: sin número, como hoy.
ABS_B = ('<w:abstractNum w:abstractNumId="5"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/></w:lvl></w:abstractNum>'
         '<w:num w:numId="9"><w:abstractNumId w:val="5"/></w:num>')
est_b = '<w:style w:type="paragraph" w:styleId="Vineta"><w:pPr><w:numPr><w:numId w:val="9"/></w:numPr></w:pPr></w:style>'
r = lineas(word(p("punto uno", "Vineta") + p("punto dos", "Vineta") + p("punto tres", None, (9, 0)), ABS_B, est_b))
ok(r == ["punto uno", "punto dos", "punto tres"], "viñetas (por estilo y directas): sin prefijo")

# Lista de estilo (w:numStyleLink): el abstractNum no trae niveles, los toma de la lista del estilo.
ABS_L = (f'<w:abstractNum w:abstractNumId="10">{lvl(0, "lowerRoman", "(%1)")}<w:styleLink w:val="MiLista"/></w:abstractNum>'
         '<w:abstractNum w:abstractNumId="11"><w:numStyleLink w:val="MiLista"/></w:abstractNum>'
         '<w:num w:numId="20"><w:abstractNumId w:val="10"/></w:num><w:num w:numId="21"><w:abstractNumId w:val="11"/></w:num>')
est_l = '<w:style w:type="numbering" w:styleId="MiLista"><w:pPr><w:numPr><w:numId w:val="20"/></w:numPr></w:pPr></w:style>'
r = lineas(word(p("a", None, (21, 0)) + p("b", None, (21, 0)), ABS_L, est_l))
ok(r == ["(i) a", "(ii) b"], "abstractNum con numStyleLink usa los niveles de la lista del estilo")

# ── 2. Contadores por lista: continuar o reiniciar como Word ───────────────
print("Listas que comparten abstractNum")
NUMS = (ABS_0 + '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
        '<w:num w:numId="2"><w:abstractNumId w:val="0"/></w:num>'
        '<w:num w:numId="3"><w:abstractNumId w:val="0"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride></w:num>'
        '<w:num w:numId="4"><w:abstractNumId w:val="0"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="5"/></w:lvlOverride></w:num>')
cuerpo = "".join([
    p("a", None, (1, 0)), p("b", None, (1, 0)),
    p("Otra lista, mismo abstractNum", None, (2, 0)),   # continúa: 3
    p("Reinicia en 1", None, (3, 0)), p("sigue", None, (3, 0)),  # 1, 2
    p("Reinicia en 5", None, (4, 0)), p("sigue", None, (4, 0)),   # 5, 6
])
r = lineas(word(cuerpo, NUMS))
ok(r == ["1. a", "2. b", "3. Otra lista, mismo abstractNum", "1. Reinicia en 1", "2. sigue", "5. Reinicia en 5", "6. sigue"],
   "otro numId con el mismo abstractNum continúa; startOverride reinicia (en 1 o en el valor dado)")

# Niveles a), b), c) dentro de 1., 2.: el nivel inferior reinicia con cada número.
cuerpo = "".join([
    p("P1", None, (1, 0)), p("o1", None, (1, 1)), p("o2", None, (1, 1)), p("o3", None, (1, 1)),
    p("P2", None, (1, 0)), p("o4", None, (1, 1)), p("o5", None, (1, 1)), p("o6", None, (1, 1)),
])
r = lineas(word(cuerpo, ABS_0 + NUM_1))
ok(r == ["1. P1", "a) o1", "b) o2", "c) o3", "2. P2", "a) o4", "b) o5", "c) o6"], "a), b), c) dentro de 1., 2.")

# Un reinicio que cruza listas: el segundo numId (mismo abstractNum) también reinicia sus opciones.
cuerpo = "".join([p("P1", None, (1, 0)), p("o1", None, (1, 1)), p("P2", None, (2, 0)), p("o2", None, (2, 1))])
r = lineas(word(cuerpo, NUMS))
ok(r == ["1. P1", "a) o1", "2. P2", "a) o2"], "un nivel superior reinicia los inferiores aunque cambie el numId")

# w:lvlRestart="0": el nivel inferior nunca reinicia.
ABS_R = (f'<w:abstractNum w:abstractNumId="0">{lvl(0, "decimal", "%1.")}{lvl(1, "lowerLetter", "%2)", extra="<w:lvlRestart w:val=\"0\"/>")}</w:abstractNum>'
         + NUM_1)
cuerpo = "".join([p("P1", None, (1, 0)), p("o1", None, (1, 1)), p("P2", None, (1, 0)), p("o2", None, (1, 1))])
ok(lineas(word(cuerpo, ABS_R)) == ["1. P1", "a) o1", "2. P2", "b) o2"], "lvlRestart=0: las letras continúan")

# Formatos claros: decimal, lowerLetter, upperLetter, lowerRoman, upperRoman, bullet; otros, como hoy.
ABS_F = ('<w:abstractNum w:abstractNumId="0">'
         + lvl(0, "decimal", "%1.") + lvl(1, "lowerLetter", "%2)") + lvl(2, "upperLetter", "%3.")
         + lvl(3, "lowerRoman", "%4)") + lvl(4, "upperRoman", "%5.") + lvl(5, "bullet", "o") + lvl(6, "ordinal", "%7")
         + "</w:abstractNum>" + NUM_1)
cuerpo = "".join(p(t, None, (1, i)) for i, t in enumerate(["n", "l", "u", "r", "R", "b", "o"]))
ok(lineas(word(cuerpo, ABS_F)) == ["1. n", "a) l", "A. u", "i) r", "I. R", "b", "1 o"],
   "decimal, letras, romanos y viñeta; un formato raro (ordinal) queda como hoy")

# Texto de nivel que cita al superior: «1.1», «1.2».
ABS_M = f'<w:abstractNum w:abstractNumId="0">{lvl(0, "decimal", "%1.")}{lvl(1, "decimal", "%1.%2")}</w:abstractNum>' + NUM_1
cuerpo = p("T", None, (1, 0)) + p("a", None, (1, 1)) + p("b", None, (1, 1)) + p("T2", None, (1, 0)) + p("c", None, (1, 1))
ok(lineas(word(cuerpo, ABS_M)) == ["1. T", "1.1 a", "1.2 b", "2. T2", "2.1 c"], "plantilla con varios niveles (1.1, 1.2)")

# ── 3. Un documento sin nada de eso: sale igual que siempre ────────────────
print("Sin estilos con numeración ni celdas combinadas")
cuerpo_vieja = "".join([
    p("Parcial"), p("¿Capital de Francia?", None, (1, 0)), p("París", None, (1, 1)), p("Madrid", None, (1, 1)),
    p("¿Capital de Italia?", None, (1, 0)), p("Milán", None, (1, 1)), p("Roma", None, (1, 1)),
    p("viñeta", None, (9, 0)),
    '<w:tbl><w:tr><w:tc><w:p/></w:tc><w:tc>' + p("Mamífero") + '</w:tc><w:tc>' + p("Ave") + '</w:tc></w:tr>'
    '<w:tr><w:tc>' + p("Delfín") + '</w:tc><w:tc>' + p("X") + '</w:tc><w:tc><w:p/></w:tc></w:tr></w:tbl>',
    p("fin"),
])
d = extractor_docx.leer_docx(word(cuerpo_vieja, ABS_0 + NUM_1 + ABS_B,
                                  '<w:style w:type="paragraph" w:styleId="Otro"><w:pPr><w:jc w:val="left"/></w:pPr></w:style>'))
ok(d.texto_plano == "Parcial\n1. ¿Capital de Francia?\na) París\nb) Madrid\n2. ¿Capital de Italia?\na) Milán\nb) Roma\nviñeta\n"
                    " | Mamífero | Ave\nDelfín | X | \nfin",
   "texto plano idéntico al de siempre")
ok(d.texto_enriquecido.count("[Tabla]\n|  | Mamífero | Ave |\n| Delfín | X |  |\n[/Tabla]") == 1,
   "la tabla sin celdas combinadas se escribe igual")
ok(d.tablas == [[["", "Mamífero", "Ave"], ["Delfín", "X", ""]]], "tablas: misma estructura de siempre")
# Una celda con gridSpan="1" o vMerge de reinicio no cambia nada.
tb = ('<w:tbl><w:tr><w:tc><w:tcPr><w:gridSpan w:val="1"/></w:tcPr>' + p("A") + '</w:tc>'
      '<w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr>' + p("B") + '</w:tc></w:tr></w:tbl>')
ok(extractor_docx.leer_docx(word(tb)).tablas == [[["A", "B"]]], "gridSpan=1 y vMerge de reinicio: igual")

# ── 4. Tablas con celdas combinadas ────────────────────────────────────────


def tc(texto="", span=None, vmerge=None):
    props = ""
    if span:
        props += f'<w:gridSpan w:val="{span}"/>'
    if vmerge is not None:
        props += "<w:vMerge/>" if vmerge == "continue" else '<w:vMerge w:val="restart"/>'
    return f"<w:tc>{'<w:tcPr>' + props + '</w:tcPr>' if props else ''}{p(texto) if texto else '<w:p/>'}</w:tc>"


def tr(*celdas, antes=0):
    pr = f'<w:trPr><w:gridBefore w:val="{antes}"/></w:trPr>' if antes else ""
    return f"<w:tr>{pr}{''.join(celdas)}</w:tr>"


def tabla(*filas):
    return "<w:tbl>" + "".join(filas) + "</w:tbl>"


def emparejamiento(items, opciones, num=1):
    return {"num": num, "type": "matching", "data": {
        "col_a": {str(i): t for i, t in enumerate(items, start=1)},
        "col_b": {chr(64 + i): t for i, t in enumerate(opciones, start=1)}}}


def resolver(cuerpo, items, opciones):
    d = extractor_docx.leer_docx(word(cuerpo))
    q = emparejamiento(items, opciones)
    clave = {}
    n = mark_resolver.resolve_table_marks([q], clave, d.tablas)
    return d, n, clave.get(1, {}).get("answer")


print("Tablas: celdas combinadas")
OPC = ["Mamífero", "Ave", "Reptil"]
ITEMS = ["Delfín", "Águila"]

# Referencia sin combinar.
llano = tabla(tr(tc(), tc("Mamífero"), tc("Ave"), tc("Reptil")),
              tr(tc("Delfín"), tc("X"), tc(), tc()),
              tr(tc("Águila"), tc(), tc("X"), tc()))
d, n, resp = resolver(llano, ITEMS, OPC)
ok(resp == "1-A; 2-B" and n == 1, "sin celdas combinadas: se resuelve como siempre")

# gridSpan en una fila: las dos columnas del medio combinadas; la X de la tercera columna es «Reptil».
comb = tabla(tr(tc(), tc("Mamífero"), tc("Ave"), tc("Reptil")),
             tr(tc("Delfín"), tc("X"), tc(), tc()),
             tr(tc("Águila"), tc(span=2), tc("X")))
d, n, resp = resolver(comb, ITEMS, OPC)
ok(d.tablas[0][2] == ["Águila", "", "", "X"], "la celda combinada ocupa sus columnas: la X queda en la 4.ª columna")
ok(resp == "1-A; 2-C", "la marca cae en la columna que se ve (Reptil), no en la de al lado")
ok("| Águila |  |  | X |" in d.texto_enriquecido, "el texto para la IA también lleva la rejilla completa")

# Encabezado combinado: la celda «Clasificación» abarca dos columnas y una fila superior de título.
enc = tabla(tr(tc("Clasifica a los animales", span=4)),
            tr(tc(), tc("Mamífero"), tc("Ave"), tc("Reptil")),
            tr(tc("Delfín"), tc("X"), tc(), tc()),
            tr(tc("Águila"), tc(), tc("X"), tc()))
d, n, resp = resolver(enc, ITEMS, OPC)
ok(d.tablas[0][0] == ["Clasifica a los animales", "", "", ""], "fila de título combinada: cuatro columnas")
ok(resp == "1-A; 2-B", "con una fila de título combinada, el encabezado es la fila que nombra las columnas")

# Encabezado de dos filas: «Ítem» combinada en vertical (vMerge) y «Clasificación» en horizontal (gridSpan).
enc2 = tabla(tr(tc("Ítem", vmerge="restart"), tc("Clasificación", span=3)),
             tr(tc("OCULTO", vmerge="continue"), tc("Mamífero"), tc("Ave"), tc("Reptil")),
             tr(tc("Delfín"), tc("X"), tc(), tc()),
             tr(tc("Águila"), tc(), tc(), tc("X")))
d, n, resp = resolver(enc2, ITEMS, OPC)
ok(d.tablas[0][0] == ["Ítem", "Clasificación", "", ""] and d.tablas[0][1][0] == "",
   "vMerge: la celda que continúa queda vacía (su texto no se ve en Word)")
ok("OCULTO" not in d.texto_plano and "OCULTO" not in d.texto_enriquecido, "el texto oculto de una celda vMerge no se lee")
ok(resp == "1-A; 2-C", "encabezado de dos filas con vMerge y gridSpan: la X cae en su columna")

# gridBefore: una fila que empieza en la 2.ª columna.
antes = tabla(tr(tc(), tc("Mamífero"), tc("Ave")),
              tr(tc("X"), tc(), antes=1))
ok(extractor_docx.leer_docx(word(antes)).tablas == [[["", "Mamífero", "Ave"], ["", "X", ""]]],
   "gridBefore: las columnas que la fila se salta quedan vacías")

# Una X combinada hacia abajo (vMerge) no se reparte ni se adivina: la 2.ª fila queda sin marca.
vx = tabla(tr(tc(), tc("Mamífero"), tc("Ave"), tc("Reptil")),
           tr(tc("Delfín"), tc("X", vmerge="restart"), tc(), tc()),
           tr(tc("Águila"), tc(vmerge="continue"), tc("X"), tc()))
d, n, resp = resolver(vx, ITEMS, OPC)
ok(d.tablas[0][2][1] == "" and d.tablas[0][1][1] == "X", "una X combinada en vertical queda solo en su celda de origen")
ok(resp == "1-A; 2-B", "…y cada fila conserva su propia marca")
vx2 = tabla(tr(tc(), tc("Mamífero"), tc("Ave"), tc("Reptil")),
            tr(tc("Delfín"), tc("X", vmerge="restart"), tc(), tc()),
            tr(tc("Águila"), tc(vmerge="continue"), tc(), tc()))
d, n, resp = resolver(vx2, ITEMS, OPC)
ok(n == 0 and resp is None, "una fila sin marca propia (X combinada hacia abajo) no se resuelve: no se inventa la respuesta")

# Límites: una combinación absurda no crece sin tope.
d = extractor_docx.leer_docx(word(tabla(tr(tc("A", span=60000), tc("B", span=60000)))))
ok(len(d.tablas[0][0]) <= extractor_docx.MAX_COLUMNAS_TABLA + 2, "gridSpan enorme: la fila queda acotada")

# El encabezado de siempre sigue mandando si ya nombra las opciones (no se busca otro).
d, n, resp = resolver(tabla(tr(tc(), tc("Mamífero"), tc("Ave"), tc("Reptil")),
                            tr(tc("Delfín"), tc("X"), tc(), tc()),
                            tr(tc("Águila"), tc(), tc("X"), tc())), ITEMS, OPC)
ok(resp == "1-A; 2-B", "encabezado en la primera fila: sin cambios")

print()
print("TODO OK" if not fallas else f"{fallas} FALLA(S)")
sys.exit(1 if fallas else 0)
