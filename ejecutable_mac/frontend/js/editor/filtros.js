/**
 * filtros.js — filtro por tipo de pregunta.
 */
import { buildReviewRail } from './panel.js';
import { _closeCollapsiblePanel, togglePanel } from './paneles.js';
import { QUESTION_TYPE_DEFS, QUESTION_TYPE_LABEL_MAP, autoGrowTextarea } from './tarjetas.js';

// Reconstruye los chips "Filtrar" contando las tarjetas que de verdad
// quedan en el DOM, para que "Todas (N)" y los conteos por tipo nunca
// queden desfasados de lo que se ve en pantalla.
export function refreshFilterChips() {
  const bar = document.getElementById('filter-chips-bar');
  if (!bar) return;

  const activeChip = bar.querySelector('.filter-chip[aria-pressed="true"]');
  let activeFilter = activeChip ? activeChip.dataset.filter : 'all';

  const cards = document.querySelectorAll('.editor-card');
  const typeCounts = Object.fromEntries(QUESTION_TYPE_DEFS.map(t => [t.key, 0]));
  cards.forEach(card => {
    const t = card.dataset.qtype;
    if (t in typeCounts) typeCounts[t]++;
  });

  // Si el tipo filtrado ya no tiene preguntas (se borró la última), no
  // tiene sentido dejar ese filtro activo.
  if (activeFilter !== 'all' && typeCounts[activeFilter] === 0) activeFilter = 'all';

  const chip = (type, label, count) =>
    `<button type="button" class="filter-chip" data-filter="${type}" aria-pressed="${activeFilter === type}" data-accion="selectFilter" data-arg="${type}">${label} <span class="count">(${count})</span></button>`;
  let html = chip('all', 'Todas', cards.length);
  Object.entries(typeCounts).forEach(([type, count]) => {
    if (count > 0) html += chip(type, QUESTION_TYPE_LABEL_MAP[type], count);
  });
  bar.innerHTML = `<div class="filter-chips" role="group" aria-label="Mostrar solo un tipo de pregunta">${html}</div>`;

  filterQuestionsByType(activeFilter);
}

export function toggleFilterMenu() {
  togglePanel('filter-chips-bar', 'block');
}

// Al elegir un chip se aplica el filtro y el panel se pliega, como al
// elegir la opción de un desplegable. El foco vuelve al botón "Filtrar".
export function selectFilter(type) {
  filterQuestionsByType(type);
  const bar = document.getElementById('filter-chips-bar');
  if (bar && bar.classList.contains('panel-open')) {
    _closeCollapsiblePanel(bar);
    document.querySelector('[aria-controls="filter-chips-bar"]')?.focus();
  }
}

// Filtro solo visual: las preguntas ocultas siguen incluidas al generar
// el XML.
function filterQuestionsByType(type) {
  const chipsBar = document.getElementById('filter-chips-bar');
  let label = 'Todas';
  if (chipsBar) {
    chipsBar.querySelectorAll('.filter-chip').forEach(chip => {
      const on = chip.dataset.filter === type;
      chip.setAttribute('aria-pressed', on ? 'true' : 'false');
      if (on) label = chip.textContent.trim();
    });
  }
  document.querySelectorAll('.editor-card').forEach(card => {
    const show = type === 'all' || card.dataset.qtype === type;
    const wasHidden = card.style.display === 'none';
    card.style.display = show ? '' : 'none';
    if (show && wasHidden) card.querySelectorAll('textarea').forEach(autoGrowTextarea);
  });
  // El botón plegado muestra el filtro activo (ej. "Ensayo (3)").
  const labelEl = document.getElementById('filter-current-label');
  if (labelEl) labelEl.textContent = label;
  buildReviewRail();
}
