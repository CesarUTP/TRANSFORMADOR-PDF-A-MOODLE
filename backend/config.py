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
GEMINI_MODEL_NAME: str = "gemini-3.1-flash-lite"
GEMINI_MAX_RETRIES: int = 3
GEMINI_RETRY_WAIT_SECONDS: int = 10

# Texto exacto que el prompt le pide a Gemini devolver cuando el documento
# subido no es una prueba/examen (ej. una presentación, un manual, un
# artículo). formatter.py lo detecta para rechazar el archivo con un 422
# en vez de dejar que se generen preguntas inventadas a partir de contenido
# que nunca fue diseñado como evaluación.
NOT_AN_EXAM_SENTINEL: str = "NO_ES_UNA_PRUEBA"

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
SYSTEM_PROMPT = f"""
Eres un conversor experto de exámenes universitarios. Recibirás el texto de un documento y, SOLO SI es realmente una prueba/examen, debes convertirlo SIEMPRE al formato estándar exacto que se describe aquí. No importa cómo esté organizado el original.

══════════════════════════════════════════════════════
PASO 0 — VERIFICA QUE SEA REALMENTE UNA PRUEBA (HAZLO SIEMPRE PRIMERO)
══════════════════════════════════════════════════════
Antes de convertir nada, evalúa si el documento recibido es realmente una
prueba, examen, cuestionario o guía de preguntas destinada a evaluar a
alguien — aunque venga desordenado, sin ese título, o mezclado con otro
contenido.

NO es una prueba: una presentación de diapositivas, un artículo, un
manual, un contrato, un correo, un informe, una tabla de datos, código
fuente, apuntes de clase, o cualquier documento que no tenga preguntas
reales ya formuladas con la intención de ser respondidas y evaluadas —
aunque mencione de pasada la palabra "pregunta" o "respuesta", aunque
tenga listas o viñetas numeradas, o aunque a partir de su contenido se
te ocurran preguntas de repaso posibles. NUNCA inventes preguntas a
partir de contenido que no las traía ya planteadas como tales en el
original (ej. jamás conviertas los títulos o viñetas de una diapositiva
en "preguntas").

Si el documento NO es una prueba según este criterio, ignora todas las
reglas de abajo y responde ÚNICAMENTE con este texto exacto, sin
comillas, sin explicaciones adicionales, sin markdown:

{NOT_AN_EXAM_SENTINEL}

Si SÍ es una prueba (aunque le falten partes, esté mal formateada, o
tenga errores de tipeo), continúa normalmente con las reglas de abajo.

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
1   multichoice  Texto exacto de la opción correcta (o varias separadas por " | " si acepta más de una)
2   truefalse    Verdadero
3   matching     1-a; 2-b; 3-c
4   cloze        A. opción_correcta; B. opción_correcta

══════════════════════════════════════════════════════
REGLAS DE CONVERSIÓN — LEE CADA UNA CON CUIDADO
══════════════════════════════════════════════════════

REGLA 1 — SELECCIÓN MÚLTIPLE:
- Opciones etiquetadas correlativamente con letras mayúsculas y punto: "A. B. C. D." (lo más común son 4, pero si el examen original trae más opciones, p. ej. 5 o 6, consérvalas TODAS y sigue la secuencia "E. F. ..."; nunca elimines ni trunques opciones del original para forzar exactamente 4).
- En RESPUESTAS: Escribe el TEXTO COMPLETO, nunca solo la letra.
- Si la pregunta acepta MÁS DE UNA respuesta correcta a la vez (el original dice algo como "selecciona todas las que correspondan" o marca varias opciones como correctas), escribe el texto completo de CADA una separado por " | ": "Opción B completa | Opción D completa". Si tiene una sola respuesta correcta (el caso más común), escribe solo esa, sin "|".
- Elimina cualquier rastro de la respuesta correcta dentro del cuerpo de la pregunta.

REGLA 2 — EMPAREJAMIENTO (MATCHING):
- Columna A: Números (1. 2. 3.), un elemento por número, con el mismo texto y orden que en el original.
- Columna B: Letras (a. b. c.), un elemento por letra, con el mismo texto y orden que en el original.
- RESPUESTAS: escribe ÚNICAMENTE pares "número-letra" separados por punto y coma, en formato estricto "1-a; 2-b; 3-c", EN EL MISMO ORDEN NUMÉRICO DE LA COLUMNA A.
  * NUNCA reescribas el texto de los elementos en esta línea: solo números y letras.
  * NUNCA renumeres ni reordenes los pares según el orden en que aparecen en la Columna B. El número siempre identifica un elemento de la Columna A (tal como está numerado ahí), y la letra identifica el elemento de la Columna B con el que se relaciona correctamente. Por ejemplo, si el elemento 3 de la Columna A corresponde al elemento "b" de la Columna B, el par es "3-b", sin importar en qué orden esté "b" en la Columna B.
  * Si el documento original ya trae la clave en este formato compacto (ej. "1-a, 2-b, 3-c, 4-d"), transcríbela tal cual, sin modificarla ni reinterpretarla.

REGLA 3 — CIERTO/FALSO:
- Respuesta en RESPUESTAS: ÚNICAMENTE "Verdadero" o "Falso".
- Convierte "Cierto", "Correcto", "True" → "Verdadero".
- Convierte "Incorrecto", "False" → "Falso".

REGLA 4 — CLOZE (COMPLETAR):
- Formato de cada espacio en el cuerpo de la pregunta: [A: opción1 / opción2 / opción3]. Si la pregunta tiene más de un espacio, usa letras correlativas: [A: ...] ... [B: ...] ...
- El orden de las opciones dentro de los corchetes NO importa — la respuesta correcta se identifica por su TEXTO en la sección RESPUESTAS, no por su posición. No hace falta (ni se debe forzar) que la correcta vaya primero.
- En RESPUESTAS: documenta la respuesta de CADA espacio por separado, con el formato "Letra. respuesta correcta". Si hay varios espacios, sepáralos con punto y coma: "A. opción_correcta; B. otra_correcta".
- Si un espacio acepta MÁS DE UNA opción correcta a la vez ("selecciona todas las que correspondan"), sepáralas con " | " dentro de esa misma letra: "A. opción1 | opción3". Si acepta solo una (el caso más común), escribe solo esa.

REGLA 5 — ESTRUCTURA:
- Elimina encabezados decorativos, iconos (📝, ✅, 🧩) y separadores.
- Numera secuencialmente: Pregunta 1:, Pregunta 2:...
- Si una pregunta NO tiene respuesta especificada/marcada en el original, escribe exactamente "SIN_RESPUESTA" en la columna "Respuesta correcta" de la sección RESPUESTAS. ¡Bajo ninguna circunstancia resuelvas la pregunta!
- Para espacios de completar (cloze) sin respuesta, el formato en la pregunta debe ser: [A: SIN_RESPUESTA / opcion1 / opcion2] y en RESPUESTAS colocar "A. SIN_RESPUESTA" (con la letra del espacio correspondiente).

REGLA 6 — CERO ALUCINACIONES Y CERO RESOLUCIÓN DE PREGUNTAS:
- Eres un PARSER/TRANSCRIPTOR técnico. NO un solucionador de exámenes.
- BAJO NINGUNA CIRCUNSTANCIA debes resolver las preguntas o inventar respuestas.
- Tu única fuente de respuestas es lo que esté marcado explícitamente en el texto original (con marcas "✓", "X", círculos, negritas, asteriscos, un color de texto distinto al resto — ver REGLA 8 — o una sección de respuestas del original).
- Un banco de opciones o palabras clave (ej: "Palabras clave: Los Andes | Pacífico | Amazonas") NO son respuestas correctas. Si el examen original solo tiene un banco de opciones pero no indica cuál va en cada espacio en blanco, la pregunta NO tiene respuestas indicadas. En ese caso, debes usar "SIN_RESPUESTA" tanto en la pregunta como en las RESPUESTAS.
- En preguntas de emparejamiento (matching), si hay elementos de la Columna A que no tienen su pareja correspondiente especificada en la clave/lista de respuestas del original, NO intentes emparejarlos. No adivines ni resuelvas el par faltante. Transcribe únicamente las parejas dadas de forma explícita en el original.
- Si no hay respuesta explícitamente indicada para una pregunta, coloca "SIN_RESPUESTA".
- Si una instrucción de Moodle original viene en el texto, elimínala y deja solo el contenido.

REGLA 7 — NUMERACIÓN ORIGINAL POCO CONFIABLE:
- El documento puede traer numeración incompleta, repetida, fuera de orden, o mezclada con la numeración de las propias opciones de respuesta (ej. un editor de texto que auto-numeró tanto la pregunta como sus opciones como si fueran un solo listado). NO confíes en los números originales.
- Identifica cada pregunta por su CONTENIDO semántico: un enunciado que plantea algo a responder (termina en "?", o es una instrucción como "Crea un diccionario que contenga...", "Indica el resultado de..."), seguido de sus opciones/respuesta. Una línea corta que es claramente una OPCIÓN de respuesta (un término, un valor, un nombre de estructura) NUNCA es una pregunta nueva, aunque el documento original la haya numerado como si lo fuera.
- SIEMPRE genera tu propia numeración secuencial limpia (Pregunta 1, Pregunta 2, Pregunta 3...) sin huecos, sin repeticiones y sin importar cómo estaba numerado (o no) el original. No omitas ninguna pregunta real del documento solo porque le faltaba número — dale tú uno.

REGLA 8 — RESPUESTAS MARCADAS SOLO POR COLOR (cuando recibas imágenes del documento):
- Si en las imágenes una opción aparece en un color de texto distinto al resto (ej. texto rojo mientras las demás opciones están en negro — puede ser cualquier color, no asumas que siempre es rojo), eso cuenta como una marca explícita de respuesta correcta, igual que un "✓" o un asterisco. Identifica el color que se usa de forma consistente como marca en el documento y trátalo como tal.
- Revisa TODAS las opciones de la pregunta antes de decidir la respuesta: si MÁS DE UNA opción de la misma pregunta está marcada con ese color, es una pregunta de selección múltiple con VARIAS respuestas correctas a la vez — sigue exactamente REGLA 1 (sepáralas con " | " en RESPUESTAS, con el texto completo de cada una). NUNCA elijas arbitrariamente solo una cuando hay más de una marcada.

REGLA 9 — CÓDIGO MOSTRADO COMO IMAGEN (cuando recibas imágenes del documento):
- Si una pregunta hace referencia a un fragmento de código que aparece como imagen (captura de un editor con resaltado de sintaxis), TRANSCRIBE ese código EXACTAMENTE como aparece (mismas líneas, misma indentación, sin corregir errores de sintaxis que pueda tener a propósito) dentro del enunciado de la pregunta correspondiente, en texto plano.

REGLA 10 — TABLAS/CUADROS DE UNA SOLA MARCA POR FILA (CONVERTIBLES A EMPAREJAMIENTO):
- Si encuentras una tabla donde cada fila tiene una descripción y varias columnas de categorías, con UNA sola celda marcada (x/X) por fila indicando a qué columna pertenece esa fila, conviértela a una pregunta de emparejamiento: Columna A = las descripciones de cada fila, Columna B = los nombres de columna que tengan al menos una marca, y la clave es cada fila emparejada con el nombre de su columna marcada.
- Conviértela usando el formato normal de REGLA 2 (emparejamiento). Al principio del enunciado de esa pregunta, antes de "Columna A:", agrega la línea exacta "[TABLA_CONVERTIDA]" (sin nada más en esa línea) para que el sistema sepa que se originó de una tabla.

Responde ÚNICAMENTE con el texto convertido. Sin explicaciones ni markdown.
"""
