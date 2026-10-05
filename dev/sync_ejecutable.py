"""
sync_ejecutable.py — Actualiza ejecutable/ y ejecutable_mac/ con el código actual.

    backend/venv/bin/python dev/sync_ejecutable.py

ejecutable/ (Windows) y ejecutable_mac/ (macOS) son paquetes autosuficientes
que se copian a la máquina donde se compila el instalador (ver sus LEEME_*).
Cada uno lleva una COPIA del backend, el frontend y el launcher: si no se
sincronizan antes de compilar, el instalador sale con código viejo (pasó:
quedaron días atrás, sin pipeline.py, schema_adapter.py ni mark_resolver.py).

Copia solo lo que la app necesita para correr: los módulos .py de backend/ (y su carpeta fuentes/),
su requirements.txt, todo frontend/ (index.html, css/, js/) y launcher.py.
Borra los archivos que ya no existen en el original. Nunca copia un .env
(la API key se pone a mano junto al ejecutable instalado).

Antes de copiar nada corre las pruebas (dev/test_casos_borde.py,
dev/test_seguridad.py, dev/test_mejoras.py y las demás test_*.py de PRUEBAS): si alguna falla, no se
actualizan los instaladores. --sin-pruebas las salta (solo para una
emergencia).

--check: no copia ni borra nada — solo dice si ejecutable/ o
ejecutable_mac/ quedaron desfasados de backend/frontend/launcher.py, y
termina con código de salida distinto de cero si es así. Antes nadie se
enteraba de esto hasta compilar el instalador y encontrarlo roto (pasó:
imagenes.py y ayuda_ia.py llegaron a faltar por completo en las dos
copias). Pensado para correr en CI en cada push, no para ejecutarlo a
mano antes de compilar — para eso está el propio sync.
"""

import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Archivos del frontend que son de desarrollo y no viajan en el instalador.
SOLO_DESARROLLO = {"pruebas.html", "pruebas.js"}
DESTS = [ROOT / "ejecutable", ROOT / "ejecutable_mac"]


def _sources() -> list:
    """(origen, ruta relativa) de todo lo que la app necesita."""
    out = [(ROOT / "launcher.py", Path("launcher.py")),
           (ROOT / "backend" / "requirements.txt", Path("backend/requirements.txt")),
           (ROOT / "dev" / "generar_avisos_terceros.py", Path("generar_avisos_terceros.py")),
           (ROOT / "requirements-build.lock", Path("requirements-build.lock"))]
    out += [(src, Path("backend") / src.name) for src in sorted((ROOT / "backend").glob("*.py"))]
    # Fuente del PDF del examen (backend/fuentes/): backend/ va entero como datos del instalador.
    out += [(src, src.relative_to(ROOT)) for src in sorted((ROOT / "backend" / "fuentes").glob("*"))
            if src.is_file() and not src.name.startswith(".")]
    out += [(src, src.relative_to(ROOT))
            for src in sorted((ROOT / "frontend").rglob("*"))
            if src.is_file() and not src.name.startswith(".")
            and src.name not in SOLO_DESARROLLO]
    return out


def _files(dest: Path):
    return [(src, dest / rel) for src, rel in _sources()]


def _desfase(dest: Path) -> tuple:
    """Qué archivos DEBERÍAN copiarse (faltan o difieren) y cuáles DEBERÍAN
    borrarse (ya no existen en el original) para que `dest` quede al día.
    No toca el disco — lo usan tanto sync() (que sí aplica el cambio) como
    check() (que solo lo reporta)."""
    faltan_o_difieren = [dst.relative_to(ROOT) for src, dst in _files(dest)
                         if not dst.exists() or not filecmp.cmp(src, dst, shallow=False)]
    expected = {dest / rel for _, rel in _sources()}
    sobran = []
    for folder, pattern in ((dest / "backend", "*.py"), (dest / "backend" / "fuentes", "*"),
                            (dest / "frontend", "**/*")):
        if not folder.is_dir():
            continue
        for stale in folder.rglob(pattern) if pattern.startswith("**") else folder.glob(pattern):
            if stale.is_file() and not stale.name.startswith(".") and stale not in expected:
                sobran.append(stale.relative_to(ROOT))
    return faltan_o_difieren, sobran


def sync(dest: Path) -> tuple:
    changed = []
    for src, dst in _files(dest):
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or not filecmp.cmp(src, dst, shallow=False):
            shutil.copy2(src, dst)
            changed.append(dst.relative_to(ROOT))
    # Lo que ya no existe en el original se borra de la copia (si no, un
    # módulo renombrado seguiría viajando dentro del instalador).
    _, sobran = _desfase(dest)
    for rel in sobran:
        (ROOT / rel).unlink()
    return changed, sobran


def check(dest: Path) -> tuple:
    """Como sync(), pero sin escribir nada: solo dice qué DEBERÍA cambiar."""
    return _desfase(dest)


PRUEBAS = (
    "test_casos_borde.py",
    "test_seguridad.py",
    "test_mejoras.py",
    "test_xml_baseline.py",
    "test_modelo.py",
    "test_confianza.py",
    "test_extraccion.py",
    "test_word_avanzado.py",
    "test_xml_validador.py",
    "test_opciones_separadores.py",
    "test_ia_servidor.py",
    "test_ia_proveedor.py",
    "test_datos_arranque.py",
    "test_compat_moodle.py",
    "test_original.py",
    "test_ia_asistida.py",
    "test_importar_xml.py",
    "test_exportar_pdf.py",
)


def _correr_pruebas() -> None:
    for prueba in PRUEBAS:
        print(f"Corriendo {prueba}…")
        r = subprocess.run([sys.executable, str(ROOT / "dev" / prueba)], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode:
            print(r.stdout[-4000:], r.stderr[-4000:], sep="\n")
            sys.exit(f"Fallan las pruebas de {prueba}: no se actualizan los instaladores.")
    # Lógica del frontend en Node (sin navegador ni dependencias). Si esta
    # máquina no tiene Node se avisa y se sigue: el CI sí la corre siempre.
    node = shutil.which("node")
    if node:
        print("Corriendo test_frontend.mjs…")
        r = subprocess.run([node, str(ROOT / "dev" / "test_frontend.mjs")], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode:
            print(r.stdout[-4000:], r.stderr[-4000:], sep="\n")
            sys.exit("Fallan las pruebas del frontend: no se actualizan los instaladores.")
    else:
        print("AVISO: no hay Node en el PATH; se omiten las pruebas del frontend (el CI las corre).")
    print("Pruebas OK.\n")


def _check() -> int:
    desfasado = False
    for dest in DESTS:
        if not dest.is_dir():
            print(f"  falta la carpeta   {dest.relative_to(ROOT)}")
            desfasado = True
            continue
        difieren, sobran = check(dest)
        for path in difieren:
            print(f"  desactualizado   {path}")
        for path in sobran:
            print(f"  sobra            {path}")
        if difieren or sobran:
            desfasado = True
        else:
            print(f"{dest.name}/ está al día.")
    if desfasado:
        print("\nejecutable/ y/o ejecutable_mac/ no coinciden con el código actual.")
        print("Corre: backend/venv/bin/python dev/sync_ejecutable.py")
        return 1
    print("\nTodo sincronizado.")
    return 0


def main() -> int:
    if "--check" in sys.argv:
        return _check()
    if "--sin-pruebas" not in sys.argv:
        _correr_pruebas()
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
