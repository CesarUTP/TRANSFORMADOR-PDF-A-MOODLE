# Conversor a Moodle XML

Convierte tus pruebas, cuestionarios y exámenes (PDF o TXT) en un archivo **Moodle XML Question Format** listo para importar — con un backend FastAPI, una interfaz web moderna, y un prefiltro de IA (Gemini) que normaliza automáticamente exámenes con formato desordenado.

Corre como una app de escritorio nativa (Windows/macOS, vía `pywebview`) — no es necesario tener conocimientos técnicos para usarla.

---

## Características principales

- **7 tipos de pregunta Moodle**: opción múltiple, verdadero/falso, emparejamiento, completar (Cloze), ensayo, respuesta corta y numérica.
- **Respuestas múltiples**: tanto en opción múltiple como en cada espacio de una pregunta Cloze, se puede marcar más de una opción como correcta a la vez.
- **Prefiltro de IA**: si el examen no viene en el formato esperado (numeración distinta, respuestas marcadas con ✓, claves de emparejamiento sueltas, etc.), Gemini lo normaliza automáticamente antes de procesarlo — sin inventar ni resolver ninguna respuesta que no esté indicada en el original.
- **Validación de que el archivo sea realmente una prueba**: antes de convertir nada, el sistema evalúa si el documento tiene preguntas y una clave de respuestas reales. Si le suben una presentación, un manual, un artículo o cualquier otro documento que no sea una evaluación, lo rechaza con un mensaje claro en vez de inventar preguntas a partir de su contenido.
- **Editor de revisión interactivo**: antes de generar el XML final, se pueden inspeccionar y editar todas las preguntas.
  - Filtro por tipo (los 7 tipos soportados), con conteo en vivo y color propio por tipo.
  - Menú de "Añadir nueva pregunta" colapsable: se despliega en un clic y vuelve a cerrarse solo al elegir un tipo.
  - Botones de acción (**Aprobar y Generar XML** / **Cancelar**) fijos arriba del todo — accesibles sin bajar por exámenes de 100+ preguntas — en verde y rojo respectivamente, por convención de color.
  - Checkboxes para respuestas múltiples y un constructor visual para preguntas Cloze (sin escribir la sintaxis de corchetes a mano).
- **Resumen visual del resultado**: al terminar, una tarjeta por cada tipo de pregunta *presente* en el examen (no se muestran tipos con 0 preguntas) y una gráfica de pastel con la distribución de los puntos totales por tipo.
- **Historial de conversiones**: cada examen convertido queda guardado localmente y se puede volver a descargar.
- **100% local**: el procesamiento del documento ocurre en tu equipo. La IA solo recibe el texto ya extraído, únicamente para normalizar su estructura.

---

## Estructura del proyecto

```
Conversor a Moodle XML/
├── iniciar.command       ← Doble clic para abrir la app en macOS
├── iniciar.bat           ← Doble clic para abrir la app en Windows
├── launcher.py           ← Punto de entrada de la app de escritorio (splash + pywebview)
├── build.py              ← Empaqueta la app como ejecutable (PyInstaller)
├── README.md
│
├── backend/
│   ├── main.py           ← API FastAPI (endpoints)
│   ├── config.py         ← Configuración centralizada + prompt del sistema (IA)
│   ├── extractor.py      ← Extracción de texto (.pdf / .txt)
│   ├── pipeline.py       ← Flujo completo de normalización (lo usan la API y dev/eval.py)
│   ├── formatter.py      ← Llamada a Gemini (modo texto o JSON con esquema)
│   ├── parser.py         ← Lee el formato de texto que devuelve la IA (modo texto)
│   ├── schema_adapter.py ← Convierte la salida JSON de la IA (modo JSON)
│   ├── mark_resolver.py  ← Decide en código las respuestas marcadas por color o tabla
│   ├── validator.py      ← Validación de preguntas contra el spec Moodle XML
│   ├── xml_builder.py    ← Generación del XML Moodle
│   ├── database.py       ← Historial de conversiones (SQLite)
│   ├── models.py         ← Modelos Pydantic
│   ├── requirements.txt  ← Dependencias Python
│   └── venv/             ← Entorno virtual (no versionado)
│
├── frontend/
│   └── index.html        ← Interfaz web (HTML + Vanilla JS)
│
├── assets/
│   └── Icon.ico          ← Ícono del ejecutable empaquetado
│
├── data/
│   └── exams_history.db  ← Base de datos del historial (se crea sola en el primer uso, no versionada)
│
├── docs/
│   └── Formato Moodle XML.txt  ← Referencia del spec Moodle XML usado por el validador
│
├── samples/
│   ├── *.pdf / *.txt     ← Exámenes reales de prueba
│   ├── synthetic/        ← Exámenes sintéticos (generados por dev/synthetic/)
│   └── golden/           ← Resultado esperado de cada uno (set de regresión)
│
├── dev/
│   ├── eval.py           ← Evaluación de la normalización contra samples/golden/
│   ├── compare.py        ← Compara resultados de eval.py lado a lado
│   ├── synthetic/        ← Generador de los exámenes sintéticos
│   └── eval_results/     ← Resultados guardados (ver RESULTADOS.md)
│
├── samples/              ← Exámenes de ejemplo para probar la app manualmente
│   ├── Parcial_Historia_Geografia.pdf
│   └── parcial n.1.pdf
│
├── dev/                  ← Scripts y datos usados solo en desarrollo/pruebas
│   ├── create_exam_pdf.py
│   ├── list_models.py
│   ├── run_test.py
│   └── test_webview.py
│
└── ejecutable/           ← Todo lo necesario para generar el instalador de Windows
    ├── backend/ frontend/ assets/ launcher.py  ← copia autosuficiente del código fuente
    ├── build.py           ← compila el .exe con PyInstaller
    ├── installer.iss      ← script de Inno Setup (icono, accesos directos, desinstalador)
    ├── build_windows.bat  ← un solo doble clic que hace todo el proceso
    └── LEEME_WINDOWS.txt  ← instrucciones y requisitos
```

---

## Uso para el usuario final

1. Descarga o clona el proyecto.
2. Haz doble clic en **`iniciar.command`** (macOS) o **`iniciar.bat`** (Windows).
3. La primera vez, el script instala automáticamente todo lo necesario (puede tardar unos minutos); las siguientes veces abre directo.
4. Se abre la app en una ventana nativa: sube tu examen, revisa las preguntas detectadas, y descarga el `.xml` listo para importar en Moodle (**Banco de preguntas → Importar**).

¿Quieres un instalador de verdad (`Setup.exe`, con ícono, acceso directo y desinstalador, sin que el usuario final necesite Python)? Mira [`ejecutable/LEEME_WINDOWS.txt`](ejecutable/LEEME_WINDOWS.txt).

---

## Para desarrolladores

### 1. Crear el entorno virtual

```bash
cd backend
python -m venv venv
```

### 2. Activar el entorno virtual

**Windows (PowerShell):**
```powershell
.\venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
source venv/bin/activate
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
pip install pywebview   # solo si vas a correr la app de escritorio (launcher.py)
```

### 4. Iniciar el backend

```bash
uvicorn main:app --reload --port 8000
```

El API queda disponible en `http://localhost:8000`.
Documentación interactiva Swagger: `http://localhost:8000/docs`.

### 5. Abrir el frontend

Con el backend corriendo, abre `http://localhost:8000` en el navegador — el propio backend sirve el frontend. También puedes correr la app de escritorio nativa con `python launcher.py` desde la raíz del proyecto.

---

## Evaluar cambios en la normalización

Antes de cambiar el prompt, el modelo o la extracción, compara contra el set de regresión:

```bash
backend/venv/bin/python dev/eval.py                    # 15 documentos × 3 corridas
backend/venv/bin/python dev/eval.py --only s02 s05     # solo algunos
backend/venv/bin/python dev/eval.py --mode json        # probar el modo JSON
backend/venv/bin/python dev/compare.py dev/eval_results/A.json dev/eval_results/B.json
```

La métrica principal es la **exactitud**: preguntas que llegan al editor con el tipo, el enunciado completo y la respuesta correctos. Varios exámenes sintéticos traen a propósito claves "incorrectas" (ej. Saturno como el planeta más grande), para detectar si el modelo resuelve en vez de transcribir. Detalles en `samples/golden/README.md`; resultados actuales en `dev/eval_results/RESULTADOS.md`.

---

## Formato esperado del examen

El documento puede subirse en **cualquier formato razonable** (numeración con "1.", "1)", respuestas marcadas con ✓, claves de emparejamiento ya compactas, etc.) — el prefiltro de IA lo normaliza automáticamente al formato interno antes de procesarlo. Ese formato interno es:

```
Pregunta 1:
¿Cuál es la definición de interfaz de usuario?
A. El espacio de contacto entre usuario y sistema
B. Un componente de software únicamente
C. Un protocolo de red
D. Una base de datos relacional

Pregunta 2:
...

Pregunta 4:
Enunciado con un espacio así: [A: opción_correcta / opción2 / opción3]

RESPUESTAS
Nº  Tipo         Respuesta correcta
1   multichoice  El espacio de contacto entre usuario y sistema
2   truefalse    Verdadero
3   matching     1-a; 2-b; 3-c
4   cloze        A. opción_correcta
```

### Tipos de pregunta soportados

| Tipo | Formato en RESPUESTAS |
|------|----------------------|
| `multichoice` | Texto completo de la opción correcta. Si acepta más de una respuesta a la vez, sepáralas con `" \| "` (ej. `Opción B \| Opción D`). |
| `truefalse` | `Verdadero` o `Falso` |
| `matching` | Pares compactos `número-letra`, ej. `1-a; 2-b; 3-c` |
| `cloze` | Un espacio: `A. opción_correcta`. Varios espacios: `A. resp_A; B. resp_B`. Un espacio con varias respuestas correctas: `A. opción1 \| opción3`. |

Las preguntas de tipo **cloze** usan corchetes en el cuerpo, con letras correlativas si hay más de un espacio: `[A: opción1 / opción2 / opción3] ... [B: opción1 / opción2]`. El orden de las opciones dentro de los corchetes no importa — la respuesta correcta se identifica por su texto, no por su posición.

Si una pregunta no tiene una respuesta indicada explícitamente en el examen original, el sistema **nunca la inventa ni la resuelve**: la marca como `SIN_RESPUESTA` y bloquea la generación del XML hasta que se corrija, para no importar a Moodle una clave incorrecta.

---

## Endpoints de la API

### `POST /api/parse`

Sube el archivo (`.pdf` o `.txt`), lo pasa por el prefiltro de Gemini si hace falta, y devuelve las preguntas ya parseadas y validadas.

### `POST /api/parse_stream` y `POST /api/normalize_with_ai_stream`

Igual que `/api/parse` y `/api/normalize_with_ai`, pero la respuesta es NDJSON (una línea JSON por evento) para mostrar el avance: `{"type": "stage", …}`, `{"type": "progress", "done": 12, "expected": 40}` y al final `{"type": "result", "data": …}` o `{"type": "error", "status": …, "detail": …}`. Es lo que usa la interfaz.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `file` | `File` | Archivo `.pdf` o `.txt` |

**Respuesta exitosa (200):** `{ filename, questions, answer_key, was_reformatted }`
**Respuesta de error (422):** `{"detail": {"message": "...", "errors": [...]}}` — incluye, entre otros casos, cuando el documento no parece ser una prueba/examen real.

### `POST /api/generate_xml`

Recibe las preguntas (ya editadas o no) y genera el archivo Moodle XML final.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `filename`, `category`, `total_points` | — | Metadatos del examen |
| `questions`, `answer_key` | — | Mismo formato devuelto por `/api/parse` |

**Respuesta exitosa:** descarga del archivo `.xml`, con el header `X-Question-Stats` (JSON con conteo por tipo de pregunta y puntajes calculados).

### `GET /api/history`

Devuelve los últimos 50 exámenes convertidos (sin el contenido del XML, solo metadatos).

### `GET /api/history/{record_id}/download`

Vuelve a descargar el XML de una conversión anterior guardada en el historial.

---

## Dependencias

```
fastapi==0.115.12
uvicorn[standard]==0.34.2
python-multipart==0.0.20
pdfplumber==0.11.6
lxml>=5.3.2
pydantic>=2.11.3
google-generativeai==0.8.3
```

Además, para la app de escritorio: `pywebview` (no incluida en `requirements.txt` porque no hace falta para correr solo el backend).

---

## Módulo de prefiltro de IA

El sistema utiliza **Gemini 3.1 Flash Lite** para normalizar la estructura de los documentos — nunca para resolver ni inventar respuestas.

```
PDF/TXT → Extracción (texto + color + tablas) → [GEMINI] → Parser / Adaptador JSON
        → Marcas resueltas en código → Validador → Editor → XML Builder → Moodle XML
```

**Las marcas del PDF se leen, no se adivinan.** En un PDF digital, `extract_text()` pierde justo las marcas de respuesta más comunes: el color de una opción, el resaltado, el subrayado, la negrita y la columna de la "X" en un cuadro de marcas. Sin ellas el modelo tiende a *resolver* la pregunta con su propio conocimiento. Por eso:

- el texto que recibe el modelo lleva esas marcas anotadas (`⟦rojo⟧Lista (list)⟦/rojo⟧`, `⟦resaltado⟧…`, `⟦subrayado⟧…`, `⟦negrita⟧…`) y las tablas con su estructura (`| Evento | … | x |`);
- después, `mark_resolver.py` decide en código las respuestas marcadas. El modelo solo estructura (qué es enunciado, qué es opción).

**Progreso en vivo.** La llamada a Gemini se hace por streaming (SSE) y el backend va informando al navegador cuántas preguntas lleva procesadas (`/api/parse_stream`, `/api/normalize_with_ai_stream`), así la pantalla de carga muestra "12 de ~40 preguntas procesadas" y el tiempo restante real.

Se controla con variables de entorno (o un archivo `.env`):

| Variable | Por defecto | Qué hace |
|---|---|---|
| `GEMINI_API_KEY` | — | Key de Google AI Studio (ver `.env.example`) |
| `ENRICH_PDF_TEXT` | `1` | Marcas (color, resaltado, subrayado, negrita, tablas) en el texto + resueltas en código |
| `NORMALIZER_MODE` | `json` | Carga normal. `json`: la IA devuelve JSON con esquema (más fiel; un examen de 55 preguntas tarda hasta ~1,5 min). `text`: formato de texto propio (2-5× más rápido) |
| `NORMALIZER_MODE_AI` | `text` | Botón "Normalizar con IA" (escaneados), donde el modo texto midió mejor |

| Caso | Acción |
|------|--------|
| El documento **ya tiene** el formato estándar | Gemini retorna el texto sin cambios significativos |
| El documento **no tiene** el formato estándar | Gemini reformatea **solo la estructura**, conservando preguntas y respuestas tal cual están |
| El documento **no es una prueba real** (presentación, manual, artículo, apuntes, etc.) | Gemini responde con un centinela interno (`NO_ES_UNA_PRUEBA`); el backend lo detecta y responde `422` sin generar ninguna pregunta |
| Una pregunta **no tiene respuesta marcada** en el original | Se marca `SIN_RESPUESTA` — el sistema bloquea el XML en vez de adivinar |
| La API de Gemini **no está disponible** | Reintenta 3 veces (10s de espera entre intentos) antes de devolver error; una llamada colgada se corta (180 s en modo texto, 300 s en JSON) |
| Se alcanzó el **límite de peticiones por minuto** (429) | Espera el tiempo que indica Google y reintenta |

---

> **Nota de privacidad:** El procesamiento del documento (extracción, parseo, generación del XML) ocurre localmente. El prefiltro de IA solo envía el texto ya extraído a la API de Google, únicamente para normalizar su estructura — nunca las respuestas correctas por separado, ni ningún otro dato.

---

## Solución de problemas

### El instalador de Windows se queda pegado en la pantalla de carga

El `.exe` compilado con PyInstaller usa `--noconsole`, así que si el
backend (uvicorn) falla al arrancar, la app no muestra ningún error —
simplemente se queda en la splash para siempre. Desde esta versión,
`launcher.py` escribe cualquier fallo del backend en un archivo
`launcher_error.log`, creado junto al `.exe` (dentro de la carpeta
donde quedó instalada la app). Si te pasa, revisa ese archivo primero.

La causa más común: un módulo que usa `backend/` (fastapi, uvicorn,
sqlite3, etc.) no quedó incluido en el `.exe`. Como PyInstaller trata
la carpeta `backend/` como datos copiados tal cual (vía `--add-data`)
y no como código que analiza, no detecta automáticamente sus imports
— hay que declararlos a mano con `--hidden-import` en
[`ejecutable/build.py`](ejecutable/build.py) y volver a compilar. Ver
[`ejecutable/LEEME_WINDOWS.txt`](ejecutable/LEEME_WINDOWS.txt) para más detalle.

---

## Créditos

Desarrollado por **César González** y **Vicente Urriola**.
