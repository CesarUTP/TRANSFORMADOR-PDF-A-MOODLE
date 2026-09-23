/**
 * confirmar.js — diálogo de confirmación para acciones que descartan
 * trabajo (p. ej. descartar la revisión de 40 preguntas).
 *
 * Devuelve una promesa: true si el docente confirma, false si cancela
 * (botón, Escape o clic fuera). El foco arranca en la opción SEGURA.
 */
import { abrirModal, cerrarModal } from './modales.js';

const modal = document.getElementById('modal-confirm');
const titleEl = document.getElementById('confirm-title');
const bodyEl = document.getElementById('confirm-body');
const okBtn = document.getElementById('btn-confirm-ok');
const cancelBtn = document.getElementById('btn-confirm-cancel');

let resolver = null;

function terminar(valor) {
  const r = resolver;
  resolver = null;
  cerrarModal(modal);
  if (r) r(valor);
}

okBtn.addEventListener('click', () => terminar(true));
cancelBtn.addEventListener('click', () => terminar(false));
modal.addEventListener('click', e => { if (e.target === modal) terminar(false); });

export function cerrarConfirmacion() {
  terminar(false);
}

export function confirmar({ titulo, mensaje, confirmar: okLabel = 'Descartar', cancelar = 'Cancelar' }) {
  if (resolver) resolver(false);
  titleEl.textContent = titulo;
  bodyEl.textContent = mensaje;
  okBtn.textContent = okLabel;
  cancelBtn.textContent = cancelar;
  return new Promise(resolve => {
    resolver = resolve;
    abrirModal(modal, { foco: cancelBtn, onClose: () => { if (resolver) { const r = resolver; resolver = null; r(false); } } });
  });
}
