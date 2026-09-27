/**
 * toast.js — el aviso flotante de abajo.
 *
 * Puede llevar una acción (p. ej. "Deshacer"): en ese caso dura más
 * (6 s) y no se va mientras el mouse o el foco del teclado estén encima,
 * para que dé tiempo a usarla. El texto se inserta como texto, nunca
 * como HTML (puede traer mensajes de error del servidor).
 *
 * Teclado: el aviso está al final de la página, así que llegar a su botón
 * con Tab era impráctico. Mientras se ve, Ctrl/⌘+Z lo pulsa (salvo que se
 * esté escribiendo en OTRO campo: ahí Ctrl+Z deshace lo escrito, como
 * siempre). Si alPulsar devuelve un elemento, el foco vuelve a él: sin
 * esto quedaba en <body> y el usuario de teclado perdía su lugar.
 */
import { toastEl } from '../dom.js';

const TOAST_ICONS = { success: 'check-circle', error: 'alert-circle', info: 'info' };

let toastTimer;
let toastSwapTimer;
let restante = 0;
let inicio = 0;

function _programarCierre(ms) {
  clearTimeout(toastTimer);
  restante = ms;
  inicio = Date.now();
  toastTimer = setTimeout(hideToast, ms);
}

function _pausar() {
  if (!toastEl.classList.contains('show')) return;
  clearTimeout(toastTimer);
  restante = Math.max(restante - (Date.now() - inicio), 1500);
}

function _reanudar() {
  if (!toastEl.classList.contains('show')) return;
  // Si el foco sigue dentro (p. ej. en "Deshacer"), no se reanuda.
  if (toastEl.matches(':hover') || toastEl.contains(document.activeElement)) return;
  _programarCierre(restante);
}

toastEl.addEventListener('pointerenter', _pausar);
toastEl.addEventListener('pointerleave', _reanudar);
toastEl.addEventListener('focusin', _pausar);
toastEl.addEventListener('focusout', () => setTimeout(_reanudar, 0));

let _accionActual = null;
const _MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

function _ejecutar(accion) {
  _accionActual = null;
  hideToast();
  const destino = accion.alPulsar();
  if (destino && typeof destino.focus === 'function' && destino.isConnected) {
    destino.focus({ preventScroll: true });
  }
}

document.addEventListener('keydown', e => {
  if (!_accionActual || !toastEl.classList.contains('show')) return;
  if (e.key.toLowerCase() !== 'z' || e.shiftKey || e.altKey || !(e.metaKey || e.ctrlKey)) return;
  const t = e.target;
  const escribiendo = t.closest && t.closest('input:not([type="checkbox"]):not([type="radio"]), textarea, [contenteditable="true"]');
  if (escribiendo && !(_accionActual.campo && t === _accionActual.campo)) return;
  e.preventDefault();
  _ejecutar(_accionActual);
});

export function hideToast() {
  clearTimeout(toastTimer);
  _accionActual = null;
  toastEl.classList.remove('show');
}

/**
 * showToast(mensaje, tipo, { accion: { texto, alPulsar, campo? } })
 * tipo: 'success' | 'error' | 'info'
 * alPulsar puede devolver el elemento que recibe el foco después.
 * campo: el campo de texto que la acción restaura (ahí Ctrl/⌘+Z sí la usa).
 */
export function showToast(msg, type = 'success', { accion = null } = {}) {
  const paint = () => {
    toastEl.replaceChildren();
    const icon = document.createElement('i');
    icon.setAttribute('data-lucide', TOAST_ICONS[type] || 'check-circle');
    icon.style.cssText = 'width:16px;height:16px;';
    const span = document.createElement('span');
    span.className = 'toast-msg';
    span.textContent = msg;
    toastEl.append(icon, span);
    if (accion) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'toast-action';
      btn.textContent = accion.texto;
      if (accion.texto === 'Deshacer') {
        const atajo = document.createElement('kbd');
        atajo.className = 'toast-atajo';
        atajo.textContent = _MAC ? '⌘Z' : 'Ctrl+Z';
        btn.append(' ', atajo);
        btn.setAttribute('aria-keyshortcuts', _MAC ? 'Meta+Z' : 'Control+Z');
      }
      btn.addEventListener('click', () => _ejecutar(accion));
      toastEl.append(btn);
    }
    // Solo «Deshacer» responde a Ctrl/⌘+Z (no, p. ej., «Descargar»).
    _accionActual = accion && accion.texto === 'Deshacer' ? accion : null;
    toastEl.className = 'toast' + (type === 'error' ? ' error' : type === 'info' ? ' info' : '');
    lucide.createIcons();
    void toastEl.offsetWidth;
    toastEl.classList.add('show');
    _programarCierre(accion ? 6000 : type === 'error' ? 5000 : 3500);
  };

  clearTimeout(toastSwapTimer);
  if (toastEl.classList.contains('show')) {
    // Ya hay un aviso visible: se desvanece brevemente antes de mostrar
    // el nuevo, en vez de reemplazar el texto de golpe.
    toastEl.classList.remove('show');
    clearTimeout(toastTimer);
    _accionActual = null;
    toastSwapTimer = setTimeout(paint, 150);
  } else {
    paint();
  }
}
