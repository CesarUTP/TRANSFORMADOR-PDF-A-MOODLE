"""
test_versiones.py — Versión 2.5: varias versiones impresas de un mismo examen.

    PYTHONUTF8=1 backend/venv/bin/python dev/test_versiones.py

Sin red ni Gemini; la base es temporal. Un examen de 100 preguntas (50 de selección múltiple, 30 de
emparejamiento y 20 de verdadero o falso) sirve de banco:
  1. versiones.subconjunto: copias, orden pedido, clave de cada pregunta, puntos propios, errores.
  2. /api/exportar_versiones: un ZIP con un PDF por versión; cada PDF trae SOLO sus preguntas, dice qué
     versión es (también en la clave) y su clave coincide con la del examen completo.
  3. Lo que se rechaza: token, versión vacía o repetida, números que no existen, nombres repetidos, tope.
"""

import io
import json
import logging
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "dev"))

TMP = Path(tempfile.mkdtemp(prefix="conv versiones "))
os.environ["HOME"] = str(TMP / "home")
os.environ["LOCALAPPDATA"] = str(TMP / "home" / "AppData")
(TMP / "datos" / "data").mkdir(parents=True)
import database  # noqa: E402

database.get_db_path = lambda: TMP / "datos" / "data" / "exams_history.db"  # ANTES de importar main

import pdfplumber  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import seguridad  # noqa: E402
import versiones  # noqa: E402

logging.disable(logging.CRITICAL)
fallas = 0


def ok(cond, msg):
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


def texto_de(pdf: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf)) as d:
        return "\n".join(p.extract_text() or "" for p in d.pages)


# ── El examen de 100 preguntas ──────────────────────────────────────────
questions, key = [], {}
LETRAS = "ABCD"
for i in range(1, 101):
    if i <= 50:
        correcta = (i * 7) % 4
        questions.append({"num": i, "type": "multichoice", "points": 1.0,
                          "data": {"stem": f"PREG{i:03d} de selección", "options": {L: f"op{i:03d}{L}" for L in LETRAS}}})
        key[i] = {"type": "multichoice", "answer": LETRAS[correcta]}
    elif i <= 80:
        questions.append({"num": i, "type": "matching", "points": 2.0,
                          "data": {"stem": f"PREG{i:03d} une", "col_a": {"1": f"izq{i:03d}x", "2": f"izq{i:03d}y"},
                                   "col_b": {"a": f"der{i:03d}p", "b": f"der{i:03d}q"}}})
        key[i] = {"type": "matching", "answer": "1-b; 2-a", "pairs": {"1": "b", "2": "a"}}
    else:
        questions.append({"num": i, "type": "truefalse", "points": 1.0, "data": {"stem": f"PREG{i:03d} afirmación"}})
        key[i] = {"type": "truefalse", "answer": "Verdadero" if i % 2 else "Falso"}
TOTAL = sum(q["points"] for q in questions)
CLAVE_JSON = {str(k): v for k, v in key.items()}

# ══════════════════════════════════════════════════════════════════════════
print("1. versiones.subconjunto")
# ══════════════════════════════════════════════════════════════════════════
qs, kv = versiones.subconjunto(questions, key, [90, 3, 60], {3: 5, "60": 0.5})
ok([q["num"] for q in qs] == [90, 3, 60], "respeta el orden pedido")
ok(sorted(kv) == [3, 60, 90] and kv[3] == key[3] and kv[60] == key[60] and kv[90] == key[90], "cada pregunta lleva SU clave (la del examen completo)")
ok([q["points"] for q in qs] == [1.0, 5.0, 0.5], "los puntos editados mandan; el resto conserva los suyos")
ok(questions[2]["points"] == 1.0 and "points" in questions[0], "el examen original no se toca")
for malo, texto in (([], "vacía"), ([1, 1], "repetida"), ([1, 999], "inexistente")):
    try:
        versiones.subconjunto(questions, key, malo)
        ok(False, f"una versión {texto} se rechaza")
    except versiones.VersionInvalida:
        ok(True, f"una versión {texto} se rechaza")
for p in (-1, float("nan"), "x", True):
    try:
        versiones.subconjunto(questions, key, [1], {1: p})
        ok(False, f"puntos {p!r} se rechazan")
    except versiones.VersionInvalida:
        ok(True, f"puntos {p!r} se rechazan")
ok(versiones.etiqueta_para_archivo("Versión Ñ/2") == "Version_N_2" and versiones.etiqueta_para_archivo("///") == "X", "la etiqueta es segura para un nombre de archivo")
z = zipfile.ZipFile(io.BytesIO(versiones.empaquetar([("a.pdf", b"1"), ("a.pdf", b"2"), ("b.pdf", b"3")])))
ok(sorted(z.namelist()) == ["a.pdf", "a_2.pdf", "b.pdf"], "el ZIP numera los nombres repetidos")

# ══════════════════════════════════════════════════════════════════════════
print("2. /api/exportar_versiones")
# ══════════════════════════════════════════════════════════════════════════
main.init_db()
cli = TestClient(main.app, base_url="http://127.0.0.1:8000")
H = {"X-Conversor-Token": seguridad.TOKEN}
# Cuatro versiones con 25 preguntas cada una, sin repetir ninguna (25 × 4 = 100).
reparto = [list(range(1 + 25 * v, 26 + 25 * v)) for v in range(4)]
cuerpo = {"filename": "banco 100.docx", "total_points": TOTAL, "questions": questions, "answer_key": CLAVE_JSON,
          "datos": {"materia": "Física", "actividad": "Parcial", "docente": "Ana", "contenido": "examen_y_clave", "mezclar": False},
          "versiones": [{"etiqueta": "ABCD"[v], "nums": nums, "total_points": float(sum(questions[n - 1]["points"] for n in nums))} for v, nums in enumerate(reparto)]}
r = cli.post("/api/exportar_versiones", json=cuerpo, headers=H)
ok(r.status_code == 200 and r.headers["content-type"] == "application/zip", f"200 con un ZIP ({r.status_code})")
info = json.loads(r.headers["x-pdf-info"])
ok([v["etiqueta"] for v in info["versiones"]] == list("ABCD") and all(v["preguntas"] == 25 for v in info["versiones"]), f"X-PDF-Info resume cada versión {info['versiones']}")
ok("banco%20100_versiones.zip" in r.headers["content-disposition"] or "banco 100_versiones.zip" in r.headers["content-disposition"], r.headers["content-disposition"])
z = zipfile.ZipFile(io.BytesIO(r.content))
ok(sorted(z.namelist()) == [f"banco 100_version_{L}_examen_y_clave.pdf" for L in "ABCD"], f"un PDF por versión: {z.namelist()}")
for L, nums in zip("ABCD", reparto):
    t = texto_de(z.read(f"banco 100_version_{L}_examen_y_clave.pdf"))
    corte = t.index("CLAVE DE RESPUESTAS")
    examen, clave = t[:corte], t[corte:]
    propias = [f"PREG{n:03d}" for n in nums]
    ajenas = [f"PREG{n:03d}" for n in range(1, 101) if n not in nums]
    ok(all(p in examen for p in propias), f"versión {L}: trae sus 25 preguntas")
    ok(not any(a in t for a in ajenas), f"versión {L}: no trae ninguna pregunta de otra versión")
    ok(f"VERSIÓN {L}" in examen and f"VERSIÓN {L}" in clave, f"versión {L}: se llama así en el examen y en la clave")
    # La clave de una versión es la de sus preguntas: la letra correcta de cada selección múltiple figura en ella.
    malas = []
    for n in nums:
        if n <= 50:
            L_ok = key[n]["answer"]
            if f"op{n:03d}{L_ok}" not in clave:
                malas.append(n)
    ok(not malas, f"versión {L}: la clave nombra la respuesta correcta de cada pregunta ({malas[:3]})")
    total_v = sum(questions[n - 1]["points"] for n in nums)
    ok(f"/{total_v:g}" in examen.replace(" ", ""), f"versión {L}: la calificación es sobre el total de SUS preguntas ({total_v:g})")

# El orden pedido manda y la numeración del papel es la de la versión.
r = cli.post("/api/exportar_versiones", headers=H, json={**cuerpo, "datos": {**cuerpo["datos"], "partes": False, "contenido": "solo_examen"},
             "versiones": [{"etiqueta": "Única", "nums": [3, 1, 2], "total_points": 3}]})
z = zipfile.ZipFile(io.BytesIO(r.content))
t = texto_de(z.read(z.namelist()[0]))
ok(r.status_code == 200 and t.index("PREG003") < t.index("PREG001") < t.index("PREG002"), "sin partes, las preguntas salen en el orden de la versión")
ok(z.namelist() == ["banco 100_version_Unica_examen.pdf"], str(z.namelist()))

# Los puntos editados por versión llegan al papel.
r = cli.post("/api/exportar_versiones", headers=H, json={**cuerpo, "datos": {**cuerpo["datos"], "contenido": "solo_examen"},
             "versiones": [{"etiqueta": "A", "nums": [1, 2], "puntos": {"1": 40, "2": 60}, "total_points": 100}]})
t = texto_de(zipfile.ZipFile(io.BytesIO(r.content)).read("banco 100_version_A_examen.pdf"))
ok(r.status_code == 200 and "100" in t and "40" in t and "60" in t, "los puntos editados (40 + 60 = 100) salen en el examen")

# ══════════════════════════════════════════════════════════════════════════
print("3. Lo que se rechaza")
# ══════════════════════════════════════════════════════════════════════════
ok(cli.post("/api/exportar_versiones", json=cuerpo).status_code == 401, "sin token: 401")
v0 = cuerpo["versiones"][0]
for nombre, versiones_malas in (
    ("sin versiones", []),
    ("una versión sin preguntas", [{**v0, "nums": []}]),
    ("una pregunta repetida en una versión", [{**v0, "nums": [1, 1]}]),
    ("una pregunta que no existe", [{**v0, "nums": [1, 500]}]),
    ("dos versiones con el mismo nombre", [v0, {**v0, "etiqueta": "a"}]),
    ("más de 12 versiones", [{**v0, "etiqueta": f"V{i}"} for i in range(13)]),
    ("puntos negativos", [{**v0, "puntos": {"1": -3}}]),
    ("un total de puntos en cero", [{**v0, "total_points": 0}]),
):
    ok(cli.post("/api/exportar_versiones", json={**cuerpo, "versiones": versiones_malas}, headers=H).status_code == 422, f"{nombre}: 422")
ok(cli.post("/api/exportar_versiones", json={**cuerpo, "datos": {"contenido": "otra"}}, headers=H).status_code == 422, "opciones desconocidas: 422")
malo = {**cuerpo, "questions": [{"num": 1, "type": "inventado", "data": {"stem": "a"}}], "answer_key": {"1": {"type": "essay", "answer": ""}},
        "versiones": [{"etiqueta": "A", "nums": [1], "total_points": 1}]}
ok(cli.post("/api/exportar_versiones", json=malo, headers=H).status_code == 422, "el examen se valida como para el XML: 422")
ok(cli.post("/api/exportar_pdf", json={"filename": "x.docx", "total_points": 1, "questions": questions[:1], "answer_key": {"1": key[1]},
                                       "datos": {"version": "A"}}, headers=H).status_code == 200, "un PDF suelto también puede llevar el nombre de su versión")

print()
print("TODO BIEN" if fallas == 0 else f"{fallas} FALLAS")
sys.exit(1 if fallas else 0)
