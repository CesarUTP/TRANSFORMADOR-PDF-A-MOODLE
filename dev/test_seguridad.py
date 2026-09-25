"""
test_seguridad.py — pruebas de la seguridad del servidor local y el launcher.

    backend/venv/bin/python dev/test_seguridad.py

Se copia a sí misma, con backend/, frontend/ y launcher.py, a una carpeta
temporal y corre ahí con un entorno vacío (HOME falso): nunca lee el .env
real, la clave guardada (clave.dat) ni el historial, y nunca llama a Gemini.
dev/sync_ejecutable.py la corre antes de actualizar los instaladores.

Cubre: token por arranque, Host/Origin (DNS rebinding), sin CORS, CSP,
tamaño máximo, XSS por type/num, puerto propio y firma de /api/salud,
impostor en el puerto, enlaces externos, puente de pywebview, aviso de
actualización, límites de PDF y los algoritmos que eran cuadráticos.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARCA = "_CONVERSOR_PRUEBA_AISLADA"


def _lanzar_aislada() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="conversor-prueba-"))
    try:
        ignorar = shutil.ignore_patterns("venv", "build_venv", "__pycache__", ".env*", "*.db",
                                         "clave.dat", "*.log", "C:*")
        for carpeta in ("backend", "frontend"):
            shutil.copytree(ROOT / carpeta, tmp / carpeta, ignore=ignorar)
        shutil.copy2(ROOT / "launcher.py", tmp / "launcher.py")
        shutil.copy2(__file__, tmp / "test_seguridad.py")
        (tmp / "home").mkdir()
        env = {"HOME": str(tmp / "home"), "LOCALAPPDATA": str(tmp / "home"),
               "USERPROFILE": str(tmp / "home"), "PATH": os.defpath, MARCA: "1"}
        if os.name == "nt":
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
        return subprocess.run([sys.executable, str(tmp / "test_seguridad.py")], env=env, cwd=tmp).returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if os.environ.get(MARCA) != "1":
    sys.exit(_lanzar_aislada())


# ── Desde aquí: dentro de la copia aislada ──────────────────────────────────
import json  # noqa: E402
import random  # noqa: E402
import re  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import http.server  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI / "backend"))
sys.path.insert(0, str(AQUI))

fallas = 0


def ok(cond: bool, msg: str) -> None:
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
import seguridad  # noqa: E402

main.init_db()
c = TestClient(main.app, base_url="http://127.0.0.1:8000")
H = {"X-Conversor-Token": seguridad.TOKEN}

print("Servidor local")
r = c.get("/")
ok(r.status_code == 200 and "script-src 'self'" in r.headers.get("content-security-policy", ""), "/ se sirve con CSP")
ok("unpkg" not in r.text and "googleapis" not in r.text and "onclick=" not in r.text, "index.html sin scripts/fuentes externos ni onclick")
ok(c.get("/js/vendor/lucide.min.js").status_code == 200, "Lucide servido desde la app")
ok(c.get("/fonts/outfit-latin-wght-normal.woff2").status_code == 200, "fuentes servidas desde la app")
ok(c.get("/api/history").status_code == 401, "historial sin token -> 401")
ok(c.get("/api/history", headers={"X-Conversor-Token": "x" * 43}).status_code == 401, "historial con token falso -> 401")
r = c.get("/api/history", headers=H)
ok(r.status_code == 200 and "access-control-allow-origin" not in r.headers, "historial con token -> 200, sin CORS")
ok(c.get("/api/history", headers={**H, "Origin": "https://malo.example"}).status_code == 403, "Origin ajeno -> 403")
ok(c.get("/api/history", headers={**H, "Host": "malo.example:8000"}).status_code == 400, "Host ajeno (DNS rebinding) -> 400")
ok(c.get("/api/history", headers={**H, "Host": "localhost:8000"}).status_code == 200, "Host localhost -> 200")
r = c.options("/api/history", headers={"Origin": "https://malo.example", "Access-Control-Request-Method": "DELETE"})
ok("access-control-allow-origin" not in r.headers, "preflight ajeno sin permiso CORS")
r = c.get("/api/salud?n=abc")
ok(r.status_code == 200 and r.json()["firma"] == seguridad.firma_salud("abc"), "/api/salud firma sin pedir token")
r = c.post("/api/check_special_cases", headers={**H, "Content-Length": str(seguridad.MAX_CUERPO_BYTES + 1)}, content=b"x")
ok(r.status_code == 413, "cuerpo más grande que el máximo -> 413")
r = c.post("/api/parse", headers=H, files={"file": ("a.txt", b"1. hola?\nA) x\n" * 20, "text/plain")})
ok(r.status_code == 503, "sin clave de la API no se procesa el documento -> 503")

print("XSS por type / num")
base = {"filename": "x.pdf", "category": "c", "total_points": 10,
        "answer_key": {"1": {"type": "essay", "answer": ""}}}
malo = {**base, "questions": [{"num": 1, "type": '"><img src=x onerror=alert(1)>', "data": {"stem": "a"}}]}
ok(c.post("/api/generate_xml", json=malo, headers=H).status_code == 422, "type desconocido -> 422 (no se guarda)")
malo = {**base, "questions": [{"num": '1"><b>', "type": "essay", "data": {"stem": "a"}}]}
ok(c.post("/api/generate_xml", json=malo, headers=H).status_code == 422, "num no entero -> 422")
bueno = {**base, "questions": [{"num": 1, "type": "essay", "data": {"stem": "Explica algo"}}]}
ok(c.post("/api/generate_xml", json=bueno, headers=H).status_code == 200, "pregunta válida -> 200")

print("Algoritmos (tiempo lineal)")
from answer_matching import find_cloze_brackets  # noqa: E402
from validator import estimate_expected_questions, estimate_question_count  # noqa: E402

_ABRE = re.compile(r"([A-Za-z]):\s*")


def _cloze_anterior(text):
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] != "[":
            i += 1
            continue
        m = _ABRE.match(text, i + 1)
        if not m:
            i += 1
            continue
        d, j = 1, m.end()
        while j < n and d:
            d += {"[": 1, "]": -1}.get(text[j], 0)
            j += 1
        if d:
            i += 1
            continue
        out.append((i, j, m.group(1), text[m.end():j - 1]))
        i = j
    return out


random.seed(1)
textos = ("".join(random.choice("[]A: x/b") for _ in range(random.randint(0, 60))) for _ in range(5000))
ok(all(_cloze_anterior(t) == find_cloze_brackets(t) for t in textos), "corchetes Cloze: mismo resultado que la versión anterior")
t0 = time.time(); find_cloze_brackets("[A:" * 100000)
ok(time.time() - t0 < 1, "corchetes Cloze: 100 000 '[A:' en menos de 1 s")
t0 = time.time(); estimate_question_count("\n" * 1_000_000); estimate_expected_questions("\n" * 1_000_000)
ok(time.time() - t0 < 1, "estimadores: 1 000 000 de saltos de línea en menos de 1 s")
txt = "1. uno?\n2) dos?\n  3. tres?\nPregunta 4 cuatro?\n"
ok((estimate_question_count(txt), estimate_expected_questions(txt)) == (3, 4), "estimadores: mismos conteos")

print("Aviso de actualización (respuestas simuladas, sin internet)")
import io  # noqa: E402
import actualizaciones  # noqa: E402


class _Resp:
    def __init__(self, status, cuerpo):
        self.status_code, self.raw = status, io.BytesIO(cuerpo)
        self.raw.read = (lambda f: lambda n, decode_content=True: f(n))(self.raw.read)

    def close(self):
        pass


def _con(status, cuerpo):
    actualizaciones.requests.get = lambda *a, **k: _Resp(status, cuerpo)
    return actualizaciones._consultar()


pref = actualizaciones.PREFIJO_DESCARGAS
ok(_con(200, json.dumps({"version": "99.0", "url": pref + "releases"}).encode())["hay"], "versión mayor -> hay aviso")
ok(not _con(200, json.dumps({"version": actualizaciones.APP_VERSION, "url": pref}).encode())["hay"], "misma versión -> sin aviso")
ok(not _con(200, json.dumps({"version": "99.0", "url": "https://malo.example/x.exe"}).encode())["hay"], "enlace fuera del repositorio -> sin aviso")
ok(not _con(200, json.dumps({"version": "<b>9</b>", "url": pref}).encode())["hay"], "versión con formato raro -> sin aviso")
ok(not _con(200, b"x" * 20000)["hay"], "respuesta demasiado grande -> sin aviso")
ok(not _con(404, b"")["hay"], "404 (repositorio privado) -> sin aviso")
ok(len(_con(200, json.dumps({"version": "99.0", "url": pref, "notas": "n" * 5000}).encode())["notas"]) <= 300, "notas recortadas")
actualizaciones._cache = {"hay": False, "actual": actualizaciones.APP_VERSION}
ok(c.get("/api/actualizacion").status_code == 401 and c.get("/api/actualizacion", headers=H).status_code == 200, "/api/actualizacion pide token")

print("Límites de PDF")
import extractor  # noqa: E402


def _pdf(n, w=612, h=792):
    objs, kids = ["<< /Type /Catalog /Pages 2 0 R >>", None], []
    for _ in range(n):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] /Contents {len(objs) + 2} 0 R >>")
        kids.append(len(objs))
        objs.append("<< /Length 34 >>stream\nBT /F1 12 Tf 72 72 Td (Hola) Tj ET\nendstream")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {n} >>"
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF".encode()


try:
    extractor.comprobar_paginas(_pdf(extractor.MAX_PAGINAS + 1))
    ok(False, "PDF con demasiadas páginas rechazado")
except extractor.DocumentoDemasiadoGrande:
    ok(True, "PDF con demasiadas páginas rechazado")
w, h = extractor.render_all_pages_as_images(_pdf(1, 14400, 14400))[0].size
ok(w * h <= extractor.MAX_PIXELES_RENDER, f"página gigante renderizada con tope ({w}x{h})")

print("Launcher")
import launcher  # noqa: E402

ok(launcher._SOCK.getsockname()[1] == launcher.PORT and launcher.PORT != 8000, "puerto propio, elegido al azar")
otro = socket.socket()
try:
    otro.bind(("127.0.0.1", launcher.PORT))
    ok(False, "otro socket no puede enlazar el puerto de la app")
except OSError:
    ok(True, "otro socket no puede enlazar el puerto de la app")
finally:
    otro.close()
threading.Thread(target=launcher._run_server, daemon=True).start()
ok(launcher._wait_for_server(20), "el launcher reconoce su servidor por la firma")
try:
    urllib.request.urlopen(launcher.URL + "/api/history", timeout=3)
    ok(False, "servidor real sin token -> 401")
except urllib.error.HTTPError as e:
    ok(e.code == 401, "servidor real sin token -> 401")


class _Impostor(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"firma": "0" * 64}).encode())

    def log_message(self, *a):
        pass


falso = http.server.HTTPServer(("127.0.0.1", 0), _Impostor)
threading.Thread(target=falso.serve_forever, daemon=True).start()
url_real, launcher.URL = launcher.URL, f"http://127.0.0.1:{falso.server_address[1]}"
ok(launcher._wait_for_server(3) is False, "un impostor en el puerto es rechazado")
launcher.URL = url_real

abiertos = []
launcher._abrir_en_navegador = lambda url, *a: abiertos.append(url) or True
import webbrowser  # noqa: E402

ok(webbrowser.open("file:///C:/Windows/System32/calc.exe") is False, "window.open no abre file://")
ok(webbrowser.open("https://malo.example/") is False, "window.open no abre un sitio ajeno")
ok(launcher.open_url("https://aistudio.google.com.malo.example/") is False, "open_url rechaza un dominio parecido")
ok(webbrowser.open("https://aistudio.google.com/apikey") is True, "AI Studio sí se abre")

import webview  # noqa: E402

ventana = webview.create_window("prueba", html="<p>x</p>")
ventana.expose(launcher.save_xml_file, launcher.open_url)


def _resolver(nombre):  # misma lógica que webview.util.js_bridge_call
    f = ventana._functions.get(nombre)
    if f is not None:
        return f
    obj = ventana._js_api
    for parte in nombre.split("."):
        obj = getattr(obj, parte, None)
        if obj is None:
            return None
    return obj


ok(ventana._js_api is None, "la ventana no expone un objeto js_api")
ok(all(_resolver(n) is None for n in ("_window.gui.os.system", "save_xml_file.__globals__", "open_url.__globals__.clear")),
   "el puente no alcanza la ventana ni os.system")
ok(_resolver("save_xml_file") is launcher.save_xml_file, "el puente sí llega a save_xml_file")

print()
print("TODO OK" if not fallas else f"{fallas} FALLA(S)")
sys.exit(1 if fallas else 0)
