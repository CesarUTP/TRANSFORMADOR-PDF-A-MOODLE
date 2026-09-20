/**
 * dom.js — referencias a los elementos fijos de la página.
 * Se buscan una sola vez, al cargar, y se comparten entre módulos.
 */

// Modal Help
export const modalHelp = document.getElementById('modal-help');

export const modalTabs = document.querySelectorAll('.modal-tab');

export const modalPanels = {
  about: document.getElementById('modal-panel-about'),
  review: document.getElementById('modal-panel-review'),
  format: document.getElementById('modal-panel-format'),
  prompt: document.getElementById('modal-panel-prompt'),
  moodle: document.getElementById('modal-panel-moodle'),
};

// Copy Prompt
export const btnCopyPrompt = document.getElementById('btn-copy-prompt');

export const copyLabel = document.getElementById('copy-label');

export const copyIcon = document.getElementById('copy-icon');

export const aiPromptText = document.getElementById('ai-prompt-text');

// DOM Elements
export const dropZone = document.getElementById('drop-zone');

export const fileInput = document.getElementById('file-input');

export const filePreview = document.getElementById('file-preview');

export const fileNameEl = document.getElementById('file-name');

export const fileSizeEl = document.getElementById('file-size');

export const fileIconEl = document.getElementById('file-icon');

export const btnRemoveFile = document.getElementById('btn-remove-file');

export const categoryInput = document.getElementById('category-input');

export const pointsInput = document.getElementById('points-input');

export const pointsError = document.getElementById('points-error');

export const btnConvert = document.getElementById('btn-convert');

export const panelUpload = document.getElementById('panel-upload');

export const panelProgress = document.getElementById('panel-progress');

export const panelEditor = document.getElementById('panel-editor');

export const panelSuccess = document.getElementById('panel-success');

export const panelError = document.getElementById('panel-error');

export const toastEl = document.getElementById('toast');

// Disclaimer: PDF con imágenes incrustadas (caso especial no 100% fiable)
export const modalDisclaimer = document.getElementById('modal-disclaimer');

// History Logic
export const modalHistory = document.getElementById('modal-history');
