"""
test_v18_datos_arranque.py — versión 1.8: base del historial robusta (base
dañada, tabla ausente, poda a 300), arranque del launcher (hilo muerto, sin
proxy, carpeta de datos) y clave guardada (caché, archivos ilegibles).

    PYTHONUTF8=1 backend/venv/bin/python dev/test_v18_datos_arranque.py

No usa red externa ni Gemini. TODO va a una carpeta temporal (con acentos y
espacios a propósito): HOME se cambia ANTES de importar nada de la app para
que ni el historial ni la clave ni el .env reales se toquen, y
database.get_db_path se reemplaza antes de usar la base. Solo claves falsas.
"""

import atexit
import http.server
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))  # launcher.py vive en la raíz

# ── Aislamiento: todo en una carpeta temporal con acentos y espacios ────────
TMP = Path(tempfile.mkdtemp(prefix="conv v18 ñandú "))
atexit.register(shutil.rmtree, TMP, True)
os.environ["HOME"] = str(TMP / "home")
os.environ["LOCALAPPDATA"] = str(TMP / "home" / "AppData")
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("XDG_DATA_HOME", None)

import database  # noqa: E402

DB_DIR = TMP / "datos ñ" / "data"
DB_DIR.mkdir(parents=True)
DB_FILE = DB_DIR / "exams_history.db"
database.get_db_path = lambda: DB_FILE  # ANTES de cualquier uso de la base

import credenciales  # noqa: E402

os.environ.pop("GEMINI_API_KEY", None)  # por si config cargó un .env de desarrollo

fallas = 0


def ok(cond, msg):
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


def _limpiar_db():
    for f in DB_DIR.glob("*"):
        f.unlink()


# ═══════════════════════════ 1. database ═══════════════════════════
print("\n== database: base nueva y ciclo básico ==")
_limpiar_db()
ok(database.init_db() is True, "init_db() en carpeta con acentos y espacios devuelve True")
rid = database.save_conversion("a.xml", "Cat", 10.0, "<xml>A</xml>", '{"q":1}')
ok(isinstance(rid, int) and rid > 0, "save_conversion devuelve un id")
ok(database.get_xml_content(rid)["xml_content"] == "<xml>A</xml>", "get_xml_content devuelve lo guardado")
ok(database.get_editor_data(rid)["editor_json"] == '{"q":1}', "get_editor_data devuelve lo guardado")
lista = database.get_history_list()
ok(len(lista) == 1 and lista[0]["has_editor"] is True, "get_history_list lista la fila con has_editor")
ok(database.delete_history_item(rid) is True and database.get_history_list() == [], "delete_history_item borra")
ok(database.get_xml_content(99999) is None, "id inexistente devuelve None")

print("\n== database: tabla ausente (base vacía / tabla borrada) ==")
_limpiar_db()
sqlite3.connect(DB_FILE).close()  # archivo SQLite válido pero sin tablas
ok(database.get_history_list() == [], "get_history_list sin tabla devuelve [] (la crea)")
_limpiar_db()
sqlite3.connect(DB_FILE).close()
ok(database.get_xml_content(1) is None, "get_xml_content sin tabla devuelve None")
_limpiar_db()
sqlite3.connect(DB_FILE).close()
ok(database.get_editor_data(1) is None, "get_editor_data sin tabla devuelve None")
_limpiar_db()
sqlite3.connect(DB_FILE).close()
ok(database.delete_history_item(1) is False, "delete_history_item sin tabla devuelve False")
_limpiar_db()
sqlite3.connect(DB_FILE).close()
rid = database.save_conversion("b.xml", "Cat", 5.0, "<xml>B</xml>")
ok(rid == 1 and database.get_xml_content(rid)["xml_content"] == "<xml>B</xml>",
   "save_conversion sin tabla la crea y reintenta una vez")
# Tabla borrada con la app corriendo
with sqlite3.connect(DB_FILE) as c:
    c.execute("DROP TABLE history")
rid = database.save_conversion("c.xml", "Cat", 5.0, "<xml>C</xml>")
ok(len(database.get_history_list()) == 1, "tabla borrada a mitad de sesión: se recrea al guardar")

print("\n== database: otros errores se propagan ==")
_orig_connection = database._connection


class _Falla:
    def __enter__(self):
        raise sqlite3.OperationalError("database or disk is full")

    def __exit__(self, *a):
        return False


database._connection = lambda: _Falla()
try:
    database.save_conversion("d.xml", "Cat", 1.0, "<x/>")
    ok(False, "disco lleno se propaga desde save_conversion")
except sqlite3.OperationalError as exc:
    ok("full" in str(exc), "disco lleno se propaga desde save_conversion (main.py lo captura)")
database._connection = _orig_connection

print("\n== database: base dañada ==")
_limpiar_db()
DB_FILE.write_bytes(b"esto no es una base de datos sqlite " * 100)
ok(database.init_db() is True, "init_db con archivo corrupto no lanza y devuelve True")
baks = sorted(DB_DIR.glob("*.bak"))
ok(len(baks) == 1 and baks[0].read_bytes().startswith(b"esto no es"), "la base dañada quedó como .bak con su contenido")
ok(database.get_history_list() == [] and database.save_conversion("e.xml", "C", 1.0, "<x/>") > 0,
   "la base nueva funciona")
# Segunda corrupción: no pisa el backup anterior
DB_FILE.write_bytes(b"otra corrupcion " * 100)
time.sleep(0.01)
database.init_db()
baks2 = sorted(DB_DIR.glob("*.bak"))
ok(len(baks2) == 2 and baks[0] in baks2, "segundo daño: dos .bak, el anterior intacto")
# Corrupción interna (encabezado válido, páginas rotas): quick_check
_limpiar_db()
database.init_db()
for i in range(20):
    database.save_conversion(f"f{i}.xml", "C", 1.0, "<x>" + "z" * 5000 + "</x>")
data = bytearray(DB_FILE.read_bytes())
for pos in range(4096, len(data), 4096):  # se destrozan páginas de datos, no el encabezado
    data[pos:pos + 64] = b"\xff" * 64
DB_FILE.write_bytes(bytes(data))
res = database.init_db()
ok(res is True and len(list(DB_DIR.glob("*.bak"))) == 1 and database.get_history_list() == [],
   "páginas internas rotas se detectan (quick_check) y se recrea la base")

print("\n== database: errores que NO son daño no renombran la base ==")
_limpiar_db()
database.init_db()
database.save_conversion("g.xml", "C", 1.0, "<x/>")
_orig_crear = database._crear_o_migrar


def _bloqueada():
    raise sqlite3.OperationalError("database is locked")


database._crear_o_migrar = _bloqueada
ok(database.init_db() is False, "base bloqueada: init_db devuelve False sin lanzar")
database._crear_o_migrar = _orig_crear
ok(not list(DB_DIR.glob("*.bak")) and len(database.get_history_list()) == 1, "la base no se renombró ni perdió datos")


def _sin_permiso():
    raise PermissionError(13, "Permission denied")


database._crear_o_migrar = _sin_permiso
ok(database.init_db() is False, "carpeta sin permisos: init_db devuelve False sin lanzar")
database._crear_o_migrar = _orig_crear

print("\n== database: poda a MAX_HISTORIAL ==")
_limpiar_db()
database.init_db()
ok(database.MAX_HISTORIAL == 300, "el tope es 300 (el mismo que ya listaba la app; constante única)")
ids = [database.save_conversion(f"p{i}.xml", "C", 1.0, f"<x>{i}</x>", f'{{"i":{i}}}') for i in range(database.MAX_HISTORIAL + 15)]
lista = database.get_history_list()
ok(len(lista) == database.MAX_HISTORIAL, f"quedan {database.MAX_HISTORIAL} filas (hay {len(lista)})")
ok(lista[0]["id"] == ids[-1] and lista[-1]["id"] == ids[15], "se borraron las 15 más antiguas y quedan las más recientes")
ok(database.get_xml_content(ids[0]) is None and database.get_xml_content(ids[-1])["xml_content"] == f"<x>{len(ids) - 1}</x>",
   "las borradas ya no se descargan; las recientes sí")
ok(database.get_editor_data(ids[-1])["editor_json"] == f'{{"i":{len(ids) - 1}}}', "reabrir (editor_json) sigue funcionando")
with sqlite3.connect(DB_FILE) as c:
    modo = c.execute("PRAGMA auto_vacuum").fetchone()[0]
ok(modo == 2, "la base nueva usa auto_vacuum incremental (el espacio se devuelve sin VACUUM completo)")

print("\n== database: poda por tamaño total ==")
_limpiar_db()
database.init_db()
tope0 = database.MAX_HISTORIAL_BYTES
database.MAX_HISTORIAL_BYTES = 100_000
grande = "y" * 30_000
ids = [database.save_conversion(f"t{i}.xml", "C", 1.0, grande) for i in range(6)]
lista = database.get_history_list()
ok(len(lista) < 6 and lista[0]["id"] == ids[-1], f"el tope de tamaño borra antiguas y conserva la última ({len(lista)} filas)")
database.MAX_HISTORIAL_BYTES = 10  # una sola fila ya lo excede: nunca se borra la recién guardada
nueva = database.save_conversion("u.xml", "C", 1.0, grande)
ok(database.get_xml_content(nueva) is not None, "la fila recién guardada nunca se poda")
database.MAX_HISTORIAL_BYTES = tope0

print("\n== database: fallo al podar no invalida el guardado ==")
_orig_podar = database._podar
database._podar = lambda conn: (_ for _ in ()).throw(sqlite3.OperationalError("boom"))
rid = database.save_conversion("v.xml", "C", 1.0, "<x/>")
ok(database.get_xml_content(rid) is not None, "si la poda falla, la conversión queda guardada")
database._podar = _orig_podar

# ═══════════════════════════ 2. launcher ═══════════════════════════
print("\n== launcher ==")
import launcher  # noqa: E402

LOG = TMP / "log ñ" / "launcher_error.log"
LOG.parent.mkdir()
launcher.LOG_PATH = str(LOG)

# carpeta de datos inaccesible: no revienta
_orig_makedirs = os.makedirs


def _makedirs_falla(*a, **k):
    raise PermissionError(13, "denegado")


os.makedirs = _makedirs_falla
try:
    launcher._FALLO_CARPETA_DATOS.clear()
    ruta = launcher._app_data_dir()
    ok(os.path.isdir(ruta) and launcher._FALLO_CARPETA_DATOS, "carpeta de datos inaccesible: no lanza y usa la temporal")
finally:
    os.makedirs = _orig_makedirs
ruta_ok = launcher._app_data_dir()
ok(os.path.isdir(ruta_ok) and str(TMP) in ruta_ok, "con HOME con acentos y espacios crea la carpeta normal")

# el opener de salud ignora el proxy
proxies = [h for h in launcher._SIN_PROXY.handlers if isinstance(h, launcher.urllib.request.ProxyHandler)]
ok(not any(hasattr(h, "http_open") for h in proxies), "la comprobación de salud usa un opener sin proxy")


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        cuerpo = json.dumps({"firma": "x"}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", 0), _H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["http_proxy"] = os.environ["HTTP_PROXY"] = "http://127.0.0.1:1"  # proxy que rechaza todo
try:
    with launcher._SIN_PROXY.open(f"http://127.0.0.1:{srv.server_address[1]}/", timeout=2) as r:
        ok(r.status == 200, "con un proxy roto en el entorno, el opener sin proxy llega a 127.0.0.1")
finally:
    os.environ.pop("http_proxy", None)
    os.environ.pop("HTTP_PROXY", None)
    srv.shutdown()

# hilo del servidor muerto: no se espera el plazo completo
launcher.URL = "http://127.0.0.1:9"  # puerto cerrado
muerto = threading.Thread(target=lambda: None)
muerto.start()
muerto.join()
launcher._SERVIDOR_HILO = muerto
launcher._SERVIDOR_CAUSA = "RuntimeError: prueba"
t0 = time.time()
res = launcher._wait_for_server(timeout=30)
dt = time.time() - t0
ok(res is False and dt < 3, f"hilo del servidor muerto: falla de inmediato ({dt:.2f} s, no 30 s)")
texto = LOG.read_text(encoding="utf-8") if LOG.exists() else ""
ok("terminó antes de responder" in texto and "RuntimeError: prueba" in texto, "la causa queda en launcher_error.log")
ok("RuntimeError: prueba" in launcher._error_html(launcher.LOG_PATH, launcher._SERVIDOR_CAUSA),
   "la pantalla de error muestra el detalle técnico")
ok("Detalle" not in launcher._error_html(launcher.LOG_PATH), "sin causa, la pantalla de error queda como antes")

# los errores de uvicorn van al registro
launcher._enganchar_errores_uvicorn()
import logging  # noqa: E402

logging.getLogger("uvicorn.error").error("fallo de arranque de prueba")
ok("fallo de arranque de prueba" in LOG.read_text(encoding="utf-8"), "los errores de uvicorn se escriben en el registro del launcher")

# ═══════════════════════════ 3. credenciales ═══════════════════════════
print("\n== credenciales ==")
CDIR = TMP / "Clave ñ con espacios"
CDIR.mkdir()
credenciales.ARCHIVO = CDIR / "clave.dat"
credenciales.ENV_PATH = CDIR / ".env"
FALSA = "CLAVE-FALSA-DE-PRUEBA-1234"


def _reset():
    credenciales._cache = None
    credenciales._origen = None
    credenciales._firma_cache = None
    credenciales._aviso = None


_reset()
ok(credenciales.estado() == {"configurada": False, "origen": None, "final": None}, "sin clave: estado vacío")
credenciales.guardar(FALSA)
e = credenciales.estado()
ok(e == {"configurada": True, "origen": "archivo", "final": FALSA[-4:]} and FALSA not in json.dumps(e),
   "guardar → estado muestra solo los 4 últimos")

# caché: estado()/get_api_key() no vuelven a descifrar ni a derivar
llamadas = {"fernet": 0}
_orig_fernet = credenciales._fernet


def _fernet_contado(sal):
    llamadas["fernet"] += 1
    return _orig_fernet(sal)


credenciales._fernet = _fernet_contado
for _ in range(5):
    credenciales.estado()
    credenciales.get_api_key()
ok(llamadas["fernet"] == 0, "estado()/get_api_key() repetidos no descifran clave.dat")
_reset()
credenciales.estado()
credenciales.estado()
ok(llamadas["fernet"] == 1, "tras un arranque en frío se descifra una sola vez")

# id del equipo cacheado
credenciales._id_del_equipo.cache_clear()
for _ in range(3):
    credenciales._id_del_equipo()
ok(credenciales._id_del_equipo.cache_info().hits >= 2 and credenciales._id_del_equipo.cache_info().misses == 1,
   "_id_del_equipo se calcula una vez (caché)")

# cambio externo del archivo invalida la caché
credenciales._fernet = _orig_fernet
credenciales._escribir_archivo("OTRA-CLAVE-FALSA-9999")
ok(credenciales.get_api_key() == "OTRA-CLAVE-FALSA-9999", "si clave.dat cambia por fuera, se relee")
credenciales.ARCHIVO.unlink()
ok(credenciales.get_api_key() == "" and credenciales.estado()["configurada"] is False, "si clave.dat desaparece, se invalida")
credenciales.guardar(FALSA)

# archivos ilegibles / con otra forma → «sin clave», sin excepción ni 500
for nombre, contenido in [("lista", "[1,2,3]"), ("nulo", "null"), ("texto", '"hola"'), ("basura", "\x00\xff{{{"),
                          ("sin sal", '{"clave": "x"}'), ("tipos", '{"sal": 5, "clave": 7}'), ("vacío", "")]:
    _reset()
    credenciales.ARCHIVO.write_bytes(contenido.encode("latin-1", "replace"))
    try:
        clave = credenciales.get_api_key()
        e = credenciales.estado()
        ok(clave == "" and e["configurada"] is False and "aviso" in e, f"clave.dat «{nombre}» se trata como sin clave, con aviso")
    except Exception as exc:  # noqa: BLE001
        ok(False, f"clave.dat «{nombre}» lanzó {type(exc).__name__}")
ok("CLAVE" not in json.dumps(credenciales.estado()), "el aviso no expone contenido")

# OSError (antivirus/permisos)
if hasattr(os, "geteuid") and os.geteuid() != 0:
    credenciales.guardar(FALSA)
    _reset()
    os.chmod(credenciales.ARCHIVO, 0)
    try:
        ok(credenciales.get_api_key() == "" and "aviso" in credenciales.estado(), "archivo sin permiso de lectura: sin clave, sin excepción")
    finally:
        os.chmod(credenciales.ARCHIVO, 0o600)
else:
    print("  (omitida la prueba de permisos: se ejecuta como root o sin geteuid)")

# guardar tras un archivo dañado repone todo
credenciales.guardar(FALSA)
ok(credenciales.get_api_key() == FALSA and credenciales.estado()["origen"] == "archivo", "guardar tras un archivo dañado lo repone")
credenciales.borrar()
ok(credenciales.estado()["configurada"] is False and not credenciales.ARCHIVO.exists(), "borrar deja la app sin clave")

# entorno
os.environ["GEMINI_API_KEY"] = "ENTORNO-FALSA-0000"
_reset()
e = credenciales.estado()
ok(e["origen"] == "entorno" and e["final"] == "0000", "clave del entorno: origen «entorno»")
os.environ.pop("GEMINI_API_KEY", None)
_reset()

# .env ilegible no rompe la lectura
credenciales.ENV_PATH.write_bytes(b"\xff\xfe\x00GEMINI_API_KEY=\xff")
ok(credenciales._clave_en_env_de_datos() == "" and credenciales.get_api_key() == "", ".env con bytes inválidos se ignora")

print()
if fallas:
    print(f"HAY {fallas} FALLA(S)")
    sys.exit(1)
print("TODO OK")
