import contextlib
import os
import sqlite3
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Iterator, List, Dict, Any, Optional

logger = logging.getLogger(__name__)


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


def init_db():
    with _connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                category TEXT NOT NULL,
                total_points REAL NOT NULL,
                xml_content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Migración: las preguntas tal como quedaron en el editor (JSON),
        # para poder "Reabrir" una conversión y corregirla. Las entradas
        # anteriores a esta columna quedan en NULL y solo se descargan.
        cols = {row[1] for row in conn.execute('PRAGMA table_info(history)')}
        if 'editor_json' not in cols:
            conn.execute('ALTER TABLE history ADD COLUMN editor_json TEXT')
        conn.commit()
    logger.info("Database initialized at %s", get_db_path())

def save_conversion(filename: str, category: str, total_points: float, xml_content: str,
                    editor_json: Optional[str] = None) -> int:
    with _connection() as conn:
        cursor = conn.execute('''
            INSERT INTO history (filename, category, total_points, xml_content, editor_json)
            VALUES (?, ?, ?, ?, ?)
        ''', (filename, category, total_points, xml_content, editor_json))
        record_id = cursor.lastrowid
        conn.commit()
        return record_id

def get_history_list() -> List[Dict[str, Any]]:
    with _connection() as conn:
        conn.row_factory = sqlite3.Row
        # Todo menos xml_content (pesado). Hasta 300: el buscador del
        # Historial filtra en el navegador sobre esta lista.
        cursor = conn.execute('''
            SELECT id, filename, category, total_points, created_at,
                   editor_json IS NOT NULL AS has_editor
            FROM history
            ORDER BY id DESC
            LIMIT 300
        ''')
        return [{**dict(row), 'has_editor': bool(row['has_editor'])} for row in cursor.fetchall()]

def get_xml_content(record_id: int) -> Optional[Dict[str, Any]]:
    with _connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT filename, xml_content FROM history WHERE id = ?', (record_id,)).fetchone()
        return dict(row) if row else None

def get_editor_data(record_id: int) -> Optional[Dict[str, Any]]:
    with _connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            'SELECT filename, category, total_points, editor_json FROM history WHERE id = ?',
            (record_id,),
        ).fetchone()
        return dict(row) if row else None

def delete_history_item(record_id: int) -> bool:
    with _connection() as conn:
        cursor = conn.execute('DELETE FROM history WHERE id = ?', (record_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        return deleted
