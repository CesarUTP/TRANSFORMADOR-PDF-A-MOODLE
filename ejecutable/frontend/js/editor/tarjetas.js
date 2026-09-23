/**
 * tarjetas.js — dibuja cada pregunta del editor y vuelve a leerla del DOM.
 */
import { clozeBuildTextAndAnswer, initClozeBuilder, parseClozeSegments, renderClozeBuilder } from './cloze.js';
import { scrollToEditorCard } from './panel.js';
import { _editorTotalPoints } from './puntos-ui.js';
import { estado, notificar } from '../estado.js';
import { DEFAULT_TYPE_WEIGHTS, fmtPoints } from '../puntos.js';
import { showToast } from '../ui/toast.js';
import { esc_html, humanizeSkipReason, splitAnswers } from '../util.js';

// estado.currentParseResult es la única fuente de datos que usa renderEditor()
// para redibujar TODAS las tarjetas de golpe (al añadir una pregunta, o
// tras un reintento de generación fallido). Como nada más lo actualiza
// mientras el usuario edita o borra tarjetas a mano, hay que resincronizarlo
// con lo que de verdad hay en el DOM justo antes de cada re-render — si no,
// un renderEditor() puede "resucitar" preguntas que ya se habían borrado
// (estado.currentParseResult seguía teniendo la lista vieja completa) o revertir
// ediciones en curso a su texto original sin editar.
export function syncParseResultFromDOM() {
  const existingCards = document.querySelectorAll('.editor-card');
  // skipped_questions/completeness_notice/color_marks_notice no viven en
  // el DOM (son solo informativos, de la respuesta original de
  // /api/parse) — collectEditorData() no los conoce, así que se
  // preservan del estado anterior para que el aviso no desaparezca solo
  // por haber añadido o borrado una pregunta.
  const prevSkipped = estado.currentParseResult ? estado.currentParseResult.skipped_questions : undefined;
  const prevNotice = estado.currentParseResult ? estado.currentParseResult.completeness_notice : undefined;
  const prevColorNotice = estado.currentParseResult ? estado.currentParseResult.color_marks_notice : undefined;
  estado.currentParseResult = existingCards.length > 0
    ? collectEditorData()
    : { questions: [], answer_key: {} };
  if (prevSkipped) estado.currentParseResult.skipped_questions = prevSkipped;
  if (prevNotice) estado.currentParseResult.completeness_notice = prevNotice;
  if (prevColorNotice) estado.currentParseResult.color_marks_notice = prevColorNotice;
}

// Borrar una pregunta ya no es definitivo: el aviso ofrece "Deshacer"
// durante 6 s y la devuelve a su lugar con todo lo editado.
export function deleteQuestionCard(btn) {
  const card = btn.closest('.editor-card');
  if (card) {
    syncParseResultFromDOM();
    const pos = Array.from(document.querySelectorAll('.editor-card')).indexOf(card);
    const snapshot = JSON.parse(JSON.stringify(estado.currentParseResult));
    card.remove();
    syncParseResultFromDOM();
    // Vuelve a dibujar TODAS las tarjetas restantes (mismo patrón que
    // addNewQuestion/recoverSkippedQuestion) para que sus data-idx queden
    // al día con el array ya reindexado. Sin esto, borrar una SEGUNDA
    // tarjeta (sin que medie otro render de por medio) usaba el data-idx
    // viejo contra el array ya más corto, y una tarjeta se quedaba con
    // metadatos (color_review_hint, low_confidence, answer_from_marks) de
    // OTRA pregunta distinta a la que en verdad muestra en pantalla.
    renderEditor(estado.currentParseResult);
    lucide.createIcons();
    notificar('pregunta borrada');
    // El foco pasa a la tarjeta que ocupó su lugar (o a la anterior).
    const cards = document.querySelectorAll('.editor-card');
    cards[Math.min(pos, cards.length - 1)]?.focus({ preventScroll: true });
    showToast(`Pregunta ${pos + 1} eliminada`, 'info', {
      accion: { texto: 'Deshacer', alPulsar: () => {
        renderEditor(snapshot);
        lucide.createIcons();
        const back = document.querySelectorAll('.editor-card')[pos];
        if (back) scrollToEditorCard(back, { enfocar: true });
        showToast(`Pregunta ${pos + 1} restaurada`, 'info');
      } },
    });
  }
}

export function addNewQuestion(type) {
  syncParseResultFromDOM();
  const existingCards = document.querySelectorAll('.editor-card');
  const nextNum = existingCards.length + 1;

  let newQ = { num: nextNum, type: type, data: {} };
  let defaultAns = '';

  if (type === 'multichoice') {
    newQ.data = {
      stem: 'Escribe aquí el enunciado de la nueva pregunta de selección múltiple.',
      options: { A: 'Primera opción', B: 'Segunda opción', C: 'Tercera opción', D: 'Cuarta opción' }
    };
    defaultAns = 'Primera opción';
  } else if (type === 'truefalse') {
    newQ.data = { stem: 'Afirmación: Escribe aquí la afirmación para verdadero o falso.' };
    defaultAns = 'Verdadero';
  } else if (type === 'cloze') {
    newQ.data = { text: 'El concepto principal de [A: opción1 / opción2 / opción3] es clave.' };
    defaultAns = 'A. opción1';
  } else if (type === 'matching') {
    newQ.data = {
      stem: 'Relaciona cada concepto de la Columna A con su pareja en la Columna B.',
      col_a: { '1': 'Primer concepto', '2': 'Segundo concepto' },
      col_b: { 'a': 'Primera pareja', 'b': 'Segunda pareja' }
    };
    defaultAns = '1. Primer concepto → Primera pareja; 2. Segundo concepto → Segunda pareja';
  } else if (type === 'essay') {
    newQ.data = { stem: 'Escribe aquí la instrucción de la pregunta de ensayo (respuesta abierta).' };
    defaultAns = '';
  } else if (type === 'shortanswer') {
    newQ.data = { stem: 'Escribe aquí el enunciado de la pregunta de respuesta corta.' };
    defaultAns = 'Respuesta corta';
  } else if (type === 'numerical') {
    newQ.data = { stem: 'Escribe aquí el enunciado de la pregunta numérica.' };
    defaultAns = '0';
  }

  // Puntaje default para la pregunta nueva: el promedio de lo que ya
  // vale el resto (o un reparto equitativo si todavía no hay ninguna)
  // — nunca se recalculan las demás por el simple hecho de agregar una,
  // para no pisar ediciones manuales previas.
  const existingPoints = estado.currentParseResult.questions.map(q => Number(q.points) || 0).filter(p => p > 0);
  newQ.points = existingPoints.length
    ? Math.round((existingPoints.reduce((a, b) => a + b, 0) / existingPoints.length) * 100) / 100
    : Math.round((estado.currentUploadMetadata.total_points / (estado.currentParseResult.questions.length + 1)) * 100) / 100;

  estado.currentParseResult.questions.push(newQ);
  estado.currentParseResult.answer_key[nextNum] = { type: type, answer: defaultAns };

  renderEditor(estado.currentParseResult);
  lucide.createIcons();
  showToast(`Pregunta ${nextNum} (${QUESTION_TYPE_LABEL_MAP[type] || type}) añadida`);
  _irAPreguntaNueva(nextNum);
}

// Lleva a la pregunta recién añadida y pone el cursor en su enunciado
// (antes se intentaba mover el scroll de un contenedor que no tiene
// scroll propio, así que la página no se movía).
function _irAPreguntaNueva(num) {
  requestAnimationFrame(() => {
    const card = document.querySelector(`.editor-card[data-qnum="${num}"]`);
    if (!card) return;
    scrollToEditorCard(card);
    const campo = card.querySelector('textarea, input[type="text"]');
    (campo || card).focus({ preventScroll: true });
    if (campo && campo.select) campo.select();
  });
}

// "Rescata" una pregunta omitida cuyo único problema era la respuesta
// (el backend ya confirmó que el enunciado/opciones/columnas se
// parsearon bien — ver recoverable_data en validator.py) — la añade al
// editor con todo eso ya prellenado, para que el usuario solo tenga que
// marcar/escribir la respuesta correcta en vez de reconstruirla desde 0.
export function recoverSkippedQuestion(skippedIdx) {
  syncParseResultFromDOM();
  const sq = (estado.currentParseResult.skipped_questions || [])[skippedIdx];
  if (!sq || !sq.recoverable_data) return;

  const existingCards = document.querySelectorAll('.editor-card');
  const nextNum = existingCards.length + 1;
  const newQ = { num: nextNum, type: sq.type, data: JSON.parse(JSON.stringify(sq.recoverable_data)) };
  // Mismo puntaje default que "Añadir nueva pregunta": el promedio de
  // lo que ya vale el resto. Sin esto la pregunta rescatada entraba sin
  // `points`, su casilla salía vacía y el contador "X / Y pts" la
  // contaba como 0 sin que se notara por qué.
  const recoveredPeers = estado.currentParseResult.questions.map(q => Number(q.points) || 0).filter(p => p > 0);
  newQ.points = recoveredPeers.length
    ? Math.round((recoveredPeers.reduce((a, b) => a + b, 0) / recoveredPeers.length) * 100) / 100
    : Math.round((_editorTotalPoints() / (estado.currentParseResult.questions.length + 1)) * 100) / 100;

  // Respuesta en blanco por tipo — el usuario la completa a mano. Para
  // truefalse se deja "Verdadero" preseleccionado (el <select> siempre
  // necesita un valor), igual que hace "Añadir nueva pregunta"; el resto
  // arranca vacío para que sea evidente que falta completarlo.
  const blankAnswer = sq.type === 'truefalse' ? 'Verdadero' : '';
  estado.currentParseResult.answer_key[nextNum] = sq.type === 'matching'
    ? { type: sq.type, answer: '', pairs: {} }
    : { type: sq.type, answer: blankAnswer };

  estado.currentParseResult.questions.push(newQ);
  estado.currentParseResult.skipped_questions.splice(skippedIdx, 1);

  renderEditor(estado.currentParseResult);
  lucide.createIcons();
  showToast(`Pregunta ${nextNum} añadida — marca la respuesta correcta`, 'info');
  requestAnimationFrame(() => {
    const card = document.querySelector(`.editor-card[data-qnum="${nextNum}"]`);
    if (card) scrollToEditorCard(card, { enfocar: true });
  });
}

// ── Cloze builder ────────────────────────────────────────────────────
// Edita preguntas "completar" como bloques de texto + tarjetas de
// espacio-en-blanco (opciones + radio para marcar la correcta) en vez
// de exponer la sintaxis [A: opción1 / opción2] directamente. El texto
// con corchetes que el backend necesita se reconstruye automáticamente
// a partir de estas piezas — el usuario nunca tiene que escribirlo.

// Helper to extract Matching pairs from question and key info
function getMatchingPairs(q, keyInfo) {
  const pairs = [];
  const colA = (q.data && q.data.col_a) || {};
  const colB = (q.data && q.data.col_b) || {};
  const aKeys = Object.keys(colA).sort((a, b) => parseInt(a) - parseInt(b));

  // Priority 1: use the real número→letra answer key (keyInfo.pairs), so each
  // Columna A item is shown paired with its ACTUAL correct Columna B item —
  // not just whatever happens to share the same position (1st with 1st, etc.),
  // which is wrong whenever the correct order isn't literally 1-a, 2-b, 3-c...
  const pairsMap = (keyInfo && keyInfo.pairs) || {};
  if (Object.keys(pairsMap).length > 0) {
    aKeys.forEach(aKey => {
      const letter = String(pairsMap[aKey] || '').toLowerCase();
      const left = colA[aKey] || '';
      const right = letter && colB[letter] !== undefined ? colB[letter] : '';
      if (left || right) pairs.push({ left, right });
    });
  }

  // Fallback 1: legacy arrow-text key format "1. Item → Pareja"
  if (pairs.length === 0) {
    const rawKey = (keyInfo && keyInfo.answer) || '';
    const regex = /\d+\.\s*([^→;\n]+?)\s*→\s*([^;\n]+)/g;
    let match;
    while ((match = regex.exec(rawKey)) !== null) {
      pairs.push({ left: match[1].trim(), right: match[2].trim() });
    }
  }

  // Fallback 2: no reliable key at all — assume sequential 1-a, 2-b, 3-c order
  // (better than showing nothing, but may not reflect the real correct answer).
  if (pairs.length === 0 && aKeys.length > 0) {
    const bKeys = Object.keys(colB).sort();
    aKeys.forEach((aKey, idx) => {
      const left = colA[aKey] || '';
      const bKey = bKeys[idx];
      const right = bKey ? colB[bKey] : '';
      if (left || right) pairs.push({ left, right });
    });
  }

  if (pairs.length === 0) {
    pairs.push({ left: '', right: '' });
  }
  return pairs;
}

export function addMatchingPairRow(qIdx) {
  const container = document.getElementById(`matching-pairs-list-${qIdx}`);
  if (!container) return;
  const pairIdx = container.querySelectorAll('.matching-pair-row').length + 1;
  const tmp = document.createElement('div');
  tmp.innerHTML = _matchingPairRowHtml({ left: '', right: '' }, pairIdx);
  const row = tmp.firstElementChild;
  container.appendChild(row);
  lucide.createIcons();
  row.querySelectorAll('textarea').forEach(autoGrowTextarea);
  row.querySelector('.pair-left').focus();
}

function _matchingPairRowHtml(p, n) {
  return `<div class="matching-pair-row">
    <textarea class="pair-left form-input single-line" rows="1" placeholder="Concepto (columna A)" aria-label="Concepto ${n}, columna A">${esc_html(p.left)}</textarea>
    <i data-lucide="arrow-right" class="pair-arrow" aria-hidden="true"></i>
    <textarea class="pair-right form-input single-line" rows="1" placeholder="Su pareja correcta (columna B)" aria-label="Pareja correcta del concepto ${n}, columna B">${esc_html(p.right)}</textarea>
    <button type="button" class="btn btn-icon btn-danger-text" onclick="removeMatchingPairRow(this)" aria-label="Quitar la pareja ${n}" title="Quitar pareja">
      <i data-lucide="trash-2" style="width:15px;height:15px;"></i>
    </button>
  </div>`;
}

export function removeMatchingPairRow(btn) {
  const row = btn.closest('.matching-pair-row');
  const list = row?.parentElement;
  row?.remove();
  list?.querySelector('.matching-pair-row:last-child .pair-left')?.focus();
}

// Interactive Question Editor Renderer
//
// Orden de la pantalla (la tarea principal —revisar— va primero):
//   1. Avisos en UNA línea cada uno (omitidas plegadas, marcas del PDF).
//   2. Barra de herramientas plegada: Filtrar · Distribuir puntos.
//   3. Las tarjetas de pregunta.
//   4. "¿Falta alguna pregunta?" → Añadir pregunta, al final.
export function renderEditor(data) {
  estado.currentParseResult = data;
  const container = document.getElementById('editor-questions-container');
  const total = data.questions.length;

  // Subtítulo con el conteo real del examen.
  const sub = document.getElementById('editor-sub');
  if (sub) {
    const skippedN = (data.skipped_questions || []).length;
    sub.innerHTML = `${total} pregunta${total !== 1 ? 's' : ''}${skippedN ? ` · ${skippedN} no incluida${skippedN !== 1 ? 's' : ''}` : ''}. Compara cada una con tu documento: la transcripción puede traer errores o respuestas faltantes. <button type="button" class="text-link" onclick="openHelp('review')">¿Cómo reviso?</button>`;
  }

  // Preguntas que el sistema NO pudo procesar: una línea plegable con el
  // conteo; al abrirla, el motivo de cada una y cómo rescatarla.
  let skippedHtml = '';
  const skipped = data.skipped_questions || [];
  if (skipped.length > 0) {
    const skippedItems = skipped.map((sq, sIdx) => `
      <div class="skipped-item">
        <p class="skipped-preview">${sq.preview ? esc_html(sq.preview) : `<em>(sin texto identificable — tipo ${esc_html(QUESTION_TYPE_LABEL_MAP[sq.type] || sq.type)})</em>`}</p>
        <p class="skipped-reason">${esc_html(humanizeSkipReason(sq.reasons[0]))}</p>
        <p class="skipped-num">Ubicada como pregunta #${sq.num} — este número es del sistema, puede no coincidir con el del documento original.</p>
        ${sq.recoverable_data ? `<button type="button" class="btn btn-ghost btn-sm" onclick="recoverSkippedQuestion(${sIdx})" style="margin-top:8px;">
          <i data-lucide="wand-2" style="width:13px;height:13px;"></i> Añadir con lo ya extraído
        </button>` : ''}
      </div>`).join('');

    skippedHtml = `<details class="skipped-details">
      <summary>
        <i data-lucide="alert-triangle"></i>
        ${skipped.length} pregunta${skipped.length !== 1 ? 's' : ''} no se pud${skipped.length !== 1 ? 'ieron' : 'o'} incluir
        <span class="summary-more">Ver motivos <i data-lucide="chevron-down"></i></span>
      </summary>
      <div class="skipped-body">
        ${skippedItems}
        <p class="skipped-reason" style="margin-top:10px;padding-top:10px;border-top:1px solid var(--color-border-subtle);">
          Para incluirlas: corrige lo que falte en el documento original y vuelve a convertirlo, o agrégalas con "Añadir pregunta", al final de la lista.
        </p>
      </div>
    </details>`;
  }

  const completenessHtml = data.completeness_notice
    ? `<div class="callout is-warning"><i data-lucide="alert-triangle"></i><p>${esc_html(data.completeness_notice)}</p></div>` : '';

  // Aviso informativo (no de advertencia) de dónde salieron las
  // respuestas cuando el documento las marca. Neutro: el violeta es de
  // "Completar" y no se reutiliza para otro significado.
  const colorNoticeHtml = data.color_marks_notice
    ? `<div class="callout"><i data-lucide="highlighter"></i><p>${esc_html(data.color_marks_notice)}</p></div>` : '';

  const noticesHtml = (skippedHtml || completenessHtml || colorNoticeHtml)
    ? `<div class="editor-notices">${skippedHtml}${completenessHtml}${colorNoticeHtml}</div>` : '';

  // Barra de herramientas: dos botones plegados. Sus paneles se abren
  // debajo, de a uno.
  const typesPresent = [...new Set(data.questions.map(q => q.type))];
  const toolbarHtml = `<div class="editor-tools">
    <div class="editor-toolbar">
      <button type="button" class="btn btn-ghost toolbar-btn" onclick="toggleFilterMenu()" aria-expanded="false" aria-controls="filter-chips-bar">
        <i data-lucide="filter" style="width:16px;height:16px;"></i>
        Mostrar: <strong id="filter-current-label">Todas</strong>
        <i data-lucide="chevron-down" class="chev" aria-hidden="true"></i>
      </button>
      <button type="button" class="btn btn-ghost toolbar-btn" onclick="togglePointsToolMenu()" aria-expanded="false" aria-controls="points-tool-panel">
        <i data-lucide="calculator" style="width:16px;height:16px;"></i>
        Puntos: <strong id="points-assigned-label">0 / 0 pts</strong>
        <i data-lucide="chevron-down" class="chev" aria-hidden="true"></i>
      </button>
    </div>
    <div id="filter-chips-bar" class="collapsible-panel"></div>
    <div id="points-tool-panel" class="collapsible-panel" style="flex-direction:column;gap:12px;">
      <div style="display:flex;gap:8px;" role="group" aria-label="Cómo repartir los puntos">
        <button type="button" id="points-mode-equal" class="btn btn-ghost btn-sm" aria-pressed="false" onclick="setPointsToolMode('equal')" style="flex:1;">Igual para todas</button>
        <button type="button" id="points-mode-byType" class="btn btn-primary btn-sm" aria-pressed="true" onclick="setPointsToolMode('byType')" style="flex:1;">Según el tipo</button>
      </div>
      <p class="points-help">Cada número es un <strong style="color:var(--color-text);">peso relativo</strong>: un tipo con peso 2 vale el doble que uno con peso 1. A la derecha ves cuánto quedaría cada pregunta; el reparto siempre suma el total del examen, <strong style="color:var(--color-text);">${fmtPoints(_editorTotalPoints())} pts</strong>.</p>
      <div id="points-weights-editor" style="display:flex;flex-direction:column;gap:8px;">
        ${typesPresent.map(t => {
          const def = QUESTION_TYPE_DEFS.find(d => d.key === t) || { label: t, colorVar: 'var(--color-text)' };
          return `<div class="points-weight-row">
            <span class="type-name" style="color:${def.colorVar};">${def.label}</span>
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="points-weight-preview" data-type="${t}">—</span>
              <input type="number" class="form-input points-weight-input" data-type="${t}" min="0" step="0.5" value="${DEFAULT_TYPE_WEIGHTS[t] || 1}" aria-label="Peso relativo de ${def.label}" />
            </div>
          </div>`;
        }).join('')}
      </div>
      <button type="button" class="btn btn-primary btn-sm" onclick="applyPointsDistribution()">Aplicar a todas las preguntas</button>
    </div>
  </div>`;

  // "Añadir pregunta" al final: es una tarea ocasional, no debe estar
  // entre el docente y la primera pregunta.
  const addQuestionHtml = `<div class="add-question-block">
    <div class="add-head">
      <p>¿Falta alguna pregunta del documento?</p>
      <button type="button" class="btn btn-ghost btn-sm" onclick="toggleAddQuestionMenu()" aria-expanded="false" aria-controls="add-question-types">
        <i data-lucide="plus" style="width:15px;height:15px;"></i> Añadir pregunta
      </button>
    </div>
    <div id="add-question-types" class="collapsible-panel add-type-grid" role="group" aria-label="Tipo de la pregunta nueva" style="background:none;border:none;padding:0;margin:12px 0 0;">
      ${QUESTION_TYPE_DEFS.map(t => `<button type="button" class="filter-chip" data-filter="${t.key}" onclick="addNewQuestion('${t.key}')">
        <i data-lucide="plus" style="width:13px;height:13px;"></i> ${t.label}
      </button>`).join('')}
    </div>
  </div>`;

  // Todas las tarjetas se arman en un solo string y se insertan de una
  // vez (antes se hacía innerHTML += por cada pregunta, que vuelve a
  // parsear todo el contenedor en cada vuelta: lento con 50+ preguntas).
  const cardsHtml = data.questions.map((q, i) => _cardHtml(q, i, data.answer_key[q.num] || { answer: '' })).join('');

  container.innerHTML = noticesHtml + toolbarHtml + cardsHtml + addQuestionHtml;

  // Los campos de texto siempre muestran todo su contenido.
  container.querySelectorAll('.editor-card textarea').forEach(autoGrowTextarea);
  container.querySelectorAll('.cloze-builder').forEach(initClozeBuilder);
  _observarAncho(container);
  // Un solo aviso: los chips de filtro, el mapa del examen y el contador
  // de puntos se actualizan solos (ver suscripciones en app.js).
  notificar('editor redibujado');
  lucide.createIcons();
}

function _flagBadge(cls, icon, text, tip) {
  return `<span class="type-badge ${cls}" title="${esc_html(tip)}"><i data-lucide="${icon}"></i> ${text}</span>`;
}

function _cardHtml(q, i, keyInfo) {
  const needsReview = q.data.from_table || q.data.color_review_hint || q.data.low_confidence;
  const flags = [
    q.data.from_table && _flagBadge('flag-review', 'table-2', 'convertida de tabla', 'El sistema detectó un cuadro en el documento original y lo convirtió en esta pregunta de emparejamiento. Revísala con cuidado antes de generar el XML.'),
    q.data.color_review_hint && _flagBadge('flag-review', 'palette', 'revisar marca', 'Esta pregunta viene de una página con respuestas marcadas (color, resaltado, subrayado o negrita), pero el sistema no pudo leer la marca con certeza. Compara las opciones correctas con el documento original.'),
    q.data.low_confidence && _flagBadge('flag-review', 'eye-off', 'confianza baja', 'La IA no pudo leer con total claridad una imagen que esta pregunta necesita (código o marca borrosa o cortada). Compárala con el documento original.'),
    q.data.answer_from_marks && _flagBadge('flag-neutral', 'highlighter', 'respuesta por marca', 'La respuesta se tomó directamente de la marca del documento (color, resaltado, subrayado, negrita o X en un cuadro), leída del PDF sin que la IA la interprete.'),
  ].filter(Boolean).join('');

  let html = `<article class="editor-card" tabindex="-1" data-idx="${i}" data-qnum="${q.num}" data-qtype="${q.type}"${needsReview ? ' data-review="1"' : ''} aria-labelledby="q-title-${i}">
    <div class="card-head">
      <div class="card-title">
        <h3 id="q-title-${i}">Pregunta ${q.num}</h3>
        <span class="type-badge ${q.type}">${QUESTION_TYPE_LABEL_MAP[q.type] || esc_html(q.type)}</span>
      </div>
      <div class="card-meta">
        <input type="number" class="q-points form-input" step="0.01" min="0" value="${q.points != null ? esc_html(q.points) : ''}" aria-label="Puntos de la pregunta ${q.num}" title="Puntos que vale esta pregunta" />
        <span class="pts-unit" aria-hidden="true">pts</span>
        <button type="button" class="btn btn-icon btn-danger-text" onclick="deleteQuestionCard(this)" aria-label="Eliminar la pregunta ${q.num}" title="Eliminar pregunta">
          <i data-lucide="trash-2" style="width:15px;height:15px;"></i>
        </button>
      </div>
    </div>
    ${flags ? `<div class="card-flags">${flags}</div>` : ''}`;

  if (q.type !== 'cloze') {
    // El enunciado se ESCAPA: un examen con "<" o "</textarea>" rompía la
    // tarjeta (el texto se insertaba como HTML dentro del <textarea>).
    html += `<div><label class="field-label" for="q-stem-${i}">Enunciado</label><textarea id="q-stem-${i}" class="q-stem" rows="2">${esc_html(q.data.stem || '')}</textarea></div>`;
  }

  if (q.type === 'multichoice') {
    const optEntries = Object.entries(q.data.options || {});
    const answerTargets = splitAnswers(keyInfo.answer).map(s => s.toLowerCase());
    // Un objetivo de la clave que coincide EXACTO con el texto de
    // alguna opción es esa opción y NINGUNA otra: con opciones
    // A: Python / B: Java / C: JavaScript / D: C y la respuesta
    // "Java | C", antes se marcaban también JavaScript (por la letra
    // C, y porque "java" está contenido en "javascript").
    const allOptTexts = optEntries.map(([, txt]) => txt.trim().toLowerCase());
    const isOptCorrect = (letter, optText) => {
      const optClean = optText.trim().toLowerCase();
      return answerTargets.some(t => {
        if (t === optClean) return true;
        if (allOptTexts.includes(t)) return false;
        if (t === letter.toLowerCase()) return true;
        // Coincidencia parcial solo para respuestas largas (la clave trae
        // el texto completo de la opción en vez de su letra).
        if (t.length < 4 || optClean.length < 4) return false;
        return t.includes(optClean) || optClean.includes(t);
      });
    };
    html += `<fieldset style="margin-top:12px;border:none;padding:0;">
      <legend class="field-label" style="color:var(--color-success);">
        <i data-lucide="check-circle-2" style="width:14px;height:14px;"></i>
        Opciones — marca la(s) correcta(s)
      </legend>`;
    optEntries.forEach(([letter, optText]) => {
      const checked = isOptCorrect(letter, optText);
      const L = esc_html(letter);
      html += `<div class="mc-option-row">
        <input type="checkbox" id="q-opt-ok-${i}-${L}" class="q-opt-correct" data-letter="${L}" ${checked ? 'checked' : ''} aria-label="La opción ${L} es correcta" />
        <label for="q-opt-ok-${i}-${L}" class="mc-option-letter" title="Marcar como correcta">${L}</label>
        <input class="form-input q-opt" data-letter="${L}" value="${esc_html(optText)}" aria-label="Texto de la opción ${L}" />
      </div>`;
    });
    html += `<p class="card-note">Marca varias si la pregunta es de "selecciona todas las que correspondan".</p></fieldset>`;

  } else if (q.type === 'truefalse') {
    html += `<div style="margin-top:14px;"><label class="field-label" for="q-ans-${i}" style="color:var(--color-success);">Respuesta correcta</label>
      <select id="q-ans-${i}" class="q-ans form-input" style="border-color:var(--color-success);margin-top:6px;">
        <option value="Verdadero" ${keyInfo.answer.toLowerCase() === 'verdadero' ? 'selected' : ''}>Verdadero</option>
        <option value="Falso" ${keyInfo.answer.toLowerCase() === 'falso' ? 'selected' : ''}>Falso</option>
      </select>
    </div>`;

  } else if (q.type === 'cloze') {
    html += `<div><p class="field-label">Enunciado con espacios en blanco</p>
      <p class="card-note" style="margin:4px 0 8px;">Escribe el texto normal y pulsa <strong>Espacio en blanco</strong> donde falte una palabra; luego marca la opción correcta.</p>
    </div>`;
    const segments = parseClozeSegments(q.data.text || '', keyInfo.answer);
    html += renderClozeBuilder(i, segments);

  } else if (q.type === 'matching') {
    const pairs = getMatchingPairs(q, keyInfo);
    html += `<div class="matching-box">
      <p class="field-label" style="color:var(--color-success);margin-bottom:10px;">
        <i data-lucide="link-2" style="width:14px;height:14px;"></i>
        Parejas (concepto → su pareja correcta)
      </p>
      <div id="matching-pairs-list-${i}" class="matching-pairs-list">
        ${pairs.map((p, pIdx) => _matchingPairRowHtml(p, pIdx + 1)).join('')}
      </div>
      <button type="button" class="btn btn-ghost btn-sm btn-block" onclick="addMatchingPairRow(${i})" style="margin-top:10px;">
        <i data-lucide="plus" style="width:14px;height:14px;"></i> Agregar pareja
      </button>
    </div>`;

  } else if (q.type === 'essay') {
    html += `<p class="card-note" style="margin-top:10px;display:flex;gap:6px;align-items:flex-start;">
      <i data-lucide="pencil-line" style="width:14px;height:14px;color:var(--color-es);flex-shrink:0;margin-top:1px;"></i>
      Respuesta abierta: el docente la califica a mano en Moodle. No necesita respuesta correcta.
    </p>`;

  } else if (q.type === 'shortanswer') {
    html += `<div style="margin-top:14px;"><label class="field-label" for="q-sa-${i}" style="color:var(--color-success);">Respuesta correcta (palabra o frase corta)</label>
      <input id="q-sa-${i}" class="q-sa-answer form-input" style="border-color:var(--color-success);" value="${esc_html(keyInfo.answer || '')}" placeholder="Escribe la respuesta correcta" />
      <p class="card-note">Moodle no distingue mayúsculas y también acepta la respuesta sin tildes, pero una tilde mal puesta cuenta como error.</p>
    </div>`;

  } else if (q.type === 'numerical') {
    html += `<div style="margin-top:14px;"><label class="field-label" for="q-nu-${i}" style="color:var(--color-success);">Respuesta correcta (número)</label>
      <input id="q-nu-${i}" class="q-nu-answer form-input" type="number" step="any" style="border-color:var(--color-success);" value="${esc_html(keyInfo.answer || '')}" placeholder="Escribe el número correcto" />
    </div>`;
  }

  return html + `</article>`;
}

// Hace crecer un <textarea> verticalmente para mostrar todo su contenido
// sin barra de scroll interna ni redimensionado manual. Los campos de una
// sola línea lógica (parejas, fragmentos de completar) no aceptan Enter:
// en el XML serían un salto de línea que el docente no quiso escribir.
export function autoGrowTextarea(el) {
  // Una tarjeta oculta por el filtro no tiene medidas: se deja como está
  // y se recalcula al volver a mostrarse (ver filterQuestionsByType).
  if (el.getClientRects().length) {
    el.style.height = 'auto';
    el.style.height = (el.scrollHeight + 2) + 'px';
  }
  if (!el.dataset.autoGrowBound) {
    el.addEventListener('input', () => {
      el.style.height = 'auto';
      el.style.height = (el.scrollHeight + 2) + 'px';
    });
    if (el.classList.contains('single-line')) {
      el.addEventListener('keydown', e => { if (e.key === 'Enter') e.preventDefault(); });
    }
    el.dataset.autoGrowBound = '1';
  }
}

// Al cambiar el ancho de la ventana, los textos se re-envuelven y su
// alto cambia: sin esto el enunciado quedaba cortado tras redimensionar.
let _ro = null;
let _ultimoAncho = 0;
function _observarAncho(container) {
  if (_ro || typeof ResizeObserver === 'undefined') return;
  _ro = new ResizeObserver(entries => {
    const w = Math.round(entries[0].contentRect.width);
    if (w === _ultimoAncho) return;
    _ultimoAncho = w;
    requestAnimationFrame(() => container.querySelectorAll('.editor-card textarea').forEach(autoGrowTextarea));
  });
  _ro.observe(container);
}

export function collectEditorData() {
  const qs = [];
  const ak = {};
  const cards = document.querySelectorAll('.editor-card');

  cards.forEach((card, newIndex) => {
    const qNum = newIndex + 1; // Re-index questions cleanly 1, 2, 3...
    const idxAttr = card.getAttribute('data-idx');
    const originalQ = (estado.currentParseResult && estado.currentParseResult.questions && idxAttr !== null && estado.currentParseResult.questions[parseInt(idxAttr)]) 
                      ? estado.currentParseResult.questions[parseInt(idxAttr)] 
                      : { num: qNum, type: 'multichoice', data: {} };

    const newQ = JSON.parse(JSON.stringify(originalQ));
    newQ.num = qNum; // Update question number if additions/deletions happened

    // Puntaje propio de esta pregunta (editable a mano o por el panel
    // de "Distribuir puntos") — se manda tal cual al backend, que ya
    // no decide el puntaje, solo lo usa.
    const pointsEl = card.querySelector('.q-points');
    newQ.points = pointsEl ? (parseFloat(pointsEl.value) || 0) : 0;

    // Detect type from card badge
    const badgeEl = card.querySelector('.type-badge');
    if (badgeEl) {
      const typeClass = Array.from(badgeEl.classList).find(c => ['multichoice', 'truefalse', 'cloze', 'matching', 'essay', 'shortanswer', 'numerical'].includes(c));
      if (typeClass) newQ.type = typeClass;
    }

    if (newQ.type === 'multichoice' || newQ.type === 'truefalse' || newQ.type === 'matching' || newQ.type === 'essay' || newQ.type === 'shortanswer' || newQ.type === 'numerical') {
      const stemEl = card.querySelector('.q-stem');
      if (stemEl) newQ.data.stem = stemEl.value;
    }

    if (newQ.type === 'multichoice') {
      const optEls = card.querySelectorAll('.q-opt');
      newQ.data.options = newQ.data.options || {};
      optEls.forEach(optEl => {
        newQ.data.options[optEl.getAttribute('data-letter')] = optEl.value;
      });
      // Puede haber más de una casilla marcada ("selecciona todas las
      // que correspondan") — se unen con " | " para que el backend
      // sepa que son varias respuestas correctas, no solo una.
      const correctTexts = [];
      card.querySelectorAll('.q-opt-correct').forEach(cb => {
        if (cb.checked) {
          const letter = cb.getAttribute('data-letter');
          correctTexts.push(newQ.data.options[letter] || '');
        }
      });
      ak[qNum] = { type: newQ.type, answer: correctTexts.filter(Boolean).join(' | ') };

    } else if (newQ.type === 'truefalse') {
      const ansEl = card.querySelector('.q-ans');
      ak[qNum] = { type: newQ.type, answer: ansEl ? ansEl.value : 'Verdadero' };

    } else if (newQ.type === 'cloze') {
      const builderEl = card.querySelector('.cloze-builder');
      if (builderEl) {
        const { text, answer } = clozeBuildTextAndAnswer(builderEl);
        newQ.data.text = text;
        ak[qNum] = { type: newQ.type, answer };
      } else {
        ak[qNum] = { type: newQ.type, answer: '' };
      }

    } else if (newQ.type === 'matching') {
      const pairRows = card.querySelectorAll('.matching-pair-row');
      const colA = {};
      const colB = {};
      const pairsMap = {};
      const keyPairs = [];

      pairRows.forEach((row, pIdx) => {
        const leftVal = row.querySelector('.pair-left').value.trim();
        const rightVal = row.querySelector('.pair-right').value.trim();
        if (leftVal || rightVal) {
          const numKey = String(pIdx + 1);
          const letterKey = String.fromCharCode(97 + pIdx);
          colA[numKey] = leftVal;
          colB[letterKey] = rightVal;
          pairsMap[numKey] = letterKey;
          keyPairs.push(`${numKey}-${letterKey}`);
        }
      });

      newQ.data.col_a = colA;
      newQ.data.col_b = colB;
      ak[qNum] = { type: newQ.type, answer: keyPairs.join('; '), pairs: pairsMap };

    } else if (newQ.type === 'essay') {
      // Sin respuesta que guardar — se califica manualmente en Moodle.
      ak[qNum] = { type: newQ.type, answer: '' };

    } else if (newQ.type === 'shortanswer') {
      const ansEl = card.querySelector('.q-sa-answer');
      ak[qNum] = { type: newQ.type, answer: ansEl ? ansEl.value.trim() : '' };

    } else if (newQ.type === 'numerical') {
      const ansEl = card.querySelector('.q-nu-answer');
      ak[qNum] = { type: newQ.type, answer: ansEl ? ansEl.value.trim() : '' };
    }

    qs.push(newQ);
  });
  return { questions: qs, answer_key: ak };
}

// Stats Updater
export const QUESTION_TYPE_DEFS = [
  { key: 'multichoice', label: 'Opción múltiple', colorVar: 'var(--color-mc)', bgVar: 'var(--color-mc-bg)', borderVar: 'var(--color-mc-border)' },
  { key: 'truefalse',   label: 'Verdadero/Falso', colorVar: 'var(--color-tf)', bgVar: 'var(--color-tf-bg)', borderVar: 'var(--color-tf-border)' },
  { key: 'matching',    label: 'Emparejamiento', colorVar: 'var(--color-mt)', bgVar: 'var(--color-mt-bg)', borderVar: 'var(--color-mt-border)' },
  { key: 'cloze',       label: 'Completar',     colorVar: 'var(--color-cl)', bgVar: 'var(--color-cl-bg)', borderVar: 'var(--color-cl-border)' },
  { key: 'essay',       label: 'Ensayo',        colorVar: 'var(--color-es)', bgVar: 'var(--color-es-bg)', borderVar: 'var(--color-es-border)' },
  { key: 'shortanswer', label: 'Respuesta corta', colorVar: 'var(--color-sa)', bgVar: 'var(--color-sa-bg)', borderVar: 'var(--color-sa-border)' },
  { key: 'numerical',   label: 'Numérica',      colorVar: 'var(--color-nu)', bgVar: 'var(--color-nu-bg)', borderVar: 'var(--color-nu-border)' },
];

// Único mapa tipo→etiqueta en español, reusado por el badge de cada
// tarjeta, los chips de filtro, "Añadir pregunta", los avisos y el
// resumen final: un mismo tipo se llama igual en toda la app (antes
// convivían "Cierto/Falso" y "Verdadero/Falso", "Emparejar" y
// "Emparejamiento").
export const QUESTION_TYPE_LABEL_MAP = Object.fromEntries(QUESTION_TYPE_DEFS.map(t => [t.key, t.label]));
