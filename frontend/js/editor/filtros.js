/**
 * filtros.js — filtro por tipo de pregunta.
 */
import { buildReviewRail } from './panel.js';
import { _closeCollapsiblePanel, _closeOtherCollapsiblePanels, _collapsePanelByHand, _openCollapsiblePanel, _panelsExpandedMode, _updateToggleAllPanelsLabel } from './paneles.js';
import { QUESTION_TYPE_LABEL_MAP } from './tarjetas.js';

// Reconstruye los chips "Filtrar:" contando las tarjetas que de verdad
// quedan en el DOM en este momento. Se llama tras cualquier cambio en la
// cantidad de preguntas (borrar, añadir) para que "Todas (N)" y los
// conteos por tipo nunca queden desincronizados de lo que se ve en
// pantalla — mostrar un número viejo ahí hace pensar al usuario que su
// edición no se guardó de verdad.
export function refreshFilterChips() {
  const bar = document.getElementById('filter-chips-bar');
  if (!bar) return;

  const activeChip = bar.querySelector('.filter-chip.active');
  let activeFilter = activeChip ? activeChip.dataset.filter : 'all';

  const cards = document.querySelectorAll('.editor-card');
  const typeCounts = { multichoice: 0, truefalse: 0, matching: 0, cloze: 0, essay: 0, shortanswer: 0, numerical: 0 };
  cards.forEach(card => {
    const t = card.dataset.qtype;
    if (t in typeCounts) typeCounts[t]++;
  });

  // Si el tipo que estaba filtrado ya no tiene preguntas (se borró la
  // última de ese tipo), no tiene sentido dejar ese filtro activo.
  if (activeFilter !== 'all' && typeCounts[activeFilter] === 0) {
    activeFilter = 'all';
  }

  const typeLabels = QUESTION_TYPE_LABEL_MAP;
  let html = `<button type="button" class="filter-chip${activeFilter === 'all' ? ' active' : ''}" data-filter="all" onclick="selectFilter('all')">Todas <span class="count">(${cards.length})</span></button>`;
  Object.entries(typeCounts).forEach(([type, count]) => {
    if (count === 0) return;
    html += `<button type="button" class="filter-chip${activeFilter === type ? ' active' : ''}" data-filter="${type}" onclick="selectFilter('${type}')">${typeLabels[type]} <span class="count">(${count})</span></button>`;
  });
  bar.innerHTML = html;

  filterQuestionsByType(activeFilter);
}

// Igual que toggleAddQuestionMenu() — el bloque "Filtrar" arranca
// colapsado mostrando solo el filtro activo; un clic despliega los
// chips por tipo debajo.
export function toggleFilterMenu() {
  const el = document.getElementById('filter-chips-bar');
  if (!el) return;
  if (el.classList.contains('panel-open')) {
    _collapsePanelByHand(el);
  } else {
    _closeOtherCollapsiblePanels('filter-chips-bar');
    _openCollapsiblePanel(el, 'flex');
  }
  _updateToggleAllPanelsLabel();
}

// Onclick de cada chip: aplica el filtro y colapsa el menú de vuelta,
// como al elegir una opción de un desplegable — SALVO con "Desplegar
// todo" fijado, donde los paneles se quedan abiertos hasta que el
// docente pulse "Ocultar todo". Filtrar cerraba la barra igual, así
// que "Desplegar todo" parecía apagarse solo al elegir un tipo.
export function selectFilter(type) {
  filterQuestionsByType(type);
  if (_panelsExpandedMode) return;
  const bar = document.getElementById('filter-chips-bar');
  if (bar) _closeCollapsiblePanel(bar);
}

// Filtra las tarjetas visibles del editor por tipo de pregunta (o
// "all" para verlas todas). Es solo un filtro visual: las preguntas
// ocultas siguen incluidas al generar el XML.
function filterQuestionsByType(type) {
  // Acotado a #filter-chips-bar: los botones de "Añadir nueva pregunta"
  // reutilizan la misma clase .filter-chip (mismo estilo visual por
  // tipo) pero no son parte del filtro — sin este scope, filtrar por un
  // tipo los marcaría como "activos" por error.
  const chipsBar = document.getElementById('filter-chips-bar');
  if (chipsBar) {
    chipsBar.querySelectorAll('.filter-chip').forEach(chip => {
      chip.classList.toggle('active', chip.dataset.filter === type);
    });
  }
  document.querySelectorAll('.editor-card').forEach(card => {
    card.style.display = (type === 'all' || card.dataset.qtype === type) ? '' : 'none';
  });
  // El botón colapsado muestra el filtro activo (ej. "Ensayo (3)") sin
  // necesidad de desplegar la lista completa de chips.
  const activeChipEl = chipsBar && chipsBar.querySelector(`.filter-chip[data-filter="${type}"]`);
  const labelEl = document.getElementById('filter-current-label');
  if (labelEl && activeChipEl) labelEl.textContent = activeChipEl.textContent;
  buildReviewRail();
}
