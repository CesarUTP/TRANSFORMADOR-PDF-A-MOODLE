/**
 * navegacion.js — los tres pasos de la app (cargar, revisar, descargar).
 */
import { borrarBorrador } from './borrador.js';
import { clearFile } from './carga.js';
import { panelEditor, panelError, panelProgress, panelSuccess, panelUpload } from './dom.js';
import { estado } from './estado.js';
import { confirmar } from './ui/confirmar.js';

// Stepper Manager
function updateStepper(step) {
  const items = [1, 2, 3].map(n => document.getElementById(`step-${n}-indicator`));
  items.forEach((el, i) => {
    const n = i + 1;
    el.className = 'step-item ' + (step === n ? 'active' : step > n ? 'completed' : '');
    if (step === n) el.setAttribute('aria-current', 'step');
    else el.removeAttribute('aria-current');
  });
  document.getElementById('step-line-1').className = 'step-line ' + (step >= 2 ? 'active' : '');
  document.getElementById('step-line-2').className = 'step-line ' + (step >= 3 ? 'active' : '');
}

const PANELES = {
  upload:   { el: () => panelUpload,   titulo: 'upload-heading' },
  progress: { el: () => panelProgress, titulo: 'progress-title' },
  editor:   { el: () => panelEditor,   titulo: 'editor-title' },
  success:  { el: () => panelSuccess,  titulo: 'success-title' },
  error:    { el: () => panelError,    titulo: 'error-title' },
};

// Panel Manager. Al cambiar de paso la página vuelve arriba y el foco va
// al título de la pantalla nueva: así el lector de pantalla anuncia dónde
// está el docente (antes el foco quedaba perdido en <body>).
export function showPanel(name, { enfocar = true } = {}) {
  Object.entries(PANELES).forEach(([key, p]) => {
    p.el().style.display = key === name ? 'block' : 'none';
  });
  document.body.classList.toggle('editor-active', name === 'editor');
  const rail = document.getElementById('review-rail');
  rail?.classList.remove('grid-open');
  rail?.querySelector('.rail-pos')?.setAttribute('aria-expanded', 'false');

  if (name === 'upload') updateStepper(1);
  else if (name === 'editor') updateStepper(2);
  else if (name === 'success') updateStepper(3);

  window.scrollTo({ top: 0, behavior: 'auto' });
  if (enfocar) document.getElementById(PANELES[name].titulo)?.focus({ preventScroll: true });
}

export function resetAll() {
  clearFile();
  estado.downloadBlob = null;
  estado.downloadFilename = '';
  estado.errorReturnPanel = 'upload';
  showPanel('upload');
}

// "Descartar" en el panel de revisión: antes era un botón rojo junto a
// "Aprobar" que borraba todo sin preguntar. Ahora es discreto y pide
// confirmación diciendo cuánto trabajo se pierde.
export async function confirmDiscardReview() {
  const n = document.querySelectorAll('#editor-questions-container .editor-card').length;
  const ok = await confirmar({
    titulo: '¿Descartar esta revisión?',
    mensaje: n
      ? `Se perderán los cambios en ${n === 1 ? 'la pregunta' : `las ${n} preguntas`} de este examen y volverás al paso 1. Esta acción no se puede deshacer.`
      : 'Volverás al paso 1. Esta acción no se puede deshacer.',
    confirmar: 'Descartar revisión',
    cancelar: 'Seguir revisando',
  });
  if (!ok) return;
  borrarBorrador();
  resetAll();
}
