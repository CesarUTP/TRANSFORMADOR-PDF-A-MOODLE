"""
test_materias.py — Versión 2.3: «Mis materias» y «Mi perfil» (datos y rutas).

    PYTHONUTF8=1 backend/venv/bin/python dev/test_materias.py

Sin red ni Gemini; la base es temporal (nunca toca la del docente).
  1. Una base de la versión anterior (sin materias) se migra sin perder nada y deja una copia.
  2. Crear, listar, cambiar, archivar y borrar materias (nombre único sin distinguir mayúsculas, tope, validación).
  3. Guardar un examen con materia y actividad; moverlo; mover varios a la vez.
  4. Borrar una materia NO borra sus exámenes: pasan a «Sin materia».
  5. Política de borrado: al llenarse el Historial se van primero los exámenes sin materia.
  6. Uso del Historial y aviso de cercanía al límite.
  7. Las rutas: token, validación, 404, 409.
  8. Mi perfil: nombre y rótulo del docente, perfil predeterminado, renombrar y borrar perfiles sin dejar referencias rotas.
"""

import contextlib
import json
import logging
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "dev"))

TMP = Path(tempfile.mkdtemp(prefix="conv materias "))
os.environ["HOME"] = str(TMP / "home")
os.environ["LOCALAPPDATA"] = str(TMP / "home" / "AppData")
DB_DIR = TMP / "datos" / "data"
DB_DIR.mkdir(parents=True)
DB_FILE = DB_DIR / "exams_history.db"
import database  # noqa: E402

database.get_db_path = lambda: DB_FILE  # ANTES de importar main

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import seguridad  # noqa: E402

logging.disable(logging.CRITICAL)
fallas = 0


def ok(cond, msg):
    global fallas
    print(("  ok   " if cond else "  FALLA ") + msg)
    fallas += 0 if cond else 1


def fila_de(i):
    return [x for x in database.get_history_list() if x["id"] == i][0]


# ═══════════════ 1. Migración desde la base anterior ═══════════════
print("Migración de una base sin materias")
with contextlib.closing(sqlite3.connect(DB_FILE)) as c0:
    c0.execute("""CREATE TABLE history (id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, category TEXT NOT NULL,
                  total_points REAL NOT NULL, xml_content TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, editor_json TEXT)""")
    for i in range(3):
        c0.execute("INSERT INTO history (filename, category, total_points, xml_content, editor_json) VALUES (?,?,?,?,?)",
                   (f"viejo{i}.pdf", "Historia", 10.0, f"<quiz>{i}</quiz>", '{"questions":[],"answer_key":{}}'))
    c0.commit()
ok(database.init_db() is True, "init_db migra la base anterior")
with contextlib.closing(sqlite3.connect(DB_FILE)) as c1:
    cols = {r[1] for r in c1.execute("PRAGMA table_info(history)")}
    ok({"materia_id", "actividad"} <= cols, "history tiene materia_id y actividad")
    ok(c1.execute("SELECT count(*) FROM history").fetchone()[0] == 3, "los 3 exámenes anteriores siguen ahí")
    ok(c1.execute("SELECT count(*) FROM history WHERE materia_id IS NULL").fetchone()[0] == 3, "…sin materia")
    ok(c1.execute("SELECT name FROM sqlite_master WHERE name='materias'").fetchone() is not None, "existe la tabla materias")
copia = DB_FILE.with_name(DB_FILE.name + ".antes-de-materias.bak")
ok(copia.exists(), "se guardó una copia de la base antes de migrar")
with contextlib.closing(sqlite3.connect(copia)) as cc:
    ok(cc.execute("SELECT count(*) FROM history").fetchone()[0] == 3 and "materia_id" not in {r[1] for r in cc.execute("PRAGMA table_info(history)")},
       "la copia es la base ANTERIOR, con sus 3 exámenes")
antes = copia.stat().st_mtime_ns
ok(database.init_db() is True and copia.stat().st_mtime_ns == antes, "migrar otra vez no toca la copia")
lista = database.get_history_list()
ok(len(lista) == 3 and all(x["materia_id"] is None and x["actividad"] is None and x["bytes"] > 0 for x in lista), "la lista trae materia_id, actividad y tamaño")

# Una base nueva y vacía no necesita copia.
vacia = TMP / "otra" / "data"
vacia.mkdir(parents=True)
database.get_db_path = lambda: vacia / "exams_history.db"
database.init_db()
ok(not list(vacia.glob("*.bak")), "una base nueva no genera copia")
database.get_db_path = lambda: DB_FILE

# ═══════════════ 2. Materias ═══════════════
print("Materias")
m1 = database.create_materia("Historia de Panamá", "verde", "UTP", "Ana Pérez", "1IL-131")
ok(m1["id"] > 0 and m1["nombre"] == "Historia de Panamá" and m1["color"] == "verde" and m1["perfil"] == "UTP" and m1["archivada"] is False, "crear una materia con sus valores por defecto")
try:
    database.create_materia("historia DE panamá")
    ok(False, "nombre repetido (otra capitalización)")
except database.MateriaDuplicada:
    ok(True, "dos materias no pueden llamarse igual (sin distinguir mayúsculas)")
m2 = database.create_materia("Cálculo")
for repetido in ("CÁLCULO", "calculo", "  Cálculo  "):
    try:
        database.create_materia(repetido)
        ok(False, f"«{repetido}» es la misma materia que «Cálculo»")
    except database.MateriaDuplicada:
        ok(True, f"«{repetido}» es la misma materia que «Cálculo» (sin mayúsculas ni tildes)")
ok(m2["color"] == "azul" and m2["perfil"] is None and m2["docente"] is None, "una materia solo con nombre toma los valores de siempre")
ok([m["nombre"] for m in database.list_materias()] == ["Cálculo", "Historia de Panamá"], "se listan por orden alfabético")
ok(database.update_materia(m2["id"], {"nombre": "Cálculo I", "grupo": "2IS-11"})["nombre"] == "Cálculo I", "cambiar el nombre y el grupo")
try:
    database.update_materia(m2["id"], {"nombre": "HISTORIA DE PANAMÁ"})
    ok(False, "renombrar a un nombre que ya existe")
except database.MateriaDuplicada:
    ok(True, "renombrar a un nombre que ya existe se rechaza")
ok(database.update_materia(m2["id"], {"archivada": True})["archivada"] is True and database.update_materia(m2["id"], {"archivada": False})["archivada"] is False, "archivar y desarchivar")
ok(database.update_materia(m1["id"], {"perfil": None})["perfil"] is None, "vaciar el perfil por defecto")
ok(database.update_materia(9999, {"nombre": "x"}) is None, "una materia inexistente: None")

# ═══════════════ 3. Exámenes con materia ═══════════════
print("Exámenes con materia y actividad")
rid = database.save_conversion("parcial1.pdf", "Hist", 20.0, "<quiz>p1</quiz>", '{"questions":[],"answer_key":{}}', m1["id"], "Parcial 1")
ok(fila_de(rid)["materia_id"] == m1["id"] and fila_de(rid)["actividad"] == "Parcial 1", "el examen guarda su materia y su actividad")
ok(database.get_editor_data(rid)["materia_id"] == m1["id"], "get_editor_data devuelve la materia")
rid2 = database.save_conversion("fantasma.pdf", "Hist", 5.0, "<quiz>f</quiz>", None, 9999, None)
ok(fila_de(rid2)["materia_id"] is None, "una materia que ya no existe se guarda como «sin materia»")
ok(database.update_history_item(rid2, materia_id=m2["id"]) is True and fila_de(rid2)["materia_id"] == m2["id"], "mover un examen a otra materia")
ok(database.update_history_item(rid2, actividad="Quiz 3") is True and fila_de(rid2)["actividad"] == "Quiz 3" and fila_de(rid2)["materia_id"] == m2["id"], "cambiar solo la actividad no toca la materia")
ok(database.update_history_item(rid2, materia_id=None) is True and fila_de(rid2)["materia_id"] is None, "dejarlo «sin materia»")
ok(database.update_history_item(rid2, materia_id=9999) is False and database.update_history_item(99999, materia_id=None) is None, "materia inexistente: False; examen inexistente: None")
viejos = [x["id"] for x in database.get_history_list() if x["filename"].startswith("viejo")]
ok(database.move_history_items(viejos, m1["id"]) == 3, "mover varios a la vez")
ok(database.move_history_items([viejos[0], 99999], None) == 1 and database.move_history_items(viejos, 9999) is None, "ids que no existen no cuentan; materia inexistente: None")
database.move_history_items(viejos, m1["id"])
mats = {m["nombre"]: m for m in database.list_materias()}
ok(mats["Historia de Panamá"]["examenes"] == 4 and mats["Historia de Panamá"]["bytes"] > 0 and mats["Historia de Panamá"]["ultimo"], "list_materias cuenta exámenes, bytes y último uso")

# ═══════════════ 4. Borrar una materia ═══════════════
print("Borrar una materia")
n_antes = len(database.get_history_list())
ok(database.delete_materia(m1["id"]) == 4, "borrar la materia devuelve cuántos exámenes pasaron a «sin materia»")
ok(len(database.get_history_list()) == n_antes and all(x["materia_id"] is None for x in database.get_history_list()), "ningún examen se borró")
ok(database.delete_materia(m1["id"]) is None, "borrar otra vez: None")
sobran = [database.save_conversion(f"borrar{i}.pdf", "C", 1.0, "<x/>") for i in range(3)]
ok(database.delete_history_items(sobran[:2] + [99999]) == 2 and {x["id"] for x in database.get_history_list()} >= {sobran[2]}
   and not ({sobran[0], sobran[1]} & {x["id"] for x in database.get_history_list()}), "borrar varios a la vez: cuenta solo los que existían")
database.delete_history_items(sobran)

# ═══════════════ 5. Política de borrado ═══════════════
print("Política de borrado: primero los exámenes sin materia")
with contextlib.closing(sqlite3.connect(DB_FILE)) as c2:
    c2.execute("DELETE FROM history")
    c2.commit()
mp = database.create_materia("Protegida")
database.MAX_HISTORIAL = 10
ids_con = [database.save_conversion(f"con{i}.pdf", "C", 1.0, "<x/>", None, mp["id"]) for i in range(4)]
ids_sin = [database.save_conversion(f"sin{i}.pdf", "C", 1.0, "<x/>") for i in range(6)]
ok(len(database.get_history_list()) == 10, "con 10 de 10 todavía no se borra nada")
nuevos = [database.save_conversion(f"nuevo{i}.pdf", "C", 1.0, "<x/>") for i in range(3)]
vivos = {x["id"] for x in database.get_history_list()}
ok(len(vivos) == 10 and all(i in vivos for i in ids_con), "al pasarse del límite, TODOS los de la materia siguen")
ok(not any(i in vivos for i in ids_sin[:3]) and all(i in vivos for i in nuevos), "se fueron los 3 sin materia más antiguos, quedan los nuevos")
# Si solo quedan exámenes con materia, también se poda (el más antiguo primero), nunca el recién guardado.
for i in nuevos + ids_sin[3:]:
    database.delete_history_item(i)
ids_con2 = [database.save_conversion(f"otra{i}.pdf", "C", 1.0, "<x/>", None, mp["id"]) for i in range(8)]
vivos = {x["id"] for x in database.get_history_list()}
ok(len(vivos) == 10 and ids_con2[-1] in vivos and ids_con[0] not in vivos and ids_con[1] not in vivos, "sin nada que no tenga materia, se borran los más antiguos (último recurso)")
database.MAX_HISTORIAL = 300

# Por tamaño: se va primero lo sin materia aunque sea más reciente que lo clasificado.
with contextlib.closing(sqlite3.connect(DB_FILE)) as c2:
    c2.execute("DELETE FROM history")
    c2.commit()
database.MAX_HISTORIAL_BYTES = 30_000
grande = "<x>" + "z" * 9_000 + "</x>"
a = database.save_conversion("a.pdf", "C", 1.0, grande, None, mp["id"])
b = database.save_conversion("b.pdf", "C", 1.0, grande)
c_ = database.save_conversion("c.pdf", "C", 1.0, grande, None, mp["id"])
d = database.save_conversion("d.pdf", "C", 1.0, grande)
vivos = {x["id"] for x in database.get_history_list()}
ok(vivos == {a, c_, d}, "por tamaño: se borró el sin materia más antiguo (b), no el clasificado más antiguo (a)")
e = database.save_conversion("e.pdf", "C", 1.0, grande)
vivos = {x["id"] for x in database.get_history_list()}
ok(vivos == {a, c_, e}, "…y luego el siguiente sin materia (d); el recién guardado siempre queda")
database.MAX_HISTORIAL_BYTES = 400 * 1024 * 1024

# ═══════════════ 6. Uso ═══════════════
print("Uso del Historial")
uso = database.get_uso()
ok(uso["examenes"] == 3 and uso["sin_materia"] == 1 and uso["bytes"] > 27_000 and uso["cerca_del_limite"] is False, "get_uso cuenta exámenes, bytes y los que no tienen materia")
database.MAX_HISTORIAL = 3
uso = database.get_uso()
ok(uso["cerca_del_limite"] is True and uso["porcentaje"] == 100.0, "al 100 % de los exámenes: cerca del límite")
database.MAX_HISTORIAL = 300

# ═══════════════ 7. Rutas ═══════════════
print("Rutas")
cli = TestClient(main.app, base_url="http://127.0.0.1:8000")
H = {"X-Conversor-Token": seguridad.TOKEN}
ok(cli.get("/api/materias").status_code == 401 and cli.post("/api/materias", json={"nombre": "X"}).status_code == 401
   and cli.patch("/api/materias/1", json={}).status_code == 401 and cli.delete("/api/materias/1").status_code == 401, "sin token: 401")
ok(cli.patch("/api/history/1", json={"actividad": "x"}).status_code == 401 and cli.post("/api/history/mover", json={"ids": [1]}).status_code == 401
   and cli.get("/api/history/uso").status_code == 401, "las rutas del Historial nuevas también piden token")
r = cli.post("/api/materias", json={"nombre": "  Física   II  ", "color": "rosa", "docente": " Luis "}, headers=H)
ok(r.status_code == 201 and r.json()["nombre"] == "Física II" and r.json()["docente"] == "Luis", "crear: se limpian los espacios")
fid = r.json()["id"]
ok(cli.post("/api/materias", json={"nombre": "física ii"}, headers=H).status_code == 409, "nombre repetido: 409")
ok(cli.post("/api/materias", json={"nombre": "   "}, headers=H).status_code == 422 and cli.post("/api/materias", json={"nombre": "A" * 500}, headers=H).status_code == 422, "nombre vacío o enorme: 422")
ok(cli.post("/api/materias", json={"nombre": "Ok", "color": "fucsia"}, headers=H).status_code == 422, "color que no existe: 422")
ok(cli.post("/api/materias", json={}, headers=H).status_code == 422, "sin nombre: 422")
r = cli.patch(f"/api/materias/{fid}", json={"color": "azul", "grupo": "3A"}, headers=H)
ok(r.status_code == 200 and r.json()["color"] == "azul" and r.json()["grupo"] == "3A" and r.json()["nombre"] == "Física II", "cambiar solo lo enviado")
ok(cli.patch(f"/api/materias/{fid}", json={"docente": None}, headers=H).json()["docente"] is None, "null vacía el docente")
ok(cli.patch(f"/api/materias/{fid}", json={"archivada": True}, headers=H).json()["archivada"] is True, "archivar por la ruta")
ok(cli.patch(f"/api/materias/{fid}", json={"archivada": None}, headers=H).status_code == 422 and cli.patch(f"/api/materias/{fid}", json={"nombre": ""}, headers=H).status_code == 422, "valores no válidos: 422")
ok(cli.patch("/api/materias/99999", json={"color": "azul"}, headers=H).status_code == 404, "materia inexistente: 404")
ok(any(m["nombre"] == "Física II" for m in cli.get("/api/materias", headers=H).json()), "GET lista las materias")

cuerpo = {"filename": "ejemplo.pdf", "category": "mis-preguntas", "total_points": 10, "materia_id": fid, "actividad": "  Quiz   1 ",
          "questions": [{"num": 1, "type": "multichoice", "points": 10, "data": {"stem": "¿Cuánto es 2+2?", "options": {"a": "3", "b": "4"}}}],
          "answer_key": {"1": {"type": "multichoice", "answer": "b"}}}
r = cli.post("/api/generate_xml", json=cuerpo, headers=H)
st = json.loads(r.headers["X-Question-Stats"])
hid = st["historial_id"]
ok(r.status_code == 200 and isinstance(hid, int) and st["historial_guardado"] is True, "generar el XML devuelve el id del examen guardado")


def hist(i):
    return [x for x in cli.get("/api/history", headers=H).json() if x["id"] == i][0]


ok(hist(hid)["materia_id"] == fid and hist(hid)["actividad"] == "Quiz 1", "queda en su materia, con la actividad limpia")
ok(cli.get(f"/api/history/{hid}/editor", headers=H).json()["materia_id"] == fid, "reabrir devuelve la materia")
r = cli.post("/api/generate_xml", json={k: v for k, v in cuerpo.items() if k not in ("materia_id", "actividad")}, headers=H)
ok(r.status_code == 200 and hist(json.loads(r.headers["X-Question-Stats"])["historial_id"])["materia_id"] is None,
   "sin materia en la petición: queda «sin materia» (los clientes anteriores siguen funcionando)")
ok(cli.post("/api/generate_xml", json={**cuerpo, "materia_id": "abc"}, headers=H).status_code == 422, "materia_id que no es número: 422")

ok(cli.patch(f"/api/history/{hid}", json={"materia_id": None}, headers=H).status_code == 200 and hist(hid)["materia_id"] is None, "PATCH: sacar un examen de su materia")
ok(cli.patch(f"/api/history/{hid}", json={"materia_id": fid, "actividad": "Parcial"}, headers=H).status_code == 200 and hist(hid)["actividad"] == "Parcial", "PATCH: materia y actividad a la vez")
ok(cli.patch(f"/api/history/{hid}", json={}, headers=H).status_code == 422, "PATCH sin nada que cambiar: 422")
ok(cli.patch("/api/history/99999", json={"actividad": "x"}, headers=H).status_code == 404 and cli.patch(f"/api/history/{hid}", json={"materia_id": 99999}, headers=H).status_code == 404, "PATCH: examen o materia inexistente: 404")
r = cli.post("/api/history/mover", json={"ids": [hid, hid], "materia_id": None}, headers=H)
ok(r.status_code == 200 and r.json()["movidos"] == 1, "mover: los ids repetidos cuentan una vez")
ok(cli.post("/api/history/mover", json={"ids": [], "materia_id": None}, headers=H).status_code == 422 and cli.post("/api/history/mover", json={"ids": [hid], "materia_id": 99999}, headers=H).status_code == 404, "mover sin ids: 422; a una materia inexistente: 404")
ok(cli.post("/api/history/borrar", json={"ids": []}, headers=H).status_code == 422 and cli.post("/api/history/borrar", json={"ids": [1]}).status_code == 401, "borrar varios: sin ids 422, sin token 401")
tmp_ids = [json.loads(cli.post("/api/generate_xml", json=cuerpo, headers=H).headers["X-Question-Stats"])["historial_id"] for _ in range(2)]
r = cli.post("/api/history/borrar", json={"ids": tmp_ids + tmp_ids + [99999]}, headers=H)
ok(r.status_code == 200 and r.json()["borrados"] == 2 and not any(x["id"] in tmp_ids for x in cli.get("/api/history", headers=H).json()), "borrar varios por la ruta (repetidos e inexistentes no cuentan)")
u = cli.get("/api/history/uso", headers=H).json()
ok({"examenes", "bytes", "maximo_examenes", "maximo_bytes", "sin_materia", "porcentaje", "cerca_del_limite"} <= set(u), "uso: trae todo lo que muestra la interfaz")
r = cli.delete(f"/api/materias/{fid}", headers=H)
ok(r.status_code == 200 and "examenes_sin_materia" in r.json() and cli.delete(f"/api/materias/{fid}", headers=H).status_code == 404, "borrar la materia por la ruta (y 404 si ya no está)")

# ═══════════════ 8. Mi perfil (datos del docente y perfiles de encabezado) ═══════════════
print("Mi perfil")
ok(cli.get("/api/yo").status_code == 401 and cli.put("/api/yo", json={}).status_code == 401 and cli.post("/api/perfiles_pdf/x/renombrar", json={"nuevo": "y"}).status_code == 401, "sin token: 401")
ok(cli.get("/api/yo", headers=H).json() == {"nombre": "", "rotulo_docente": "facilitador", "perfil_predeterminado": None}, "al principio: sin nombre, «facilitador», sin perfil predeterminado")
r = cli.put("/api/yo", json={"nombre": "  Ana   Pérez  ", "rotulo_docente": "profesor"}, headers=H)
ok(r.status_code == 200 and r.json()["nombre"] == "Ana Pérez" and r.json()["rotulo_docente"] == "profesor", "guardar el nombre (limpio) y el rótulo")
ok(cli.get("/api/yo", headers=H).json()["nombre"] == "Ana Pérez", "se conserva")
ok(cli.put("/api/yo", json={"rotulo_docente": "jefe"}, headers=H).status_code == 422, "rótulo que no existe: 422")
ok(cli.put("/api/yo", json={"nombre": "A" * 400}, headers=H).status_code == 422, "nombre enorme: 422")
ok(cli.put("/api/yo", json={"perfil_predeterminado": "No existe"}, headers=H).status_code == 404, "perfil predeterminado que no existe: 404")
ok(cli.put("/api/yo", json={"rotulo_docente": "docente"}, headers=H).json()["nombre"] == "Ana Pérez", "cambiar solo el rótulo no toca el nombre")

pf = {"institucion": "UTP", "facultad": "Sistemas"}
cli.put("/api/perfiles_pdf/UTP", json=pf, headers=H)
cli.put("/api/perfiles_pdf/Colegio", json={"institucion": "Colegio X"}, headers=H)
mu = cli.post("/api/materias", json={"nombre": "Usa UTP", "perfil": "UTP"}, headers=H).json()
ok(cli.put("/api/yo", json={"perfil_predeterminado": "UTP"}, headers=H).json()["perfil_predeterminado"] == "UTP", "elegir el perfil predeterminado")
ok(cli.post("/api/perfiles_pdf/UTP/renombrar", json={"nuevo": "Colegio"}, headers=H).status_code == 409, "renombrar a un nombre que ya existe: 409")
ok(cli.post("/api/perfiles_pdf/Nada/renombrar", json={"nuevo": "Otro"}, headers=H).status_code == 404 and cli.post("/api/perfiles_pdf/UTP/renombrar", json={"nuevo": "  "}, headers=H).status_code == 422, "perfil inexistente: 404; nombre vacío: 422")
r = cli.post("/api/perfiles_pdf/UTP/renombrar", json={"nuevo": "UTP Panamá"}, headers=H)
nombres = [x["nombre"] for x in cli.get("/api/perfiles_pdf", headers=H).json()]
ok(r.status_code == 200 and "UTP Panamá" in nombres and "UTP" not in nombres, "renombrar el perfil")
ok(cli.get("/api/yo", headers=H).json()["perfil_predeterminado"] == "UTP Panamá", "…el predeterminado lo sigue")
ok([m["perfil"] for m in cli.get("/api/materias", headers=H).json() if m["id"] == mu["id"]] == ["UTP Panamá"], "…y las materias que lo usaban también")
ok([x for x in cli.get("/api/perfiles_pdf", headers=H).json() if x["nombre"] == "UTP Panamá"][0]["datos"]["institucion"] == "UTP", "…con sus datos intactos")
ok(cli.delete("/api/perfiles_pdf/UTP%20Panam%C3%A1", headers=H).status_code == 200, "borrar el perfil")
ok(cli.get("/api/yo", headers=H).json()["perfil_predeterminado"] is None, "…ya no hay predeterminado")
ok([m["perfil"] for m in cli.get("/api/materias", headers=H).json() if m["id"] == mu["id"]] == [None], "…ni materias que lo usen")
ok(cli.put("/api/yo", json={"perfil_predeterminado": "Colegio"}, headers=H).status_code == 200 and cli.put("/api/yo", json={"perfil_predeterminado": None}, headers=H).json()["perfil_predeterminado"] is None, "quitar el predeterminado con null")

print()
print("TODO OK" if not fallas else f"{fallas} FALLA(S)")
sys.exit(1 if fallas else 0)
