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


def pdf_has_colored_text(file_bytes: bytes) -> bool:
    """
    Chequeo rápido de si el PDF usa texto de color no-gris (ej. respuestas
    marcadas en rojo u otro color) en vez de imágenes incrustadas. A
    diferencia de pdf_has_embedded_images(), esto NO es un "caso especial"
    para el usuario — el sistema ya sabe interpretar este tipo de marca
    (REGLA 8 del prompt) — solo sirve para mostrar después una recomendación
    de revisar manualmente las respuestas, por si la IA se equivocó al
    identificar alguna marca.
    """
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            for ch in page.chars:
                color = ch.get("non_stroking_color")
                if not isinstance(color, (tuple, list)) or len(color) != 3:
                    # Escala de grises (un solo valor), CMYK u otro formato
                    # inesperado: no es una marca de color reconocible.
                    continue
                r, g, b = color
                # Un tono "de color" se aleja de la diagonal gris (r≈g≈b);
                # un umbral pequeño evita falsos positivos por antialiasing
                # o negros/grises ligeramente impuros.
                if max(abs(r - g), abs(g - b), abs(r - b)) > 0.15:
                    return True
    return False


def extract_text_from_txt(file_bytes: bytes) -> str:
    """Decode a text file from raw bytes (UTF-8 with fallback to latin-1)."""
    try:
        return file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return file_bytes.decode("latin-1")
