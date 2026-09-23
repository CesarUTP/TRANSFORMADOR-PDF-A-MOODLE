/**
 * toast.js — el aviso flotante de abajo.
 *
 * Puede llevar una acción (p. ej. "Deshacer"): en ese caso dura más
 * (6 s) y no se va mientras el mouse o el foco del teclado estén encima,
 * para que dé tiempo a usarla. El texto se inserta como texto, nunca
 * como HTML (puede traer mensajes de error del servidor).
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

export function hideToast() {
  clearTimeout(toastTimer);
  toastEl.classList.remove('show');
}

/**
 * showToast(mensaje, tipo, { accion: { texto, alPulsar } })
 * tipo: 'success' | 'error' | 'info'
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
      btn.addEventListener('click', () => {
        hideToast();
        accion.alPulsar();
      });
      toastEl.append(btn);
    }
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
    toastSwapTimer = setTimeout(paint, 150);
  } else {
    paint();
  }
}
