/**
 * modales.js — cómo se abre y se cierra cualquier ventana modal (Guía,
 * Historial, aviso de imágenes, confirmación), más la Guía en sí.
 *
 * Todo modal pasa por abrirModal()/cerrarModal(), que se ocupan de lo que
 * antes faltaba: el foco entra al modal, no se escapa a la página de atrás
 * (el resto queda `inert`), Escape lo cierra y, al cerrar, el foco vuelve
 * al botón que lo abrió.
 */
import { modalDisclaimer, modalHelp, modalPanels, modalTabs } from '../dom.js';

// Lo que queda "detrás" de un modal abierto: inerte (ni foco ni clics ni
// lector de pantalla) mientras haya al menos un modal encima.
const FONDO = ['.app-header', '#main', '#review-rail'];

const pila = []; // [{ el, opener, onClose }]

function _fijarFondoInerte(inerte) {
  FONDO.forEach(sel => {
    const el = document.querySelector(sel);
    if (el) el.inert = inerte;
  });
  document.body.style.overflow = inerte ? 'hidden' : '';
}

function _primerEnfocable(el) {
  return el.querySelector('[data-autofocus]')
    || el.querySelector('button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])');
}

/**
 * Abre un modal. `foco` es el elemento que recibe el foco al abrir (por
 * defecto, el primero enfocable). `onClose` se llama al cerrarlo por
 * cualquier vía (Escape, clic fuera, botón).
 */
export function abrirModal(el, { foco = null, onClose = null } = {}) {
  if (pila.some(m => m.el === el)) return;
  const opener = document.activeElement;
  // Un segundo modal encima del primero: el de abajo también queda inerte.
  if (pila.length) pila[pila.length - 1].el.inert = true;
  pila.push({ el, opener, onClose });
  _fijarFondoInerte(true);
  el.classList.add('open');
  if (window.lucide) lucide.createIcons();
  requestAnimationFrame(() => (foco || _primerEnfocable(el))?.focus({ preventScroll: true }));
}

export function cerrarModal(el) {
  const i = pila.findIndex(m => m.el === el);
  if (i < 0) return;
  const [{ opener, onClose }] = pila.splice(i, 1);
  el.classList.remove('open');
  if (pila.length) pila[pila.length - 1].el.inert = false;
  else _fijarFondoInerte(false);
  if (opener && document.contains(opener)) opener.focus({ preventScroll: true });
  if (onClose) onClose();
}

/** El modal de más arriba (para Escape). */
export function modalActivo() {
  return pila.length ? pila[pila.length - 1].el : null;
}

// ── Guía ────────────────────────────────────────────────────────────────
export function openHelp(tabId) {
  if (tabId) switchTab(tabId, { enfocar: false });
  abrirModal(modalHelp, { foco: document.querySelector('.modal-tab[aria-selected="true"]') });
}

export function closeHelp() {
  cerrarModal(modalHelp);
}

// Pestañas con el patrón de ARIA (tablist/tab/tabpanel): solo la pestaña
// activa está en el orden de Tab; las flechas mueven entre pestañas.
export function switchTab(tabId, { enfocar = true } = {}) {
  modalTabs.forEach(t => {
    const sel = t.dataset.tab === tabId;
    t.classList.toggle('active', sel);
    t.setAttribute('aria-selected', sel ? 'true' : 'false');
    t.tabIndex = sel ? 0 : -1;
    if (sel && enfocar) t.focus();
  });
  Object.entries(modalPanels).forEach(([id, panel]) => panel.classList.toggle('active', id === tabId));
  // En celular la fila de pestañas se desplaza: la elegida queda a la vista.
  document.querySelector(`.modal-tab[data-tab="${tabId}"]`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  const body = document.querySelector('#modal-help .modal-body');
  if (body) body.scrollTop = 0;
}

export function onTabKeydown(e) {
  const tabs = Array.from(modalTabs);
  const i = tabs.indexOf(e.currentTarget);
  let next = null;
  if (e.key === 'ArrowRight') next = tabs[(i + 1) % tabs.length];
  else if (e.key === 'ArrowLeft') next = tabs[(i - 1 + tabs.length) % tabs.length];
  else if (e.key === 'Home') next = tabs[0];
  else if (e.key === 'End') next = tabs[tabs.length - 1];
  if (!next) return;
  e.preventDefault();
  switchTab(next.dataset.tab);
}

export function fileFingerprint(file) {
  return file ? `${file.name}_${file.size}_${file.lastModified}` : null;
}

// ── Aviso de imágenes incrustadas ───────────────────────────────────────
export function openDisclaimer() {
  abrirModal(modalDisclaimer, { foco: document.getElementById('btn-disclaimer-continue') });
}

export function closeDisclaimer() {
  cerrarModal(modalDisclaimer);
}
