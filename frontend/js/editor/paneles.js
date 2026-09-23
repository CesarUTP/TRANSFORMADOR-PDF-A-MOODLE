/**
 * paneles.js — los paneles plegables de la revisión (Filtrar, Distribuir
 * puntos, Añadir pregunta).
 *
 * Arrancan PLEGADOS y son mutuamente excluyentes: abrir uno cierra el
 * otro. Antes arrancaban los tres abiertos (más un aviso y la lista de
 * omitidas), y la primera pregunta quedaba 1-2 pantallas más abajo; la
 * tarea principal es revisar, estas herramientas son ocasionales.
 */

const COLLAPSIBLE_PANEL_IDS = ['add-question-types', 'filter-chips-bar', 'points-tool-panel'];

function _setExpanded(id, open) {
  document.querySelectorAll(`[aria-controls="${id}"]`).forEach(b => b.setAttribute('aria-expanded', open ? 'true' : 'false'));
}

// Forzar un reflow (leer offsetHeight) entre fijar el display y agregar
// la clase garantiza que el navegador "vio" el estado inicial oculto y la
// transición se ve (más fiable que requestAnimationFrame en segundo plano).
export function _openCollapsiblePanel(el, displayValue = 'flex') {
  el.style.display = displayValue;
  void el.offsetHeight;
  el.classList.add('panel-open');
  _setExpanded(el.id, true);
}

export function _closeCollapsiblePanel(el) {
  el.classList.remove('panel-open');
  _setExpanded(el.id, false);
  setTimeout(() => { if (!el.classList.contains('panel-open')) el.style.display = 'none'; }, 150);
}

function _closeOthers(exceptId) {
  COLLAPSIBLE_PANEL_IDS.forEach(id => {
    if (id === exceptId) return;
    const el = document.getElementById(id);
    if (el && el.classList.contains('panel-open')) _closeCollapsiblePanel(el);
  });
}

/** Abre o cierra un panel; al abrirlo cierra los demás. Devuelve si quedó abierto. */
export function togglePanel(id, displayValue = 'flex') {
  const el = document.getElementById(id);
  if (!el) return false;
  if (el.classList.contains('panel-open')) {
    _closeCollapsiblePanel(el);
    return false;
  }
  _closeOthers(id);
  _openCollapsiblePanel(el, displayValue);
  return true;
}

export function toggleAddQuestionMenu() {
  togglePanel('add-question-types', 'grid');
}
