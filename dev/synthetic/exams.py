"""
exams.py — Definición de los exámenes sintéticos del set de regresión.

Cada examen se define aquí como DATOS (la verdad), y generate.py los
dibuja como PDF de distintas maneras (clave al final, marcas de color,
asterisco, tabla de marcas, escaneado...). Como el PDF se genera a partir
de estos datos, la respuesta correcta de cada pregunta se conoce por
construcción — el "golden" no depende de que nadie lo etiquete a mano.

Formato de una pregunta (el mismo que usa el golden, ver README.md):
  {"type": "multichoice", "stem": str, "options": [str], "correct": [int]}
  {"type": "truefalse",   "stem": str, "answer": "Verdadero"|"Falso"}
  {"type": "matching",    "stem": str, "pairs": [[izq, der], ...], "extra_right": [str]}
  {"type": "cloze",       "text": "... {0} ... {1} ...", "blanks": [{"options": [str], "correct": [int]}]}
  {"type": "essay",       "stem": str}
  {"type": "shortanswer", "stem": str, "answer": str}
  {"type": "numerical",   "stem": str, "answer": str}
Cualquier pregunta puede llevar "unanswered": True — el documento NO
marca su respuesta, y lo correcto es que el sistema no invente una.

CLAVES CONTRAFÁCTICAS (marcadas con # ≠ abajo): en varias preguntas el
documento marca a propósito una respuesta que NO es la correcta en la
realidad. El sistema es un transcriptor: debe respetar lo que dice el
documento aunque esté "mal". Si una de esas preguntas sale con la
respuesta real, el modelo la RESOLVIÓ en vez de leer la marca — que es
justo lo que la REGLA 6 prohíbe y lo que una clave correcta no permite
detectar (el modelo acierta igual resolviendo).
"""

# ── Banco base: los 7 tipos, respuestas explícitas ──────────────────────────
BASE_MIXED = [
    {"type": "multichoice", "stem": "¿Cuál es el planeta más grande del sistema solar?",
     "options": ["Marte", "Júpiter", "Saturno", "Venus"], "correct": [2]},  # ≠ (real: Júpiter)
    {"type": "multichoice", "stem": "¿Qué gas absorben las plantas durante la fotosíntesis?",
     "options": ["Oxígeno", "Nitrógeno", "Dióxido de carbono", "Helio"], "correct": [2]},
    {"type": "truefalse", "stem": "El agua hierve a 100 grados Celsius a nivel del mar.",
     "answer": "Verdadero"},
    {"type": "truefalse", "stem": "La Gran Muralla China es visible a simple vista desde la Luna.",
     "answer": "Verdadero"},  # ≠ (real: Falso)
    {"type": "matching", "stem": "Relaciona cada país con su capital.",
     "pairs": [["Perú", "Lima"], ["Chile", "Santiago"], ["Colombia", "Bogotá"], ["Ecuador", "Quito"]]},
    {"type": "cloze", "text": "La capital de Francia es {0} y su río principal es el {1}.",
     "blanks": [{"options": ["París", "Lyon", "Marsella"], "correct": [0]},
                {"options": ["Sena", "Loira", "Ródano"], "correct": [0]}]},
    {"type": "essay", "stem": "Explica con tus palabras las causas principales de la Primera Guerra Mundial."},
    {"type": "shortanswer", "stem": "¿Cómo se llama el proceso por el cual el agua pasa de líquido a gas?",
     "answer": "Evaporación"},
    {"type": "numerical", "stem": "¿Cuántos minutos tiene una hora?", "answer": "50"},  # ≠ (real: 60)
    {"type": "multichoice", "stem": "¿Cuál de estos animales es un mamífero?",
     "options": ["Tiburón", "Delfín", "Pingüino", "Cocodrilo"], "correct": [1]},
]

# ── Marcas por color: incluye preguntas con VARIAS correctas ────────────────
COLOR_MC = [
    {"type": "multichoice", "stem": "¿Cuáles de los siguientes son tipos de datos primitivos en Python?",
     "options": ["Entero (int)", "Lista (list)", "Cadena de caracteres (string)", "Diccionario (dict)"],
     "correct": [1, 3]},  # ≠ (real: int y string)
    {"type": "multichoice", "stem": "¿Qué estructura de datos no permite elementos duplicados?",
     "options": ["Lista (list)", "Tupla (tuple)", "Conjunto (set)", "Cadena (str)"], "correct": [0]},  # ≠ (real: set)
    {"type": "multichoice", "stem": "¿Cuál es una característica de una tupla en Python?",
     "options": ["Es inmutable, sus elementos no pueden modificarse después de su creación",
                 "Solo puede contener números", "Se define con llaves {}", "No admite índices"],
     "correct": [0]},
    {"type": "multichoice", "stem": "¿Cuáles de estos lenguajes son de tipado dinámico?",
     "options": ["Python", "Java", "JavaScript", "C"], "correct": [1, 3]},  # ≠ (real: Python y JavaScript)
    {"type": "multichoice", "stem": "¿Qué palabra reservada se usa para definir una función en Python?",
     "options": ["func", "def", "function", "lambda"], "correct": [0]},  # ≠ (real: def)
    {"type": "multichoice", "stem": "¿Qué imprime la instrucción print(3 > 5)?",
     "options": ["True", "False", "None", "Error"], "correct": [0]},  # ≠ (real: False)
    {"type": "multichoice", "stem": "¿Qué operador calcula el residuo de una división?",
     "options": ["/", "//", "%", "**"], "correct": [2]},
    {"type": "multichoice", "stem": "¿Cuáles de los siguientes son bucles en Python?",
     "options": ["for", "repeat", "while", "loop"], "correct": [1, 3]},  # ≠ (real: for y while)
]

# ── Enunciados con listas rotuladas A./B. (caso de corrupción silenciosa) ──
AFIRMACIONES = [
    {"type": "multichoice",
     "stem": "Considera las siguientes afirmaciones:\nA. El agua hierve a 100 °C a nivel del mar.\nB. El hielo se derrite a 0 °C.\n¿Cuál de las opciones es correcta respecto a ellas?",
     "options": ["Solo la primera", "Solo la segunda", "Ambas", "Ninguna"], "correct": [2]},
    {"type": "multichoice",
     "stem": "Lee las siguientes proposiciones:\nA. Lima es la capital del Perú.\nB. Cusco es la capital del Perú.\n¿Qué se puede afirmar?",
     "options": ["A es verdadera y B es falsa", "A es falsa y B es verdadera", "Ambas son verdaderas", "Ambas son falsas"],
     "correct": [0]},
    {"type": "multichoice",
     "stem": "Dados los siguientes pasos de un algoritmo:\nA. Leer el número.\nB. Multiplicarlo por dos.\n¿Qué resultado da el algoritmo si se lee el 7?",
     "options": ["7", "9", "14", "49"], "correct": [2]},
    {"type": "truefalse", "stem": "Un triángulo equilátero tiene sus tres lados iguales.", "answer": "Verdadero"},
]

# ── Tabla de marcas (una X por fila) → emparejamiento ───────────────────────
TABLA = {
    "stem": "Marca con una X el tipo de operador al que corresponde cada situación.",
    "columns": ["Aritmético", "Relacional", "Lógico", "Asignación"],
    "rows": [
        ["Elevar un número a un exponente", 0],
        ["Saber si un número es mayor que otro", 1],
        ["Exigir que se cumplan dos condiciones a la vez", 2],
        ["Guardar un valor dentro de una variable", 3],
        ["Sumar dos cantidades", 2],  # ≠ (real: Aritmético) — detecta columna deducida por significado
    ],
}
TABLA_EXTRA = [
    {"type": "truefalse", "stem": "El operador == compara si dos valores son iguales.", "answer": "Verdadero"},
    {"type": "multichoice", "stem": "¿Qué valor tiene la expresión 2 + 3 * 4?",
     "options": ["20", "14", "24", "9"], "correct": [1]},
]

# ── Marcas por asterisco + preguntas SIN respuesta marcada ─────────────────
ASTERISCO = [
    {"type": "multichoice", "stem": "¿En qué año llegó Cristóbal Colón a América?",
     "options": ["1492", "1502", "1392", "1521"], "correct": [1]},  # ≠ (real: 1492)
    {"type": "multichoice", "stem": "¿Cuál es el océano más grande del mundo?",
     "options": ["Atlántico", "Índico", "Pacífico", "Ártico"], "correct": [2]},
    {"type": "multichoice", "stem": "¿Qué órgano bombea la sangre en el cuerpo humano?",
     "options": ["Pulmón", "Hígado", "Riñón", "Corazón"], "correct": [], "unanswered": True},
    {"type": "multichoice", "stem": "¿Cuál es el metal más abundante en la corteza terrestre?",
     "options": ["Hierro", "Aluminio", "Cobre", "Oro"], "correct": [1]},
    {"type": "multichoice", "stem": "¿Cuántos continentes se reconocen tradicionalmente?",
     "options": ["Cinco", "Seis", "Siete", "Ocho"], "correct": [], "unanswered": True},
    {"type": "multichoice", "stem": "¿Qué científico formuló la teoría de la relatividad?",
     "options": ["Newton", "Einstein", "Galileo", "Darwin"], "correct": [0]},  # ≠ (real: Einstein)
]

# ── Cloze: varios huecos, y un banco de palabras SIN respuesta ─────────────
CLOZE = [
    {"type": "cloze", "text": "El sol sale por el {0} y se oculta por el {1}.",
     "blanks": [{"options": ["este", "oeste", "norte"], "correct": [0]},
                {"options": ["oeste", "este", "sur"], "correct": [0]}]},
    {"type": "cloze", "text": "Los seres vivos que fabrican su propio alimento se llaman {0}.",
     "blanks": [{"options": ["autótrofos", "heterótrofos", "descomponedores"], "correct": [0]}]},
    {"type": "cloze", "text": "El corazón tiene {0} cavidades y la sangre oxigenada sale por la {1}.",
     "blanks": [{"options": ["cuatro", "dos", "tres"], "correct": [0]},
                {"options": ["aorta", "vena cava", "arteria pulmonar"], "correct": [0]}]},
    # Solo banco de palabras, sin indicar cuál va: REGLA 6 → no hay respuesta.
    {"type": "cloze", "text": "La cordillera que atraviesa Sudamérica de norte a sur es {0}.",
     "blanks": [{"options": ["Los Andes", "Los Alpes", "El Himalaya"], "correct": []}],
     "unanswered": True, "word_bank_only": True},
    {"type": "shortanswer", "stem": "¿Qué nombre recibe la capa de gases que rodea la Tierra?",
     "answer": "Atmósfera"},
]

# ── Documento que NO es un examen (debe rechazarse) ─────────────────────────
NO_EXAMEN_PARRAFOS = [
    "Manual de instalación del sistema de riego automático",
    "1. Introducción. Este manual describe cómo instalar y configurar el sistema de riego "
    "automático modelo R-200 en jardines domésticos de hasta 200 metros cuadrados.",
    "2. Requisitos. Antes de comenzar, verifique que cuenta con una toma de agua con presión "
    "mínima de 2 bar y una toma eléctrica de 220 V protegida contra la humedad.",
    "3. Instalación de la unidad central. Fije la unidad a una pared a no menos de 50 cm del suelo. "
    "Conecte la manguera principal a la entrada marcada como IN.",
    "4. Programación. Presione el botón MODO para elegir la frecuencia de riego. La pantalla "
    "mostrará la respuesta del sistema a cada selección.",
    "5. Preguntas frecuentes. Si el sistema no responde, revise el fusible y la conexión de agua. "
    "Para más información, consulte con el servicio técnico autorizado.",
    "6. Garantía. El equipo cuenta con una garantía de 12 meses contra defectos de fabricación.",
]


def long_exam(n: int = 60) -> list:
    """Examen largo generado de forma determinista (sumas y V/F)."""
    qs = []
    for i in range(n):
        a, b = 3 + i, 7 + (i * 3) % 11
        if i % 3 == 2:
            s = a + b
            claim_ok = (i % 2 == 0)
            shown = s if claim_ok else s + 1
            qs.append({"type": "truefalse", "stem": f"La suma de {a} y {b} es igual a {shown}.",
                       "answer": "Verdadero" if claim_ok else "Falso"})
        else:
            s = a + b
            opts = [str(s - 2), str(s), str(s + 3), str(s + 5)]
            # Rotar la posición de la correcta para no dejarla siempre en B.
            rot = i % 4
            opts = opts[rot:] + opts[:rot]
            qs.append({"type": "multichoice", "stem": f"¿Cuánto es {a} + {b}?",
                       "options": opts, "correct": [opts.index(str(s))]})
    return qs
