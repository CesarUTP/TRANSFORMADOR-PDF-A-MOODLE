/**
 * cloze.js — constructor visual de preguntas de completar,
 * para no escribir la sintaxis de corchetes a mano.
 */
import { autoGrowTextarea } from './tarjetas.js';
import { showToast } from '../ui/toast.js';
import { esc_html, findClozeBrackets, splitAnswers, splitOptions } from '../util.js';

// Convierte el texto crudo "[A: opt1 / opt2]" (+ la respuesta guardada
// en la clave) en una lista ordenada de segmentos {type:'text', value}
// y {type:'blank', options, correctIndices, multi}. Un espacio "multi"
// permite marcar más de una opción como correcta (Moodle MULTIRESPONSE_S,
// casillas) en vez de una sola (MULTICHOICE_S, opción única).
export function parseClozeSegments(text, keyAnswer) {
  const keyMap = {}; // letra -> [respuestas correctas...]
  if (keyAnswer) {
    const keySlotRegex = /([A-Za-z])[\.:]\s*([^;\n]+)/g;
    let km;
    while ((km = keySlotRegex.exec(keyAnswer)) !== null) {
      const parts = splitAnswers(km[2]);
      if (parts.length) keyMap[km[1].toUpperCase()] = parts;
    }
  }

  const segments = [];
  let last = 0;
  findClozeBrackets(text).forEach(({ start, end, letter: rawLetter, optionsRaw }) => {
    if (start > last) segments.push({ type: 'text', value: text.slice(last, start) });
    const letter = rawLetter.toUpperCase();
    const options = splitOptions(optionsRaw);
    if (options.length === 0) options.push('', '');

    const wantedList = keyMap[letter] || [];
    let correctIndices = [];
    wantedList.forEach(wanted => {
      const idx = options.findIndex(o => o.toLowerCase() === wanted.toLowerCase());
      if (idx >= 0 && !correctIndices.includes(idx)) correctIndices.push(idx);
    });
    if (correctIndices.length === 0) correctIndices = [0];
    segments.push({ type: 'blank', options, correctIndices, multi: correctIndices.length > 1 });
    last = end;
  });
  if (last < (text || '').length || segments.length === 0) {
    segments.push({ type: 'text', value: (text || '').slice(last) });
  }
  return segments;
}

export function renderClozeBuilder(qIdx, segments) {
  let html = `<div class="cloze-builder" id="cloze-builder-${qIdx}">`;
  html += `<div class="cloze-preview"></div>`;
  let blankNum = 0;
  let textNum = 0;
  segments.forEach((seg) => {
    if (seg.type === 'text') {
      textNum++;
      // Textarea de una sola línea lógica que crece con el texto: antes
      // era un <input> y los fragmentos largos quedaban cortados.
      html += `<div class="cloze-text-row">
        <textarea class="form-input cloze-text-input single-line" rows="1" placeholder="Texto de la pregunta…" aria-label="Fragmento de texto ${textNum}">${esc_html(seg.value)}</textarea>
        <button type="button" class="cloze-insert-btn" data-accion="clozeInsertBlank" data-este title="Inserta un espacio en blanco donde esté el cursor"><i data-lucide="plus"></i> Espacio en blanco</button>
      </div>`;
    } else {
      const n = ++blankNum;
      const groupName = `cloze-correct-${qIdx}-${n}`;
      const inputType = seg.multi ? 'checkbox' : 'radio';
      html += `<div class="cloze-blank-card" role="group" aria-label="Espacio en blanco ${n}">
        <div class="cloze-blank-header">
          <strong><i data-lucide="circle-dot"></i> Espacio ${n} — marca la opción correcta</strong>
          <button type="button" class="btn btn-icon btn-danger-text" data-accion="clozeRemoveBlank" data-este aria-label="Quitar el espacio ${n}" title="Quitar este espacio">
            <i data-lucide="trash-2" style="width:14px;height:14px;"></i>
          </button>
        </div>
        <label class="cloze-multi-toggle">
          <input type="checkbox" class="cloze-multi-checkbox" ${seg.multi ? 'checked' : ''} data-accion-cambio="clozeToggleMulti" data-este />
          Permitir varias respuestas correctas en este espacio
        </label>
        <div class="cloze-options">`;
      seg.options.forEach((opt, oi) => {
        const isChecked = seg.correctIndices.includes(oi);
        html += `<div class="cloze-option-row">
          <input type="${inputType}" name="${groupName}" ${isChecked ? 'checked' : ''} aria-label="La opción ${oi + 1} es correcta" title="Marcar como respuesta correcta" />
          <input type="text" class="form-input cloze-option-input" value="${esc_html(opt)}" placeholder="Opción ${oi + 1}" aria-label="Opción ${oi + 1} del espacio ${n}" />
          <button type="button" class="btn btn-icon btn-danger-text" data-accion="clozeRemoveOption" data-este aria-label="Quitar la opción ${oi + 1}" title="Quitar esta opción">
            <i data-lucide="x" style="width:14px;height:14px;"></i>
          </button>
        </div>`;
      });
      html += `</div>
        <button type="button" class="btn btn-quiet btn-sm" style="margin-top:6px;" data-accion="clozeAddOption" data-este><i data-lucide="plus" style="width:13px;height:13px;"></i> Agregar opción</button>
      </div>`;
    }
  });
  html += `</div>`;
  return html;
}

function clozeGetBuilder(el) { return el.closest('.cloze-builder'); }

function clozeSegmentIndexOf(builderEl, el) {
  const list = Array.from(builderEl.querySelectorAll(':scope > .cloze-text-row, :scope > .cloze-blank-card'));
  return list.indexOf(el);
}

// Lee el estado actual (ya editado por el usuario) directamente del DOM.
function readClozeSegmentsFromDOM(builderEl) {
  const segments = [];
  builderEl.querySelectorAll(':scope > .cloze-text-row, :scope > .cloze-blank-card').forEach(el => {
    if (el.classList.contains('cloze-text-row')) {
      segments.push({ type: 'text', value: el.querySelector('.cloze-text-input').value });
    } else {
      const multi = !!el.querySelector('.cloze-multi-checkbox')?.checked;
      const options = [];
      const correctIndices = [];
      el.querySelectorAll('.cloze-option-row').forEach((row, idx) => {
        options.push(row.querySelector('.cloze-option-input').value);
        const marker = row.querySelector('input[type="radio"], input[type="checkbox"]');
        if (marker && marker.checked) correctIndices.push(idx);
      });
      segments.push({ type: 'blank', options, correctIndices, multi });
    }
  });
  return segments;
}

function clozeUpdatePreview(builderEl) {
  const preview = builderEl.querySelector('.cloze-preview');
  if (!preview) return;
  const segments = readClozeSegmentsFromDOM(builderEl);
  let html = '';
  segments.forEach(seg => {
    if (seg.type === 'text') {
      html += esc_html(seg.value);
    } else {
      const correctTexts = seg.correctIndices.map(i => seg.options[i]).filter(t => t && t.trim());
      const label = correctTexts.length ? correctTexts.map(esc_html).join(' + ') : '(elige una opción)';
      html += `<span class="blank-tag">${label} <i data-lucide="${seg.multi ? 'list-checks' : 'chevron-down'}"></i></span>`;
    }
  });
  preview.innerHTML = html.trim() ? html : '<em>Escribe el enunciado de la pregunta…</em>';
  if (window.lucide && preview.querySelector('[data-lucide]')) lucide.createIcons({ root: preview });
}

// Cambia un espacio de "una sola respuesta correcta" (radio) a "varias"
// (casillas) o viceversa. Al volver a "una sola" se conserva únicamente
// la primera opción que estuviera marcada, para no dejar el estado ambiguo.
export function clozeToggleMulti(checkbox) {
  const builderEl = clozeGetBuilder(checkbox);
  const card = checkbox.closest('.cloze-blank-card');
  const segments = readClozeSegmentsFromDOM(builderEl);
  const idx = clozeSegmentIndexOf(builderEl, card);
  const seg = segments[idx];
  seg.multi = checkbox.checked;
  if (!seg.multi && seg.correctIndices.length > 1) {
    seg.correctIndices = [seg.correctIndices[0]];
  }
  clozeRerender(builderEl, segments);
}

export function initClozeBuilder(builderEl) {
  builderEl.querySelectorAll('textarea').forEach(autoGrowTextarea);
  if (builderEl.dataset.bound) { clozeUpdatePreview(builderEl); return; }
  builderEl.addEventListener('input', () => clozeUpdatePreview(builderEl));
  builderEl.addEventListener('change', () => clozeUpdatePreview(builderEl));
  builderEl.dataset.bound = '1';
  clozeUpdatePreview(builderEl);
}

function clozeRerender(builderEl, segments) {
  const qIdx = builderEl.id.replace('cloze-builder-', '');
  const temp = document.createElement('div');
  temp.innerHTML = renderClozeBuilder(qIdx, segments);
  const newBuilderEl = temp.firstElementChild;
  builderEl.replaceWith(newBuilderEl);
  lucide.createIcons();
  initClozeBuilder(newBuilderEl);
}

export function clozeInsertBlank(btn) {
  const builderEl = clozeGetBuilder(btn);
  const row = btn.closest('.cloze-text-row');
  const input = row.querySelector('.cloze-text-input');
  const pos = input.selectionStart != null ? input.selectionStart : input.value.length;
  const before = input.value.slice(0, pos);
  const after = input.value.slice(pos);
  const segments = readClozeSegmentsFromDOM(builderEl);
  const idx = clozeSegmentIndexOf(builderEl, row);
  segments[idx] = { type: 'text', value: before };
  segments.splice(idx + 1, 0,
    { type: 'blank', options: ['Opción correcta', 'Opción incorrecta'], correctIndices: [0], multi: false },
    { type: 'text', value: after }
  );
  clozeRerender(builderEl, segments);
}

export function clozeRemoveBlank(btn) {
  const builderEl = clozeGetBuilder(btn);
  const card = btn.closest('.cloze-blank-card');
  const segments = readClozeSegmentsFromDOM(builderEl);
  const idx = clozeSegmentIndexOf(builderEl, card);
  const prev = segments[idx - 1], next = segments[idx + 1];
  if (prev && prev.type === 'text' && next && next.type === 'text') {
    prev.value = prev.value + next.value;
    segments.splice(idx, 2);
  } else {
    segments.splice(idx, 1);
  }
  if (segments.length === 0) segments.push({ type: 'text', value: '' });
  clozeRerender(builderEl, segments);
}

export function clozeAddOption(btn) {
  const builderEl = clozeGetBuilder(btn);
  const card = btn.closest('.cloze-blank-card');
  const segments = readClozeSegmentsFromDOM(builderEl);
  const idx = clozeSegmentIndexOf(builderEl, card);
  segments[idx].options.push('');
  clozeRerender(builderEl, segments);
}

export function clozeRemoveOption(btn) {
  const builderEl = clozeGetBuilder(btn);
  const card = btn.closest('.cloze-blank-card');
  const row = btn.closest('.cloze-option-row');
  const segments = readClozeSegmentsFromDOM(builderEl);
  const idx = clozeSegmentIndexOf(builderEl, card);
  if (segments[idx].options.length <= 2) {
    showToast('Cada espacio necesita al menos 2 opciones', 'info');
    return;
  }
  const optIdx = Array.from(card.querySelectorAll('.cloze-option-row')).indexOf(row);
  const seg = segments[idx];
  seg.options.splice(optIdx, 1);
  seg.correctIndices = seg.correctIndices
    .filter(i => i !== optIdx)
    .map(i => (i > optIdx ? i - 1 : i));
  if (seg.correctIndices.length === 0) seg.correctIndices = [0];
  clozeRerender(builderEl, segments);
}

// Reconstruye el texto "[A: opt1 / opt2]" y la clave de respuesta que
// el backend espera, a partir del estado actual del builder. Varias
// respuestas correctas para un mismo espacio se unen con " | " — eso
// es lo que hace que el backend elija MULTIRESPONSE_S en vez de
// MULTICHOICE_S al generar el XML.
export function clozeBuildTextAndAnswer(builderEl) {
  const segments = readClozeSegmentsFromDOM(builderEl);
  let text = '';
  let letterCode = 65; // 'A'
  const answerParts = [];
  segments.forEach(seg => {
    if (seg.type === 'text') {
      text += seg.value;
    } else {
      const letter = String.fromCharCode(letterCode++);
      const rawOpts = seg.options.map(o => o.trim());
      const rawCorrectTexts = seg.correctIndices.map(i => rawOpts[i]).filter(Boolean);
      // Las opciones vacías (filas agregadas y nunca completadas) se
      // omiten para no dejar una alternativa en blanco en el desplegable
      // final que vería el estudiante en Moodle.
      const opts = rawOpts.filter(o => o.length > 0);
      let correctTexts = rawCorrectTexts.filter(t => opts.includes(t));
      if (correctTexts.length === 0 && opts.length > 0) correctTexts = [opts[0]];
      text += `[${letter}: ${opts.join(' / ')}]`;
      answerParts.push(`${letter}. ${correctTexts.join(' | ')}`);
    }
  });
  return { text, answer: answerParts.join('; ') };
}
