"""
test_xml_baseline.py — Red de seguridad de los refactores: el XML de Moodle
que sale de cada examen sintético NO debe cambiar si no se quiso cambiar.

    backend/venv/bin/python dev/test_xml_baseline.py              # compara con la línea base
    backend/venv/bin/python dev/test_xml_baseline.py --guardar    # fija una línea base NUEVA
    backend/venv/bin/python dev/test_xml_baseline.py --volcar DIR # escribe los XML para compararlos con diff

Usa el mismo camino que xml_fidelity.py y sin llamar a Gemini: la verdad de
cada examen (dev/synthetic/adversarial_bank.py y exams.py) se convierte en la
respuesta que daría una IA perfecta y pasa por schema_adapter.adapt →
validator.partition_questions → xml_builder.build_xml. De cada examen se guarda
el SHA-256 del XML completo, cuántas preguntas válidas y cuáles omitidas.

La línea base vive en dev/eval_results/xml_baseline.json (versionada). Si un
cambio MODIFICA el XML a propósito (p. ej. una corrección de fidelidad), este
test falla y dice qué exámenes cambiaron: revisa el diff con --volcar y, si es
lo esperado, vuelve a fijar con --guardar y explícalo en el commit.

Las funciones públicas adapt / partition_questions / build_xml deben seguir
aceptando los mismos datos mientras se refactoriza.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "dev"))
sys.path.insert(0, str(ROOT / "dev" / "synthetic"))

import xml_fidelity as xf  # noqa: E402  (apaga el logging: es lo que se quiere)
import exams  # noqa: E402
from schema_adapter import adapt  # noqa: E402
from validator import partition_questions  # noqa: E402
from xml_builder import build_xml  # noqa: E402

BASE = ROOT / "dev" / "eval_results" / "xml_baseline.json"


# Exámenes con opciones cuyo PROPIO texto contiene los separadores internos
# (« | » entre respuestas, « / » entre opciones de un hueco). Antes de las
# respuestas por índice (modelo.py) se partían mal. Entraron a la línea base con
# la versión 1.9 (las 23 anteriores no cambiaron).
SEP_OPCION_MULTIPLE = [
    {"type": "multichoice", "stem": "¿Qué operador hace una O bit a bit en C?",
     "options": ["x | y", "x & y", "x || y", "x ^ y"], "correct": [0]},
    {"type": "multichoice", "stem": "Selecciona las expresiones que contienen una O.",
     "options": ["a || b", "a && b", "a | b", "a + b"], "correct": [0, 2]},
    {"type": "multichoice", "stem": "¿Qué carácter une comandos en una tubería?",
     "options": ["|", "&", "^", "~"], "correct": [0]},
    {"type": "multichoice", "stem": "¿Cuál es la expresión completa?",
     "options": ["x | y", "x | y | z", "y"], "correct": [1]},
    {"type": "multichoice", "stem": "Selecciona las rutas válidas en Windows.",
     "options": ["C:\\ruta / otra", "C:\\ruta", "/usr/bin", "otra"], "correct": [0, 2]},
    {"type": "multichoice", "stem": "¿Cuánto es la división indicada?",
     "options": ["10 / 2", "5", "2 / 10", "20"], "correct": [0, 1]},
]
SEP_COMPLETAR = [
    {"type": "cloze", "text": "El resultado de {0} es cinco.",
     "blanks": [{"options": ["10 / 2", "5 / 1", "2"], "correct": [0]}]},
    {"type": "cloze", "text": "Para unir condiciones se usa {0} y la ruta es {1}.",
     "blanks": [{"options": ["a || b", "a | b", "a && b"], "correct": [1]},
                {"options": ["C:\\ruta / otra", "C:\\ruta"], "correct": [0]}]},
    {"type": "cloze", "text": "Las dos expresiones con una O son {0}.",
     "blanks": [{"options": ["x | y", "z | w", "q & r"], "correct": [0, 1]}]},
    {"type": "cloze", "text": "El texto con símbolos de Moodle es {0}.",
     "blanks": [{"options": ["a ~ b", "c } d", "e # f", "g"], "correct": [2]}]},
]


def bancos() -> dict:
    """{nombre: [preguntas]} de todos los bancos sintéticos, en orden estable."""
    out = dict(xf.load_exams())
    for nombre in ("BASE_MIXED", "COLOR_MC", "AFIRMACIONES", "ASTERISCO", "CLOZE",
                   "RESALTADO_MC", "NEGRITA_MC", "SUBRAYADO_MC"):
        if hasattr(exams, nombre):
            out["s_" + nombre.lower()] = getattr(exams, nombre)
    for n in (60, 150):
        out[f"s_largo_{n}"] = exams.long_exam(n)
    out["s_sep_opcion_multiple"] = SEP_OPCION_MULTIPLE
    out["s_sep_completar"] = SEP_COMPLETAR
    return out


def convertir(qs: list) -> tuple:
    questions, key = adapt(xf.perfect_model(qs))
    validas, omitidas = partition_questions(questions, key)
    xml, _stats = build_xml(validas, key)
    return xml, len(validas), sorted(int(q.get("num", 0)) for q in omitidas)


def huella(xml: str, validas: int, omitidas: list) -> dict:
    return {
        "sha256": hashlib.sha256(xml.encode("utf-8")).hexdigest(),
        "bytes": len(xml.encode("utf-8")),
        "validas": validas,
        "omitidas": omitidas,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--guardar", action="store_true", help="fija la línea base con el comportamiento actual")
    ap.add_argument("--volcar", metavar="DIR", help="escribe cada XML en DIR (para diff)")
    args = ap.parse_args()

    actual, xmls = {}, {}
    for nombre, qs in bancos().items():
        xml, validas, omitidas = convertir(qs)
        actual[nombre] = huella(xml, validas, omitidas)
        xmls[nombre] = xml

    if args.volcar:
        d = Path(args.volcar)
        d.mkdir(parents=True, exist_ok=True)
        for nombre, xml in xmls.items():
            (d / f"{nombre}.xml").write_text(xml, encoding="utf-8")
        print(f"XML escritos en {d} ({len(xmls)} archivos)")

    if args.guardar:
        BASE.write_text(json.dumps(actual, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Línea base guardada: {len(actual)} exámenes en {BASE.relative_to(ROOT)}")
        return 0

    if not BASE.exists():
        print(f"FALTA la línea base {BASE.relative_to(ROOT)}: corre con --guardar")
        return 1
    esperado = json.loads(BASE.read_text(encoding="utf-8"))

    fallas = 0
    for nombre in sorted(set(esperado) | set(actual)):
        if nombre not in actual:
            print(f"  FALLA {nombre}: ya no se genera")
            fallas += 1
        elif nombre not in esperado:
            print(f"  FALLA {nombre}: examen nuevo sin línea base (corre --guardar si es a propósito)")
            fallas += 1
        elif actual[nombre] != esperado[nombre]:
            e, a = esperado[nombre], actual[nombre]
            print(f"  FALLA {nombre}: el XML cambió (válidas {e['validas']}→{a['validas']}, "
                  f"omitidas {e['omitidas']}→{a['omitidas']}, bytes {e['bytes']}→{a['bytes']})")
            fallas += 1
        else:
            print(f"  ok   {nombre} ({actual[nombre]['validas']} válidas, XML idéntico)")
    print()
    print("TODO OK" if not fallas else f"{fallas} FALLA(S)")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
