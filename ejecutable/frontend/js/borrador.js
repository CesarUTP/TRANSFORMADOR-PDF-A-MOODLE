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
import { reiniciarPanelPuntos } from './editor/puntos-ui.js';
import { renderEditor, collectEditorData } from './editor/tarjetas.js';
import { estado } from './estado.js';
import { showPanel } from './navegacion.js';
import { showToast } from './ui/toast.js';
import { timeAgo } from './util.js';

const CLAVE = 'moodle_review_draft_v1';
// Las imágenes (base64, varios MB) van en una clave aparte: así el texto del
// borrador, que se guarda tras cada pausa al escribir, se serializa en
// milisegundos, y las imágenes se reescriben solo cuando cambian (agregar,
// quitar o mover una). Un borrador viejo con las imágenes dentro se sigue
// leyendo igual.
const CLAVE_IMG = 'moodle_review_draft_imgs_v1';
let _timer = null;
let _firmaImgGuardada = null; // qué imágenes hay ya escritas en CLAVE_IMG
let _firmaImgFallida = null;  // imágenes que no cupieron (no se reintentan)
let _avisoEspacio = false;    // ya se avisó de que no cabe (no se repite)

function _leer({ conImagenes = false } = {}) {
  try {
    const d = JSON.parse(localStorage.getItem(CLAVE));
    if (!(d && d.parse && Array.isArray(d.parse.questions) && d.meta)) return null;
    if (conImagenes && d.firmaImg) {
      const img = JSON.parse(localStorage.getItem(CLAVE_IMG));
      // Solo si son EXACTAMENTE las imágenes de este borrador.
      if (img && img.firma === d.firmaImg && Array.isArray(img.porPregunta)) {
        d.parse.questions.forEach((q, i) => {
          const lista = img.porPregunta[i];
          if (q && q.data && Array.isArray(lista) && lista.length) q.data.images = lista;
        });
      }
    }
    return d;
  } catch (_) {
    return null;
  }
}

// Una huella barata de las imágenes de cada pregunta (tipo, largo y los
// extremos del base64): basta para saber si el conjunto cambió.
function _firmaImagenes(questions) {
  return questions.map(q => ((q.data && q.data.images) || [])
    .map(im => `${im.mime}:${im.b64.length}:${im.b64.slice(0, 24)}:${im.b64.slice(-24)}`).join(',')).join('|');
}

function _esFaltaDeEspacio(e) {
  return !!e && (e.name === 'QuotaExceededError' || e.name === 'NS_ERROR_DOM_QUOTA_REACHED' || e.code === 22 || e.code === 1014);
}

function _avisarSinEspacio(mensaje) {
  if (_avisoEspacio) return;
  _avisoEspacio = true;
  showToast(mensaje, 'error');
}

/** Guarda YA el estado actual del editor (sin tocar estado.currentParseResult). */
export function guardarBorradorAhora() {
  clearTimeout(_timer);
  if (!document.body.classList.contains('editor-active') || !estado.currentUploadMetadata) return;
  try {
    const cards = document.querySelectorAll('#editor-questions-container .editor-card');
    const parse = cards.length ? collectEditorData() : { questions: [], answer_key: {} };
    const prev = estado.currentParseResult || {};
    ['skipped_questions', 'completeness_notice', 'color_marks_notice', 'escaneado', 'importado', 'original_id'].forEach(k => {
      if (prev[k]) parse[k] = prev[k];
    });
    // Las imágenes se separan del texto (ver CLAVE_IMG).
    const firma = _firmaImagenes(parse.questions);
    const porPregunta = parse.questions.map(q => (q.data && q.data.images) || []);
    const hayImagenes = porPregunta.some(lista => lista.length > 0);
    parse.questions.forEach(q => { if (q.data) delete q.data.images; });

    let firmaEscrita = '';
    if (!hayImagenes) {
      // Sin imágenes: se libera el espacio de las que hubiera.
      if (_firmaImgGuardada !== '') { try { localStorage.removeItem(CLAVE_IMG); } catch (_) {} }
      _firmaImgGuardada = '';
      _firmaImgFallida = null;
    } else if (firma === _firmaImgGuardada) {
      firmaEscrita = firma; // ya están escritas: no se vuelve a serializar nada
    } else if (firma !== _firmaImgFallida) {
      try {
        localStorage.removeItem(CLAVE_IMG); // libera la versión anterior antes de escribir la nueva
        localStorage.setItem(CLAVE_IMG, JSON.stringify({ firma, porPregunta }));
        _firmaImgGuardada = firma;
        _firmaImgFallida = null;
        firmaEscrita = firma;
      } catch (e) {
        // No caben (o no se pueden guardar): el texto se guarda sin ellas y
        // no se reintenta con las mismas imágenes en cada tecla.
        _firmaImgGuardada = null;
        _firmaImgFallida = firma;
        try { localStorage.removeItem(CLAVE_IMG); } catch (_) {}
        if (_esFaltaDeEspacio(e)) {
          _avisarSinEspacio('El borrador no cabe en el espacio del navegador con las imágenes: se guarda sin ellas. Genera el XML o descarga tu trabajo para no perderlas.');
        }
      }
    }
    localStorage.setItem(CLAVE, JSON.stringify({
      savedAt: Date.now(), meta: estado.currentUploadMetadata, parse, firmaImg: firmaEscrita,
    }));
    // Se guardó todo bien: si más adelante vuelve a fallar, se avisa de nuevo.
    if (!hayImagenes || firmaEscrita) _avisoEspacio = false;
  } catch (e) {
    // Sin localStorage (modo privado) no es crítico: la revisión sigue
    // funcionando, solo no se podrá retomar. Pero si es que NO CABE, el
    // docente debe saberlo, una sola vez (no en cada tecla).
    if (_esFaltaDeEspacio(e)) {
      _avisarSinEspacio('El borrador no cabe en el espacio del navegador; guarda o descarga tu trabajo.');
    }
  }
}

/** Guarda con un retraso de 800 ms (se llama en cada tecla). */
export function guardarBorrador() {
  clearTimeout(_timer);
  _timer = setTimeout(guardarBorradorAhora, 800);
}

export function borrarBorrador() {
  clearTimeout(_timer);
  try { localStorage.removeItem(CLAVE); localStorage.removeItem(CLAVE_IMG); } catch (_) {}
  _firmaImgGuardada = null;
  _firmaImgFallida = null;
  mostrarAvisoBorrador();
}

/** Abre el editor con unos datos ya parseados (borrador o historial). */
export function abrirEnEditor(meta, parse) {
  estado.currentUploadMetadata = meta;
  // Un borrador de esta misma sesión aún tiene su original en el servidor; el Historial, no.
  estado.originalId = (parse && parse.original_id) || null;
  estado.selectedFile = null;
  estado.downloadBlob = null;
  showPanel('editor', { enfocar: false });
  reiniciarPanelPuntos();
  renderEditor(parse, { nuevo: true });
  document.getElementById('editor-title')?.focus({ preventScroll: true });
}

export function retomarBorrador() {
  const d = _leer({ conImagenes: true });
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
