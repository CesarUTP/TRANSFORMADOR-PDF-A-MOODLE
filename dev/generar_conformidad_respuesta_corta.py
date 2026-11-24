"""
generar_conformidad_respuesta_corta.py — XML de PRUEBA (respuesta corta con caracteres difíciles) para Moodle real.

    PYTHONUTF8=1 backend/venv/bin/python dev/generar_conformidad_respuesta_corta.py

Escribe dev/conformidad_moodle/respuesta_corta_moodle.xml. Desde la 2.9 la respuesta de una respuesta corta se
escribe como texto plano, sin escapes HTML (antes «O'Higgins» salía como «O&#x27;Higgins» y no coincidía con lo que
escribía el estudiante). Las pruebas automáticas comprueban el XML; esto es para confirmar en un Moodle REAL que
la respuesta se acepta. Ver dev/conformidad_moodle/LEEME.md.
"""

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
logging.disable(logging.CRITICAL)
from xml_builder import build_xml  # noqa: E402

CASOS = [
    ("O'Higgins", "P01 · ¿Cómo se apellidaba el libertador chileno Bernardo?"),
    ("AT&T", "P02 · ¿Cómo se llama la compañía telefónica estadounidense fundada por Bell?"),
    ("Panamá", "P03 · ¿Cuál es la capital de la República de Panamá? (con y sin tilde)"),
    ("pingüino", "P04 · Ave que no vuela y vive en la Antártida (con y sin diéresis)"),
    ('dijo "hola"', "P05 · Escribe exactamente: dijo \"hola\" (con comillas)"),
    ("x < y", "P06 · Escribe exactamente: x < y"),
]


def main() -> int:
    qs = [{"num": i, "type": "shortanswer", "data": {"stem": enunciado}} for i, (_, enunciado) in enumerate(CASOS, 1)]
    ak = {i: {"type": "shortanswer", "answer": r} for i, (r, _) in enumerate(CASOS, 1)}
    xml, _ = build_xml(qs, ak, category="PRUEBA-respuesta-corta (borrar)")
    destino = ROOT / "dev" / "conformidad_moodle" / "respuesta_corta_moodle.xml"
    destino.write_text(xml, encoding="utf-8")
    print(f"{len(qs)} preguntas → {destino.relative_to(ROOT)} ({len(xml)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
