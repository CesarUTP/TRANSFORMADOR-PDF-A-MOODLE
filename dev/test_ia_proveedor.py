"""
test_ia_proveedor.py — versión 1.9: la capa de proveedor de IA (ia_proveedor,
ia_gemini, ia_reintentos, ia_seleccion, ia_cancelacion, ia_prompts) y la
fachada formatter.

    PYTHONUTF8=1 backend/venv/bin/python dev/test_ia_proveedor.py

Sin red ni Gemini: el proveedor es uno FALSO que implementa la interfaz y se
enchufa por proveedor_actual() (variable CONVERSOR_PROVEEDOR_IA), y las
respuestas HTTP de Gemini se simulan. No toca la clave ni el historial (HOME
va a una carpeta temporal; jamás se importa main).

Qué cubre
  1. Prompts y esquema: SHA-256 de cada texto (no pueden cambiar ni una letra).
  2. El cuerpo que se envía a Gemini es idéntico al de antes.
  3. Errores y motivos de fin normalizados; mensajes en español idénticos.
  4. Reintentos, esperas y cancelación con un proveedor falso.
  5. Una conversión simulada completa con el proveedor falso.
  6. Selección de proveedor por entorno (y rechazo de valores desconocidos).
  7. La fachada formatter y el empaquetado (módulos planos en backend/).
"""

import base64
import hashlib
import io
import json
import logging
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# ── Aislamiento: nada de la máquina real ────────────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="conv ia proveedor "))
os.environ["HOME"] = str(TMP / "home")
os.environ["LOCALAPPDATA"] = str(TMP / "home" / "AppData")
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("XDG_DATA_HOME", None)
os.environ.pop("CONVERSOR_PROVEEDOR_IA", None)

import requests  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from PIL import Image  # noqa: E402

import ayuda_ia  # noqa: E402
import config  # noqa: E402
import formatter  # noqa: E402
import ia_cancelacion  # noqa: E402
import ia_gemini  # noqa: E402
import ia_prompts  # noqa: E402
import ia_proveedor  # noqa: E402
import ia_reintentos  # noqa: E402
import ia_seleccion  # noqa: E402
import pipeline  # noqa: E402
from ia_proveedor import (  # noqa: E402
    ErrorConfiguracionIA, IACuotaError, IAErrorHTTP, IARechazadaError, IASaturadaError, IASinClaveError,
    IASinConexionError, IATimeoutError, ProveedorIA, RespuestaCortada, RespuestaIA,
    RespuestaVacia, SolicitudIA, parte_imagen_b64, parte_texto,
)

for _h in list(logging.getLogger().handlers):
    if getattr(_h, "_conversor_errores", False):
        logging.getLogger().removeHandler(_h)
logging.disable(logging.ERROR)  # los errores provocados a propósito no ensucian la salida

fallas = 0


def ok(cond, msg):
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


def sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


# ═══════════════ 1. Prompts y esquema: byte a byte ══════════════════════════
# Hashes tomados ANTES de partir formatter.py (1.8). Si cambia un solo
# carácter de un prompt o del esquema, esto falla: el contenido de los
# prompts no se toca al refactorizar.
print("Prompts y esquema: SHA-256 idéntico al de la 1.8")
HASHES = {
    "SYSTEM_PROMPT": "a31f91e140b2f2c48463a3716e757c6965ef9223014d500b54890a5a7227e874",
    "SYSTEM_PROMPT_JSON": "e9ae65218c9034e2afef436e72c2cb851a60d5561a8a68d502802ee22690d476",
    "RESPONSE_SCHEMA": "a96327cca175f2c3012c93f52b2aa445dc9d04618d9dff970ff83886a5c28a82",
    "PREFIJO_FALTANTES": "092bc52283fcdf65819c9121eef23752e0e91fb5c665214c33b8566805aefc44",
    "PROMPT_RETRO": "d92380ddc6c74478deaa134b3e06a7d8ce8524cb2edd5856c3103c7223dd1853",
    "PROMPT_REDACCION": "88f64e6f3b75e2fcfb338c96cd91630b5bd9af6888dd9da5dbf159ac24accaf2",
}
for nombre, esperado in HASHES.items():
    valor = getattr(ia_prompts, nombre)
    texto = json.dumps(valor, ensure_ascii=False, sort_keys=False) if isinstance(valor, dict) else valor
    ok(sha(texto) == esperado, f"{nombre}: contenido idéntico")
ok(ayuda_ia.PROMPT_RETRO is ia_prompts.PROMPT_RETRO and ayuda_ia.PROMPT_REDACCION is ia_prompts.PROMPT_REDACCION,
   "ayuda_ia usa los prompts de ia_prompts (un solo texto)")
ok(formatter._PREFIJO_FALTANTES is ia_prompts.PREFIJO_FALTANTES, "formatter conserva _PREFIJO_FALTANTES")
ok(config.SYSTEM_PROMPT is ia_prompts.SYSTEM_PROMPT and config.SYSTEM_PROMPT_JSON is ia_prompts.SYSTEM_PROMPT_JSON
   and config.RESPONSE_SCHEMA is ia_prompts.RESPONSE_SCHEMA, "`from config import SYSTEM_PROMPT…` sigue funcionando")
try:
    config.NO_EXISTE  # noqa: B018
    ok(False, "config sigue rechazando nombres que no existen")
except AttributeError:
    ok(True, "config sigue rechazando nombres que no existen")
ok(config.NOT_AN_EXAM_SENTINEL in ia_prompts.SYSTEM_PROMPT, "el prompt de texto menciona el centinela de «no es un examen»")

# ═══════════════ 2. El cuerpo para Gemini no cambió ═════════════════════════
print("Cuerpo de la petición a Gemini: idéntico al de la 1.8")
_img = Image.new("RGB", (6, 6), (200, 30, 30))


def _imagen_antigua(img):
    """Cómo codificaba formatter._image_part una página en la 1.8."""
    buf = io.BytesIO()
    img.save(buf, format="webp", lossless=True)
    return {"inline_data": {"mime_type": "image/webp", "data": base64.b64encode(buf.getvalue()).decode()}}


def _cuerpo_antiguo(system_prompt, raw_text, page_images, generation_config):
    """Copia de formatter._build_request de la 1.8."""
    parts = [{"text": raw_text}] + [_imagen_antigua(i) for i in (page_images or [])]
    return {"systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation_config}


sol = ia_seleccion.armar_solicitud(ia_prompts.SYSTEM_PROMPT, "texto", [_img], temperatura=config.GEMINI_TEMPERATURE)
nuevo = ia_gemini.construir_cuerpo(sol.partes, instruccion=sol.instruccion, esquema=sol.esquema,
                                   temperatura=sol.temperatura, max_tokens=sol.max_tokens)
viejo = _cuerpo_antiguo(ia_prompts.SYSTEM_PROMPT, "texto", [_img], {"temperature": config.GEMINI_TEMPERATURE})
ok(json.dumps(nuevo) == json.dumps(viejo), "modo texto: mismo JSON (también el orden de las claves)")

sol = ia_seleccion.armar_solicitud(ia_prompts.SYSTEM_PROMPT_JSON, "texto", None, temperatura=config.GEMINI_TEMPERATURE,
                                   esquema=ia_prompts.RESPONSE_SCHEMA, max_tokens=config.GEMINI_MAX_OUTPUT_TOKENS)
nuevo = ia_gemini.construir_cuerpo(sol.partes, instruccion=sol.instruccion, esquema=sol.esquema,
                                   temperatura=sol.temperatura, max_tokens=sol.max_tokens)
viejo = _cuerpo_antiguo(ia_prompts.SYSTEM_PROMPT_JSON, "texto", None, {
    "temperature": config.GEMINI_TEMPERATURE, "responseMimeType": "application/json",
    "responseSchema": ia_prompts.RESPONSE_SCHEMA, "maxOutputTokens": config.GEMINI_MAX_OUTPUT_TOKENS})
ok(json.dumps(nuevo) == json.dumps(viejo), "modo JSON: mismo JSON (esquema y tope de tokens incluidos)")

nuevo = ia_gemini.construir_cuerpo([parte_texto("Hola"), parte_imagen_b64("image/png", "iVBORw0KGgo=")],
                                   instruccion="P", temperatura=0.3, max_tokens=4096)
ok(json.dumps(nuevo) == json.dumps({
    "systemInstruction": {"parts": [{"text": "P"}]},
    "contents": [{"role": "user", "parts": [{"text": "Hola"}, {"inline_data": {"mime_type": "image/png", "data": "iVBORw0KGgo="}}]}],
    "generationConfig": {"temperature": 0.3, "maxOutputTokens": 4096}}), "botones de IA del editor: mismo JSON")
ok(formatter._image_part(_img) is formatter._image_part(_img), "una página se codifica una sola vez (caché por imagen)")

# ═══════════════ 3. Errores y motivos de fin normalizados ═══════════════════
print("Motivos de fin normalizados")
for crudo, esperado in [("STOP", "STOP"), ("stop", "STOP"), ("end_turn", "STOP"), ("MAX_TOKENS", "MAX_TOKENS"),
                        ("length", "MAX_TOKENS"), ("max_output_tokens", "MAX_TOKENS"), ("SAFETY", "SAFETY"),
                        ("recitation", "RECITATION"), ("", ""), (None, "")]:
    ok(ia_proveedor.normalizar_finish(crudo) == esperado, f"finish {crudo!r} → {esperado!r}")
r = RespuestaIA(text="x", finish_reason="STOP", prompt_tokens=3, output_tokens=4)
ok(r.texto == "x" and r.uso == {"prompt_tokens": 3, "output_tokens": 4}, "RespuestaIA: texto y uso")
ok(formatter._GenResult is RespuestaIA, "formatter._GenResult sigue existiendo (es RespuestaIA)")

print("Errores HTTP de Gemini → clases normalizadas")
casos = [(429, IACuotaError), (500, IASaturadaError), (502, IASaturadaError), (503, IASaturadaError),
         (504, IASaturadaError), (400, IARechazadaError), (401, IARechazadaError), (403, IARechazadaError),
         (404, IARechazadaError)]
for codigo, clase in casos:
    e = ia_gemini._http_error(codigo, "cuerpo")
    ok(type(e) is clase or isinstance(e, clase), f"HTTP {codigo} → {clase.__name__}")
e = ia_gemini._http_error(418, "tetera")
ok(type(e) is IAErrorHTTP and e.code == 418 and str(e) == "418 tetera", "otro código: IAErrorHTTP genérico, texto «código cuerpo»")
e = ia_gemini._http_error(429, "RESOURCE_EXHAUSTED ... PerDay ... Please retry in 38.7s")
ok(e.diaria is True and abs(e.espera_segundos - 39.7) < 1e-6, "429 con «PerDay»: cuota diaria; espera = lo que pide Google + 1 s")
e = ia_gemini._http_error(429, "Please retry in 400s")
ok(e.diaria is False and e.espera_segundos == 65.0, "429 por minuto: espera tope de 65 s")
e = ia_gemini._http_error(429, "sin dato")
ok(e.espera_segundos == 30.0, "429 sin «retry in»: 30 s")
ok(isinstance(formatter.GeminiQuotaError(429, "x"), IACuotaError) and formatter.GeminiOverloadedError is IASaturadaError
   and formatter.GeminiRejectedError is IARechazadaError and formatter.GeminiHTTPError is IAErrorHTTP,
   "los nombres Gemini*Error de siempre siguen en formatter")
ok(issubclass(IATimeoutError, TimeoutError) and issubclass(IASinConexionError, ConnectionError)
   and issubclass(RespuestaVacia, RuntimeError) and issubclass(RespuestaCortada, RuntimeError),
   "los errores de red/respuesta siguen siendo TimeoutError / ConnectionError / RuntimeError")


class _FakeResp:
    """Respuesta HTTP en streaming (como requests con stream=True)."""

    def __init__(self, cuerpo: bytes = b"", status=200):
        self.cuerpo, self.status_code = cuerpo, status
        self.encoding = None
        self.text = cuerpo.decode("utf-8", "replace")
        self.cerrada = False

    def iter_lines(self, chunk_size=512, decode_unicode=False, delimiter=None):
        for ln in self.cuerpo.split(delimiter or b"\n"):
            yield ln

    def close(self):
        self.cerrada = True


def _sse(*eventos) -> bytes:
    return b"".join(b"data: " + json.dumps(e, ensure_ascii=False).encode("utf-8") + b"\n\n" for e in eventos)


def _evento(texto, finish=None, tokens=(5, 7)):
    cand = {"content": {"parts": [{"text": texto}]}}
    if finish:
        cand["finishReason"] = finish
    return {"candidates": [cand], "usageMetadata": {"promptTokenCount": tokens[0], "candidatesTokenCount": tokens[1]}}


_post_original = requests.post
_key_original = ia_gemini.get_api_key
ia_gemini.get_api_key = lambda: "clave-falsa-de-prueba"


def _con_http(resp):
    requests.post = lambda *a, **k: resp() if callable(resp) else resp


def _llamar_gemini(**kw):
    return ia_gemini.GeminiProveedor().generar([parte_texto("x")], instruccion="i", **kw)


try:
    print("Lectura del stream de Gemini")
    acumulado = []
    _con_http(_FakeResp(_sse(_evento("Hola "), _evento("mundo", "STOP"))))
    r = _llamar_gemini(on_texto=acumulado.append)
    ok(r.text == "Hola mundo" and r.finish_reason == "STOP" and (r.prompt_tokens, r.output_tokens) == (5, 7),
       "texto, finish_reason y uso (tokens) de la respuesta")
    ok(acumulado == ["Hola ", "Hola mundo"], "on_texto recibe el texto ACUMULADO en cada fragmento")
    _con_http(_FakeResp(_sse(_evento("{", "MAX_TOKENS"))))
    ok(_llamar_gemini().finish_reason == "MAX_TOKENS", "MAX_TOKENS se conserva normalizado")
    _con_http(_FakeResp(_sse(_evento("x", "SAFETY"))))
    ok(_llamar_gemini().finish_reason == "SAFETY", "SAFETY pasa tal cual (es el «motivo» que ve el docente)")
    _con_http(_FakeResp(_sse(_evento("sin fin"))))
    try:
        _llamar_gemini()
        ok(False, "sin finishReason")
    except RespuestaCortada:
        ok(True, "sin finishReason: RespuestaCortada")
    _con_http(_FakeResp(_sse({"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}})))
    try:
        _llamar_gemini()
        ok(False, "respuesta vacía")
    except RespuestaVacia as e:
        ok(e.motivo == "PROHIBITED_CONTENT", "respuesta vacía por bloqueo: RespuestaVacia con su motivo")
    _con_http(_FakeResp(_sse(_evento("a"), {"error": {"code": 503, "message": "overloaded"}})))
    try:
        _llamar_gemini()
        ok(False, "error dentro del stream")
    except IASaturadaError:
        ok(True, "un error 503 DENTRO del stream (status 200) también se normaliza")
    for status, clase in [(429, IACuotaError), (503, IASaturadaError), (403, IARechazadaError)]:
        _con_http(_FakeResp(b'{"error": {"message": "no"}}', status=status))
        try:
            _llamar_gemini()
            ok(False, f"HTTP {status}")
        except clase as e:
            ok(e.code == status and "no" in str(e), f"HTTP {status} → {clase.__name__} con el cuerpo en el texto")

    print("Fallos de red de requests → errores normalizados")
    for exc, clase in [(requests.exceptions.ReadTimeout("lento"), IATimeoutError),
                       (requests.exceptions.ConnectTimeout("no conecta"), IASinConexionError),
                       (requests.exceptions.ConnectionError("sin internet"), IASinConexionError)]:
        def _lanza(*a, _e=exc, **k):
            raise _e
        requests.post = _lanza
        try:
            _llamar_gemini()
            ok(False, type(exc).__name__)
        except clase:
            ok(True, f"{type(exc).__name__} → {clase.__name__}")
    ia_gemini.get_api_key = lambda: ""
    try:
        ia_gemini.GeminiProveedor().comprobar_listo()
        ok(False, "sin clave")
    except IASinClaveError as e:
        ok(e.mensaje == config.MISSING_API_KEY_MESSAGE, "sin clave: IASinClaveError con el mensaje de siempre")
finally:
    requests.post = _post_original
    ia_gemini.get_api_key = _key_original


# ═══════════════ Proveedor FALSO ════════════════════════════════════════════
class ProveedorFalso(ProveedorIA):
    """Implementa la interfaz sin red. `guion` es una lista: cada llamada
    consume un elemento; si es una excepción se lanza, si es un str o dict se
    devuelve como texto (dict → JSON), si es un RespuestaIA tal cual."""
    nombre = "falso"

    def __init__(self, guion=None, texto_por_defecto=None):
        self.guion = list(guion or [])
        self.por_defecto = texto_por_defecto
        self.llamadas = []
        self.sin_clave = False

    def comprobar_listo(self):
        if self.sin_clave:
            raise IASinClaveError("Falta la credencial del proveedor falso.")

    def generar(self, partes, *, instruccion="", esquema=None, temperatura=0.0, max_tokens=None, stream=True,
                on_texto=None, timeout=180):
        self.llamadas.append({"partes": list(partes), "instruccion": instruccion, "esquema": esquema,
                              "temperatura": temperatura, "max_tokens": max_tokens, "timeout": timeout})
        ia_cancelacion.comprobar_cancelacion()
        item = self.guion.pop(0) if self.guion else self.por_defecto
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, RespuestaIA):
            return item
        texto = json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else item
        if on_texto:
            for i in range(1, 4):  # llega "en streaming", en tres trozos
                on_texto(texto[: len(texto) * i // 3])
        return RespuestaIA(text=texto, finish_reason="STOP", prompt_tokens=11, output_tokens=22)


_falso_actual = {"p": None}


def enchufar(proveedor):
    """Registra el falso y lo selecciona por la variable de entorno."""
    _falso_actual["p"] = proveedor
    ia_proveedor.registrar_proveedor("falso", lambda: _falso_actual["p"])
    os.environ["CONVERSOR_PROVEEDOR_IA"] = "falso"
    return proveedor


def desenchufar():
    os.environ.pop("CONVERSOR_PROVEEDOR_IA", None)
    ia_proveedor.quitar_proveedor("falso")


_esperar_original = ia_reintentos._esperar
esperas = []
ia_reintentos._esperar = lambda s: esperas.append(s)  # sin esperas reales


def _sol():
    return SolicitudIA(instruccion="i", partes=[parte_texto("x")])


def correr(proveedor, *args, **kw):
    """generar_con_reintentos con el proveedor falso; devuelve (resultado|HTTPException, esperas)."""
    enchufar(proveedor)
    esperas.clear()
    try:
        return ia_reintentos.generar_con_reintentos(*args, **kw), list(esperas)
    except HTTPException as e:
        return e, list(esperas)


# ═══════════════ 4. Reintentos con un proveedor falso ═══════════════════════
print("Reintentos y mensajes (proveedor falso)")
MAXR = config.GEMINI_MAX_RETRIES
try:
    # Sin clave
    p = ProveedorFalso(); p.sin_clave = True
    e, _ = correr(p, _sol(), 1, lambda r: r, 30)
    ok(isinstance(e, HTTPException) and e.status_code == 503 and e.detail == "Falta la credencial del proveedor falso."
       and not p.llamadas, "sin clave: 503 con el mensaje del proveedor, sin llamar")

    # Éxito y registro de llamadas
    ia_reintentos.reset_call_log()
    p = ProveedorFalso(["hola"])
    r, _ = correr(p, _sol(), 1, lambda res: res.text.upper(), 30)
    ok(r == "HOLA" and len(p.llamadas) == 1, "éxito: parse recibe la RespuestaIA")
    log = ia_reintentos.get_call_log()
    ok(len(log) == 1 and log[0]["prompt_tokens"] == 11 and log[0]["output_tokens"] == 22, "get_call_log: tokens de la llamada")

    # Cuota diaria
    p = ProveedorFalso([IACuotaError(429, "PerDay", diaria=True)])
    e, esp = correr(p, _sol(), 1, lambda r: r, 30)
    ok(e.status_code == 503 and e.detail == (
        "Se alcanzó el límite diario de uso del servicio de IA. "
        "Se restablece automáticamente cada día (medianoche, hora del Pacífico). "
        "Si esto ocurre seguido, conviene usar una API key con facturación activada.")
       and len(p.llamadas) == 1 and esp == [], "cuota diaria: mensaje de siempre, sin esperar ni reintentar")

    # Cuota por minuto: espera lo que pide y reintenta sin gastar un intento
    avisos = []
    p = ProveedorFalso([IACuotaError(429, "x", espera_segundos=12.0), "listo"])
    r, esp = correr(p, _sol(), 1, lambda res: res.text, 30, on_retry=avisos.append)
    ok(r == "listo" and esp == [12.0] and len(p.llamadas) == 2, "cuota por minuto: espera exactamente lo que pide y reintenta")
    ok(avisos == ["Límite por minuto del servicio de IA alcanzado: se continúa en 12 s…"], "…y avisa al docente con el texto de siempre")

    # Cuota persistente (cupo de esperas agotado)
    p = ProveedorFalso([IACuotaError(429, "x", espera_segundos=50.0)])
    e, _ = correr(p, _sol(), 1, lambda r: r, 30, quota_waits=1, quota_max_seconds=20)
    ok(e.status_code == 503 and e.detail == "Se alcanzó el límite de uso del servicio de IA. Espera un minuto e intenta de nuevo."
       and len(p.llamadas) == 1, "cuota con espera > tope (botones del editor): 503 sin esperar")

    # Saturación: esperas crecientes 5, 10, 20, 30, 30 y luego se rinde
    p = ProveedorFalso([IASaturadaError(503, "x")] * 10)
    avisos = []
    e, esp = correr(p, _sol(), 1, lambda r: r, 30, on_retry=avisos.append)
    ok(esp == [5, 10, 20, 30, 30] and len(p.llamadas) == 6, f"saturación: esperas 5, 10, 20, 30, 30 ({esp})")
    ok(e.status_code == 503 and e.detail == (
        "El servicio de IA de Google está saturado en este momento (no es un "
        "problema del documento). Intenta de nuevo en unos minutos."), "…y el mensaje final de siempre")
    ok(avisos[0] == "El servicio de IA está saturado; reintentando en 5 s…", "aviso de saturación con el texto de siempre")
    p = ProveedorFalso([IASaturadaError(503, "x")] * 10)
    e, esp = correr(p, _sol(), 1, lambda r: r, 30, overload_waits=(4, 8))
    ok(esp == [4, 8] and len(p.llamadas) == 3, "saturación con esperas cortas (botones del editor): 4 y 8 s")

    # Rechazo
    p = ProveedorFalso([IARechazadaError(403, "no")])
    e, esp = correr(p, _sol(), 1, lambda r: r, 30)
    ok(e.status_code == 502 and e.detail == (
        "Google rechazó tu clave de la API de Gemini (no es válida o fue "
        "revocada). Ábrela desde «Acerca de → API de Gemini» y pega una "
        "clave nueva de https://aistudio.google.com/apikey.") and len(p.llamadas) == 1,
       "401/403: «Google rechazó tu clave…», sin reintentar")
    p = ProveedorFalso([IARechazadaError(404, "no")])
    e, _ = correr(p, _sol(), 1, lambda r: r, 30)
    ok(e.status_code == 502 and e.detail == (
        "El servicio de IA rechazó la solicitud (posible configuración "
        "inválida del modelo o del documento). Detalle técnico: error HTTP 404."), "otros rechazos: «…error HTTP 404.»")

    # Timeout: UN reintento
    p = ProveedorFalso([IATimeoutError("lento")] * 5)
    avisos = []
    e, esp = correr(p, _sol(), 1, lambda r: r, 77, on_retry=avisos.append)
    ok(e.status_code == 503 and len(p.llamadas) == 2 and esp == [config.GEMINI_RETRY_WAIT_SECONDS], "timeout: un solo reintento tras esperar 10 s")
    ok("más de 77 segundos" in e.detail and e.detail.startswith("La IA tardó demasiado en responder"), "…y el mensaje dice el tope")
    ok(avisos == ["La IA tardó demasiado en responder; reintentando una vez…"], "…con el aviso de siempre")
    p = ProveedorFalso([TimeoutError("socket"), TimeoutError("socket")])
    e, _ = correr(p, _sol(), 1, lambda r: r, 30)
    ok(isinstance(e, HTTPException) and len(p.llamadas) == 2, "un TimeoutError genérico se trata igual que IATimeoutError")

    # Sin conexión: todos los intentos
    p = ProveedorFalso([IASinConexionError("dns")] * 5)
    avisos = []
    e, esp = correr(p, _sol(), 1, lambda r: r, 30, on_retry=avisos.append)
    ok(e.status_code == 503 and e.detail == "No se pudo conectar con el servicio de IA de Google. Revisa tu conexión a internet e inténtalo de nuevo."
       and len(p.llamadas) == MAXR, f"sin conexión: {MAXR} intentos y el mensaje de siempre")
    ok(avisos[0] == "No se pudo conectar con el servicio de IA; reintentando…", "…con el aviso de siempre")

    # Respuesta vacía / interrumpida / cortada / JSON inválido
    p = ProveedorFalso([RespuestaVacia("STOP", "PROHIBITED_CONTENT")] * 5)
    e, _ = correr(p, _sol(), 1, lambda r: r, 30)
    ok(e.status_code == 502 and "PROHIBITED_CONTENT" in e.detail and len(p.llamadas) == 2,
       "bloqueo: mensaje con el motivo y UN solo reintento")
    p = ProveedorFalso([RespuestaIA("x", "SAFETY")] * 5)
    e, _ = correr(p, _sol(), 1, lambda r: ia_seleccion.comprobar_finalizacion(r), 30)
    ok(e.status_code == 502 and e.detail.startswith("La IA interrumpió su respuesta antes de terminarla (motivo: SAFETY)")
       and len(p.llamadas) == 2, "SAFETY: «La IA interrumpió…», un solo reintento")
    p = ProveedorFalso([RespuestaIA("{", "MAX_TOKENS")] * 5)
    e, _ = correr(p, _sol(), 1, lambda r: ia_seleccion.comprobar_finalizacion(r), 30)
    ok(e.status_code == 422 and "demasiado largo" in json.dumps(e.detail, ensure_ascii=False) and len(p.llamadas) == 1,
       "MAX_TOKENS: 422 «demasiado largo», sin reintentar")
    p = ProveedorFalso([RespuestaCortada("corta")] * 5)
    e, _ = correr(p, _sol(), 1, lambda r: r, 30)
    ok(e.status_code == 503 and e.detail.startswith("La respuesta de la IA se cortó varias veces") and len(p.llamadas) == MAXR,
       f"cortada: {MAXR} intentos y mensaje de conexión inestable")
    p = ProveedorFalso(["{no es json"] * 5)
    e, _ = correr(p, _sol(), 1, ia_seleccion.parse_structured_response, 30)
    ok(e.status_code == 502 and "no se pudo interpretar" in e.detail and len(p.llamadas) == MAXR, "JSON inválido: reintenta y mensaje veraz")
    p = ProveedorFalso([RuntimeError("raro")] * 5)
    e, _ = correr(p, _sol(), 1, lambda r: r, 30)
    ok(e.status_code == 503 and e.detail.startswith("No se pudo completar la lectura con la IA") and len(p.llamadas) == MAXR,
       "error inesperado: mensaje genérico tras los intentos")

    # Mensajes sobrescritos por el proveedor
    p = ProveedorFalso([IASaturadaError(503, "x")] * 10)
    p.mensajes = {"saturada": "Servidor local ocupado."}
    e, _ = correr(p, _sol(), 1, lambda r: r, 30, overload_waits=())
    ok(e.detail == "Servidor local ocupado.", "un proveedor puede cambiar el texto de sus propios mensajes")

    # Cancelación: Event por hilo
    canc = ia_cancelacion.Cancelacion()
    canc.cancelar()
    ia_cancelacion.usar_cancelacion(canc)
    p = ProveedorFalso(["x"])
    try:
        correr(p, _sol(), 1, lambda r: r, 30)
        ok(False, "cancelada antes de llamar")
    except ia_cancelacion.ConversionCancelada:
        ok(not p.llamadas, "cancelada: ConversionCancelada y NO se llama al proveedor")
    finally:
        ia_cancelacion.usar_cancelacion(None)
    p = ProveedorFalso([ia_cancelacion.ConversionCancelada()])
    try:
        correr(p, _sol(), 1, lambda r: r, 30)
        ok(False, "ConversionCancelada del proveedor")
    except ia_cancelacion.ConversionCancelada:
        ok(len(p.llamadas) == 1, "ConversionCancelada lanzada por el proveedor se propaga sin reintentos")
    ok(formatter.Cancelacion is ia_cancelacion.Cancelacion and formatter.ConversionCancelada is ia_cancelacion.ConversionCancelada
       and formatter.usar_cancelacion is ia_cancelacion.usar_cancelacion, "la fachada exporta la cancelación de siempre")
    # Es por hilo: otra Cancelacion en otro hilo no afecta a este
    visto = {}
    c2 = ia_cancelacion.Cancelacion()

    def _hilo():
        ia_cancelacion.usar_cancelacion(c2)
        visto["hilo"] = ia_cancelacion.cancelacion_actual() is c2
    t = threading.Thread(target=_hilo); t.start(); t.join()
    ok(visto["hilo"] and ia_cancelacion.cancelacion_actual() is None, "la Cancelacion va por hilo (threading.local)")
    t0 = time.monotonic()
    ia_cancelacion.usar_cancelacion(c2)
    threading.Timer(0.2, c2.cancelar).start()
    try:
        ia_cancelacion.esperar(5)
        ok(False, "esperar interrumpible")
    except ia_cancelacion.ConversionCancelada:
        ok(time.monotonic() - t0 < 2, "esperar() se interrumpe al cancelar (Event.wait, no sleep)")
    finally:
        ia_cancelacion.usar_cancelacion(None)
finally:
    desenchufar()

# ═══════════════ 5. Conversión simulada COMPLETA con el proveedor falso ═════
print("Conversión simulada completa con un proveedor falso (sin Gemini)")


def _q(i, enun, ops, marcada=True):
    return {"orden": i, "tipo": "multichoice", "enunciado": enun,
            "opciones": [{"letra_original": l, "texto": t, "correcta": marcada and l == "A"} for l, t in ops],
            "items_izquierda": [], "items_derecha": [], "parejas": [], "huecos": [], "clave_texto": "",
            "respuesta_texto": "", "retroalimentacion": "", "respuesta_marcada": marcada, "origen_tabla": False,
            "pagina": 1, "confianza": "alta"}


def _payload(n=2, marcada=True):
    return {"es_examen": True, "preguntas": [_q(i, f"¿Pregunta número {i}?", [("A", "Sí"), ("B", "No")], marcada)
                                             for i in range(1, n + 1)]}


TXT = ("Pregunta 1: ¿Cuál es la capital de Francia?\nA) París\nB) Madrid\n"
       "Pregunta 2: ¿Cuál es la capital de Italia?\nA) Roma\nB) Milán\n\nRESPUESTAS\n1 A\n2 A\n").encode("utf-8")

_key_pipeline = pipeline.get_api_key
_mode = pipeline.NORMALIZER_MODE
requests.post = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe haber red"))
pipeline.get_api_key = lambda: "clave-falsa"  # _comprobar_entrada de pipeline (hoy comprueba la clave de Gemini)
try:
    # a) pipeline.parse_document, modo JSON, de punta a punta
    pipeline.NORMALIZER_MODE = "json"
    p = enchufar(ProveedorFalso([_payload(2)]))
    eventos = []
    resultado = pipeline.parse_document(TXT, "examen.txt", progress=eventos.append)
    ok(len(resultado["questions"]) == 2, "parse_document (JSON): 2 preguntas salen del proveedor falso")
    ok(len(p.llamadas) == 1, "…con UNA sola llamada al proveedor")
    ll = p.llamadas[0]
    ok(ll["instruccion"] == ia_prompts.SYSTEM_PROMPT_JSON and ll["esquema"] is ia_prompts.RESPONSE_SCHEMA
       and ll["max_tokens"] == config.GEMINI_MAX_OUTPUT_TOKENS and ll["temperatura"] == config.GEMINI_TEMPERATURE
       and ll["timeout"] == config.GEMINI_REQUEST_TIMEOUT_SECONDS_JSON,
       "el proveedor recibe el prompt JSON, el esquema, el tope de tokens, la temperatura y el timeout de siempre")
    ok(ll["partes"][0].texto and not ll["partes"][0].es_imagen, "la primera parte es el texto del documento")
    ok(any(e.get("type") == "progress" or e.get("key") == "ai" for e in eventos if isinstance(e, dict)),
       "el progreso de la IA llega a la pantalla de carga")

    # b) modo texto
    pipeline.NORMALIZER_MODE = "text"
    texto_ia = ("Pregunta 1: ¿Cuál es la capital de Francia?\nA. París\nB. Madrid\n"
                "Pregunta 2: ¿Cuál es la capital de Italia?\nA. Roma\nB. Milán\n\nRESPUESTAS\n1 A\n2 A")
    p = enchufar(ProveedorFalso([texto_ia]))
    avance = []
    texto, reformateado = formatter.verify_and_format("doc original", None, progress=avance.append)
    ok(texto == texto_ia and reformateado is True, "verify_and_format: devuelve el texto de la IA y que se reformateó")
    ok(avance and avance[-1] == 2, f"…y el progreso cuenta las «Pregunta N:» que llegan en streaming ({avance})")
    ok(p.llamadas[0]["instruccion"] == ia_prompts.SYSTEM_PROMPT and p.llamadas[0]["esquema"] is None
       and p.llamadas[0]["max_tokens"] is None and p.llamadas[0]["timeout"] == config.GEMINI_REQUEST_TIMEOUT_SECONDS,
       "modo texto: prompt de texto, sin esquema ni tope, timeout de texto")
    p = enchufar(ProveedorFalso([config.NOT_AN_EXAM_SENTINEL]))
    try:
        formatter.verify_and_format("una presentación", None)
        ok(False, "centinela")
    except HTTPException as e:
        ok(e.status_code == 422 and "no parece ser una prueba" in e.detail["message"] and len(p.llamadas) == 1,
           "el centinela «NO_ES_UNA_PRUEBA» se rechaza con 422, sin reintentar")
    p = enchufar(ProveedorFalso([{"es_examen": False, "preguntas": []}]))
    try:
        formatter.extract_structured("una presentación", None)
        ok(False, "es_examen=false")
    except HTTPException as e:
        ok(e.status_code == 422 and len(p.llamadas) == 1, "JSON con es_examen=false: 422 sin reintentar")

    # c) reintento de calidad: elige por cantidad y luego por ratio, pasando por el proveedor
    avisos = []
    p = enchufar(ProveedorFalso([_payload(3, marcada=False), _payload(2, marcada=False), _payload(3, marcada=True)]))
    r = formatter.extract_structured("t", [_img], permitir_reintento_calidad=True, on_retry=avisos.append)
    ok(len(p.llamadas) == 3 and len(r["preguntas"]) == 3 and r["preguntas"][0]["respuesta_marcada"] is True,
       "calidad: reintenta mientras haya muchos SIN respuesta y se queda con el mejor (más preguntas, luego menos sin respuesta)")
    ok(avisos.count("Verificando la calidad de la lectura de las marcas de color; releyendo el documento…") == 2,
       "…avisando al docente en cada relectura")
    ok(any(parte.es_imagen for parte in p.llamadas[0]["partes"]), "las páginas viajan como ParteIA de imagen (WebP)")
    p = enchufar(ProveedorFalso([_payload(3, marcada=False), _payload(2, marcada=True)]))
    r = formatter.extract_structured("t", [_img], permitir_reintento_calidad=True)
    ok(len(p.llamadas) == 2 and len(r["preguntas"]) == 3 and r["preguntas"][0]["respuesta_marcada"] is False,
       "calidad: se elige por CANTIDAD antes que por menos «sin respuesta» (el intento que omite preguntas no gana)")
    p = enchufar(ProveedorFalso([_payload(3, marcada=False)] * 3))
    formatter.extract_structured("t", [_img], permitir_reintento_calidad=False)
    ok(len(p.llamadas) == 1, "sin marca de respuestas en el documento: UNA sola llamada aunque haya imágenes")
    p = enchufar(ProveedorFalso([_payload(3, marcada=False), IASinConexionError("cae"), IASinConexionError("cae"),
                                 IASinConexionError("cae")]))
    r = formatter.extract_structured("t", [_img], permitir_reintento_calidad=True)
    ok(len(r["preguntas"]) == 3, "calidad: si la relectura falla del todo, se conserva el mejor resultado ya obtenido")
    p = enchufar(ProveedorFalso([IASinConexionError("cae")] * 3))
    try:
        formatter.extract_structured("t", [_img], permitir_reintento_calidad=True)
        ok(False, "sin resultado previo")
    except HTTPException as e:
        ok(e.status_code == 503, "…pero sin ningún resultado previo el error se propaga")

    # d) preguntas omitidas
    p = enchufar(ProveedorFalso([_payload(2)]))
    preguntas = pipeline.extract_missing(["17. Del siguiente código…", "18. ¿Qué imprime?"], None)
    ok([q["orden"] for q in preguntas] == [1, 2], "extract_missing: devuelve las preguntas tal cual, con su «orden»")
    ll = p.llamadas[0]
    ok(ll["instruccion"] == ia_prompts.PREFIJO_FALTANTES + ia_prompts.SYSTEM_PROMPT_JSON
       and ll["partes"][0].texto.startswith("=== FRAGMENTO 1 ===\n17. Del siguiente código…"),
       "extract_missing: prefijo de omitidas + prompt JSON, fragmentos numerados")
    p = enchufar(ProveedorFalso([IASaturadaError(503, "x")] * 10))
    ok(pipeline.extract_missing(["x"], None) == [] and len(p.llamadas) == 6, "extract_missing: «mejor esfuerzo», cualquier fallo → []")
    ok(pipeline.extract_missing([], None) == [], "extract_missing sin fragmentos: no llama a nadie")
    p = enchufar(ProveedorFalso([ia_cancelacion.ConversionCancelada()]))
    try:
        pipeline.extract_missing(["x"], None)
        ok(False, "cancelar en omitidas")
    except ia_cancelacion.ConversionCancelada:
        ok(True, "extract_missing: cancelar sí se propaga")

    # e) botones de IA del editor
    p = enchufar(ProveedorFalso(["Porque la suma de 1 + 1 da 2."]))
    fb = ayuda_ia.generar({"type": "essay", "data": {"stem": "¿Cuánto es 1+1?",
                                                    "images": [{"mime": "image/png", "b64": "iVBORw0KGgo="}]}}, None)
    ll = p.llamadas[0]
    ok(fb == "Porque la suma de 1 + 1 da 2.", "«Escribir con IA» funciona con el proveedor falso")
    ok(ll["instruccion"] == ia_prompts.PROMPT_RETRO and ll["temperatura"] == 0.3 and ll["max_tokens"] == 4096
       and ll["timeout"] == 60 and ll["esquema"] is None, "…con el prompt, temperatura, tope y timeout de siempre")
    ok(len(ll["partes"]) == 2 and ll["partes"][1].es_imagen and ll["partes"][1].mime == "image/png",
       "…y las imágenes de la pregunta viajan como ParteIA")
    p = enchufar(ProveedorFalso([IASaturadaError(503, "x")] * 10))
    try:
        ayuda_ia.generar({"type": "essay", "data": {"stem": "¿Cuánto es 1+1?"}}, None)
        ok(False, "saturación en el editor")
    except HTTPException as e:
        ok(len(p.llamadas) == 3, "botones del editor: solo 2 esperas cortas ante saturación (3 llamadas)")
    p = enchufar(ProveedorFalso([RespuestaIA("¿Cuál es la capi", "MAX_TOKENS")]))
    try:
        ayuda_ia.mejorar_enunciado({"type": "essay", "data": {"stem": "cual es la capital de francia"}})
        ok(False, "respuesta cortada")
    except HTTPException as e:
        ok(e.status_code == 502 and "no alcanzó a terminar" in e.detail, "«Mejorar redacción»: un MAX_TOKENS normalizado no se aplica")
    p = enchufar(ProveedorFalso(["¿Cuál es la capital de Francia?"]))
    r = ayuda_ia.mejorar_enunciado({"type": "essay", "data": {"stem": "cual es la capital de francia"}})
    ok(r == {"enunciado": "¿Cuál es la capital de Francia?", "cambio": True}
       and p.llamadas[0]["instruccion"] == ia_prompts.PROMPT_REDACCION and p.llamadas[0]["temperatura"] == 0.2
       and p.llamadas[0]["max_tokens"] == 8192, "«Mejorar redacción» con el proveedor falso")
finally:
    desenchufar()
    requests.post = _post_original
    pipeline.get_api_key = _key_pipeline
    pipeline.NORMALIZER_MODE = _mode
    ia_reintentos._esperar = _esperar_original

# ═══════════════ 6. Selección del proveedor por entorno ═════════════════════
print("Selección del proveedor (CONVERSOR_PROVEEDOR_IA)")
os.environ.pop("CONVERSOR_PROVEEDOR_IA", None)
ok(config.IA_PROVEEDOR_POR_DEFECTO == "gemini" and config.IA_PROVEEDOR_VARIABLE == "CONVERSOR_PROVEEDOR_IA",
   "constantes de config: por defecto «gemini», variable CONVERSOR_PROVEEDOR_IA")
ok(ia_proveedor.nombre_configurado() == "gemini", "sin variable: «gemini»")
p0 = ia_proveedor.proveedor_actual()
ok(isinstance(p0, ia_gemini.GeminiProveedor) and p0.nombre == "gemini", "por defecto, proveedor_actual() es Gemini")
ok(ia_proveedor.proveedor_actual() is p0, "la instancia se reutiliza")
for valor in ("gemini", "GEMINI", "  Gemini  "):
    os.environ["CONVERSOR_PROVEEDOR_IA"] = valor
    ok(isinstance(ia_proveedor.proveedor_actual(), ia_gemini.GeminiProveedor), f"valor {valor!r} → Gemini")
os.environ["CONVERSOR_PROVEEDOR_IA"] = ""
ok(isinstance(ia_proveedor.proveedor_actual(), ia_gemini.GeminiProveedor), "variable vacía → el valor por defecto")

os.environ["CONVERSOR_PROVEEDOR_IA"] = "llama-local"
try:
    ia_proveedor.proveedor_actual()
    ok(False, "proveedor desconocido")
except ErrorConfiguracionIA as e:
    msg = str(e)
    ok("llama-local" in msg and "CONVERSOR_PROVEEDOR_IA" in msg and "gemini" in msg and "desconocido" in msg,
       f"valor desconocido: ErrorConfiguracionIA con mensaje claro ({msg})")
ok(ia_proveedor.proveedores_disponibles() == ["gemini"], "proveedores_disponibles(): solo gemini (no se agregan proveedores reales nuevos)")
try:
    ia_reintentos.generar_con_reintentos(_sol(), 1, lambda r: r, 30)
    ok(False, "la conversión con un proveedor desconocido")
except HTTPException as e:
    ok(e.status_code == 503 and "llama-local" in e.detail, "en una conversión, el valor desconocido es un 503 con ese mensaje (no un traceback)")

enchufar(ProveedorFalso())
ok(isinstance(ia_proveedor.proveedor_actual(), ProveedorFalso), "registrar_proveedor + variable: proveedor_actual() devuelve el falso")
_otra = ProveedorFalso()
ia_proveedor.registrar_proveedor("falso", lambda: _otra)
ok(ia_proveedor.proveedor_actual() is _otra, "volver a registrar el mismo nombre reemplaza al anterior (sin instancia vieja en caché)")
desenchufar()
ok("falso" not in ia_proveedor.proveedores_disponibles(), "quitar_proveedor lo retira")
os.environ.pop("CONVERSOR_PROVEEDOR_IA", None)
try:
    ProveedorIA().generar([])
    ok(False, "la interfaz base")
except NotImplementedError:
    ok(True, "ProveedorIA.generar es abstracto")

# ═══════════════ 7. Fachada y empaquetado ═══════════════════════════════════
print("Fachada formatter y empaquetado")
NOMBRES = ["verify_and_format", "extract_structured", "extract_missing", "comprobar_cancelacion", "Cancelacion",
           "usar_cancelacion", "ConversionCancelada", "reset_call_log", "get_call_log", "_stream_generate",
           "_post", "_generate_with_retries", "_call_gemini_with_retries", "_parse_structured_response",
           "_progress_counter", "_image_part", "_partes_imagen", "_esperar", "_throttle", "_notify", "_fallo_final",
           "_comprobar_finalizacion", "_not_an_exam_error", "_demasiado_largo_error", "_http_error",
           "_quota_retry_seconds", "_record_call", "_OVERLOAD_WAITS", "_sin_respuesta_ratio",
           "_contar_preguntas_texto", "_unanswered_ratio", "RespuestaVacia", "RespuestaCortada",
           "RespuestaInterrumpida", "GeminiHTTPError", "GeminiQuotaError", "GeminiOverloadedError",
           "GeminiRejectedError", "_GenResult", "ProgressFn", "GEMINI_MAX_RETRIES"]
faltan = [n for n in NOMBRES if not hasattr(formatter, n)]
ok(not faltan, f"la fachada conserva todos los nombres que usan pipeline, main, ayuda_ia, eval y las pruebas ({faltan})")
ok(pipeline.verify_and_format is formatter.verify_and_format and pipeline.extract_structured is formatter.extract_structured
   and pipeline.extract_missing is formatter.extract_missing, "pipeline importa de formatter las mismas funciones")
ok(formatter._sin_respuesta_ratio("RESPUESTAS\n1 A\n2 SIN_RESPUESTA") == 0.5 and formatter._contar_preguntas_texto("Pregunta 1: a\nPregunta 2: b") == 2,
   "las medidas de calidad siguen igual")
ok(formatter._unanswered_ratio({"preguntas": [{"tipo": "multichoice", "respuesta_marcada": False}, {"tipo": "essay"},
                                                {"tipo": "multichoice", "respuesta_marcada": True}]}) == 0.5,
   "ratio estructurado: ignora los ensayos")
cuenta = []
f = formatter._progress_counter(r"(?m)^Pregunta\s+\d+:", cuenta.append)
f("Pregunta 1: a\n"); f("Pregunta 1: a\nPregunta 2: b"); f("Pregunta 1: a\nPregunta 2: b\nxx")
ok(cuenta == [1, 2], "el contador de progreso avisa solo cuando cambia")

backend = ROOT / "backend"
modulos = sorted(p.name for p in backend.glob("ia_*.py"))
ok(modulos == ["ia_cancelacion.py", "ia_gemini.py", "ia_prompts.py", "ia_proveedor.py", "ia_reintentos.py", "ia_seleccion.py"],
   f"los módulos de la capa de IA son archivos planos de backend/ ({modulos})")
paquetes = [p.name for p in backend.iterdir() if p.is_dir() and (p.name.startswith("ia_") or (p / "__init__.py").exists())
            and p.name not in ("venv", "__pycache__")]
ok(not paquetes, "ninguna subcarpeta/paquete en backend/ (dev/sync_ejecutable.py solo copia backend/*.py)")
fuente = (backend / "ia_proveedor.py").read_text(encoding="utf-8")
ok("from ia_gemini import GeminiProveedor" in fuente and "importlib" not in fuente,
   "ia_proveedor importa ia_gemini con un `import` explícito (PyInstaller lo detecta; nada de importlib por nombre)")
ok(all("import requests" not in (backend / n).read_text(encoding="utf-8")
       for n in ("ia_reintentos.py", "ia_seleccion.py", "ayuda_ia.py", "formatter.py", "ia_proveedor.py")),
   "solo ia_gemini habla HTTP: reintentos, selección, formatter y ayuda_ia ya no importan requests")

print()
print("TODO OK" if not fallas else f"{fallas} FALLA(S)")
sys.exit(1 if fallas else 0)
