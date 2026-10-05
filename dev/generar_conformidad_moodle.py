"""
generar_conformidad_moodle.py — XML de PRUEBA para importar en un Moodle real.

    PYTHONUTF8=1 backend/venv/bin/python dev/generar_conformidad_moodle.py

Escribe dev/conformidad_moodle/conformidad_moodle.xml: una pregunta de cada tipo
y de cada rasgo que genera la app (incluidos los casos que rompieron la
importación en la 1.9). Las pruebas automáticas comprueban que el XML sea el que
creemos correcto; esto es para comprobar que MOODLE lo acepta y lo muestra bien.

Cómo usarlo (cuando se quiera confirmar en un Moodle real; no hace falta para
publicar): en un curso de pruebas, Banco de preguntas → Importar → «Formato XML de
Moodle», categoría nueva, y DEJAR «Detenerse en error = Sí» (lo normal): el archivo
debe importarse COMPLETO, las 10 preguntas. Luego abrir la vista previa de cada una:
dev/conformidad_moodle/LEEME.md dice qué debe verse.
"""

import base64
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)
from xml_builder import build_xml  # noqa: E402


def _png_rojo() -> str:
    """PNG de 24×24 rojo (sin dependencias), en base64."""
    def trozo(tipo, datos):
        c = struct.pack(">I", len(datos)) + tipo + datos
        return c + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)
    filas = b"".join(b"\x00" + b"\xd0\x20\x20" * 24 for _ in range(24))
    png = (b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", struct.pack(">IIBBBBB", 24, 24, 8, 2, 0, 0, 0))
           + trozo(b"IDAT", zlib.compress(filas)) + trozo(b"IEND", b""))
    return base64.b64encode(png).decode()


def preguntas():
    qs, ak = [], {}

    def add(tipo, data, clave, puntos=None):
        n = len(qs) + 1
        q = {"num": n, "type": tipo, "data": data}
        if puntos is not None:
            q["points"] = puntos
        qs.append(q)
        ak[n] = {"type": tipo, **clave}

    add("multichoice", {"stem": "P01 · ¿Cuál es la capital de Panamá?",
                        "options": {"A": "Colón", "B": "Ciudad de Panamá", "C": "David", "D": "Santiago"},
                        "feedback": "La capital es Ciudad de Panamá."},
        {"answer": "Ciudad de Panamá", "correct_idx": [1]})
    add("multichoice", {"stem": "P02 · Marca TODOS los lenguajes compilados.",
                        "options": {chr(65 + i): t for i, t in enumerate(["C", "Python", "Rust", "JavaScript", "Go", "Ruby"])}},
        {"answer": "C | Rust | Go", "correct_idx": [0, 2, 4]})
    # El caso que en la 1.9 hacía fallar la importación de TODO el archivo: 12 correctas y 13 incorrectas.
    ops = {chr(65 + i): f"Opción {i + 1}" for i in range(25)}
    add("multichoice", {"stem": "P03 · Marca las opciones 1 a 12 (12 correctas, 13 incorrectas).", "options": ops},
        {"answer": " | ".join(ops[chr(65 + i)] for i in range(12)), "correct_idx": list(range(12))})
    add("truefalse", {"stem": "P04 · El agua hierve a 100 °C a nivel del mar."}, {"answer": "Verdadero"})
    add("matching", {"stem": "P05 · Relaciona cada país con su capital.",
                     "col_a": {"1": "Perú", "2": "Chile", "3": "Colombia", "4": "Ecuador"},
                     "col_b": {"a": "Lima", "b": "Santiago", "c": "Bogotá", "d": "Quito"}},
        {"answer": "1-a; 2-b; 3-c; 4-d", "pairs": {"1": "a", "2": "b", "3": "c", "4": "d"}})
    opts_a = ["TCP/IP", "UDP", "10 / 2"]
    opts_b = ["dijo \"hola\"", "{llave}", "a~b", "c#d", "e}f", "g\\h", "R&D", "x < y"]
    add("cloze", {"text": "P06 · Elige [A: " + " / ".join(opts_a) + "] y luego [B: " + " / ".join(opts_b) + "]. Mide 2,5 puntos."},
        {"answer": "A. TCP/IP; B. a~b",
         "huecos": [{"letra": "A", "options": opts_a, "correct_idx": [0]},
                    {"letra": "B", "options": opts_b, "correct_idx": [2]}]}, puntos=2.5)
    add("shortanswer", {"stem": "P07 · ¿Cómo se llama el proceso por el que las plantas fabrican su alimento?"},
        {"answer": "Fotosíntesis"})
    add("numerical", {"stem": "P08 · ¿Cuánto es 15 × 4?"}, {"answer": "60"})
    add("essay", {"stem": "P09 · Explica con tus palabras las causas de la Primera Guerra Mundial."},
        {"answer": "respuesta abierta, se califica manualmente"})
    add("multichoice", {"stem": "P10 · Imagen y fórmula: la figura es un cuadrado rojo. Si x = 3, ¿cuánto es \\(x^2 + 1\\)? (a < b)",
                        "options": {"A": "6", "B": "10", "C": "9", "D": "12"},
                        "images": [{"name": "cuadrado_rojo.png", "mime": "image/png", "b64": _png_rojo()}],
                        "feedback": "Es \\(3^2 + 1 = 10\\)."},
        {"answer": "10", "correct_idx": [1]})
    return qs, ak


def main() -> int:
    qs, ak = preguntas()
    xml, stats = build_xml(qs, ak, category="PRUEBA-conformidad (borrar)")
    destino = ROOT / "dev" / "conformidad_moodle" / "conformidad_moodle.xml"
    destino.write_text(xml, encoding="utf-8")
    print(f"{len(qs)} preguntas → {destino.relative_to(ROOT)} ({len(xml)} bytes)")
    for a in stats.avisos:
        print("  aviso:", a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
