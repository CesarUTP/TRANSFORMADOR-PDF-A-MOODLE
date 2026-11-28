"""
plegado.py — «Modo folleto» del PDF (3.2): pone las páginas de dos en dos en hojas a lo ancho, en el orden en
que quedan al imprimir a doble cara (volteando por el borde corto), apilar las hojas y doblarlas por la mitad.

Cada hoja de papel lleva cuatro páginas. Con N páginas (se completa con blancos hasta un múltiplo de 4), la
primera hoja lleva delante [N | 1] y detrás [2 | N-1]; la segunda, delante [N-2 | 3] y detrás [4 | N-3]; etc.
Las páginas se copian tal cual (texto y dibujos vectoriales, sin encoger ni convertir en imagen): quien las
compone ya las hizo del tamaño de media hoja (plan_impreso, `plegado`).
"""

import io
from typing import List, Optional, Tuple

import pypdfium2 as pdfium

from pdfium_cerrojo import CERROJO

Cara = Tuple[Optional[int], Optional[int]]      # (página de la izquierda, página de la derecha); None = en blanco


def caras(n: int) -> List[Cara]:
    """Las caras en el orden del PDF (frente y dorso de la hoja 1, frente y dorso de la 2…), con las páginas
    numeradas desde 0. Siempre un número par de caras: cada hoja tiene dos."""
    total = max(4, -(-n // 4) * 4)
    real = lambda i: i if i < n else None
    out: List[Cara] = []
    for hoja in range(total // 4):
        out.append((real(total - 1 - 2 * hoja), real(2 * hoja)))
        out.append((real(2 * hoja + 1), real(total - 2 - 2 * hoja)))
    return out


def imponer(pdf: bytes) -> Tuple[bytes, int, int]:
    """(PDF para imprimir como folleto, caras, hojas) a partir de un PDF con páginas de media hoja."""
    with CERROJO:
        origen = pdfium.PdfDocument(pdf)
        destino = pdfium.PdfDocument.new()
        try:
            n = len(origen)
            if not n:
                raise ValueError("No hay páginas que imprimir.")
            ancho, alto = origen.get_page_size(0)
            orden = caras(n)
            piezas = {i: origen.page_as_xobject(i, destino) for i in range(n)}
            for cara in orden:
                pagina = destino.new_page(2 * ancho, alto)
                for lado, i in enumerate(cara):
                    if i is None:
                        continue
                    objeto = piezas[i].as_pageobject()
                    objeto.transform(pdfium.PdfMatrix().translate(lado * ancho, 0))
                    pagina.insert_obj(objeto)
                pagina.gen_content()
            salida = io.BytesIO()
            destino.save(salida)
            return salida.getvalue(), len(orden), len(orden) // 2
        finally:
            destino.close()
            origen.close()
