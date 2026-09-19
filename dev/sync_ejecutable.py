"""
sync_ejecutable.py — Actualiza ejecutable/ y ejecutable_mac/ con el código actual.

    backend/venv/bin/python dev/sync_ejecutable.py

ejecutable/ (Windows) y ejecutable_mac/ (macOS) son paquetes autosuficientes
que se copian a la máquina donde se compila el instalador (ver sus LEEME_*).
Cada uno lleva una COPIA del backend, el frontend y el launcher: si no se
sincronizan antes de compilar, el instalador sale con código viejo (pasó:
quedaron días atrás, sin pipeline.py, schema_adapter.py ni mark_resolver.py).

Copia solo lo que la app necesita para correr: los módulos .py de backend/,
su requirements.txt, frontend/index.html y launcher.py. Borra de
ejecutable/backend/ los .py que ya no existen en backend/. Nunca copia un
.env (la API key se pone a mano junto al .exe instalado).
"""

import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESTS = [ROOT / "ejecutable", ROOT / "ejecutable_mac"]


def _files(dest: Path):
    return [
        (ROOT / "launcher.py", dest / "launcher.py"),
        (ROOT / "frontend" / "index.html", dest / "frontend" / "index.html"),
        (ROOT / "backend" / "requirements.txt", dest / "backend" / "requirements.txt"),
    ] + [
        (src, dest / "backend" / src.name)
        for src in sorted((ROOT / "backend").glob("*.py"))
    ]


def sync(dest: Path) -> tuple:
    changed = []
    for src, dst in _files(dest):
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or not filecmp.cmp(src, dst, shallow=False):
            shutil.copy2(src, dst)
            changed.append(dst.relative_to(ROOT))
    current = {src.name for src in (ROOT / "backend").glob("*.py")}
    removed = []
    for stale in (dest / "backend").glob("*.py"):
        if stale.name not in current:
            stale.unlink()
            removed.append(stale.relative_to(ROOT))
    return changed, removed


def main() -> int:
    for dest in DESTS:
        if not dest.is_dir():
            sys.exit(f"No existe {dest}")
        changed, removed = sync(dest)
        for path in changed:
            print(f"  actualizado  {path}")
        for path in removed:
            print(f"  eliminado    {path}")
        print(f"{dest.name}/ ya estaba al día." if not (changed or removed)
              else f"{dest.name}/: {len(changed)} actualizado(s), {len(removed)} eliminado(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
