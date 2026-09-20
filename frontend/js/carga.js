/**
 * carga.js — subir el examen y pedir la conversión al backend
 * (incluye la lectura del progreso en vivo, que llega por NDJSON).
 */
import { btnConvert, categoryInput, fileIconEl, fileInput, fileNameEl, filePreview, fileSizeEl } from './dom.js';
import { expandirPanelesPorDefecto } from './editor/paneles.js';
import { renderEditor } from './editor/tarjetas.js';
import { estado } from './estado.js';
import { showPanel } from './navegacion.js';
import { onProgressCount, onProgressStage, startProgress, stopProgress } from './progreso.js';
import { autoDistributePoints } from './puntos.js';
import { formatBytes, friendlyHttpError } from './util.js';

export function showFilePreview(file) {
  estado.selectedFile = file;
  estado.disclaimerAcknowledgedFor = null;
  fileNameEl.textContent = file.name;
  fileSizeEl.textContent = formatBytes(file.size);
  const isPdf = file.name.toLowerCase().endsWith('.pdf');
  fileIconEl.setAttribute('data-lucide', isPdf ? 'file-text' : 'file');
  lucide.createIcons();
  filePreview.style.display = 'flex';
  btnConvert.disabled = false;
}

export function clearFile() {
  estado.selectedFile = null;
  fileInput.value = '';
  filePreview.style.display = 'none';
  btnConvert.disabled = true;
}

// Envía el resultado ya parseado (de /api/parse o /api/normalize_with_ai
// — misma forma de respuesta) directo al editor, guardando los metadatos
// de la subida para el paso de generar el XML más adelante.
function goToEditorWithParsedData(parsedData, ptsVal) {
  estado.currentUploadMetadata = {
    filename: estado.selectedFile.name,
    category: categoryInput.value.trim() || 'mis-preguntas',
    total_points: ptsVal
  };
  // Puntaje inicial por pregunta: mismo reparto por peso de tipo que
  // usaba el backend hasta ahora, pero ya visible y editable en el
  // editor — el docente que no toque nada obtiene el mismo resultado
  // de siempre, sin pasos extra.
  autoDistributePoints(parsedData.questions, ptsVal, 'byType');
  showPanel('editor');
  // Cada examen nuevo abre el editor con los 3 paneles desplegados,
  // aunque en el anterior el docente los haya ocultado.
  expandirPanelesPorDefecto();
  renderEditor(parsedData);
  lucide.createIcons();
}

// Lee la respuesta de /api/*_stream: una línea JSON por evento
// (etapa, avance, resultado o error). Devuelve el evento final
// ("result" o "error") y va actualizando la pantalla de carga con el
// avance real mientras llega.
export async function readProgressStream(res) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nl;
    while ((nl = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (!line) continue;
      let ev;
      try { ev = JSON.parse(line); } catch (_) { continue; }
      if (ev.type === 'stage') onProgressStage(ev);
      else if (ev.type === 'progress') onProgressCount(ev);
      else if (ev.type === 'result' || ev.type === 'error') return ev;
    }
  }
  return { type: 'error', status: 0, detail: 'La conexión con el servidor se cortó antes de terminar. Intenta de nuevo.' };
}

async function runStreamingConversion(endpoint, kind, ptsVal) {
  showPanel('progress');
  startProgress(kind);

  const formData = new FormData();
  formData.append('file', estado.selectedFile);

  try {
    const res = await fetch(endpoint, { method: 'POST', body: formData });
    if (!res.ok || !res.body) {
      stopProgress(false);
      let errMsg = friendlyHttpError(res.status);
      try { const json = await res.json(); errMsg = json.detail || errMsg; } catch (_) {}
      showError(errMsg);
      return;
    }
    const final = await readProgressStream(res);
    if (final.type === 'error') {
      stopProgress(false);
      showError(final.detail || friendlyHttpError(final.status));
      return;
    }
    stopProgress(true);
    goToEditorWithParsedData(final.data, ptsVal);
  } catch (err) {
    stopProgress(false);
    showError("No se pudo conectar con el servidor backend: " + err.message);
  }
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
    showError(`Formato no soportado ".${ext}". Selecciona un archivo .pdf o .txt.`);
    return;
  }
  showFilePreview(file);
}

// Error Handler
export function showError(msg, returnTo = 'upload') {
  estado.errorReturnPanel = returnTo;
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
