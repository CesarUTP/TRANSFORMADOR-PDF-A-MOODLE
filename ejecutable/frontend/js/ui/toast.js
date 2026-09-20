/**
 * toast.js — el aviso flotante de abajo.
 */
import { toastEl } from '../dom.js';

// Toast Function
const TOAST_ICONS = { success: 'check-circle', error: 'alert-circle', info: 'info' };

let toastTimer;

let toastSwapTimer;

export function showToast(msg, type = 'success') {
  const paint = () => {
    toastEl.innerHTML = `<i data-lucide="${TOAST_ICONS[type] || 'check-circle'}" style="width:16px;height:16px;"></i><span>${msg}</span>`;
    toastEl.className = 'toast' + (type === 'error' ? ' error' : type === 'info' ? ' info' : '');
    lucide.createIcons();
    void toastEl.offsetWidth;
    toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.classList.remove('show'); }, 3500);
  };

  clearTimeout(toastSwapTimer);
  if (toastEl.classList.contains('show')) {
    // Ya hay un toast visible: se desvanece brevemente antes de mostrar
    // el nuevo mensaje, en vez de reemplazar el texto de golpe.
    toastEl.classList.remove('show');
    clearTimeout(toastTimer);
    toastSwapTimer = setTimeout(paint, 200);
  } else {
    paint();
  }
}
