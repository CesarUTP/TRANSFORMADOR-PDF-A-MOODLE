"""
test_casos_borde.py — Regresión de los casos borde que rompían el XML o la
lectura de marcas. No llama a Gemini: prueba adaptador → validador → XML y
el lector de marcas con datos armados a mano.

    backend/venv/bin/python dev/test_casos_borde.py

Cada caso viene de un fallo medido en dev/eval_results/RESULTADOS.md
(sección "Pruebas adversariales"): opción "|", "/" y "=" en Cloze,
apóstrofo en Cloze, una opción de código con "[" "]" balanceados,
todas las opciones marcadas, emparejamiento sin clave, verdadero/falso con
casilla marcada y subrayado dibujado como lo hace Word.
"""
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "dev"))
logging.disable(logging.CRITICAL)

from lxml import etree  # noqa: E402
from mark_resolver import resolve_answer_marks, resolve_tf_marks  # noqa: E402
from schema_adapter import adapt  # noqa: E402
from validator import partition_questions  # noqa: E402
from xml_builder import build_xml  # noqa: E402
from xml_fidelity import read_cloze  # noqa: E402

BASE = {"opciones": [], "items_izquierda": [], "items_derecha": [], "parejas": [], "huecos": [], "clave_texto": "",
        "respuesta_texto": "", "respuesta_marcada": True, "origen_tabla": False, "pagina": 1, "confianza": "alta"}
fallos = []


def caso(nombre):
    def deco(fn):
        try:
            fn()
            print(f"  ok   {nombre}")
        except AssertionError as e:
            fallos.append(nombre)
            print(f"  FALLA {nombre}: {e}")
        return fn
    return deco


def convertir(*qs):
    qs = [{**BASE, "orden": i, **q} for i, q in enumerate(qs, 1)]
    questions, key = adapt({"es_examen": True, "preguntas": qs})
    valid, skipped = partition_questions(questions, key)
    xml, _ = build_xml(valid, key)
    etree.fromstring(xml.encode())
    return valid, skipped, xml, key


def opts(*items):
    return [{"letra_original": "abcdefgh"[i], "texto": t, "correcta": ok} for i, (t, ok) in enumerate(items)]


def cloze_de(xml):
    return read_cloze(re.search(r"<questiontext.*?CDATA\[(.*?)\]\]>", xml, re.S).group(1).replace("&amp;", "&"))


@caso("clave numérica de posición resuelve cuando las opciones no tienen letra propia")
def _():
    from schema_adapter import adapt as _adapt
    sin_letra = [{"letra_original": "", "texto": t, "correcta": False} for t in ("Quito", "Lima", "Bogotá")]
    q = {**BASE, "orden": 1, "tipo": "multichoice", "enunciado": "¿Cuál es la capital de Perú?",
         "clave_texto": "2", "opciones": sin_letra}
    qs, key = _adapt({"es_examen": True, "preguntas": [q]})
    assert key[1]["answer"] == "Lima", key[1]["answer"]


@caso("varias respuestas correctas: marcar TODAS las opciones no da 100%")
def _():
    _, sk, xml, _k = convertir({"tipo": "multichoice", "enunciado": "¿Cuáles son primos?",
                               "opciones": opts(("2", True), ("4", False), ("7", True), ("9", False))})
    assert not sk, sk
    fr = dict((t, f) for f, t in re.findall(r'<answer fraction="(-?[\d.]+)">\s*<text><!\[CDATA\[(.*?)\]\]>', xml))
    assert fr["2"] == "50.0" and fr["7"] == "50.0", fr
    assert float(fr["4"]) < 0 and float(fr["9"]) < 0, fr
    assert abs(sum(float(v) for v in fr.values())) < 0.01, fr  # marcar TODAS da ~0%


@caso("una sola respuesta correcta: las demás siguen en 0% (no negativas)")
def _():
    _, sk, xml, _k = convertir({"tipo": "multichoice", "enunciado": "¿Capital de Perú?",
                               "opciones": opts(("Lima", True), ("Quito", False), ("Bogotá", False))})
    assert not sk, sk
    fr = sorted(re.findall(r'<answer fraction="(-?[\d.]+)">', xml), key=float)
    assert fr == ["0", "0", "100"], fr


@caso('opción "|" correcta se marca en el XML (no cae en la A)')
def _():
    _, sk, xml, _k = convertir({"tipo": "multichoice", "enunciado": "¿OR bit a bit?",
                               "opciones": opts(("&", False), ("|", True), ("^", False), ("~", False))})
    assert not sk
    fr = dict(re.findall(r'<answer fraction="([\d.]+)">\s*<text><!\[CDATA\[(.*?)\]\]>', xml)[i][::-1] for i in range(4))
    assert fr["|"] == "100" and fr["&amp;"] == "0", fr


@caso('opción "|" junto a otra correcta (varias respuestas)')
def _():
    _, _s, xml, key = convertir({"tipo": "multichoice", "enunciado": "¿Operadores bit a bit?",
                                "opciones": opts(("&", True), ("|", True), ("y", False))})
    assert key[1]["answer"] == "& | |", key[1]["answer"]
    assert 'fraction="50.0"' in xml and xml.count('fraction="50.0"') == 2


@caso("Cloze con / en las opciones conserva 3 opciones (km/h, TCP/IP)")
def _():
    h = {"marcador": "A", "opciones": opts(("km/h", True), ("m/s²", False), ("kg/m", False))}
    _, sk, xml, _k = convertir({"tipo": "cloze", "enunciado": "Se mide en [A].", "huecos": [h]})
    assert not sk
    (tipo, o), = cloze_de(xml)
    assert [t for t, _ in o] == ["km/h", "m/s²", "kg/m"] and o[0][1], o


@caso("Cloze con opciones que empiezan por = no marca dos correctas")
def _():
    h = {"marcador": "A", "opciones": opts(("=", True), ("==", False), (":=", False))}
    _, sk, xml, _k = convertir({"tipo": "cloze", "enunciado": "Asigna con [A].", "huecos": [h]})
    (tipo, o), = cloze_de(xml)
    assert [(t, c) for t, c in o] == [("=", True), ("==", False), (":=", False)], o


@caso("Cloze con una opción de código \"arr[0]\" no corta el hueco a mitad de camino")
def _():
    h = {"marcador": "A", "opciones": opts(("[10, 20, 30]", False), ("10", True), ("arr[1]", False))}
    _, sk, xml, _k = convertir({"tipo": "cloze", "enunciado": "¿Qué imprime arr[0] si arr = [A]?", "huecos": [h]})
    assert not sk, sk
    (tipo, o), = cloze_de(xml)
    assert [t for t, _ in o] == ["[10, 20, 30]", "10", "arr[1]"], o
    assert dict(o)["10"] is True, o


@caso("Cloze con dos huecos, cada uno con su propio código, no se mezclan")
def _():
    h1 = {"marcador": "A", "opciones": opts(("lista[0]", True), ("lista[-1]", False))}
    h2 = {"marcador": "B", "opciones": opts(("matriz[i][j]", True), ("matriz[j][i]", False))}
    _, sk, xml, _k = convertir({"tipo": "cloze", "enunciado": "Primero [A], luego [B].", "huecos": [h1, h2]})
    assert not sk, sk
    slots = cloze_de(xml)
    assert len(slots) == 2, slots
    assert [t for t, _ in slots[0][1]] == ["lista[0]", "lista[-1]"], slots
    assert [t for t, _ in slots[1][1]] == ["matriz[i][j]", "matriz[j][i]"], slots


@caso("Cloze con apóstrofo no crea un separador # de retroalimentación")
def _():
    h = {"marcador": "A", "opciones": opts(("L'Oréal", True), ("Dior", False))}
    _, sk, xml, _k = convertir({"tipo": "cloze", "enunciado": "Marca [A].", "huecos": [h]})
    (tipo, o), = cloze_de(xml)
    assert [t for t, _ in o] == ["L'Oreal", "Dior"], o      # sin tildes por diseño (strip_accents)


@caso("todas las opciones marcadas → sin respuesta (queda omitida)")
def _():
    v, sk, _x, _k = convertir({"tipo": "multichoice", "enunciado": "¿Cuál?",
                              "opciones": opts(("a", True), ("b", True), ("c", True), ("d", True))})
    assert not v and sk and "respuesta correcta" in sk[0]["reasons"][0], sk


@caso("clave explícita con todas las opciones sí se respeta")
def _():
    v, sk, _x, key = convertir({"tipo": "multichoice", "enunciado": "¿Cuáles?", "clave_texto": "a, b",
                               "opciones": opts(("uno", False), ("dos", False))})
    assert v and key[1]["answer"] == "uno | dos", key


@caso("emparejamiento sin clave (respuesta_marcada=false) no conserva las parejas del modelo")
def _():
    v, sk, _x, key = convertir({"tipo": "matching", "enunciado": "Relaciona.", "respuesta_marcada": False,
                               "items_izquierda": ["Oro", "Plata"], "items_derecha": ["Au", "Ag"],
                               "parejas": [{"izquierda": 1, "derecha": 1}, {"izquierda": 2, "derecha": 2}]})
    assert not v and sk, "debía quedar omitido"


@caso("emparejamiento con clave compacta del documento sí se conserva")
def _():
    v, sk, _x, key = convertir({"tipo": "matching", "enunciado": "Relaciona.", "clave_texto": "1-b, 2-a",
                               "items_izquierda": ["Oro", "Plata"], "items_derecha": ["Ag", "Au"]})
    assert v and key[1]["pairs"] == {"1": "b", "2": "a"}, key


def _tf(pages, stems, respuestas):
    qs = [{"num": i, "type": "truefalse", "data": {"stem": s}} for i, s in enumerate(stems, 1)]
    key = {i: {"type": "truefalse", "answer": r} for i, r in enumerate(respuestas, 1)}
    resolve_tf_marks(qs, key, pages)
    return [key[i]["answer"] for i in range(1, len(stems) + 1)]


@caso("V/F con casilla ( X ) manda sobre lo que dijo el modelo")
def _():
    page = ("1. El español es el idioma oficial de Brasil.   ( X ) Verdadero   (   ) Falso\n"
            "2. El sol es una estrella.   (   ) Verdadero   ( X ) Falso")
    got = _tf([page], ["El español es el idioma oficial de Brasil.", "El sol es una estrella."], ["Falso", "Verdadero"])
    assert got == ["Verdadero", "Falso"], got


@caso("V/F con la palabra en color")
def _():
    page = "1. La luz es más lenta que el sonido.   ( ) ⟦rojo⟧Falso⟦/rojo⟧   ( ) Verdadero"
    assert _tf([page], ["La luz es más lenta que el sonido."], ["Verdadero"]) == ["Falso"]


@caso("V/F sin marca o con estilo repetido en todas no toca la respuesta")
def _():
    page = "1. Uno de prueba largo.   (   ) Verdadero   (   ) Falso"
    assert _tf([page], ["Uno de prueba largo."], ["Verdadero"]) == ["Verdadero"]
    pages = ["\n".join(f"{i}. Afirmación número {i} bastante larga.   ⟦negrita⟧Verdadero⟦/negrita⟧   Falso" for i in range(1, 5))]
    got = _tf(pages, [f"Afirmación número {i} bastante larga." for i in range(1, 5)], ["Falso"] * 4)
    assert got == ["Falso"] * 4, got


# ── Subrayado dibujado como en Word (PARCIAL N.pdf) ─────────────────────────

def _pdf_subrayado(dibujar) -> bytes:
    import io
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont("Helvetica", 12)
    dibujar(c, letter[1])
    c.save()
    return buf.getvalue()


@caso("bbox de página rotada (bottom < top) no desactiva la detección de subrayado")
def _():
    import extractor
    # Palabra con bbox degenerado (bottom < top), como puede salir en una
    # página rotada 90/270°. El subrayado real está justo debajo del borde
    # inferior "real" (aquí, el menor de los dos valores).
    word = {"x0": 100.0, "x1": 140.0, "top": 210.0, "bottom": 200.0, "fontname": "Helvetica"}
    underline = (100.0, 140.0, 201.5)  # y muy cerca de "bottom" (200)
    assert extractor._word_style(word, [], [underline]) == "subrayado"


@caso("subrayado sobre la línea base (Word) llega al modelo como ⟦subrayado⟧")
def _():
    import extractor

    def dibujar(c, h):
        for i, (txt, sub) in enumerate([("A. PANAMA OESTE", True), ("B. PANAMA", True), ("C. CHINA", False)]):
            y = h - 100 - i * 20
            c.drawString(100, y, txt)
            if sub:
                x0 = 100 + c.stringWidth("A. ", "Helvetica", 12)
                # Word: rectángulo de 0,25 pt sobre la línea base (~3 pt por
                # encima del borde inferior del cuadro de la palabra)
                c.rect(x0, y - 0.1, c.stringWidth(txt[3:], "Helvetica", 12), 0.25, stroke=0, fill=1)
    texto = extractor.extract_pages_text_enriched(_pdf_subrayado(dibujar))[0]
    assert "⟦subrayado⟧PANAMA OESTE⟦/subrayado⟧" in texto and "⟦subrayado⟧PANAMA⟦/subrayado⟧" in texto, texto
    assert "CHINA" in texto and "⟦subrayado⟧CHINA" not in texto, texto


@caso("un tachado o una regla que cruza letras grandes NO cuenta como subrayado")
def _():
    import extractor

    def dibujar(c, h):
        y = h - 100
        c.drawString(100, y, "TACHADO")
        c.rect(100, y + 4, c.stringWidth("TACHADO", "Helvetica", 12), 0.25, stroke=0, fill=1)   # mitad de la letra
        c.setFont("Helvetica-Bold", 70)
        c.drawString(100, h - 300, "RO")
        c.rect(72, h - 300 + 28, 400, 0.25, stroke=0, fill=1)                                  # regla de tabla a media altura
    texto = extractor.extract_pages_text_enriched(_pdf_subrayado(dibujar))[0]
    assert "subrayado" not in texto, texto


# ── Marcas mezcladas: cada pregunta usa la suya ─────────────────────────────

def _mc(n, opciones):
    return {"num": n, "type": "multichoice", "data": {"stem": f"Enunciado número {n} de la prueba de ejemplo", "options": dict(zip("ABCD", opciones))}}


def _resolver(bloques, modelo):
    """bloques: [(marca|None por opción)] por pregunta; modelo: respuesta (equivocada) que dio la IA."""
    opciones = [["uno", "dos", "tres", "cuatro"] for _ in bloques]
    qs = [_mc(i, o) for i, o in enumerate(opciones, 1)]
    key = {i: {"type": "multichoice", "answer": modelo} for i in range(1, len(qs) + 1)}
    lineas = []
    for i, marcas in enumerate(bloques, 1):
        lineas.append(f"{i}. Enunciado número {i} de la prueba de ejemplo")
        for L, txt, m in zip("ABCD", opciones[i - 1], marcas):
            lineas.append(f"⟦{m}⟧{L}. {txt}⟦/{m}⟧" if m else f"{L}. {txt}")
    res = resolver_ = resolve_answer_marks(qs, key, ["\n".join(lineas)])
    return res, key


@caso("una opción prefijo de otra ya no le \"roba\" la marca a su vecina")
def _():
    # "Estructura de datos abstracta" es un prefijo literal de la opción
    # "... compleja". Sin el chequeo de colisión, buscar la línea de la
    # opción CORTA encontraba la línea de la opción LARGA (coincidencia
    # difusa de _option_line) — si la larga estaba marcada, la corta
    # "heredaba" esa marca aunque su propia línea no tuviera ninguna.
    from mark_resolver import _anchors, _candidates, _lines
    qs = [{"num": 1, "type": "multichoice", "data": {"stem": "¿Qué es una estructura lineal?",
          "options": {"A": "Estructura de datos abstracta", "B": "Estructura de datos abstracta compleja",
                       "C": "Cola", "D": "Grafo"}}}]
    page = ("1. ¿Qué es una estructura lineal?\n"
            "⟦rojo⟧B. Estructura de datos abstracta compleja⟦/rojo⟧\n"
            "A. Estructura de datos abstracta\n"
            "C. Cola\nD. Grafo")
    lines = _lines([page])
    anchors = _anchors(qs, lines)
    located, candidates = _candidates(qs, lines, anchors, "rojo")
    assert located == 0 and candidates == [], (located, candidates)  # colisión: no se ubica con certeza


@caso("marcas mezcladas (resaltado, subrayado, negrita): el código las resuelve")
def _():
    res, key = _resolver([["resaltado", None, None, None], [None, "subrayado", "subrayado", None], [None, None, None, "negrita"]], "cuatro")
    assert res["mark"] == "mixta" and res["applied"] == 3, res
    assert [key[i]["answer"] for i in (1, 2, 3)] == ["uno", "dos | tres", "cuatro"], key


@caso("una sola marca en todo el examen se comporta como antes (no 'mixta')")
def _():
    res, key = _resolver([["rojo", None, None, None], [None, "rojo", None, None], [None, None, "rojo", None]], "cuatro")
    assert res["mark"] == "rojo" and res["applied"] == 3, res


@caso("dos negritas sueltas en un examen largo no reemplazan la clave")
def _():
    sin = [[None] * 4] * 8
    res, key = _resolver([["negrita", None, None, None], [None, "subrayado", None, None]] + sin, "cuatro")
    assert res["applied"] == 0 and key[1]["answer"] == "cuatro", (res, key[1])


@caso("dos marcas distintas en la MISMA pregunta: el código no decide esa (y sí las demás)")
def _():
    ciclo = ["resaltado", "subrayado", "negrita", "rojo"]
    bloques = [["resaltado", "subrayado", None, None]]                                   # ambigua
    bloques += [[None] * (i % 4) + [ciclo[i % 4]] + [None] * (3 - i % 4) for i in range(8)]
    bloques += [[None] * 4] * 5                                                          # sin marca: la dominante sola no llega al 30 %
    res, key = _resolver(bloques, "cuatro")
    assert res["mark"] == "mixta" and res["applied"] == 8, res
    assert key[1]["answer"] == "cuatro", key[1]                                            # no se decidió
    assert key[2]["answer"] == "uno" and key[3]["answer"] == "dos", key


@caso("mixtas con TODAS las opciones marcadas en una pregunta: esa no se decide")
def _():
    res, key = _resolver([["negrita"] * 4, ["subrayado", None, None, None], [None, "resaltado", None, None]], "cuatro")
    assert key[1]["answer"] == "cuatro" and key[2]["answer"] == "uno" and key[3]["answer"] == "dos", key


print()
print("TODO OK" if not fallos else f"{len(fallos)} FALLAN: {fallos}")
sys.exit(1 if fallos else 0)
