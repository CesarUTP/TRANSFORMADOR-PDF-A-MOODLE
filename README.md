# PDF → Moodle XML

Convierte exámenes en PDF o TXT al **Moodle XML Question Format** con un backend FastAPI y una interfaz web moderna.

---

## Estructura del proyecto

```
pdf-to-moodle/
├── backend/
│   ├── main.py          ← API FastAPI (endpoints)
│   ├── extractor.py     ← Extracción de texto (.pdf / .txt)
│   ├── formatter.py     ← Prefiltro Gemini (normalización de estructura)
│   ├── parser.py        ← Parseo dinámico de preguntas y clave de respuestas
│   ├── xml_builder.py   ← Generación del XML Moodle
│   ├── models.py        ← Modelos Pydantic
│   └── requirements.txt ← Dependencias Python
└── frontend/
    └── index.html       ← Interfaz web (HTML + Vanilla JS + Tailwind CSS)
```

---

## Instalación y uso

### 1. Crear el entorno virtual

```bash
cd pdf-to-moodle/backend
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
```

### 4. Iniciar el backend

```bash
uvicorn main:app --reload --port 8000
```

El API quedará disponible en `http://localhost:8000`.  
Documentación interactiva Swagger: `http://localhost:8000/docs`.

### 5. Abrir el frontend

Abre `frontend/index.html` directamente en tu navegador, o usa la extensión **Live Server** de VS Code.

---

## Formato esperado del PDF / TXT

El documento debe tener la siguiente estructura:

```
Pregunta 1:
¿Cuál es la definición de interfaz de usuario?
A. El espacio de contacto entre usuario y sistema
B. Un componente de software únicamente
C. Un protocolo de red
D. Una base de datos relacional

Pregunta 2:
...

RESPUESTAS
Nº  Tipo          Respuesta correcta
1   multichoice   El espacio de contacto entre usuario y sistema
2   truefalse     Verdadero
3   matching      1. Concepto → Definición; 2. ...
4   cloze         Opción correcta
```

### Tipos de pregunta soportados

| Tipo | Formato en RESPUESTAS |
|------|----------------------|
| `multichoice` | Texto completo de la opción correcta |
| `truefalse` | `Verdadero` o `Falso` |
| `matching` | `1. ColA → ColB; 2. ColA → ColB; ...` |
| `cloze` | Texto de la opción correcta del espacio |

Las preguntas de tipo **cloze** usan corchetes en el cuerpo: `[A: opción1 / opción2 / opción3]`.

---

## Endpoint de la API

### `POST /convert`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `file` | `File` | Archivo `.pdf` o `.txt` |
| `category` | `string` | Nombre de la categoría Moodle (default: `mis-preguntas`) |

**Respuesta exitosa:** Descarga del archivo `.xml` con headers:
- `X-Question-Stats` — JSON con conteo por tipo de pregunta y puntajes.
- `X-Was-Reformatted` — `"true"` si Gemini normalizó el documento, `"false"` si ya tenía formato correcto.

**Respuesta de error:** JSON `{"detail": "mensaje descriptivo"}` con código HTTP 400 o 422.

---

## Dependencias

```
fastapi==0.115.12
uvicorn[standard]==0.34.2
python-multipart==0.0.20
pdfplumber==0.11.6
lxml==5.3.2
pydantic==2.11.3
google-generativeai==0.8.3
```

---

## Módulo de Prefiltro Gemini

El sistema utiliza **Gemini 3.1 Flash Lite** (`gemini-3.1-flash-lite-preview`) para normalizar la estructura de los documentos antes del parsing.

### Flujo con prefiltro

```
PDF/TXT → Extracción de texto → [GEMINI PREFILTRO] → Parser Regex → XML Builder → Moodle XML
```

### Comportamiento

| Caso | Acción |
|------|--------|
| El documento **ya tiene** el formato estándar | Gemini retorna el texto con cambios mínimos |
| El documento **no tiene** el formato estándar | Gemini reformatea **solo la estructura**, conservando preguntas y respuestas |
| La API de Gemini **no está disponible** | Retorna HTTP 503 tras 3 reintentos con espera de 10s entre cada uno |

Cuando Gemini normalizó el documento, la interfaz muestra un aviso en amarillo informando al usuario.

---

> **Nota:** El procesamiento del documento es local.  
> El prefiltro Gemini solo envía el texto extraído a la API de Google para normalizar su estructura.
