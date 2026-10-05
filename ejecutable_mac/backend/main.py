"""
main.py — creación de la aplicación FastAPI (Conversor a Moodle XML).

Aquí solo vive lo que arma la app: el middleware de seguridad (token por
arranque, Host/Origin, CSP; ver seguridad.py), el manejo de errores de
validación, el arranque, la interfaz estática y el montaje de las rutas.
Los endpoints están por tema (cada uno es un APIRouter sin prefijo):

  rutas_convertir.py   /api/check_special_cases, /api/parse*, /api/normalize_with_ai*
  rutas_xml.py         /api/generate_xml
  rutas_pdf.py         /api/exportar_pdf
  rutas_historial.py   /api/history*
  rutas_ayuda.py       /api/retroalimentacion, /api/mejorar_enunciado
  rutas_clave.py       /api/salud, /api/actualizacion, /api/acerca, /api/api-key

Para agregar un endpoint nuevo: un rutas_<tema>.py plano (sin subcarpetas:
dev/sync_ejecutable.py solo copia backend/*.py de primer nivel) con su
`router`, y una línea `app.include_router(...)` abajo. El middleware cubre
toda ruta que cuelgue de `app`; dev/test_seguridad.py (sección «Rutas») lo comprueba.

Los helpers compartidos están en estado_servidor.py y se re-exportan aquí
con sus nombres de siempre (main._CUPOS_CONVERSION, main._evento_ndjson, …).
"""

import logging
import math
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import APP_VERSION, SERVER_PORT
import seguridad
from database import get_db_path, init_db

# Re-exportados: las pruebas y herramientas los usan como main.X.
from estado_servidor import (  # noqa: F401
    ERROR_LOG_PATH, MAX_AVISOS_CABECERA, _CUPOS_CONVERSION, _CUPOS_IA_PUNTUAL,
    _ESPERA_CUPO_PUNTUAL_S, _RespuestaCancelable, _acepta_ia_cache, _avisos_para_cabecera,
    _con_cupo, _con_cupo_puntual, _configurar_log_de_errores, _content_disposition,
    _detalle_tecnico, _evento_ndjson, _ndjson_progress_stream, _nombre_nfc,
)
import rutas_ayuda
import rutas_clave
import rutas_convertir
import rutas_historial
import rutas_original
import rutas_pdf
import rutas_xml

logger = logging.getLogger(__name__)

# Sin /docs, /redoc ni /openapi.json: son páginas de desarrollo que listan toda
# la API y no las usa nadie; una app de escritorio no debe publicarlas.
app = FastAPI(title="PDF → Moodle XML", version=APP_VERSION,
              docs_url=None, redoc_url=None, openapi_url=None)

# Sin CORS: la interfaz se sirve desde este mismo servidor, así que ninguna
# otra página necesita (ni debe poder) leer sus respuestas. Host, Origin,
# token por arranque, tamaño máximo y CSP: ver seguridad.py.
app.add_middleware(seguridad.SoloLaApp)


def _sin_infinito(obj):
    """Reemplaza Infinity/NaN por su texto antes de volver a JSON: un valor
    inválido que el docente (o una petición manual) mandó en el cuerpo
    vuelve TAL CUAL dentro del detalle del error 422 de FastAPI — y
    Starlette rechaza a su vez ESE JSON de salida porque no admite
    Infinity/NaN, así que el 422 legible se convertía en un 500 sin
    detalle."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _sin_infinito(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sin_infinito(v) for v in obj]
    return obj


@app.exception_handler(RequestValidationError)
async def _error_de_validacion(request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": _sin_infinito(exc.errors())})


@app.on_event("startup")
def startup_event():
    # El historial es secundario: si no se puede preparar, la app arranca igual
    # (convertir y descargar no dependen de él) y el motivo queda en el
    # registro; las pantallas del historial y el guardado avisan por su lado.
    try:
        if init_db() is False:
            logger.error("No se pudo preparar la base del historial en %s; la app arranca sin historial.", get_db_path())
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo preparar la base del historial; la app arranca sin historial.")
    if not seguridad.EN_LAUNCHER:
        # Arrancado a mano (uvicorn, ver README): sin el token en la URL la
        # interfaz no puede usar la API.
        print(f"\n  Abre la app en: http://127.0.0.1:{SERVER_PORT}/#t={seguridad.TOKEN}\n"
              "  (si arrancaste uvicorn con otro --port, cambia el número)\n", flush=True)


# ── Rutas por tema ──────────────────────────────────────────────────────────
app.include_router(rutas_clave.router)       # /api/salud, /api/actualizacion, /api/acerca, /api/api-key
app.include_router(rutas_convertir.router)   # /api/check_special_cases, /api/parse*, /api/normalize_with_ai*
app.include_router(rutas_xml.router)         # /api/generate_xml
app.include_router(rutas_pdf.router)         # /api/exportar_pdf
app.include_router(rutas_historial.router)   # /api/history*
app.include_router(rutas_ayuda.router)       # /api/retroalimentacion, /api/mejorar_enunciado, /api/sugerir_respuesta
app.include_router(rutas_original.router)    # /api/original/{id}/pagina/{n}

# ── Serve frontend static files ─────────────────────────────────────────────
# Works both in development (relative path) and inside a PyInstaller bundle.
def _frontend_dir() -> Path:
    if getattr(sys, "frozen", False):
        # Running as a PyInstaller bundle
        return Path(sys._MEIPASS) / "frontend"
    # Running as normal Python
    return Path(__file__).parent.parent / "frontend"

_fe = _frontend_dir()
if _fe.exists():
    app.mount("/static", StaticFiles(directory=str(_fe)), name="static")
    # index.html se sirve en "/", así que sus rutas relativas ("css/base.css",
    # "js/app.js") caen en la raíz: cada carpeta del frontend se monta ahí.
    for _sub in ("css", "js", "img", "fonts", "legal"):
        _dir = _fe / _sub
        if _dir.is_dir():
            app.mount(f"/{_sub}", StaticFiles(directory=str(_dir)), name=_sub)

@app.get("/", include_in_schema=False)
async def serve_index():
    index = _frontend_dir() / "index.html"
    return FileResponse(str(index))
