"""
sync_ejecutable.py — Actualiza la carpeta ejecutable/ con el código actual.

    backend/venv/bin/python dev/sync_ejecutable.py

ejecutable/ es el paquete autosuficiente que se copia a una PC con Windows
para generar el instalador (ver ejecutable/LEEME_WINDOWS.txt). Lleva una
COPIA del backend, el frontend y el launcher: si no se sincroniza antes de
compilar, el instalador sale con código viejo (pasó: quedó cuatro días
atrás, sin pipeline.py, schema_adapter.py ni mark_resolver.py).

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
DEST = ROOT / "ejecutable"

FILES = [
    (ROOT / "launcher.py", DEST / "launcher.py"),
    (ROOT / "frontend" / "index.html", DEST / "frontend" / "index.html"),
    (ROOT / "backend" / "requirements.txt", DEST / "backend" / "requirements.txt"),
] + [
    (src, DEST / "backend" / src.name)
    for src in sorted((ROOT / "backend").glob("*.py"))
]


def main() -> int:
    if not DEST.is_dir():
        sys.exit(f"No existe {DEST}")
    changed = []
    for src, dst in FILES:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or not filecmp.cmp(src, dst, shallow=False):
            shutil.copy2(src, dst)
            changed.append(dst.relative_to(ROOT))
    current = {src.name for src in (ROOT / "backend").glob("*.py")}
    removed = []
    for stale in (DEST / "backend").glob("*.py"):
        if stale.name not in current:
            stale.unlink()
            removed.append(stale.relative_to(ROOT))
    for path in changed:
        print(f"  actualizado  {path}")
    for path in removed:
        print(f"  eliminado    {path}")
    print("ejecutable/ ya estaba al día." if not (changed or removed)
          else f"{len(changed)} actualizado(s), {len(removed)} eliminado(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
