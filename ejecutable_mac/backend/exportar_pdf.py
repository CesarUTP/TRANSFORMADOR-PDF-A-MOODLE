"""
exportar_pdf.py — el examen revisado como PDF imprimible, con su clave (2.1).

Es un documento de APOYO: el docente lo guarda o lo imprime junto al Moodle
XML, que sigue siendo lo que se importa a Moodle. El PDF sale de las MISMAS
preguntas y la MISMA clave que el XML y usa los mismos resolutores del modelo
(modelo.py) para decidir qué es correcto, así que no puede discrepar de él. No
inventa nada: lo que no se pudo escribir en papel (un carácter que la fuente
no tiene, una fórmula que no se convierte a texto, una imagen ilegible) se
deja visible o se avisa.

    resultado = generar_pdf(preguntas, answer_key, total_points, datos)
    resultado.pdf, resultado.paginas, resultado.avisos

Desde la 2.8 este módulo SOLO DIBUJA: qué lleva el examen (orden, letras, clave,
indicaciones, medidas) lo decide `plan_impreso.py`, el mismo plan que usa el Word
(`exportar_docx.py`), así que los dos documentos coinciden por construcción.

Maquetación (ReportLab, Platypus): papel Carta o A4, márgenes de 2 cm, cada
pregunta entera en su página mientras quepa, casillas dibujadas como figuras
(círculo = una respuesta, cuadrado = varias; así se imprimen igual en cualquier
fuente y en blanco y negro), «Página X de Y». La CLAVE va en páginas aparte al
final (o sola): cada respuesta con su letra Y su texto, porque Moodle mezcla
las opciones y la letra sola no basta.
"""

import io
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate, Flowable, Frame, Image as RLImage, Indenter, KeepTogether, NextPageTemplate,
    PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.platypus.doctemplate import LayoutError

from plan_impreso import (  # noqa: F401  (varios se usan desde fuera: rutas y pruebas)
    CONTENIDOS, FUENTES, GRIS, GRIS_CLARO, LIMITE_CAMPO, LIMITE_INSTRUCCIONES, LIMITE_LOGO, LIMITE_VERSION,
    MARGENES, PAPELES, PASO_BURBUJAS, PASO_HUECOS, RENGLONES_MAX, RENGLONES_MIN, ROTULOS, TAM_MAX, TAM_MIN,
    Burbujas, CuadroEstudiante, DatosExamen, Espacio, Estilo, FilaDocente, Grupo, Huecos, Imagen, LogosCabecera,
    Opcion, Parrafo, Plan, PuntosNoEnteros, RejillaBurbujas, Renglones, Sangrado, Seccion, TablaHuecos,
    TablaPareo, construir_plan, revisar_puntos_enteros,
)

_FAMILIA = "DejaVu"
_GRIS = colors.HexColor(GRIS)
_GRIS_CLARO = colors.HexColor(GRIS_CLARO)


@dataclass
class ResultadoPdf:
    pdf: bytes
    paginas: int
    preguntas: int
    avisos: List[str] = field(default_factory=list)


# ── Figuras ─────────────────────────────────────────────────────────────────

class _Casilla(Flowable):
    """Círculo (una respuesta) o cuadrado (varias), dibujado: no depende de ningún glifo."""

    def __init__(self, redonda: bool, lado: float = 8.5):
        super().__init__()
        self.redonda, self.lado = redonda, lado

    def wrap(self, aw, ah):
        return self.lado, self.lado

    def draw(self):
        c = self.canv
        c.setLineWidth(0.8)
        c.setStrokeColor(colors.black)
        if self.redonda:
            c.circle(self.lado / 2, self.lado / 2, self.lado / 2 - 0.4)
        else:
            c.rect(0.4, 0.4, self.lado - 0.8, self.lado - 0.8)


class _Renglones(Flowable):
    """Espacio rayado para una respuesta de desarrollo."""

    def __init__(self, n: int, paso: float = 22):
        super().__init__()
        self.n, self.paso = n, paso

    def wrap(self, aw, ah):
        self.ancho = aw
        return aw, self.n * self.paso

    def draw(self):
        c = self.canv
        c.setStrokeColor(_GRIS_CLARO)
        c.setLineWidth(0.6)
        for i in range(self.n):
            y = self.paso * (i + 1) - 4
            c.line(0, y, self.ancho, y)


class _Lienzo(canvas.Canvas):
    """Pone «Página X de Y» al final, cuando ya se sabe cuántas páginas hay. Cada sección (el examen o el folleto,
    la hoja de respuestas, la clave) numera las suyas: se imprimen y se reparten por separado."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._estados: List[dict] = []

    def showPage(self):
        self._estados.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        por_seccion: Dict[Any, int] = {}
        for estado in self._estados:
            s = estado.get("_seccion")
            por_seccion[s] = por_seccion.get(s, 0) + 1
        vistas: Dict[Any, int] = {}
        for estado in self._estados:
            self.__dict__.update(estado)
            s = estado.get("_seccion")
            vistas[s] = vistas.get(s, 0) + 1
            self.setFont(getattr(self, "_fuente_pie", _FAMILIA), 8)
            self.setFillColor(_GRIS)
            self.drawRightString(self._pagesize[0] - getattr(self, "_margen_der", 2 * cm), getattr(self, "_pie_y", 1.1 * cm),
                                 f"Página {vistas[s]} de {por_seccion[s]}")
            super().showPage()
        super().save()


class _Burbujas(Flowable):
    """Fila de una hoja de respuestas de opción: el número y una burbuja con su letra por opción (círculo = una
    respuesta, cuadro = varias). Con `marcadas` es la clave: esas burbujas van rellenas."""

    PASO = PASO_BURBUJAS

    def __init__(self, num: int, letras: List[str], redonda: bool, marcadas=(), fam: str = _FAMILIA):
        super().__init__()
        self.num, self.letras, self.redonda, self.marcadas, self.fam = num, list(letras), redonda, set(marcadas), fam

    def wrap(self, aw, ah):
        self.aw = aw
        return aw, 19

    def draw(self):
        c = self.canv
        c.setFont(self.fam + "-B", 9)
        c.setFillColor(colors.black)
        etiqueta = f"{self.num}."
        c.drawString(0, 5, etiqueta)
        x = max(24, pdfmetrics.stringWidth(etiqueta, self.fam + "-B", 9) + 6)
        r = 6.6
        for letra in self.letras:
            lleno = letra in self.marcadas
            c.setLineWidth(0.8)
            c.setStrokeColor(colors.black)
            c.setFillColor(colors.black if lleno else colors.white)
            if self.redonda:
                c.circle(x + r, 9.5, r, stroke=1, fill=1)
            else:
                c.rect(x, 9.5 - r, 2 * r, 2 * r, stroke=1, fill=1)
            c.setFillColor(colors.white if lleno else colors.black)
            c.setFont(self.fam, 7)
            c.drawCentredString(x + r, 7.2, letra)
            x += self.PASO


class _Huecos(Flowable):
    """Respuestas que se escriben, en una hoja de respuestas: «6.  1. ______  2. ______». Con valores es la clave
    (la respuesta escrita sobre la raya). Las líneas ya vienen repartidas por el plan."""

    PASO = PASO_HUECOS

    def __init__(self, h: Huecos, fam: str = _FAMILIA):
        super().__init__()
        self.num, self.filas, self.tam, self.fam = h.num, h.lineas, h.tam, fam

    def wrap(self, aw, ah):
        return aw, len(self.filas) * self.PASO + 2

    def draw(self):
        c = self.canv
        fb = self.fam + "-B"
        alto = len(self.filas) * self.PASO + 2
        for r, fila in enumerate(self.filas):
            y = alto - (r + 1) * self.PASO + 8
            c.setFillColor(colors.black)
            if r == 0:
                c.setFont(fb, self.tam)
                c.drawString(0, y, f"{self.num}.")
            for x, etiqueta, valor, w_et, largo, tam_valor in fila:
                if etiqueta:
                    c.setFont(fb, self.tam)
                    c.drawString(x, y, etiqueta)
                c.setStrokeColor(colors.black)
                c.setLineWidth(0.7)
                c.line(x + w_et, y - 2, x + w_et + largo, y - 2)
                if valor:
                    c.setFont(fb, tam_valor)
                    c.drawCentredString(x + w_et + largo / 2, y, valor)


# ── El plan, dibujado ───────────────────────────────────────────────────────

class _Dibujante:
    def __init__(self, plan: Plan, simple: bool = False):
        self.plan, self.simple = plan, simple
        self.geo = plan.geo
        self.nombres = {"e": plan.fuente_e, "p": plan.fuente_p}
        self._estilos: Dict[Estilo, ParagraphStyle] = {}

    # ---- estilos y párrafos ----
    def _estilo(self, e: Estilo) -> ParagraphStyle:
        if e not in self._estilos:
            fam = self.nombres[e.grupo]
            sufijo = "-BI" if e.negrita and e.cursiva else "-B" if e.negrita else "-I" if e.cursiva else ""
            self._estilos[e] = ParagraphStyle(
                f"e{len(self._estilos)}", fontName=fam + sufijo, fontSize=e.tam, leading=e.leading,
                textColor=colors.HexColor(e.color) if e.color else colors.black, alignment=e.alinear,
                leftIndent=e.sangria, bulletIndent=e.vineta_sangria, bulletFontName=fam + ("-B" if e.vineta_negrita else ""),
                bulletFontSize=e.vineta_tam, spaceBefore=e.antes, spaceAfter=e.despues)
        return self._estilos[e]

    def _p(self, p: Parrafo) -> Paragraph:
        return Paragraph(p.marcado, self._estilo(p.estilo), bulletText=p.vineta)

    def _celdas(self, bloques: list) -> list:
        return [self._p(b) if isinstance(b, Parrafo) else b for b in bloques]

    # ---- de bloques del plan a flowables ----
    def piezas(self, bloques: list) -> list:
        salida: list = []
        for b in bloques:
            salida += self.pieza(b)
        return salida

    def pieza(self, b: Any) -> list:
        g = self.geo
        if isinstance(b, Parrafo):
            return [self._p(b)]
        if isinstance(b, Espacio):
            return [Spacer(1, b.alto)]
        if isinstance(b, Imagen):
            return [self._imagen(b)]
        if isinstance(b, Sangrado):
            return [Indenter(left=b.izquierda)] + self.piezas(b.hijos) + [Indenter(left=-b.izquierda)]
        if isinstance(b, Grupo):
            return [KeepTogether(self.piezas(b.hijos))]
        if isinstance(b, Opcion):
            return [self._opcion(b)]
        if isinstance(b, TablaPareo):
            mitad = (g.ancho - g.sangria) / 2
            tabla = Table([[self._p(izq), self._p(der)] for izq, der in b.filas], colWidths=[mitad, mitad])
            tabla.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                       ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LINEBELOW", (0, 0), (-1, 0), 0.5, _GRIS_CLARO)]))
            return [tabla]
        if isinstance(b, TablaHuecos):
            tabla = Table([[self._p(num), self._celdas(celda)] for num, celda in b.filas],
                          colWidths=[1.0 * cm, g.ancho - g.sangria - 1.0 * cm])
            tabla.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                       ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                       ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LINEBELOW", (0, 0), (-1, -2), 0.4, _GRIS_CLARO)]))
            return [tabla]
        if isinstance(b, Renglones):
            return [_Renglones(b.n, b.paso)]
        if isinstance(b, RejillaBurbujas):
            fp = self.nombres["p"]
            celdas = [[_Burbujas(x.num, x.letras, x.redonda, x.marcadas, fp) if x is not None else "" for x in fila] for fila in b.celdas]
            tabla = Table(celdas, colWidths=[g.ancho / b.columnas] * b.columnas)
            tabla.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                                       ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
            return [tabla]
        if isinstance(b, Huecos):
            return [_Huecos(b, self.nombres["p"])]
        if isinstance(b, LogosCabecera):
            izq = self._imagen(b.izquierdo) if b.izquierdo else ""
            der = self._imagen(b.derecho) if b.derecho else ""
            tabla = Table([[izq, [self._p(x) for x in b.centro], der]], colWidths=[b.lado, g.ancho - 2 * b.lado, b.lado])
            tabla.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (0, 0), "LEFT"), ("ALIGN", (2, 0), (2, 0), "RIGHT"),
                                       ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                       ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
            return [tabla]
        if isinstance(b, CuadroEstudiante):
            cuadro = Table([[self._p(c) if isinstance(c, Parrafo) else c for c in fila] for fila in b.filas],
                           colWidths=b.anchos, rowHeights=[b.alto_fila] * 2)
            cuadro.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.8, colors.black), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                        ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
            return [cuadro]
        if isinstance(b, FilaDocente):
            celdas = [self._p(b.izquierda) if b.izquierda else ""]
            anchos = [b.ancho_izquierda]
            if b.nota:
                celdas.append(self._p(b.nota))
                anchos = [b.ancho_izquierda, b.ancho_nota]
            fila = Table([celdas], colWidths=anchos)
            fila.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                      ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
            return [fila]
        raise TypeError(f"bloque desconocido: {type(b).__name__}")

    @staticmethod
    def _imagen(im: Imagen) -> RLImage:
        return RLImage(io.BytesIO(im.datos), width=im.ancho, height=im.alto, hAlign=im.alinear)

    def _opcion(self, o: Opcion) -> Any:
        base = self.plan.estilos["base"]
        if self.simple:
            return self._p(Parrafo(base, ("○ " if o.casilla == "redonda" else "□ ") + o.marcado))
        g = self.geo
        t = Table([[_Casilla(redonda=o.casilla == "redonda"), self._p(Parrafo(self.plan.estilos["opcion"], o.marcado))]],
                  colWidths=[18, g.ancho - g.sangria - 18])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (0, 0), 2.5),
                               ("TOPPADDING", (1, 0), (1, 0), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        return t

    # ---- encabezado corrido y documento ----
    def _encabezado(self, sec: Seccion, vista: dict):
        g, fe = self.geo, self.plan.fuente_e

        def dibujar(c, doc):
            c._seccion = sec.id                      # para «Página X de Y» dentro de su sección (ver _Lienzo)
            c._margen_der = g.m_der                  # el pie va dentro del margen inferior, a la altura que quepa
            c._pie_y = max(0.45 * cm, g.m_inf - 0.8 * cm)
            c._fuente_pie = fe
            # Primera hoja de la sección: lleva el encabezado grande, no el corrido.
            vista["n"] = vista["n"] + 1 if vista["seccion"] == sec.id else 1
            vista["seccion"] = sec.id
            if sec.primera_sin_encabezado and vista["n"] == 1:
                return
            c.saveState()
            c.setFont(fe, 8)
            c.setFillColor(_GRIS)
            y = g.papel[1] - max(0.55 * cm, g.m_sup - 0.8 * cm)      # dentro del margen superior
            c.drawString(g.m_izq, y, sec.izquierda)
            c.drawRightString(g.papel[0] - g.m_der, y, sec.derecha)
            c.setStrokeColor(_GRIS_CLARO)
            c.setLineWidth(0.5)
            c.line(g.m_izq, y - 4, g.papel[0] - g.m_der, y - 4)
            c.restoreState()
        return dibujar

    def construir(self):
        g, plan = self.geo, self.plan
        buf = io.BytesIO()
        doc = BaseDocTemplate(buf, pagesize=g.papel, leftMargin=g.m_izq, rightMargin=g.m_der,
                              topMargin=g.m_sup, bottomMargin=g.m_inf, title=plan.meta["titulo"],
                              author=plan.meta["autor"], subject=plan.meta["materia"], creator="Cátedra")
        marco = lambda: Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="m", leftPadding=0, rightPadding=0,
                              topPadding=0, bottomPadding=0)
        vista = {"seccion": None, "n": 0}
        doc.addPageTemplates([PageTemplate(id=s.id, frames=[marco()], onPage=self._encabezado(s, vista)) for s in plan.secciones])
        historia: list = []
        for i, sec in enumerate(plan.secciones):
            if i:
                historia.extend([NextPageTemplate(sec.id), PageBreak()])
            historia += self.piezas(sec.bloques)
        doc.build(historia, canvasmaker=_Lienzo)
        return buf.getvalue(), doc.page


def generar_pdf(questions: List[Dict[str, Any]], answer_key: Dict[int, Dict[str, Any]],
                total_points: float, datos: DatosExamen) -> ResultadoPdf:
    """El PDF del examen (y su clave). `questions` y `answer_key` son los mismos que recibe
    xml_builder.build_xml: aquí no se valida (lo hace la ruta, igual que para el XML)."""
    plan = construir_plan(questions, answer_key, total_points, datos)
    # Si una pregunta no cabe en una página dentro de una tabla (algo enorme), se rehace sin tablas.
    for simple in (False, True):
        try:
            pdf, paginas = _Dibujante(plan, simple).construir()
            break
        except LayoutError:
            if simple:
                raise
    return ResultadoPdf(pdf=pdf, paginas=paginas, preguntas=plan.preguntas, avisos=plan.avisos)
