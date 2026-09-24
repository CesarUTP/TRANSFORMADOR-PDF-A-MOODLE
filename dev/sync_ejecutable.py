"""
sync_ejecutable.py — Actualiza ejecutable/ y ejecutable_mac/ con el código actual.

    backend/venv/bin/python dev/sync_ejecutable.py

ejecutable/ (Windows) y ejecutable_mac/ (macOS) son paquetes autosuficientes
que se copian a la máquina donde se compila el instalador (ver sus LEEME_*).
Cada uno lleva una COPIA del backend, el frontend y el launcher: si no se
sincronizan antes de compilar, el instalador sale con código viejo (pasó:
quedaron días atrás, sin pipeline.py, schema_adapter.py ni mark_resolver.py).

Copia solo lo que la app necesita para correr: los módulos .py de backend/,
su requirements.txt, todo frontend/ (index.html, css/, js/) y launcher.py.
Borra los archivos que ya no existen en el original. Nunca copia un .env
(la API key se pone a mano junto al ejecutable instalado).
"""

import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Archivos del frontend que son de desarrollo y no viajan en el instalador.
SOLO_DESARROLLO = {"pruebas.html", "pruebas.js"}
DESTS = [ROOT / "ejecutable", ROOT / "ejecutable_mac"]


def _sources() -> list:
    """(origen, ruta relativa) de todo lo que la app necesita."""
    out = [(ROOT / "launcher.py", Path("launcher.py")),
           (ROOT / "backend" / "requirements.txt", Path("backend/requirements.txt"))]
    out += [(src, Path("backend") / src.name) for src in sorted((ROOT / "backend").glob("*.py"))]
    out += [(src, src.relative_to(ROOT))
            for src in sorted((ROOT / "frontend").rglob("*"))
            if src.is_file() and not src.name.startswith(".")
            and src.name not in SOLO_DESARROLLO]
    return out


def _files(dest: Path):
    return [(src, dest / rel) for src, rel in _sources()]


def sync(dest: Path) -> tuple:
    changed = []
    for src, dst in _files(dest):
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or not filecmp.cmp(src, dst, shallow=False):
            shutil.copy2(src, dst)
            changed.append(dst.relative_to(ROOT))
    # Lo que ya no existe en el original se borra de la copia (si no, un
    # módulo renombrado seguiría viajando dentro del instalador).
    expected = {dest / rel for _, rel in _sources()}
    removed = []
    for folder, pattern in ((dest / "backend", "*.py"), (dest / "frontend", "**/*")):
        for stale in folder.rglob(pattern) if pattern.startswith("**") else folder.glob(pattern):
            if stale.is_file() and not stale.name.startswith(".") and stale not in expected:
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
