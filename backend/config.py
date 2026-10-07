"""
config.py — Configuración centralizada del proyecto PDF → Moodle XML.

Todas las constantes que antes estaban dispersas en varios módulos se
consolidan aquí. Los valores sensibles (como API keys) se leen desde
variables de entorno con un fallback vacío para forzar configuración
explícita en producción.
"""
import os
import sys
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)


def _app_data_dir() -> Path:
    """Carpeta de datos de la app (la misma que usa database.py)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "ConversorMoodleXML"


def _load_dotenv() -> None:
    """
    Carga variables desde un archivo .env local (NO versionado — ver
    .gitignore) sin agregar dependencias: una línea CLAVE=valor por
    variable, se ignoran comentarios (#) y líneas vacías. Nunca pisa una
    variable que ya venga del entorno real. Se buscan, en orden:

      1. En la carpeta de datos de la app (la misma del historial):
           macOS:   ~/Library/Application Support/ConversorMoodleXML/.env
           Windows: %LOCALAPPDATA%\\ConversorMoodleXML\\.env
         Es la ubicación recomendada: sobrevive a recompilar o reinstalar
         la app (antes la clave vivía DENTRO del .app y se perdía en cada
         compilación).
      2. Junto al ejecutable empaquetado.
      3. En backend/ y en la raíz del proyecto (desarrollo).

    Una línea vacía ("GEMINI_API_KEY=" sin valor) no cuenta: así la
    plantilla recién creada no tapa una clave puesta en otro lugar.
    """
    candidates = [_app_data_dir() / ".env"]
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / ".env")
    here = Path(__file__).resolve().parent
    candidates += [here / ".env", here.parent / ".env"]
    for path in candidates:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value


_load_dotenv()

# ── Gemini API ──────────────────────────────────────────────────────────────
# La clave de cada usuario se pega en el modal de bienvenida y se guarda
# cifrada en la carpeta de datos (ver credenciales.py). GEMINI_API_KEY
# en el entorno o en un .env sigue sirviendo para desarrollo. Nunca va en
# el código: la anterior quedó en el historial del repo y hubo que rotarla.
ENV_PATH = _app_data_dir() / ".env"
# Mensaje único para cuando falta: lo muestra la app tal cual (ver
# ia_reintentos.generar_con_reintentos), así el usuario sabe qué hacer en vez
# de ver un error técnico de la API.
MISSING_API_KEY_MESSAGE = (
    "Falta configurar tu API de Gemini. Ábrela desde «Acerca de», arriba a la "
    "derecha (sección «API de Gemini»), y pega tu clave de Google AI Studio (se obtiene gratis en "
    "https://aistudio.google.com/apikey)."
)
# Se puede cambiar con la variable GEMINI_MODEL (p. ej. para comparar
# modelos con dev/eval.py sin tocar el código).
GEMINI_MODEL_NAME: str = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-3.1-flash-lite"
GEMINI_MAX_RETRIES: int = 3
# Tiempo máximo de UNA llamada a Gemini. Sin esto, una petición que se
# queda colgada del lado de Google esperaba el timeout por defecto del SDK
# (~10 min) antes de reintentar — visto en la evaluación: corridas de
# ~700 s en documentos que normalmente tardan 10-40 s. El examen real más
# largo probado (19 páginas, 55 preguntas) responde en < 60 s, así que
# 180 s deja margen de sobra y convierte el cuelgue en un reintento rápido.
GEMINI_REQUEST_TIMEOUT_SECONDS: int = 180
# El modo JSON genera ~3x más texto: el examen más lento medido (55
# preguntas largas) tardó hasta 112 s, así que se le da más margen para
# que un examen algo más grande no se convierta en un error por el corte.
GEMINI_REQUEST_TIMEOUT_SECONDS_JSON: int = 300
GEMINI_RETRY_WAIT_SECONDS: int = 10

# temperature=0: la respuesta se genera de forma lo más determinista posible
# (menos "creatividad"/aleatoriedad en el muestreo). Para una tarea de
# transcripción/estructuración como esta no queremos variedad — queremos
# que el mismo documento produzca siempre el mismo resultado. Reduce (no
# elimina del todo) la inconsistencia observada entre corridas idénticas,
# sobre todo leyendo color en imágenes.
GEMINI_TEMPERATURE: float = 0.0

# Reintento de CALIDAD (distinto del reintento por error de la API más
# abajo): a veces Gemini responde sin ningún error técnico pero con
# demasiadas preguntas marcadas SIN_RESPUESTA de golpe — señal de que esa
# corrida en particular "leyó mal" el documento (más notorio detectando
# color en imágenes). Si la proporción de SIN_RESPUESTA supera este
# umbral, se reintenta la llamada hasta GEMINI_MAX_QUALITY_ATTEMPTS veces
# y se usa el mejor resultado, en vez de quedarse con el primero que salió mal.
GEMINI_SIN_RESPUESTA_THRESHOLD: float = 0.35
GEMINI_MAX_QUALITY_ATTEMPTS: int = 3

# Texto exacto que el prompt le pide a Gemini devolver cuando el documento
# subido no es una prueba/examen (ej. una presentación, un manual, un
# artículo). ia_seleccion.py lo detecta para rechazar el archivo con un 422
# en vez de dejar que se generen preguntas inventadas a partir de contenido
# que nunca fue diseñado como evaluación.
NOT_AN_EXAM_SENTINEL: str = "NO_ES_UNA_PRUEBA"

# Marca (REGLA 11) que Gemini agrega al enunciado de una pregunta cuando
# recibió una imagen necesaria para responderla pero no pudo leerla con
# confianza (borrosa, cortada, ilegible) — validator.py la detecta para dar
# un motivo de "omitida" más específico que el genérico "sin respuesta".
TRANSCRIPTION_FAILED_MARKER: str = "[TRANSCRIPCION_FALLIDA]"

# ── Versión y actualizaciones ───────────────────────────────────────────────
# Única fuente de la versión (splash, API, aviso de actualización). Al
# publicar una nueva: subir este número y el de ejecutable/installer.iss, y
# actualizar version.json (en la raíz del repositorio) con la misma versión
# y el enlace de descarga.
APP_VERSION: str = "2.6"
# La app lee este archivo al arrancar para avisar si hay una versión más
# nueva. Tiene que ser una dirección PÚBLICA: mientras el repositorio sea
# privado, GitHub responde 404 y la app simplemente no avisa nada.
URL_ACTUALIZACIONES: str = "https://raw.githubusercontent.com/CesarUTP/TRANSFORMADOR-PDF-A-MOODLE/main/version.json"
# El enlace de descarga del aviso solo puede apuntar aquí (lo abre el
# navegador del sistema; ver launcher.open_url).
PREFIJO_DESCARGAS: str = "https://github.com/CesarUTP/TRANSFORMADOR-PDF-A-MOODLE/"

# ── Servidor ────────────────────────────────────────────────────────────────
SERVER_HOST: str = "127.0.0.1"
SERVER_PORT: int = 8000

# ── Valores por defecto del endpoint /convert ───────────────────────────────
DEFAULT_CATEGORY: str = "mis-preguntas"
DEFAULT_TOTAL_POINTS: float = 100.0

# ── Pesos relativos por tipo de pregunta para distribución de puntaje ───────
# Estos pesos determinan cuánto vale cada tipo respecto a los demás.
# Fórmula:  grade_tipo = (peso_tipo / Σ(peso_i × cantidad_i)) × total_puntos
TYPE_WEIGHTS: dict[str, int] = {
    "truefalse":    1,
    "shortanswer":  1,
    "numerical":    1,
    "multichoice":  2,
    "matching":     3,
    "cloze":        3,
    "essay":        3,
}

# ── Parámetros XML Moodle ──────────────────────────────────────────────────
MULTICHOICE_PENALTY: float = 0.3333333
FEEDBACK_CORRECT: str = "¡Correcto!"
FEEDBACK_INCORRECT: str = "Incorrecto."
DEFAULT_MATCHING_STEM: str = (
    "Relaciona los elementos de la columna A con la columna B."
)

# ── Tipos de pregunta válidos según spec Moodle XML ────────────────────────
VALID_QUESTION_TYPES: set[str] = {
    "multichoice", "truefalse", "shortanswer", "matching",
    "cloze", "essay", "numerical", "description",
}

# ── Campos obligatorios según spec Moodle XML por tipo ─────────────────────
# Ref: "Formato Moodle XML.txt" — cada pregunta REQUIERE <name> y <questiontext>.
# Los campos adicionales por tipo se listan a continuación.
REQUIRED_FIELDS: dict[str, list[str]] = {
    "multichoice":  ["stem", "options"],       # al menos 2 <answer>, con fraction
    "truefalse":    ["stem"],                  # exactamente 2 <answer> (true/false)
    # Sin "stem" a propósito: una tabla convertida a emparejamiento (REGLA 10)
    # suele venir sin enunciado propio, y xml_builder ya pone
    # DEFAULT_MATCHING_STEM en ese caso. Exigirlo aquí descartaba preguntas
    # completas y correctas que el generador sí sabía construir.
    "matching":     ["col_a", "col_b"],         # al menos 2 <subquestion>
    "cloze":        ["text"],                   # questiontext con sintaxis {N:TYPE:...}
    "essay":        ["stem"],                   # sin respuesta que validar — califica el docente en Moodle
    "shortanswer":  ["stem"],                   # <answer> con el texto corto esperado
    "numerical":    ["stem"],                   # <answer> con un valor numérico
}

# ── Restricciones de estructura Moodle XML ─────────────────────────────────
MIN_MULTICHOICE_OPTIONS: int = 2
MIN_MATCHING_PAIRS: int = 2
MIN_CLOZE_OPTIONS: int = 1

# ── Prompts y esquema de la IA ──────────────────────────────────────────────
# SYSTEM_PROMPT, SYSTEM_PROMPT_JSON y RESPONSE_SCHEMA viven ahora en
# ia_prompts.py (ver __getattr__ al final de este archivo).


# ══════════════════════════════════════════════════════════════════════════
# Normalización con salida estructurada (JSON con esquema)
# ══════════════════════════════════════════════════════════════════════════
# "text": el modelo escribe el formato de texto propio (Pregunta N: / A. B.
#         / RESPUESTAS) y parser.py lo vuelve a leer con regex — el flujo
#         histórico.
# "json": el modelo devuelve JSON restringido por RESPONSE_SCHEMA
#         (decodificación con esquema: no puede emitir una forma inválida)
#         y schema_adapter.py lo convierte a lo que ya consume el editor.
# Se elige por entorno para poder evaluar ambos lado a lado con
# dev/eval.py --mode. Resultado (ver dev/eval_results/RESULTADOS.md): con
# el texto enriquecido, "json" empata en exactitud general y además
# elimina dos errores silenciosos del modo texto (enunciados cortados por
# su propia lista A./B., y respuestas inventadas desde un banco de
# palabras). Tarda 2-5x más (un examen de 55 preguntas: hasta ~95 s), lo
# que se consideró aceptable frente a cargar el examen a mano. Es el modo
# de la carga normal (/api/parse).
NORMALIZER_MODE: str = os.environ.get("NORMALIZER_MODE", "json").strip().lower()

# Modo de "Normalizar con IA" (/api/normalize_with_ai: todas las páginas
# como imagen, pensado para escaneados). Ahí el modo texto midió 100 % y
# el JSON 90 % (resolvió una pregunta por su cuenta), así que se queda en
# texto.
NORMALIZER_MODE_AI: str = os.environ.get("NORMALIZER_MODE_AI", "text").strip().lower()

# Enriquece el texto de las páginas con color o tablas antes de mandarlo al
# modelo (extractor.extract_pages_text_enriched): anota las palabras en
# color (⟦rojo⟧…⟦/rojo⟧) e inserta las tablas con su estructura. Son las
# marcas de respuesta más comunes de un PDF digital y extract_text() las
# pierde: sin esto el modelo no veía la marca y terminaba resolviendo.
# Activo por defecto desde la evaluación de la fase 3 (dev/eval_results):
# sintéticos 87 % → 98 %, reales sin cambios, mismo tiempo de respuesta.
ENRICH_PDF_TEXT: bool = os.environ.get("ENRICH_PDF_TEXT", "1").strip() in ("1", "true", "yes")

# Tope de tokens de salida para el modo JSON: el JSON es más largo que el
# formato de texto (~50 % en las pruebas), y un examen largo puede
# acercarse al límite por defecto. Si aun así se corta, formatter lo
# detecta (finish_reason MAX_TOKENS) en vez de intentar leer JSON truncado.
GEMINI_MAX_OUTPUT_TOKENS: int = 65536


# ── Proveedor de IA ─────────────────────────────────────────────────────────
# Qué servicio de IA usa la app (ver ia_proveedor.py). Hoy solo existe
# «gemini»; un proveedor nuevo (p. ej. uno local) se agrega como módulo
# ia_<nombre>.py y se registra en ia_proveedor._REGISTRO. Se puede cambiar
# con la variable de entorno CONVERSOR_PROVEEDOR_IA.
IA_PROVEEDOR_POR_DEFECTO: str = "gemini"
IA_PROVEEDOR_VARIABLE: str = "CONVERSOR_PROVEEDOR_IA"


def __getattr__(nombre: str):
    """Los prompts y el esquema de la IA se movieron a ia_prompts.py; este
    atajo (importación diferida: ia_prompts importa de aquí) mantiene vivos
    los `from config import SYSTEM_PROMPT` de siempre."""
    if nombre in ("SYSTEM_PROMPT", "SYSTEM_PROMPT_JSON", "RESPONSE_SCHEMA"):
        import ia_prompts
        return getattr(ia_prompts, nombre)
    raise AttributeError(f"module {__name__!r} has no attribute {nombre!r}")
