"""
actualizaciones.py — ¿hay una versión más nueva de la app?

Al arrancar, la interfaz pregunta a /api/actualizacion; aquí se descarga
un JSON pequeño (config.URL_ACTUALIZACIONES) con esta forma:

    {"version": "1.3", "url": "https://github.com/…/releases/…", "notas": "…"}

Todo lo que viene de afuera se trata como no confiable: tamaño máximo,
versión con formato numérico, enlace solo dentro de PREFIJO_DESCARGAS y
notas recortadas (la interfaz además las muestra como texto, no HTML).
Cualquier fallo (sin internet, 404, JSON raro) equivale a "no hay nada
nuevo": el aviso es una ayuda, nunca debe molestar ni bloquear.
"""

import json
import logging
import re

import requests

from config import APP_VERSION, PREFIJO_DESCARGAS, URL_ACTUALIZACIONES

logger = logging.getLogger(__name__)

_MAX_BYTES = 16 * 1024
_VERSION = re.compile(r"\d{1,4}(\.\d{1,4}){0,3}")
_cache: dict | None = None


def _tupla(version: str) -> tuple:
    return tuple(int(p) for p in version.split("."))


def _consultar() -> dict:
    sin_novedad = {"hay": False, "actual": APP_VERSION}
    try:
        r = requests.get(URL_ACTUALIZACIONES, timeout=4, stream=True, allow_redirects=False)
        try:
            if r.status_code != 200:
                return sin_novedad
            cuerpo = r.raw.read(_MAX_BYTES + 1, decode_content=True)
        finally:
            r.close()
        if len(cuerpo) > _MAX_BYTES:
            return sin_novedad
        datos = json.loads(cuerpo.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — sin internet, 404, JSON inválido…
        logger.info("No se pudo comprobar si hay actualizaciones: %s", type(exc).__name__)
        return sin_novedad
    if not isinstance(datos, dict):
        return sin_novedad
    version, url = str(datos.get("version", "")), str(datos.get("url", ""))
    if not _VERSION.fullmatch(version) or not url.startswith(PREFIJO_DESCARGAS) or len(url) > 300:
        return sin_novedad
    if _tupla(version) <= _tupla(APP_VERSION):
        return sin_novedad
    return {"hay": True, "actual": APP_VERSION, "version": version, "url": url,
            "notas": str(datos.get("notas", ""))[:300]}


def comprobar() -> dict:
    """Una sola consulta por arranque."""
    global _cache
    if _cache is None:
        _cache = _consultar()
    return _cache
