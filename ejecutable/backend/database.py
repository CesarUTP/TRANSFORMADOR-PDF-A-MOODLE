import os
import sqlite3
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

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

def init_db():
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            category TEXT NOT NULL,
            total_points REAL NOT NULL,
            xml_content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("Database initialized at %s", db_path)

def save_conversion(filename: str, category: str, total_points: float, xml_content: str) -> int:
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO history (filename, category, total_points, xml_content)
        VALUES (?, ?, ?, ?)
    ''', (filename, category, total_points, xml_content))
    record_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return record_id

def get_history_list() -> List[Dict[str, Any]]:
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    # Fetch all except xml_content to save memory
    cursor.execute('''
        SELECT id, filename, category, total_points, created_at 
        FROM history 
        ORDER BY id DESC 
        LIMIT 50
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_xml_content(record_id: int) -> Optional[Dict[str, Any]]:
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT filename, xml_content FROM history WHERE id = ?', (record_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def delete_history_item(record_id: int) -> bool:
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = ?', (record_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted
