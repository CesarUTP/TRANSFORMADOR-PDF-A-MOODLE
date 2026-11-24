"""
pdfium_cerrojo.py — UN solo cerrojo para todo lo que dibuja una página con PDFium.

PDFium (la biblioteca que dibuja las páginas) no es segura entre hilos: dos dibujos a la vez, aunque sean de
archivos distintos, pueden cerrar el programa sin dejar un error en el registro. Se dibuja con PDFium en tres sitios:
la vista previa del PDF del examen (rutas_pdf), la lectura de PDF escaneados (extractor._render) y el recorte de
imágenes de las preguntas (imagenes). Como el servidor atiende cada petición en su propio hilo, una vista previa y una
conversión al mismo tiempo podían chocar. Todos toman ESTE cerrojo.

Es reentrante (RLock): quien ya lo tiene puede volver a pedirlo sin bloquearse. Va en un módulo aparte, plano en
backend/, para que los tres lo importen sin depender unos de otros.
"""

import threading

CERROJO = threading.RLock()
