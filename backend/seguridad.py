"""
seguridad.py — quién puede hablar con el servidor local.

El servidor escucha en 127.0.0.1, pero eso no basta: cualquier página web
abierta en el navegador (o cualquier programa del equipo) puede enviarle
peticiones. Antes bastaba con eso para leer o borrar el historial, gastar
la cuota de Gemini del docente o guardar HTML malicioso en una revisión.

Reglas, en un solo middleware para todas las rutas:

  1. Host permitido: solo 127.0.0.1 o localhost con el puerto real del
     servidor. Corta el "DNS rebinding" (un dominio ajeno que apunta a
     127.0.0.1 llega con su propio nombre en Host).
  2. Origin, si viene, tiene que ser la propia app.
  3. Toda ruta /api/ exige la cabecera X-Conversor-Token con el token de
     ESTE arranque. El launcher lo genera y se lo pasa a la ventana en el
     fragmento de la URL (#t=…), que nunca viaja al servidor ni queda en
     ningún registro; ninguna otra página puede leerlo.
  4. Cuerpo de petición con tamaño máximo.

Además, cada respuesta lleva una Content-Security-Policy: aunque algo
lograra colar HTML en la página, el navegador no ejecuta scripts en línea
ni scripts de otros servidores.
"""

import hashlib
import hmac
import json
import os
import secrets
import sys

# En desarrollo (uvicorn a mano, ver README) se puede fijar el token con
# CONVERSOR_TOKEN para que no cambie en cada recarga. El ejecutable siempre
# genera uno nuevo.
_token_dev = None if getattr(sys, "frozen", False) else os.environ.get("CONVERSOR_TOKEN")
TOKEN: str = _token_dev or secrets.token_urlsafe(32)

# El launcher lo pone en True: entonces no hace falta avisar la URL con el
# token por consola (ver main.startup_event).
EN_LAUNCHER = False

CABECERA_TOKEN = b"x-conversor-token"
HOSTS_PERMITIDOS = ("127.0.0.1", "localhost")

# Ruta que el launcher usa para confirmar que quien responde en el puerto
# es ESTE servidor (no necesita el token: responde una firma con él).
RUTA_SALUD = "/api/salud"

# Un examen en PDF, aun con imágenes, pesa unos pocos MB.
MAX_CUERPO_BYTES = 40 * 1024 * 1024

# 'unsafe-eval' solo porque pywebview arma window.pywebview.api con
# new Function(); los scripts en línea (onclick="…", <script>…</script>)
# siguen prohibidos, que es lo que frena un HTML inyectado.
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-eval'",
    "style-src 'self' 'unsafe-inline'",
    "font-src 'self'",
    "img-src 'self' data: blob:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'none'",
])


def firma_salud(nonce: str) -> str:
    return hmac.new(TOKEN.encode(), nonce.encode(), hashlib.sha256).hexdigest()


def token_valido(valor: str) -> bool:
    return hmac.compare_digest(valor.encode(), TOKEN.encode())


async def _responder(send, status: int, detalle: str) -> None:
    cuerpo = json.dumps({"detail": detalle}, ensure_ascii=False).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(cuerpo)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": cuerpo})


class SoloLaApp:
    """Middleware ASGI (no BaseHTTPMiddleware: no interfiere con las
    respuestas en streaming de /api/*_stream)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        cabeceras = {}
        for k, v in scope.get("headers", []):
            cabeceras.setdefault(k, v.decode("latin-1"))

        puerto = (scope.get("server") or (None, None))[1]
        permitidos = {f"{h}:{puerto}" for h in HOSTS_PERMITIDOS}
        host = cabeceras.get(b"host", "")
        if host not in permitidos:
            return await _responder(send, 400, "Host no permitido")

        origen = cabeceras.get(b"origin")
        if origen is not None and origen not in {f"http://{h}" for h in permitidos}:
            return await _responder(send, 403, "Origen no permitido")

        ruta = scope.get("path", "")
        if ruta.startswith("/api/") and ruta != RUTA_SALUD:
            if not token_valido(cabeceras.get(CABECERA_TOKEN, "")):
                return await _responder(send, 401, "Petición no autorizada. Cierra y vuelve a abrir la aplicación.")

        if scope.get("method") in ("POST", "PUT", "PATCH"):
            largo = cabeceras.get(b"content-length")
            if largo is None or not largo.isdigit():
                return await _responder(send, 411, "Falta el tamaño de la petición.")
            if int(largo) > MAX_CUERPO_BYTES:
                return await _responder(send, 413, (
                    f"El archivo es demasiado grande (máximo {MAX_CUERPO_BYTES // (1024 * 1024)} MB)."))

        async def enviar(mensaje):
            if mensaje["type"] == "http.response.start":
                mensaje.setdefault("headers", [])
                mensaje["headers"] = list(mensaje["headers"]) + [
                    (b"content-security-policy", CSP.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                ]
            await send(mensaje)

        await self.app(scope, receive, enviar)
