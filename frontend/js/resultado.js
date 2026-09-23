/**
 * resultado.js — generar el XML, resumen final y descarga.
 */
import { borrarBorrador, guardarBorradorAhora } from './borrador.js';
import { showError } from './carga.js';
import { selectFilter } from './editor/filtros.js';
import { buildReviewRail, refreshQuestionIssues, scrollToEditorCard } from './editor/panel.js';
import { QUESTION_TYPE_DEFS, collectEditorData } from './editor/tarjetas.js';
import { estado } from './estado.js';
import { showPanel } from './navegacion.js';
import { stopProgress } from './progreso.js';
import { showToast } from './ui/toast.js';
import { describeArcSlice, esc_html, friendlyHttpError, getCssVar, humanizeSkipReason, polarToCartesian, textColorOnFill } from './util.js';

// Recibe las preguntas TAL COMO se acaban de enviar a generar el XML
// (con su `type` y `points` reales) y arma el resumen final: una sola
// vista con preguntas y puntos por tipo (antes había tarjetas por tipo Y
// un pastel que repetían el mismo dato).
function updateSuccessStats(questions) {
  const fmt = n => Number(n).toFixed(2).replace(/\.?0+$/, '') + ' pts';
  const counts = {};
  const sums = {};
  QUESTION_TYPE_DEFS.forEach(t => { counts[t.key] = 0; sums[t.key] = 0; });
  (questions || []).forEach(q => {
    if (!(q.type in counts)) return;
    counts[q.type]++;
    sums[q.type] += Number(q.points) || 0;
  });
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const totalPts = Object.values(sums).reduce((a, b) => a + b, 0);

  const skippedCount = (estado.currentParseResult && estado.currentParseResult.skipped_questions)
    ? estado.currentParseResult.skipped_questions.length : 0;
  const skippedNote = skippedCount > 0
    ? ` · ${skippedCount} no incluida${skippedCount !== 1 ? 's' : ''}`
    : '';
  document.getElementById('success-subtitle').textContent =
    `${total} pregunta${total !== 1 ? 's' : ''}${skippedNote} · ${estado.downloadFilename}`;

  // Omitidas: mismo motivo que en el editor. Ahora se puede volver a la
  // revisión para añadirlas (antes el texto decía "la próxima vez").
  const skippedNoticeEl = document.getElementById('success-skipped-notice');
  if (skippedCount > 0) {
    const skippedItemsHtml = estado.currentParseResult.skipped_questions.map(sq => `
      <li style="margin-bottom:6px;">
        <strong style="color:var(--color-text);">${esc_html(sq.preview ? sq.preview.slice(0, 80) : `Pregunta ${sq.num}`)}</strong>
        — ${esc_html(humanizeSkipReason(sq.reasons[0]))}
      </li>`).join('');
    skippedNoticeEl.innerHTML = `
      <i data-lucide="alert-triangle"></i>
      <div style="min-width:0;">
        <p style="font-weight:700;font-size:13.5px;color:var(--color-warning);margin:0 0 6px;">${skippedCount} pregunta${skippedCount !== 1 ? 's' : ''} no incluida${skippedCount !== 1 ? 's' : ''} en este XML</p>
        <ul style="margin:0 0 8px 18px;padding:0;font-size:13px;line-height:1.5;">${skippedItemsHtml}</ul>
        <p style="margin:0;font-size:12px;">Para incluirlas, vuelve a la revisión y usa "Añadir pregunta", o corrige el documento original y conviértelo de nuevo.</p>
      </div>`;
    skippedNoticeEl.style.display = 'flex';
    if (window.lucide) lucide.createIcons();
  } else {
    skippedNoticeEl.style.display = 'none';
  }

  const items = QUESTION_TYPE_DEFS
    .map(t => ({ ...t, count: counts[t.key], subtotal: sums[t.key] || 0 }))
    .filter(t => t.count > 0);

  document.getElementById('points-pie-legend').innerHTML = items.map(item => `
    <span class="breakdown-swatch" style="background:${item.colorVar};"></span>
    <span class="breakdown-label">${item.label}</span>
    <span class="breakdown-count">${item.count} pregunta${item.count !== 1 ? 's' : ''}</span>
    <span class="breakdown-points" style="color:${item.colorVar};">${fmt(item.subtotal)}</span>
  `).join('') + `
    <span class="breakdown-total"></span>
    <span class="breakdown-total breakdown-label" style="font-weight:800;">Total</span>
    <span class="breakdown-total breakdown-count">${total} pregunta${total !== 1 ? 's' : ''}</span>
    <span class="breakdown-total breakdown-points" style="color:var(--color-text);">${fmt(totalPts)}</span>`;

  renderPointsPie(items);
}

// El pastel solo aparece con 2 tipos o más (con uno sería un círculo
// entero que no dice nada). La lista de al lado ya lleva los números.
// El color del texto de cada porción depende del tema: al cambiarlo se
// vuelve a dibujar con los colores nuevos.
let _ultimoPastel = null;
window.addEventListener('themechange', () => { if (_ultimoPastel) renderPointsPie(_ultimoPastel); });

function renderPointsPie(items) {
  _ultimoPastel = items;
  const svg = document.getElementById('points-pie-svg');
  // Un tipo con 0 pts no tiene porción (dibujaría solo una raya); y si al
  // final queda un solo tipo con puntos, el pastel sería un círculo entero.
  items = items.filter(i => i.subtotal > 0);
  if (items.length < 2) { svg.style.display = 'none'; return; }
  svg.style.display = '';

  const grandTotal = items.reduce((sum, i) => sum + i.subtotal, 0) || 1;
  const cx = 100, cy = 100, r = 90;
  // Separación entre porciones: un trazo del color de la tarjeta, de
  // grosor PAREJO. Antes era un hueco angular (1,5°), que por geometría
  // es una cuña: ancho en el borde y casi nulo hacia el centro.
  const sepColor = 'var(--color-surface)';
  const fmt = n => Number(n).toFixed(2).replace(/\.?0+$/, '') + ' pts';

  let cursor = 0;
  let svgHtml = '';

  items.forEach(item => {
    const pct = item.subtotal / grandTotal * 100;
    const sweep = pct / 100 * 360;
    const start = cursor;
    const end = cursor + sweep;
    cursor += sweep;

    const colorHex = getCssVar(item.colorVar.slice(4, -1)); // "var(--x)" -> "--x"
    const path = describeArcSlice(cx, cy, r, start, end);
    svgHtml += `<path d="${path}" fill="${item.colorVar}" stroke="${sepColor}" stroke-width="2.5" stroke-linejoin="round">
      <title>${item.label}: ${item.count} pregunta${item.count !== 1 ? 's' : ''} · ${fmt(item.subtotal)} (${pct.toFixed(1)}%)</title>
    </path>`;

    // Etiqueta directa solo si la porción es lo bastante ancha.
    if (pct >= 8) {
      const mid = start + (end - start) / 2;
      const pos = polarToCartesian(cx, cy, r * 0.65, mid);
      svgHtml += `<text x="${pos.x}" y="${pos.y}" text-anchor="middle" dominant-baseline="middle" font-size="13" font-weight="800" fill="${textColorOnFill(colorHex)}" aria-hidden="true">${pct.toFixed(0)}%</text>`;
    }
  });

  svg.innerHTML = svgHtml;
}

// Conversion Step 2: Generate XML
// Función nombrada (en vez de addEventListener) porque el botón vive
// dentro de editor-questions-container, cuyo innerHTML se reconstruye
// por completo en cada renderEditor() — un listener adjunto al nodo
// anterior se perdería con cada re-render.
export async function generateXml() {
  // Con preguntas incompletas el backend rechazaría el XML: se avisa
  // aquí y se lleva al docente a la primera, en vez de mostrar un error.
  const incomplete = refreshQuestionIssues();
  if (incomplete > 0) {
    buildReviewRail();
    const first = document.querySelector('#editor-questions-container .editor-card.is-incomplete');
    if (first) {
      if (first.style.display === 'none') selectFilter('all');
      scrollToEditorCard(first, { enfocar: true });
    }
    showToast(incomplete === 1
      ? 'Falta completar 1 pregunta antes de generar el XML'
      : `Faltan completar ${incomplete} preguntas antes de generar el XML`, 'error');
    return;
  }
  const { questions, answer_key } = collectEditorData();
  const payload = {
    filename: estado.currentUploadMetadata.filename,
    category: estado.currentUploadMetadata.category,
    total_points: estado.currentUploadMetadata.total_points,
    questions,
    answer_key
  };

  // Se guarda el borrador antes de salir del editor: si algo falla aquí,
  // el trabajo sigue a salvo.
  guardarBorradorAhora();
  showPanel('progress');
  document.getElementById('progress-title').textContent = 'Generando el archivo XML…';
  document.getElementById('progress-subtitle').textContent = 'Verificando cada pregunta y armando el archivo…';
  document.getElementById('progress-detail').textContent = '';
  document.getElementById('progress-bar-fill').style.transform = 'scaleX(0.6)';
  // Este paso es local (sin llamada a IA) y casi instantáneo: sin
  // cronómetro ni botón de cancelar.
  document.getElementById('progress-timer-row').style.display = 'none';
  document.getElementById('btn-cancel-progress').style.display = 'none';

  try {
    const res = await fetch('/api/generate_xml', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    stopProgress(res.ok);
    if (!res.ok) {
      let errMsg = friendlyHttpError(res.status);
      try { const json = await res.json(); errMsg = json.detail || errMsg; } catch (_) {}
      showError(errMsg, 'editor');
      return;
    }

    // Se usa directamente lo que se acaba de enviar (con el `points`
    // real de cada pregunta) en vez del header X-Question-Stats del
    // backend — una sola fuente de verdad, y el resumen final siempre
    // coincide exactamente con el XML que se generó.
    const disposition = res.headers.get('Content-Disposition');
    // El nombre real (con tildes) viene en filename*=UTF-8''…; filename="…"
    // es solo una versión ASCII de respaldo.
    let filename = 'examen_moodle.xml';
    const utf8 = disposition && disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const ascii = disposition && disposition.match(/filename="([^"]+)"/);
    if (utf8) {
      try { filename = decodeURIComponent(utf8[1]); } catch (_) { if (ascii) filename = ascii[1]; }
    } else if (ascii) {
      filename = ascii[1];
    }

    const blob = await res.blob();
    estado.downloadBlob = blob;
    estado.downloadFilename = filename;

    // Después de guardar el nombre del archivo: el resumen lo muestra, y
    // si se calculaba antes salía un "•" suelto al final de la frase.
    updateSuccessStats(questions);
    const dlLabel = document.getElementById('btn-download-label');
    if (dlLabel) dlLabel.textContent = 'Descargar Moodle XML';
    showPanel('success');
    // Ya quedó en el Historial (desde donde se puede reabrir): el
    // borrador local deja de hacer falta.
    borrarBorrador();
    // El guardado nativo se dispara solo una vez, cuando el usuario
    // presiona "Descargar Moodle XML" — no automáticamente aquí, para
    // no pedirle guardar el mismo archivo dos veces seguidas.
  } catch (err) {
    stopProgress(false);
    showError('No se pudo conectar con el conversor para generar el archivo. Tu revisión está intacta: vuelve e inténtalo de nuevo. (Detalle: ' + err.message + ')', 'editor');
  }
}

// Download XML Event
// Guarda un archivo en el equipo del usuario. Dentro de la app empaquetada
// (pywebview), el truco de <a download> con un blob: URL no dispara un
// diálogo real de "Guardar como" — la ventana nativa simplemente MUESTRA
// el contenido en pantalla en vez de descargarlo (el bug reportado con
// el historial). Por eso, cuando existe el puente pywebview.api, se usa
// save_xml_file() (implementado en Python, sí abre el diálogo nativo);
// el truco <a download> queda solo como respaldo para cuando se corre
// en un navegador normal (modo desarrollo, sin pywebview).
function _readBlobAsBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(reader.result.split(',')[1]);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

export async function saveFileToUser(blob, filename, successMsg) {
  if (window.pywebview && window.pywebview.api) {
    const b64 = await _readBlobAsBase64(blob);
    const res = await window.pywebview.api.save_xml_file(filename, b64);
    if (res && res.saved) showToast(successMsg);
    return !!(res && res.saved);
  }

  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
  showToast(successMsg);
  return true;
}
