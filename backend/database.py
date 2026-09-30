import contextlib
import os
import shutil
import sqlite3
import sys
import logging
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
        conn.commit()


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


def _podar(conn: sqlite3.Connection) -> None:
    """Conserva solo las MAX_HISTORIAL filas más recientes y, si el total pasa
    de MAX_HISTORIAL_BYTES, recorta más las antiguas (la más nueva siempre queda)."""
    conn.execute(
        'DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT ?)',
        (MAX_HISTORIAL,),
    )
    # length(CAST(.. AS BLOB)) sale del encabezado del registro: no lee las imágenes.
    filas = conn.execute(
        'SELECT id, length(CAST(xml_content AS BLOB)) + coalesce(length(CAST(editor_json AS BLOB)), 0) '
        'FROM history ORDER BY id DESC'
    ).fetchall()
    acumulado = 0
    corte = None
    for i, (fila_id, tam) in enumerate(filas):
        acumulado += tam or 0
        if acumulado > MAX_HISTORIAL_BYTES and i > 0:
            corte = fila_id  # esta y las anteriores (ids menores o iguales) se borran
            break
    if corte is not None:
        conn.execute('DELETE FROM history WHERE id <= ?', (corte,))
    conn.commit()
    # Con auto_vacuum incremental (bases nuevas) se devuelve el espacio; en
    # bases anteriores es un no-op. No se hace VACUUM completo: bloquearía la app.
    if conn.execute('PRAGMA auto_vacuum').fetchone()[0] == 2:
        conn.execute('PRAGMA incremental_vacuum(200)').fetchall()


def save_conversion(filename: str, category: str, total_points: float, xml_content: str,
                    editor_json: Optional[str] = None) -> int:
    """Guarda una conversión y devuelve su id. Si falta la tabla la crea y
    reintenta una vez; cualquier otro error se propaga (main.py lo captura).
    Un fallo al podar el historial no invalida el guardado."""
    def _guardar() -> int:
        with _connection() as conn:
            cursor = conn.execute('''
                INSERT INTO history (filename, category, total_points, xml_content, editor_json)
                VALUES (?, ?, ?, ?, ?)
            ''', (filename, category, total_points, xml_content, editor_json))
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
            cursor = conn.execute('''
                SELECT id, filename, category, total_points, created_at,
                       editor_json IS NOT NULL AS has_editor
                FROM history
                ORDER BY id DESC
                LIMIT ?
            ''', (MAX_HISTORIAL,))
            return [{**dict(row), 'has_editor': bool(row['has_editor'])} for row in cursor.fetchall()]
    return _con_reintento_tabla(_listar)


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
                'SELECT filename, category, total_points, editor_json FROM history WHERE id = ?',
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
