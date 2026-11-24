"""
comprobar_dependencias.py — las dependencias fijadas dicen lo mismo en todos lados (3.0).

    python dev/comprobar_dependencias.py

Comprueba, sin red:
  · cada versión de backend/requirements.txt aparece, igual, en requirements-build.lock (con lo que se compila);
  · toda línea del lock lleva sus huellas SHA-256 (el CI y los instaladores instalan con --require-hashes);
  · requirements-build.in sigue apuntando a backend/requirements.txt.
Si cambias una versión en requirements.txt hay que regenerar el lock:
    uv pip compile --universal --generate-hashes --python-version 3.10 requirements-build.in -o requirements-build.lock
(con --upgrade-package <paquete> para subir uno de los indirectos). No usa red ni toca datos.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
fallas = 0


def ok(cond, msg):
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


def norm(nombre: str) -> str:
    return re.sub(r"[-_.]+", "-", nombre).lower()


def pines_de_requirements() -> dict:
    """{nombre: {versión, …}} de backend/requirements.txt (puede haber varias líneas por paquete con marcadores)."""
    out = {}
    for linea in (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8").splitlines():
        linea = linea.split("#")[0].strip()
        m = re.match(r"([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([^\s;]+)", linea)
        if m:
            out.setdefault(norm(m.group(1)), set()).add(m.group(2))
    return out


def pines_del_lock() -> tuple:
    """({nombre: {versión, …}}, [paquetes sin huella])."""
    texto = (ROOT / "requirements-build.lock").read_text(encoding="utf-8")
    out, sin_huella = {}, []
    for bloque in re.split(r"\n(?=[A-Za-z0-9_.\-]+(?:\[[^\]]*\])?==)", texto):
        m = re.match(r"([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([^\s;\\]+)", bloque)
        if not m:
            continue
        out.setdefault(norm(m.group(1)), set()).add(m.group(2))
        if "--hash=sha256:" not in bloque:
            sin_huella.append(m.group(1))
    return out, sin_huella


print("Dependencias: requirements.txt y requirements-build.lock")
req = pines_de_requirements()
lock, sin_huella = pines_del_lock()
ok(len(req) >= 10 and len(lock) >= 100, f"se leyeron {len(req)} pines de la app y {len(lock)} paquetes del lock")
for nombre, versiones in sorted(req.items()):
    ok(versiones <= lock.get(nombre, set()), f"{nombre} {sorted(versiones)}: en el lock {sorted(lock.get(nombre, []))}")
ok(not sin_huella, f"todo paquete del lock lleva su huella SHA-256 {sin_huella[:3]}")
entrada = (ROOT / "requirements-build.in").read_text(encoding="utf-8")
ok("-r backend/requirements.txt" in entrada, "requirements-build.in parte de backend/requirements.txt")

print()
print("TODO OK" if not fallas else f"{fallas} FALLA(S)")
sys.exit(1 if fallas else 0)
