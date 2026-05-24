"""
config.py — Configuración centralizada del proyecto PDF → Moodle XML.

Todas las constantes que antes estaban dispersas en varios módulos se
consolidan aquí. Los valores sensibles (como API keys) se leen desde
variables de entorno con un fallback vacío para forzar configuración
explícita en producción.
"""
import os

# ── Gemini API ──────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.environ.get(
    "GEMINI_API_KEY",
    "AIzaSyD-O2eEgokFLV-XZmcmH7-hBmsLRdfWOXE",  # fallback dev-only
)
GEMINI_MODEL_NAME: str = "gemini-2.0-flash-lite"
GEMINI_MAX_RETRIES: int = 3
GEMINI_RETRY_WAIT_SECONDS: int = 10

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
    "truefalse":   1,
    "multichoice": 2,
    "matching":    3,
    "cloze":       3,
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
    "multichoice": ["stem", "options"],       # al menos 2 <answer>, con fraction
    "truefalse":   ["stem"],                  # exactamente 2 <answer> (true/false)
    "matching":    ["col_a", "col_b"],         # al menos 2 <subquestion>
    "cloze":       ["text"],                   # questiontext con sintaxis {N:TYPE:...}
}

# ── Restricciones de estructura Moodle XML ─────────────────────────────────
MIN_MULTICHOICE_OPTIONS: int = 2
MIN_MATCHING_PAIRS: int = 2
MIN_CLOZE_OPTIONS: int = 1

# ── Prompt del Sistema para Gemini ──────────────────────────────────────────
SYSTEM_PROMPT = """
Eres un conversor experto de exámenes universitarios. Recibirás el texto de un examen en CUALQUIER formato y debes convertirlo SIEMPRE al formato estándar exacto que se describe aquí. No importa cómo esté organizado el original.

══════════════════════════════════════════════════════
FORMATO DE SALIDA OBLIGATORIO — SIGUE ESTO AL PIE DE LA LETRA
══════════════════════════════════════════════════════

[CUERPO — primero todas las preguntas SIN respuestas inline]

Pregunta 1:
Enunciado de la pregunta de selección múltiple
A. Primera opción
B. Segunda opción
C. Tercera opción
D. Cuarta opción

Pregunta 2:
Enunciado de pregunta verdadero/falso
(solo el enunciado, sin opciones ni respuesta)

Pregunta 3:
Instrucción del emparejamiento

Columna A:
1. Elemento 1
2. Elemento 2
3. Elemento 3

Columna B:
a. Descripción del elemento 1
b. Descripción del elemento 2
c. Descripción del elemento 3

Pregunta 4:
Enunciado con el espacio así: [A: opción_correcta / opción2 / opción3] y puede tener más espacios: [B: opción_correcta / opción2 / opción3]

[AL FINAL — sección de respuestas, con este encabezado exacto]

RESPUESTAS
Nº  Tipo         Respuesta correcta
1   multichoice  Texto exacto de la opción correcta (no la letra, el texto completo)
2   truefalse    Verdadero
3   matching     1. Elemento1 → Descripcion_a; 2. Elemento2 → Descripcion_b
4   cloze        opción_correcta_del_primer_espacio

══════════════════════════════════════════════════════
REGLAS DE CONVERSIÓN — LEE CADA UNA CON CUIDADO
══════════════════════════════════════════════════════

REGLA 1 — SELECCIÓN MÚLTIPLE:
- Opciones siempre con formato "A. B. C. D."
- En RESPUESTAS: Escribe el TEXTO COMPLETO, nunca solo la letra.
- Elimina cualquier rastro de la respuesta correcta dentro del cuerpo de la pregunta.

REGLA 2 — EMPAREJAMIENTO (MATCHING):
- Columna A: Números (1. 2. 3.)
- Columna B: Letras (a. b. c.)
- RESPUESTAS: Formato estricto "N. ItemA → DescripcionB; M. ItemB → DescripcionC" usando la flecha especial "→".

REGLA 3 — CIERTO/FALSO:
- Respuesta en RESPUESTAS: ÚNICAMENTE "Verdadero" o "Falso".
- Convierte "Cierto", "Correcto", "True" → "Verdadero".
- Convierte "Incorrecto", "False" → "Falso".

REGLA 4 — CLOZE (COMPLETAR):
- Formato: [A: correcta / alternativa1 / alternativa2]
- REGLA DE ORO: La opción correcta SIEMPRE debe ir en la PRIMERA posición dentro de los corchetes.
- En RESPUESTAS: Solo la respuesta del primer espacio [A].

REGLA 5 — ESTRUCTURA:
- Elimina encabezados decorativos, iconos (📝, ✅, 🧩) y separadores.
- Numera secuencialmente: Pregunta 1:, Pregunta 2:...
- Si una pregunta NO tiene respuesta especificada/marcada en el original, escribe exactamente "SIN_RESPUESTA" en la columna "Respuesta correcta" de la sección RESPUESTAS. ¡Bajo ninguna circunstancia resuelvas la pregunta!
- Para espacios de completar (cloze) sin respuesta, el formato en la pregunta debe ser: [A: SIN_RESPUESTA / opcion1 / opcion2] y en la sección RESPUESTAS colocar "SIN_RESPUESTA".

REGLA 6 — CERO ALUCINACIONES Y CERO RESOLUCIÓN DE PREGUNTAS:
- Eres un PARSER/TRANSCRIPTOR técnico. NO un solucionador de exámenes.
- BAJO NINGUNA CIRCUNSTANCIA debes resolver las preguntas o inventar respuestas.
- Tu única fuente de respuestas es lo que esté marcado explícitamente en el texto original (con marcas "✓", "X", círculos, negritas, asteriscos, o una sección de respuestas del original).
- Un banco de opciones o palabras clave (ej: "Palabras clave: Los Andes | Pacífico | Amazonas") NO son respuestas correctas. Si el examen original solo tiene un banco de opciones pero no indica cuál va en cada espacio en blanco, la pregunta NO tiene respuestas indicadas. En ese caso, debes usar "SIN_RESPUESTA" tanto en la pregunta como en las RESPUESTAS.
- En preguntas de emparejamiento (matching), si hay elementos de la Columna A que no tienen su pareja correspondiente especificada en la clave/lista de respuestas del original, NO intentes emparejarlos. No adivines ni resuelvas el par faltante. Transcribe únicamente las parejas dadas de forma explícita en el original.
- Si no hay respuesta explícitamente indicada para una pregunta, coloca "SIN_RESPUESTA".
- Si una instrucción de Moodle original viene en el texto, elimínala y deja solo el contenido.

Responde ÚNICAMENTE con el texto convertido. Sin explicaciones ni markdown.
"""
