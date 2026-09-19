"""
extractor.py — Handles text extraction from uploaded files.
Supports .pdf (via pdfplumber) and .txt (direct UTF-8 read).
"""
import pdfplumber
import io
import re
from typing import List
from PIL import Image

# Tope de páginas que se renderizan como imagen y se envían a Gemini. Un
# examen extremo con decenas de páginas con imágenes no debe disparar el
# costo/latencia sin límite — por encima de esto se ignoran las imágenes
# de las páginas restantes (el texto de esas páginas se sigue extrayendo
# normalmente, solo se pierde la lectura de código/color en imagen ahí).
MAX_IMAGE_PAGES = 15


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
                rendered = page.to_image(resolution=200)
                images.append(rendered.original)
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
            rendered = page.to_image(resolution=200)
            images.append(rendered.original)
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
        for page in pdf.pages:
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
    return segs


def _word_style(word: dict, highlights: List[tuple], underlines: List[tuple]) -> str | None:
    """Marca de estilo de una palabra (sin contar el color de texto)."""
    if highlights and any(_in_bbox(word, b) for b in highlights):
        return "resaltado"
    if underlines:
        width = (word["x1"] - word["x0"]) or 1.0
        for x0, x1, y in underlines:
            overlap = min(x1, word["x1"]) - max(x0, word["x0"])
            if overlap >= 0.6 * width and word["bottom"] - 1 <= y <= word["bottom"] + 3:
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

    blocks = []  # (top, texto)
    for line in cluster_objects(words, "top", tolerance=3):
        line = sorted(line, key=lambda w: w["x0"])
        parts: List[str] = []
        current = None  # nombre del color del tramo abierto
        for w in line:
            color = w.get("non_stroking_color")
            name = _color_name(color) if _char_has_color({"text": w["text"], "non_stroking_color": color}) else None
            name = name or _word_style(w, highlights, underlines)
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
            try:
                for t in page.extract_tables():
                    rows = [[" ".join(str(c or "").split()) for c in row] for row in t]
                    if len(rows) >= 2:
                        tables.append(rows)
            except Exception:  # noqa: BLE001
                continue
    return tables


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
