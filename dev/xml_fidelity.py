"""
xml_fidelity.py — Fidelidad de la ETAPA FINAL (adaptador → validador → XML),
medida con una IA "perfecta" y sin gastar una sola llamada a Gemini.

dev/eval.py mide qué tan bien la IA lee el documento. Esta prueba mide lo
otro: si la IA entrega exactamente lo correcto (el golden), ¿el XML que sale
dice lo mismo? Sirve para separar los fallos del modelo de los del código.

    backend/venv/bin/python dev/xml_fidelity.py            # los 12 adversariales
    backend/venv/bin/python dev/xml_fidelity.py --only x08

Cómo funciona: toma los datos con los que se dibujó cada examen (la verdad),
los convierte en la respuesta JSON que un modelo perfecto devolvería
(RESPONSE_SCHEMA), la pasa por schema_adapter → validator.partition_questions
→ xml_builder.build_xml, y LEE de vuelta el XML como lo haría Moodle
(opciones con fracción > 0, pares de <subquestion>, {N:MULTICHOICE_S:=a~b}
con "=" = correcta y "\\~" escapado) para compararlo con la verdad.

Las preguntas sin respuesta en el documento (unanswered) deben quedar
omitidas por el validador; cualquier otra cosa es una respuesta inventada.
"""

import argparse
import html
import importlib.util
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "dev" / "synthetic"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

from lxml import etree  # noqa: E402
from schema_adapter import adapt  # noqa: E402
from validator import partition_questions  # noqa: E402
from xml_builder import build_xml  # noqa: E402


class _Captured(Exception):
    def __init__(self, qs):
        self.qs = qs


def load_exams() -> dict:
    """{nombre: [preguntas]} de los 12 adversariales, sin escribir ningún archivo."""
    spec = importlib.util.spec_from_file_location("ga", ROOT / "dev/synthetic/generate_adversarial.py")
    ga = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ga)

    def capture(name, qs):
        raise _Captured(qs)
    ga.check_size = capture
    out = {}
    for fn in (ga.x01, ga.x02, ga.x03, ga.x04, ga.x05, ga.x06, ga.x07, ga.x08, ga.x09, ga.x10, ga.x11, ga.x12, ga.x13):
        try:
            fn()
        except _Captured as c:
            out[fn.__name__] = c.qs
    return out


# ── Verdad → salida JSON de un modelo perfecto ──────────────────────────────

_BASE = {"opciones": [], "items_izquierda": [], "items_derecha": [], "parejas": [], "huecos": [],
         "clave_texto": "", "respuesta_texto": "", "respuesta_marcada": True, "origen_tabla": False,
         "pagina": 1, "confianza": "alta"}


def perfect_model(qs: list) -> dict:
    out = []
    for i, q in enumerate(qs, 1):
        t, un = q["type"], bool(q.get("unanswered"))
        j = {**_BASE, "orden": i, "tipo": t, "enunciado": q.get("stem") or "", "respuesta_marcada": not un}
        if t == "multichoice":
            j["opciones"] = [{"letra_original": "abcdefghij"[k], "texto": o, "correcta": (k in q["correct"]) and not un}
                             for k, o in enumerate(q["options"])]
        elif t == "truefalse":
            j["respuesta_texto"] = "" if un else q["answer"]
        elif t == "matching":
            rights = [r for _, r in q["pairs"]] + list(q.get("extra_right", []))
            j["items_izquierda"] = [l for l, _ in q["pairs"]]
            j["items_derecha"] = rights
            j["parejas"] = [] if un else [{"izquierda": k + 1, "derecha": rights.index(r) + 1} for k, (_, r) in enumerate(q["pairs"])]
        elif t == "cloze":
            j["enunciado"] = re.sub(r"\{(\d)\}", lambda m: f"[{'ABCDEF'[int(m.group(1))]}]", q["text"])
            j["huecos"] = [{"marcador": "ABCDEF"[k],
                            "opciones": [{"letra_original": "", "texto": o, "correcta": (c in b["correct"]) and not un}
                                         for c, o in enumerate(b["options"])]} for k, b in enumerate(q["blanks"])]
        elif t in ("shortanswer", "numerical"):
            j["respuesta_texto"] = "" if un else q["answer"]
        out.append(j)
    return {"es_examen": True, "preguntas": out}


# ── Lectura del XML como lo haría Moodle ────────────────────────────────────

def _txt(node, path):
    el = node.find(path)
    return html.unescape((el.text or "").strip()) if el is not None else ""


_CLOZE = re.compile(r"\{(\d+):(MULTICHOICE_S|MULTIRESPONSE_S):((?:[^{}\\]|\\.)*)\}")


def read_cloze(text: str) -> list:
    """[(tipo, [(texto, es_correcta)])] por hueco, con la semántica de Moodle."""
    slots = []
    for m in _CLOZE.finditer(text):
        opts, cur, esc = [], "", False
        for ch in m.group(3) + "~":
            if esc:
                cur += ch
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == "~":
                opts.append(cur)
                cur = ""
            else:
                cur += ch
        slots.append((m.group(2), [_cloze_option(o) for o in opts]))
    return slots


_FRACTION = re.compile(r"^%(-?\d+)%(.*)$", re.S)


def _cloze_option(o: str):
    """(texto, es_correcta) según Moodle: "=" delante = correcta; "%n%" delante
    fija la fracción explícita (0 = incorrecta); el resto es texto."""
    if o.startswith("="):
        return o[1:], True
    m = _FRACTION.match(o)
    if m:
        return m.group(2), int(m.group(1)) > 0
    return o, False


def read_xml(xml: str) -> dict:
    root = etree.fromstring(xml.encode("utf-8"))
    res = {}
    for qn in root.findall("question"):
        typ = qn.get("type")
        if typ == "category":
            continue
        num = int(re.sub(r"\D", "", _txt(qn, "name/text")))
        e = {"type": typ}
        if typ == "multichoice":
            e["answers"] = [(_txt(a, "text"), float(a.get("fraction"))) for a in qn.findall("answer")]
        elif typ == "truefalse":
            e["answers"] = [(_txt(a, "text"), float(a.get("fraction"))) for a in qn.findall("answer")]
        elif typ == "matching":
            e["pairs"] = [(_txt(s, "text"), _txt(s, "answer/text")) for s in qn.findall("subquestion")]
        elif typ == "cloze":
            e["slots"] = read_cloze(html.unescape(qn.find("questiontext/text").text))
        elif typ in ("shortanswer", "numerical"):
            e["answers"] = [(_txt(a, "text"), float(a.get("fraction"))) for a in qn.findall("answer")]
        res[num] = e
    return res


def norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))
    return " ".join(s.split()).lower()


# ── Comparación ─────────────────────────────────────────────────────────────

def check(q: dict, e: dict) -> list:
    """Motivos por los que el XML de la pregunta q no dice lo mismo que la verdad."""
    bad, t = [], q["type"]
    if t == "multichoice":
        want = sorted(q["options"][k] for k in q["correct"])
        got = sorted(txt for txt, fr in e["answers"] if fr > 0)
        if want != got:
            bad.append(f"correctas en XML {got} ≠ esperadas {want}")
        if sorted(txt for txt, _ in e["answers"]) != sorted(q["options"]):
            bad.append("las opciones del XML no son las del examen")
        if abs(sum(fr for _, fr in e["answers"] if fr > 0) - 100) > 0.1:
            bad.append("las fracciones positivas no suman 100")
        # Con varias respuestas correctas, marcar TODAS las opciones debe
        # dar 0 (o menos), nunca 100 — si no, "seleccionar todo" se lleva la
        # nota completa sin haber discriminado nada (ver RESULTADOS.md).
        if len(q["correct"]) > 1:
            select_all = sum(fr for _, fr in e["answers"])
            if select_all > 0.1:
                bad.append(f"marcar TODAS las opciones da {select_all:.2f}% (debería ser ≤ 0)")
    elif t == "truefalse":
        got = next((txt for txt, fr in e["answers"] if fr == 100), "")
        if (got == "true") != (q["answer"] == "Verdadero"):
            bad.append("verdadero/falso invertido")
    elif t == "matching":
        want = sorted((l, r) for l, r in q["pairs"])
        if sorted(e["pairs"]) != want:
            bad.append(f"pares en XML {sorted(e['pairs'])[:3]}… ≠ esperados")
    elif t == "cloze":
        blanks = q["blanks"]
        if len(e["slots"]) != len(blanks):
            bad.append(f"{len(e['slots'])} huecos en XML, esperados {len(blanks)}")
        else:
            for k, ((typ, opts), b) in enumerate(zip(e["slots"], blanks)):
                want_opts = sorted(norm(o) for o in b["options"])
                got_opts = sorted(norm(o) for o, _ in opts)
                if want_opts != got_opts:
                    bad.append(f"hueco {k + 1}: opciones {[o for o, _ in opts]} ≠ {b['options']}")
                    continue
                want = sorted(norm(b["options"][c]) for c in b["correct"])
                got = sorted(norm(o) for o, ok in opts if ok)
                if want != got:
                    bad.append(f"hueco {k + 1}: correcta(s) en XML {got} ≠ {want}")
    elif t in ("shortanswer", "numerical"):
        if not any(norm(txt) == norm(q["answer"]) and fr == 100 for txt, fr in e["answers"]):
            bad.append(f"respuesta en XML {[a for a, _ in e['answers']]} ≠ {q['answer']!r}")
    return bad


def accents_dropped(q: dict, e: dict) -> bool:
    """Cloze cuyas opciones perdieron tildes en el XML (no cuenta como fallo de contenido)."""
    if q["type"] != "cloze":
        return False
    want = [o for b in q["blanks"] for o in b["options"]]
    got = [o for _, opts in e["slots"] for o, _ in opts]
    return sorted(want) != sorted(got) and sorted(map(norm, want)) == sorted(map(norm, got))


def run(only=None) -> dict:
    exams = load_exams()
    report = {}
    for fn_name, qs in exams.items():
        if only and not any(o in fn_name for o in only):
            continue
        questions, key = adapt(perfect_model(qs))
        valid, skipped = partition_questions(questions, key)
        xml, _ = build_xml(valid, key)
        etree.fromstring(xml.encode())                       # bien formado
        xml_q = read_xml(xml)
        skipped_nums = {s["num"] for s in skipped}
        d = {"n": len(qs), "ok": 0, "acentos": 0, "fallos": [], "omitidas_ok": 0, "inventadas": [], "omitidas_mal": [],
             "por_tipo": defaultdict(lambda: [0, 0])}
        for num, q in enumerate(qs, 1):
            t = q["type"]
            if q.get("unanswered"):
                if num in skipped_nums:
                    d["omitidas_ok"] += 1
                    d["ok"] += 1
                else:
                    d["inventadas"].append(f"#{num} [{t}]")
                d["por_tipo"][t][0] += 1
                d["por_tipo"][t][1] += num in skipped_nums
                continue
            d["por_tipo"][t][0] += 1
            if num in skipped_nums:
                d["omitidas_mal"].append(f"#{num} [{t}] omitida: {next(s['reasons'][0] for s in skipped if s['num'] == num)[:100]}")
                continue
            if t == "essay":
                d["ok"] += 1
                d["por_tipo"][t][1] += 1
                continue
            bad = check(q, xml_q[num])
            if accents_dropped(q, xml_q[num]):
                d["acentos"] += 1
            if bad:
                d["fallos"].append(f"#{num} [{t}] {(q.get('stem') or q.get('text'))[:55]!r}: {'; '.join(bad)[:170]}")
            else:
                d["ok"] += 1
                d["por_tipo"][t][1] += 1
        d["por_tipo"] = {k: v for k, v in d["por_tipo"].items()}
        report[fn_name] = d
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--json", default=str(ROOT / "dev/eval_results/xml_fidelidad_adversarial.json"))
    args = ap.parse_args()
    rep = run(args.only)
    print(f"{'examen':8s} {'preg':>5s} {'XML fiel':>9s} {'omit.ok':>8s} {'inventa':>8s} {'omit.mal':>9s} {'fallos':>7s} {'sin tildes':>11s}")
    tot = defaultdict(int)
    for name, d in rep.items():
        print(f"{name:8s} {d['n']:>5d} {d['ok']:>9d} {d['omitidas_ok']:>8d} {len(d['inventadas']):>8d} {len(d['omitidas_mal']):>9d} {len(d['fallos']):>7d} {d['acentos']:>11d}")
        for k, v in (("n", d["n"]), ("ok", d["ok"]), ("fallos", len(d["fallos"])), ("inv", len(d["inventadas"])),
                     ("omm", len(d["omitidas_mal"])), ("ac", d["acentos"])):
            tot[k] += v
    print(f"{'TOTAL':8s} {tot['n']:>5d} {tot['ok']:>9d} {'':>8s} {tot['inv']:>8d} {tot['omm']:>9d} {tot['fallos']:>7d} {tot['ac']:>11d}")
    print()
    for name, d in rep.items():
        for f in d["fallos"] + [f"INVENTADA {x}" for x in d["inventadas"]] + d["omitidas_mal"]:
            print(f"{name}: {f}")
    Path(args.json).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nDetalle: {Path(args.json).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
