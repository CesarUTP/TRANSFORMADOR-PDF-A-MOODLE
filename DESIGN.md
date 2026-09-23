---
name: Conversor a Moodle XML
description: Panel de conversión oscuro y preciso que transforma exámenes desordenados en Moodle XML validado.
colors:
  bg: "#090d16"
  bg-alt: "#0f172a"
  surface: "#131c31"
  surface-card: "#111a2e"
  surface-hover: "#1e293b"
  border: "rgba(255, 255, 255, 0.12)"
  border-subtle: "rgba(255, 255, 255, 0.06)"
  text: "#f8fafc"
  text-muted: "#94a3b8"
  text-subtle: "#8f9db0"
  primary: "#0369a1"
  primary-hover: "#0284c7"
  accent-senal: "#38bdf8"
  on-accent: "#06101f"
  cta: "#0369a1"
  cta-hover: "#075985"
  cta-success: "#047857"
  cta-success-hover: "#065f46"
  success: "#10b981"
  success-solid: "#0c855d"
  success-bg: "rgba(16, 185, 129, 0.12)"
  warning: "#f59e0b"
  warning-bg: "rgba(245, 158, 11, 0.12)"
  error: "#f43f5e"
  error-bg: "rgba(244, 63, 94, 0.12)"
  error-solid: "#be123c"
  tipo-multichoice: "#38bdf8"
  tipo-truefalse: "#34d399"
  tipo-matching: "#fbbf24"
  tipo-cloze: "#a78bfa"
  tipo-essay: "#f472b6"
  tipo-shortanswer: "#2dd4bf"
  tipo-numerical: "#fb923c"
typography:
  headline:
    fontFamily: "Outfit, Hanken Grotesk, system-ui, sans-serif"
    fontSize: "22px"
    fontWeight: 800
    lineHeight: 1.3
    letterSpacing: "-0.3px"
  title:
    fontFamily: "Outfit, Hanken Grotesk, system-ui, sans-serif"
    fontSize: "19px"
    fontWeight: 800
    lineHeight: 1.2
    letterSpacing: "-0.5px"
  body:
    fontFamily: "Hanken Grotesk, system-ui, -apple-system, sans-serif"
    fontSize: "14px"
    fontWeight: 500
    lineHeight: 1.6
    letterSpacing: "normal"
  label:
    fontFamily: "Hanken Grotesk, system-ui, -apple-system, sans-serif"
    fontSize: "11.5px"
    fontWeight: 800
    lineHeight: 1.3
    letterSpacing: "0.4px"
  large:
    fontFamily: "Hanken Grotesk, system-ui, -apple-system, sans-serif"
    fontSize: "16px"
    fontWeight: 700
    lineHeight: 1.4
  small:
    fontFamily: "Hanken Grotesk, system-ui, -apple-system, sans-serif"
    fontSize: "12.5px"
    fontWeight: 500
    lineHeight: 1.5
  mono:
    fontFamily: "JetBrains Mono, monospace"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.6
rounded:
  sm: "8px"
  md: "14px"
  lg: "20px"
  xl: "28px"
  full: "9999px"
spacing:
  xs: "6px"
  sm: "10px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.cta}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "12px 22px"
  button-primary-hover:
    backgroundColor: "{colors.cta-hover}"
  button-success:
    backgroundColor: "{colors.cta-success}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "12px 22px"
  button-ghost:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "12px 22px"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.text-muted}"
    rounded: "{rounded.md}"
    padding: "8px 12px"
  chip-filter:
    backgroundColor: "{colors.surface-hover}"
    textColor: "{colors.text-muted}"
    rounded: "{rounded.full}"
    padding: "6px 14px"
  input-field:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "12px 16px"
---

# Design System: Conversor a Moodle XML

## Overview

**Creative North Star: "El Laboratorio de Conversión"**

Este sistema es el instrumental de un laboratorio, no la vitrina de un producto: un examen desordenado entra, pasa por una secuencia de pasos visibles (subir → revisar → descargar) y sale como un XML validado. Todo el lenguaje visual sirve a ese proceso — fondo slate profundo por defecto para minimizar fatiga visual en sesiones largas de revisión de 30-40 preguntas, tipografía geométrica de alto contraste para escanear rápido, y un único acento (azul cian "Señal") reservado casi exclusivamente para lo que se puede accionar ahora mismo.

No es una landing page ni busca persuadir: es una herramienta de trabajo (modo Operar) para docentes sin conocimientos técnicos, así que la claridad y la previsibilidad superan a la expresión. El único lugar donde el sistema se permite color decorativo con intención propia es la paleta de 7 tipos de pregunta — cada tipo tiene su propio matiz para que un examen de cientos de preguntas se pueda escanear por color sin leer cada etiqueta.

Se rechazó explícitamente el vocabulario visual por defecto de "interfaz generada por IA": sin texto en degradado, sin halos de color (`box-shadow` sin desplazamiento), sin tipografías de IA sobreusadas (Plus Jakarta Sans, Inter, Space Grotesk), sin bordes de acento de más de 1px en callouts.

**Key Characteristics:**
- **Se abre siempre en modo claro** (`data-theme="light"`), sin importar el tema del sistema ni la última elección; el modo oscuro sigue disponible con el botón de tema durante la sesión. La splash también es clara.
- Un acento funcional (Azul Señal) + una paleta de 7 colores categóricos para tipos de pregunta.
- Sombras neutras (negro a baja opacidad) para elevación; cero halos de color.
- Tarjetas redondeadas de esquina generosa (14-28px), sólidas, sobre un fondo liso: sin vidrio, sin blur decorativo y sin halos radiales de fondo (se quitaron en la revisión de septiembre de 2026 por contradecir la Regla Sin Halo).
- Tipografía geométrica (Outfit para títulos, Hanken Grotesk para cuerpo) — no una fuente de IA genérica.

## Colors

La paleta es fría y de baja saturación en su base (slate), con un único acento vibrante reservado para lo accionable, y una segunda paleta categórica (no jerárquica) para distinguir los 7 tipos de pregunta Moodle de un vistazo.

### Primary
- **Azul Señal** (`#0369a1` / hover `#075985`, tokens `--color-cta`/`--color-cta-hover`): el color de los botones de acción primaria y del enfoque de formularios. Comunica "esto es lo que puedes hacer ahora", nunca decoración. Siempre **sólido**: los degradados azul→índigo anteriores se retiraron.
- **Verde Avanzar** (`#047857` / hover `#065f46`, `--color-cta-success`): solo para la acción que hace avanzar el flujo (Procesar, Generar XML, Descargar).
- **Texto sobre acento** (`--color-on-accent`: `#06101f` en oscuro, `#ffffff` en claro): el texto encima de un relleno de `--color-accent` o de un color de tipo (chip de filtro activo, pregunta actual del mapa). En oscuro esos rellenos son claros y el blanco quedaba entre 1,7:1 y 2,7:1; con este token todos pasan de 7:1.

### Secondary
- **Cian de Acento** (`#38bdf8` en oscuro / `#0273ae` en claro): usado en logo, íconos de estado y el título de marca. Es el mismo matiz que Azul Señal pero más claro — reservado para elementos de identidad, no de acción.

### Neutral
- **Slate Profundo** (`#090d16`): fondo base en modo oscuro.
- **Slate Superficie** (`#131c31` / hover `#1e293b`): fondo de tarjetas y controles sobre el fondo base.
- **Texto Principal** (`#f8fafc`): texto de alto énfasis.
- **Texto Atenuado** (`#94a3b8`): texto secundario (subtítulos, descripciones).
- **Texto Sutil** (`#8f9db0`): texto terciario (metadatos, notas de pie) — nunca gris genérico puro; conserva un tinte azulado para no romper la temperatura de la paleta. Ajustado explícitamente para cumplir 4.5:1 sobre cualquier superficie del sistema (antes: `#8593a7`, insuficiente en `#1e293b`).

### Categóricos — Tipos de Pregunta (no jerárquicos, un color por tipo)
- **Azul Multiopción** (`#38bdf8`): opción múltiple.
- **Verde Afirmativo** (`#34d399`): verdadero/falso.
- **Ámbar Emparejador** (`#fbbf24`): emparejamiento.
- **Violeta Completar** (`#a78bfa`): completar (Cloze).
- **Rosa Ensayo** (`#f472b6`): ensayo.
- **Turquesa Respuesta Corta** (`#2dd4bf`): respuesta corta.
- **Naranja Numérico** (`#fb923c`): numérica.

### Semánticos
- **Verde Éxito** (`#10b981`, relleno sólido `#0c855d`): confirmaciones, respuesta correcta.
- **Ámbar Aviso** (`#f59e0b`): preguntas omitidas, advertencias no bloqueantes.
- **Rojo Error** (`#f43f5e`, relleno sólido `#be123c`): errores, preguntas incompletas y la confirmación de una acción destructiva (dentro de un diálogo). Nunca un botón rojo permanente junto a la acción principal.

### Named Rules
**La Regla del Acento Único.** Azul Señal se usa solo en controles accionables (botones primarios, foco de inputs, enlaces). Nunca aparece como decoración de fondo o como color de un ícono puramente informativo.

**La Regla Sin Halo.** Ninguna sombra de color sin desplazamiento (`box-shadow` "glow" a 0 0 Npx) — la elevación se comunica con sombras neutras (negro a baja opacidad) con desplazamiento y difuminado reales.

## Typography

**Display/Heading Font:** Outfit (con Hanken Grotesk, system-ui como respaldo)
**Body Font:** Hanken Grotesk (con system-ui, -apple-system como respaldo)
**Mono Font:** JetBrains Mono — reservado a bloques de código/formato (ejemplos de XML, prompt de IA), nunca como "disfraz técnico" en UI genérica.

**Character:** Un geométrico de alto contraste (Outfit) para títulos cortos y contundentes, emparejado con un grotesco humanista (Hanken Grotesk) que mantiene legibilidad alta en párrafos densos de instrucciones — sin caer en las fuentes por defecto de interfaces generadas por IA.

### Escala (tokens `--text-*` en base.css)
`xs` 11.5 · `sm` 12.5 · `md` 14 · `lg` 16 · `title` 19 · `headline` 22 (px). Todo tamaño de texto sale de aquí; no se escriben tamaños sueltos en estilos en línea. Excepción: `.brand-title` y `.screen-title` declaran el valor en px (19 y 22; 17 para la marca en celular), porque el detector de diseño no resuelve `var()` y los leía como 16px.

### Hierarchy
- **Headline** (800, 22px, 1.3, clase `.screen-title`): título de cada pantalla ("Revisa las preguntas", "Tu XML está listo"). Recibe el foco al cambiar de paso.
- **Title** (800, 19px, 1.2, tracking -0.5px): título de marca y de modales (`.modal-title`).
- **Large** (800, 16px): título de cada tarjeta de pregunta ("Pregunta 12") y botones grandes.
- **Body** (500, 14-14.5px, 1.6): texto de instrucciones, descripciones, notas. Los párrafos largos de la Guía usan hasta 1.7 de interlineado para lectura sostenida.
- **Label** (700-800, 11.5-12px, 0.4-0.5px tracking, mayúsculas): etiquetas de campo y badges de tipo — el único lugar donde mayúsculas son válidas por ser texto corto (2-3 palabras). Nunca en preguntas u oraciones completas.

### Named Rules
**La Regla de las Mayúsculas Cortas.** `text-transform: uppercase` solo en etiquetas de ≤20 caracteres (badges, labels de campo). Cualquier encabezado que sea una oración o pregunta completa va en case normal.

## Layout

Contenedor central único (`max-width: 860px`, centrado) — el sistema no usa una grilla multi-columna porque su tarea principal (revisar preguntas una por una) es inherentemente secuencial y vertical. Padding lateral de 24px en escritorio, reducido a 16px bajo 640px. Bajo 480px, la barra de navegación superior colapsa de "ícono + etiqueta" a solo ícono para evitar overflow horizontal (conserva `aria-label`/`title` para accesibilidad). Ritmo vertical por tarjetas apiladas con `gap` de 12-20px entre ellas; el stepper de progreso (1-2-3) y los botones de acción principales quedan fijos arriba del scroll en exámenes largos.

### Editor de revisión (≥1140px)
Contenido (860px) + mapa del examen (196px) a la derecha. Para que quepa en un portátil de 1280px, contenido y cabecera se corren a la izquierda la mitad del ancho del mapa. Por debajo de 1140px el mapa pasa a una barra fija abajo ("12 de 40" + Generar XML) y el aviso flotante sube por encima de ella.

Orden de la pantalla de revisión: título y conteo → avisos de una línea (omitidas plegadas en `<details>`) → barra plegada (Mostrar · Puntos) → tarjetas → "¿Falta alguna pregunta? Añadir pregunta" al final. La primera pregunta debe verse sin scroll en un portátil.

## Elevation & Depth

Sistema mayormente plano en reposo: las tarjetas se distinguen del fondo por un borde de 1px semitransparente y un color de superficie ligeramente más claro, no por sombra. La sombra aparece como respuesta a jerarquía o estado (logo, botones primarios, elementos con foco), siempre neutra (negro a baja opacidad) — nunca coloreada ni sin desplazamiento. Esto reemplazó una versión anterior con halos de color (`box-shadow` cian/verde/rojo sin offset) que se identificó y corrigió explícitamente como un patrón de "interfaz generada por IA".

### Shadow Vocabulary
- **`--shadow-sm`** (`0 2px 8px rgba(0,0,0,0.2)`): elevación mínima, controles pequeños.
- **`--shadow-md`** (`0 8px 24px rgba(0,0,0,0.3)`): tarjetas modales, dropdowns.
- **`--shadow-lg`** (`0 20px 50px rgba(0,0,0,0.45)`): superficies flotantes (modal de Guía/Historial).
- **`--shadow-glow`** (`0 8px 20px rgba(0,0,0,0.35)`): nombre heredado; ya casi no se usa (logo y botones usan `--shadow-sm`).

### Named Rules
**La Regla Sin Halo.** Toda sombra lleva desplazamiento vertical real y difuminado; ninguna es un aro de color a desplazamiento cero. Ver también la regla homónima en Colors.

## Shapes

Esquinas generosamente redondeadas y consistentes por escala: `8px` para controles pequeños (inputs, botones ghost), `14px` para tarjetas y botones primarios, `20px` para tarjetas de sección (`glass-card`), `28px` para el dropzone de carga de archivo, y `9999px` (píldora completa) para badges, chips de filtro y el indicador del logo circular. Bordes de 1-1.5px, siempre semitransparentes (nunca sólidos de alto contraste) excepto en callouts de estado (aviso, error) donde el borde sí usa el color semántico a opacidad completa para reforzar la alerta.

## Components

### Buttons
- **Shape:** `border-radius: 14px` (`--radius-md`).
- **Primary / Success:** color sólido (`--color-cta` azul, `--color-cta-success` verde) con texto blanco (≥5,5:1), `padding: 12px 22px`, `--shadow-sm`. Tamaños `.btn-lg` y `.btn-sm`.
- **Ghost:** superficie con borde de 1.5px, para acciones secundarias (Volver a la revisión, Reabrir, Descargar XML del historial).
- **Ghost también para salir o descartar** ("Descartar", "Convertir otro examen", "Cancelar y volver"): llevan marco, en gris, igual que "Volver a la revisión", para que se lean como botones. Lo que las separa de la acción principal es el color (gris frente a verde) y el tamaño, no la falta de marco. Descartar la revisión siempre pide confirmación en un diálogo (`#modal-confirm`) con el foco en la opción segura.
- **Quiet:** sin fondo ni borde, solo para acciones menores dentro de un bloque (p. ej. "Agregar opción" en un espacio de Completar).
- **Hover:** solo color, sin mover el botón, y solo con mouse (`@media (hover: hover) and (pointer: fine)`).
- **Press:** `:active { transform: scale(0.97) }` en 120ms con `--ease-out`, en todo lo que se presiona (botones, chips, cuadros del mapa, pestañas).
- **Ghost:** fondo `--color-surface-hover`, texto atenuado, borde sutil — para acciones secundarias (Historial, Reintentar).

### Callouts
Clase `.callout` (`.is-warning`, `.is-error`): una línea con ícono y borde de 1px en las 4 caras. Informativo = superficie neutra con ícono de acento (nunca violeta: es el color de Completar).

### Zona de carga y subida
Con un archivo elegido, la zona de carga pasa a verde (borde sólido `--color-success`, fondo `--color-success-bg`, ícono de archivo con check y el título "Archivo listo"). Bajo el nombre del archivo, `.upload-bar` muestra el avance real de la subida (vía `XMLHttpRequest`, ver `js/subida.js`). Después, mientras el conversor revisa el archivo, queda llena y atenuada, con un contador de segundos (sin animación en bucle). Solo aparece si la espera supera 300 ms. En la pantalla de progreso, mientras dura la subida, la barra completa representa esa subida ("12,3 MB de 60,0 MB").

### Atajos de teclado
J/K (siguiente/anterior), I (siguiente incompleta), R (siguiente para revisar), ? (abre la Guía en «Revisión») y Esc. No hay botón propio en el editor: la lista vive en la Guía → Revisión, a la que se llega con «¿Cómo reviso?» o con `?`.

### Pantalla de arranque (splash, launcher.py)
Sin tarjeta, sin vidrio ni halos, sin texto en degradado y sin mensajes inventados. Fondo liso claro (la app siempre abre en modo claro); el ícono oficial a 64px (incrustado en el HTML, porque la splash se carga sin servidor), nombre en Outfit 30px, una línea de descripción y una barra de 3px que avanza con las etapas REALES del arranque (`setStage`, llamada desde el launcher). Pie con los créditos y la versión, separado por una línea fina. La pantalla de "no se pudo iniciar" usa el mismo lenguaje, con la marca en rojo, qué hacer y la ruta del registro.

### Mapa del examen (review rail)
Un cuadro por pregunta. **Incompleta:** borde rojo sólido + fondo rojo tenue. **Para revisar:** borde ámbar **discontinuo** (no depende solo del color, y se distingue del ámbar de Emparejamiento). **Actual:** contorno de acento de 2px; solo si no tiene avisos se rellena de acento con `--color-on-accent`. Teclas J/K para siguiente/anterior.

### Chips (badges de tipo y filtros)
- **Style:** píldora completa (`--radius-full`), fondo del color categórico a 15% opacidad, texto y borde en el color sólido correspondiente. Etiqueta siempre en mayúsculas cortas (nombre del tipo).
- **State:** el chip de filtro activo (`aria-pressed="true"`) invierte a fondo sólido del color con texto `--color-on-accent`; los inactivos quedan en su variante tenue.
- **Nombres:** un tipo se llama igual en toda la app: Opción múltiple, Verdadero/Falso, Emparejamiento, Completar, Ensayo, Respuesta corta, Numérica.
- **Señales de procedencia** ("convertida de tabla", "revisar marca", "confianza baja") usan el estilo de aviso (`.flag-review`), no un color de tipo.

### Cards / Containers
- **Corner Style:** `20px` (`glass-card`, tarjetas de sección) o `14px` (tarjetas internas del editor).
- **Background:** `--color-surface-card` sólido (sin `backdrop-filter`), o `--color-surface` para tarjetas anidadas dentro de otra tarjeta.
- **Shadow Strategy:** ninguna en reposo; borde de 1px es el único separador visual del fondo.
- **Border:** 1px, `--color-border` (blanco a 12% opacidad en oscuro).
- **Internal Padding:** 18-32px según densidad de contenido.

### Inputs / Fields
- **Style:** fondo `--color-bg` (más oscuro que la tarjeta que lo contiene, para que se lea como "hueco" donde escribir), borde 1.5px `--color-border`, `border-radius: 14px`.
- **Focus:** borde cambia a Azul Señal + anillo de foco (`box-shadow: 0 0 0 3px` a baja opacidad del acento) — única excepción intencional a "sin halo", porque es una señal de accesibilidad funcional, no decorativa.
- **Error / Disabled:** los inputs no tienen estado de error visual propio hoy; los errores se comunican a nivel de tarjeta de pregunta completa (borde/fondo ámbar), no por campo individual.

### Ícono
El ícono oficial es `assets/Icon.ico` (mosaico claro redondeado con PDF → código). Se exporta a `frontend/img/icono.png` y se usa tal cual, sin recuadro de color alrededor: cabecera (44px), favicon y splash (64px). El `.app`/`.exe` usan `Icon.icns`/`Icon.ico`.

### Navigation
- **Style:** barra superior fija (`sticky`) con logo + título a la izquierda, acciones secundarias (Historial, Guía, tema) a la derecha como botones de ícono + etiqueta. La Guía se distingue del resto (fondo sólido Azul Señal) por ser la puerta de ayuda para un usuario nuevo. El botón de tema muestra la acción (sol = "pasar a claro"). Bajo 640px se oculta el subtítulo; bajo 480px quedan solo íconos (con `aria-label`/`title`).

### Historial
Buscador arriba de la lista que filtra al instante por nombre, categoría o fecha, sin distinguir tildes ni mayúsculas, y resalta la coincidencia. Muestra "N de M"; Esc con texto escrito borra la búsqueda. El modal tiene alto fijo para no saltar de tamaño al filtrar.

### Gráfica de puntos
Pastel con separadores de grosor parejo (trazo de 2,5px del color de la tarjeta), nunca huecos angulares, que salen en cuña. Los tipos con 0 pts no tienen porción, y con un solo tipo con puntos no se dibuja pastel.

### Modales
Todos pasan por `abrirModal`/`cerrarModal` (ui/modales.js): el foco entra al modal, el resto de la página queda `inert`, Escape cierra el de más arriba y el foco vuelve a quien lo abrió. Entrada 200ms, salida 150ms, desde el centro (no desde un disparador).

## Motion
Tokens en base.css: `--ease-out: cubic-bezier(0.23, 1, 0.32, 1)`, `--ease-in-out: cubic-bezier(0.77, 0, 0.175, 1)`, `--dur-press` 120ms, `--dur-fast` 150ms, `--dur-enter` 200ms.
- Nada de UI pasa de 250ms; las salidas son más rápidas que las entradas.
- Cambio de pantalla: fundido + 6px en 200ms. Cambio de pestaña de la Guía: sin animación (es frecuente).
- Acciones de teclado repetidas (J/K) no se animan.
- Solo se anima `transform` y `opacity` (la barra de avance usa `scaleX`, nunca `width`).
- `prefers-reduced-motion`: se conservan los fundidos y se quita todo desplazamiento, escala y scroll animado (`scrollBehavior()` en util.js).

### Stepper (componente de firma)
Indicador de progreso de 3 pasos (Cargar y Configurar → Revisar Preguntas → Descargar XML) con círculos numerados conectados por una línea — el paso activo se llena con Azul Señal, los completados quedan en verde, los futuros en gris neutro. Es la única referencia de "dónde estoy" en un flujo que de otro modo son pantallas independientes.

## Do's and Don'ts

### Do:
- **Do** usar Azul Señal (`#0369a1`/`#0284c7`) solo para lo accionable — botones primarios, foco, enlaces.
- **Do** dar a cada sombra un desplazamiento vertical real y difuminado (nunca `0 0 Npx` coloreado).
- **Do** reservar mayúsculas a etiquetas cortas (badges, labels de campo); cualquier oración o pregunta completa va en case normal.
- **Do** mantener un color categórico fijo por tipo de pregunta en toda la app (badges, chips de filtro, bordes de tarjeta) — la asociación color↔tipo debe ser consistente de principio a fin.
- **Do** dar a los callouts de estado (aviso, error, éxito) un borde de 1px en las 4 caras, no un acento lateral grueso.
- **Do** ofrecer "Deshacer" (aviso de 6 s que no se va mientras el mouse o el foco están encima) en lugar de confirmar acciones pequeñas y reversibles, y un diálogo de confirmación solo para descartar trabajo grande.
- **Do** insertar el texto del examen siempre escapado (`esc_html`), también dentro de `<textarea>` y atributos.

### Don't:
- **Don't** usar texto en degradado (`background-clip: text`) — la jerarquía viene de peso y tamaño, no de decoración.
- **Don't** usar degradados en botones, vidrio (`backdrop-filter`) en tarjetas ni halos radiales de fondo.
- **Don't** usar glifos de texto (✕ ⚠ ☑ →) como íconos: siempre Lucide.
- **Don't** usar Plus Jakarta Sans, Inter, Space Grotesk, Roboto ni Geist — son las fuentes por defecto de interfaces generadas por IA; el sistema usa Outfit + Hanken Grotesk deliberadamente.
- **Don't** animar `width`/`height` para barras de progreso — usar `transform: scaleX()`.
- **Don't** dejar animaciones decorativas infinitas (pulsos, glows) sin una alternativa para `prefers-reduced-motion`.
- **Don't** usar un color categórico de tipo de pregunta para transmitir un significado distinto (p. ej. usar el ámbar de "emparejamiento" como color de advertencia genérica) — cada color categórico pertenece a un solo tipo.
