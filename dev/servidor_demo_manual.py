"""
servidor_demo_manual.py — Cátedra con datos INVENTADOS, para tomar las capturas del manual de usuario.

    backend/venv/bin/python dev/servidor_demo_manual.py            # http://127.0.0.1:8794/#t=prueba-local

Usa una base de datos y una carpeta de usuario TEMPORALES (nunca toca tu Historial, tu perfil ni tu clave) y llena
la aplicación con una persona, tres materias, un perfil de encabezado y unos exámenes de ejemplo. No llama a Gemini.
Lo usa dev/capturas_manual_usuario.py.
"""

import json
import logging
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "backend"), str(RAIZ / "dev")]
TMP = Path(tempfile.mkdtemp(prefix="catedra demo manual "))
os.environ["HOME"] = str(TMP / "home")
os.environ["LOCALAPPDATA"] = str(TMP / "home" / "AppData")
os.environ["CONVERSOR_TOKEN"] = "prueba-local"
# Nunca la clave de nadie: si el entorno ya trae la variable (aunque vacía), el .env de desarrollo NO se lee.
os.environ["GEMINI_API_KEY"] = ""

import database  # noqa: E402

(TMP / "data").mkdir()
database.get_db_path = lambda: TMP / "data" / "exams_history.db"  # ANTES de importar main
logging.disable(logging.CRITICAL)
database.init_db()

PUERTO = int(os.environ.get("PUERTO_DEMO", "8794"))

TEMAS = ["ríos de Panamá", "el Canal", "clima tropical", "población", "relieve", "costas", "provincias", "recursos hídricos"]


def examen(n: int, prefijo: str, tipos=("multichoice", "truefalse", "matching")):
    """Un examen inventado de `n` preguntas: [(preguntas, clave)]."""
    qs, clave = [], {}
    for i in range(1, n + 1):
        tema = TEMAS[i % len(TEMAS)]
        t = tipos[(i - 1) % len(tipos)]
        if t == "multichoice":
            qs.append({"num": i, "type": "multichoice", "points": 2,
                       "data": {"stem": f"{prefijo}: ¿Cuál de estas afirmaciones sobre {tema} es correcta?",
                                "options": {"A": f"Primera idea sobre {tema}", "B": f"Segunda idea sobre {tema}",
                                            "C": f"Tercera idea sobre {tema}", "D": f"Cuarta idea sobre {tema}"}}})
            clave[str(i)] = {"type": "multichoice", "answer": "ABCD"[i % 4]}
        elif t == "truefalse":
            qs.append({"num": i, "type": "truefalse", "points": 1, "data": {"stem": f"{prefijo}: {tema.capitalize()} se estudia en la unidad {i % 5 + 1}."}})
            clave[str(i)] = {"type": "truefalse", "answer": "Verdadero" if i % 2 else "Falso"}
        else:
            qs.append({"num": i, "type": "matching", "points": 3,
                       "data": {"stem": f"{prefijo}: relaciona cada concepto de {tema} con su definición",
                                "col_a": {"1": f"Concepto {i}A", "2": f"Concepto {i}B"}, "col_b": {"a": f"Definición {i}a", "b": f"Definición {i}b"}}})
            clave[str(i)] = {"type": "matching", "answer": "1-b; 2-a", "pairs": {"1": "b", "2": "a"}}
    return qs, clave


def con_procedencia(qs, clave):
    """Un examen «leído de un PDF»: con página, origen y confianza de cada respuesta, y una pregunta sin respuesta."""
    for q in qs:
        i = q["num"]
        q["data"]["page"] = (i - 1) // 5 + 1
        fila = (i - 1) % 5
        q["data"]["recuadro"] = [0.09, round((95 + fila * 135) / 792, 4), 0.91, round((95 + fila * 135 + 118) / 792, 4)]
        if i % 7 == 0:
            q["data"]["origen_respuesta"], q["data"]["confianza"] = "ia", "media"
    qs[2]["data"]["origen_respuesta"], qs[2]["data"]["confianza"] = "ia", "baja"
    clave["4"] = {"type": "multichoice", "answer": "SIN_RESPUESTA"}
    return qs, clave


def guardar(nombre, categoria, total, materia_id, actividad, n, prefijo, rico=False):
    qs, clave = examen(n, prefijo)
    if rico:
        qs, clave = con_procedencia(qs, clave)
    editor = json.dumps({"questions": qs, "answer_key": clave}, ensure_ascii=False)
    database.save_conversion(nombre, categoria, float(total), "<quiz/>", editor, materia_id, actividad)


def pdf_original(qs, clave) -> bytes:
    """El «examen original» del parcial 1 (cuatro páginas, cinco preguntas cada una), para la revisión lado a lado."""
    import io
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for pagina in range(4):
        c.setFont("Helvetica-Bold", 13)
        c.drawCentredString(306, 750, "Universidad Tecnológica de Panamá")
        c.setFont("Helvetica", 11)
        c.drawCentredString(306, 733, "Geografía de Panamá · Parcial 1 (ejemplo inventado)")
        for fila in range(5):
            q = qs[pagina * 5 + fila]
            arriba = 792 - (95 + fila * 135)
            c.setFont("Helvetica-Bold", 10.5)
            c.drawString(70, arriba - 14, f"{q['num']}. {q['data']['stem']}"[:95])
            c.setFont("Helvetica", 10)
            if q["type"] == "multichoice":
                for k, (letra, texto) in enumerate(q["data"]["options"].items()):
                    c.drawString(90, arriba - 36 - k * 18, f"{letra}) {texto}")
            elif q["type"] == "truefalse":
                c.drawString(90, arriba - 36, "Verdadero          Falso")
            else:
                for k, (n, texto) in enumerate(q["data"]["col_a"].items()):
                    c.drawString(90, arriba - 36 - k * 18, f"{n}. {texto}")
                for k, (letra, texto) in enumerate(q["data"]["col_b"].items()):
                    c.drawString(320, arriba - 36 - k * 18, f"{letra}) {texto}")
        c.showPage()
    c.save()
    return buf.getvalue()


# Una clave FALSA, guardada solo en la carpeta temporal, para que la aplicación se abra sin el paso de bienvenida
# (la comprobación con Google no se hace: no se llama a Gemini).
import credenciales  # noqa: E402

credenciales._escribir_archivo("AIzaSyDEMO-clave-falsa-para-capturas-0000")
credenciales._cargar()

database.set_ajustes({"nombre": "Ing. Ana Pérez", "rotulo_docente": "facilitador"})
database.save_perfil("UTP Panamá", json.dumps({
    "institucion": "Universidad Tecnológica de Panamá", "facultad": "Facultad de Ingeniería de Sistemas", "departamento": "Ingeniería de Software",
    "docente": "", "rotulo_docente": "facilitador", "instrucciones": "Toda respuesta dejada a lápiz no tiene derecho a reclamo.\nNo se permite ningún dispositivo electrónico.",
    "logo_izquierdo": "", "logo_derecho": "", "papel": "carta", "margenes": "moderados", "fuente_titulos": "dejavu", "tam_titulos": 11,
    "fuente_preguntas": "dejavu", "tam_preguntas": 10, "campos_estudiante": True, "partes": True, "mezclar": True, "puntos_por_pregunta": True,
    "renglones_ensayo": 6}))
database.set_ajustes({"perfil_predeterminado": "UTP Panamá"})
geo = database.create_materia("Geografía de Panamá", "verde", "UTP Panamá", "Ing. Ana Pérez", "1IL-131")
calc = database.create_materia("Cálculo II", "violeta", "UTP Panamá", "Ing. Ana Pérez", "2IS-11")
database.create_materia("Redes de computadoras", "turquesa", None, None, None)
guardar("banco_geografia.docx", "Banco-Geografia", 100, geo["id"], "Banco de preguntas", 60, "Geografía")
guardar("parcial1_geografia.pdf", "Parcial-1-Geografia", 100, geo["id"], "Parcial 1", 20, "Parcial 1", rico=True)
_qs_p1, _clave_p1 = con_procedencia(*examen(20, "Parcial 1"))
import originales  # noqa: E402
_id_original = originales.guardar(pdf_original(_qs_p1, _clave_p1))
Path(os.environ.get("ID_ORIGINAL_DEMO", "/tmp/catedra_demo_original_id.txt")).write_text(_id_original or "", encoding="utf-8")
guardar("quiz2_integrales.pdf", "Quiz-2-Calculo", 20, calc["id"], "Quiz 2", 10, "Quiz 2")
guardar("final_calculo.docx", "Final-Calculo", 100, calc["id"], "Examen final", 30, "Final")
guardar("examen_viejo.pdf", "mis-preguntas", 50, None, None, 8, "Examen")

if __name__ == "__main__":
    import uvicorn
    import main  # noqa: E402
    print(f"Cátedra de demostración en http://127.0.0.1:{PUERTO}/#t=prueba-local  (datos inventados en {TMP})", flush=True)
    uvicorn.run(main.app, host="127.0.0.1", port=PUERTO, log_level="warning")
