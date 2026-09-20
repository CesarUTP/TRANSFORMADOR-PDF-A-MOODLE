/**
 * navegacion.js — los tres pasos de la app (cargar, revisar, descargar).
 */
import { clearFile } from './carga.js';
import { panelEditor, panelError, panelProgress, panelSuccess, panelUpload } from './dom.js';
import { estado } from './estado.js';

// Stepper Manager
function updateStepper(step) {
  const s1 = document.getElementById('step-1-indicator');
  const s2 = document.getElementById('step-2-indicator');
  const s3 = document.getElementById('step-3-indicator');
  const l1 = document.getElementById('step-line-1');
  const l2 = document.getElementById('step-line-2');

  s1.className = 'step-item ' + (step === 1 ? 'active' : step > 1 ? 'completed' : '');
  s2.className = 'step-item ' + (step === 2 ? 'active' : step > 2 ? 'completed' : '');
  s3.className = 'step-item ' + (step === 3 ? 'active' : '');

  l1.className = 'step-line ' + (step >= 2 ? 'active' : '');
  l2.className = 'step-line ' + (step >= 3 ? 'active' : '');
}

// Panel Manager
export function showPanel(name) {
  panelUpload.style.display   = name === 'upload'   ? 'block' : 'none';
  panelProgress.style.display = name === 'progress' ? 'block' : 'none';
  panelEditor.style.display   = name === 'editor'   ? 'block' : 'none';
  panelSuccess.style.display  = name === 'success'  ? 'block' : 'none';
  panelError.style.display    = name === 'error'    ? 'block' : 'none';
  document.body.classList.toggle('editor-active', name === 'editor');
  document.getElementById('review-rail')?.classList.remove('grid-open');

  if (name === 'upload') updateStepper(1);
  else if (name === 'editor') updateStepper(2);
  else if (name === 'success') updateStepper(3);
}

export function resetAll() {
  clearFile();
  estado.downloadBlob = null;
  estado.downloadFilename = '';
  estado.errorReturnPanel = 'upload';
  showPanel('upload');
}
