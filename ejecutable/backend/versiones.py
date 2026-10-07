"""
versiones.py — varias versiones impresas de un mismo examen (2.5).

El docente sube un examen grande (por ejemplo 100 preguntas) que sirve de banco y pide N versiones con
algunas de esas preguntas. El SORTEO lo hace la interfaz (frontend/js/versiones-logica.js) para poder
rehacerlo y editarlo al momento; aquí solo se ARMA cada versión a partir del examen completo:

  - cada versión es una lista de números de pregunta (`nums`, en el orden en que salen) y, si el docente los
    editó, sus puntos;
  - las preguntas y la clave se toman SIEMPRE del examen completo: una versión nunca trae una pregunta o una
    respuesta que el examen no tenga, y la clave de cada versión es la de sus preguntas;
  - cada versión se genera con exportar_pdf.generar_pdf, igual que el PDF de un examen suelto.

El Moodle XML no cambia: es el del examen completo y Moodle hace su propio sorteo.
"""

import io
import math
import re
import unicodedata
import zipfile
from typing import Any, Dict, List, Optional, Tuple

MAX_VERSIONES = 12


class VersionInvalida(ValueError):
    """Una versión pide algo que el examen no tiene (se muestra al docente)."""


def subconjunto(questions: List[Dict[str, Any]], answer_key: Dict[int, Dict[str, Any]], nums: List[int],
                puntos: Optional[Dict[Any, float]] = None) -> Tuple[List[Dict[str, Any]], Dict[int, Dict[str, Any]]]:
    """Las preguntas de `nums` (en ese orden) con su clave y, si vienen, sus puntos propios.
    Devuelve copias: el examen original no se toca."""
    por_num: Dict[int, Dict[str, Any]] = {}
    for q in questions:
        n = q.get("num")
        if isinstance(n, int) and not isinstance(n, bool) and n not in por_num:
            por_num[n] = q
    if len(set(nums)) != len(nums):
        raise VersionInvalida("Una versión repite una pregunta.")
    faltan = [n for n in nums if n not in por_num]
    if faltan:
        raise VersionInvalida("La versión pide preguntas que el examen no tiene: " + ", ".join(str(n) for n in faltan[:5]) + ".")
    if not nums:
        raise VersionInvalida("Una versión no tiene preguntas.")
    puntos = puntos or {}
    qs: List[Dict[str, Any]] = []
    clave: Dict[int, Dict[str, Any]] = {}
    for n in nums:
        q = dict(por_num[n])
        p = puntos.get(n, puntos.get(str(n)))
        if p is not None:
            if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or p < 0:
                raise VersionInvalida(f"Los puntos de la pregunta {n} no son válidos.")
            q["points"] = float(p)
        qs.append(q)
        if n in answer_key:
            clave[n] = answer_key[n]
    return qs, clave


def etiqueta_para_archivo(etiqueta: str) -> str:
    """«Versión A» → «A», sin tildes ni caracteres raros (va en el nombre de un archivo)."""
    t = unicodedata.normalize("NFKD", str(etiqueta or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_")[:20] or "X"


def empaquetar(archivos: List[Tuple[str, bytes]]) -> bytes:
    """Un ZIP con los PDF de las versiones (los nombres repetidos se numeran)."""
    salida = io.BytesIO()
    usados: Dict[str, int] = {}
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, datos in archivos:
            k = usados.get(nombre, 0)
            usados[nombre] = k + 1
            if k:
                base, punto, ext = nombre.rpartition(".")
                nombre = f"{base}_{k + 1}.{ext}" if punto else f"{nombre}_{k + 1}"
            z.writestr(nombre, datos)
    return salida.getvalue()
