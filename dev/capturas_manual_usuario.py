"""
capturas_manual_usuario.py — toma las capturas de pantalla del Manual de usuario de Cátedra.

    # 1) la aplicación de demostración (datos inventados, base temporal, sin Gemini):
    (cd backend && venv/bin/python ../dev/servidor_demo_manual.py) &
    # 2) las capturas (necesita Playwright; no forma parte del proyecto, se instala aparte y usa tu Chrome):
    python3 -m venv /tmp/pw-venv && /tmp/pw-venv/bin/pip install playwright
    /tmp/pw-venv/bin/python dev/capturas_manual_usuario.py

Deja los PNG en docs/manual-usuario/fuente/capturas/. Cada captura lleva números ámbar sobre los elementos de los que
habla el manual (se dibujan sobre la página, no son parte de la aplicación). Las capturas SE GUARDAN en el repositorio
para que el manual se pueda regenerar sin Playwright (dev/generar_manual_usuario.py).
"""

import io
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

try:
    from PIL import Image
except ImportError:  # sin Pillow se guardan tal cual
    Image = None

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "docs" / "manual-usuario" / "fuente" / "capturas"
# CAPTURAS_LIMPIAS=<carpeta>: las mismas capturas SIN los números ámbar y en otra carpeta (las usan las publicaciones de redes).
if os.environ.get("CAPTURAS_LIMPIAS"):
    SALIDA = Path(os.environ["CAPTURAS_LIMPIAS"]).resolve()
SIN_MARCAS = bool(os.environ.get("CAPTURAS_LIMPIAS"))
URL = "http://127.0.0.1:8794/#t=prueba-local"
ANCHO, ALTO, ESCALA = 1280, 800, 1.5

PDF_MINIMO = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
              b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
              b"4 0 obj<</Length 74>>stream\nBT /F1 14 Tf 72 700 Td (Parcial 1 de Geografia: ejemplo) Tj ET\nendstream\nendobj\n"
              b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R/Size 6>>\n%%EOF\n")

JS_MARCA = """([sel, n, esquina, dx, dy]) => {
  const el = document.querySelector(sel);
  if (!el) return false;
  const r = el.getBoundingClientRect();
  if (!r.width && !r.height) return false;
  const m = document.createElement('div');
  m.className = '__marca';
  m.textContent = String(n);
  const x = esquina === 'der' ? r.right - 4 : esquina === 'centro' ? r.left + r.width / 2 - 13 : r.left - 10;
  const y = esquina === 'abajo' ? r.bottom - 8 : r.top - 10;
  m.style.cssText = `position:fixed;z-index:99999;left:${x + (dx || 0)}px;top:${y + (dy || 0)}px;width:26px;height:26px;border-radius:50%;
    background:#fbbf24;color:#1e3a5f;font:800 14px/26px Outfit,system-ui,sans-serif;text-align:center;border:2px solid #1e3a5f;pointer-events:none;`;
  document.body.appendChild(m);
  return true;
}"""


def guardar_png(datos: bytes, nombre: str) -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    ruta = SALIDA / nombre
    if Image is not None:
        Image.open(io.BytesIO(datos)).convert("RGB").save(ruta, "PNG", optimize=True)
    else:
        ruta.write_bytes(datos)
    print("  ", nombre)


class Capturador:
    def __init__(self, page):
        self.p = page

    def esperar(self, ms=450):
        self.p.wait_for_timeout(ms)

    def marcas(self, lista):
        """lista: [(selector, número, esquina='izq', dx=0, dy=0)]. Quita las marcas viejas antes."""
        self.p.evaluate("document.querySelectorAll('.__marca').forEach(m => m.remove())")
        if SIN_MARCAS:
            return
        for item in lista:
            sel, n = item[0], item[1]
            esquina = item[2] if len(item) > 2 else "izq"
            dx = item[3] if len(item) > 3 else 0
            dy = item[4] if len(item) > 4 else 0
            if not self.p.evaluate(JS_MARCA, [sel, n, esquina, dx, dy]):
                print(f"   (aviso: no encontré {sel} para la marca {n})")

    def foto(self, nombre, marcas=(), elemento=None, completa=False, clip=None):
        self.marcas(list(marcas))
        self.esperar(250)
        if elemento:
            datos = self.p.locator(elemento).first.screenshot()
        else:
            datos = self.p.screenshot(full_page=completa, clip=clip)
        guardar_png(datos, nombre)
        self.p.evaluate("document.querySelectorAll('.__marca').forEach(m => m.remove())")

    def alrededor(self, selector, izq=20, arriba=20, ancho=1000, alto=300):
        """Un recorte (en píxeles de la ventana) con la esquina a `izq`/`arriba` del elemento."""
        bb = self.p.locator(selector).first.bounding_box()
        return {"x": max(0, bb["x"] - izq), "y": max(0, bb["y"] - arriba), "width": ancho, "height": alto}

    def ocultar_robot(self, ocultar=True):
        self.p.evaluate(f"(() => {{ const a = document.getElementById('asistente'); if (a) a.style.display = '{'none' if ocultar else ''}'; }})()")


def abrir_examen(page, c, materia, archivo):
    """Mis materias → una materia → «Reabrir» un examen: deja la revisión en pantalla."""
    page.click("#btn-materias")
    page.wait_for_selector(".vm-tarjetas")
    page.locator(".vm-tarjeta-boton", has_text=materia).first.click()
    page.wait_for_selector(".vm-fila")
    page.locator(".vm-fila", has_text=archivo).first.locator("[data-accion='reabrirExamen']").click()
    page.wait_for_selector("#panel-editor", state="visible")
    c.esperar(1800)
    c.ocultar_robot()
    page.evaluate("window.scrollTo(0,0)")


def recargar(page, c):
    page.goto(URL)
    page.reload()
    page.wait_for_selector("#drop-zone")
    c.esperar(1200)
    c.ocultar_robot()


def main() -> None:
    id_original = Path("/tmp/catedra_demo_original_id.txt").read_text(encoding="utf-8").strip()
    with sync_playwright() as pw:
        navegador = pw.chromium.launch(channel="chrome", headless=True)
        contexto = navegador.new_context(viewport={"width": ANCHO, "height": ALTO}, device_scale_factor=ESCALA, locale="es-PA", color_scheme="light")
        page = contexto.new_page()
        page.on("pageerror", lambda e: print("   ERROR de la página:", e))
        c = Capturador(page)
        page.goto(URL)
        page.wait_for_selector("#drop-zone")
        c.esperar(1200)

        print("1. Cargar y configurar")
        c.ocultar_robot()
        c.foto("01-cargar.png", clip={"x": 130, "y": 0, "width": 1020, "height": 700}, marcas=[("#drop-zone", 1, "izq", 6, 6), ("#category-input", 2), ("#points-input", 3), ("#materia-select", 4), ("#actividad-input", 5)])
        page.set_input_files("#file-input", {"name": "Parcial 1 de Geografía.pdf", "mimeType": "application/pdf", "buffer": PDF_MINIMO})
        c.esperar(900)
        page.evaluate("document.getElementById('btn-convert').scrollIntoView({block:'center'})")
        c.esperar(300)
        c.foto("02-convertir.png", clip={"x": 130, "y": 40, "width": 1020, "height": 640}, marcas=[("#file-name", 1, "izq", -4, -2), ("#btn-convert", 2)])

        print("2. Revisión")
        recargar(page, c)
        abrir_examen(page, c, "Geografía", "parcial1_geografia.pdf")
        c.esperar(3500)  # que se vaya el aviso «Revisión reabierta»
        c.foto("03-revision.png", clip={"x": 100, "y": 60, "width": 1140, "height": 720}, marcas=[("[data-accion='toggleFilterMenu']", 1), ("[data-accion='togglePointsToolMenu']", 2), ("[data-accion='alternarTodas']", 3),
                                   (".editor-card:nth-of-type(3) .proc-chip", 4), ("#review-rail", 5), ("[data-accion='generateXml']", 6)])
        # el filtro «Mostrar»
        page.click("[data-accion='toggleFilterMenu']")
        c.esperar(500)
        c.foto("04-filtro.png", clip=c.alrededor("[data-accion='toggleFilterMenu']", 20, 70, 1000, 300))
        page.click("[data-accion='toggleFilterMenu']")
        # reparto de puntos
        page.click("[data-accion='togglePointsToolMenu']")
        c.esperar(500)
        c.foto("05-puntos.png", clip=c.alrededor("[data-accion='togglePointsToolMenu']", 400, 70, 1000, 430))
        page.click("[data-accion='togglePointsToolMenu']")
        # pregunta sin respuesta: «Sugerir respuesta con IA»
        tarjeta4 = page.locator(".editor-card").nth(3)
        tarjeta4.scroll_into_view_if_needed()
        c.esperar(400)
        if not tarjeta4.locator("[data-accion='sugerirRespuesta']").first.is_visible():
            tarjeta4.locator("[data-accion='alternarTarjeta']").first.click()
            c.esperar(700)
        c.foto("06-sin-respuesta.png", [(".editor-card:nth-of-type(4) [data-accion='sugerirRespuesta']", 1)], elemento=".editor-card:nth-of-type(4)")

        print("3. Revisar con el original (PDF de ejemplo en la memoria de la app)")
        page.evaluate("""async (id) => {
          const { apiFetch } = await import('/js/api.js');
          const { abrirEnEditor } = await import('/js/borrador.js');
          const lista = await (await apiFetch('/api/history')).json();
          const f = lista.find(x => x.filename === 'parcial1_geografia.pdf');
          const d = await (await apiFetch(`/api/history/${f.id}/editor`)).json();
          abrirEnEditor({ filename: d.filename, category: d.category, total_points: d.total_points }, { questions: d.questions, answer_key: d.answer_key, original_id: id });
        }""", id_original)
        c.esperar(1800)
        c.ocultar_robot()
        page.locator(".editor-card").nth(2).scroll_into_view_if_needed()
        c.esperar(500)
        page.locator(".editor-card").nth(2).locator("button.proc-chip, .proc-boton").first.click()
        page.wait_for_selector("#modal-original.open")
        c.esperar(2500)
        c.foto("07-original.png", elemento="#modal-original .modal-box")
        page.keyboard.press("Escape")
        c.esperar(400)

        print("4. Final y exportar")
        recargar(page, c)
        abrir_examen(page, c, "Cálculo", "quiz2_integrales.pdf")
        page.click("#btn-generate-xml")
        page.wait_for_selector("#panel-success", state="visible")
        c.esperar(2200)
        c.ocultar_robot()
        page.evaluate("window.scrollTo(0,0)")
        c.foto("08-final.png", clip={"x": 130, "y": 0, "width": 1020, "height": 790}, marcas=[("#btn-download", 1), ("#btn-exportar-pdf", 2), ("#btn-back-to-review", 3), ("#exito-materia-sel", 4)])
        page.set_viewport_size({"width": 1100, "height": 800})
        page.click("#btn-exportar-pdf")
        page.wait_for_selector("#vista-pdf.open")
        c.esperar(3000)
        c.ocultar_robot()
        c.foto("09-pdf.png", [("#pdf-perfil", 1, "der", 0, -14), ("#pdf-datos-examen", 2, "der", 0, -4), ("#pdf-grupo-incluir", 3, "der", 0, -4), ("#pdf-previa .pdf-vista-marco", 4, "izq", 6, 6), ("#pdf-pts-panel", 5, "der", 0, -6)])
        page.evaluate("document.getElementById('pdf-sec-encabezado').open = true; document.getElementById('pdf-sec-formato').open = true")
        page.evaluate("document.getElementById('pdf-sec-encabezado').scrollIntoView({block:'start'})")
        c.esperar(500)
        c.foto("10-pdf-formato.png", [("#pdf-sec-encabezado", 1), ("#pdf-sec-formato", 2)])
        page.keyboard.press("Escape")
        c.esperar(500)
        page.set_viewport_size({"width": ANCHO, "height": ALTO})

        print("5. Versiones")
        recargar(page, c)
        page.set_viewport_size({"width": 1100, "height": 1000})
        page.click("#btn-materias")
        page.wait_for_selector(".vm-tarjetas")
        page.locator(".vm-tarjeta-boton", has_text="Geografía").first.click()
        page.wait_for_selector(".vm-fila")
        page.locator(".vm-fila", has_text="banco_geografia.docx").first.locator("[data-accion='exportarPdfHistorial']").click()
        page.wait_for_selector("#vista-pdf.open")
        c.esperar(2500)
        c.ocultar_robot()
        page.click("#pdf-ver-activar")
        c.esperar(400)
        page.fill("#pdf-ver-n", "4")
        page.click("input[name=ver_modo][value=por_tipo]")
        c.esperar(500)
        for tipo, cuota in (("multichoice", "5"), ("matching", "5"), ("truefalse", "5")):
            page.fill(f"#pdf-ver-tipos input[data-tipo={tipo}]", cuota)
        c.esperar(500)
        page.evaluate("document.getElementById('pdf-versiones').scrollIntoView({block:'start'})")
        c.esperar(400)
        c.foto("11-versiones-plan.png", [("#pdf-ver-activar", 1), ("#pdf-ver-n", 2), ("input[name=ver_modo][value=por_tipo]", 3), ("#pdf-ver-tipos", 4, "der", 0, -8), ("#pdf-ver-sin-repetir", 5), ("#btn-pdf-ver-sortear", 6)])
        page.click("#btn-pdf-ver-sortear")
        c.esperar(3000)
        page.click("#btn-pdf-ver-ajustar-todas")
        c.esperar(2500)
        page.evaluate("document.getElementById('pdf-previa').scrollTop = 0")
        c.foto("12-versiones-revision.png", [("#pdf-ver-tabs .ver-tab", 1), ("#pdf-ver-objetivo", 2), ("#btn-pdf-ver-ajustar-todas", 3), ("#pdf-ver-detalle", 4)])
        page.set_viewport_size({"width": ANCHO, "height": ALTO})
        page.keyboard.press("Escape")
        c.esperar(400)

        print("6. Mis materias, Mi perfil, Guía, Acerca de, clave")
        recargar(page, c)
        page.click("#btn-materias")
        page.wait_for_selector(".vm-tarjetas")
        c.esperar(600)
        c.foto("13-mis-materias.png", clip={"x": 0, "y": 0, "width": ANCHO, "height": 470}, marcas=[(".vm-tarjetas li:nth-child(1) .vm-tarjeta-boton", 1, "izq", 6, 6), ("[data-accion='nuevaMateria']", 2), (".vm-aviso, .vm-ordenar", 3)])
        page.locator(".vm-tarjeta-boton", has_text="Geografía").first.click()
        page.wait_for_selector(".vm-fila")
        c.esperar(600)
        c.foto("14-materia.png", clip={"x": 0, "y": 0, "width": ANCHO, "height": 420}, marcas=[(".vm-buscar input", 1), (".vm-fila:nth-child(1) .vm-casilla", 2), ("[data-accion='reabrirExamen']", 3), ("[data-accion='exportarPdfHistorial']", 4), ("[data-accion='descargarExamen']", 5), ("[data-accion='organizarExamen']", 6), ("[data-accion='nuevoExamenEnMateria']", 7)])
        page.locator(".vm-fila").nth(1).locator("[data-accion='organizarExamen']").first.click()
        c.esperar(500)
        c.foto("15-organizar.png", clip={"x": 0, "y": 0, "width": ANCHO, "height": 560})
        page.keyboard.press("Escape"); page.keyboard.press("Escape")
        c.esperar(400)
        page.click("#btn-perfil")
        page.wait_for_selector("#vista-perfil.open")
        c.esperar(900)
        c.foto("16-mi-perfil.png", [("#vp-nombre", 1), ("#vp-rotulo", 2), ("[data-accion='nuevoPerfilEnc']", 3), ("#vp-perfiles .vp-perfil", 4)])
        page.locator("[data-accion='editarPerfilEnc']").first.click()
        c.esperar(1800)
        c.foto("17-perfil-editor.png", elemento="#modal-perfil-enc .modal-box")
        page.keyboard.press("Escape"); c.esperar(300); page.keyboard.press("Escape"); c.esperar(400)
        page.click("#btn-help")
        c.esperar(800)
        c.foto("18-guia.png", elemento="#modal-help .modal-box")
        page.keyboard.press("Escape"); c.esperar(300)
        page.click("#btn-acerca")
        c.esperar(1200)
        c.foto("19-acerca.png", [("#btn-acerca-api", 1)], elemento="#modal-acerca .modal-box")
        page.click("#btn-acerca-api")
        c.esperar(800)
        c.foto("20-clave.png", elemento="#modal-apikey .modal-box")

        print("7. El robot ayudante")
        page.evaluate("localStorage.removeItem('conversor.tours'); sessionStorage.clear();")
        page.goto(URL)
        page.reload()
        page.wait_for_selector("#drop-zone")
        c.ocultar_robot(False)
        c.esperar(6500)
        page.mouse.move(60, 740)
        c.esperar(1800)
        c.foto("21-robot.png", clip={"x": 0, "y": 470, "width": 560, "height": 330})
        page.get_by_role("button", name="Sí, enséñame").click()
        c.esperar(1800)
        c.foto("22-recorrido.png", clip={"x": 100, "y": 60, "width": 1080, "height": 440})

        print("8. Bienvenida (sin clave)")
        page.evaluate("""async () => { const { apiFetch } = await import('/js/api.js'); await apiFetch('/api/api-key', { method: 'DELETE' }); }""")
        page.reload()
        c.esperar(1800)
        page.wait_for_selector("#modal-apikey.open")
        c.foto("23-bienvenida.png", elemento="#modal-apikey .modal-box")
        navegador.close()


if __name__ == "__main__":
    main()
