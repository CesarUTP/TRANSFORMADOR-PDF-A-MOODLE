/**
 * panel.js — panel de revisión: mapa del examen, preguntas incompletas
 * y navegación entre ellas.
 */
import { collectEditorData } from './tarjetas.js';
import { esc_html, scrollBehavior } from '../util.js';
import { questionIssues } from '../validacion.js';

// ── Panel de revisión (mapa del examen) ────────────────────────────────
// Un cuadrito por pregunta VISIBLE (respeta el filtro activo): la actual
// resaltada, las que traen un aviso ("confianza baja", "revisar marca de
// color", "convertida de tabla") en color de advertencia, y clic para
// saltar a ella. Se reconstruye cuando cambian las tarjetas (render,
// borrar, añadir, filtrar) y se actualiza con el scroll.
function _visibleEditorCards() {
  return Array.from(document.querySelectorAll('#editor-questions-container .editor-card'))
    .filter(c => c.style.display !== 'none');
}

function _headerBottom() {
  return document.querySelector('.app-header')?.getBoundingClientRect().bottom || 0;
}

// Lleva a una tarjeta. Con "reducir movimiento", el salto es instantáneo.
// `enfocar` mueve también el foco del teclado a la tarjeta, para que Tab
// siga desde ahí (y el lector de pantalla la anuncie).
export function scrollToEditorCard(card, { enfocar = false } = {}) {
  const top = card.getBoundingClientRect().top + window.scrollY - _headerBottom() - 16;
  window.scrollTo({ top, behavior: scrollBehavior() });
  if (enfocar) card.focus({ preventScroll: true });
}

// Marca cada tarjeta (borde rojo + qué le falta) y devuelve cuántas
// quedan incompletas. collectEditorData recorre las tarjetas en el mismo
// orden del DOM, así que el índice de cada pregunta es el de su tarjeta.
export function refreshQuestionIssues() {
  const cards = Array.from(document.querySelectorAll('#editor-questions-container .editor-card'));
  if (!cards.length) return 0;
  const { questions, answer_key } = collectEditorData();
  let incomplete = 0;
  cards.forEach((card, i) => {
    const q = questions[i];
    const issues = q ? questionIssues(q, answer_key[q.num]) : [];
    card.classList.toggle('is-incomplete', issues.length > 0);
    card.dataset.issues = issues.join(' · ');
    let box = card.querySelector(':scope > .card-issues');
    if (issues.length) {
      incomplete++;
      if (!box) {
        box = document.createElement('div');
        box.className = 'card-issues';
        box.setAttribute('role', 'status');
        card.firstElementChild.insertAdjacentElement('afterend', box);
      }
      box.innerHTML = `<i data-lucide="circle-alert"></i><span>${esc_html(issues.join(' · '))}</span>`;
      if (window.lucide) lucide.createIcons({ root: box });
    } else if (box) {
      box.remove();
    }
  });
  return incomplete;
}

// Se revisa al escribir, marcar casillas o añadir/quitar opciones
// (con un pequeño retraso para no recalcular en cada tecla).
let _issuesTimer = null;

export function scheduleIssuesRefresh() {
  clearTimeout(_issuesTimer);
  _issuesTimer = setTimeout(() => {
    if (document.body.classList.contains('editor-active')) buildReviewRail();
  }, 250);
}

export function buildReviewRail() {
  const rail = document.getElementById('review-rail');
  const grid = document.getElementById('review-rail-grid');
  if (!rail || !grid) return;
  rail.style.setProperty('--header-h', `${document.querySelector('.app-header')?.offsetHeight || 0}px`);
  refreshQuestionIssues();
  const cards = _visibleEditorCards();
  grid.innerHTML = cards.map((c, i) => {
    const missing = c.dataset.issues || '';
    const review = !missing && c.dataset.review === '1';
    const cls = missing ? ' incomplete' : review ? ' needs-review' : '';
    const tip = missing ? ` — ${missing}` : review ? ' — tiene un aviso para revisar' : '';
    return `<div role="listitem"><button type="button" class="rail-item${cls}" data-pos="${i}"
      title="Pregunta ${esc_html(c.dataset.qnum)}${esc_html(tip)}" aria-label="Pregunta ${esc_html(c.dataset.qnum)}${esc_html(tip)}">${esc_html(c.dataset.qnum)}</button></div>`;
  }).join('');
  grid.querySelectorAll('.rail-item').forEach(btn => {
    btn.addEventListener('click', () => {
      const card = _visibleEditorCards()[Number(btn.dataset.pos)];
      if (card) scrollToEditorCard(card, { enfocar: true });
      closeRailGrid();
    });
  });
  const missing = cards.filter(c => c.dataset.issues).length;
  const pending = cards.filter(c => !c.dataset.issues && c.dataset.review === '1').length;
  // Íconos dibujados (Lucide), no glifos ✕/⚠ de texto.
  const nextMissing = document.getElementById('rail-incomplete-next');
  nextMissing.classList.toggle('visible', missing > 0);
  nextMissing.innerHTML = `<i data-lucide="circle-alert"></i>${missing === 1 ? '1 pregunta incompleta' : `${missing} preguntas incompletas`}`;
  nextMissing.title = 'Ir a la siguiente pregunta incompleta';
  const next = document.getElementById('rail-review-next');
  next.classList.toggle('visible', pending > 0);
  next.innerHTML = `<i data-lucide="eye"></i>${pending === 1 ? '1 pregunta para revisar' : `${pending} preguntas para revisar`}`;
  next.title = 'Ir a la siguiente pregunta con aviso';
  const errShort = document.getElementById('rail-error-short');
  errShort.classList.toggle('visible', missing > 0);
  errShort.innerHTML = `<i data-lucide="circle-alert"></i>${missing}`;
  errShort.setAttribute('aria-label', `${missing} incompleta${missing !== 1 ? 's' : ''}`);
  const warnShort = document.getElementById('rail-warn-short');
  warnShort.classList.toggle('visible', pending > 0);
  warnShort.innerHTML = `<i data-lucide="eye"></i>${pending}`;
  warnShort.setAttribute('aria-label', `${pending} para revisar`);
  if (window.lucide) lucide.createIcons({ root: rail });
  _railCurrent = -1;
  updateReviewProgress();
}

// Salta a la siguiente pregunta incompleta ('incomplete') o con aviso
// ('review') DESPUÉS de la actual, y vuelve a la primera al llegar al final.
export function jumpToNextFlagged(kind) {
  const cards = _visibleEditorCards();
  const match = kind === 'incomplete'
    ? c => !!c.dataset.issues
    : c => !c.dataset.issues && c.dataset.review === '1';
  const flagged = cards.map((c, i) => [c, i]).filter(([c]) => match(c));
  if (!flagged.length) return;
  const target = flagged.find(([, i]) => i > _railCurrent) || flagged[0];
  scrollToEditorCard(target[0], { enfocar: true });
  closeRailGrid();
}

// J / K: siguiente / anterior pregunta (solo cuando no se está escribiendo
// en un campo). Sin animación extra: es una acción de teclado repetida.
export function jumpRelative(delta) {
  const cards = _visibleEditorCards();
  if (!cards.length) return;
  const base = _railCurrent < 0 ? 0 : _railCurrent;
  const i = Math.min(Math.max(base + delta, 0), cards.length - 1);
  const card = cards[i];
  const top = card.getBoundingClientRect().top + window.scrollY - _headerBottom() - 16;
  window.scrollTo({ top, behavior: 'auto' });
  card.focus({ preventScroll: true });
}

// En pantallas angostas la grilla se abre como un panel sobre la barra
// de abajo. En escritorio siempre está visible y el botón no hace nada.
export function toggleRailGrid() {
  if (window.matchMedia('(min-width: 1140px)').matches) return;
  const rail = document.getElementById('review-rail');
  const open = rail?.classList.toggle('grid-open');
  rail?.querySelector('.rail-pos')?.setAttribute('aria-expanded', open ? 'true' : 'false');
}

export function closeRailGrid() {
  const rail = document.getElementById('review-rail');
  if (!rail?.classList.contains('grid-open')) return;
  rail.classList.remove('grid-open');
  rail.querySelector('.rail-pos')?.setAttribute('aria-expanded', 'false');
}

// "Pregunta X de N": la primera tarjeta visible cuyo borde superior ya
// pasó justo por debajo del header. Se llama al cargar, al filtrar y en
// cada scroll (una vez por frame, con requestAnimationFrame).
let _railCurrent = -1;

export function updateReviewProgress() {
  const cards = _visibleEditorCards();
  const label = document.getElementById('review-progress-label');
  const short = document.getElementById('review-progress-short');
  const fill = document.getElementById('review-progress-fill');
  if (!label || !cards.length) {
    if (label) label.textContent = 'Sin preguntas';
    if (short) short.textContent = '0 de 0';
    if (fill) fill.style.transform = 'scaleX(0)';
    return;
  }
  const threshold = _headerBottom() + 24;
  let current = 0;
  for (let i = 0; i < cards.length; i++) {
    if (cards[i].getBoundingClientRect().top <= threshold) current = i;
    else break;
  }
  // Al final de la página, la última tarjeta puede no llegar nunca
  // arriba del todo: se da por "actual" la última.
  if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) current = cards.length - 1;
  // Con un filtro activo o preguntas borradas, el número de la pregunta
  // ya no coincide con su posición en la lista: se muestran ambos.
  const qnum = cards[current].dataset.qnum;
  label.textContent = String(current + 1) === qnum
    ? `Pregunta ${qnum} de ${cards.length}`
    : `Pregunta ${qnum} · ${current + 1} de ${cards.length}`;
  if (short) short.textContent = `${current + 1} de ${cards.length}`;
  fill.style.transform = `scaleX(${(current + 1) / cards.length})`;
  if (current !== _railCurrent) {
    _railCurrent = current;
    const grid = document.getElementById('review-rail-grid');
    grid?.querySelectorAll('.rail-item.current').forEach(b => b.classList.remove('current'));
    grid?.querySelectorAll('.rail-item[aria-current]').forEach(b => b.removeAttribute('aria-current'));
    const item = grid?.querySelector(`.rail-item[data-pos="${current}"]`);
    if (item) {
      item.classList.add('current');
      item.setAttribute('aria-current', 'true');
      // Mantiene visible el cuadrito actual dentro de la grilla (con 150
      // preguntas la grilla tiene su propio scroll), sin mover la página.
      const g = grid.getBoundingClientRect(), r = item.getBoundingClientRect();
      if (r.top < g.top || r.bottom > g.bottom) grid.scrollTop += r.top - g.top - g.height / 2;
    }
  }
}

export let _reviewProgressTicking = false;

// El avance ("Pregunta X de N") se recalcula al hacer scroll, una vez por
// frame para no recalcular en cada pixel.
window.addEventListener('scroll', () => {
  if (_reviewProgressTicking) return;
  _reviewProgressTicking = true;
  requestAnimationFrame(() => { updateReviewProgress(); _reviewProgressTicking = false; });
}, { passive: true });
