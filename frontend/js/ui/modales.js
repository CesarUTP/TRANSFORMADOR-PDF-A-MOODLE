/**
 * modales.js — Guía del sistema y aviso de imágenes incrustadas.
 */
import { modalDisclaimer, modalHelp, modalPanels, modalTabs } from '../dom.js';

export function openHelp(tabId) {
  modalHelp.classList.add('open');
  document.body.style.overflow = 'hidden';
  if (tabId) switchTab(tabId);
  lucide.createIcons();
}

export function closeHelp() {
  modalHelp.classList.remove('open');
  document.body.style.overflow = '';
}

export function switchTab(tabId) {
  modalTabs.forEach(t => t.classList.toggle('active', t.dataset.tab === tabId));
  Object.entries(modalPanels).forEach(([id, panel]) => panel.classList.toggle('active', id === tabId));
  // En celular la fila de pestañas se desplaza: la elegida queda a la vista.
  document.querySelector(`.modal-tab[data-tab="${tabId}"]`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  const body = document.querySelector('#modal-help .modal-body');
  if (body) body.scrollTop = 0;
}

export function fileFingerprint(file) {
  return file ? `${file.name}_${file.size}_${file.lastModified}` : null;
}

export function openDisclaimer() {
  modalDisclaimer.classList.add('open');
  document.body.style.overflow = 'hidden';
  lucide.createIcons();
}

export function closeDisclaimer() {
  modalDisclaimer.classList.remove('open');
  document.body.style.overflow = '';
}
