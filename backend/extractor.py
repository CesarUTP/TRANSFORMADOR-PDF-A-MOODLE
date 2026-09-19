"""
extractor.py — Handles text extraction from uploaded files.
Supports .pdf (via pdfplumber) and .txt (direct UTF-8 read).
"""
import pdfplumber
import io
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


def _annotated_page_text(page) -> str:
    """
    Texto de UNA página con cada tramo de texto en color envuelto como
    ⟦rojo⟧texto⟦/rojo⟧. extract_text() descarta el color, así que una
    respuesta marcada en rojo llegaba al modelo como texto normal —
    invisible — y el modelo terminaba resolviendo la pregunta por su
    cuenta (ver REGLA 8). Se reconstruyen las líneas desde las palabras
    (mismo agrupamiento por altura que usa pdfplumber) para poder marcar
    exactamente qué palabras tienen color.
    """
    from pdfplumber.utils import cluster_objects

    words = page.extract_words(extra_attrs=["non_stroking_color"], keep_blank_chars=False)
    lines_out: List[str] = []
    for line in cluster_objects(words, "top", tolerance=3):
        line = sorted(line, key=lambda w: w["x0"])
        parts: List[str] = []
        current = None  # nombre del color del tramo abierto
        for w in line:
            color = w.get("non_stroking_color")
            name = _color_name(color) if _char_has_color({"text": w["text"], "non_stroking_color": color}) else None
            if name != current:
                if current:
                    parts[-1] += f"⟦/{current}⟧"
                if name:
                    parts.append(f"⟦{name}⟧{w['text']}")
                else:
                    parts.append(w["text"])
                current = name
            else:
                parts.append(w["text"])
        if current:
            parts[-1] += f"⟦/{current}⟧"
        lines_out.append(" ".join(parts))
    return "\n".join(lines_out)


def extract_pages_text_with_color_marks(file_bytes: bytes) -> List[str]:
    """
    Como extract_pages_text, pero en las páginas que usan texto de color
    ese texto va anotado con ⟦color⟧…⟦/color⟧ (ver _annotated_page_text).
    Las páginas sin color salen exactamente igual que con extract_text,
    para no cambiar nada en los documentos que no usan color.
    """
    pages: List[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            if any(_char_has_color(ch) for ch in page.chars):
                pages.append(_annotated_page_text(page))
            else:
                pages.append(page.extract_text() or "")
    return pages


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
