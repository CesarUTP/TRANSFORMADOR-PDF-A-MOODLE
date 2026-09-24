"""
extractor.py — Handles text extraction from uploaded files.
Supports .pdf (via pdfplumber) and .txt (direct UTF-8 read).
"""
import pdfplumber
import bisect
import io
import logging
import re
from typing import List
from PIL import Image

# pdfminer (debajo de pdfplumber) avisa "CropBox missing from /Page,
# defaulting to MediaBox" por cada página de cada lectura: es normal en PDFs
# exportados desde Word/Docs, usa el tamaño completo de la página (lo
# correcto) y no afecta la extracción. Como el PDF se recorre varias veces
# por examen, llenaba la consola con decenas de líneas iguales. Sus errores
# reales se siguen mostrando.
logging.getLogger("pdfminer").setLevel(logging.ERROR)

# Tope de páginas que se renderizan como imagen y se envían a Gemini. Un
# examen extremo con decenas de páginas con imágenes no debe disparar el
# costo/latencia sin límite — por encima de esto se ignoran las imágenes
# de las páginas restantes (el texto de esas páginas se sigue extrayendo
# normalmente, solo se pierde la lectura de código/color en imagen ahí).
MAX_IMAGE_PAGES = 15

# Límites para que un PDF enorme o armado a propósito no deje la app sin
# memoria ni CPU. Un examen real queda muy por debajo de todos.
MAX_PAGINAS = 150
# Píxeles por página renderizada (~12 MP = carta a 200 DPI con holgura).
# Una página gigante se renderiza a menos DPI en vez de ocupar cientos de MB.
MAX_PIXELES_RENDER = 12_000_000
# Objetos gráficos (líneas, rectángulos, anotaciones) y caracteres por
# página por encima de los cuales no se buscan marcas (color, subrayado,
# resaltado): esa página se lee con extract_text(), como sin marcas.
MAX_OBJETOS_MARCAS = 2_000
MAX_CARACTERES_MARCAS = 20_000


class DocumentoDemasiadoGrande(ValueError):
    pass


def comprobar_paginas(file_bytes: bytes) -> None:
    """Rechaza un PDF con más páginas que MAX_PAGINAS antes de procesarlo."""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        if len(pdf.pages) > MAX_PAGINAS:
            raise DocumentoDemasiadoGrande(
                f"El PDF tiene {len(pdf.pages)} páginas; el máximo es {MAX_PAGINAS}. "
                "Divide el documento en partes más pequeñas."
            )


def _render(page, dpi: int = 200) -> Image.Image:
    """Renderiza una página a `dpi`, o a menos si pasaría de MAX_PIXELES_RENDER."""
    ancho, alto = float(page.width), float(page.height)
    if ancho <= 0 or alto <= 0:
        raise ValueError("Página del PDF con tamaño inválido.")
    escala = dpi / 72
    if ancho * alto * escala * escala > MAX_PIXELES_RENDER:
        dpi = max(1, int(72 * (MAX_PIXELES_RENDER / (ancho * alto)) ** 0.5))
    return page.to_image(resolution=dpi).original


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract all text from a PDF file given its raw bytes."""
    full_text = ""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"
    return full_text


def extract_pages_text(file_bytes: bytes) -> List[str]:
    """Texto de cada página por separado (mismo extract_text que el resto)."""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def join_pages_with_markers(pages: List[str]) -> str:
    """
    Une el texto de las páginas con una marca "[Página N]" antes de cada
    una. El modo JSON la usa para que el modelo pueda decir de qué página
    viene cada pregunta (campo "pagina"), dato que el formato de texto
    perdía por completo al concatenar todo.
    """
    return "\n\n".join(f"[Página {i}]\n{t}" for i, t in enumerate(pages, start=1) if t.strip())


def extract_text_and_images_from_pdf(file_bytes: bytes) -> tuple[str, List[Image.Image]]:
    """
    Extrae el texto completo del PDF, y además renderiza como imagen
    ÚNICAMENTE las páginas que tienen al menos una imagen incrustada
    (código en captura de pantalla, texto marcado solo por color, etc. —
    contenido invisible para extract_text()). Las páginas sin imágenes no
    se renderizan, para no gastar de más en páginas que el texto ya cubre
    por completo.
    """
    full_text = ""
    images: List[Image.Image] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"
            if page.images and len(images) < MAX_IMAGE_PAGES:
                # 200 DPI en vez de 150: el color de las marcas de respuesta
                # se distingue mejor a esta resolución, sin disparar
                # demasiado el tamaño de la imagen.
                images.append(_render(page))
    return full_text, images


def render_all_pages_as_images(file_bytes: bytes) -> List[Image.Image]:
    """
    Renderiza CADA página del PDF como imagen (a diferencia de
    extract_text_and_images_from_pdf, que solo renderiza páginas con
    imágenes incrustadas) — usado por la acción explícita "Normalizar con
    IA", donde el usuario ya aceptó pagar el costo/tiempo extra de que
    Gemini lea el documento completo visualmente. Cubre tanto el PDF
    escaneado (sin ninguna capa de texto) como el que sí tiene texto pero
    con contenido visual disperso que el modo normal no capturó del todo.
    """
    images: List[Image.Image] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            if len(images) >= MAX_IMAGE_PAGES:
                break
            images.append(_render(page))
    return images


def pdf_has_embedded_images(file_bytes: bytes) -> bool:
    """
    Chequeo rápido (sin renderizar nada) de si el PDF trae al menos una
    página con imagen incrustada — señal de un "caso especial" (código en
    captura, marcas de respuesta solo por color, etc.) que el prefiltro de
    IA puede no transcribir con 100% de fiabilidad. Se usa para avisarle al
    usuario ANTES de arrancar el procesamiento pesado, no después.
    """
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages[:MAX_PAGINAS]:
            if page.images:
                return True
    return False


def _char_has_color(ch: dict) -> bool:
    if not ch.get("text", "").strip():
        # Un espacio en blanco coloreado es invisible para el lector (no
        # tiene glifo que pintar) — un artefacto común de encabezados/pies
        # de página o hipervínculos que "heredan" el color de un elemento
        # vecino. Contarlo como marca de color daba falsos positivos en
        # documentos completamente en blanco y negro.
        return False
    color = ch.get("non_stroking_color")
    if not isinstance(color, (tuple, list)) or len(color) != 3:
        # Escala de grises (un solo valor), CMYK u otro formato inesperado:
        # no es una marca de color reconocible.
        return False
    r, g, b = color
    # Un tono "de color" se aleja de la diagonal gris (r≈g≈b); un umbral
    # pequeño evita falsos positivos por antialiasing o negros/grises
    # ligeramente impuros.
    return max(abs(r - g), abs(g - b), abs(r - b)) > 0.15


def _color_name(rgb) -> str:
    """Nombre aproximado de un color RGB (0-1), para que el modelo distinga
    p. ej. una marca en rojo de un título en azul."""
    import colorsys
    r, g, b = (float(x) for x in rgb)
    h, l, sat = colorsys.rgb_to_hls(r, g, b)
    deg = h * 360
    if deg < 15 or deg >= 330:
        return "rojo"
    if deg < 45:
        return "naranja"
    if deg < 70:
        return "amarillo"
    if deg < 170:
        return "verde"
    if deg < 200:
        return "celeste"
    if deg < 260:
        return "azul"
    return "morado"


def _in_bbox(word: dict, bbox) -> bool:
    x0, top, x1, bottom = bbox
    cx, cy = (word["x0"] + word["x1"]) / 2, (word["top"] + word["bottom"]) / 2
    return x0 <= cx <= x1 and top <= cy <= bottom


def _render_table(rows) -> str:
    """Tabla como filas "| celda | celda |" (celdas vacías incluidas: la
    columna en la que está cada marca es justamente la información)."""
    out = []
    for row in rows:
        cells = [" ".join(str(c or "").split()) for c in row]
        out.append("| " + " | ".join(cells) + " |")
    return "[Tabla]\n" + "\n".join(out) + "\n[/Tabla]"


_BOLD_FONT = re.compile(r"bold|black|heavy|semibold|demibold", re.IGNORECASE)


def _is_marker_fill(color) -> bool:
    """Relleno "de marcador": un color con tono (amarillo, verde, celeste…),
    no blanco ni gris — el sombreado gris de una celda o un encabezado no
    es una marca de respuesta."""
    if not isinstance(color, (tuple, list)) or len(color) != 3:
        return False
    r, g, b = (float(x) for x in color)
    return max(abs(r - g), abs(g - b), abs(r - b)) > 0.15


def _highlight_boxes(page) -> List[tuple]:
    """Cajas (x0, top, x1, bottom) de resaltado: rectángulos rellenos de
    color detrás del texto (así exporta Word el resaltado) y anotaciones
    de resaltado hechas con un lector de PDF."""
    area = float(page.width * page.height) or 1.0
    boxes = []
    for r in page.rects:
        if r.get("fill") and _is_marker_fill(r.get("non_stroking_color")) \
                and (r["width"] * r["height"]) / area < 0.3:
            boxes.append((r["x0"], r["top"], r["x1"], r["bottom"]))
    for a in page.annots or []:
        subtype = str((a.get("data") or {}).get("Subtype", "")).lower()
        if "highlight" in subtype:
            boxes.append((a["x0"], a["top"], a["x1"], a["bottom"]))
    return boxes


def _underline_segments(page) -> List[tuple]:
    """Segmentos horizontales finos (x0, x1, y): líneas o rectángulos de
    menos de 1.5 pt de alto, que es como se dibuja un subrayado."""
    segs = [(l["x0"], l["x1"], l["top"]) for l in page.lines if abs(l["top"] - l["bottom"]) < 1.5]
    segs += [(r["x0"], r["x1"], r["top"]) for r in page.rects if r["height"] < 1.5 and r["width"] > 3]
    # Ordenados por altura: _word_style solo revisa los que están cerca del
    # borde inferior de cada palabra (bisect), no todos contra todas.
    return sorted(segs, key=lambda s: s[2])


def _word_style(word: dict, highlights: List[tuple], underlines: List[tuple],
                under_y: List[float] | None = None) -> str | None:
    """Marca de estilo de una palabra (sin contar el color de texto).
    `underlines` ordenado por y; `under_y` son esas alturas (se calculan una
    vez por página y se pasan aquí para no recorrerlas en cada palabra)."""
    if highlights and any(_in_bbox(word, b) for b in highlights):
        return "resaltado"
    if underlines:
        # abs(): en una página rotada 90°/270° el bbox de una palabra puede
        # venir con x1 < x0 o bottom < top — sin abs(), height/width salían
        # negativos y "above" (más abajo) también, invirtiendo la ventana
        # de comparación y desactivando la detección de subrayado en
        # silencio para esa palabra en vez de solo no encontrar nada.
        width = abs(word["x1"] - word["x0"]) or 1.0
        height = abs(word["bottom"] - word["top"]) or 1.0
        # underlines viene ordenado por y (ver _underline_segments): solo los
        # de la ventana [bottom - 4, bottom + 3] pueden cumplir la condición.
        ys = under_y if under_y is not None else [u[2] for u in underlines]
        desde = bisect.bisect_left(ys, word["bottom"] - 4.0)
        hasta = bisect.bisect_right(ys, word["bottom"] + 3)
        for x0, x1, y in underlines[desde:hasta]:
            overlap = min(x1, word["x1"]) - max(x0, word["x0"])
            # Word dibuja el subrayado sobre la línea base, hasta ~3 pt POR
            # ENCIMA del borde inferior del cuadro de la palabra (Aptos 12 pt:
            # y=358,4 con bottom=361,3); antes solo se aceptaba desde 1 pt por
            # encima y esas opciones subrayadas llegaban al modelo sin marca.
            # El margen es en puntos y tiene tope (4 pt): con uno proporcional,
            # el borde de una tabla que cruza una letra grande de una marca de
            # agua contaba como subrayado (x06).
            above = min(0.35 * height, 4.0)
            if overlap >= 0.6 * width and word["bottom"] - above <= y <= word["bottom"] + 3:
                return "subrayado"
    if _BOLD_FONT.search(str(word.get("fontname", ""))):
        return "negrita"
    return None


def _enriched_page_text(page) -> str:
    """
    Texto de UNA página reconstruido desde las palabras de pdfplumber, con
    dos datos que extract_text() pierde y que son justamente las marcas de
    respuesta más comunes en un PDF digital:

    - Color: cada tramo en color va envuelto como ⟦rojo⟧texto⟦/rojo⟧. Sin
      esto, una respuesta marcada en rojo llegaba al modelo como texto
      normal y el modelo terminaba resolviendo la pregunta por su cuenta.
    - Tablas: se insertan con su estructura ("| celda | celda |") en el
      lugar donde están. En texto plano la "X" de un cuadro de marcas
      quedaba al final de la fila, sin saber de qué columna era, y el
      modelo adivinaba la columna por el significado (REGLA 10).
    - Resaltado, subrayado y negrita: igual que el color, como
      ⟦resaltado⟧…⟦/resaltado⟧, ⟦subrayado⟧… y ⟦negrita⟧… (prioridad:
      color > resaltado > subrayado > negrita, una sola marca por palabra).

    Las líneas se agrupan por altura igual que lo hace pdfplumber.
    """
    from pdfplumber.utils import cluster_objects

    # Página con demasiados objetos o caracteres (un PDF armado a propósito,
    # o un plano/diagrama): buscar marcas en ella costaría minutos de CPU.
    if (len(page.lines) + len(page.rects) + len(page.annots or []) > MAX_OBJETOS_MARCAS
            or len(page.chars) > MAX_CARACTERES_MARCAS):
        return page.extract_text() or ""

    tables = []
    try:
        for t in page.find_tables():
            rows = t.extract()
            if rows and len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                tables.append((t.bbox, rows))
    except Exception:  # noqa: BLE001 — una tabla rara no debe tumbar la extracción
        tables = []

    words = page.extract_words(extra_attrs=["non_stroking_color", "fontname"], keep_blank_chars=False)
    words = [w for w in words if not any(_in_bbox(w, bbox) for bbox, _ in tables)]
    highlights = _highlight_boxes(page)
    underlines = _underline_segments(page)
    under_y = [u[2] for u in underlines]

    blocks = []  # (top, texto)
    for line in cluster_objects(words, "top", tolerance=3):
        line = sorted(line, key=lambda w: w["x0"])
        parts: List[str] = []
        current = None  # nombre del color del tramo abierto
        for w in line:
            color = w.get("non_stroking_color")
            name = _color_name(color) if _char_has_color({"text": w["text"], "non_stroking_color": color}) else None
            name = name or _word_style(w, highlights, underlines, under_y)
            if name != current:
                if current:
                    parts[-1] += f"⟦/{current}⟧"
                parts.append(f"⟦{name}⟧{w['text']}" if name else w["text"])
                current = name
            else:
                parts.append(w["text"])
        if current:
            parts[-1] += f"⟦/{current}⟧"
        blocks.append((min(w["top"] for w in line), " ".join(parts)))
    for bbox, rows in tables:
        blocks.append((bbox[1], _render_table(rows)))
    return "\n".join(text for _, text in sorted(blocks, key=lambda b: b[0]))


def _page_needs_enrichment(page) -> bool:
    if any(_char_has_color(ch) for ch in page.chars):
        return True
    if _highlight_boxes(page) or _underline_segments(page):
        return True
    if any(_BOLD_FONT.search(str(ch.get("fontname", ""))) for ch in page.chars):
        return True
    try:
        return bool(page.find_tables())
    except Exception:  # noqa: BLE001
        return False


def extract_pages_text_enriched(file_bytes: bytes) -> List[str]:
    """
    Como extract_pages_text, pero las páginas con texto de color o con
    tablas salen enriquecidas (ver _enriched_page_text). Las demás salen
    exactamente igual que con extract_text, para no cambiar nada en los
    documentos que no usan ninguna de las dos cosas.
    """
    pages: List[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            pages.append(_enriched_page_text(page) if _page_needs_enrichment(page) else (page.extract_text() or ""))
    return pages


def extract_tables(file_bytes: bytes) -> List[List[List[str]]]:
    """Todas las tablas del PDF (filas de celdas), para resolver cuadros de
    marcas en código (ver mark_resolver.resolve_table_marks)."""
    tables: List[List[List[str]]] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            tables.extend(_page_tables(page))
    return tables


def _page_tables(page) -> List[List[List[str]]]:
    tables: List[List[List[str]]] = []
    try:
        for t in page.extract_tables():
            rows = [[" ".join(str(c or "").split()) for c in row] for row in t]
            if len(rows) >= 2:
                tables.append(rows)
    except Exception:  # noqa: BLE001
        pass
    return tables


def extract_pages_enriched_and_tables(file_bytes: bytes) -> tuple[List[str], List[List[List[str]]]]:
    """
    extract_pages_text_enriched() + extract_tables() en un solo
    pdfplumber.open(): pipeline._deterministic_marks las llamaba una
    después de la otra sobre el MISMO archivo — cada pdfplumber.open()
    reparsea la estructura completa del PDF desde cero, así que llamarlas
    por separado duplicaba ese trabajo sin necesidad (una sola petición de
    /api/parse en modo JSON llegaba a abrir el mismo PDF 5 veces; ver
    dev/eval_results/RESULTADOS.md).
    """
    pages: List[str] = []
    tables: List[List[List[str]]] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            pages.append(_enriched_page_text(page) if _page_needs_enrichment(page) else (page.extract_text() or ""))
            tables.extend(_page_tables(page))
    return pages, tables


def get_colored_page_numbers(file_bytes: bytes) -> List[int]:
    """Números (1-based) de las páginas que usan texto de color."""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        return [p.page_number for p in pdf.pages if any(_char_has_color(ch) for ch in p.chars)]


def get_colored_text_pages(file_bytes: bytes) -> List[str]:
    """
    Devuelve el texto completo de cada página del PDF que use texto de
    color no-gris (ej. respuestas marcadas en rojo u otro color). Sirve
    para luego ubicar, por coincidencia de texto, cuáles preguntas
    concretas viven en una página con esa marca — y así señalarlas
    individualmente en vez de un aviso genérico para todo el documento.
    """
    pages_text: List[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            if any(_char_has_color(ch) for ch in page.chars):
                pages_text.append(page.extract_text() or "")
    return pages_text


def get_colored_pages(file_bytes: bytes) -> tuple[List[int], List[str]]:
    """
    get_colored_page_numbers() + get_colored_text_pages() en un solo
    pdfplumber.open() (mismo motivo que extract_pages_enriched_and_tables):
    pipeline.py las llamaba por separado sobre el MISMO archivo dentro de
    la MISMA petición.
    """
    numbers: List[int] = []
    texts: List[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            if any(_char_has_color(ch) for ch in page.chars):
                numbers.append(page.page_number)
                texts.append(page.extract_text() or "")
    return numbers, texts


def pdf_has_colored_text(file_bytes: bytes) -> bool:
    """
    Chequeo rápido de si el PDF usa texto de color no-gris en vez de
    imágenes incrustadas. A diferencia de pdf_has_embedded_images(), esto
    NO es un "caso especial" para el usuario — el sistema ya sabe
    interpretar este tipo de marca (REGLA 8 del prompt) — solo sirve para
    mostrar después una recomendación de revisar manualmente las
    respuestas, por si la IA se equivocó al identificar alguna marca.
    """
    return bool(get_colored_text_pages(file_bytes))


def extract_text_from_txt(file_bytes: bytes) -> str:
    """Decode a text file from raw bytes (UTF-8 with fallback to latin-1)."""
    try:
        return file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return file_bytes.decode("latin-1")
