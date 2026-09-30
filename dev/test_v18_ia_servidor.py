"""
test_v18_ia_servidor.py — versión 1.8: IA, servidor y pipeline (cancelar de
verdad, reintentos, mensajes de error, «Mejorar redacción», avisos de páginas
y guardado del historial no fatal).

    PYTHONUTF8=1 backend/venv/bin/python dev/test_v18_ia_servidor.py

Sin red ni Gemini real: la IA y las respuestas HTTP se simulan. La base del
historial y la clave NO se tocan: HOME va a una carpeta temporal y
database.get_db_path se reemplaza ANTES de importar main. errores.log del
repositorio tampoco se toca (se quita su handler tras importar main).
"""

import asyncio
import gc
import inspect
import json
import logging
import os
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# ── Aislamiento: nada de la máquina real ────────────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="conv v18 ia "))
os.environ["HOME"] = str(TMP / "home")
os.environ["LOCALAPPDATA"] = str(TMP / "home" / "AppData")
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("XDG_DATA_HOME", None)

import database  # noqa: E402

DB_DIR = TMP / "datos" / "data"
DB_DIR.mkdir(parents=True)
database.get_db_path = lambda: DB_DIR / "exams_history.db"  # ANTES de importar main

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402
import requests  # noqa: E402

import ayuda_ia  # noqa: E402
import extractor  # noqa: E402
import formatter  # noqa: E402
import imagenes  # noqa: E402
import main  # noqa: E402
import pipeline  # noqa: E402
import seguridad  # noqa: E402

os.environ.pop("GEMINI_API_KEY", None)
# Los errores que estas pruebas provocan a propósito no van al errores.log real.
for _h in list(logging.getLogger().handlers):
    if getattr(_h, "_conversor_errores", False):
        logging.getLogger().removeHandler(_h)

logging.disable(logging.ERROR)  # los errores provocados a propósito no ensucian la salida

fallas = 0


def ok(cond, msg):
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


# ── Utilidades de simulación ────────────────────────────────────────────────
class _FakeResp:
    """Respuesta HTTP en streaming. iter_lines imita a requests: sin
    `delimiter` parte con str.splitlines() (también en U+2028), con
    `delimiter` parte solo por él."""

    def __init__(self, cuerpo: bytes = b"", status=200, bloquear=False):
        self.cuerpo, self.status_code, self.bloquear = cuerpo, status, bloquear
        self.cerrada = threading.Event()
        self.encoding = None
        self.text = cuerpo.decode("utf-8", "replace")

    def iter_lines(self, chunk_size=512, decode_unicode=False, delimiter=None):
        if self.bloquear:
            self.cerrada.wait(15)
            raise requests.exceptions.ConnectionError("conexión cerrada")
        if delimiter is None:
            for ln in self.cuerpo.decode("utf-8").splitlines():
                yield ln
            return
        for ln in self.cuerpo.split(delimiter):
            yield ln

    def close(self):
        self.cerrada.set()


def _sse(*eventos) -> bytes:
    return b"".join(b"data: " + json.dumps(e, ensure_ascii=False).encode("utf-8") + b"\n\n" for e in eventos)


def _evento(texto, finish=None):
    cand = {"content": {"parts": [{"text": texto}]}}
    if finish:
        cand["finishReason"] = finish
    return {"candidates": [cand], "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 7}}


_post_original = requests.post
_key_original = formatter.get_api_key
formatter.get_api_key = lambda: "clave-falsa-de-prueba"
_esperar_original = formatter._esperar

_img = Image.new("RGB", (4, 4), (200, 30, 30))

# ═══════════════ 1. Streaming: SSE, progreso, cancelación ═══════════════════
print("Streaming SSE")
u2028 = "Pregunta 1: ¿Qué hace esto en dos líneas?\u0085 fin"
requests.post = lambda *a, **k: _FakeResp(_sse(_evento(u2028), _evento(" listo", "STOP")))
try:
    r = formatter._stream_generate({}, 30, None)
    ok(r.text == u2028 + " listo" and r.finish_reason == "STOP",
       "U+2028 / U+0085 dentro del texto no parten el evento SSE (iter_lines por «\\n»)")
finally:
    requests.post = _post_original

seen = []
f = formatter._progress_counter(r"(?m)^Pregunta\s+\d+:", seen.append)
texto = "".join(f"Pregunta {i}: algo\n" for i in range(1, 121))
for i in range(0, len(texto), 7):
    f(texto[:i + 7])
ok(seen[-1] == 120 and seen == sorted(set(seen)), "contador de progreso incremental: cuenta 120 preguntas sin saltos")
f2 = formatter._progress_counter(r"(?m)^Pregunta\s+\d+:", seen.append)
f2("Pregunta 1"); f2("Pregunta 1:"); f2("Pregunta 1: x\nPregunta 2:")
ok(seen[-1] == 2, "una coincidencia partida entre fragmentos («Pregunta 1» + «:») se cuenta una sola vez")
seen.clear()
f3 = formatter._progress_counter(r'"orden"\s*:', seen.append)
f3('{"orden": 1, "x": "a"}, {"orden"'); f3('{"orden": 1, "x": "a"}, {"orden": 2')
f3('{"orden":')  # texto nuevo más corto (reintento): se cuenta desde cero
ok(seen == [1, 2, 1], f"al reintentar (texto nuevo) el contador vuelve a empezar ({seen})")

print("Cancelar de verdad")
# a) durante la lectura del stream: cancelar cierra la conexión
resp_bloq = _FakeResp(bloquear=True)
requests.post = lambda *a, **k: resp_bloq
res = {}
canc = formatter.Cancelacion()


def _hilo_stream():
    formatter.usar_cancelacion(canc)
    try:
        formatter._stream_generate({}, 60, None)
        res["r"] = "terminó"
    except BaseException as e:  # noqa: BLE001
        res["r"] = e
    finally:
        res["t"] = time.monotonic()


t = threading.Thread(target=_hilo_stream, daemon=True)
t.start()
time.sleep(0.4)
t0 = time.monotonic()
canc.cancelar()
t.join(5)
ok(not t.is_alive() and isinstance(res.get("r"), formatter.ConversionCancelada) and res["t"] - t0 < 1.5,
   "cancelar en pleno stream: el hilo sale enseguida con ConversionCancelada (sin reintentar)")
ok(resp_bloq.cerrada.is_set(), "…y la conexión con Gemini queda cerrada")

# b) mientras llega la respuesta (antes de las cabeceras)
def _post_lento(*a, **k):
    time.sleep(3)
    return _FakeResp(_sse(_evento("x", "STOP")))


requests.post = _post_lento
canc = formatter.Cancelacion()
res = {}
t = threading.Thread(target=_hilo_stream, daemon=True)
t.start()
time.sleep(0.3)
t0 = time.monotonic()
canc.cancelar()
t.join(5)
ok(not t.is_alive() and isinstance(res.get("r"), formatter.ConversionCancelada) and res["t"] - t0 < 1.5,
   "cancelar mientras se espera la respuesta de Google: no hay que esperar a que llegue")
requests.post = _post_original

# c) durante la espera entre reintentos (saturación 503): Event.wait, no sleep
llamadas = []


def _stream_503(body, timeout, on_text):
    llamadas.append(1)
    raise formatter.GeminiOverloadedError(503, "saturado")


_stream_original = formatter._stream_generate
formatter._stream_generate = _stream_503
canc = formatter.Cancelacion()
res = {}


def _hilo_reintentos():
    formatter.usar_cancelacion(canc)
    try:
        formatter._generate_with_retries({}, 10, lambda r: r, 30)
        res["r"] = "terminó"
    except BaseException as e:  # noqa: BLE001
        res["r"] = e
    finally:
        res["t"] = time.monotonic()


t = threading.Thread(target=_hilo_reintentos, daemon=True)
t.start()
time.sleep(0.4)
t0 = time.monotonic()
canc.cancelar()
t.join(5)
ok(not t.is_alive() and isinstance(res.get("r"), formatter.ConversionCancelada) and res["t"] - t0 < 1.5 and len(llamadas) == 1,
   "cancelar durante la espera de un reintento (5 s): sale al instante y no hace otra llamada")
# Sin cancelación activa, _esperar sigue siendo una espera normal.
t0 = time.monotonic()
formatter._esperar(0.05)
ok(time.monotonic() - t0 >= 0.04, "sin cancelación activa, _esperar espera normal")
formatter._stream_generate = _stream_original

# ═══════════════ 2. Cupos, cola y desconexión del navegador (main) ═════════
print("Servidor: cupos y desconexión")


async def _correr(resp, desconectar_tras=None):
    """Corre la respuesta ASGI; si `desconectar_tras`, el navegador se
    desconecta pasado ese tiempo. Devuelve los eventos NDJSON recibidos."""
    trozos = []

    async def receive():
        if desconectar_tras is None:
            await asyncio.sleep(3600)
        await asyncio.sleep(desconectar_tras)
        return {"type": "http.disconnect"}

    async def send(m):
        if m["type"] == "http.response.body" and m.get("body"):
            trozos.append(m["body"].decode("utf-8"))

    await resp({"type": "http", "asgi": {"spec_version": "2.3"}, "method": "POST", "path": "/x", "headers": []},
               receive, send)
    return [json.loads(l) for t_ in trozos for l in t_.splitlines() if l.strip()]


estado = {}


def fn_bloqueada(raw, filename, progress=None):
    estado["empezo"] = True
    progress({"type": "stage", "key": "extract", "message": "leyendo"})
    try:
        while True:
            formatter._esperar(0.05)  # lo que hace formatter en sus esperas
    finally:
        estado["salio"] = time.monotonic()


ok(main._CUPOS_CONVERSION._value == 2, "los 2 cupos de conversión están libres al empezar")
estado.clear()
resp = main._ndjson_progress_stream(fn_bloqueada, b"x", "a.pdf")
eventos = asyncio.run(_correr(resp, desconectar_tras=0.6))
t0 = time.monotonic()
hasta = time.monotonic() + 3
while "salio" not in estado and time.monotonic() < hasta:
    time.sleep(0.05)
ok(estado.get("empezo") and "salio" in estado, "el navegador se desconecta (Cancelar): el trabajo de la conversión termina")
time.sleep(0.2)
ok(main._CUPOS_CONVERSION._value == 2, "…y el cupo de conversión se libera")
ok(resp._cancelacion.cancelada, "la Cancelacion de esa conversión queda activada")
ok(any(e.get("key") == "extract" for e in eventos), "los eventos anteriores a la desconexión sí llegaron")

# Cola: con los 2 cupos ocupados se avisa «en cola» y cancelar no ocupa cupo.
main._CUPOS_CONVERSION.acquire()
main._CUPOS_CONVERSION.acquire()
estado.clear()
resp = main._ndjson_progress_stream(fn_bloqueada, b"x", "b.pdf")
eventos = asyncio.run(_correr(resp, desconectar_tras=0.8))
time.sleep(0.8)
ok(any(e.get("type") == "stage" and e.get("key") == "queue" and e.get("message") for e in eventos),
   "con los cupos ocupados se emite un evento «stage/queue» antes de esperar")
ok(not estado.get("empezo"), "cancelar en la cola: la conversión nunca llega a empezar")
ok(main._CUPOS_CONVERSION._value == 0, "…y no toca ningún cupo que no era suyo")
main._CUPOS_CONVERSION.release()
main._CUPOS_CONVERSION.release()
ok(main._CUPOS_CONVERSION._value == 2, "los cupos vuelven a 2")

# Flujo normal: resultado y fin.
resp = main._ndjson_progress_stream(lambda raw, name, progress=None: {"ok": 1}, b"x", "c.pdf")
eventos = asyncio.run(_correr(resp))
ok(eventos and eventos[-1] == {"type": "result", "data": {"ok": 1}}, "sin cancelar: llega el resultado")
time.sleep(0.2)
ok(main._CUPOS_CONVERSION._value == 2, "cupo liberado al terminar normalmente")

# Un HTTPException previsto llega como evento de error, sin reintento.
def fn_http(raw, name, progress=None):
    raise HTTPException(status_code=422, detail="no es un examen")


eventos = asyncio.run(_correr(main._ndjson_progress_stream(fn_http, b"x", "d.pdf")))
ok(eventos[-1] == {"type": "error", "status": 422, "detail": "no es un examen"}, "error previsto: evento de error 422")

# Botones de IA de una pregunta: cupo propio.
main._CUPOS_CONVERSION.acquire()
main._CUPOS_CONVERSION.acquire()
try:
    ok(main._con_cupo_puntual(lambda: 7) == 7, "«Escribir con IA» / «Mejorar redacción» no esperan a las conversiones largas")
finally:
    main._CUPOS_CONVERSION.release()
    main._CUPOS_CONVERSION.release()
main._CUPOS_IA_PUNTUAL.acquire()
main._CUPOS_IA_PUNTUAL.acquire()
_espera_original = main._ESPERA_CUPO_PUNTUAL_S
main._ESPERA_CUPO_PUNTUAL_S = 0.2
try:
    main._con_cupo_puntual(lambda: 1)
    ok(False, "con su cupo lleno, la ayuda de IA no espera minutos")
except HTTPException as e:
    ok(e.status_code == 429, "con su propio cupo lleno: 429 con mensaje claro tras una espera corta")
finally:
    main._ESPERA_CUPO_PUNTUAL_S = _espera_original
    main._CUPOS_IA_PUNTUAL.release()
    main._CUPOS_IA_PUNTUAL.release()

# Rutas del historial en el threadpool (def), no en el event loop.
for nombre in ("api_get_history", "api_download_history", "api_history_editor", "api_delete_history"):
    ok(not inspect.iscoroutinefunction(getattr(main, nombre)), f"{nombre} es `def` (threadpool), no bloquea el event loop")

# ═══════════════ 3. Reintento del worker: no repite la IA ══════════════════
print("Reintento del worker: solo el postproceso")
TXT = ("Pregunta 1: ¿Cuál es la capital de Francia?\nA) París\nB) Madrid\n"
       "Pregunta 2: ¿Cuál es la capital de Italia?\nA) Roma\nB) Milán\n\nRESPUESTAS\n1 A\n2 A\n").encode("utf-8")


def _payload():
    def q(i, enun, ops):
        return {"orden": i, "tipo": "multichoice", "enunciado": enun,
                "opciones": [{"letra_original": l, "texto": t, "correcta": l == "A"} for l, t in ops],
                "items_izquierda": [], "items_derecha": [], "parejas": [], "huecos": [], "clave_texto": "",
                "respuesta_texto": "", "retroalimentacion": "", "respuesta_marcada": True, "origen_tabla": False,
                "pagina": 1, "confianza": "alta"}
    return {"es_examen": True, "preguntas": [
        q(1, "¿Cuál es la capital de Francia?", [("A", "París"), ("B", "Madrid")]),
        q(2, "¿Cuál es la capital de Italia?", [("A", "Roma"), ("B", "Milán")])]}


conteo = {"ia": 0, "final": 0}


def _extract_falso(model_text, page_images=None, progress=None, on_retry=None, permitir_reintento_calidad=True):
    conteo["ia"] += 1
    return _payload()


_finalize_real = pipeline._finalize_structured
_extract_real = pipeline.extract_structured
_key_pipeline = pipeline.get_api_key
pipeline.get_api_key = lambda: "clave-falsa"
pipeline.extract_structured = _extract_falso
_mode = pipeline.NORMALIZER_MODE
pipeline.NORMALIZER_MODE = "json"
try:
    def _final_falla_una_vez(*a, **k):
        conteo["final"] += 1
        if conteo["final"] == 1:
            raise RuntimeError("fallo del postproceso")
        return _finalize_real(*a, **k)

    pipeline._finalize_structured = _final_falla_una_vez
    eventos = asyncio.run(_correr(main._ndjson_progress_stream(pipeline.parse_document, TXT, "ex.txt")))
    ok(eventos[-1]["type"] == "result" and len(eventos[-1]["data"]["questions"]) == 2, "un fallo del postproceso se recupera en el reintento")
    ok(conteo["ia"] == 1, f"…y la IA se llamó UNA sola vez, no dos ({conteo['ia']})")
    ok(any(e.get("key") == "retry" for e in eventos), "el docente ve el aviso de reintento")

    conteo.update(ia=0, final=0)

    def _final_siempre_falla(*a, **k):
        conteo["final"] += 1
        raise RuntimeError("bug determinista")

    pipeline._finalize_structured = _final_siempre_falla
    eventos = asyncio.run(_correr(main._ndjson_progress_stream(pipeline.parse_document, TXT, "ex.txt")))
    ok(eventos[-1]["type"] == "error" and eventos[-1]["status"] == 500, "un bug determinista termina en un error claro (500)")
    ok(conteo["ia"] == 1 and conteo["final"] == 2, f"…con 1 llamada a la IA y 2 al postproceso ({conteo})")
    ok(_payload() == _payload(), "(control) el payload simulado es reproducible")
finally:
    pipeline._finalize_structured = _finalize_real
    pipeline.extract_structured = _extract_real
    pipeline.NORMALIZER_MODE = _mode
    pipeline.get_api_key = _key_pipeline

# ═══════════════ 4. Reintento de calidad solo con marca real ═══════════════
print("Reintento de calidad de la IA")
opciones_rojas = ("1. ¿Capital de Francia?\na) Madrid\nb) ⟦rojo⟧París⟦/rojo⟧\nc) Roma\n"
                  "2. ¿Capital de Italia?\na) ⟦rojo⟧Roma⟦/rojo⟧\nb) Lima\nc) Bonn")
titulo_azul = "⟦azul⟧Parcial de Historia Universal, unidad 1⟦/azul⟧\n1. ¿Capital de Francia?\na) Madrid\nb) París\nc) Roma"
ok(pipeline._hay_marca_de_respuestas(([opciones_rojas], []), False) is True, "opciones cortas en rojo: hay marca de respuestas")
ok(pipeline._hay_marca_de_respuestas(([titulo_azul], []), True) is False,
   "un encabezado azul suelto NO cuenta como marca (antes disparaba hasta 3 llamadas completas)")
titulos_negrita = ("⟦negrita⟧EXAMEN PARCIAL DE HISTORIA⟦/negrita⟧\n1. ¿Capital de Francia?\na) Madrid\nb) París\nc) Roma\n"
                   "⟦negrita⟧CLAVE DE RESPUESTAS⟦/negrita⟧\n1. b")
opciones_negrita = ("1. ¿Capital de Francia?\na) Madrid\nb) ⟦negrita⟧París⟦/negrita⟧\nc) Roma\n"
                    "2. ¿Capital de Italia?\na) ⟦negrita⟧Roma⟦/negrita⟧\nb) Lima\nc) Bonn")
ok(pipeline._hay_marca_de_respuestas(([titulos_negrita], []), True) is False,
   "títulos en negrita («CLAVE DE RESPUESTAS») NO cuentan como marca de respuestas")
ok(pipeline._hay_marca_de_respuestas(([opciones_negrita], []), False) is True,
   "opciones «b) …» en negrita SÍ cuentan como marca de respuestas")
ok(pipeline._hay_marca_de_respuestas(None, True) is True and pipeline._hay_marca_de_respuestas(None, False) is False,
   "sin texto enriquecido no se puede saber: se usa el criterio de respaldo")

# ═══════════════ 5. Reintentos de calidad: el mejor resultado no se pierde ═
print("Reintento de calidad: no se pierde el mejor resultado")
_gwr = formatter._generate_with_retries
formatter._esperar = lambda s: None


def _pj(n, sin_resp):
    return {"es_examen": True, "preguntas": [{"tipo": "multichoice", "respuesta_marcada": not sin_resp} for _ in range(n)]}


secuencia = [_pj(3, True), HTTPException(status_code=503, detail="saturado")]
formatter._generate_with_retries = lambda *a, **k: (lambda x: (_ for _ in ()).throw(x) if isinstance(x, Exception) else x)(secuencia.pop(0))
try:
    r = formatter.extract_structured("t", [_img], permitir_reintento_calidad=True)
    ok(len(r["preguntas"]) == 3, "JSON: si el 2.º intento de calidad falla (503), se devuelve el 1.º ya obtenido")
    secuencia = [_pj(3, True), _pj(2, False)]
    r = formatter.extract_structured("t", [_img], permitir_reintento_calidad=True)
    ok(len(r["preguntas"]) == 3, "JSON: se elige por cantidad de preguntas y luego por ratio")
    secuencia = [HTTPException(status_code=503, detail="saturado")]
    try:
        formatter.extract_structured("t", [_img], permitir_reintento_calidad=True)
        ok(False, "sin ningún resultado previo, el error se propaga")
    except HTTPException as e:
        ok(e.status_code == 503, "sin ningún resultado previo, el error se propaga")
finally:
    formatter._generate_with_retries = _gwr

_cgwr = formatter._call_gemini_with_retries
txt3 = "Pregunta 1: a\nPregunta 2: b\nPregunta 3: c\nRESPUESTAS\n1 SIN_RESPUESTA\n2 SIN_RESPUESTA\n3 SIN_RESPUESTA"
txt1 = "Pregunta 1: a\nRESPUESTAS\n1 A"
secuencia = [(txt3, True), (txt1, True)]
formatter._call_gemini_with_retries = lambda *a, **k: secuencia.pop(0)
try:
    r, _ = formatter.verify_and_format("t", [_img], permitir_reintento_calidad=True)
    ok(r == txt3, "texto: elige el intento con MÁS preguntas aunque tenga peor ratio (mismo criterio que el JSON)")
    secuencia = [(txt3, True), Exception("503")]

    def _lanza(*a, **k):
        x = secuencia.pop(0)
        if isinstance(x, Exception):
            raise x
        return x

    formatter._call_gemini_with_retries = _lanza
    r, _ = formatter.verify_and_format("t", [_img], permitir_reintento_calidad=True)
    ok(r == txt3, "texto: si el 2.º intento lanza una excepción, se devuelve el 1.º")
    calls = []
    formatter._call_gemini_with_retries = lambda *a, **k: (calls.append(1), (txt3, True))[1]
    formatter.verify_and_format("t", [_img], permitir_reintento_calidad=False)
    ok(len(calls) == 1, "sin marca de respuestas (permitir_reintento_calidad=False): una sola llamada")
finally:
    formatter._call_gemini_with_retries = _cgwr

# ═══════════════ 6. finish_reason y mensajes de error veraces ══════════════
print("finish_reason y mensajes de error")


def _con_stream(fabrica):
    formatter._stream_generate = fabrica


def _resultado(finish, texto="Pregunta 1: ¿Algo?\nA) x\nRESPUESTAS\n1 A"):
    return formatter._GenResult(text=texto, finish_reason=finish, prompt_tokens=1, output_tokens=1)


n = {"c": 0}


def _stream_finish(finish):
    def f(body, timeout, on_text):
        n["c"] += 1
        return _resultado(finish)
    return f


try:
    _con_stream(_stream_finish("STOP"))
    n["c"] = 0
    out, _ = formatter._call_gemini_with_retries({}, "x")
    ok(out.startswith("Pregunta 1") and n["c"] == 1, "modo texto: STOP se acepta")

    _con_stream(_stream_finish("MAX_TOKENS"))
    n["c"] = 0
    try:
        formatter._call_gemini_with_retries({}, "x")
        ok(False, "modo texto: MAX_TOKENS no se acepta como respuesta completa")
    except HTTPException as e:
        ok(e.status_code == 422 and "demasiado largo" in json.dumps(e.detail, ensure_ascii=False) and n["c"] == 1,
           "modo texto: MAX_TOKENS falla claro («demasiado largo») y sin reintentar")

    _con_stream(_stream_finish("SAFETY"))
    n["c"] = 0
    try:
        formatter._call_gemini_with_retries({}, "x")
        ok(False, "modo texto: SAFETY no se acepta")
    except HTTPException as e:
        ok("SAFETY" in str(e.detail) and "concurrido" not in str(e.detail) and n["c"] == 2,
           f"modo texto: SAFETY = intento fallido con su motivo, un solo reintento ({n['c']} llamadas)")

    def _vacia(body, timeout, on_text):
        n["c"] += 1
        raise formatter.RespuestaVacia("STOP", "PROHIBITED_CONTENT")

    _con_stream(_vacia)
    n["c"] = 0
    try:
        formatter._call_gemini_with_retries({}, "x")
    except HTTPException as e:
        ok("PROHIBITED_CONTENT" in str(e.detail) and "concurrido" not in str(e.detail),
           "bloqueo de seguridad: mensaje veraz (no «servidor muy concurrido»)")

    def _timeout(body, timeout, on_text):
        n["c"] += 1
        raise TimeoutError("superó 180 s")

    _con_stream(_timeout)
    n["c"] = 0
    try:
        formatter._call_gemini_with_retries({}, "x")
    except HTTPException as e:
        ok("tardó demasiado" in str(e.detail) and n["c"] == 2 and "concurrido" not in str(e.detail),
           f"TimeoutError: mensaje veraz y solo UN reintento ({n['c']} llamadas)")

    def _json_malo(body, timeout, on_text):
        n["c"] += 1
        return _resultado("STOP", "{no es json")

    _con_stream(_json_malo)
    n["c"] = 0
    try:
        formatter._generate_with_retries({}, 5, formatter._parse_structured_response, 30)
    except HTTPException as e:
        ok("no se pudo interpretar" in str(e.detail) and n["c"] == formatter.GEMINI_MAX_RETRIES,
           "JSON inválido: mensaje veraz tras los reintentos normales")

    _con_stream(_stream_finish("RECITATION"))
    try:
        formatter._generate_with_retries({}, 5, formatter._parse_structured_response, 30)
    except HTTPException as e:
        ok("RECITATION" in str(e.detail), "JSON: un finish_reason distinto de STOP también es un intento fallido")

    def _cuota(body, timeout, on_text):
        n["c"] += 1
        raise formatter.GeminiQuotaError(429, "Please retry in 45.0s")

    _con_stream(_cuota)
    n["c"] = 0
    try:
        formatter._generate_with_retries({}, 5, lambda r: r, 30, quota_waits=1, quota_max_seconds=20)
        ok(False, "cuota con espera larga en una llamada puntual")
    except HTTPException as e:
        ok(e.status_code == 503 and n["c"] == 1, "llamada de UNA pregunta: si Google pide >20 s de espera, se avisa sin esperar")
finally:
    formatter._stream_generate = _stream_original
    formatter._esperar = _esperar_original

# ═══════════════ 7. Preguntas omitidas: emparejar por «orden» ══════════════
print("Preguntas omitidas: emparejar por «orden»")
stems = ["Primera pregunta sobre historia antigua universal", "Segunda pregunta que la IA omitió por completo aquí",
         "Tercera pregunta sobre geografía moderna del mundo", "Cuarta pregunta que la IA omitió también al final"]
lineas = [imagenes.Linea((1, float(i)), f"{i}. {s}") for i, s in enumerate(stems, 1)]
ub = imagenes.Ubicaciones(lineas=lineas, imagenes=[])


def _pl(orden, enun):
    d = _payload()["preguntas"][0]
    return {**d, "orden": orden, "enunciado": enun}


def _base():
    return {"es_examen": True, "preguntas": [_pl(1, stems[0]), _pl(2, stems[2])]}


_em_real = pipeline.extract_missing
try:
    pedido = {}

    def _falso(devuelve):
        def f(fragmentos, page_images=None, on_retry=None):
            pedido["fragmentos"] = list(fragmentos)
            return devuelve(fragmentos)
        return f

    # La IA devuelve SOLO la 2.ª (orden=2): debe ir donde va la 2.ª, no la 1.ª.
    pipeline.extract_missing = _falso(lambda fr: [_pl(2, "TEXTO DE LA SEGUNDA")])
    out = pipeline._completar_omitidas(_base(), ub, [], None)
    orden_final = [p["enunciado"] for p in sorted(out["preguntas"], key=lambda p: p["orden"])]
    ok(len(pedido["fragmentos"]) == 2 and len(out["preguntas"]) == 3, "se piden las 2 candidatas y se inserta solo la que devolvió la IA")
    ok(orden_final == [stems[0], stems[2], "TEXTO DE LA SEGUNDA"],
       f"la respuesta con orden=2 queda en el hueco de la candidata 2 (al final), no en el de la 1 ({orden_final})")

    # Ambas, en orden invertido.
    pipeline.extract_missing = _falso(lambda fr: [_pl(2, "SEGUNDA"), _pl(1, "PRIMERA")])
    out = pipeline._completar_omitidas(_base(), ub, [], None)
    orden_final = [p["enunciado"] for p in sorted(out["preguntas"], key=lambda p: p["orden"])]
    ok(orden_final == [stems[0], "PRIMERA", stems[2], "SEGUNDA"], f"devueltas en otro orden: cada una va a su hueco ({orden_final})")

    # Sin orden válido, repetido o fuera de rango: se descarta.
    pipeline.extract_missing = _falso(lambda fr: [_pl(None, "A"), _pl(7, "B"), _pl(1, "C1"), _pl(1, "C2"), _pl(2.5, "D")])
    out = pipeline._completar_omitidas(_base(), ub, [], None)
    ok(len(out["preguntas"]) == 2, "«orden» ausente, inexistente, repetido o no entero: se descarta, nada se inventa")
finally:
    pipeline.extract_missing = _em_real

print("Partes de imagen: codificadas una sola vez")
im = Image.new("RGB", (30, 30), (10, 200, 10))
p1 = formatter._image_part(im)
p2 = formatter._image_part(im)
ok(p1 is p2, "la misma imagen no se recodifica en WebP en cada llamada (reintento de calidad, omitidas)")
k = id(im)
del im
gc.collect()
ok(k not in formatter._partes_imagen, "…y la entrada de caché desaparece cuando la imagen se libera")

# ═══════════════ 8. Páginas que no llegaron a la IA ════════════════════════
print("Aviso de páginas perdidas")


def _pdf(n, con_texto=True):
    objs, kids = ["<< /Type /Catalog /Pages 2 0 R >>", None], []
    contenido = "BT /F1 12 Tf 72 72 Td (Hola) Tj ET" if con_texto else " "
    for _ in range(n):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents {len(objs) + 2} 0 R >>")
        kids.append(len(objs))
        objs.append(f"<< /Length {len(contenido)} >>stream\n{contenido}\nendstream")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {n} >>"
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF".encode()


imgs, total = extractor.render_all_pages_as_images(_pdf(extractor.MAX_IMAGE_PAGES + 2), con_total=True)
ok(len(imgs) == extractor.MAX_IMAGE_PAGES and total == extractor.MAX_IMAGE_PAGES + 2, "se sabe cuántas páginas tiene el PDF y cuántas se enviaron")
ok(isinstance(extractor.render_all_pages_as_images(_pdf(2)), list), "sin con_total sigue devolviendo solo la lista de imágenes")
ok(pipeline._aviso_paginas(15, 15, False) is None and pipeline._aviso_paginas(3, 15, True) is None, "sin recorte no hay aviso")
a1 = pipeline._aviso_paginas(20, 15, False)
ok("16 a 20" in a1 and "NO están" in a1, "escaneado recortado: aviso claro con las páginas perdidas")
ok("20 páginas" in pipeline._aviso_paginas(20, 15, True), "con texto: aviso más suave")

_key_p = pipeline.get_api_key
pipeline.get_api_key = lambda: "clave-falsa"
_mode_ai = pipeline.NORMALIZER_MODE_AI
pipeline.NORMALIZER_MODE_AI = "json"
pipeline.extract_structured = lambda *a, **k: _payload()
try:
    res_ = pipeline.normalize_document_with_ai(_pdf(extractor.MAX_IMAGE_PAGES + 5, con_texto=False), "escaneado.pdf")
    ok(res_["completeness_notice"] and "16 a 20" in res_["completeness_notice"],
       "de punta a punta: un escaneado de 20 páginas muestra el aviso en completeness_notice")
    res_ = pipeline.normalize_document_with_ai(_pdf(3, con_texto=False), "corto.pdf")
    ok(not res_["completeness_notice"], "un escaneado corto no lleva aviso")
finally:
    pipeline.extract_structured = _extract_real
    pipeline.NORMALIZER_MODE_AI = _mode_ai
    pipeline.get_api_key = _key_p

# ═══════════════ 9. PDF con contraseña / dañado ════════════════════════════
print("Errores de archivos PDF")
from pdfminer.pdfdocument import PDFPasswordIncorrect  # noqa: E402

ok("contraseña" in pipeline._mensaje_error_pdf(PDFPasswordIncorrect()), "PDFPasswordIncorrect (sin texto): mensaje claro sobre la contraseña")
ok("dañado" in (pipeline._mensaje_error_pdf(type("PDFSyntaxError", (Exception,), {})("x")) or ""), "PDF dañado: mensaje claro")
ok(pipeline._mensaje_error_pdf(ValueError("otra cosa")) is None, "un error desconocido no se disfraza")
ok(pipeline._detalle_lectura(KeyError(), "Error al leer").endswith("KeyError"), "sin texto en la excepción se muestra su nombre, no un mensaje vacío")
_pw = pipeline.comprobar_paginas


def _pide_clave(raw):
    raise PDFPasswordIncorrect()


pipeline.comprobar_paginas = _pide_clave
pipeline.get_api_key = lambda: "clave-falsa"
try:
    pipeline.parse_document(b"%PDF-1.4", "protegido.pdf")
    ok(False, "PDF con contraseña rechazado")
except HTTPException as e:
    ok(e.status_code == 422 and "contraseña" in e.detail, "parse_document: PDF con contraseña -> 422 claro")
finally:
    pipeline.comprobar_paginas = _pw
    pipeline.get_api_key = _key_pipeline

# ═══════════════ 10. «Mejorar redacción» ═══════════════════════════════════
print("Mejorar redacción: cambios de sentido")
malos = [
    ("¿Cuáles de las siguientes afirmaciones son incorrectas?", "¿Cuáles de las siguientes afirmaciones son correctas?", "incorrectas -> correctas"),
    ("El agua siempre hierve a 100 grados en la Tierra.", "El agua a veces hierve a 100 grados en la Tierra.", "siempre -> a veces"),
    ("¿Cuál es el planeta mayor del sistema solar?", "¿Cuál es el planeta menor del sistema solar?", "mayor -> menor"),
    ("Un sistema sin memoria no puede almacenar datos.", "Un sistema con memoria no puede almacenar datos.", "sin -> con"),
    ("Einstein desarrolló la teoría de la relatividad.", "Newton desarrolló la teoría de la relatividad.", "nombre propio al inicio"),
    ("Según Einstein, la luz viaja a velocidad constante.", "Según Newton, la luz viaja a velocidad constante.", "nombre propio en medio"),
    ("Explique con detalle las diferencias entre el modelo relacional y el modelo jerárquico de bases de datos.",
     "Explique las diferencias entre modelos de bases de datos.", "se borra media frase"),
]
for o, nuevo, etiqueta in malos:
    ok(bool(ayuda_ia.cambios_indebidos(o, nuevo)), f"se rechaza: {etiqueta}")
buenos = [
    ("cual es la capital de francia", "¿Cuál es la capital de Francia?", "tildes, signos y mayúscula de Francia"),
    ("Que función cumple el metodo __init__ en una clase de Python", "¿Qué función cumple el método __init__ en una clase de Python?", "tildes"),
    ("Cual de las siguientes opciones describe mejor lo que hace la funcion print en python?",
     "¿Cuál de las siguientes opciones describe mejor la función print de Python?", "reformulación leve"),
    ("Segun el texto, por que ocurrio la revolucion francesa en 1789?", "Según el texto, ¿por qué ocurrió la Revolución Francesa en 1789?", "mayúsculas y tildes"),
    ("El agua hierve a 100 grados celcius al nivel del mar", "El agua hierve a 100 grados Celsius al nivel del mar.", "errata en un nombre propio"),
    ("Todos los mamiferos son de sangre caliente y respiran aire", "Todos los mamíferos son de sangre caliente y respiran aire.", "tildes con «todos»"),
    ("Cual es la capital de panama", "¿Cuál es la capital de Panamá?", "Panamá con mayúscula y tilde"),
]
for o, nuevo, etiqueta in buenos:
    ok(ayuda_ia.cambios_indebidos(o, nuevo) == [], f"se acepta: {etiqueta}")
mot = ayuda_ia.cambios_indebidos("Un sistema sin memoria", "Un sistema con memoria")
ok(any("sin" in m and "con" in m for m in mot), f"el motivo dice qué cambió ({mot})")
ok("longitud" in ayuda_ia.cambios_indebidos("a" * 100, "a" * 60), "el límite de longitud ya no permite borrar casi la mitad (0.6)")

print("Mejorar redacción / retroalimentación: tokens y finish_reason")
capturado = {}


class _RespF:
    def __init__(self, text, finish):
        self.text, self.finish_reason = text, finish


def _gwr_falso(finish, texto="Texto correcto."):
    def f(body, n_, parse, timeout, **kw):
        capturado["body"], capturado["kw"] = body, kw
        return parse(_RespF(texto, finish))
    return f


_gwr2 = formatter._generate_with_retries
try:
    formatter._generate_with_retries = _gwr_falso("STOP", "¿Cuál es la capital de Francia?")
    r = ayuda_ia.mejorar_enunciado({"type": "essay", "data": {"stem": "cual es la capital de francia"}})
    ok(r["enunciado"] == "¿Cuál es la capital de Francia?", "«Mejorar redacción» con STOP funciona")
    ok(capturado["body"]["generationConfig"]["maxOutputTokens"] >= 8192, "margen amplio de tokens (los de «thinking» cuentan dentro del tope)")
    ok(capturado["kw"].get("quota_waits", 9) <= 1, "llamada de una pregunta: pocas esperas de cuota")
    formatter._generate_with_retries = _gwr_falso("MAX_TOKENS", "¿Cuál es la capi")
    try:
        ayuda_ia.mejorar_enunciado({"type": "essay", "data": {"stem": "cual es la capital de francia"}})
        ok(False, "respuesta cortada no se aplica")
    except HTTPException as e:
        ok(e.status_code == 502 and "no alcanzó a terminar" in e.detail, "«Mejorar redacción» con MAX_TOKENS: no se aplica un texto cortado")
    formatter._generate_with_retries = _gwr_falso("STOP", "Porque suma dos.")
    ayuda_ia.generar({"type": "essay", "data": {"stem": "¿Cuánto es 1+1?"}}, None)
    ok(capturado["body"]["generationConfig"]["maxOutputTokens"] >= 4096, "retroalimentación: margen amplio de tokens")
    formatter._generate_with_retries = _gwr_falso("SAFETY", "algo")
    try:
        ayuda_ia.generar({"type": "essay", "data": {"stem": "¿Cuánto es 1+1?"}}, None)
        ok(False, "respuesta interrumpida no se aplica")
    except HTTPException as e:
        ok("SAFETY" in e.detail, "retroalimentación con SAFETY: mensaje claro")
finally:
    formatter._generate_with_retries = _gwr2

# ═══════════════ 11. Servidor: guardado del historial no fatal ═════════════
print("Servidor: historial y exportación")
c = TestClient(main.app, base_url="http://127.0.0.1:8000")
H = {"X-Conversor-Token": seguridad.TOKEN}
cuerpo_xml = {
    "filename": "ejemplo.pdf", "category": "mis-preguntas", "total_points": 10,
    "questions": [{"num": 1, "type": "multichoice", "points": 10,
                   "data": {"stem": "¿Cuánto es 2+2?", "options": {"a": "3", "b": "4"}}}],
    "answer_key": {"1": {"type": "multichoice", "answer": "b"}},
}
_save = main.save_conversion


def _guardar_falla(*a, **k):
    raise sqlite3.OperationalError("no such table: history")


main.save_conversion = _guardar_falla
try:
    r = c.post("/api/generate_xml", headers=H, json=cuerpo_xml)
    st = json.loads(r.headers.get("X-Question-Stats", "{}"))
    ok(r.status_code == 200 and b"<quiz>" in r.content, "el historial falla («no such table»): la exportación NO se aborta, el XML se entrega")
    ok(st.get("historial_guardado") is False and "Historial" in (st.get("aviso_historial") or ""), "…y la respuesta avisa (X-Question-Stats.historial_guardado=false + aviso_historial)")
    main.save_conversion = lambda *a, **k: 1
    r = c.post("/api/generate_xml", headers=H, json=cuerpo_xml)
    st = json.loads(r.headers.get("X-Question-Stats", "{}"))
    ok(r.status_code == 200 and st.get("historial_guardado") is True and st.get("aviso_historial") is None, "con el historial sano: historial_guardado=true")
    ok(isinstance(st.get("avisos"), list), "los avisos del constructor llegan al frontend (X-Question-Stats.avisos)")
finally:
    main.save_conversion = _save

_gh = main.get_history_list
main.get_history_list = lambda: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked"))
try:
    r = c.get("/api/history", headers=H)
    ok(r.status_code == 503 and "historial" in r.json()["detail"], "historial ilegible: 503 con mensaje claro, no un 500 mudo")
finally:
    main.get_history_list = _gh

_ge = main.get_editor_data
main.get_editor_data = lambda i: {"filename": "x.pdf", "category": "c", "total_points": 1, "editor_json": "{no json"}
try:
    r = c.get(f"/api/history/1/editor", headers=H)
    ok(r.status_code == 422 and "dañados" in r.json()["detail"], "editor_json dañado: 422 claro (antes un 500)")
finally:
    main.get_editor_data = _ge

_init = main.init_db
try:
    main.init_db = lambda: False
    main.startup_event()
    ok(True, "init_db() devuelve False: el arranque sigue (queda en el registro)")
    main.init_db = lambda: (_ for _ in ()).throw(RuntimeError("disco"))
    main.startup_event()
    ok(True, "init_db() lanza: el arranque sigue en vez de morir en silencio")
except Exception as e:  # noqa: BLE001
    ok(False, f"el arranque no debe fallar por el historial ({e})")
finally:
    main.init_db = _init

_key = main.credenciales.guardar
main.credenciales.guardar = lambda k: (_ for _ in ()).throw(PermissionError("denegado"))
_val = main.credenciales.validar
main.credenciales.validar = lambda k: None
try:
    r = c.post("/api/api-key", headers=H, json={"clave": "x" * 30})
    ok(r.status_code == 500 and "no se pudo guardar" in r.json()["detail"] and "permiso" in r.json()["detail"], "guardar la clave sin permiso de escritura: mensaje claro")
finally:
    main.credenciales.guardar = _key
    main.credenciales.validar = _val

print("Avisos en la cabecera y evento de resultado")
_av = [f"aviso {i}" for i in range(12)]
_cab = main._avisos_para_cabecera(_av)
ok(len(_cab) == main.MAX_AVISOS_CABECERA + 1 and _cab[0] == "aviso 0" and "7 avisos más" in _cab[-1],
   "con muchos avisos la cabecera deja los primeros y resume el resto")
ok(main._avisos_para_cabecera(["a", "b"]) == ["a", "b"] and main._avisos_para_cabecera(None) == [],
   "con pocos avisos (o ninguno) no cambia nada")
ok(main._evento_ndjson({"type": "ping", "x": "ñ"}) == '{"type": "ping", "x": "ñ"}\n', "el evento NDJSON conserva el formato")

formatter.get_api_key = _key_original
requests.post = _post_original
print()
print("TODO OK" if not fallas else f"{fallas} FALLA(S)")
sys.exit(1 if fallas else 0)
