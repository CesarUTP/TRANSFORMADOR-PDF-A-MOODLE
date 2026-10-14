"""
pdf_regresion.py — comprueba que un refactor NO cambió ni un píxel de los PDF (2.8).

    PYTHONUTF8=1 backend/venv/bin/python dev/pdf_regresion.py --guardar DIR     # fija la línea base
    PYTHONUTF8=1 backend/venv/bin/python dev/pdf_regresion.py --comparar DIR    # la compara con el código actual

Genera los PDF de los 25 exámenes sintéticos con varias combinaciones de opciones (contenido, papel,
márgenes, tipos de letra, partes, mezclado, puntos, logos…), los dibuja con pypdfium2 y guarda un hash por
página. `--comparar` dice qué PDF cambió y en qué página. La línea base se guarda FUERA del repositorio
(los píxeles pueden variar de un equipo a otro: sirve para comparar antes y después EN LA MISMA máquina).
Sin red ni Gemini; no toca la base de datos ni la clave.
"""

import argparse
import base64
import hashlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "dev"))
sys.path.insert(0, str(ROOT / "dev" / "synthetic"))

import pypdfium2 as pdfium  # noqa: E402
from PIL import Image  # noqa: E402

import xml_fidelity as xf  # noqa: E402  (apaga el logging)
import test_xml_baseline as base  # noqa: E402
import exportar_pdf as ep  # noqa: E402
from schema_adapter import adapt  # noqa: E402
from validator import partition_questions  # noqa: E402

DATOS = dict(institucion="Universidad de Prueba", facultad="Facultad de Ingeniería", departamento="Departamento de Sistemas",
             materia="Materia de prueba", actividad="Parcial 1", docente="Docente de Prueba", grupo="1IL-131",
             fecha="13/10/2026", instrucciones="Lea con cuidado.\n- No se permite calculadora.\n- Tiempo: 90 minutos.", version="A")


def _logo() -> str:
    im = Image.new("RGB", (60, 40), (30, 90, 160))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


# nombre → opciones de DatosExamen (se suman a DATOS)
VARIANTES = {
    "examen_y_clave": {},
    "solo_examen": {"contenido": "solo_examen"},
    "solo_clave": {"contenido": "solo_clave"},
    "folleto": {"contenido": "folleto_hoja_clave"},
    "arial": {"fuente_titulos": "arial", "fuente_preguntas": "arial", "tam_titulos": 13, "tam_preguntas": 11},
    "times_a4": {"fuente_titulos": "times", "fuente_preguntas": "times", "papel": "a4", "margenes": "estrechos", "tam_preguntas": 12},
    "sin_partes_sin_mezcla": {"partes": False, "mezclar": False, "contenido": "folleto_hoja_clave"},
    "sin_puntos_sin_estudiante": {"puntos_por_pregunta": False, "campos_estudiante": False, "rotulo_docente": "profesor"},
    "legal_anchos_logos": {"papel": "legal", "margenes": "anchos", "logo_izquierdo": _logo(), "logo_derecho": _logo(), "renglones_ensayo": 10},
}


def _png(w, h, modo="RGB", color=(30, 90, 200)) -> str:
    b = io.BytesIO()
    Image.new(modo, (w, h), color).save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode()


def examen_extra() -> tuple:
    """Lo que los sintéticos no traen: imágenes (grande, con transparencia, dañada), fórmulas, emojis,
    un carácter que Arial no tiene, desarrollo, respuesta corta y numérica, y un «Completar» y un pareo con imágenes."""
    img = lambda n, b64: {"name": n, "mime": "image/png", "b64": b64}
    qs = [
        {"num": 1, "type": "multichoice", "data": {"stem": "Mira la imagen \\(x^2 + \\alpha \\leq 3\\) y responde 😀",
         "options": {"A": "Uno", "B": "Dos \\(\\frac{1}{2}\\)", "C": "Tres ∀x", "D": "Cuatro"},
         "images": [img("g.png", _png(1600, 900)), img("p.png", _png(40, 30, "RGBA", (255, 0, 0, 128))), img("x.png", "bm8gZXMgdW5hIGltYWdlbg==")]}},
        {"num": 2, "type": "multichoice", "data": {"stem": "Varias correctas",
         "options": {"A": "Todas las anteriores", "B": "Opción B", "C": "Opción C"}}},
        {"num": 3, "type": "truefalse", "data": {"stem": "La Tierra es plana", "images": [img("t.png", _png(300, 200))]}},
        {"num": 4, "type": "matching", "data": {"stem": "Une", "col_a": {"1": "Uno \\(\\sqrt{3}\\)", "2": "Dos", "3": "Tres", "4": "Cuatro"},
         "col_b": {"a": "Alfa", "b": "Beta", "c": "Gamma", "d": "Delta", "e": "Épsilon"}}},
        {"num": 5, "type": "cloze", "data": {"text": "El agua es [A: H₂O / CO₂ / NaCl] y hierve a [B: 100 / 90 / 120] grados; su símbolo es [C: H2O].",
         "images": [img("c.png", _png(200, 100))]}},
        {"num": 6, "type": "essay", "data": {"stem": "Desarrolla el tema " + "largo " * 40, "feedback": "Debe mencionar tres puntos."}},
        {"num": 7, "type": "shortanswer", "data": {"stem": "Capital de Panamá"}},
        {"num": 8, "type": "numerical", "data": {"stem": "Raíz de 9"}},
    ]
    key = {1: {"type": "multichoice", "answer": "B | C"}, 2: {"type": "multichoice", "answer": "A"},
           3: {"type": "truefalse", "answer": "Falso"},
           4: {"type": "matching", "answer": "1-a; 2-b; 3-c; 4-d", "pairs": {"1": "a", "2": "b", "3": "c", "4": "d"}},
           5: {"type": "cloze", "answer": "A. H₂O; B. 100; C. H2O"},
           6: {"type": "essay", "answer": ""}, 7: {"type": "shortanswer", "answer": "Panamá"}, 8: {"type": "numerical", "answer": "3"}}
    return qs, key


def generar() -> dict:
    salida = {}
    qs_x, key_x = examen_extra()
    for var, extra in VARIANTES.items():
        r = ep.generar_pdf(qs_x, key_x, 20, ep.DatosExamen(**{**DATOS, **extra}))
        salida[f"extra|{var}"] = r.pdf
    for nombre, qs in base.bancos().items():
        questions, key = adapt(xf.perfect_model(qs))
        validas, _ = partition_questions(questions, key)
        if not validas:
            continue
        for var, extra in VARIANTES.items():
            r = ep.generar_pdf(validas, key, 20, ep.DatosExamen(**{**DATOS, **extra}))
            salida[f"{nombre}|{var}"] = r.pdf
    return salida


def huellas(pdf: bytes) -> list:
    doc = pdfium.PdfDocument(pdf)
    out = []
    for i in range(len(doc)):
        im = doc[i].render(scale=0.7).to_pil().convert("L")
        out.append(hashlib.sha256(im.tobytes()).hexdigest()[:16])
    doc.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--guardar", metavar="DIR")
    g.add_argument("--comparar", metavar="DIR")
    args = ap.parse_args()
    pdfs = generar()
    ahora = {k: huellas(v) for k, v in pdfs.items()}
    if args.guardar:
        d = Path(args.guardar)
        (d / "pdf").mkdir(parents=True, exist_ok=True)
        for k, v in pdfs.items():
            (d / "pdf" / (k.replace("|", "__") + ".pdf")).write_bytes(v)
        (d / "huellas.json").write_text(json.dumps(ahora, indent=0, sort_keys=True), encoding="utf-8")
        print(f"Línea base: {len(ahora)} PDF, {sum(len(v) for v in ahora.values())} páginas, en {d}")
        return 0
    antes = json.loads((Path(args.comparar) / "huellas.json").read_text(encoding="utf-8"))
    distintos = []
    for k in sorted(set(antes) | set(ahora)):
        a, b = antes.get(k), ahora.get(k)
        if a != b:
            pag = "falta" if a is None or b is None else (f"{len(a)}→{len(b)} páginas" if len(a) != len(b) else
                  "págs " + ",".join(str(i + 1) for i, (x, y) in enumerate(zip(a, b)) if x != y))
            distintos.append(f"  {k}: {pag}")
    if distintos:
        print(f"FALLA: {len(distintos)} de {len(ahora)} PDF cambiaron")
        print("\n".join(distintos[:40]))
        return 1
    print(f"OK: los {len(ahora)} PDF ({sum(len(v) for v in ahora.values())} páginas) son idénticos píxel a píxel")
    return 0


if __name__ == "__main__":
    sys.exit(main())
