# Resultados de la evaluación de la normalización

Set: 10 exámenes sintéticos (256 preguntas, verdad exacta por construcción)
y 5 documentos reales (153 preguntas). Cada documento se procesa 3 veces.
**Exactitud** = preguntas que llegan al editor con el tipo, el enunciado
completo y la respuesta correctos, sobre las esperadas. Ver cómo se mide en
`dev/eval.py` y el formato del golden en `samples/golden/README.md`.

Reproducir la comparación:

```bash
backend/venv/bin/python dev/compare.py \
  dev/eval_results/20260918_1904_text_base.json \
  dev/eval_results/20260918_2011_text_enrich_fase3_texto.json \
  dev/eval_results/20260918_2003_json_enrich_fase3.json
```

## Resumen

| | Base (modo texto) | Texto + enriquecido **(por defecto)** | JSON + enriquecido |
|---|---|---|---|
| Sintéticos | 87 % | 98 % | 99–100 % |
| Reales | 96 % | 95 % | 96 % |
| Varianza entre corridas | sí | no | no |
| Tiempo de IA por documento | 35 s¹ | 6 s | 21 s |
| Tokens de salida por documento | 1 531 | 1 917 | 5 845 |

¹ La base incluye llamadas que quedaban colgadas del lado de Google
(~700 s); desde el commit de las fases 2-3 hay un timeout de 180 s.

## Por documento

| Documento | Qué prueba | Base | Texto+enr. | JSON+enr. |
|---|---|---|---|---|
| s01 clave al final | 7 tipos, clave con respuestas "incorrectas" a propósito | 90 % | 100 % | 100 % |
| s02 color sin imágenes | respuestas marcadas solo en rojo, títulos en azul | 25 % | 100 % | 100 % |
| s03 enunciado con lista A./B. | enunciados que traen su propia lista rotulada | 25 % | 25 % | **100 %** |
| s04 tabla de marcas | una X por fila (y una fila "contraintuitiva") | 0 %² | 100 % | 100 % |
| s05 60 preguntas | documento largo | 100 % | 100 % | 100 % |
| s06 escaneado | sin capa de texto (camino "Normalizar con IA") | 100 % | 100 % | 90 % |
| s07 no es examen | debe rechazarse | 100 % | 100 % | 100 % |
| s08 asterisco y sin marca | 2 preguntas sin respuesta: no inventar | 100 % | 100 % | 100 % |
| s09 completar + banco | banco de palabras sin clave: no inventar | 80 % | 80 % | **100 %** |
| s10 150 preguntas | techo de tamaño | 100 % | 100 % | 100 % |
| real Parcial 1 2026 1S | 55 preguntas, clave por letra | 100 % | 100 % | 100 % |
| real Computación ³ | marcas en rojo, código en imágenes, tabla | 80 % | 79 % | 82 % |
| real Historia/Geografía | 7 tipos, clave al final | 100 % | 100 % | 100 % |
| real parcial n.1 | 40 preguntas, clave con justificación | 100 % | 100 % | 100 % |
| real test tipos nuevos (.txt) | formato canónico | 100 % | 100 % | 100 % |

² Rechazado antes de llegar a la IA por la pre-validación (exigía la
palabra "respuesta"); corregido en la fase 1.
³ Golden revisado por Claude contra el PDF (color e imágenes), pendiente
de confirmación humana. Lo que falta en los tres modos son enunciados que
son código dentro de una imagen y un par de preguntas abiertas sin
opciones.

## Qué aprendimos

1. **El modelo resuelve en vez de transcribir** cuando no ve la marca, e
   incluso cuando la ve. Con una clave que dice "Saturno" como planeta más
   grande, devolvía "Júpiter". Por eso el set usa claves contrafácticas: con
   claves correctas el modelo acierta igual resolviendo y el problema no se
   ve.
2. **Lo que se puede decidir sin el modelo, no se le deja al modelo.** En
   un PDF digital el color y la celda de cada X son datos exactos.
   `mark_resolver.py` decide esas respuestas en código, y `clave_texto`
   (modo JSON) hace que el modelo solo copie la clave, que la resuelve el
   código. Esa es la mayor parte de la mejora.
3. **El formato JSON corrige dos errores silenciosos** que el modo texto
   mantiene incluso con todo lo demás: enunciados cortados por su propia
   lista A./B. (s03) y respuestas inventadas desde un banco de palabras
   (s09). Cuesta ~3.5× más tiempo. Queda disponible
   (`NORMALIZER_MODE=json`) y desactivado.
4. **No hizo falta procesar por páginas** (fase 4): 150 preguntas usan 25k
   de 65k tokens de salida sin omitir ninguna, y partir el documento
   separaría las preguntas de una clave que está al final. El reintento de
   calidad no se disparó ni una vez en 132 corridas.
5. **No conviene el PDF nativo para escaneados** (fase 5): 41 % menos
   tokens, pero 75 s contra ~9 s, y el camino actual acierta el 100 % de
   la muestra. Límite conocido: el camino actual solo lee las primeras 15
   páginas (`MAX_IMAGE_PAGES`).

## Configuración actual (después de esta evaluación)

Tras ver los tiempos, se priorizó la fidelidad: un examen de 55 preguntas
tarda hasta ~95 s en JSON, frente a horas de carga manual. Quedó así:

- **Carga normal: JSON** (`NORMALIZER_MODE=json`).
- **"Normalizar con IA" (escaneados): texto** (`NORMALIZER_MODE_AI=text`),
  que ahí midió 100 % contra 90 %.
- **Marcas nuevas:** resaltado, subrayado y negrita se leen igual que el
  color. Los sintéticos s11-s13 usan claves contrafácticas. Probado sin
  llamar a la IA: `mark_resolver` recupera 5/5 respuestas en cada uno y
  8/8 en el de color.
- **Modo texto:** el lector toma el ÚLTIMO bloque A./B./C. como opciones
  (arregla s03 también en texto).
- **Progreso en vivo** por streaming: la pantalla muestra "12 de ~40
  preguntas procesadas" y el tiempo restante real.

**Pendiente:** la evaluación completa de esta configuración se cortó
porque se agotó la cuota diaria del plan gratuito (ver abajo). Cuando se
restablezca, correr:

```bash
backend/venv/bin/python dev/eval.py --tag final
backend/venv/bin/python dev/eval.py --mode text --only s03 s11 s12 s13 --tag final_texto
```

y agregar la columna al resumen de arriba.

## Plan gratuito de Gemini

La key actual está en el plan gratuito:

- **15 peticiones por minuto.** La evaluación se autolimita a 13/min
  (`GEMINI_MAX_RPM`), así que una corrida completa (~55 procesamientos)
  tarda ~20-30 minutos.
- **500 peticiones por día y por modelo.** Para un docente alcanza de
  sobra: son 500 exámenes por día. Pero ~8 evaluaciones completas en un
  día lo agotan. Se restablece a medianoche (hora del Pacífico). Cuando se
  agota, la app ahora lo avisa al instante en vez de reintentar durante
  ~5 minutos.
