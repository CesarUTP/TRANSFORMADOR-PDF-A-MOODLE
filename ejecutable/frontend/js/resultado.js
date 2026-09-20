/**
 * resultado.js — generar el XML, resumen final y descarga.
 */
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
// (con su `type` y `points` reales) — ya no depende del header
// X-Question-Stats del backend. Antes asumía un único "grade" uniforme
// por tipo (`count × gradePerQ`), que dejó de ser cierto en cuanto el
// docente puede poner un puntaje distinto a cada pregunta individual;
// ahora suma los puntos reales de cada una.
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

  // Balance final: si el modo tolerante omitió alguna pregunta (ver
  // renderEditor), se refleja aquí también, no solo en el editor — es
  // el resumen que el usuario se lleva de toda la conversión.
  const skippedCount = (estado.currentParseResult && estado.currentParseResult.skipped_questions)
    ? estado.currentParseResult.skipped_questions.length : 0;
  const skippedNote = skippedCount > 0
    ? ` · ${skippedCount} omitida${skippedCount !== 1 ? 's' : ''}`
    : '';
  document.getElementById('success-subtitle').textContent = `${total} pregunta${total !== 1 ? 's' : ''} extraída${total !== 1 ? 's' : ''}${skippedNote} • ${estado.downloadFilename}`;

  // Mismo motivo y misma solución que se mostraban en el editor, ahora
  // también aquí — para que no dependa de la memoria del docente entre
  // una pantalla y otra.
  const skippedNoticeEl = document.getElementById('success-skipped-notice');
  if (skippedCount > 0) {
    const skippedItemsHtml = estado.currentParseResult.skipped_questions.map(sq => `
      <li style="margin-bottom:6px;">
        <strong style="color:var(--color-text);">${esc_html(sq.preview ? sq.preview.slice(0, 80) : `Pregunta ${sq.num}`)}</strong>
        — ${esc_html(humanizeSkipReason(sq.reasons[0]))}
      </li>`).join('');
    skippedNoticeEl.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;font-weight:700;font-size:13.5px;color:var(--color-warning);margin-bottom:8px;">
        <i data-lucide="alert-triangle" style="width:16px;height:16px;"></i>
        ${skippedCount} pregunta${skippedCount !== 1 ? 's' : ''} no incluida${skippedCount !== 1 ? 's' : ''} en este XML
      </div>
      <ul style="margin:0 0 8px 20px;padding:0;font-size:13px;color:var(--color-text-muted);line-height:1.5;">${skippedItemsHtml}</ul>
      <p style="margin:0;font-size:12px;color:var(--color-text-subtle);">Para incluirlas: corrige lo que falte en el documento original y vuelve a convertirlo, o agrégalas manualmente la próxima vez con "Añadir nueva pregunta".</p>`;
    skippedNoticeEl.style.display = 'block';
    if (window.lucide) lucide.createIcons();
  } else {
    skippedNoticeEl.style.display = 'none';
  }

  // Solo entra a la lista (tarjeta + porción del pastel) el tipo que
  // realmente tiene preguntas en este examen — si no hubo, por ejemplo,
  // preguntas de completar, ese tipo simplemente no aparece en ningún
  // lado, en vez de mostrar una tarjeta en 0.
  const items = QUESTION_TYPE_DEFS
    .map(t => ({ ...t, count: counts[t.key], subtotal: sums[t.key] || 0 }))
    .filter(t => t.count > 0);

  // El subtotal ya es la SUMA real de los puntos de cada pregunta de
  // ese tipo (pueden valer distinto entre sí) — se muestra directo en
  // la tarjeta en vez de un "X pts/preg" que ya no describe nada si no
  // son todas iguales.
  document.getElementById('stats-grid').innerHTML = items.map(item => `
    <div class="stat-card" style="border-top:3px solid ${item.colorVar};">
      <div class="stat-num" style="color:${item.colorVar};">${item.count}</div>
      <div class="stat-label">${item.label}</div>
      ${item.subtotal ? `<div class="stat-grade" style="color:${item.colorVar};">${fmt(item.subtotal)}</div>` : ''}
    </div>
  `).join('');

  renderPointsPie(items);
}

function renderPointsPie(items) {
  const card = document.getElementById('points-chart-card');
  const svg = document.getElementById('points-pie-svg');
  const legend = document.getElementById('points-pie-legend');

  // Con 0 o 1 tipo presente un pastel no aporta nada (1 sola porción es
  // siempre el 100%) — se oculta la tarjeta entera en vez de mostrar un
  // círculo trivial.
  if (items.length < 2) { card.style.display = 'none'; return; }
  card.style.display = 'block';

  const grandTotal = items.reduce((sum, i) => sum + i.subtotal, 0) || 1;
  const cx = 100, cy = 100, r = 90;
  const gapDeg = 1.5; // separador angular entre porciones (spacer, no borde)
  const fmt = n => Number(n).toFixed(2).replace(/\.?0+$/, '') + ' pts';

  let cursor = 0;
  let svgHtml = '';
  let legendHtml = '';

  items.forEach(item => {
    const pct = item.subtotal / grandTotal * 100;
    const sweep = pct / 100 * 360;
    const start = cursor + gapDeg / 2;
    const end = Math.max(cursor + sweep - gapDeg / 2, start);
    cursor += sweep;

    const colorHex = getCssVar(item.colorVar.slice(4, -1)); // "var(--x)" -> "--x"
    const path = describeArcSlice(cx, cy, r, start, end);
    svgHtml += `<path d="${path}" fill="${item.colorVar}">
      <title>${item.label}: ${item.count} pregunta${item.count !== 1 ? 's' : ''} · ${fmt(item.subtotal)} (${pct.toFixed(1)}%)</title>
    </path>`;

    // Etiqueta directa solo si la porción es lo bastante ancha para que
    // el texto quepa cómodo (evita amontonar números en porciones finas).
    if (pct >= 8) {
      const mid = start + (end - start) / 2;
      const pos = polarToCartesian(cx, cy, r * 0.65, mid);
      svgHtml += `<text x="${pos.x}" y="${pos.y}" text-anchor="middle" dominant-baseline="middle" font-size="13" font-weight="800" fill="${textColorOnFill(colorHex)}">${pct.toFixed(0)}%</text>`;
    }

    // El porcentaje ya se ve en la propia porción del pastel — aquí solo
    // hace falta el subtotal en puntos, en una píldora con el mismo
    // color del tipo (tenue, como el type-badge de las tarjetas de
    // pregunta) para reforzar la identidad visual sin repetir el dato.
    // Los 3 elementos son hijos directos del grid de #points-pie-legend
    // (swatch / etiqueta / píldora), no un <div> por fila — así CSS
    // Grid alinea cada columna (etiqueta, píldora) al ancho de su
    // contenido más largo automáticamente, sin medir nada por JS y sin
    // el hueco irregular que dejaba una fila flex de ancho variable.
    legendHtml += `
      <span style="width:12px;height:12px;border-radius:3px;background:${item.colorVar};"></span>
      <span style="font-size:13px;font-weight:600;color:var(--color-text);white-space:nowrap;">${item.label}</span>
      <span style="font-size:12px;font-weight:700;color:${item.colorVar};background:${item.bgVar};border:1px solid ${item.borderVar};border-radius:var(--radius-sm);padding:3px 10px;white-space:nowrap;text-align:center;">${fmt(item.subtotal)}</span>
    `;
  });

  svg.innerHTML = svgHtml;
  legend.innerHTML = legendHtml;
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
      scrollToEditorCard(first);
    }
    showToast(incomplete === 1
      ? 'Falta completar 1 pregunta antes de aprobar'
      : `Faltan completar ${incomplete} preguntas antes de aprobar`, 'error');
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

  showPanel('progress');
  document.getElementById('progress-subtitle').textContent = 'Construyendo estructura Moodle XML...';
  document.getElementById('progress-bar-fill').style.transform = 'scaleX(0.6)';
  // Este paso es local (sin llamada a IA) y casi instantáneo — no tiene
  // sentido mostrar un tiempo transcurrido/estimado que quedó pegado
  // del paso anterior.
  document.getElementById('progress-timer-row').style.display = 'none';

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
    let filename = 'examen_moodle.xml';
    if (disposition && disposition.includes('filename=')) {
      const match = disposition.match(/filename="(.+)"/);
      if (match) filename = match[1];
    }

    const blob = await res.blob();
    estado.downloadBlob = blob;
    estado.downloadFilename = filename;

    // Después de guardar el nombre del archivo: el resumen lo muestra, y
    // si se calculaba antes salía un "•" suelto al final de la frase.
    updateSuccessStats(questions);
    showPanel('success');
    // El guardado nativo se dispara solo una vez, cuando el usuario
    // presiona "Descargar Moodle XML" — no automáticamente aquí, para
    // no pedirle guardar el mismo archivo dos veces seguidas.
  } catch (err) {
    stopProgress(false);
    showError("Error de comunicación: " + err.message, 'editor');
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
    return;
  }

  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
  showToast(successMsg);
}
