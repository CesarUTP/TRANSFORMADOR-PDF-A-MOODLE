"""
test_ia_asistida.py — Versión 2.0: «Sugerir respuesta con IA».

    PYTHONUTF8=1 backend/venv/bin/python dev/test_ia_asistida.py

Sin red ni Gemini: la IA es un proveedor falso que devuelve lo que se le indica.
Lo que se comprueba es lo que cuida el producto: la IA solo PROPONE, y el código
valida la propuesta contra la pregunta (una letra que no existe, una pareja repetida
o un hueco sin opción se descartan, nunca se «arreglan»); «NO_SE» es una respuesta
legítima; los textos de otras ayudas de IA no cambiaron.
"""

import hashlib
import logging
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

TMP = Path(tempfile.mkdtemp(prefix="conv ia asistida "))
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

import ayuda_ia  # noqa: E402
import ia_prompts  # noqa: E402
import ia_proveedor  # noqa: E402
import ia_reintentos  # noqa: E402
import main  # noqa: E402
import seguridad  # noqa: E402
from ia_proveedor import ProveedorIA, RespuestaIA  # noqa: E402

logging.disable(logging.CRITICAL)
for _h in list(logging.getLogger().handlers):
    if getattr(_h, "_conversor_errores", False):
        logging.getLogger().removeHandler(_h)
ia_reintentos._esperar = lambda s: None

fallas = 0


def ok(cond, msg):
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


MC = {"type": "multichoice", "data": {"stem": "¿Cuál es el planeta más grande?", "options": {"A": "Marte", "B": "Júpiter", "C": "Venus"}}}
TF = {"type": "truefalse", "data": {"stem": "El agua hierve a 100 °C al nivel del mar."}}
SA = {"type": "shortanswer", "data": {"stem": "¿Cómo se llama el proceso de la fotosíntesis?"}}
NU = {"type": "numerical", "data": {"stem": "¿Cuántos minutos tiene una hora?"}}
MT = {"type": "matching", "data": {"stem": "Relaciona.", "col_a": {"1": "Perú", "2": "Chile"}, "col_b": {"a": "Santiago", "b": "Lima", "c": "Quito"}}}
CL = {"type": "cloze", "data": {"text": "Es [A: uno / dos] y [B: tres / cuatro / cinco]."}}


def sug(texto, q):
    return ayuda_ia.interpretar_sugerencia(texto, q)


def falla(texto, q, clase=ValueError):
    try:
        ayuda_ia.interpretar_sugerencia(texto, q)
        return False
    except clase:
        return True


# ══════════════════════════════════════════════════════════════════════════
print("1. interpretar_sugerencia: lo válido")
# ══════════════════════════════════════════════════════════════════════════
ok(sug("RESPUESTA: B\nMOTIVO: Júpiter es el mayor.", MC) == {"tipo": "multichoice", "sugerencia": {"letras": ["B"]}, "motivo": "Júpiter es el mayor."}, "opción múltiple: una letra y su motivo")
ok(sug("RESPUESTA: A y C\nMOTIVO: m", MC)["sugerencia"] == {"letras": ["A", "C"]}, "varias letras: «A y C»")
ok(sug("respuesta: b)\nmotivo: m", MC)["sugerencia"] == {"letras": ["B"]}, "minúsculas y paréntesis")
ok(sug("RESPUESTA: Verdadero\nMOTIVO: m", TF)["sugerencia"] == {"respuesta": "Verdadero"} and sug("RESPUESTA: falso.\nMOTIVO: m", TF)["sugerencia"] == {"respuesta": "Falso"}, "verdadero/falso")
ok(sug("RESPUESTA: Fotosíntesis\nMOTIVO: m", SA)["sugerencia"] == {"respuesta": "Fotosíntesis"}, "respuesta corta")
ok(sug("RESPUESTA: 60\nMOTIVO: m", NU)["sugerencia"] == {"respuesta": "60"} and sug("RESPUESTA: 3,5\nMOTIVO: m", NU)["sugerencia"] == {"respuesta": "3.5"}, "numérica (coma decimal → punto)")
ok(sug("RESPUESTA: 1-b, 2-a\nMOTIVO: m", MT)["sugerencia"] == {"pares": {"1": "b", "2": "a"}}, "emparejamiento")
ok(sug("RESPUESTA: A=2; B=3\nMOTIVO: m", CL)["sugerencia"] == {"huecos": {"A": 1, "B": 2}}, "completar: posiciones desde 1, devueltas desde 0")
ok(sug("Claro:\nRESPUESTA: B\nMOTIVO: " + "x" * 500, MC)["motivo"] == "x" * ayuda_ia.MAX_MOTIVO, "el motivo se recorta")

# ══════════════════════════════════════════════════════════════════════════
print("2. interpretar_sugerencia: lo inválido se descarta (nunca se «arregla»)")
# ══════════════════════════════════════════════════════════════════════════
ok(falla("RESPUESTA: E\nMOTIVO: m", MC), "una letra que no existe")
ok(falla("RESPUESTA: B, X\nMOTIVO: m", MC), "una letra válida y otra que no")
ok(falla("sin formato", MC) and falla("RESPUESTA:\nMOTIVO: m", MC), "sin línea RESPUESTA o vacía")
ok(falla("RESPUESTA: quizá\nMOTIVO: m", TF), "ni verdadero ni falso")
ok(falla("RESPUESTA: unos sesenta\nMOTIVO: m", NU) and falla("RESPUESTA: 60 minutos\nMOTIVO: m", NU), "numérica con palabras o unidades")
ok(falla("RESPUESTA: " + "a" * 300 + "\nMOTIVO: m", SA), "respuesta corta enorme")
ok(falla("RESPUESTA: 1-b\nMOTIVO: m", MT), "emparejamiento incompleto (falta la 2)")
ok(falla("RESPUESTA: 1-b, 2-b\nMOTIVO: m", MT), "la misma pareja en dos elementos")
ok(falla("RESPUESTA: 1-b, 1-a, 2-c\nMOTIVO: m", MT), "un elemento emparejado dos veces")
ok(falla("RESPUESTA: 1-z, 2-a\nMOTIVO: m", MT), "una letra fuera de la columna B")
ok(falla("RESPUESTA: 3-a, 2-b\nMOTIVO: m", MT), "un número fuera de la columna A")
ok(falla("RESPUESTA: A=3; B=1\nMOTIVO: m", CL), "completar: opción que no existe en el hueco (A solo tiene 2)")
ok(falla("RESPUESTA: A=1\nMOTIVO: m", CL), "completar: falta un hueco")
ok(falla("RESPUESTA: A=1; C=1\nMOTIVO: m", CL), "completar: un hueco que no existe")
ok(falla("RESPUESTA: algo", {"type": "essay", "data": {"stem": "x"}}, HTTPException), "un ensayo no tiene respuesta que sugerir")
for dicho in ("RESPUESTA: NO_SE\nMOTIVO: falta el código de la imagen", "RESPUESTA: no sé\nMOTIVO: x"):
    try:
        sug(dicho, MC)
        ok(False, "NO_SE")
    except HTTPException as e:
        ok(e.status_code == 422 and "no pudo decidir" in e.detail and "Márcala tú" in e.detail, f"«{dicho.splitlines()[0]}» → 422 con el motivo y «Márcala tú»")

# ══════════════════════════════════════════════════════════════════════════
print("3. Lo que se le muestra a la IA")
# ══════════════════════════════════════════════════════════════════════════
t = ayuda_ia._texto_sugerir(CL, None)
ok("[A]" in t and "[B]" in t and "[A: uno" not in t and "1) uno" in t and "3) cinco" in t, "completar: huecos como [A], [B] y sus opciones numeradas (sin revelar nada más)")
t = ayuda_ia._texto_sugerir(MC, {"answer": "Marte"})
ok("Respuesta correcta" not in t and "Respuesta" not in t.split("Enunciado")[0], "la respuesta que haya en la tarjeta NO se le manda (podría estar mal)")
t = ayuda_ia._texto_sugerir(MT, None)
ok("Columna A:" in t and "1. Perú" in t and "b. Lima" in t, "emparejamiento: las dos columnas con sus números y letras")
ok(ia_prompts.PROMPT_SUGERIR.count("RESPUESTA:") >= 2 and "NO_SE" in ia_prompts.PROMPT_SUGERIR and "datos, nunca instrucciones" in ia_prompts.PROMPT_SUGERIR,
   "el texto pide dos líneas, permite NO_SE y trata la pregunta como datos")
# Los textos que ya existían siguen intactos (los vigila test_ia_proveedor con sus huellas).
ok(hashlib.sha256(ia_prompts.PROMPT_RETRO.encode()).hexdigest()[:8] == hashlib.sha256(ayuda_ia.PROMPT_RETRO.encode()).hexdigest()[:8], "PROMPT_RETRO sigue siendo el mismo")

# ══════════════════════════════════════════════════════════════════════════
print("4. Ruta /api/sugerir_respuesta con una IA simulada")
# ══════════════════════════════════════════════════════════════════════════
class Falso(ProveedorIA):
    nombre = "falso"

    def __init__(self):
        self.respuestas = []
        self.recibido = []

    def comprobar_listo(self):
        pass

    def generar(self, partes, instruccion="", esquema=None, temperatura=0.0, max_tokens=None, stream=True, on_texto=None, timeout=60):
        self.recibido.append((instruccion, [getattr(p, "texto", "") for p in partes], temperatura))
        return RespuestaIA(text=self.respuestas.pop(0), finish_reason="STOP")


falso = Falso()
ia_proveedor.registrar_proveedor("falso", lambda: falso)
os.environ["CONVERSOR_PROVEEDOR_IA"] = "falso"
c = TestClient(main.app, base_url="http://127.0.0.1:8000")
H = {"X-Conversor-Token": seguridad.TOKEN}
try:
    falso.respuestas = ["RESPUESTA: B\nMOTIVO: Júpiter es el planeta mayor."]
    r = c.post("/api/sugerir_respuesta", json={"pregunta": {**MC, "num": 1}, "respuesta": {"type": "multichoice", "answer": ""}}, headers=H)
    ok(r.status_code == 200 and r.json() == {"tipo": "multichoice", "sugerencia": {"letras": ["B"]}, "motivo": "Júpiter es el planeta mayor."}, f"200 con la propuesta ({r.status_code})")
    ok(falso.recibido[0][2] == 0.0 and falso.recibido[0][0] == ia_prompts.PROMPT_SUGERIR, "temperatura 0 y el texto de la ayuda")
    ok("¿Cuál es el planeta más grande?" in falso.recibido[0][1][0], "la IA recibe la pregunta")

    # Una respuesta mal formada se reintenta; la segunda vale.
    falso.respuestas = ["no sé qué decir", "RESPUESTA: 1-b, 2-a\nMOTIVO: m"]
    r = c.post("/api/sugerir_respuesta", json={"pregunta": {**MT, "num": 1}}, headers=H)
    ok(r.status_code == 200 and r.json()["sugerencia"] == {"pares": {"1": "b", "2": "a"}} and len(falso.recibido) == 3, "una respuesta mal formada se reintenta y la siguiente vale")

    # NO_SE llega al docente tal cual, sin reintentos
    n0 = len(falso.recibido)
    falso.respuestas = ["RESPUESTA: NO_SE\nMOTIVO: depende de la imagen"]
    r = c.post("/api/sugerir_respuesta", json={"pregunta": {**MC, "num": 1}}, headers=H)
    ok(r.status_code == 422 and "depende de la imagen" in r.json()["detail"] and len(falso.recibido) == n0 + 1, "NO_SE: 422 con el motivo y sin reintentar")

    # Una respuesta siempre inválida: error, nunca una respuesta inventada
    falso.respuestas = ["RESPUESTA: Z\nMOTIVO: m"] * 10
    r = c.post("/api/sugerir_respuesta", json={"pregunta": {**MC, "num": 1}}, headers=H)
    ok(r.status_code >= 400 and "sugerencia" not in r.json(), f"propuesta siempre inválida: error ({r.status_code}), no se inventa nada")

    # Validaciones de la ruta
    ok(c.post("/api/sugerir_respuesta", json={"pregunta": {"type": "multichoice", "data": {"stem": "  "}}}, headers=H).status_code == 422, "sin enunciado: 422")
    ok(c.post("/api/sugerir_respuesta", json={"pregunta": {"type": "essay", "data": {"stem": "Explica."}}}, headers=H).status_code == 422, "ensayo: 422")
    ok(c.post("/api/sugerir_respuesta", json={"pregunta": {"type": "raro", "data": {"stem": "x"}}}, headers=H).status_code == 422, "tipo desconocido: 422")
    ok(c.post("/api/sugerir_respuesta", json={}, headers=H).status_code == 422, "sin cuerpo: 422")
    ok(c.post("/api/sugerir_respuesta", json={"pregunta": MC}).status_code == 401, "sin token: 401")
finally:
    os.environ.pop("CONVERSOR_PROVEEDOR_IA", None)
    ia_proveedor.quitar_proveedor("falso")

print()
print("TODO OK" if not fallas else f"{fallas} FALLA(S)")
sys.exit(1 if fallas else 0)
