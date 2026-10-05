"""
test_original.py — Versión 2.0: «Revisión con el original».

    PYTHONUTF8=1 backend/venv/bin/python dev/test_original.py

Sin red ni Gemini (la IA se simula) y sin tocar el historial ni la clave. Cubre:
  1. originales.py: el PDF solo en MEMORIA, con tope; se olvida; ids inválidos.
  2. El dibujo del recorte: tamaño, resalte, página completa, páginas que no existen.
  3. La ruta GET /api/original/{id}/pagina/{n}: PNG, mensajes de error, validación.
  4. De punta a punta: parse_document devuelve `original_id` solo para PDF; el
     original NO acaba en el historial ni en ningún archivo.
  5. Escaneados: toda respuesta de origen «ia» sale con confianza «baja» y el aviso
     de documento escaneado; los PDF con texto no cambian.
"""

import copy
import io
import logging
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "dev"))
sys.path.insert(0, str(ROOT / "dev" / "synthetic"))

TMP = Path(tempfile.mkdtemp(prefix="conv original "))
os.environ["HOME"] = str(TMP / "home")
os.environ["LOCALAPPDATA"] = str(TMP / "home" / "AppData")
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("XDG_DATA_HOME", None)

import database  # noqa: E402

DB_DIR = TMP / "datos" / "data"
DB_DIR.mkdir(parents=True)
database.get_db_path = lambda: DB_DIR / "exams_history.db"  # ANTES de importar main

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

import xml_fidelity as xf  # noqa: E402  (apaga el logging)
import exams  # noqa: E402
import confianza  # noqa: E402
import ia_gemini  # noqa: E402
import main  # noqa: E402
import originales  # noqa: E402
import pipeline  # noqa: E402
import seguridad  # noqa: E402

logging.disable(logging.CRITICAL)
for _h in list(logging.getLogger().handlers):
    if getattr(_h, "_conversor_errores", False):
        logging.getLogger().removeHandler(_h)

fallas = 0


def ok(cond, msg):
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


def pdf_con_texto(paginas=2):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for n in range(1, paginas + 1):
        c.setFont("Helvetica", 12)
        c.drawString(72, 700, f"{n}. Pregunta de la página {n}")
        c.drawString(90, 680, "a) primera")
        c.drawString(90, 664, "b) segunda")
        c.showPage()
    c.save()
    return buf.getvalue()


def pdf_escaneado():
    """Una página que es solo una imagen (sin capa de texto)."""
    imagen = Image.new("RGB", (850, 1100), "white")
    buf = io.BytesIO()
    imagen.save(buf, format="PNG")
    buf.seek(0)
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=letter)
    from reportlab.lib.utils import ImageReader
    c.drawImage(ImageReader(buf), 0, 0, width=letter[0], height=letter[1])
    c.showPage()
    c.save()
    return out.getvalue()


c = TestClient(main.app, base_url="http://127.0.0.1:8000")
H = {"X-Conversor-Token": seguridad.TOKEN}
PNG = b"\x89PNG\r\n\x1a\n"

# ══════════════════════════════════════════════════════════════════════════
print("1. originales: solo en memoria, con tope")
# ══════════════════════════════════════════════════════════════════════════
originales.olvidar_todo()
a = originales.guardar(b"%PDF-uno")
ok(a and originales.obtener(a) == b"%PDF-uno", "se guarda y se recupera")
b = originales.guardar(b"%PDF-dos")
d3 = originales.guardar(b"%PDF-tres")
ok(originales.hay_originales() == originales.MAX_DOCUMENTOS, f"tope de documentos ({originales.MAX_DOCUMENTOS})")
try:
    originales.obtener(a)
    ok(False, "el más viejo se desplaza al guardar uno nuevo")
except originales.OriginalNoDisponible:
    ok(True, "el más viejo se desplaza al guardar uno nuevo")
ok(originales.guardar(b"") is None and originales.guardar(b"x" * (originales.MAX_BYTES_TOTAL + 1)) is None,
   "vacío o más grande que el tope: no se guarda")
for malo in ("", "../etc/passwd", "x" * 32, None, 5):
    try:
        originales.obtener(malo)
        ok(False, f"id inválido {malo!r}")
    except originales.OriginalNoDisponible:
        ok(True, f"id inválido {malo!r}: no disponible")
originales.olvidar_todo()
ok(originales.hay_originales() == 0, "olvidar_todo vacía la memoria")
import extractor, inspect  # noqa: E402
fuente = inspect.getsource(originales)
ok("open(" not in fuente.replace("pdfplumber.open", "") and "write" not in fuente.replace("sys.stdout", ""),
   "originales.py no abre ni escribe archivos (solo memoria)")

# ══════════════════════════════════════════════════════════════════════════
print("2. Dibujo del recorte")
# ══════════════════════════════════════════════════════════════════════════
pdf = pdf_con_texto(2)
ident = originales.guardar(pdf)
recuadro = (0.10, 0.10, 0.60, 0.20)
completa = Image.open(io.BytesIO(originales.renderizar(ident, 1, recuadro, "pagina")))
recorte = Image.open(io.BytesIO(originales.renderizar(ident, 1, recuadro, "recorte")))
ok(recorte.height < completa.height * 0.3 and recorte.width / recorte.height > 2 * completa.width / completa.height, f"el recorte es solo la zona de la pregunta ({recorte.size} vs página {completa.size})")
ok(completa.height > completa.width, "la página completa conserva su proporción vertical")
azul = lambda im: sum(1 for px in im.convert("RGB").getdata() if px[2] > 200 and px[0] < 80)
ok(azul(recorte) > 50 and azul(completa) > 50, "el recuadro de la pregunta sale resaltado (azul) en ambos")
sin_recuadro = Image.open(io.BytesIO(originales.renderizar(ident, 2, None, "recorte")))
ok(sin_recuadro.size == completa.size and azul(sin_recuadro) == 0, "sin recuadro (dos columnas, escaneado…): página completa y sin resalte")
grande = Image.open(io.BytesIO(originales.renderizar(ident, 1, recuadro, "recorte", zoom=3.0)))
ok(grande.width <= originales.ANCHO_MAX_PX, "el zoom nunca pasa del ancho máximo")
for malo in (0, 3, -1):
    try:
        originales.renderizar(ident, malo)
        ok(False, f"página {malo} fuera del documento")
    except IndexError:
        ok(True, f"página {malo} fuera del documento: IndexError")
ok(originales.parsear_recuadro("0.1,0.1,0.6,0.2") == (0.1, 0.1, 0.6, 0.2), "recuadro válido")
ok(all(originales.parsear_recuadro(x) is None for x in (None, "", "a,b,c,d", "0.1,0.1,0.6", "0.6,0.1,0.1,0.2", "-1,0,1,1", "0,0,2,1", "0.1,0.1,0.1,0.1")),
   "recuadros inválidos o vacíos: None")

# ══════════════════════════════════════════════════════════════════════════
print("3. Ruta /api/original/{id}/pagina/{n}")
# ══════════════════════════════════════════════════════════════════════════
r = c.get(f"/api/original/{ident}/pagina/1", headers=H)
ok(r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content.startswith(PNG), "200 con un PNG")
ok(r.headers.get("cache-control") == "no-store", "sin caché del navegador")
r = c.get(f"/api/original/{ident}/pagina/1?vista=pagina&recuadro=0.1,0.1,0.6,0.2&zoom=2", headers=H)
ok(r.status_code == 200 and Image.open(io.BytesIO(r.content)).width > completa.width, "vista de página completa con zoom y recuadro")
r = c.get("/api/original/" + "0" * 32 + "/pagina/1", headers=H)
ok(r.status_code == 404 and "ya no está disponible" in r.json()["detail"] and "Historial" in r.json()["detail"], "id desconocido: 404 con el motivo")
r = c.get(f"/api/original/{ident}/pagina/9", headers=H)
ok(r.status_code == 404 and "no existe" in r.json()["detail"], "página inexistente: 404")
ok(c.get(f"/api/original/{ident}/pagina/1?vista=otra", headers=H).status_code == 422, "vista inválida: 422")
ok(c.get(f"/api/original/{ident}/pagina/1?zoom=9", headers=H).status_code == 422, "zoom fuera de rango: 422")
ok(c.get(f"/api/original/{ident}/pagina/1?recuadro=" + "9" * 200, headers=H).status_code == 422, "recuadro demasiado largo: 422")
ok(c.get(f"/api/original/{ident}/pagina/1?recuadro=basura", headers=H).status_code == 200, "recuadro ilegible: se ignora y sale la página (no rompe)")
ok(c.get(f"/api/original/{ident}/pagina/1").status_code == 401, "sin token: 401")
roto = originales.guardar(b"%PDF-esto no es un pdf")
ok(c.get(f"/api/original/{roto}/pagina/1", headers=H).status_code == 422, "un PDF dañado: 422 con mensaje, no 500")

# ══════════════════════════════════════════════════════════════════════════
print("4. De punta a punta: el original va a memoria, nunca al historial")
# ══════════════════════════════════════════════════════════════════════════
_extract = pipeline.extract_structured
_modo = pipeline.NORMALIZER_MODE
_claves = (pipeline.get_api_key, ia_gemini.get_api_key)
# Sin clave real (en el CI no hay ninguna): _comprobar_entrada pregunta al proveedor si está listo.
pipeline.get_api_key = ia_gemini.get_api_key = lambda: "clave-falsa"
pipeline.NORMALIZER_MODE = "json"
payload = xf.perfect_model(exams.BASE_MIXED)
pipeline.extract_structured = lambda *a, **k: copy.deepcopy(payload)
SINT = ROOT / "samples" / "synthetic"
try:
    originales.olvidar_todo()
    res = pipeline.parse_document((SINT / "s01_limpio_clave_final.pdf").read_bytes(), "s01.pdf")
    oid = res.get("original_id")
    ok(oid and originales.obtener(oid) == (SINT / "s01_limpio_clave_final.pdf").read_bytes(), "un PDF devuelve `original_id` y queda en memoria")
    p1 = next(q["data"]["page"] for q in res["questions"] if q["data"].get("page"))
    rimg = c.get(f"/api/original/{oid}/pagina/{p1}", headers=H)
    ok(rimg.status_code == 200, "y su página se puede pedir con ese id")
    ok(res["escaneado"] is False, "un PDF con texto no es «escaneado»")
    txt = pipeline.parse_document(("Examen de prueba para el curso de ciencias naturales. Instrucciones: marque una sola respuesta.\n\n"
                                   "1. ¿Cuál es el planeta más grande del sistema solar?\nA. Marte\nB. Júpiter\nC. Venus\nD. Mercurio\n\n"
                                   "RESPUESTAS\n1. B\n").encode(), "x.txt")
    ok("original_id" not in txt, "un TXT no tiene original que mostrar (sin `original_id`)")
    # Nada del examen en la base de datos del historial
    with closing(sqlite3.connect(DB_DIR / "exams_history.db")) as con:
        tablas = [t[0] for t in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        filas = sum(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tablas)
    ok(filas == 0, "convertir no escribe nada en el historial")
    # ni en disco: ningún archivo nuevo con el PDF bajo el directorio temporal de esta prueba
    escritos = [p for p in TMP.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"]
    ok(not escritos, "ni se copia el PDF a ningún archivo")

    # ══════════════════════════════════════════════════════════════════════
    print("5. Escaneados: «ia» → confianza baja y aviso")
    # ══════════════════════════════════════════════════════════════════════
    pipeline.NORMALIZER_MODE_AI, _m_ai = "json", pipeline.NORMALIZER_MODE_AI
    try:
        esc = pipeline.normalize_document_with_ai(pdf_escaneado(), "escaneo.pdf")
        normal = pipeline.normalize_document_with_ai((SINT / "s01_limpio_clave_final.pdf").read_bytes(), "s01.pdf")
    finally:
        pipeline.NORMALIZER_MODE_AI = _m_ai
    con_resp = [q for q in esc["questions"] if q["data"].get("origen_respuesta")]
    ok(esc["escaneado"] is True and con_resp, "un PDF sin capa de texto sale marcado como escaneado")
    ia = [q for q in con_resp if q["data"]["origen_respuesta"] == "ia"]
    ok(ia and all(q["data"]["confianza"] == "baja" for q in ia), f"todas las respuestas de origen «ia» salen con confianza baja ({len(ia)})")
    ok(esc.get("color_marks_notice", "").startswith("Escaneado: verifica cada respuesta contra el original"), "y el aviso dice «Escaneado: verifica cada respuesta contra el original»")
    ok(normal["escaneado"] is False and any(q["data"].get("confianza") == "media" for q in normal["questions"]),
       "un PDF con texto leído con IA (no escaneado) conserva «media»")
    ok(confianza.evaluar({"num": 1, "type": "multichoice", "data": {"stem": "x", "options": {"A": "u", "B": "d"}}},
                         {"type": "multichoice", "answer": "u"}, {"escaneado": True}) == ("ia", "baja"), "confianza.evaluar: escaneado + ia → baja")
    ok(confianza.evaluar({"num": 1, "type": "multichoice", "data": {"stem": "x", "options": {"A": "u", "B": "d"}}},
                         {"type": "multichoice", "answer": "u", "from_key": True}, {"escaneado": True}) == ("documento", "alta"),
       "escaneado no baja lo que el código resolvió desde la clave del documento")
finally:
    pipeline.extract_structured = _extract
    pipeline.NORMALIZER_MODE = _modo
    pipeline.get_api_key, ia_gemini.get_api_key = _claves
    originales.olvidar_todo()

print()
print("TODO OK" if not fallas else f"{fallas} FALLA(S)")
sys.exit(1 if fallas else 0)
