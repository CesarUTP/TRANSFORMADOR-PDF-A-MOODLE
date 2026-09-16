# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Docentes (colegio, universidad o cualquier otro nivel educativo) que ya tienen un examen, quiz o prueba parcial redactado en PDF o TXT y necesitan subirlo al banco de preguntas de Moodle. Uso principal: el propio desarrollador y sus colegas — se distribuye como instalador nativo (Windows/macOS) precisamente para que otros docentes, sin conocimientos técnicos, puedan usarlo sin instalar Python ni nada manualmente.

## Product Purpose

Moodle no permite pegar un examen en formato "normal": cada pregunta debe cargarse a mano en el banco de preguntas, o construirse a mano en XML con una sintaxis estricta y poco intuitiva. Para un examen de 30-40 preguntas esto es lento y fácil de arruinar con un error de tipeo. Este sistema toma el examen tal como ya existe, lo interpreta (con ayuda de un prefiltro de IA cuando el formato es irregular) y genera directamente el archivo Moodle XML listo para importar. Éxito = un examen real, con su formato imperfecto típico, se convierte en un XML válido que Moodle acepta sin errores, en segundos en vez de horas.

## Positioning

A diferencia de un generador de preguntas por IA, este sistema nunca inventa ni resuelve una pregunta o respuesta que no esté ya en el documento original — solo transcribe y normaliza estructura. Su diferencial frente a cargar a mano es la validación estructural estricta (detecta, por ejemplo, que un par de emparejamiento no corresponda realmente a la respuesta correcta, no solo que "la cantidad cuadre") combinada con un editor de revisión donde el docente confirma cada pregunta antes de generar el XML final — nunca una caja negra que exporta a ciegas.

## Operating Context

El docente ya redactó el examen en un procesador de texto o lo tiene escaneado/impreso, con una clave de respuestas al final. Sube el archivo, el sistema normaliza estructura (con IA cuando hace falta) y presenta un editor con conteo por tipo de pregunta antes de exportar. El XML final se importa en Moodle vía *Banco de preguntas → Importar*. Corre como app de escritorio nativa (pywebview) para no exigir conocimientos técnicos al usuario final, aunque su interfaz es una página web servida por un backend FastAPI local.

## Capabilities and Constraints

- 7 tipos de pregunta Moodle: opción múltiple, verdadero/falso, emparejamiento, completar (Cloze), ensayo, respuesta corta y numérica.
- Prefiltro de IA (Gemini) solo normaliza estructura/formato; nunca inventa ni resuelve respuestas no indicadas en el original.
- Validación estricta antes de generar el XML: rechaza documentos que no sean realmente una evaluación, y separa preguntas válidas de preguntas omitidas con motivo explicado ("Modo Tolerante").
- Procesamiento 100% local salvo el texto ya extraído del examen, que se envía a la IA únicamente para normalizar su formato.
- Historial local de conversiones (SQLite) para volver a descargar exámenes ya procesados.
- Terminología del propio dominio Moodle: "banco de preguntas", "Cloze", "clave de respuestas", categoría y puntaje total del examen.

## Evidence on Hand

Ninguna evidencia externa formal (sin testimonios, casos de estudio ni métricas de uso reportadas) — proyecto en uso real por el desarrollador y colegas directos, sin marketing ni prueba pública que fabricar.

## Product Principles

1. Nunca inventar ni resolver contenido que no esté ya en el documento del usuario — la IA normaliza formato, no genera conocimiento.
2. Preferir rechazar o marcar una pregunta como omitida, con motivo claro, antes que arriesgar un XML importado silenciosamente incorrecto.
3. El docente revisa y aprueba cada pregunta antes de exportar — nunca un flujo de un solo clic sin inspección.
4. Cero fricción técnica para el usuario final: instalador nativo, sin configuración ni conocimientos de Moodle XML requeridos.
5. El procesamiento del documento se queda en el equipo del usuario; solo el texto extraído (nunca el archivo original) sale hacia la IA.
