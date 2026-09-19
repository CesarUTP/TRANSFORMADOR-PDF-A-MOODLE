"""
compare.py — Pone lado a lado varios resultados de dev/eval.py.

    backend/venv/bin/python dev/compare.py dev/eval_results/A.json dev/eval_results/B.json [...]

Muestra, por documento, la exactitud promedio (preguntas correctas de
punta a punta / esperadas) de cada resultado, y los totales por grupo
(sintéticos / reales), además de tiempo de IA y tokens de salida.
"""

import json
import sys
from pathlib import Path


def load(path: str) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    label = d.get("mode", "?") + ("+enrich" if d.get("enrich") else "")
    return {"label": f"{label} ({Path(path).stem.split('_', 2)[-1]})", "docs": d["docs"]}


def main(paths):
    results = [load(p) for p in paths]
    docs = sorted({name for r in results for name in r["docs"]},
                  key=lambda n: (n.startswith("real_"), n))
    w = max(len(r["label"]) for r in results) + 2
    print(f"{'documento':34s}" + "".join(f"{r['label']:>{w}s}" for r in results))
    print("─" * (34 + w * len(results)))
    totals = {r["label"]: {"synthetic": [0.0, 0], "real": [0.0, 0]} for r in results}
    for name in docs:
        group = "real" if name.startswith("real_") else "synthetic"
        row = f"{name[:34]:34s}"
        for r in results:
            s = (r["docs"].get(name) or {}).get("summary")
            if not s:
                row += f"{'—':>{w}s}"
                continue
            row += f"{s['exactitud']:>{w - 1}.0%} "
            t = totals[r["label"]][group]
            t[0] += s.get("completas", 0)
            t[1] += s["esperadas"]
        print(row)
    print("─" * (34 + w * len(results)))
    for group in ("synthetic", "real"):
        row = f"{'TOTAL ' + group:34s}"
        for r in results:
            ok, n = totals[r["label"]][group]
            row += f"{(ok / n if n else 0):>{w - 1}.0%} "
        print(row)
    print()
    for label, key in (("seg IA (prom/doc)", "seconds"), ("tokens salida (prom/doc)", "output_tokens")):
        row = f"{label:34s}"
        for r in results:
            vals = [v["summary"].get(key, 0) for v in r["docs"].values()]
            row += f"{(sum(vals) / len(vals) if vals else 0):>{w - 1}.0f} "
        print(row)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
