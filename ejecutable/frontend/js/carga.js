/**
 * carga.js — subir el examen y pedir la conversión al backend
 * (incluye la lectura del progreso en vivo, que llega por NDJSON).
 */
import { guardarBorradorAhora } from './borrador.js';
import { btnConvert, categoryInput, dropZone, fileIconEl, fileInput, fileNameEl, filePreview, fileSizeEl } from './dom.js';
import { renderEditor } from './editor/tarjetas.js';
import { estado } from './estado.js';
import { showPanel } from './navegacion.js';
import { onProgressCount, onProgressStage, onUploadDone, onUploadProgress, startProgress, stopProgress } from './progreso.js';
import { autoDistributePoints } from './puntos.js';
import { subir } from './subida.js';
import { formatBytes, friendlyHttpError } from './util.js';

// El aviso bajo el botón explica por qué está deshabilitado.
function _setConvertEnabled(enabled) {
  btnConvert.disabled = !enabled;
  const hint = document.getElementById('convert-hint');
  if (hint) hint.style.display = enabled ? 'none' : 'block';
}

function _dropError(msg) {
  const el = document.getElementById('drop-error');
  if (!el) return;
  el.textContent = msg || '';
  el.style.display = msg ? 'block' : 'none';
  dropZone.classList.toggle('has-error', !!msg);
}

export function showFilePreview(file) {
  _dropError('');
  estado.selectedFile = file;
  estado.disclaimerAcknowledgedFor = null;
  fileNameEl.textContent = file.name;
  fileSizeEl.textContent = formatBytes(file.size);
  const isPdf = file.name.toLowerCase().endsWith('.pdf');
  fileIconEl.setAttribute('data-lucide', isPdf ? 'file-text' : 'file');
  lucide.createIcons();
  filePreview.style.display = 'flex';
  _setConvertEnabled(true);
  _marcarZona(file);
}

// La zona de carga se pinta de verde con el archivo elegido y cambia su
// texto; al quitarlo vuelve a su estado de "arrastra tu examen aquí".
function _marcarZona(file) {
  dropZone.classList.toggle('has-file', !!file);
  document.getElementById('drop-title').textContent = file ? 'Archivo listo' : 'Arrastra tu examen aquí';
  document.getElementById('drop-sub').textContent = file
    ? 'Arrastra otro o haz clic si quieres cambiarlo'
    : 'o haz clic para buscarlo en tu computadora';
  dropZone.setAttribute('aria-label', file
    ? `Archivo elegido: ${file.name}. Pulsa para elegir otro`
    : 'Elegir el examen: arrastra un archivo PDF o TXT, o pulsa para buscarlo');
}

export function clearFile() {
  estado.selectedFile = null;
  fileInput.value = '';
  filePreview.style.display = 'none';
  _setConvertEnabled(false);
  _marcarZona(null);
}

// Envía el resultado ya parseado (de /api/parse o /api/normalize_with_ai
// — misma forma de respuesta) directo al editor, guardando los metadatos
// de la subida para el paso de generar el XML más adelante.
function goToEditorWithParsedData(parsedData, ptsVal) {
  estado.currentUploadMetadata = {
    // macOS entrega los nombres en forma descompuesta (NFD): "Panamá" como
    // "Panama" + tilde suelta. Se normaliza para guardarlo y mostrarlo igual.
    filename: estado.selectedFile.name.normalize('NFC'),
    category: categoryInput.value.trim() || 'mis-preguntas',
    total_points: ptsVal
  };
  // Puntaje inicial por pregunta: mismo reparto por peso de tipo que
  // usaba el backend hasta ahora, pero ya visible y editable en el
  // editor — el docente que no toque nada obtiene el mismo resultado
  // de siempre, sin pasos extra.
  autoDistributePoints(parsedData.questions, ptsVal, 'byType');
  showPanel('editor', { enfocar: false });
  renderEditor(parsedData);
  lucide.createIcons();
  document.getElementById('editor-title')?.focus({ preventScroll: true });
  // Desde este momento la revisión ya se puede retomar si algo se cierra.
  guardarBorradorAhora();
}

// La respuesta de /api/*_stream es una línea JSON por evento (etapa,
// avance, resultado o error). Este lector recibe el texto ACUMULADO de
// la respuesta cada vez que llega algo, procesa solo las líneas nuevas y
// actualiza la pantalla de carga. Devuelve el evento final, si ya llegó.
function lectorDeAvance() {
  let consumido = 0;
  let buffer = '';
  let final = null;
  const procesar = linea => {
    const line = linea.trim();
    if (!line || final) return;
    let ev;
    try { ev = JSON.parse(line); } catch (_) { return; }
    if (ev.type === 'stage') onProgressStage(ev);
    else if (ev.type === 'progress') onProgressCount(ev);
    else if (ev.type === 'result' || ev.type === 'error') final = ev;
  };
  return {
    leer(texto) {
      buffer += texto.slice(consumido);
      consumido = texto.length;
      let nl;
      while ((nl = buffer.indexOf('\n')) >= 0) {
        procesar(buffer.slice(0, nl));
        buffer = buffer.slice(nl + 1);
      }
    },
    terminar() {
      procesar(buffer);
      buffer = '';
      return final || { type: 'error', status: 0, detail: 'La conexión con el servidor se cortó antes de terminar. Intenta de nuevo.' };
    },
  };
}

async function runStreamingConversion(endpoint, kind, ptsVal) {
  showPanel('progress');
  startProgress(kind);

  const formData = new FormData();
  formData.append('file', estado.selectedFile);
  const abort = new AbortController();
  estado.conversionAbort = abort;
  const lector = lectorDeAvance();

  try {
    // Con XMLHttpRequest (no fetch) para mostrar el avance real de la
    // subida de archivos grandes antes de que empiece el procesamiento.
    const res = await subir(endpoint, formData, {
      signal: abort.signal,
      onSubida: (enviados, total) => onUploadProgress(enviados, total),
      onSubido: onUploadDone,
      onTexto: texto => { if (texto) lector.leer(texto); },
    });
    if (res.status < 200 || res.status >= 300) {
      stopProgress(false);
      let errMsg = friendlyHttpError(res.status);
      try { const json = JSON.parse(res.text); errMsg = json.detail || errMsg; } catch (_) {}
      showError(errMsg);
      return;
    }
    lector.leer(res.text);
    const final = lector.terminar();
    if (final.type === 'error') {
      stopProgress(false);
      showError(final.detail || friendlyHttpError(final.status));
      return;
    }
    stopProgress(true);
    goToEditorWithParsedData(final.data, ptsVal);
  } catch (err) {
    stopProgress(false);
    if (err.name === 'AbortError') return; // cancelado a propósito
    showError('No se pudo conectar con el conversor. Cierra y vuelve a abrir la aplicación; si sigue igual, reinicia el equipo. (Detalle: ' + err.message + ')', 'upload', 'Sin conexión con el conversor');
  } finally {
    if (estado.conversionAbort === abort) estado.conversionAbort = null;
  }
}

// "Cancelar y volver" en la pantalla de progreso: corta la espera y deja
// al docente en el paso 1 con el mismo archivo ya elegido.
export function cancelConversion() {
  if (estado.conversionAbort) estado.conversionAbort.abort();
  estado.conversionAbort = null;
  stopProgress(false);
  showPanel('upload');
}

// Conversion Step 1: Parse
export function runConversion(ptsVal, kind = 'text') {
  return runStreamingConversion('/api/parse_stream', kind, ptsVal);
}

// Alternativa in-app al flujo externo de "copia este prompt y pégalo en
// tu IA": renderiza el documento completo y deja que Gemini lo lea
// visualmente (ver /api/normalize_with_ai) — tarda más que una
// conversión normal porque manda todas las páginas, no solo las que
// tienen imágenes detectadas.
export function runNormalizeWithAI(ptsVal) {
  return runStreamingConversion('/api/normalize_with_ai_stream', 'normalize', ptsVal);
}

export function handleFileSelected(file) {
  const ext = file.name.split('.').pop().toLowerCase();
  if (!['pdf', 'txt'].includes(ext)) {
    // Aviso en la misma zona de carga, sin sacar al docente del paso 1.
    fileInput.value = '';
    _dropError(`“${file.name}” no es un PDF ni un TXT. Elige un archivo .pdf o .txt.`);
    return;
  }
  showFilePreview(file);
}

// Error Handler. El título dice QUÉ falló (antes siempre era "Error en el
// Procesamiento") y el botón, a dónde vuelve.
export function showError(msg, returnTo = 'upload', title = null) {
  estado.errorReturnPanel = returnTo;
  document.getElementById('error-title').textContent = title
    || (returnTo === 'editor' ? 'No se pudo generar el XML' : 'No se pudo leer el examen');
  document.getElementById('btn-reset-error-label').textContent = returnTo === 'editor'
    ? 'Volver a la revisión'
    : 'Volver e intentar de nuevo';
  showPanel('error');
  const errorMessage = document.getElementById('error-message');
  const ocrHint = document.getElementById('error-ocr-hint');
  errorMessage.innerHTML = '';

  let textContent = '';
  if (typeof msg === 'object' && msg !== null && msg.errors) {
    const p = document.createElement('p');
    p.style.fontWeight = '700';
    p.textContent = msg.message || 'Se detectaron errores en la estructura del examen:';
    errorMessage.appendChild(p);
    const ul = document.createElement('ul');
    ul.style.paddingLeft = '18px';
    ul.style.marginTop = '6px';
    msg.errors.forEach(err => {
      const li = document.createElement('li');
      li.textContent = err;
      ul.appendChild(li);
      textContent += ' ' + err;
    });
    errorMessage.appendChild(ul);
  } else {
    errorMessage.textContent = String(msg);
    textContent = String(msg);
  }

  const isOcr = /escaneado|texto legible|sin texto|ocr/i.test(textContent);
  ocrHint.style.display = isOcr ? 'block' : 'none';
  if (isOcr) lucide.createIcons();
}
