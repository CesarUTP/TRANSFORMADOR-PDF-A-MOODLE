import contextlib
import os
import shutil
import sqlite3
import sys
import logging
import unicodedata
from pathlib import Path
from datetime import datetime
from typing import Callable, Iterator, List, Dict, Any, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Cuántas conversiones guarda el historial (las más recientes). Cada fila lleva
# el XML y el JSON del editor, ambos con las imágenes en base64, así que sin
# tope la base crecía sin límite. Es el único sitio donde se define: la lista
# del Historial y la poda al guardar usan este mismo número.
MAX_HISTORIAL = 300
# Tope de tamaño total (bytes de xml_content + editor_json). Si se pasa, se
# borran también las más antiguas, sin tocar nunca la que se acaba de guardar.
MAX_HISTORIAL_BYTES = 400 * 1024 * 1024
# Cuántas materias se pueden crear y los colores de su tarjeta (la interfaz los
# traduce a los colores del tema).
MAX_MATERIAS = 60
COLORES_MATERIA = ("azul", "verde", "ambar", "violeta", "rosa", "turquesa", "naranja", "gris")
LIMITE_NOMBRE_MATERIA = 80
LIMITE_CAMPO_MATERIA = 160
# A partir de qué parte del límite se avisa al docente de que el Historial se está llenando.
UMBRAL_AVISO = 0.85
# Por encima de este tamaño no se hace la comprobación de integridad al
# arrancar (sería lenta); el resto de la detección de daño sigue funcionando.
_MAX_BYTES_COMPROBAR = 64 * 1024 * 1024


def _app_data_dir() -> Path:
    """
    Carpeta de datos de la app para el ejecutable empaquetado.

    La carpeta del propio ejecutable (ej. "C:\\Program Files\\..." en
    Windows tras instalarlo con el instalador) NO es escribible por un
    usuario sin privilegios de administrador — intentar crear ahí la base
    de datos lanza PermissionError, el backend nunca termina de arrancar,
    y el usuario solo ve una pantalla de "no se pudo iniciar el servidor".
    Se usa en su lugar la carpeta de datos de aplicación estándar de cada
    sistema operativo, que siempre es escribible por el usuario actual.
    """
    app_name = "ConversorMoodleXML"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / app_name


def get_db_path() -> Path:
    if getattr(sys, "frozen", False):
        base_dir = _app_data_dir()
    else:
        base_dir = Path(__file__).parent.parent
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "exams_history.db"

@contextlib.contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    """
    Conexión SQLite que SIEMPRE se cierra, incluso si execute()/commit()
    lanza una excepción — antes cada función de este módulo hacía
    sqlite3.connect() y conn.close() al final "en línea recta", sin
    try/finally: una escritura concurrente que choca con "database is
    locked" (u otro error a mitad de camino) dejaba la conexión abierta,
    sin liberar, en un proceso de larga vida como el ejecutable de
    escritorio.
    """
    conn = sqlite3.connect(get_db_path())
    try:
        yield conn
    finally:
        conn.close()


_ESQUEMA = '''
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        category TEXT NOT NULL,
        total_points REAL NOT NULL,
        xml_content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
'''


_ESQUEMA_PERFILES = '''
    CREATE TABLE IF NOT EXISTS perfiles_pdf (
        nombre TEXT PRIMARY KEY,
        datos TEXT NOT NULL,
        actualizado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
'''

_ESQUEMA_MATERIAS = '''
    CREATE TABLE IF NOT EXISTS materias (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        clave TEXT NOT NULL UNIQUE,
        color TEXT NOT NULL DEFAULT 'azul',
        perfil TEXT,
        docente TEXT,
        grupo TEXT,
        archivada INTEGER NOT NULL DEFAULT 0,
        creada TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
'''

# Los datos del docente (Mi perfil): clave → valor, para el nombre que sale en los encabezados y el perfil predeterminado.
_ESQUEMA_AJUSTES = '''
    CREATE TABLE IF NOT EXISTS ajustes (
        clave TEXT PRIMARY KEY,
        valor TEXT NOT NULL
    )
'''
AJUSTES_PREDETERMINADOS: Dict[str, Any] = {"nombre": "", "rotulo_docente": "facilitador", "perfil_predeterminado": None}

# Cuántos perfiles de encabezado se pueden guardar (cada uno puede llevar dos logos pequeños).
MAX_PERFILES = 30


def _es_tabla_ausente(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and "no such table" in str(exc).lower()


def _es_base_danada(exc: BaseException) -> bool:
    """Base corrupta o que no es una base SQLite (no: bloqueada, disco lleno,
    sin permisos ni tabla ausente, que renombrar no arregla)."""
    if not isinstance(exc, sqlite3.DatabaseError):
        return False
    if isinstance(exc, sqlite3.OperationalError):
        msg = str(exc).lower()
        return "malformed" in msg or "not a database" in msg or "corrupt" in msg
    return True  # DatabaseError "file is not a database", "disk image is malformed"


def _crear_o_migrar() -> None:
    """Crea la tabla, migra columnas y comprueba (barato) que la base no esté dañada."""
    ruta = get_db_path()
    with _connection() as conn:
        # Lectura mínima: falla con DatabaseError si el archivo no es SQLite.
        tablas = conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        if tablas == 0:
            # Solo se puede fijar antes de crear la primera tabla: así el
            # espacio de filas borradas por la poda se puede devolver.
            conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
        elif ruta.exists() and ruta.stat().st_size <= _MAX_BYTES_COMPROBAR:
            estado = conn.execute("PRAGMA quick_check(1)").fetchone()
            if estado and str(estado[0]).lower() != "ok":
                raise sqlite3.DatabaseError("database disk image is malformed (quick_check)")
        conn.execute(_ESQUEMA)
        # Migración: las preguntas tal como quedaron en el editor (JSON),
        # para poder "Reabrir" una conversión y corregirla. Las entradas
        # anteriores a esta columna quedan en NULL y solo se descargan.
        cols = {row[1] for row in conn.execute('PRAGMA table_info(history)')}
        if 'editor_json' not in cols:
            conn.execute('ALTER TABLE history ADD COLUMN editor_json TEXT')
        # Mis materias (2.3): a qué materia pertenece cada examen (NULL = «Sin materia») y
        # cómo se llama la actividad (Parcial 1, Quiz 2…). Antes de tocar una base que ya
        # tiene exámenes se guarda una copia: es la primera vez que se cambia su forma.
        if 'materia_id' not in cols or 'actividad' not in cols:
            if conn.execute('SELECT 1 FROM history LIMIT 1').fetchone():
                _respaldar_antes_de_migrar(conn, ruta)
            if 'materia_id' not in cols:
                conn.execute('ALTER TABLE history ADD COLUMN materia_id INTEGER')
            if 'actividad' not in cols:
                conn.execute('ALTER TABLE history ADD COLUMN actividad TEXT')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_history_materia ON history(materia_id)')
        conn.execute(_ESQUEMA_MATERIAS)
        # Perfiles de encabezado del PDF del examen (institución, logos, formato…), con nombre.
        conn.execute(_ESQUEMA_PERFILES)
        conn.execute(_ESQUEMA_AJUSTES)
        conn.commit()


def _respaldar_antes_de_migrar(conn: sqlite3.Connection, ruta: Path) -> None:
    """Copia la base a «<nombre>.antes-de-materias.bak» (una sola vez: si ya existe no se pisa).
    Un fallo al copiar (disco lleno…) no impide migrar: añadir columnas no borra nada."""
    destino = ruta.with_name(ruta.name + ".antes-de-materias.bak")
    if destino.exists():
        return
    try:
        copia = sqlite3.connect(destino)
        try:
            conn.backup(copia)
        finally:
            copia.close()
        logger.info("Copia de la base antes de crear «Mis materias»: %s", destino)
    except (sqlite3.Error, OSError):
        logger.exception("No se pudo guardar la copia previa a la migración (se migra igual)")
        destino.unlink(missing_ok=True)


def _apartar_base_danada() -> Optional[Path]:
    """Renombra la base dañada (y sus archivos auxiliares) a .bak con marca de
    tiempo, sin pisar copias anteriores. Devuelve la ruta del .bak."""
    ruta = get_db_path()
    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = ruta.with_name(f"{ruta.name}.{marca}.bak")
    n = 1
    while destino.exists():
        destino = ruta.with_name(f"{ruta.name}.{marca}-{n}.bak")
        n += 1
    shutil.move(str(ruta), str(destino))
    for sufijo in ("-journal", "-wal", "-shm"):
        aux = ruta.with_name(ruta.name + sufijo)
        if aux.exists():
            try:
                shutil.move(str(aux), str(destino.with_name(destino.name + sufijo)))
            except OSError:
                aux.unlink(missing_ok=True)
    return destino


def init_db() -> bool:
    """
    Deja lista la base del historial. NUNCA lanza: devuelve True si quedó
    operativa y False si no (sin permisos, disco lleno, carpeta inaccesible…).
    La app arranca igual; el historial fallará después con un error que
    main.py ya captura por operación.

    Base dañada: se aparta como «.bak» con marca de tiempo (el docente puede
    recuperarla) y se crea una nueva vacía.
    """
    try:
        _crear_o_migrar()
        logger.info("Database initialized at %s", get_db_path())
        return True
    except Exception as exc:  # noqa: BLE001 — la app no puede morir por el historial
        if not _es_base_danada(exc):
            logger.exception("No se pudo preparar la base del historial (se sigue sin ella)")
            return False
        logger.exception("La base del historial está dañada; se aparta y se crea una nueva")
    try:
        bak = _apartar_base_danada()
        logger.error("Base dañada guardada como %s", bak)
        _crear_o_migrar()
        logger.info("Database recreated at %s", get_db_path())
        return True
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo recrear la base del historial (se sigue sin ella)")
        return False


def _con_reintento_tabla(operacion: Callable[[], T]) -> T:
    """Ejecuta `operacion`; si falla porque falta la tabla (base borrada o
    recreada mientras la app corría), la crea y reintenta UNA vez. Cualquier
    otro error se propaga."""
    try:
        return operacion()
    except sqlite3.OperationalError as exc:
        if not _es_tabla_ausente(exc):
            raise
        logger.warning("Falta la tabla del historial; se crea y se reintenta")
        init_db()
        return operacion()


_TAM_FILA = 'length(CAST(xml_content AS BLOB)) + coalesce(length(CAST(editor_json AS BLOB)), 0)'
_TAM_FILA_H = _TAM_FILA.replace('xml_content', 'h.xml_content').replace('editor_json', 'h.editor_json')


def _podar(conn: sqlite3.Connection) -> None:
    """Mantiene el Historial dentro de MAX_HISTORIAL filas y MAX_HISTORIAL_BYTES. Cuando hay que
    borrar, se van primero los exámenes SIN materia (los más antiguos antes) y solo si no alcanza
    se tocan los que sí la tienen; el más reciente (el que se acaba de guardar) nunca se borra."""
    # length(CAST(.. AS BLOB)) sale del encabezado del registro: no lee las imágenes.
    filas = conn.execute(
        f'SELECT id, {_TAM_FILA}, materia_id IS NOT NULL FROM history ORDER BY id ASC'
    ).fetchall()
    if not filas:
        return
    cuantas = len(filas)
    total = sum(f[1] or 0 for f in filas)
    if cuantas <= MAX_HISTORIAL and total <= MAX_HISTORIAL_BYTES:
        return
    protegido = filas[-1][0]
    orden = [f for f in filas if f[0] != protegido and not f[2]] + [f for f in filas if f[0] != protegido and f[2]]
    borrar = []
    for fila_id, tam, _con_materia in orden:
        if cuantas <= MAX_HISTORIAL and total <= MAX_HISTORIAL_BYTES:
            break
        borrar.append(fila_id)
        cuantas -= 1
        total -= tam or 0
    for i in range(0, len(borrar), 500):
        trozo = borrar[i:i + 500]
        conn.execute(f'DELETE FROM history WHERE id IN ({",".join("?" * len(trozo))})', trozo)
    conn.commit()
    # Con auto_vacuum incremental (bases nuevas) se devuelve el espacio; en
    # bases anteriores es un no-op. No se hace VACUUM completo: bloquearía la app.
    if conn.execute('PRAGMA auto_vacuum').fetchone()[0] == 2:
        conn.execute('PRAGMA incremental_vacuum(200)').fetchall()


def save_conversion(filename: str, category: str, total_points: float, xml_content: str,
                    editor_json: Optional[str] = None, materia_id: Optional[int] = None,
                    actividad: Optional[str] = None) -> int:
    """Guarda una conversión y devuelve su id. Si falta la tabla la crea y
    reintenta una vez; cualquier otro error se propaga (main.py lo captura).
    Un fallo al podar el historial no invalida el guardado. Una materia que no
    existe (borrada mientras tanto) se guarda como «sin materia»."""
    def _guardar() -> int:
        with _connection() as conn:
            if materia_id is not None and not conn.execute('SELECT 1 FROM materias WHERE id = ?', (materia_id,)).fetchone():
                logger.warning("La materia %s ya no existe: el examen se guarda sin materia", materia_id)
                mid = None
            else:
                mid = materia_id
            cursor = conn.execute('''
                INSERT INTO history (filename, category, total_points, xml_content, editor_json, materia_id, actividad)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (filename, category, total_points, xml_content, editor_json, mid, (actividad or None)))
            record_id = cursor.lastrowid
            conn.commit()
            try:
                _podar(conn)
            except Exception:  # noqa: BLE001 — ya está guardado; la poda se reintenta en el próximo
                logger.exception("No se pudo podar el historial")
            return record_id
    return _con_reintento_tabla(_guardar)


def get_history_list() -> List[Dict[str, Any]]:
    def _listar() -> List[Dict[str, Any]]:
        with _connection() as conn:
            conn.row_factory = sqlite3.Row
            # Todo menos xml_content (pesado). El buscador del Historial
            # filtra en el navegador sobre esta lista.
            cursor = conn.execute(f'''
                SELECT id, filename, category, total_points, created_at, materia_id, actividad,
                       editor_json IS NOT NULL AS has_editor, {_TAM_FILA} AS bytes
                FROM history
                ORDER BY id DESC
                LIMIT ?
            ''', (MAX_HISTORIAL,))
            return [{**dict(row), 'has_editor': bool(row['has_editor']), 'bytes': row['bytes'] or 0} for row in cursor.fetchall()]
    return _con_reintento_tabla(_listar)


def get_uso() -> Dict[str, Any]:
    """Cuánto del Historial está usado y cuánto de eso no tiene materia (lo primero que se borra al llenarse)."""
    def _medir() -> Dict[str, Any]:
        with _connection() as conn:
            n, b, sn, sb = conn.execute(
                f'SELECT count(*), coalesce(sum({_TAM_FILA}), 0), '
                f'coalesce(sum(materia_id IS NULL), 0), coalesce(sum(CASE WHEN materia_id IS NULL THEN {_TAM_FILA} ELSE 0 END), 0) '
                'FROM history'
            ).fetchone()
        return {
            "examenes": n, "bytes": b, "maximo_examenes": MAX_HISTORIAL, "maximo_bytes": MAX_HISTORIAL_BYTES,
            "sin_materia": sn, "sin_materia_bytes": sb,
            "porcentaje": round(max(n / MAX_HISTORIAL, b / MAX_HISTORIAL_BYTES) * 100, 1),
            "cerca_del_limite": max(n / MAX_HISTORIAL, b / MAX_HISTORIAL_BYTES) >= UMBRAL_AVISO,
        }
    return _con_reintento_tabla(_medir)


def get_xml_content(record_id: int) -> Optional[Dict[str, Any]]:
    def _leer() -> Optional[Dict[str, Any]]:
        with _connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute('SELECT filename, xml_content FROM history WHERE id = ?', (record_id,)).fetchone()
            return dict(row) if row else None
    return _con_reintento_tabla(_leer)


def get_editor_data(record_id: int) -> Optional[Dict[str, Any]]:
    def _leer() -> Optional[Dict[str, Any]]:
        with _connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                'SELECT filename, category, total_points, editor_json, materia_id, actividad FROM history WHERE id = ?',
                (record_id,),
            ).fetchone()
            return dict(row) if row else None
    return _con_reintento_tabla(_leer)


def delete_history_item(record_id: int) -> bool:
    def _borrar() -> bool:
        with _connection() as conn:
            cursor = conn.execute('DELETE FROM history WHERE id = ?', (record_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
    return _con_reintento_tabla(_borrar)


# ── Mis materias ────────────────────────────────────────────────────────────

def _clave_nombre(nombre: str) -> str:
    """El nombre sin mayúsculas ni tildes: «Cálculo», «CALCULO» y «calculo» son la misma materia
    (el COLLATE NOCASE de SQLite solo ignora las mayúsculas ASCII, no las de «Á» o «Ñ»)."""
    sin_marcas = "".join(c for c in unicodedata.normalize("NFD", nombre) if not unicodedata.combining(c))
    return " ".join(sin_marcas.casefold().split())


class MateriaDuplicada(Exception):
    """Ya hay una materia con ese nombre (sin distinguir mayúsculas)."""


class LimiteDeMaterias(Exception):
    """Ya hay MAX_MATERIAS materias."""


_COLUMNAS_MATERIA = "id, nombre, color, perfil, docente, grupo, archivada, creada"


def _materia_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {**dict(row), "archivada": bool(row["archivada"])}


def list_materias() -> List[Dict[str, Any]]:
    """Las materias con cuántos exámenes tienen, cuánto pesan y cuándo se usó la última vez."""
    def _listar() -> List[Dict[str, Any]]:
        with _connection() as conn:
            conn.row_factory = sqlite3.Row
            filas = conn.execute(f'''
                SELECT m.id, m.nombre, m.color, m.perfil, m.docente, m.grupo, m.archivada, m.creada,
                       count(h.id) AS examenes,
                       coalesce(sum({_TAM_FILA_H}), 0) AS bytes,
                       max(h.created_at) AS ultimo
                FROM materias m LEFT JOIN history h ON h.materia_id = m.id
                GROUP BY m.id
                ORDER BY m.clave
            ''').fetchall()
            return [{**_materia_dict(f), "examenes": f["examenes"], "bytes": f["bytes"], "ultimo": f["ultimo"]} for f in filas]
    return _con_reintento_tabla(_listar)


def get_materia(materia_id: int) -> Optional[Dict[str, Any]]:
    def _leer() -> Optional[Dict[str, Any]]:
        with _connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(f'SELECT {_COLUMNAS_MATERIA} FROM materias WHERE id = ?', (materia_id,)).fetchone()
            return _materia_dict(row) if row else None
    return _con_reintento_tabla(_leer)


def create_materia(nombre: str, color: str = "azul", perfil: Optional[str] = None,
                   docente: Optional[str] = None, grupo: Optional[str] = None) -> Dict[str, Any]:
    def _crear() -> Dict[str, Any]:
        with _connection() as conn:
            conn.row_factory = sqlite3.Row
            if conn.execute('SELECT count(*) FROM materias').fetchone()[0] >= MAX_MATERIAS:
                raise LimiteDeMaterias()
            try:
                cur = conn.execute(
                    'INSERT INTO materias (nombre, clave, color, perfil, docente, grupo) VALUES (?, ?, ?, ?, ?, ?)',
                    (nombre, _clave_nombre(nombre), color, perfil or None, docente or None, grupo or None),
                )
            except sqlite3.IntegrityError:
                raise MateriaDuplicada()
            conn.commit()
            return _materia_dict(conn.execute(f'SELECT {_COLUMNAS_MATERIA} FROM materias WHERE id = ?', (cur.lastrowid,)).fetchone())
    return _con_reintento_tabla(_crear)


_EDITABLES_MATERIA = ("nombre", "color", "perfil", "docente", "grupo", "archivada")


def update_materia(materia_id: int, cambios: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Cambia solo los campos de `cambios` (un valor None vacía perfil, docente y grupo). None si no existe."""
    campos = {k: v for k, v in cambios.items() if k in _EDITABLES_MATERIA}
    if "nombre" in campos:
        campos["clave"] = _clave_nombre(campos["nombre"])

    def _cambiar() -> Optional[Dict[str, Any]]:
        with _connection() as conn:
            conn.row_factory = sqlite3.Row
            if not conn.execute('SELECT 1 FROM materias WHERE id = ?', (materia_id,)).fetchone():
                return None
            if campos:
                sets = ", ".join(f"{k} = ?" for k in campos)
                vals = [int(v) if k == "archivada" else v for k, v in campos.items()]
                try:
                    conn.execute(f'UPDATE materias SET {sets} WHERE id = ?', (*vals, materia_id))
                except sqlite3.IntegrityError:
                    raise MateriaDuplicada()
                conn.commit()
            return _materia_dict(conn.execute(f'SELECT {_COLUMNAS_MATERIA} FROM materias WHERE id = ?', (materia_id,)).fetchone())
    return _con_reintento_tabla(_cambiar)


def delete_materia(materia_id: int) -> Optional[int]:
    """Borra la materia; sus exámenes NO se borran: pasan a «sin materia». Devuelve cuántos pasaron, o None si no existía."""
    def _borrar() -> Optional[int]:
        with _connection() as conn:
            if not conn.execute('SELECT 1 FROM materias WHERE id = ?', (materia_id,)).fetchone():
                return None
            movidos = conn.execute('UPDATE history SET materia_id = NULL WHERE materia_id = ?', (materia_id,)).rowcount
            conn.execute('DELETE FROM materias WHERE id = ?', (materia_id,))
            conn.commit()
            return movidos
    return _con_reintento_tabla(_borrar)


_SIN_CAMBIO = object()


def update_history_item(record_id: int, materia_id: Any = _SIN_CAMBIO, actividad: Any = _SIN_CAMBIO) -> Optional[bool]:
    """Cambia la materia y/o la actividad de un examen. None si el examen no existe; False si la materia no existe."""
    def _cambiar() -> Optional[bool]:
        with _connection() as conn:
            if not conn.execute('SELECT 1 FROM history WHERE id = ?', (record_id,)).fetchone():
                return None
            if materia_id is not _SIN_CAMBIO and materia_id is not None \
                    and not conn.execute('SELECT 1 FROM materias WHERE id = ?', (materia_id,)).fetchone():
                return False
            if materia_id is not _SIN_CAMBIO:
                conn.execute('UPDATE history SET materia_id = ? WHERE id = ?', (materia_id, record_id))
            if actividad is not _SIN_CAMBIO:
                conn.execute('UPDATE history SET actividad = ? WHERE id = ?', (actividad or None, record_id))
            conn.commit()
            return True
    return _con_reintento_tabla(_cambiar)


def delete_history_items(ids: List[int]) -> int:
    """Borra varios exámenes a la vez. Devuelve cuántos existían y se borraron."""
    def _borrar() -> int:
        with _connection() as conn:
            total = 0
            for i in range(0, len(ids), 500):
                trozo = ids[i:i + 500]
                total += conn.execute(f'DELETE FROM history WHERE id IN ({",".join("?" * len(trozo))})', trozo).rowcount
            conn.commit()
            if conn.execute('PRAGMA auto_vacuum').fetchone()[0] == 2:
                conn.execute('PRAGMA incremental_vacuum(200)').fetchall()
            return total
    return _con_reintento_tabla(_borrar)


def move_history_items(ids: List[int], materia_id: Optional[int]) -> Optional[int]:
    """Pasa varios exámenes a una materia (None = sin materia). Devuelve cuántos se movieron; None si la materia no existe."""
    def _mover() -> Optional[int]:
        with _connection() as conn:
            if materia_id is not None and not conn.execute('SELECT 1 FROM materias WHERE id = ?', (materia_id,)).fetchone():
                return None
            total = 0
            for i in range(0, len(ids), 500):
                trozo = ids[i:i + 500]
                total += conn.execute(
                    f'UPDATE history SET materia_id = ? WHERE id IN ({",".join("?" * len(trozo))})', (materia_id, *trozo),
                ).rowcount
            conn.commit()
            return total
    return _con_reintento_tabla(_mover)


# ── Perfiles de encabezado del PDF ──────────────────────────────────────────

def list_perfiles() -> List[Dict[str, Any]]:
    def _listar() -> List[Dict[str, Any]]:
        with _connection() as conn:
            filas = conn.execute('SELECT nombre, datos, actualizado FROM perfiles_pdf ORDER BY nombre COLLATE NOCASE').fetchall()
            return [{"nombre": n, "datos": d, "actualizado": a} for n, d, a in filas]
    return _con_reintento_tabla(_listar)


def save_perfil(nombre: str, datos_json: str) -> bool:
    """Crea o reemplaza el perfil `nombre`. False si es nuevo y ya hay MAX_PERFILES."""
    def _guardar() -> bool:
        with _connection() as conn:
            existe = conn.execute('SELECT 1 FROM perfiles_pdf WHERE nombre = ?', (nombre,)).fetchone()
            if not existe and conn.execute('SELECT count(*) FROM perfiles_pdf').fetchone()[0] >= MAX_PERFILES:
                return False
            conn.execute('''
                INSERT INTO perfiles_pdf (nombre, datos, actualizado) VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(nombre) DO UPDATE SET datos = excluded.datos, actualizado = CURRENT_TIMESTAMP
            ''', (nombre, datos_json))
            conn.commit()
            return True
    return _con_reintento_tabla(_guardar)


def delete_perfil(nombre: str) -> bool:
    """Borra el perfil y quita lo que apuntaba a él (el predeterminado y las materias que lo usaban)."""
    def _borrar() -> bool:
        with _connection() as conn:
            cursor = conn.execute('DELETE FROM perfiles_pdf WHERE nombre = ?', (nombre,))
            if cursor.rowcount > 0:
                conn.execute("DELETE FROM ajustes WHERE clave = 'perfil_predeterminado' AND valor = ?", (nombre,))
                conn.execute('UPDATE materias SET perfil = NULL WHERE perfil = ?', (nombre,))
            conn.commit()
            return cursor.rowcount > 0
    return _con_reintento_tabla(_borrar)


def rename_perfil(viejo: str, nuevo: str) -> str:
    """Cambia el nombre de un perfil y de todo lo que apuntaba a él. 'ok', 'no_existe' o 'ya_existe'."""
    def _renombrar() -> str:
        with _connection() as conn:
            if not conn.execute('SELECT 1 FROM perfiles_pdf WHERE nombre = ?', (viejo,)).fetchone():
                return 'no_existe'
            if viejo != nuevo and conn.execute('SELECT 1 FROM perfiles_pdf WHERE nombre = ?', (nuevo,)).fetchone():
                return 'ya_existe'
            conn.execute('UPDATE perfiles_pdf SET nombre = ? WHERE nombre = ?', (nuevo, viejo))
            conn.execute("UPDATE ajustes SET valor = ? WHERE clave = 'perfil_predeterminado' AND valor = ?", (nuevo, viejo))
            conn.execute('UPDATE materias SET perfil = ? WHERE perfil = ?', (nuevo, viejo))
            conn.commit()
            return 'ok'
    return _con_reintento_tabla(_renombrar)


# ── Mi perfil: los datos del docente ────────────────────────────────────────

def get_ajustes() -> Dict[str, Any]:
    def _leer() -> Dict[str, Any]:
        with _connection() as conn:
            guardado = dict(conn.execute('SELECT clave, valor FROM ajustes').fetchall())
        return {k: guardado.get(k, v) for k, v in AJUSTES_PREDETERMINADOS.items()}
    return _con_reintento_tabla(_leer)


def set_ajustes(cambios: Dict[str, Any]) -> None:
    """Guarda solo las claves conocidas de `cambios` (un valor None o vacío en el perfil predeterminado lo quita)."""
    def _guardar() -> None:
        with _connection() as conn:
            for clave, valor in cambios.items():
                if clave not in AJUSTES_PREDETERMINADOS:
                    continue
                if valor is None or (clave == 'perfil_predeterminado' and valor == ''):
                    conn.execute('DELETE FROM ajustes WHERE clave = ?', (clave,))
                else:
                    conn.execute('INSERT INTO ajustes (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor', (clave, str(valor)))
            conn.commit()
    _con_reintento_tabla(_guardar)
