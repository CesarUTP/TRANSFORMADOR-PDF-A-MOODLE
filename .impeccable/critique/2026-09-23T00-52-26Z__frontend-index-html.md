---
target: interfaz completa del conversor
total_score: 22
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 3
target_identity: "file:/Users/cesar/Documents/Programas/TRANSFORMADOR-PDF-A-MOODLE-colaboracion/frontend/index.html"
target_fingerprint: "sha256:ae27c76367616abafa2061dbf86efc0bf40f3fddbe4eee113c085c04d8ef297c"
target_path: /Users/cesar/Documents/Programas/TRANSFORMADOR-PDF-A-MOODLE-colaboracion/frontend/index.html
timestamp: 2026-09-23T00-52-26Z
slug: frontend-index-html
---
Method: dual-agent (A: revisión de diseño + lente Emil · B: detector + overlay en navegador)

## Salud del diseño — 22/40 (Aceptable)

| # | Heurística | Puntaje | Problema clave |
|---|---|---|---|
| 1 | Visibilidad del estado | 3 | Progreso real y panel lateral buenos; no hay estado "revisada" por pregunta ni forma de cancelar un procesamiento de hasta 90 s |
| 2 | Coincidencia con el mundo real | 2 | "Preguntas Parseadas", "Prompt IA", "(multichoice)" en un toast (tarjetas.js:110); "Aprobar" en realidad genera el XML |
| 3 | Control y libertad | 1 | "Cancelar" borra la revisión sin confirmar (index.html:315 → navegacion.js:39); borrar pregunta sin deshacer; sin vuelta atrás desde la pantalla final |
| 4 | Consistencia | 2 | Cierto/Falso vs Verdadero/Falso, Emparejar vs Emparejamiento; violeta de Cloze reutilizado para IA; ámbar de aviso ≈ ámbar de Emparejar |
| 5 | Prevención de errores | 2 | Incompletas bloquean Aprobar (bien); acciones destructivas y "Aplicar" puntos sin red |
| 6 | Reconocer antes que recordar | 2 | Nada marca qué ya se revisó; inputs de una línea cortan parejas y fragmentos |
| 7 | Flexibilidad y eficiencia | 2 | "Siguiente incompleta" existe; sin atajos de teclado ni acciones en lote |
| 8 | Estética minimalista | 2 | Muro de avisos y paneles antes de la pregunta 1; ayuda repetida en cada tarjeta |
| 9 | Recuperación de errores | 3 | Cada tarjeta dice qué falta; título de error genérico |
| 10 | Ayuda y documentación | 3 | Guía completa (paso "Importar en Moodle" excelente) pero densa y fuera de contexto |

## Veredicto de especificidad
Mitad autoría, mitad plantilla. Propio: paleta de 7 tipos, panel-mapa, editor Cloze sin corchetes, rescate de omitidas, etiquetas de procedencia. Intercambiable: glass-card con blur, halos radiales de fondo (base.css:175-177, contra la Regla Sin Halo), CTA degradados azul→índigo, nube de carga, pastel de éxito.
Detector: CLI 33 hallazgos (15 color, 9 font-size, 7 radius advisory; 2 layout-transition → editor.css:34). Overlay: 82 en la vista principal (73 "cian neón" inflados por paths de iconos Lucide y vistas ocultas; 4 "degradado cian"; 3 line-length ~86-89 car.). Falsos positivos: layout-transition en body, radios 2-6px en elementos diminutos, gradientes-token, pruebas.html (11 hallazgos). Real: width en #review-progress-fill; tamaños de fuente inline fuera de escala (index.html:150,190,326; tarjetas.js:227,401,499); --color-accent-gradient con índigo.

## Problemas prioritarios
- [P0] Pérdida de trabajo sin confirmación: Cancelar→resetAll, papelera sin deshacer (tarjetas.js:39-56), Aplicar puntos pisa manuales. Fix: Cancelar ghost + confirmación con conteo; toast "Deshacer" 6 s; borrador en localStorage. → harden
- [P1] Primera pregunta enterrada a 1,6–2,6 pantallas (1291-3365 px). Fix: paneles plegados por defecto, omitidas en una línea expandible, "Añadir pregunta" al final. → distill + layout
- [P1] Accesibilidad rota: modales sin focus trap; tabs sin roles; blanco sobre chip activo 1,67-2,72:1 y rail current 2,14:1 (editor.css:70,304-312); aria-live sobre cronómetro; toast role=alert+polite; papelera sin aria-label; foco en body al cambiar pantalla. → audit + harden
- [P1] Texto cortado e inseguro en edición: inputs de una línea para parejas/fragmentos; enunciado sin recalcular alto; stem sin escapar dentro de <textarea> (tarjetas.js:427). → adapt + harden
- [P2] Final sin retorno y copia técnica: "Volver a la revisión", Descargar arriba, renombrar Parseadas/Aprobar. → clarify

## Personas
Jordan: botón deshabilitado sin explicación; editor abre con advertencias; "Aprobar" ambiguo; formato no soportado → pantalla de error completa.
Sam: foco escapa de modales; chips <3:1; cronómetro anunciado cada segundo; smooth scroll ignora reduced-motion; Sí/No de 24×22 px.
Alex: sin J/K; historial no reabre en editor; scroll a pregunta añadida roto (tarjetas.js:112-115); rail colapsa a barra inferior bajo 1320 px.
Docente con 40 preguntas: sin marca "revisada"; ~28.000 px; toast tapa Aprobar 3,5 s; tras aprobar no puede corregir.

## Motion (lente Emil)
fadeIn 0.4s→0.2s strong ease-out; reduced-motion incompleto (base.css:220); smooth scroll sin condición (panel.js:26, tarjetas.js:158); width→scaleX (editor.css:34); modal-box salida=entrada y opacidad muerta (componentes.css:423); tab-panel fadeInUp en cambio frecuente (componentes.css:478); sin :active en chips/rail/tabs; hover sin @media(hover:hover); stat-card hover falso; translateY(-2px) en botones de ancho completo compite con scale; spinner 1.2s→0.8s; transición de tema solo en body.

## Menores
innerHTML += en bucle (tarjetas.js:532); etiquetas del pastel sin contraste en claro; "1/10 ✕1" críptico; rail current oculta estado incompleto; cabecera móvil 4 líneas; DESIGN.md sin --color-success-solid ni stops de gradientes.

## Preguntas
1. ¿Por qué no hay "Aprobada" por tarjeta si el principio es aprobar cada pregunta?
2. ¿Y si el editor mostrara una pregunta a la vez con el panel como índice?
3. ¿Las omitidas deberían vivir en su posición original en vez de ser un muro previo?
