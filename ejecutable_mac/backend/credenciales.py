"""
credenciales.py — dónde vive la clave de la API de Gemini de cada usuario.

Cada instalación usa la clave de su propio docente, que la pega en el
modal de bienvenida la primera vez (o la cambia desde «Acerca de → API de Gemini»).
Se guarda CIFRADA en la carpeta de datos de la app, junto al historial:

  macOS:   ~/Library/Application Support/ConversorMoodleXML/clave.dat
  Windows: %LOCALAPPDATA%\\ConversorMoodleXML\\clave.dat

No se usa un hash: la app necesita la clave tal cual para mandarla a
Google en cada conversión, y un hash no se puede revertir.

El cifrado (Fernet: AES + HMAC) usa una llave derivada del identificador
de ESTE equipo y de ESTE usuario, más una sal al azar guardada en el
archivo. Copiado a otra computadora u otra cuenta, el archivo no sirve.
Tampoco es una bóveda: alguien con acceso a la sesión del usuario podría
descifrarlo. Para una clave gratuita que se anula en un clic desde Google
es suficiente, y a diferencia del Llavero de macOS no pide permiso
después de cada actualización de una app sin firma de desarrollador.

Si el identificador del equipo cambia (p. ej. cambio de placa) la clave
no se puede descifrar: la app simplemente la vuelve a pedir.

Orden de lectura (get_api_key):
  1. clave.dat
  2. La variable GEMINI_API_KEY (entorno real o un .env de desarrollo;
     ver config._load_dotenv).
"""
import base64
import functools
import getpass
import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import uuid

import requests
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from config import ENV_PATH

logger = logging.getLogger(__name__)

ARCHIVO = ENV_PATH.parent / "clave.dat"
_VAR = "GEMINI_API_KEY"

_lock = threading.Lock()
_cache: str | None = None  # None = aún no leída; "" = no hay clave
_origen: str | None = None  # "archivo" | "entorno" | None: de dónde salió _cache
_firma_cache = None  # (mtime_ns, tamaño) de clave.dat cuando se leyó _cache
_aviso: str | None = None  # motivo legible si clave.dat existe pero no se pudo usar


class ClaveInvalida(Exception):
    """Google rechazó la clave."""


class SinConexion(Exception):
    """No se pudo comprobar la clave (sin internet, Google caído…)."""


# ── Llave del equipo ────────────────────────────────────────────────────────
@functools.lru_cache(maxsize=1)
def _id_del_equipo() -> str:
    """Identificador estable de la máquina (no cambia al reinstalar la app).

    Se calcula una sola vez por proceso: en macOS lanza el subproceso `ioreg`
    y el valor no cambia mientras la app está abierta."""
    try:
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            ) as k:
                return str(winreg.QueryValueEx(k, "MachineGuid")[0])
        if sys.platform == "darwin":
            salida = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            for linea in salida.splitlines():
                if "IOPlatformUUID" in linea:
                    return linea.split("=", 1)[1].strip().strip('"')
        for ruta in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            if os.path.isfile(ruta):
                return open(ruta, encoding="utf-8").read().strip()
    except Exception as exc:  # noqa: BLE001 — se usa el respaldo de abajo
        logger.warning("No se pudo leer el identificador del equipo: %s", type(exc).__name__)
    return f"mac-{uuid.getnode():012x}"


def _usuario() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return os.path.expanduser("~")


def _fernet(sal: bytes) -> Fernet:
    material = f"ConversorMoodleXML|{_id_del_equipo()}|{_usuario()}".encode("utf-8")
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=sal, iterations=200_000)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(material)))


# ── Archivo cifrado ─────────────────────────────────────────────────────────
def _firma_archivo():
    """(mtime_ns, tamaño) de clave.dat, o None si no existe o no se puede consultar."""
    try:
        st = ARCHIVO.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _leer_archivo() -> str:
    """La clave descifrada de clave.dat; "" si no hay, no se puede leer (antivirus,
    permisos), tiene otra forma o es de otro equipo/usuario. Nunca lanza y nunca
    registra el contenido del archivo."""
    global _aviso
    try:
        if not ARCHIVO.is_file():
            return ""
        datos = json.loads(ARCHIVO.read_text(encoding="utf-8"))
        sal = base64.b64decode(datos["sal"])
        return _fernet(sal).decrypt(datos["clave"].encode("ascii")).decode("utf-8").strip()
    except OSError as exc:
        _aviso = "No se pudo leer el archivo de la clave guardada (¿lo bloquea un antivirus o faltan permisos?). Ingresa la clave de nuevo."
        logger.warning("No se pudo leer clave.dat (%s); se pedirá la clave otra vez.", type(exc).__name__)
        return ""
    except (InvalidToken, KeyError, ValueError, TypeError, AttributeError) as exc:
        # Otro equipo/usuario, o archivo dañado o con otra forma: se vuelve a pedir.
        _aviso = "La clave guardada no se pudo descifrar (otro equipo o archivo dañado). Ingresa la clave de nuevo."
        logger.warning("No se pudo descifrar clave.dat (%s); se pedirá la clave otra vez.", type(exc).__name__)
        return ""


def _escribir_archivo(clave: str) -> None:
    """Escribe (o reemplaza) clave.dat. Sal nueva en cada guardado."""
    ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    sal = secrets.token_bytes(16)
    datos = {
        "v": 1,
        "sal": base64.b64encode(sal).decode("ascii"),
        "clave": _fernet(sal).encrypt(clave.encode("utf-8")).decode("ascii"),
    }
    # Se escribe aparte y se reemplaza de una vez: un corte a mitad de
    # camino no deja un archivo a medias (ni pierde la clave anterior).
    tmp = ARCHIVO.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, ARCHIVO)


# ── .env de instalaciones anteriores ───────────────────────────────────────
def _clave_en_env_de_datos() -> str:
    """El valor de GEMINI_API_KEY en el .env de la carpeta de datos, si lo hay."""
    try:
        if not ENV_PATH.is_file():
            return ""
        lineas = ENV_PATH.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return ""
    for linea in lineas:
        k, sep, v = linea.strip().partition("=")
        if sep and k.strip() == _VAR:
            return v.strip().strip('"').strip("'")
    return ""


def _vaciar_env_de_datos() -> None:
    """Deja "GEMINI_API_KEY=" vacío en el .env de datos (el resto del archivo se conserva)."""
    if not ENV_PATH.is_file():
        return
    lineas = ENV_PATH.read_text(encoding="utf-8").splitlines()
    nuevas = [f"{_VAR}=" if l.strip().partition("=")[0].strip() == _VAR else l for l in lineas]
    ENV_PATH.write_text("\n".join(nuevas) + "\n", encoding="utf-8")


def _migrar_env() -> None:
    """
    Instalaciones anteriores guardaban la clave en texto plano en el .env
    de la carpeta de datos. Si todavía no hay clave.dat, se cifra ahí y se
    borra del .env.
    """
    clave = _clave_en_env_de_datos()
    if not clave or _firma_archivo() is not None:
        return
    try:
        _escribir_archivo(clave)
        _vaciar_env_de_datos()
        if os.environ.get(_VAR, "").strip() == clave:
            os.environ.pop(_VAR, None)
        logger.info("Clave de la API de Gemini movida del .env a clave.dat (cifrada).")
    except Exception as exc:  # noqa: BLE001 — si falla, sigue funcionando desde el .env
        logger.warning("No se pudo cifrar la clave del .env: %s", type(exc).__name__)


# ── API del módulo ──────────────────────────────────────────────────────────
def _cargar() -> None:
    """Lee la clave (clave.dat, o si no el entorno) y recuerda su origen.
    Se llama con _lock tomado."""
    global _cache, _origen, _firma_cache, _aviso
    _aviso = None
    _migrar_env()
    _firma_cache = _firma_archivo()
    desde_archivo = _leer_archivo()
    if desde_archivo:
        _cache, _origen = desde_archivo, "archivo"
    else:
        _cache = os.environ.get(_VAR, "").strip()
        _origen = "entorno" if _cache else None


def get_api_key() -> str:
    """
    La clave vigente ("" si no hay). Queda en memoria y solo se vuelve a leer
    (y a descifrar, que es lo caro) si clave.dat cambió, apareció o desapareció.
    Nunca lanza: un archivo ilegible cuenta como «sin clave».
    """
    with _lock:
        if _cache is None or _firma_archivo() != _firma_cache:
            _cargar()
        return _cache


def estado() -> dict:
    """Si hay clave y de dónde sale — nunca la clave en sí, solo sus 4 últimos caracteres."""
    clave = get_api_key()
    if not clave:
        resp = {"configurada": False, "origen": None, "final": None}
        if _aviso:
            resp["aviso"] = _aviso  # clave.dat existe pero no sirvió; texto fijo, sin datos del archivo
        return resp
    return {"configurada": True, "origen": _origen or "entorno", "final": clave[-4:]}


def validar(clave: str) -> None:
    """
    Comprueba la clave contra Google listando modelos: no gasta tokens ni
    cuesta nada. Lanza ClaveInvalida o SinConexion.
    """
    try:
        resp = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"pageSize": 1},
            headers={"x-goog-api-key": clave},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise SinConexion(type(exc).__name__) from exc
    if resp.status_code == 200:
        return
    if resp.status_code in (400, 401, 403):
        raise ClaveInvalida(resp.status_code)
    # 429/5xx: la clave puede estar bien pero Google no respondió.
    raise SinConexion(f"HTTP {resp.status_code}")


def guardar(clave: str) -> None:
    """Guarda la clave (ya validada), reemplazando la anterior si la había."""
    global _cache, _origen, _firma_cache, _aviso
    with _lock:
        _escribir_archivo(clave)
        # Que no quede una copia vieja en texto plano.
        if _clave_en_env_de_datos():
            _vaciar_env_de_datos()
        os.environ.pop(_VAR, None)
        _cache, _origen, _aviso = clave, "archivo", None
        _firma_cache = _firma_archivo()


def borrar() -> None:
    """Borra clave.dat y la del .env de datos. La app vuelve a pedirla."""
    global _cache, _origen, _firma_cache, _aviso
    with _lock:
        ARCHIVO.unlink(missing_ok=True)
        if _clave_en_env_de_datos():
            _vaciar_env_de_datos()
        os.environ.pop(_VAR, None)
        _cache, _origen, _firma_cache, _aviso = None, None, None, None
