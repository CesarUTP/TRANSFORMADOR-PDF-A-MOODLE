/**
 * paneles.js — los tres paneles plegables de la revisión
 * (Filtrar, Añadir pregunta, Distribuir puntos).
 */
import { updatePointsWeightPreview } from './puntos-ui.js';

// Despliega/oculta los 4 botones de tipo bajo "Añadir nueva pregunta".
// No hace falta volver a ocultarlos tras elegir un tipo: addNewQuestion()
// termina llamando a renderEditor(), que reconstruye este bloque desde
// cero ya colapsado.
// Abre/cierra un panel colapsable (Filtrar / Añadir nueva pregunta) con
// una transición de opacidad + desplazamiento en vez de un salto seco
// de display:none a flex. Forzar un reflow (leer offsetHeight) entre
// fijar el display y agregar la clase le garantiza al navegador que ya
// "vio" el estado inicial oculto antes del cambio — si no, ambos
// cambios se aplicarían en el mismo cálculo de estilos y la transición
// no se vería (esto es más confiable que requestAnimationFrame, que en
// pestañas en segundo plano o sin foco puede no dispararse a tiempo).
export function _openCollapsiblePanel(el, displayValue) {
  el.style.display = displayValue;
  void el.offsetHeight;
  el.classList.add('panel-open');
}

export function _closeCollapsiblePanel(el) {
  el.classList.remove('panel-open');
  setTimeout(() => { el.style.display = 'none'; }, 200);
}

// Los 3 paneles colapsables de la revisión (Filtrar / Añadir nueva
// pregunta / Distribuir puntos) son mutuamente excluyentes: abrir uno
// cierra los otros. Antes esto estaba hardcodeado de a pares y se iba
// a olvidar de actualizar al agregar un tercer panel — un solo helper
// que cierra "todos menos el que se está abriendo" escala sin tocar
// los demás toggles cuando aparezca un cuarto.
const COLLAPSIBLE_PANEL_IDS = ['add-question-types', 'filter-chips-bar', 'points-tool-panel'];

// "Desplegar todo" suspende la exclusión mutua: mientras está activo,
// abrir uno de los 3 paneles ya NO cierra los otros dos. Se apaga solo
// al pulsar "Ocultar todo" (o al volver a activarlo si ya estaban
// todos abiertos) — interactuar con un panel individual no lo apaga.
// Arranca activo: al abrir el editor los 3 paneles se ven desplegados.
export let _panelsExpandedMode = true;

export function _closeOtherCollapsiblePanels(exceptId) {
  if (_panelsExpandedMode) return;
  COLLAPSIBLE_PANEL_IDS.forEach(id => {
    if (id === exceptId) return;
    const el = document.getElementById(id);
    if (el && el.classList.contains('panel-open')) _closeCollapsiblePanel(el);
  });
}

// Vuelve a abrir los 3 paneles cuando el modo "Desplegar todo" está
// fijado. Hace falta porque renderEditor() reconstruye el bloque de
// paneles desde cero (añadir/borrar una pregunta, aplicar puntos…) y
// los deja colapsados: sin esto, el modo quedaba activo por dentro
// pero con todo cerrado en pantalla.
export function _restorePanelsExpandedMode() {
  if (!_panelsExpandedMode) return;
  COLLAPSIBLE_PANEL_IDS.forEach(id => {
    const el = document.getElementById(id);
    if (el && !el.classList.contains('panel-open')) _openCollapsiblePanel(el, 'flex');
  });
}

// Colapsar un panel a mano rompe el "todo abierto", así que apaga el
// modo fijado — si no, el botón diría "Desplegar todo" mientras por
// dentro seguiría fijado, y el panel cerrado volvería a abrirse solo en
// el siguiente re-render.
export function _collapsePanelByHand(el) {
  _panelsExpandedMode = false;
  _closeCollapsiblePanel(el);
}

function _allPanelsOpen() {
  return COLLAPSIBLE_PANEL_IDS.every(id => {
    const el = document.getElementById(id);
    return el && el.classList.contains('panel-open');
  });
}

export function _updateToggleAllPanelsLabel() {
  const label = document.getElementById('toggle-all-panels-label');
  if (label) label.textContent = _allPanelsOpen() ? 'Ocultar todo' : 'Desplegar todo';
}

// Botón único que expande o colapsa los 3 paneles a la vez. Al
// expandir, activa el modo que suspende la exclusión mutua (para que
// luego se puedan seguir abriendo/cerrando individualmente sin que se
// cierren entre sí); al ocultar todo, lo desactiva de nuevo.
export function toggleAllPanels() {
  const allOpen = _allPanelsOpen();
  if (allOpen) {
    _panelsExpandedMode = false;
    COLLAPSIBLE_PANEL_IDS.forEach(id => {
      const el = document.getElementById(id);
      if (el) _closeCollapsiblePanel(el);
    });
  } else {
    _panelsExpandedMode = true;
    COLLAPSIBLE_PANEL_IDS.forEach(id => {
      const el = document.getElementById(id);
      if (el && !el.classList.contains('panel-open')) _openCollapsiblePanel(el, 'flex');
    });
    updatePointsWeightPreview();
  }
  _updateToggleAllPanelsLabel();
}

export function toggleAddQuestionMenu() {
  const el = document.getElementById('add-question-types');
  if (!el) return;
  if (el.classList.contains('panel-open')) {
    _collapsePanelByHand(el);
  } else {
    _closeOtherCollapsiblePanels('add-question-types');
    _openCollapsiblePanel(el, 'flex');
  }
  _updateToggleAllPanelsLabel();
}

/**
 * Deja los 3 paneles desplegados para el próximo render. Lo llama carga.js
 * al abrir el editor con un examen nuevo: un módulo no puede asignar a una
 * variable que importa de otro, así que el cambio se hace aquí.
 */
export function expandirPanelesPorDefecto() {
  _panelsExpandedMode = true;
}
