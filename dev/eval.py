"""
eval.py — Set de regresión de la normalización de documentos.

Corre el pipeline REAL de la app (backend/pipeline.py, el mismo que usan
/api/parse y /api/normalize_with_ai) sobre cada documento de
samples/golden/, varias veces, y compara el resultado con lo esperado.

Uso:
    backend/venv/bin/python dev/eval.py                    # todo, 3 corridas, modo actual
    backend/venv/bin/python dev/eval.py --mode json        # otro modo de normalización
    backend/venv/bin/python dev/eval.py --only s02 s05     # solo algunos documentos
    backend/venv/bin/python dev/eval.py --runs 1           # más rápido, sin medir varianza
    backend/venv/bin/python dev/eval.py --bootstrap-real   # pre-llena el golden de los PDFs reales

Cada corrida queda guardada en dev/eval_results/<fecha>_<modo>.json con
el detalle de cada pregunta que falló y por qué.

Qué se mide, por documento (promedio de las corridas):
  encontradas    preguntas esperadas que aparecieron (válidas u omitidas)
  utilizables    esperadas que llegaron al editor como válidas
  tipo_ok        ... con el tipo correcto
  enunciado_ok   ... con el enunciado completo (detecta truncados silenciosos)
  respuesta_ok   ... con la respuesta correcta; para una pregunta SIN
                 marca en el original, "ok" es que el sistema NO invente
                 una (quede omitida por falta de respuesta)
  inventadas     respuestas puestas a preguntas que el original no marcaba
  sobrantes      preguntas válidas que no corresponden a ninguna esperada
  omitidas       preguntas que el sistema descartó
Una pregunta del golden con "lenient": true es ambigua en el original;
solo se exige que aparezca.
La métrica principal es EXACTITUD = completas / esperadas, donde una
pregunta está "completa" si llegó con el tipo, el enunciado completo y la
respuesta correctos: la fracción que llega al editor lista para usar.
"""

import argparse
import concurrent.futures as cf
import datetime as dt
import difflib
import json
import os
import re
import statistics
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
GOLDEN_DIR = SAMPLES / "golden"
RESULTS_DIR = ROOT / "dev" / "eval_results"


def _setup_backend(mode: str, enrich: bool = False):
    # El modo se fija por entorno ANTES de importar el backend, para que
    # config.py lo lea igual que lo haría la app.
    os.environ["NORMALIZER_MODE"] = mode
    os.environ["ENRICH_PDF_TEXT"] = "1" if enrich else "0"
    # Plan gratuito de Gemini: 15 peticiones/min por modelo. La evaluación
    # corre varios documentos en paralelo, así que espacia TODAS las
    # llamadas del proceso por debajo de ese límite (ver formatter._throttle).
    os.environ.setdefault("GEMINI_MAX_RPM", "13")
    sys.path.insert(0, str(ROOT / "backend"))
    import logging
    logging.basicConfig(level=logging.WARNING)
    import pipeline  # noqa: F401
    import formatter  # noqa: F401
    return pipeline, formatter


# ── Normalización de texto para comparar ────────────────────────────────────

def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def sim(a, b) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    # Uno contenido en el otro (ej. el modelo agregó "Completa:" o cortó
    # una coletilla): se cuenta como muy parecido.
    shorter, longer = sorted((a, b), key=len)
    if len(shorter) >= 12 and shorter in longer:
        ratio = max(ratio, 0.85)
    return ratio


def token_recall(expected, got) -> float:
    e = norm(expected).split()
    g = set(norm(got).split())
    if not e:
        return 1.0
    return sum(1 for t in e if t in g) / len(e)


def same_answer(a, b) -> bool:
    na, nb = norm(a), norm(b)
    if na == nb:
        return True
    try:
        return abs(float(str(a).replace(",", ".")) - float(str(b).replace(",", "."))) < 1e-9
    except ValueError:
        pass
    return len(na) >= 4 and len(nb) >= 4 and sim(a, b) >= 0.9


def same_answer_set(exp: list, got: list) -> bool:
    if len(exp) != len(got):
        return False
    remaining = list(got)
    for e in exp:
        hit = next((g for g in remaining if same_answer(e, g)), None)
        if hit is None:
            return False
        remaining.remove(hit)
    return True


# ── Salida del pipeline → forma canónica comparable con el golden ───────────

_BRACKET = re.compile(r"\[([A-Za-z]):\s*([^\]]+)\]")


def canonical_from_response(res: dict) -> list:
    """Convierte la respuesta de pipeline (lo que recibe el editor) a una
    lista de preguntas en el mismo formato que el golden."""
    from answer_matching import split_answers  # mismo separador " | " que usa la app
    out = []
    key = res.get("answer_key", {})
    for q in res.get("questions", []):
        t, d = q["type"], q.get("data") or {}
        ans = str((key.get(q["num"]) or key.get(str(q["num"])) or {}).get("answer", ""))
        kinfo = key.get(q["num"]) or key.get(str(q["num"])) or {}
        c = {"status": "valid", "type": t}
        if t == "multichoice":
            opts = d.get("options", {})
            c["stem"] = d.get("stem", "")
            c["options"] = [opts[k] for k in sorted(opts)]
            got = []
            texts = {v.strip().lower() for v in opts.values()}
            for part in split_answers(ans):
                # Igual que xml_builder: el texto exacto de una opción gana a
                # la letra ("C" puede ser la opción cuyo texto es "C").
                if len(part) == 1 and part.upper() in opts and part.lower() not in texts:
                    got.append(opts[part.upper()])
                else:
                    got.append(part)
            c["answers"] = got
        elif t == "truefalse":
            c["stem"] = d.get("stem", "")
            c["answers"] = [ans.strip()]
        elif t == "matching":
            col_a, col_b = d.get("col_a", {}), d.get("col_b", {})
            pairs = kinfo.get("pairs", {}) or {}
            c["stem"] = d.get("stem", "")
            c["pairs"] = [[col_a[k], col_b.get(str(v).lower(), "")]
                          for k, v in sorted(pairs.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0)
                          if k in col_a]
            c["left_items"] = list(col_a.values())
        elif t == "cloze":
            text = d.get("text", "")
            c["stem"] = _BRACKET.sub("____", text)
            letters = [m.group(1).upper() for m in _BRACKET.finditer(text)]
            keymap = {}
            for m in re.finditer(r"([A-Za-z])[\.:]\s*([^;\n]+)", ans):
                keymap[m.group(1).upper()] = split_answers(m.group(2))
            c["blanks"] = [keymap.get(L, []) for L in letters]
        elif t == "essay":
            c["stem"] = d.get("stem", "")
        else:
            c["stem"] = d.get("stem", "")
            c["answers"] = [ans.strip()]
        out.append(c)
    for s in res.get("skipped_questions", []):
        d = s.get("recoverable_data") or {}
        out.append({
            "status": "skipped", "type": s.get("type"),
            "stem": d.get("stem") or d.get("text") or s.get("preview", ""),
            "options": list((d.get("options") or {}).values()),
            "answer_only": "recoverable_data" in s,
            "reasons": s.get("reasons", []),
        })
    return out


# ── Emparejar esperadas ↔ obtenidas y puntuar ───────────────────────────────

def _signature_score(e: dict, g: dict) -> float:
    s = sim(e.get("stem", ""), g.get("stem", ""))
    if e.get("options") and g.get("options"):
        o = sim(" ".join(e["options"]), " ".join(g["options"]))
        s = 0.55 * s + 0.45 * o
    if e["type"] == "matching" and (g.get("left_items") or g.get("pairs")):
        left_e = " ".join(p[0] for p in e.get("pairs", []))
        left_g = " ".join(g.get("left_items") or [p[0] for p in g.get("pairs", [])])
        s = max(s, sim(left_e, left_g))
    return s


def match(expected: list, got: list, threshold: float = 0.55):
    cands = []
    for i, e in enumerate(expected):
        for j, g in enumerate(got):
            sc = _signature_score(e, g)
            if sc >= threshold:
                cands.append((sc, i, j))
    cands.sort(reverse=True)
    used_e, used_g, pairs = set(), set(), {}
    for sc, i, j in cands:
        if i in used_e or j in used_g:
            continue
        used_e.add(i)
        used_g.add(j)
        pairs[i] = j
    return pairs


def answer_correct(e: dict, g: dict) -> bool:
    t = e["type"]
    if t == "essay":
        return g["type"] == "essay"
    if t == "multichoice" or t in ("truefalse", "shortanswer", "numerical"):
        return same_answer_set(e.get("answers", []), g.get("answers", []))
    if t == "matching":
        exp = [f"{p[0]} → {p[1]}" for p in e.get("pairs", [])]
        got = [f"{p[0]} → {p[1]}" for p in g.get("pairs", [])]
        return same_answer_set(exp, got)
    if t == "cloze":
        eb, gb = e.get("blanks", []), g.get("blanks", [])
        return len(eb) == len(gb) and all(same_answer_set(a, b) for a, b in zip(eb, gb))
    return False


def score_run(golden: dict, outcome: dict) -> dict:
    exp = golden["questions"]
    # "seconds" = tiempo DENTRO de las llamadas a Gemini (sin la espera del
    # limitador de peticiones/minuto, que depende de la cuota y no del sistema).
    r = {"status": outcome["status"], "seconds": round(sum(c["seconds"] for c in outcome["calls"]), 1),
         "prompt_tokens": sum(c["prompt_tokens"] for c in outcome["calls"]),
         "output_tokens": sum(c["output_tokens"] for c in outcome["calls"]),
         "gemini_calls": len(outcome["calls"]), "esperadas": len(exp), "problemas": []}

    if not golden.get("is_exam", True):
        ok = outcome["status"] == "rejected"
        r.update(rechazo_correcto=ok, exactitud=1.0 if ok else 0.0)
        if not ok:
            r["problemas"].append(f"debía rechazarse como no-examen y quedó '{outcome['status']}'")
        return r

    got = outcome.get("predicted", [])
    if outcome["status"] != "ok":
        r.update(encontradas=0, utilizables=0, tipo_ok=0, enunciado_ok=0, respuesta_ok=0, completas=0,
                 inventadas=0, sobrantes=0, omitidas=0, exactitud=0.0)
        r["problemas"].append(f"el documento completo falló: {outcome.get('detail', '')}"[:300])
        return r

    pairs = match(exp, got)
    counters = dict(encontradas=0, utilizables=0, tipo_ok=0, enunciado_ok=0, respuesta_ok=0, inventadas=0,
                    completas=0)
    for i, e in enumerate(exp):
        label = f"#{i + 1} [{e['type']}] {e.get('stem', '')[:60]!r}"
        if i not in pairs:
            r["problemas"].append(f"{label}: NO apareció")
            continue
        g = got[pairs[i]]
        counters["encontradas"] += 1
        if e.get("lenient"):
            # Pregunta ambigua en el original (ver "note" en el golden): basta
            # con que aparezca; no se juzga tipo ni respuesta.
            counters["completas"] += 1
            counters["respuesta_ok"] += 1
            if g["status"] == "valid":
                counters["utilizables"] += 1
            continue
        if e.get("unanswered"):
            if g["status"] == "skipped":
                counters["respuesta_ok"] += 1
                counters["completas"] += 1
            else:
                counters["inventadas"] += 1
                r["problemas"].append(f"{label}: sin marca en el original, pero salió con respuesta {g.get('answers') or g.get('blanks')}")
            continue
        if g["status"] != "valid":
            r["problemas"].append(f"{label}: omitida → {'; '.join(g.get('reasons', []))[:160]}")
            continue
        counters["utilizables"] += 1
        type_ok = g["type"] == e["type"]
        stem_ok = e["type"] == "matching" or token_recall(e.get("stem", ""), g.get("stem", "")) >= 0.85
        ans_ok = answer_correct(e, g)
        counters["tipo_ok"] += type_ok
        counters["enunciado_ok"] += stem_ok
        counters["respuesta_ok"] += ans_ok
        counters["completas"] += type_ok and stem_ok and ans_ok
        if not type_ok:
            r["problemas"].append(f"{label}: tipo {g['type']} (esperado {e['type']})")
        if not stem_ok:
            r["problemas"].append(f"{label}: enunciado incompleto → {g.get('stem', '')[:90]!r}")
        if not ans_ok:
            shown = g.get("answers") or g.get("pairs") or g.get("blanks")
            r["problemas"].append(f"{label}: respuesta {shown!r:.160}")
    matched_g = set(pairs.values())
    sobrantes = [g for j, g in enumerate(got) if j not in matched_g and g["status"] == "valid"]
    for g in sobrantes:
        r["problemas"].append(f"sobrante [{g['type']}] {g.get('stem', '')[:70]!r}")
    r.update(counters, sobrantes=len(sobrantes),
             omitidas=sum(1 for g in got if g["status"] == "skipped"),
             exactitud=round(counters["completas"] / len(exp), 3) if exp else 1.0)
    return r


# ── Ejecución ────────────────────────────────────────────────────────────────

def run_once(pipeline, formatter, golden: dict) -> dict:
    from fastapi import HTTPException
    path = SAMPLES / golden["file"]
    data = path.read_bytes()
    formatter.reset_call_log()
    t0 = time.monotonic()
    out = {"status": "ok", "predicted": [], "detail": ""}
    try:
        if golden.get("path") == "normalize_with_ai":
            res = pipeline.normalize_document_with_ai(data, path.name)
        else:
            res = pipeline.parse_document(data, path.name)
        out["predicted"] = canonical_from_response(res)
        out["raw"] = res
    except HTTPException as exc:
        out["status"] = "rejected" if exc.status_code in (400, 422) else "error"
        out["detail"] = json.dumps(exc.detail, ensure_ascii=False) if not isinstance(exc.detail, str) else exc.detail
    except Exception as exc:  # noqa: BLE001 — la evaluación no debe caerse por un documento
        out["status"] = "error"
        out["detail"] = f"{type(exc).__name__}: {exc}"
    out["seconds"] = round(time.monotonic() - t0, 1)
    out["calls"] = formatter.get_call_log()
    return out


def load_goldens(only: list | None, adversarial: bool = False) -> list:
    """Los documentos "adversarial" (x01…x12, ver dev/synthetic/generate_adversarial.py)
    quedan fuera de la corrida por defecto para no mover la línea base de los
    18 originales: se incluyen con --adversarial, o al nombrarlos con --only."""
    goldens = []
    for f in sorted(GOLDEN_DIR.glob("*.expected.json")):
        name = f.name.replace(".expected.json", "")
        if only and not any(o in name for o in only):
            continue
        g = json.loads(f.read_text(encoding="utf-8"))
        if g.get("source") == "adversarial" and not (adversarial or only):
            continue
        g["name"] = name
        goldens.append(g)
    return goldens


def summarize(name: str, runs: list) -> dict:
    keys = ["exactitud", "completas", "encontradas", "utilizables", "tipo_ok", "enunciado_ok", "respuesta_ok",
            "inventadas", "sobrantes", "omitidas", "seconds", "prompt_tokens", "output_tokens", "gemini_calls"]
    s = {"doc": name, "runs": len(runs), "esperadas": runs[0]["esperadas"]}
    for k in keys:
        vals = [r[k] for r in runs if k in r]
        if vals:
            s[k] = round(statistics.mean(vals), 3)
            s[k + "_min"], s[k + "_max"] = min(vals), max(vals)
    return s


def print_table(summaries: list, goldens: dict) -> None:
    hdr = f"{'documento':34s} {'exact.':>7s} {'encont':>7s} {'util':>6s} {'resp':>6s} {'omit':>5s} {'inv':>4s} {'sobr':>5s} {'seg_ia':>6s} {'tok_in':>7s} {'tok_out':>7s}"
    print(hdr)
    print("─" * len(hdr))
    groups = {"synthetic": [], "real": [], "adversarial": []}
    for s in summaries:
        g = goldens[s["doc"]]
        groups[g.get("source") if g.get("source") in groups else "synthetic"].append(s)
    for group, items in groups.items():
        if not items:
            continue
        for s in items:
            flag = "" if goldens[s["doc"]].get("reviewed") else " *"
            n = s["esperadas"]
            rng = "" if s.get("exactitud_min") == s.get("exactitud_max") else f"±"
            print(f"{(s['doc'] + flag)[:34]:34s} {s['exactitud']:>6.0%}{rng:1s}"
                  f" {s.get('encontradas', 0):>4.1f}/{n:<2d} {s.get('utilizables', 0):>6.1f} {s.get('respuesta_ok', 0):>6.1f}"
                  f" {s.get('omitidas', 0):>5.1f} {s.get('inventadas', 0):>4.1f} {s.get('sobrantes', 0):>5.1f}"
                  f" {s['seconds']:>6.1f} {s['prompt_tokens']:>7.0f} {s['output_tokens']:>7.0f}")
        tot_exp = sum(s["esperadas"] for s in items if s["esperadas"])
        tot_ok = sum(s.get("completas", 0) for s in items)
        print(f"{'  TOTAL ' + group:34s} {tot_ok / tot_exp if tot_exp else 0:>6.0%}  "
              f"({tot_ok:.1f} de {tot_exp} preguntas correctas de punta a punta)")
        print()
    print("exact. = preguntas correctas de punta a punta (tipo + enunciado completo + respuesta) / esperadas")
    print("± = varió entre corridas   * = golden sin revisar a mano")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", default=os.environ.get("NORMALIZER_MODE", "json"),
                    help="modo de la carga normal (json por defecto, igual que la app). "
                         "'Normalizar con IA' usa NORMALIZER_MODE_AI (texto por defecto).")
    ap.add_argument("--enrich", action=argparse.BooleanOptionalAction, default=True,
                    help="ENRICH_PDF_TEXT: color y tablas en el texto + marcas resueltas en código "
                         "(activo por defecto, igual que en la app; --no-enrich para desactivarlo)")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--adversarial", action="store_true",
                    help="incluir también los exámenes adversariales x01…x12 (además de los 18 originales)")
    ap.add_argument("--bootstrap-real", action="store_true",
                    help="genera samples/golden/real_*.expected.json a partir de UNA corrida (sin revisar)")
    ap.add_argument("--tag", default="", help="sufijo para el archivo de resultados")
    args = ap.parse_args()

    pipeline, formatter = _setup_backend(args.mode, args.enrich)

    if args.bootstrap_real:
        bootstrap_real(pipeline, formatter)
        return

    goldens = load_goldens(args.only, args.adversarial)
    if not goldens:
        sys.exit("No hay golden que coincida.")
    by_name = {g["name"]: g for g in goldens}
    tasks = [(g["name"], k) for g in goldens for k in range(args.runs)]
    print(f"Modo '{args.mode}'{' + enriquecido' if args.enrich else ''}: {len(goldens)} documentos × {args.runs} corridas = {len(tasks)} ejecuciones "
          f"({args.workers} en paralelo)\n", flush=True)

    outcomes: dict = {g["name"]: [None] * args.runs for g in goldens}
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_once, pipeline, formatter, by_name[n]): (n, k) for n, k in tasks}
        for i, fut in enumerate(cf.as_completed(futs), 1):
            n, k = futs[fut]
            outcomes[n][k] = fut.result()
            o = outcomes[n][k]
            print(f"  [{i:>3}/{len(tasks)}] {n} corrida {k + 1}: {o['status']} en {o['seconds']}s", flush=True)

    report = {"mode": args.mode, "enrich": args.enrich, "runs": args.runs, "date": dt.datetime.now().isoformat(timespec="seconds"),
              "docs": {}}
    summaries = []
    for name, outs in outcomes.items():
        scored = [score_run(by_name[name], o) for o in outs]
        summ = summarize(name, scored)
        summaries.append(summ)
        report["docs"][name] = {
            "summary": summ,
            # "predicted": lo que devolvió el pipeline, ya en forma canónica —
            # para poder depurar un fallo sin volver a gastar una llamada.
            "runs": [{**s, "detail": o.get("detail", ""), "predicted": o.get("predicted", [])}
                     for s, o in zip(scored, outs)],
        }

    print()
    print_table(summaries, by_name)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    out = RESULTS_DIR / f"{stamp}_{args.mode}{'_enrich' if args.enrich else ''}{('_' + args.tag) if args.tag else ''}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nDetalle por pregunta: {out.relative_to(ROOT)}")


def bootstrap_real(pipeline, formatter) -> None:
    """Golden de los PDFs reales a partir de una corrida del pipeline actual.
    Quedan marcados reviewed=false: alguien tiene que revisarlos contra el
    PDF, porque reflejan lo que el sistema HOY entiende, no la verdad."""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for f in sorted(SAMPLES.iterdir()):
        if f.suffix.lower() not in (".pdf", ".txt") or not f.is_file():
            continue
        slug = "real_" + re.sub(r"[^a-z0-9]+", "_", norm(f.stem)).strip("_")
        target = GOLDEN_DIR / f"{slug}.expected.json"
        if target.exists():
            print(f"  ya existe, no se pisa: {target.name}")
            continue
        g = {"file": f.name, "path": "parse", "is_exam": True}
        out = run_once(pipeline, formatter, g)
        if out["status"] != "ok":
            print(f"  {f.name}: {out['status']} — {out['detail'][:120]}")
            continue
        qs = []
        for c in out["predicted"]:
            if c["status"] != "valid":
                continue
            q = {k: v for k, v in c.items() if k in ("type", "stem", "answers", "options", "pairs", "blanks")}
            qs.append(q)
        doc = {
            "source": "real", "reviewed": False, "file": f.name, "path": "parse", "is_exam": True,
            "notes": "PRE-LLENADO a partir de una corrida del pipeline de texto. Revisar contra el PDF: "
                     "corregir respuestas, agregar las preguntas que falten (las omitidas no se incluyeron) "
                     "y cambiar reviewed a true.",
            "questions": qs,
        }
        target.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  {target.name}: {len(qs)} preguntas pre-llenadas ({out['seconds']}s)")


if __name__ == "__main__":
    main()
