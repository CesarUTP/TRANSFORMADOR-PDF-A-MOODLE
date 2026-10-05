"""
originales.py — el PDF que subió el docente, SOLO mientras la app está abierta.

«Revisión con el original» (2.0): el editor muestra, junto a cada pregunta, el
recorte de su página para comparar la respuesta que propone la app con la marca
del documento. Para dibujarlo bajo demanda el servidor conserva el PDF subido:

  - en MEMORIA, nunca en disco: no queda ningún archivo del examen fuera de la
    sesión, ni en data/ ni en carpetas temporales;
  - con tope (los dos últimos documentos y 120 MB en total);
  - se olvida al cerrar la app (es solo memoria) y al guardar otro documento
    más allá del tope (una conversión nueva desplaza a las más viejas);
  - NADA del examen original se guarda en el Historial: al reabrir una
    conversión desde el Historial no hay original que mostrar.

Es un módulo plano (sin paquetes): dev/sync_ejecutable.py solo copia los
backend/*.py de primer nivel.
"""

import io
import logging
import re
import threading
import uuid
from collections import OrderedDict
from typing import Optional, Tuple

import pdfplumber
from PIL import Image, ImageDraw

import extractor

logger = logging.getLogger(__name__)

MAX_DOCUMENTOS = 2
MAX_BYTES_TOTAL = 120 * 1024 * 1024
ANCHO_MAX_PX = 1800
ID_VALIDO = re.compile(r"^[0-9a-f]{32}$")

# Márgenes alrededor del recuadro de la pregunta, como fracción de la página.
_MARGEN_X = 0.04
_MARGEN_Y = 0.025
_COLOR_RESALTE = (14, 165, 233)

_cerrojo = threading.Lock()
_docs: "OrderedDict[str, bytes]" = OrderedDict()


class OriginalNoDisponible(LookupError):
    """El original ya no está (la app se reabrió, o lo desplazó otra conversión)."""


def guardar(raw: bytes) -> Optional[str]:
    """Guarda el PDF y devuelve su id, o None si no cabe en el tope."""
    if not raw or len(raw) > MAX_BYTES_TOTAL:
        return None
    ident = uuid.uuid4().hex
    with _cerrojo:
        _docs[ident] = raw
        while len(_docs) > MAX_DOCUMENTOS or sum(len(v) for v in _docs.values()) > MAX_BYTES_TOTAL:
            _docs.popitem(last=False)
        if ident not in _docs:
            return None
    return ident


def obtener(ident: str) -> bytes:
    if not isinstance(ident, str) or not ID_VALIDO.match(ident):
        raise OriginalNoDisponible(ident)
    with _cerrojo:
        raw = _docs.get(ident)
        if raw is not None:
            _docs.move_to_end(ident)
    if raw is None:
        raise OriginalNoDisponible(ident)
    return raw


def olvidar_todo() -> None:
    with _cerrojo:
        _docs.clear()


def hay_originales() -> int:
    with _cerrojo:
        return len(_docs)


def parsear_recuadro(texto: Optional[str]) -> Optional[Tuple[float, float, float, float]]:
    """«x0,y0,x1,y1» (fracciones de la página, origen arriba a la izquierda) → tupla, o None si no vale."""
    if not texto:
        return None
    try:
        x0, y0, x1, y1 = (float(p) for p in texto.split(","))
    except (ValueError, TypeError):
        return None
    if not all(0.0 <= v <= 1.0 for v in (x0, y0, x1, y1)) or x1 - x0 < 0.005 or y1 - y0 < 0.005:
        return None
    return x0, y0, x1, y1


def _png(imagen: Image.Image) -> bytes:
    if imagen.width > ANCHO_MAX_PX:
        alto = max(1, round(imagen.height * ANCHO_MAX_PX / imagen.width))
        imagen = imagen.resize((ANCHO_MAX_PX, alto), Image.LANCZOS)
    salida = io.BytesIO()
    imagen.convert("RGB").save(salida, format="PNG", optimize=False)
    return salida.getvalue()


def _resaltar(imagen: Image.Image, caja_px: Tuple[int, int, int, int]) -> Image.Image:
    """Dibuja el recuadro de la pregunta (relleno suave + borde) sobre la página."""
    base = imagen.convert("RGBA")
    capa = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    d.rectangle(caja_px, fill=_COLOR_RESALTE + (36,))
    grosor = max(2, round(min(base.size) / 300))
    d.rectangle(caja_px, outline=_COLOR_RESALTE + (230,), width=grosor)
    return Image.alpha_composite(base, capa)


def renderizar(ident: str, pagina: int, recuadro: Optional[Tuple[float, float, float, float]] = None,
               vista: str = "recorte", zoom: float = 1.0) -> bytes:
    """PNG de la página `pagina` (desde 1) del original.

    vista="recorte" con recuadro: solo la zona de la pregunta (con un margen), resaltada.
    vista="pagina" (o recorte sin recuadro): la página completa, con el recuadro
    resaltado si se conoce. Sin recuadro (dos columnas, escaneados, páginas
    giradas) siempre es la página completa."""
    raw = obtener(ident)
    zoom = min(3.0, max(1.0, float(zoom or 1.0)))
    recortar = vista != "pagina" and recuadro is not None
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        if not 1 <= pagina <= len(pdf.pages):
            raise IndexError("página fuera del documento")
        page = pdf.pages[pagina - 1]
        try:
            imagen = extractor._render(page, dpi=int((120 if recortar else 85) * zoom))
        finally:
            extractor._liberar(page)
    ancho, alto = imagen.size
    if recuadro:
        x0, y0, x1, y1 = recuadro
        caja = (round(x0 * ancho), round(y0 * alto), round(x1 * ancho), round(y1 * alto))
        imagen = _resaltar(imagen, caja)
        if recortar:
            cx0, cy0 = max(0, round((x0 - _MARGEN_X) * ancho)), max(0, round((y0 - _MARGEN_Y) * alto))
            cx1, cy1 = min(ancho, round((x1 + _MARGEN_X) * ancho)), min(alto, round((y1 + _MARGEN_Y) * alto))
            imagen = imagen.crop((cx0, cy0, cx1, cy1))
    return _png(imagen)
