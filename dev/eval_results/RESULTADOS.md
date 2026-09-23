# Resultados de la evaluación de la normalización

Set: 13 exámenes sintéticos (271 preguntas, verdad exacta por construcción;
s11-s13 se agregaron para la corrida final) y 5 documentos reales (153
preguntas). Cada documento se procesa 3 veces.
**Exactitud** = preguntas que llegan al editor con el tipo, el enunciado
completo y la respuesta correctos, sobre las esperadas. Ver cómo se mide en
`dev/eval.py` y el formato del golden en `samples/golden/README.md`.

Reproducir la comparación:

```bash
backend/venv/bin/python dev/compare.py \
  dev/eval_results/20260918_1904_text_base.json \
  dev/eval_results/20260918_2011_text_enrich_fase3_texto.json \
  dev/eval_results/20260918_2003_json_enrich_fase3.json \
  dev/eval_results/20260919_1435_json_enrich_final_combinado.json
```

## Resumen

| | Base (modo texto) | Texto + enriquecido | JSON + enriquecido | **Final (configuración actual)** |
|---|---|---|---|---|
| Sintéticos | 87 % | 98 % | 99–100 % | **100 %** (271/271) |
| Reales | 96 % | 95 % | 96 % | **96 %** (147/153) |
| Varianza entre corridas | sí | no | no | no |
| Tiempo de IA por documento | 35 s¹ | 6 s | 21 s | 23 s⁴ |
| Tokens de salida por documento | 1 531 | 1 917 | 5 845 | 4 333 |

¹ La base incluye llamadas que quedaban colgadas del lado de Google
(~700 s); desde el commit de las fases 2-3 hay un timeout de 180 s.
⁴ El 19/09 Google tuvo el modelo saturado ("high demand", 503) durante
toda la corrida; varios tiempos incluyen esas esperas (s04 y s11 ~55 s,
contra ~5 s con el servicio normal).

## Por documento

| Documento | Qué prueba | Base | Texto+enr. | JSON+enr. | **Final** |
|---|---|---|---|---|---|
| s01 clave al final | 7 tipos, clave con respuestas "incorrectas" a propósito | 90 % | 100 % | 100 % | 100 % |
| s02 color sin imágenes | respuestas marcadas solo en rojo, títulos en azul | 25 % | 100 % | 100 % | 100 % |
| s03 enunciado con lista A./B. | enunciados que traen su propia lista rotulada | 25 % | 25 % | **100 %** | 100 % |
| s04 tabla de marcas | una X por fila (y una fila "contraintuitiva") | 0 %² | 100 % | 100 % | 100 % |
| s05 60 preguntas | documento largo | 100 % | 100 % | 100 % | 100 % |
| s06 escaneado | sin capa de texto (camino "Normalizar con IA") | 100 % | 100 % | 90 % | 100 % |
| s07 no es examen | debe rechazarse | 100 % | 100 % | 100 % | 100 % |
| s08 asterisco y sin marca | 2 preguntas sin respuesta: no inventar | 100 % | 100 % | 100 % | 100 % |
| s09 completar + banco | banco de palabras sin clave: no inventar | 80 % | 80 % | **100 %** | 100 % |
| s10 150 preguntas | techo de tamaño | 100 % | 100 % | 100 % | 100 % |
| real Parcial 1 2026 1S | 55 preguntas, clave por letra | 100 % | 100 % | 100 % | 100 % |
| real Computación ³ | marcas en rojo, código en imágenes, tabla | 80 % | 79 % | 82 % | 82 % |
| real Historia/Geografía | 7 tipos, clave al final | 100 % | 100 % | 100 % | 100 % |
| real parcial n.1 | 40 preguntas, clave con justificación | 100 % | 100 % | 100 % | 100 % |
| real test tipos nuevos (.txt) | formato canónico | 100 % | 100 % | 100 % | 100 % |
| s11 resaltado | respuesta solo resaltada, clave contrafáctica | — | — | — | 100 % |
| s12 negrita | respuesta solo en negrita, clave contrafáctica | — | — | — | 100 % |
| s13 subrayado | respuesta solo subrayada, clave contrafáctica | — | — | — | 100 % |

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
   (s09). Cuesta ~3.5× más tiempo. Tras la
   evaluación se adoptó como modo por defecto (ver abajo).
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

### Corrida final (19/09)

- **Carga normal (JSON):** 100 % en sintéticos y 96 % en reales. Lo único
  que falta es Computación (82 %): enunciados que son código dentro de
  una imagen, igual que en todas las configuraciones.
- **Modo texto** en s03, s11, s12 y s13: 100 % en los cuatro. s03 pasó de
  25 % a 100 % con el arreglo del lector.
- **Google saturado:** en la corrida original, s05 y el parcial de 55
  preguntas fallaron por 503 "high demand" de Google y por respuestas
  cortadas a mitad del stream. Con los reintentos agregados después
  (esperas de 5, 10, 20 y 30 s, detección del stream cortado y aviso en
  pantalla) se repitieron: 6 de 6 corridas correctas y 100 % en ambos.
  La tabla usa esa repetición
  (`20260919_1435_json_enrich_final_combinado.json`).

Archivos: `20260919_1433_json_enrich_final.json` (corrida original),
`20260919_1435_json_enrich_final_largos.json` (repetición de los largos) y
`20260919_1435_text_enrich_final_texto.json` (modo texto).

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

---

## Pruebas adversariales (20/09)

Doce exámenes sintéticos de 30 a 50 preguntas (**477 en total**), cada uno
diseñado para romper una parte distinta del sistema. Se generan con
`dev/synthetic/generate_adversarial.py` (verdad exacta por construcción) y
**no forman parte de la corrida por defecto** de `dev/eval.py`, para no mover
la línea base de los 18 originales: se corren con `--only x` o `--adversarial`.
Configuración: la actual (JSON + marcas en código), 3 corridas por documento.
En todos los que tienen clave o marcas, ~25 % de las preguntas de opción
múltiple y V/F llevan una respuesta **contrafáctica** (el documento marca algo
que no es lo real): el sistema debe transcribirla, no corregirla.

| Documento | Qué ataca | Preg. | Exactitud | Rango | IA (s) |
|---|---|---:|---:|---:|---:|
| x01 numeración caótica | numeración repetida/salteada, opciones numeradas, preguntas sin número | 40 | 95,0 % | 95–95 | 22 |
| x02 opciones heterogéneas | 10 estilos de rótulo, 6 opciones, "todas las anteriores", opciones-símbolo | 45 | **100 %** | 100–100 | 24 |
| x03 claves heterogéneas | clave final en 3 formatos distintos, 7 tipos | 40 | 98,3 % | 95–100 | 19 |
| x04 marcas distractoras | rojo/azul/negrita como distractores; 3 preguntas con TODAS las opciones en rojo | 40 | 92,5 % | 92,5–92,5 | 21 |
| x05 dos columnas | el texto extraído mezcla ambas columnas | 40 | **100 %** | 100–100 | 48 |
| x06 ruido documental | encabezado/pie, marca de agua girada, instrucciones numeradas, pasaje de lectura | 48 | **100 %** | 100–100 | 24 |
| x07 abiertas y numéricas | ensayo/corta/numérica, coma decimal, número en palabras, unidades | 50 | 90,0 % | 90–90 | 21 |
| x08 caracteres especiales | `& < > ]]> ~ # { } \ \|`, `/` dentro de opciones Cloze, Unicode | 36 | 91,7 % | 91,7–91,7 | 24 |
| x09 emparejamiento y Cloze | 4 variantes de rotulado, distractores, Cloze de 3 huecos y banco compartido | 36 | 91,7 % | 91,7–91,7 | 24 |
| x10 escaneado degradado | imagen pura, 100 dpi, JPEG q=40, giro, ruido; marcas solo en rojo | 32 | **71,9 %** | 71,9–71,9 | 9 |
| x11 código en imagen | el código solo existe como imagen | 30 | 93,3 % | 80–100 | 19 |
| x12 clave parcial | ~55 % de las autocalificables sin respuesta (no inventar) | 40 | 85,0 % | 85–85 | 20 |
| **Total** | | **477** | **92,9 %** (443,3/477) | | 22,9 medio |

Con 2 falsos negativos del evaluador descontados (ver F): **93,4 %**.
Comparación: 100 % en los sintéticos originales y 96 % en los reales.

### Qué falló, y por qué (promedio por corrida; 33,7 preguntas)

| Causa | Preg. | Dónde | Naturaleza |
|---|---:|---|---|
| A. El modelo "corrige" la clave del documento con su conocimiento | 10,7 | x10 (8,7), x01 (2) | **Fallo del sistema**: transcribir vs. resolver |
| B. Inventa una respuesta que el documento no da | 7,0 | x12 (4), x04 (3) | **Fallo del sistema** |
| C. Numérica con número en palabras o con unidad → omitida | 4,7 | x07 | Diseño: el validador exige un número. Es **recuperable** en el editor |
| D. Cloze de un hueco reinterpretado como respuesta corta / opción múltiple | 5,7 | x09 (3), x08 (2), x03 (0,7) | Ambigüedad de tipo; la respuesta sale bien pero pierde las opciones |
| E. Código de la imagen no transcrito al enunciado | 2,0 | x11 (1 corrida de 3) | Variabilidad del modelo |
| F. Omitida correctamente pero no emparejada por el evaluador | 2,0 | x12 | **Artefacto del evaluador** (no es un fallo del sistema) |
| G. Opción `\|` como respuesta correcta perdida | 1,0 | x08 | **Fallo del código** (ver "Fidelidad del XML") |

**A — claves contrafácticas.** En PDFs con capa de texto el sistema respetó la
marca del documento en 56 de 58 preguntas contrafácticas (96,6 %); las 2
restantes son V/F marcados con `( X )` en x01, donde no hay resolvedor en
código (solo lo hay para opción múltiple y tablas). En el **escaneado (x10) respetó 0 de 9**: el
modelo devolvió la respuesta real en 8,7 de 9. En un escaneado no hay capa de
texto, así que ni `mark_resolver` ni el aviso "revisar marca" actúan.

**B — no inventar.** x04: con las 4 opciones en rojo el modelo marcó las 4
como correctas (la marca no discrimina, y su propio prompt lo dice).
x12: los 4 emparejamientos sin clave salieron con todos sus pares correctos
*del mundo real* aunque el documento no los indicaba (el esquema JSON pide
`parejas` y el modelo las resuelve). En cambio los V/F, numéricas, respuestas
cortas, Cloze y opción múltiple sin respuesta se omitieron bien (16 omitidas).

### Fidelidad del XML con una IA perfecta (`dev/xml_fidelity.py`, sin API)

Se toma la verdad de los 12 exámenes, se convierte en la respuesta JSON que
daría un modelo perfecto, se pasa por adaptador → validador → generador, y se
**lee de vuelta el XML como lo haría Moodle**. Resultado: **473 de 477**
preguntas fieles; las 20 sin respuesta de x12 y las 3 de todo-rojo de x04
se omiten como corresponde. Los 4 fallos son todos de x08 y **no dependen del
modelo**:

1. Opción `|` como correcta: `xml_builder` separa la clave por `|` (multi-respuesta),
   queda vacía y **marca la opción A** con solo un `logger.warning`; el validador
   la deja pasar. Respuesta equivocada en silencio.
2. Cloze con `/` en una opción (`km/h`, `TCP/IP`, `HTTP/2`): el formato interno usa
   `/` como separador y `km/h` se parte en dos opciones (`{1:MULTICHOICE_S:=km~h~…}`).
   Pasa la validación.
3. Cloze con opciones que empiezan por `=` (`==`, `=`): choca con el marcador de
   respuesta correcta de Moodle y se marcan dos opciones como correctas.

Además, `strip_accents` quita las tildes de **todas** las opciones Cloze
(15 preguntas de este set: `París` → `Paris`). Es deliberado, pero cambia el texto
que ve el estudiante y conviene declararlo.

No verificado: los decimales con coma (`9,75`) se escriben tal cual en
`<answer>` de las numéricas; no se probó cómo los importa Moodle.

### Límites de esta prueba

- Los documentos los diseñó y generó el mismo equipo que el sistema; miden
  robustez ante fallos anticipados, no generalización a documentos reales nuevos.
- Una sola configuración y modelo; 3 corridas (casi sin varianza: solo x03 y x11
  variaron).
- Se corrigió un artefacto propio antes de cerrar: la letra π no existe en la
  fuente estándar (Helvetica) y salía como `p` en x01, x05 y x06; se cambió a
  "pi" y esos tres se repitieron (`..._rerun_pi.json`). Los resultados de la
  tabla usan esa repetición (`..._adversarial_combinado.json`).
- 2 fallos del evaluador (F): `eval.py` empareja las preguntas omitidas por un
  extracto de 160 caracteres y pierde algunos Cloze.
- En la primera llamada de humo una respuesta de Google se colgó 300 s y el
  reintento la recuperó (332 s en total); no se repitió en la corrida completa.

Reproducir:

```bash
backend/venv/bin/python dev/synthetic/generate_adversarial.py
backend/venv/bin/python dev/eval.py --only x --runs 3
backend/venv/bin/python dev/xml_fidelity.py
```

Archivos: `20260920_1320_json_enrich_adversarial.json` (corrida completa),
`20260920_1326_json_enrich_adversarial_rerun_pi.json` (x01, x05, x06),
`20260920_1326_json_enrich_adversarial_combinado.json` (los usados en la tabla),
`xml_fidelidad_adversarial.json`.

### Después de las correcciones (20/09)

Se corrigieron los fallos del sistema hallados arriba y se volvió a correr todo
con el código nuevo (3 corridas por documento). El código ya no tiene los
cuatro errores de la etapa de XML: con una IA perfecta, **477 de 477**
preguntas salen fieles (antes 473; `dev/xml_fidelity.py`).

**Qué se cambió**

| Fallo | Corrección | Dónde |
|---|---|---|
| Opción `\|` como correcta se perdía y el XML marcaba la A | El separador de varias respuestas pasa a ser `" \| "` con espacios (`split_answers`): `\|` solo es texto | `answer_matching.py`, `xml_builder.py`, `validator.py`, `schema_adapter.py`, `util.js`, `cloze.js`, `tarjetas.js` |
| Cloze con `/` en una opción (`km/h`, `TCP/IP`) se partía | Igual con `" / "` entre opciones (`split_options`); además se escapa `/` y `"` en el Cloze, como exige la documentación de Moodle (`} # ~ / " \`) | idem |
| Opción incorrecta que empieza por `=` marcaba dos correctas | Se escribe con `%0%` (fracción explícita 0 %, sintaxis de Moodle) | `xml_builder.py` |
| Apóstrofo en un Cloze cortaba la opción (nuevo, no estaba en el set) | `&#x27;` contenía un `#` (separador de retroalimentación): el texto del Cloze ya no convierte comillas en entidades | `xml_builder.py` |
| Todas las opciones marcadas salían como correctas (x04) | Sin clave explícita, "todas marcadas" queda sin respuesta y se omite | `schema_adapter.py` |
| Emparejamiento sin clave salía resuelto por el modelo (x12) | El adaptador respeta `respuesta_marcada=false`; la clave compacta y las tablas de marcas siguen valiendo | `schema_adapter.py` |
| V/F con `( X ) Verdadero` lo decidía el modelo (x01) | Nuevo `resolve_tf_marks`: casilla marcada o palabra en color/resaltado; no se aplica si el mismo estilo aparece en todas | `mark_resolver.py`, `pipeline.py` |
| Escaneado: el modelo "corrige" la clave y nada avisaba | Aviso explícito en el editor cuando el PDF no tiene capa de texto | `pipeline.py` |

Además: el evaluador (`dev/eval.py`) separaba por `|` a secas y daba como
"respuesta None" la opción `|` aunque el sistema ya la leyera bien; se
corrigió. Regresión sin API: `dev/test_casos_borde.py` (12 casos) y 3 pruebas
nuevas en `frontend/pruebas.html`. Las copias de `ejecutable/` y
`ejecutable_mac/` se sincronizaron.

**Resultado, antes → después**

| Documento | Antes | Después |
|---|---:|---:|
| x01 numeración caótica | 95,0 % | **100 %** |
| x02 opciones heterogéneas | 100 % | 100 % |
| x03 claves heterogéneas | 98,3 % | **100 %** |
| x04 marcas distractoras | 92,5 % | **100 %** |
| x05 dos columnas | 100 % | 100 % |
| x06 ruido documental | 100 % | 100 % |
| x07 abiertas y numéricas | 90,0 % | 90,0 % |
| x08 caracteres especiales | 91,7 % | 88,9 % |
| x09 emparejamiento y Cloze | 91,7 % | 91,7 % |
| x10 escaneado degradado | 71,9 % | 71,9 % |
| x11 código en imagen | 93,3 % | 80,0 % |
| x12 clave parcial | 85,0 % | **96,7 %** |
| **Total** | **92,9 %** (443,3/477) | **94,1 %** (448,7/477) |

Con los 2 falsos negativos del evaluador en x12 descontados: 94,5 %.
Regresión de los 18 originales con el código nuevo (1 corrida): **100 % en
los 271 sintéticos y 96 % en los 153 reales**, idéntico al resultado anterior.

Fallos por causa (promedio por corrida): **inventar respuestas 7,0 → 0**;
el modelo "corrige" la clave 11,7 → 8,3 (solo queda el escaneado); Cloze
reinterpretado 5,7 → 7,0; código no transcrito 2,0 → 6,0.

**Lo que NO mejoró, y por qué**

- **x10 (escaneado) sigue en 71,9 %.** El aviso informa al docente, pero el
  modelo sigue devolviendo lo que cree correcto en lugar de la marca en rojo
  (8,7 de 9 preguntas contrafácticas). Se probó el modo JSON para escaneados
  (`NORMALIZER_MODE_AI=json`): x10 69 % y s06 90 % (con texto: 72 % y 100 %),
  así que **no** se cambió el valor por defecto. La solución real (leer el
  color de la imagen en código, sin OCR no hay capa de texto) queda **fuera de
  alcance a propósito** (decisión del 21/09): el escaneado no es el fuerte de
  la app y el aviso al docente ya cubre el riesgo.
- **x08 y x11 empeoraron por variación del modelo, no del código.** En x08 el
  modelo etiquetó como respuesta corta entre 2 y 5 Cloze de un hueco (antes
  siempre 2); en x11 no copió el código de la imagen al enunciado de 6 V/F en
  las 3 corridas (antes, en 1 de 3). Los cambios de esta etapa solo tocan
  respuestas, no el texto que recibe el modelo ni sus enunciados. x11 es
  inestable entre sesiones (100/100/80 → 80/80/80): pooled, 86,7 %. Una
  mejora posible es reforzar en el prompt que "espacio en blanco con opciones
  entre paréntesis" es Cloze, pero cambiaría el prompt y exigiría repetir toda
  la regresión.
- **x07 (90 %)** son las numéricas con palabras o con unidad: siguen siendo
  una decisión de diseño (se omiten con motivo y se recuperan en el editor).
- **x09** conserva 3 Cloze reinterpretados como respuesta corta (2 con banco
  de palabras compartido, 1 con dos respuestas correctas).

**Riesgos que siguen sin verificarse**

- ~~No se importó ningún XML en una instancia real de Moodle~~ — **confirmado
  por César (21/09): los XML generados se importan bien en Moodle.**
- `strip_accents` sigue quitando las tildes de las opciones Cloze (decisión
  original, no error); los decimales con coma siguen escribiéndose tal cual.
- El evaluador se cierra con un fallo del intérprete (código 139) al renderizar
  escaneados en paralelo con `--workers 3` en modo JSON; con `--workers 1` no
  ocurre. Afecta solo a la herramienta de evaluación.

Archivos: `20260920_2100_json_enrich_adversarial_post_correcciones.json`
(los usados en la tabla), `*_adv_post_fix*.json` (corridas originales),
`*_regresion_post_fix.json` (18 originales), `*_exp_scan_json.json`
(experimento de escaneados).

### Marcas mezcladas y subrayado de Word (21/09)

**Subrayado no detectado.** En un PDF de Word (`PARCIAL N.pdf`, fuente Aptos) el
subrayado se dibuja sobre la línea base, ~3 pt *por encima* del borde inferior
del cuadro de la palabra, y el extractor solo aceptaba desde 1 pt por encima:
las opciones subrayadas llegaban al modelo sin ninguna marca. Ahora se acepta
hasta 4 pt por encima (tope en puntos, no proporcional: con un margen relativo,
el borde de una tabla que cruzaba las letras grandes de una marca de agua contaba
como subrayado). Comparado contra el extractor anterior en los 29 PDFs del
proyecto: solo cambia el PDF de la prueba.

**Marcas mezcladas.** `resolve_answer_marks` solo actuaba con UNA marca repetida en
≥ 2 preguntas y ≥ 30 % de las ubicadas. Un docente que subraya en una pregunta,
resalta en otra y pone negrita en la siguiente quedaba fuera y la respuesta la
decidía el modelo (sin la etiqueta "respuesta por marca"). Ahora, si la marca
dominante no alcanza, se prueban todas las marcas juntas (`mixta`) con los mismos
umbrales; dentro de una pregunta todas las opciones marcadas deben usar la misma
marca y no pueden estar marcadas todas.

| Comprobación | Lector anterior | Lector nuevo |
|---|---:|---:|
| x13 (40 preguntas, 4 marcas en rotación), IA que se equivoca a propósito en las 28 de opción múltiple | 0 / 28 | **28 / 28** |
| PARCIAL N.pdf (resaltado en P1, subrayado en P3), IA equivocada | — | 2 / 2 (`mixta`) |
| x13 con la IA real, 3 corridas | 100 % | 100 % |
| 27 documentos con PDF, respuestas resueltas por el lector | igual | igual (0 cambios) |
| Regresión, 18 originales (1 corrida) | 100 % / 96 % | 100 % / 96 % |
| Adversariales x01–x12 (1 corrida) | — | ningún documento peor que antes |

Lectura honesta: con el modelo actual el efecto **no se ve en la exactitud** (la IA
ya leía bien las marcas mezcladas: 40 de 40), sino en que las 28 respuestas ahora
salen del código —reproducibles, etiquetadas "por marca" y correctas aunque la IA
falle—. Riesgo conocido: en un examen muy corto (≈ 5 preguntas) dos marcas casuales
podrían contar como sistema de respuestas; con más preguntas lo evita el umbral del
30 %. La línea "Respuesta: X" escrita en texto (V/F y respuesta corta) sigue
decidiéndola el modelo.

Reproducir: `backend/venv/bin/python dev/eval.py --only x13_ --runs 3` y
`backend/venv/bin/python dev/test_casos_borde.py` (5 pruebas nuevas del lector y 2 del
subrayado). Archivos: `*_x13_lector_anterior.json`, `*_x13_lector_nuevo.json`,
`*_regresion_marcas_mixtas.json`, `*_adv_marcas_mixtas.json`.

### Cloze con código dentro de una opción (21/09)

Una opción de un espacio Cloze que contenga `]` (código: `arr[0]`, `matriz[i][j]`)
rompía el espacio a mitad de camino. El formato interno usa `[Letra: opción1 /
opción2]`, y `validator.py`, `xml_builder.py` y el constructor visual del
frontend (`cloze.js`) lo leían con una expresión regular que se detenía en el
**primer** `]` que encontraba — el de dentro de `arr[0]`, no el de cierre del
espacio — dejando el resto de las opciones como texto suelto y roto.

Ejemplo (con el código anterior):

```text
antes:  ¿Qué imprime arr[0] si arr = [A: [10, 20, 30] / 10 / arr[1]]?
        → {1:MULTICHOICE_S:=[10, 20, 30} / 10 / arr[1]]?     ← roto
después: {1:MULTICHOICE_S:[10, 20, 30]~=10~arr[1]}           ← correcto
```

**Corrección:** `find_cloze_brackets` (nuevo, en `answer_matching.py`, con su
gemelo `findClozeBrackets` en `util.js`) balancea los `[` y `]` internos en
vez de detenerse en el primero, así una opción con corchetes propios queda
completa. Sustituye la expresión regular en los tres lugares que la usaban.

Regresión (sin API, `dev/test_casos_borde.py`): opción de código en un solo
hueco, dos huecos con código cada uno sin mezclarse entre sí, y las 19 pruebas
anteriores siguen pasando. Con una IA perfecta (`dev/xml_fidelity.py`, 13
exámenes, 517 preguntas): **517/517 fieles**, sin cambios en los fallos ya
conocidos (tildes de `strip_accents`).

Reproducir: `backend/venv/bin/python dev/test_casos_borde.py` y
`backend/venv/bin/python dev/xml_fidelity.py`.

### Revisión de código completa: 10 hallazgos corregidos (22/09)

Con `/code-review --full --level high` sobre todo el proyecto (no solo el diff de la sesión): 6 ángulos de búsqueda, verificación uno por uno, 10 hallazgos confirmados o plausibles, corregidos todos.

| # | Archivo | Qué fallaba | Severidad |
|---|---|---|---|
| 1 | `xml_builder.py` | Opción múltiple con varias respuestas correctas: las incorrectas daban 0% en vez de negativo — marcar TODAS las opciones daba 100% de la nota | **Alta** (calificación real en Moodle) |
| 2 | `validacion.js` | El aviso "incompleta" en vivo del editor usaba la misma regex de corchetes que ya se había corregido en el backend — un Cloze con código (`arr[0]`) mostraba un estado distinto al real | Media |
| 3 | `historial.js` | Nombre de archivo insertado en `innerHTML` sin escapar, y en un atributo `onclick` sin escapar comillas dobles | Media (inyección de HTML/atributo) |
| 4 | `tarjetas.js` | Borrar una 2.ª pregunta sin otro render de por medio mezclaba metadatos (`color_review_hint`, `low_confidence`, `answer_from_marks`) entre preguntas distintas | Media |
| 5 | `main.py` | `/api/generate_xml` corría todo el trabajo pesado directo en el event loop de asyncio, a diferencia de `/api/parse` | Baja-media (retraso, no corrección) |
| 6 | `database.py` | Conexión SQLite sin `try/finally`: una excepción a mitad de escritura la dejaba sin cerrar | Baja (fuga de recursos) |
| 7 | `extractor.py` | Un bbox con `bottom < top` (página rotada) volvía negativo el margen del subrayado y desactivaba la detección en silencio | Baja (caso raro) |
| 8 | `mark_resolver.py` | Una opción cuyo texto es prefijo de otra (`"Estructura de datos abstracta"` / `"... compleja"`) podía "robarle" la línea y la marca de color a su vecina | Media |
| 9 | `schema_adapter.py` | La resolución de opciones sin rótulo por posición solo aceptaba letras; una clave numérica (`"2"`) no resolvía nada | Baja (caso raro) |
| 10 | `pipeline.py` | El mismo PDF se abría con pdfplumber 5 veces por separado en una sola petición | Eficiencia |

**Corrección #1 en detalle:** ahora la fracción de cada opción incorrecta es `-100/incorrectas`, de modo que marcar TODAS las opciones de una pregunta de varias respuestas da exactamente 0%, siguiendo la propia recomendación de la documentación de Moodle ("Multiple Choice question type"). Una sola respuesta correcta (radio) no cambia: sigue en 0% para las demás.

**Corrección #10 en detalle:** dos funciones nuevas en `extractor.py` (`extract_pages_enriched_and_tables`, `get_colored_pages`) fusionan en un solo `pdfplumber.open()` lo que antes eran 4 aperturas separadas del mismo archivo. Se verificó que producen exactamente el mismo resultado que las funciones originales en los 30 PDFs del proyecto antes de conectarlas en `pipeline.py`.

**Regresión:** 11 pruebas nuevas en `dev/test_casos_borde.py` (30 en total) y 3 en `frontend/pruebas.html` (26 en total, corridas en el navegador real). Cada una se probó primero contra el código SIN el arreglo para confirmar que de verdad falla ahí y pasa con el arreglo — no son pruebas vacuas. `dev/xml_fidelity.py`: 517/517 sin cambios. Regresión completa con la API real (1 corrida): 18 originales — **100 % sintéticos, 97 % reales** (148/153, dentro de la variación normal del modelo); 13 adversariales — **94 % (487/517)**, sin caídas respecto a la medición anterior (94,1 %).

Reproducir: `backend/venv/bin/python dev/test_casos_borde.py`, `backend/venv/bin/python dev/xml_fidelity.py`, y abrir `http://localhost:PUERTO/static/pruebas.html`. Archivos: `*_revision_10_fixes.json`, `*_revision_10_fixes_adv.json`.

## Comparación de modelos: 3.1-flash-lite vs 3.5-flash-lite (23/09/2026)

Ya en el plan de pago de Gemini (modalidad Estándar), mismo set y mismo
código; el modelo se elige con la variable `GEMINI_MODEL`.

| | gemini-3.1-flash-lite (actual) | gemini-3.5-flash-lite |
|---|---|---|
| Sintéticos | 100 % (271/271) | 100 % (271/271) |
| Reales sin `computacion` | 100 % | 100 % |
| `real_parcial_1_computacion` * (3 corridas) | 85 % | 90 % |
| Precio (entrada / salida por 1 M tokens) | $0.25 / $1.50 | $0.30 / $2.50 |
| Tiempo | referencia | ~10–15 % más lento |

**Decisión: se mantiene 3.1-flash-lite.** Empatan en todo lo verificado; la
única diferencia (< 2 preguntas en promedio) está en el documento cuyo
golden no se revisó a mano, así que no es concluyente. 3.5 cuesta ~50 % más
por examen y es algo más lento.

Archivos: `20260923_1057_json_enrich_diag.json` (3.1, 1 corrida),
`20260923_1058_json_enrich_comp31.json` (3.1, `computacion` ×3) y
`20260923_1051_json_enrich_pago_35lite.json` (3.5, 3 corridas).

Nota: con `--workers 3` la corrida de 3.1 se cerró dos veces de golpe
(código 133) tras el primer documento; con `--workers 1` corre completa.
Apunta a que el renderizado de PDF no tolera hilos en paralelo; queda por
investigar.
