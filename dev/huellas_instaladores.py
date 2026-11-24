"""
huellas_instaladores.py — la huella SHA-256 de los instaladores, para publicarla en el release (2.9).

    python dev/huellas_instaladores.py                       # los instaladores de siempre, si existen
    python dev/huellas_instaladores.py ruta/Catedra.dmg …    # los que se indiquen

Imprime el bloque en Markdown para las notas del release («Verificar la descarga») y escribe
dist-huellas/SHA256SUMS.txt (el formato que entiende `shasum -a 256 -c` en Mac y Linux): se sube al release
junto a los instaladores (`gh release upload vX.Y dist-huellas/SHA256SUMS.txt`). Quien descarga puede comprobar
que el archivo es el que se publicó, y es la comprobación mínima mientras las apps no estén firmadas ni notarizadas.
Si un instalador de Windows se sube después, se vuelve a correr con los dos y se sube el archivo de nuevo
(`--clobber`). No usa red.
"""

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREDETERMINADOS = (ROOT / "ejecutable_mac" / "dist" / "Catedra.dmg", ROOT / "ejecutable" / "Output" / "Catedra_Setup.exe")


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for trozo in iter(lambda: f.read(1024 * 1024), b""):
            h.update(trozo)
    return h.hexdigest()


def main(argv) -> int:
    rutas = [Path(a) for a in argv] or [r for r in PREDETERMINADOS if r.exists()]
    faltan = [r for r in rutas if not r.is_file()]
    if faltan or not rutas:
        print("No hay instaladores que medir:", ", ".join(map(str, faltan)) or "ninguno de los de siempre existe")
        return 1
    filas = [(sha256(r), r.name, r.stat().st_size) for r in rutas]
    destino = ROOT / "dist-huellas"
    destino.mkdir(exist_ok=True)
    (destino / "SHA256SUMS.txt").write_text("".join(f"{h}  {n}\n" for h, n, _ in filas), encoding="utf-8")
    print("### Verificar la descarga\n")
    print("Cada instalador tiene su huella SHA-256 (también en `SHA256SUMS.txt`, adjunto a este release):\n")
    print("| Archivo | Tamaño | SHA-256 |\n|---|---|---|")
    for h, n, t in filas:
        print(f"| `{n}` | {t / 1024 / 1024:.1f} MB | `{h}` |")
    print("\nPara comprobarla:\n\n- **macOS**: `shasum -a 256 Catedra.dmg` en Terminal.\n"
          "- **Windows**: `certutil -hashfile Catedra_Setup.exe SHA256` en el Símbolo del sistema.\n\n"
          "Tiene que dar el mismo valor de la tabla. Si no coincide, no instales ese archivo.")
    print(f"\n→ {destino.relative_to(ROOT)}/SHA256SUMS.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
