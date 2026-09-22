/**
 * tarjetas.js — dibuja cada pregunta del editor y vuelve a leerla del DOM.
 */
import { clozeBuildTextAndAnswer, initClozeBuilder, parseClozeSegments, renderClozeBuilder } from './cloze.js';
import { toggleFilterMenu } from './filtros.js';
import { _restorePanelsExpandedMode, _updateToggleAllPanelsLabel, toggleAddQuestionMenu, toggleAllPanels } from './paneles.js';
import { _editorTotalPoints, applyPointsDistribution, setPointsToolMode, togglePointsToolMenu } from './puntos-ui.js';
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

export function deleteQuestionCard(btn) {
  const card = btn.closest('.editor-card');
  if (card) {
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
    showToast('Pregunta eliminada de la lista', 'info');
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
  showToast(`Pregunta ${nextNum} (${type}) añadida exitosamente`);

  setTimeout(() => {
    const container = document.getElementById('editor-questions-container');
    container.scrollTop = container.scrollHeight;
  }, 100);
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
  showToast(`Pregunta ${nextNum} añadida — completa la respuesta correcta`, 'info');

  setTimeout(() => {
    const card = document.querySelector(`.editor-card[data-qnum="${nextNum}"]`);
    if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, 100);
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
  const div = document.createElement('div');
  div.className = 'matching-pair-row';
  div.style.cssText = 'display:grid;grid-template-columns:1fr auto 1fr auto;gap:8px;align-items:center;background:var(--color-surface);padding:8px 10px;border-radius:var(--radius-md);border:1px solid var(--color-border-subtle);margin-top:6px;';
  div.innerHTML = `
    <input class="pair-left form-input" value="" placeholder="Concepto (Columna A ${pairIdx})" />
    <span style="color:var(--color-accent);font-weight:bold;font-size:16px;">→</span>
    <input class="pair-right form-input" value="" placeholder="Pareja Correcta (Columna B ${pairIdx})" />
    <button type="button" class="btn btn-ghost" onclick="this.closest('.matching-pair-row').remove()" style="padding:6px 10px;color:var(--color-error);" title="Eliminar pareja">
      <i data-lucide="trash-2" style="width:15px;height:15px;"></i>
    </button>
  `;
  container.appendChild(div);
  lucide.createIcons();
}

// Interactive Question Editor Renderer
export function renderEditor(data) {
  estado.currentParseResult = data;
  const container = document.getElementById('editor-questions-container');
  container.innerHTML = '';

  // Aviso formal de revisión — antes se repetía idéntico en cada
  // tarjeta (ruido puro para alguien usando lector de pantalla al
  // pasar por 30-40 preguntas); ahora aparece una sola vez, arriba de
  // toda la lista.
  const reviewReminderHtml = data.questions.length > 0 ? `<div style="display:flex;gap:8px;align-items:flex-start;background:var(--color-warning-bg);border:1px solid var(--color-warning);border-radius:var(--radius-sm);padding:10px 12px;margin-bottom:18px;">
    <i data-lucide="shield-alert" style="width:14px;height:14px;color:var(--color-warning);flex-shrink:0;margin-top:1px;"></i>
    <p style="margin:0;font-size:12.5px;color:var(--color-text-muted);line-height:1.5;">Importante: revise cada pregunta de forma individual y confirme que no se hayan producido errores durante el proceso de normalización. De encontrarlos, corríjalos considerándolos como posibles errores de transcripción o respuestas faltantes.</p>
  </div>` : '';

  // Aviso de preguntas que el sistema NO pudo procesar (ej. de
  // respuesta abierta/no autocalificable, o sin ninguna respuesta que
  // la IA pudiera identificar) — en vez de bloquear toda la
  // conversión por una sola pregunta problemática, esas se excluyen y
  // se avisan aquí, con su motivo, para que el usuario decida si hace
  // falta revisarlas a mano en el examen original.
  let skippedHtml = '';
  const skipped = data.skipped_questions || [];
  if (skipped.length > 0 || data.completeness_notice) {
    // El enunciado (preview) va primero y en negrita — es lo único que
    // de verdad permite ubicar la pregunta en el documento original.
    // El número que asignó la IA se muestra aparte y aclarado como tal,
    // porque no necesariamente coincide con la numeración del PDF
    // original (la IA renumera todo limpio y secuencial).
    const skippedItems = skipped.map((sq, sIdx) => `
      <div style="padding:10px 0;border-top:1px solid var(--color-border-subtle);">
        <p style="margin:0 0 4px;font-size:13px;font-weight:700;color:var(--color-text);line-height:1.5;">
          ${sq.preview ? esc_html(sq.preview) : `<em>(sin texto identificable — tipo ${esc_html(QUESTION_TYPE_LABEL_MAP[sq.type] || sq.type)})</em>`}
        </p>
        <p style="margin:0;font-size:12px;color:var(--color-text-muted);line-height:1.5;">
          ${esc_html(humanizeSkipReason(sq.reasons[0]))}
        </p>
        <p style="margin:2px 0 0;font-size:12px;color:var(--color-text-subtle);">
          Ubicada como pregunta #${sq.num} — este número es del sistema, puede no coincidir con el del documento original.
        </p>
        ${sq.recoverable_data ? `<button type="button" class="btn btn-ghost" onclick="recoverSkippedQuestion(${sIdx})" style="margin-top:8px;padding:6px 12px;font-size:12px;color:var(--color-warning);border-color:var(--color-warning);">
          <i data-lucide="wand-2" style="width:13px;height:13px;"></i> Añadir con lo ya extraído — solo falta la respuesta
        </button>` : ''}
      </div>`).join('');

    skippedHtml = `<div style="background:var(--color-warning-bg);border:1px solid var(--color-warning);border-radius:var(--radius-md);padding:14px 16px;margin-bottom:18px;">
      <div style="display:flex;align-items:center;gap:8px;font-weight:700;font-size:13.5px;color:var(--color-warning);">
        <i data-lucide="alert-triangle" style="width:16px;height:16px;"></i>
        ${skipped.length > 0 ? `${skipped.length} pregunta${skipped.length !== 1 ? 's' : ''} no se pud${skipped.length !== 1 ? 'ieron' : 'o'} incluir` : 'Aviso'}
      </div>
      ${skipped.length > 0 ? `<div style="margin-top:4px;">${skippedItems}</div>` : ''}
      ${skipped.length > 0 ? `<p style="margin:10px 0 0;padding-top:10px;border-top:1px solid var(--color-border-subtle);font-size:12px;color:var(--color-text-muted);line-height:1.5;">
        <i data-lucide="lightbulb" style="width:13px;height:13px;vertical-align:-2px;"></i>
        Para incluirlas: corrige lo que falte en el documento original y vuelve a convertirlo, o agrégalas manualmente con "Añadir nueva pregunta" más abajo.
      </p>` : ''}
      ${data.completeness_notice ? `<p style="margin:${skipped.length > 0 ? '10px' : '8px'} 0 0;font-size:13px;color:var(--color-text-muted);line-height:1.5;">${esc_html(data.completeness_notice)}</p>` : ''}
    </div>`;
  }

  // Aviso informativo (no de advertencia): de dónde salieron las
  // respuestas cuando el documento las marca (color, resaltado,
  // subrayado, negrita o X en un cuadro). Lo arma el backend con lo que
  // de verdad detectó (ver pipeline._marks_notice); no bloquea nada.
  let colorNoticeHtml = '';
  if (data.color_marks_notice) {
    colorNoticeHtml = `<div style="background:var(--color-cl-bg);border:1px solid var(--color-cl-border);border-radius:var(--radius-md);padding:12px 16px;margin-bottom:18px;display:flex;gap:10px;align-items:flex-start;">
      <i data-lucide="info" style="width:16px;height:16px;color:var(--color-cl);flex-shrink:0;margin-top:1px;"></i>
      <p style="margin:0;font-size:13px;color:var(--color-text-muted);line-height:1.5;">${esc_html(data.color_marks_notice)}</p>
    </div>`;
  }

  // Botón único para expandir/colapsar los 3 paneles de abajo a la vez
  // (Filtrar / Añadir / Distribuir puntos) — interactuar con uno ya no
  // fuerza a cerrar los otros mientras este modo esté activo.
  const panelsToggleHtml = `<div style="display:flex;justify-content:flex-end;margin-bottom:8px;">
    <button type="button" class="btn btn-ghost" style="padding:6px 12px;font-size:12.5px;" onclick="toggleAllPanels()">
      <i data-lucide="chevrons-down-up" style="width:14px;height:14px;"></i>
      <span id="toggle-all-panels-label">Desplegar todo</span>
    </button>
  </div>`;

  // Barra de filtro: propia tarjeta de ancho completo. Los chips llevan
  // flex:1 (ver CSS .filter-chip) para repartirse todo el ancho entre
  // ellos, sin dejar espacio vacío a la derecha. El contenedor conserva
  // su id propio para poder refrescar solo los conteos
  // (refreshFilterChips) al borrar/añadir una pregunta, sin re-renderizar
  // toda la tarjeta ni perder ediciones en curso.
  const filterHtml = `<div style="background:var(--color-surface-hover);border:1px solid var(--color-border-subtle);border-radius:var(--radius-md);padding:10px 16px;margin-bottom:18px;">
    <button type="button" class="btn btn-ghost" style="width:100%;justify-content:flex-start;" onclick="toggleFilterMenu()">
      <i data-lucide="filter" style="width:16px;height:16px;"></i>
      Filtrar: <strong id="filter-current-label" style="margin-left:4px;">Todas</strong>
    </button>
    <div id="filter-chips-bar" style="display:none;align-items:stretch;flex-wrap:wrap;gap:8px;margin-top:10px;"></div>
  </div>`;

  // "Añadir nueva pregunta" arranca colapsado en un solo botón — al
  // hacerle clic se despliegan los 7 tipos; al elegir uno se agrega la
  // pregunta y (como addNewQuestion() llama a renderEditor() al final)
  // este bloque se reconstruye desde cero, así que vuelve a su estado
  // colapsado automáticamente sin código extra.
  const addQuestionHtml = `<div style="background:var(--color-surface-hover);border:1px solid var(--color-border-subtle);border-radius:var(--radius-md);padding:10px 16px;margin-bottom:18px;">
    <button type="button" class="btn btn-ghost" style="width:100%;justify-content:flex-start;" onclick="toggleAddQuestionMenu()">
      <i data-lucide="plus-circle" style="width:16px;height:16px;"></i> Añadir nueva pregunta
    </button>
    <div id="add-question-types" style="display:none;gap:8px;flex-wrap:wrap;margin-top:10px;">
      <button type="button" class="filter-chip" data-filter="multichoice" onclick="addNewQuestion('multichoice')">+ Múltiple</button>
      <button type="button" class="filter-chip" data-filter="truefalse" onclick="addNewQuestion('truefalse')">+ Cierto/Falso</button>
      <button type="button" class="filter-chip" data-filter="cloze" onclick="addNewQuestion('cloze')">+ Completar</button>
      <button type="button" class="filter-chip" data-filter="matching" onclick="addNewQuestion('matching')">+ Emparejamiento</button>
      <button type="button" class="filter-chip" data-filter="essay" onclick="addNewQuestion('essay')">+ Ensayo</button>
      <button type="button" class="filter-chip" data-filter="shortanswer" onclick="addNewQuestion('shortanswer')">+ Respuesta Corta</button>
      <button type="button" class="filter-chip" data-filter="numerical" onclick="addNewQuestion('numerical')">+ Numérica</button>
    </div>
  </div>`;

  // Panel de distribución rápida de puntos: cada pregunta ya trae un
  // puntaje editable a mano (ver el input junto al badge de tipo), pero
  // esto da una forma rápida de rellenar todos de una vez — repartido
  // parejo, o por peso configurable entre los tipos presentes en el
  // examen (para, por ejemplo, dar más peso a Ensayo que a
  // Verdadero/Falso). El contador "X / Y pts" es en vivo y no bloquea
  // nada: es solo una ayuda para notar un desbalance.
  const typesPresent = [...new Set(data.questions.map(q => q.type))];
  const pointsToolHtml = `<div style="background:var(--color-surface-hover);border:1px solid var(--color-border-subtle);border-radius:var(--radius-md);padding:10px 16px;margin-bottom:18px;">
    <button type="button" class="btn btn-ghost" style="width:100%;justify-content:flex-start;" onclick="togglePointsToolMenu()">
      <i data-lucide="calculator" style="width:16px;height:16px;"></i>
      Distribuir puntos — <strong id="points-assigned-label" style="margin-left:2px;">0 / 0 pts</strong>
    </button>
    <div id="points-tool-panel" style="display:none;flex-direction:column;gap:12px;margin-top:12px;">
      <div style="display:flex;gap:8px;">
        <button type="button" id="points-mode-equal" class="btn btn-ghost" onclick="setPointsToolMode('equal')" style="flex:1;">Equitativo</button>
        <button type="button" id="points-mode-byType" class="btn btn-primary" onclick="setPointsToolMode('byType')" style="flex:1;">Por tipo</button>
      </div>
      <div style="background:var(--color-cl-bg);border:1px solid var(--color-cl-border);border-radius:var(--radius-sm);padding:10px 12px;display:flex;gap:8px;align-items:flex-start;">
        <i data-lucide="info" style="width:14px;height:14px;color:var(--color-cl);flex-shrink:0;margin-top:2px;"></i>
        <div style="font-size:12px;color:var(--color-text-muted);line-height:1.65;">
          <strong style="color:var(--color-text);">¿Qué significa este número?</strong> Es un peso relativo, no el puntaje final: un tipo con peso 2 vale el doble que uno con peso 1, y con peso 3, el triple. Si todos los pesos son iguales, todas las preguntas valen lo mismo.
          <span style="display:block;margin-top:6px;">La columna de la derecha recalcula al instante cuánto quedaría cada pregunta, y el reparto siempre suma el total que definiste para este examen: <strong style="color:var(--color-text);">${fmtPoints(_editorTotalPoints())}</strong> pts.</span>
        </div>
      </div>
      <div id="points-weights-editor" style="display:flex;flex-direction:column;gap:8px;">
        ${typesPresent.map(t => {
          const def = QUESTION_TYPE_DEFS.find(d => d.key === t) || { label: t, colorVar: 'var(--color-text)' };
          return `<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
            <span style="font-size:13px;color:${def.colorVar};font-weight:700;">${def.label}</span>
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="points-weight-preview" data-type="${t}" style="font-size:11.5px;color:var(--color-text-subtle);min-width:78px;text-align:right;">—</span>
              <input type="number" class="form-input points-weight-input" data-type="${t}" min="0" step="0.5" value="${DEFAULT_TYPE_WEIGHTS[t] || 1}" style="width:70px;padding:6px 8px;font-size:12.5px;text-align:right;" aria-label="Peso relativo de ${def.label}" />
            </div>
          </div>`;
        }).join('')}
      </div>
      <button type="button" class="btn btn-primary" style="padding:10px;" onclick="applyPointsDistribution()">Aplicar</button>
      <p style="margin:0;font-size:11.5px;color:var(--color-text-subtle);">Esto reemplaza los puntos que ya hayas puesto a mano en cada pregunta.</p>
    </div>
  </div>`;

  container.innerHTML = reviewReminderHtml + skippedHtml + colorNoticeHtml + panelsToggleHtml + filterHtml + addQuestionHtml + pointsToolHtml;

  data.questions.forEach((q, i) => {
    const keyInfo = data.answer_key[q.num] || { answer: '' };
    const needsReview = q.data.from_table || q.data.color_review_hint || q.data.low_confidence;
    let html = `<div class="editor-card" data-idx="${i}" data-qnum="${q.num}" data-qtype="${q.type}"${needsReview ? ' data-review="1"' : ''}>
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:12px;">
        <strong style="color:var(--color-accent);font-size:15px;font-family:var(--font-heading);">Pregunta ${q.num}</strong>
        <div style="display:flex;align-items:center;justify-content:flex-end;flex-wrap:wrap;gap:10px;">
          ${q.data.from_table ? `<span class="type-badge" style="background:var(--color-warning-bg);color:var(--color-warning);border:1px solid var(--color-warning);" title="El sistema detectó una tabla/cuadro en el documento original y la convirtió automáticamente a esta pregunta de emparejamiento — revísala con cuidado antes de aprobar.">
            <i data-lucide="table-2" style="width:12px;height:12px;vertical-align:-2px;"></i> convertida de tabla
          </span>` : ''}
          ${q.data.color_review_hint ? `<span class="type-badge" style="background:var(--color-cl-bg);color:var(--color-cl);border:1px solid var(--color-cl-border);" title="Esta pregunta viene de una página con respuestas marcadas (color, resaltado, subrayado o negrita), pero el sistema no pudo leer la marca con certeza y la interpretó la IA. Compara las opciones correctas con el documento original, sobre todo si hay más de una marcada.">
            <i data-lucide="palette" style="width:12px;height:12px;vertical-align:-2px;"></i> revisar marca
          </span>` : ''}
          ${q.data.answer_from_marks ? `<span class="type-badge" style="background:transparent;color:var(--color-text-subtle);border:1px solid var(--color-border);" title="La respuesta se tomó directamente de la marca del documento (color, resaltado, subrayado, negrita o X en un cuadro), leída del PDF sin que la IA la interprete.">
            <i data-lucide="highlighter" style="width:12px;height:12px;vertical-align:-2px;"></i> respuesta por marca
          </span>` : ''}
          ${q.data.low_confidence ? `<span class="type-badge" style="background:var(--color-warning-bg);color:var(--color-warning);border:1px solid var(--color-warning);" title="La IA indicó que no pudo leer con total confianza una imagen que esta pregunta necesita (código o marca borrosa/cortada). Compárala con el documento original antes de aprobar.">
            <i data-lucide="eye-off" style="width:12px;height:12px;vertical-align:-2px;"></i> confianza baja
          </span>` : ''}
          <span class="type-badge ${q.type}">${QUESTION_TYPE_LABEL_MAP[q.type] || q.type}</span>
          <div style="display:flex;align-items:center;gap:4px;" title="Puntos que vale esta pregunta">
            <input type="number" class="q-points form-input" step="0.01" min="0" value="${q.points != null ? q.points : ''}" style="width:64px;padding:6px 8px;font-size:12.5px;text-align:right;" aria-label="Puntos de la pregunta ${q.num}" />
            <span style="font-size:11.5px;color:var(--color-text-subtle);">pts</span>
          </div>
          <button type="button" class="btn btn-ghost" onclick="deleteQuestionCard(this)" style="padding:4px 8px;color:var(--color-error);font-size:12px;" title="Eliminar esta pregunta">
            <i data-lucide="trash-2" style="width:14px;height:14px;"></i>
          </button>
        </div>
      </div>`;

    if (q.type === 'multichoice' || q.type === 'truefalse' || q.type === 'matching' || q.type === 'essay' || q.type === 'shortanswer' || q.type === 'numerical') {
      html += `<div><label class="field-label">Enunciado de la Pregunta</label><textarea class="q-stem" rows="2">${q.data.stem || ''}</textarea></div>`;
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
          // Fallback de coincidencia parcial: solo para respuestas largas
          // (la clave trae el texto completo de la opción en vez de su
          // letra). Con fragmentos cortos (ej. una sola letra) esto
          // marcaría por error cualquier opción que solo contenga esa
          // letra en su texto (ej. "B" calzando con "Berlín").
          if (t.length < 4 || optClean.length < 4) return false;
          return t.includes(optClean) || optClean.includes(t);
        });
      };
      html += `<div style="margin-top:12px;">
        <label class="field-label" style="color:var(--color-success);">
          <i data-lucide="check-circle-2" style="width:14px;height:14px;color:var(--color-success);"></i>
          Opciones — marca la(s) correcta(s)
        </label>
        <p style="font-size:11.5px;color:var(--color-text-subtle);margin:2px 0 4px;">Marca solo una si tiene una única respuesta correcta, o varias si es de "selecciona todas las que correspondan".</p>`;
      optEntries.forEach(([letter, optText]) => {
        const checked = isOptCorrect(letter, optText);
        html += `<div class="mc-option-row">
          <label style="display:contents;" title="Marcar como respuesta correcta">
            <input type="checkbox" class="q-opt-correct" data-letter="${letter}" ${checked ? 'checked' : ''} aria-label="Marcar la opción ${letter} como respuesta correcta" />
            <span class="mc-option-letter">${letter}</span>
          </label>
          <input class="form-input q-opt" data-letter="${letter}" value="${optText.replace(/"/g, '&quot;')}" />
        </div>`;
      });
      html += `</div>`;

    } else if (q.type === 'truefalse') {
      html += `<div style="margin-top:14px;"><label class="field-label" style="color:var(--color-success);">Respuesta Correcta (Verdadero / Falso)</label>
        <select class="q-ans form-input" style="border-color:var(--color-success);">
          <option value="Verdadero" ${keyInfo.answer.toLowerCase() === 'verdadero' ? 'selected' : ''}>Verdadero</option>
          <option value="Falso" ${keyInfo.answer.toLowerCase() === 'falso' ? 'selected' : ''}>Falso</option>
        </select>
      </div>`;

    } else if (q.type === 'cloze') {
      html += `<div><label class="field-label">Enunciado con espacios en blanco</label>
        <p style="font-size:12px;color:var(--color-text-subtle);margin:4px 0 8px;">Escribe la pregunta como texto normal. Donde falte una palabra, pulsa <strong>"+ Espacio en blanco"</strong> y luego escribe las opciones, marcando cuál es la correcta. Si un espacio admite más de una respuesta válida a la vez, activa "Permitir varias respuestas correctas" dentro de esa tarjeta.</p>
      </div>`;
      const segments = parseClozeSegments(q.data.text || '', keyInfo.answer);
      html += renderClozeBuilder(i, segments);

    } else if (q.type === 'matching') {
      const pairs = getMatchingPairs(q, keyInfo);
      html += `<div style="margin-top:14px;background:var(--color-bg);padding:14px;border-radius:var(--radius-md);border:1px solid var(--color-border);">
        <label class="field-label" style="color:var(--color-success);margin-bottom:10px;">
          <i data-lucide="link-2" style="width:14px;height:14px;color:var(--color-success);"></i>
          Parejas de Emparejamiento (Concepto Columna A → Pareja Columna B)
        </label>
        <div id="matching-pairs-list-${i}" style="display:flex;flex-direction:column;gap:8px;">`;

      pairs.forEach((p, pIdx) => {
        html += `<div class="matching-pair-row" style="display:grid;grid-template-columns:1fr auto 1fr auto;gap:8px;align-items:center;background:var(--color-surface);padding:8px 10px;border-radius:var(--radius-md);border:1px solid var(--color-border-subtle);">
          <input class="pair-left form-input" value="${p.left.replace(/"/g, '&quot;')}" placeholder="Concepto (Columna A)" />
          <span style="color:var(--color-accent);font-weight:bold;font-size:16px;">→</span>
          <input class="pair-right form-input" value="${p.right.replace(/"/g, '&quot;')}" placeholder="Pareja Correcta (Columna B)" />
          <button type="button" class="btn btn-ghost" onclick="this.closest('.matching-pair-row').remove()" style="padding:6px 10px;color:var(--color-error);" title="Eliminar pareja">
            <i data-lucide="trash-2" style="width:15px;height:15px;"></i>
          </button>
        </div>`;
      });

      html += `</div>
        <button type="button" class="btn btn-ghost" onclick="addMatchingPairRow(${i})" style="margin-top:10px;padding:8px 14px;font-size:12.5px;color:var(--color-accent);width:100%;">
          <i data-lucide="plus" style="width:14px;height:14px;"></i> Agregar Nueva Pareja
        </button>
      </div>`;

    } else if (q.type === 'essay') {
      html += `<div style="margin-top:10px;background:var(--color-es-bg);border:1px solid var(--color-es-border);border-radius:var(--radius-md);padding:10px 14px;display:flex;gap:8px;align-items:flex-start;">
        <i data-lucide="pencil-line" style="width:15px;height:15px;color:var(--color-es);flex-shrink:0;margin-top:2px;"></i>
        <p style="font-size:12.5px;color:var(--color-text-muted);margin:0;">Pregunta de respuesta abierta — el estudiante escribe libremente y el docente la califica manualmente en Moodle. No necesita una respuesta correcta aquí.</p>
      </div>`;

    } else if (q.type === 'shortanswer') {
      html += `<div style="margin-top:14px;"><label class="field-label" style="color:var(--color-success);">Respuesta Correcta (palabra o frase corta)</label>
        <input class="q-sa-answer form-input" style="border-color:var(--color-success);" value="${(keyInfo.answer || '').replace(/"/g, '&quot;')}" placeholder="Escribe la respuesta correcta" />
        <p style="font-size:11.5px;color:var(--color-text-subtle);margin:4px 0 0;">Moodle calificará esta respuesta sin distinguir mayúsculas de minúsculas, y el sistema añadirá automáticamente una variante sin tildes si la respuesta las lleva. Tenga en cuenta que una tilde ubicada incorrectamente sí se considerará una respuesta incorrecta. Le recomendamos considerar estas limitaciones antes de utilizar este tipo de pregunta.</p>
      </div>`;

    } else if (q.type === 'numerical') {
      html += `<div style="margin-top:14px;"><label class="field-label" style="color:var(--color-success);">Respuesta Correcta (número)</label>
        <input class="q-nu-answer form-input" type="number" step="any" style="border-color:var(--color-success);" value="${(keyInfo.answer || '').replace(/"/g, '&quot;')}" placeholder="Escribe el número correcto" />
      </div>`;
    }

    html += `</div>`;
    container.innerHTML += html;
  });

  // El enunciado siempre debe verse completo, sin recortarse ni
  // requerir que el usuario arrastre el borde del cuadro de texto.
  container.querySelectorAll('.editor-card textarea').forEach(autoGrowTextarea);
  container.querySelectorAll('.cloze-builder').forEach(initClozeBuilder);
  // Un solo aviso: los chips de filtro, el mapa del examen y el contador
  // de puntos se actualizan solos (ver suscripciones en app.js).
  notificar('editor redibujado');
  _restorePanelsExpandedMode();
  _updateToggleAllPanelsLabel();
  lucide.createIcons();
}

// Hace crecer un <textarea> verticalmente para mostrar todo su
// contenido sin barra de scroll interna ni redimensionado manual.
function autoGrowTextarea(el) {
  el.style.height = 'auto';
  el.style.height = (el.scrollHeight + 2) + 'px';
  if (!el.dataset.autoGrowBound) {
    el.addEventListener('input', () => {
      el.style.height = 'auto';
      el.style.height = (el.scrollHeight + 2) + 'px';
    });
    el.dataset.autoGrowBound = '1';
  }
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
  { key: 'multichoice', label: 'Múltiple',      colorVar: 'var(--color-mc)', bgVar: 'var(--color-mc-bg)', borderVar: 'var(--color-mc-border)' },
  { key: 'truefalse',   label: 'Cierto/Falso',  colorVar: 'var(--color-tf)', bgVar: 'var(--color-tf-bg)', borderVar: 'var(--color-tf-border)' },
  { key: 'matching',    label: 'Emparejar',     colorVar: 'var(--color-mt)', bgVar: 'var(--color-mt-bg)', borderVar: 'var(--color-mt-border)' },
  { key: 'cloze',       label: 'Completar',     colorVar: 'var(--color-cl)', bgVar: 'var(--color-cl-bg)', borderVar: 'var(--color-cl-border)' },
  { key: 'essay',       label: 'Ensayo',        colorVar: 'var(--color-es)', bgVar: 'var(--color-es-bg)', borderVar: 'var(--color-es-border)' },
  { key: 'shortanswer', label: 'Resp. Corta',   colorVar: 'var(--color-sa)', bgVar: 'var(--color-sa-bg)', borderVar: 'var(--color-sa-border)' },
  { key: 'numerical',   label: 'Numérica',      colorVar: 'var(--color-nu)', bgVar: 'var(--color-nu-bg)', borderVar: 'var(--color-nu-border)' },
];

// Único mapa tipo→etiqueta en español, reusado por el badge de cada
// tarjeta y por los chips de filtro — antes el badge de la tarjeta
// mostraba la clave interna en inglés (ej. "MULTICHOICE") en vez de
// "Múltiple", inconsistente con el resto de la interfaz.
export const QUESTION_TYPE_LABEL_MAP = Object.fromEntries(QUESTION_TYPE_DEFS.map(t => [t.key, t.label]));
