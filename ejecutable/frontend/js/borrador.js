/**
 * borrador.js — la revisión en curso se guarda sola en este equipo.
 *
 * Revisar 40 preguntas es trabajo de media hora: si la ventana se cierra,
 * se recarga o el docente pulsa algo por error, no debería perderse. Cada
 * cambio en el editor se guarda (con un pequeño retraso) en localStorage,
 * y al volver a abrir la app se ofrece "Retomar revisión".
 *
 * El borrador se borra al descartar la revisión a propósito o al generar
 * el XML (que ya queda en el Historial, desde donde también se reabre).
 */
import { renderEditor, collectEditorData } from './editor/tarjetas.js';
import { estado } from './estado.js';
import { showPanel } from './navegacion.js';
import { timeAgo } from './util.js';

const CLAVE = 'moodle_review_draft_v1';
let _timer = null;

function _leer() {
  try {
    const d = JSON.parse(localStorage.getItem(CLAVE));
    return d && d.parse && Array.isArray(d.parse.questions) && d.meta ? d : null;
  } catch (_) {
    return null;
  }
}

/** Guarda YA el estado actual del editor (sin tocar estado.currentParseResult). */
export function guardarBorradorAhora() {
  clearTimeout(_timer);
  if (!document.body.classList.contains('editor-active') || !estado.currentUploadMetadata) return;
  try {
    const cards = document.querySelectorAll('#editor-questions-container .editor-card');
    const parse = cards.length ? collectEditorData() : { questions: [], answer_key: {} };
    const prev = estado.currentParseResult || {};
    ['skipped_questions', 'completeness_notice', 'color_marks_notice'].forEach(k => {
      if (prev[k]) parse[k] = prev[k];
    });
    localStorage.setItem(CLAVE, JSON.stringify({ savedAt: Date.now(), meta: estado.currentUploadMetadata, parse }));
  } catch (_) {
    // Sin localStorage (modo privado, cuota llena): no es crítico, la
    // revisión sigue funcionando, solo no se podrá retomar.
  }
}

/** Guarda con un retraso de 800 ms (se llama en cada tecla). */
export function guardarBorrador() {
  clearTimeout(_timer);
  _timer = setTimeout(guardarBorradorAhora, 800);
}

export function borrarBorrador() {
  clearTimeout(_timer);
  try { localStorage.removeItem(CLAVE); } catch (_) {}
  mostrarAvisoBorrador();
}

/** Abre el editor con unos datos ya parseados (borrador o historial). */
export function abrirEnEditor(meta, parse) {
  estado.currentUploadMetadata = meta;
  estado.selectedFile = null;
  estado.downloadBlob = null;
  showPanel('editor', { enfocar: false });
  renderEditor(parse);
  lucide.createIcons();
  document.getElementById('editor-title')?.focus({ preventScroll: true });
}

export function retomarBorrador() {
  const d = _leer();
  if (!d) { mostrarAvisoBorrador(); return; }
  abrirEnEditor(d.meta, d.parse);
}

/** Muestra u oculta el aviso "Tienes una revisión sin terminar" del paso 1. */
export function mostrarAvisoBorrador() {
  const banner = document.getElementById('draft-banner');
  if (!banner) return;
  const d = _leer();
  banner.classList.toggle('visible', !!d);
  if (!d) return;
  const n = d.parse.questions.length;
  document.getElementById('draft-detail').textContent =
    `«${d.meta.filename}» · ${n} pregunta${n !== 1 ? 's' : ''} · guardada ${timeAgo(d.savedAt)}`;
}
