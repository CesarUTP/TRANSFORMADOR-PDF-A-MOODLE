# Set de regresión (golden)

Un archivo `<nombre>.expected.json` por documento de prueba. `dev/eval.py`
corre el pipeline real sobre cada uno y compara contra lo que hay aquí.

```bash
backend/venv/bin/python dev/eval.py                 # todo, 3 corridas por documento
backend/venv/bin/python dev/eval.py --only s02 s05  # solo algunos
backend/venv/bin/python dev/eval.py --mode json     # otro modo de normalización
```

## Dos tipos de documento

| Prefijo | Origen | Verdad |
|---|---|---|
| `s01…s09` | Sintéticos, generados por `dev/synthetic/generate.py` a partir de `dev/synthetic/exams.py` | Exacta por construcción |
| `real_*` | Los PDFs reales de `samples/` | Pre-llenada con el pipeline y **verificada**: ver `reviewed` / `notes` |

Para regenerar los sintéticos (es determinista):

```bash
backend/venv/bin/python -m pip install -r dev/requirements-dev.txt
backend/venv/bin/python dev/synthetic/generate.py
```

## Formato

```jsonc
{
  "source": "synthetic" | "real",
  "reviewed": true,            // false = alguien debe revisarlo contra el PDF
  "file": "synthetic/s01_limpio_clave_final.pdf",   // relativo a samples/
  "path": "parse" | "normalize_with_ai",            // qué flujo de la app se prueba
  "is_exam": true,             // false = debe rechazarse como "no es un examen"
  "notes": "qué prueba este documento",
  "questions": [
    {"type": "multichoice", "stem": "...", "options": ["..."], "answers": ["texto de la correcta", "..."]},
    {"type": "truefalse",   "stem": "...", "answers": ["Verdadero"]},
    {"type": "matching",    "stem": "...", "pairs": [["izquierda", "derecha"], ...]},
    {"type": "cloze",       "stem": "texto con ____ en cada hueco", "blanks": [["correcta"], ...]},
    {"type": "essay",       "stem": "..."},
    {"type": "shortanswer", "stem": "...", "answers": ["..."]},
    {"type": "numerical",   "stem": "...", "answers": ["60"]}
  ]
}
```

Marcas opcionales por pregunta:

- `"unanswered": true` — el documento **no** marca la respuesta. Lo correcto
  es que el sistema no invente una (la pregunta debe quedar omitida por
  falta de respuesta).
- `"lenient": true` — la pregunta es ambigua en el original (ver `note`);
  solo se exige que aparezca, sin juzgar tipo ni respuesta.

Las preguntas se emparejan por parecido del enunciado (y de las opciones),
no por número: el modelo renumera.
