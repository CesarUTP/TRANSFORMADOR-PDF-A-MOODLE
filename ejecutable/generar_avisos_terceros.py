"""
generar_avisos_terceros.py — arma el archivo de avisos de terceros de la app.

    <python del entorno de compilación> generar_avisos_terceros.py SALIDA.txt

La app empaquetada (PyInstaller) lleva dentro Python y todas las bibliotecas
instaladas en el entorno de compilación; casi todas sus licencias (MIT, BSD,
Apache…) piden que su texto acompañe a la copia que se reparte. Este script
recorre los paquetes del entorno con el que se corre y copia el texto de
cada licencia, más las de Python, Lucide y las fuentes. La app lo muestra en
«Acerca de → Avisos de terceros».

Lo corren ejecutable/build.py y ejecutable_mac/build.py justo antes de
compilar, con el MISMO Python que compila: así la lista coincide con lo que
va dentro de cada instalador (Windows y macOS no llevan los mismos paquetes).
dev/sync_ejecutable.py copia este archivo a ambas carpetas.
"""

import sys
from datetime import date
from importlib.metadata import distributions
from pathlib import Path

# Herramientas de compilación: están en el entorno pero no viajan en la app.
SOLO_COMPILACION = {"pip", "setuptools", "wheel", "pyinstaller-hooks-contrib", "altgraph", "macholib"}
PALABRAS_LICENCIA = ("LICENSE", "LICENCE", "COPYING", "NOTICE")


def _licencia(meta) -> str:
    texto = meta.get("License-Expression") or ""
    if not texto:
        clasif = [c.split(" :: ")[-1] for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")]
        primera = ((meta.get("License") or "").strip().splitlines() or [""])[0]
        texto = ", ".join(clasif) or primera[:60]
    return texto.strip() or "ver texto"


def _textos(dist) -> list:
    out = []
    for f in dist.files or []:
        nombre = str(f)
        if ".dist-info/" in nombre and any(p in Path(nombre).name.upper() for p in PALABRAS_LICENCIA) \
                or "/licenses/" in nombre:
            try:
                out.append((nombre.split(".dist-info/")[-1], Path(f.locate()).read_text(encoding="utf-8", errors="replace").strip()))
            except (OSError, ValueError):
                pass
    return out


def main(salida: Path) -> None:
    raiz = Path(__file__).resolve().parent
    # En ejecutable*/ el frontend está al lado; en dev/, un nivel arriba.
    frontend = raiz / "frontend" if (raiz / "frontend").is_dir() else raiz.parent / "frontend"
    partes = [
        "AVISOS DE TERCEROS — Conversor a Moodle XML",
        f"Generado el {date.today().isoformat()} con Python {sys.version.split()[0]} ({sys.platform}).",
        "",
        "Esta aplicación incluye software de terceros. Cada componente se distribuye",
        "bajo su propia licencia, cuyo texto se reproduce a continuación.",
    ]

    def seccion(titulo, licencia, textos):
        partes.extend(["", "=" * 78, f"{titulo} — {licencia}", "=" * 78])
        for nombre, texto in textos:
            partes.extend(["", f"--- {nombre} ---", texto])

    # Python (el intérprete va dentro de la app).
    base = Path(sys.base_prefix)
    lic_py = next((p for p in (base / "LICENSE.txt",
                               base / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt")
                   if p.is_file()), None)
    seccion(f"Python {sys.version.split()[0]}", "PSF-2.0",
            [("LICENSE.txt", lic_py.read_text(encoding="utf-8", errors="replace").strip())] if lic_py
            else [("", "Python Software Foundation License Version 2 — https://docs.python.org/3/license.html")])

    # Recursos del frontend.
    lucide = frontend / "js" / "vendor" / "LICENSE-lucide.txt"
    if lucide.is_file():
        seccion("Lucide 1.44.0 (íconos)", "ISC", [("LICENSE", lucide.read_text(encoding="utf-8").strip())])
    for f in sorted((frontend / "fonts").glob("LICENSE-*.txt")):
        seccion(f"Fuente {f.stem.replace('LICENSE-', '')} (Fontsource 5.3.0)", "SIL OFL 1.1",
                [("LICENSE", f.read_text(encoding="utf-8").strip())])

    # Paquetes de Python. PyObjC (macOS) son ~150 paquetes del mismo
    # proyecto y la misma licencia: van agrupados.
    dists = {}
    for d in distributions():
        nombre = d.metadata["Name"]
        if nombre and nombre.lower() not in SOLO_COMPILACION:
            dists[nombre.lower()] = d
    pyobjc = sorted(n for n in dists if n.startswith("pyobjc"))
    for clave in sorted(dists):
        if clave in pyobjc and clave != "pyobjc-core":
            continue
        d = dists[clave]
        titulo = f"{d.metadata['Name']} {d.version}"
        if clave == "pyobjc-core":
            titulo = f"PyObjC {d.version} ({len(pyobjc)} paquetes: pyobjc, pyobjc-core y pyobjc-framework-*)"
        if clave == "pyinstaller":
            titulo += " (solo su cargador de arranque va dentro de la app)"
        seccion(titulo, _licencia(d.metadata), _textos(d) or [("", "Sin texto de licencia en el paquete; ver "
                                                                   + (d.metadata.get("Home-page") or "PyPI"))])

    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text("\n".join(partes) + "\n", encoding="utf-8")
    print(f"Avisos de terceros: {salida} ({salida.stat().st_size // 1024} KB, {len(dists)} paquetes)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
