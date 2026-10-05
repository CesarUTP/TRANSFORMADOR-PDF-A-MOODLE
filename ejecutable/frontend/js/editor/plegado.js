/**
 * plegado.js — cada pregunta del editor se puede plegar a una fila de resumen.
 *
 * Plegar es solo visual: el contenido de la tarjeta sigue en el DOM (CSS
 * oculta lo que no es la cabecera), así que collectEditorData, la validación
 * y el XML leen exactamente lo mismo estén plegadas o no. El estado vive en
 * el atributo `data-abierta` de cada tarjeta.
 *
 * Qué se abre solo al dibujar el examen (ver abiertasPorDefecto): las que
 * piden revisión o están incompletas (hasta MAX_ABIERTAS) y, si no hay
 * ninguna, la primera. Al volver a dibujar (añadir, borrar, deshacer) se
 * conserva lo que el docente tenía abierto.
 */
import { clozeBuildTextAndAnswer } from './cloze.js';
import { autoGrowTextarea } from './tarjetas.js';
import { crearIconos } from '../util.js';
import { abiertasPorDefecto, recortar } from './plegado-logica.js';
export { MAX_ABIERTAS, abiertasPorDefecto, recortar } from './plegado-logica.js';

// ── Estado de cada tarjeta ──────────────────────────────────────────────
export const estaAbierta = card => card.hasAttribute('data-abierta');

function _tarjetas() {
  return Array.from(document.querySelectorAll('#editor-questions-container .editor-card'));
}

/** Qué tarjetas están abiertas ahora, en el orden del DOM (para volver a dibujar). */
export function abiertasEnOrden() {
  return _tarjetas().map(estaAbierta);
}

function _sincronizar(card) {
  const abierta = estaAbierta(card);
  card.querySelector('.card-toggle')?.setAttribute('aria-expanded', abierta ? 'true' : 'false');
  card.querySelector('.card-toggle')?.setAttribute('aria-label', `${abierta ? 'Plegar' : 'Abrir'} la pregunta ${card.dataset.qnum}`);
}

/** Abre una tarjeta. `animar` solo cuando la abre el docente con un clic. */
export function abrirTarjeta(card, { animar = false } = {}) {
  if (!card) return;
  if (!estaAbierta(card)) {
    card.setAttribute('data-abierta', '');
    // Estaba oculta: los campos no tenían medidas, se recalculan ahora.
    card.querySelectorAll('textarea').forEach(autoGrowTextarea);
    if (animar) {
      card.classList.add('recien-abierta');
      setTimeout(() => card.classList.remove('recien-abierta'), 260);
    }
  }
  _sincronizar(card);
}

export function plegarTarjeta(card) {
  if (!card) return;
  card.removeAttribute('data-abierta');
  card.classList.remove('recien-abierta');
  actualizarResumen(card);
  _sincronizar(card);
}

export function alternarTarjeta(el) {
  const card = el.closest('.editor-card');
  if (!card) return;
  if (estaAbierta(card)) plegarTarjeta(card);
  else abrirTarjeta(card, { animar: true });
  _actualizarBotonTodas();
}

/** «Abrir todas / Plegar todas»: si alguna está plegada abre todas; si no, las pliega. */
export function alternarTodas() {
  const cards = _tarjetas().filter(c => c.style.display !== 'none');
  const abrir = cards.some(c => !estaAbierta(c));
  cards.forEach(c => { if (abrir) abrirTarjeta(c); else plegarTarjeta(c); });
  _actualizarBotonTodas();
}

function _actualizarBotonTodas() {
  const btn = document.getElementById('btn-plegar-todas');
  if (!btn) return;
  const hay = _tarjetas().some(c => !estaAbierta(c));
  const texto = btn.querySelector('span');
  if (texto) texto.textContent = hay ? 'Abrir todas' : 'Plegar todas';
  btn.setAttribute('aria-label', hay ? 'Abrir todas las preguntas' : 'Plegar todas las preguntas');
}

// ── Resumen de una tarjeta plegada ──────────────────────────────────────
// Lo que el docente necesita para reconocer la pregunta y ver qué respuesta
// lleva, leído del DOM tal como está ahora (incluye sus ediciones).
function _valor(card, sel) {
  const el = card.querySelector(sel);
  return el ? String(el.value ?? '').trim() : '';
}

export function resumenDe(card) {
  const tipo = card.dataset.qtype;
  let enunciado = _valor(card, '.q-stem');
  let respuesta = '';
  let falta = false;
  if (tipo === 'multichoice') {
    const marcadas = Array.from(card.querySelectorAll('.q-opt-correct:checked'));
    respuesta = marcadas.map(cb => {
      const letra = cb.dataset.letter;
      const txt = Array.from(card.querySelectorAll('.q-opt')).find(o => o.dataset.letter === letra)?.value.trim();
      return txt ? `${letra}. ${txt}` : letra;
    }).join(' · ');
    falta = !marcadas.length;
  } else if (tipo === 'truefalse') {
    respuesta = _valor(card, '.q-ans');
  } else if (tipo === 'shortanswer') {
    respuesta = _valor(card, '.q-sa-answer'); falta = !respuesta;
  } else if (tipo === 'numerical') {
    respuesta = _valor(card, '.q-nu-answer'); falta = !respuesta;
  } else if (tipo === 'matching') {
    const n = card.querySelectorAll('.matching-pair-row').length;
    respuesta = n === 1 ? '1 pareja' : `${n} parejas`;
  } else if (tipo === 'essay') {
    respuesta = 'respuesta abierta';
  } else if (tipo === 'cloze') {
    const b = card.querySelector('.cloze-builder');
    if (b) {
      const { text, huecos } = clozeBuildTextAndAnswer(b);
      enunciado = text.replace(/\[[^\]]*\]/g, '____');
      const n = huecos.length;
      respuesta = n === 1 ? '1 hueco' : `${n} huecos`;
      falta = huecos.some(h => !h.correct_idx.length);
    }
  }
  return { enunciado: recortar(enunciado), respuesta: recortar(respuesta, 70), falta };
}

/** Escribe el resumen en la cabecera de la tarjeta (con textContent: nada se interpreta como HTML). */
export function actualizarResumen(card) {
  const caja = card.querySelector('.card-resumen');
  if (!caja) return;
  const { enunciado, respuesta, falta } = resumenDe(card);
  const pts = _valor(card, '.q-points');
  caja.replaceChildren();
  const e = document.createElement('span');
  e.className = 'resumen-enun';
  e.textContent = enunciado || 'Sin enunciado';
  caja.append(e);
  const r = document.createElement('span');
  r.className = `resumen-resp${falta ? ' falta' : ''}`;
  r.textContent = falta ? 'sin respuesta marcada' : respuesta;
  if (falta || respuesta) caja.append(r);
  if (pts) {
    const p = document.createElement('span');
    p.className = 'resumen-pts';
    p.textContent = `${pts} pts`;
    caja.append(p);
  }
}

/**
 * Marca de «Revisar» en la fila plegada, según los avisos que ya calcula el
 * panel (data-revisar / data-review). Solo toca el DOM si algo cambió.
 */
export function actualizarEstado(card) {
  const caja = card.querySelector('.card-estado');
  if (!caja) return;
  const clave = card.dataset.revisar === '1' ? 'dudosa' : card.dataset.review === '1' ? 'revisar' : '';
  if (caja.dataset.clave === clave) return;
  caja.dataset.clave = clave;
  caja.replaceChildren();
  if (!clave) return;
  caja.innerHTML = '<i data-lucide="eye" aria-hidden="true"></i><span>Revisar</span>';
  caja.title = card.dataset.motivo || 'Tiene un aviso para revisar';
  crearIconos(caja);
}

/**
 * Deja cada tarjeta plegada o abierta tras dibujar el editor. `abiertas` es la
 * lista a conservar; sin ella se usan los valores por defecto (examen nuevo).
 */
export function aplicarPlegado(abiertas = null) {
  const cards = _tarjetas();
  const lista = Array.isArray(abiertas) && abiertas.length
    ? cards.map((_, i) => !!abiertas[i])
    : abiertasPorDefecto(cards.map(c => ({
      incompleta: c.classList.contains('is-incomplete'),
      revisar: c.dataset.revisar === '1' || c.dataset.review === '1',
    })));
  cards.forEach((c, i) => {
    if (lista[i]) abrirTarjeta(c); else { c.removeAttribute('data-abierta'); actualizarResumen(c); _sincronizar(c); }
    actualizarEstado(c);
  });
  _actualizarBotonTodas();
}

// Un clic en la fila plegada (fuera de sus controles) la abre; Intro con la
// tarjeta enfocada (J/K la dejan ahí) la abre o la pliega. Una acción de
// teclado repetida no se anima.
export function registrarPlegado(container) {
  container.addEventListener('click', e => {
    const head = e.target.closest('.card-head');
    if (!head || e.target.closest('button, input, select, textarea, a, label')) return;
    const card = head.closest('.editor-card');
    if (card && !estaAbierta(card)) { abrirTarjeta(card, { animar: true }); _actualizarBotonTodas(); }
  });
  container.addEventListener('keydown', e => {
    if (e.key !== 'Enter' || !e.target.classList?.contains('editor-card')) return;
    e.preventDefault();
    if (estaAbierta(e.target)) plegarTarjeta(e.target); else abrirTarjeta(e.target);
    _actualizarBotonTodas();
  });
}
