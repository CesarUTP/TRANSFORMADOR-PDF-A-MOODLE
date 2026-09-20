/**
 * puntos-ui.js — panel "Distribuir puntos" (el cálculo vive en js/puntos.js).
 */
import { _closeOtherCollapsiblePanels, _collapsePanelByHand, _openCollapsiblePanel, _updateToggleAllPanelsLabel } from './paneles.js';
import { renderEditor, syncParseResultFromDOM } from './tarjetas.js';
import { estado } from '../estado.js';
import { autoDistributePoints, fmtPoints } from '../puntos.js';
import { showToast } from '../ui/toast.js';

// ── Panel "Distribuir puntos" ──────────────────────────────────────────
export function togglePointsToolMenu() {
  const el = document.getElementById('points-tool-panel');
  if (!el) return;
  if (el.classList.contains('panel-open')) {
    _collapsePanelByHand(el);
  } else {
    _closeOtherCollapsiblePanels('points-tool-panel');
    _openCollapsiblePanel(el, 'flex');
    updatePointsWeightPreview();
  }
  _updateToggleAllPanelsLabel();
}

// Puntos totales del examen: SIEMPRE los que el docente escribió al
// subir el archivo (nunca un 100 asumido) — un único lugar del que
// leerlos, para que el panel, la vista previa y el contador no puedan
// quedar diciendo cosas distintas.
export function _editorTotalPoints() {
  const t = estado.currentUploadMetadata ? Number(estado.currentUploadMetadata.total_points) : NaN;
  return Number.isFinite(t) && t > 0 ? t : 0;
}
// Formato corto y sin ceros de relleno (2.50 → "2.5", 20.00 → "20").

// Lee los pesos escritos en el panel "Por tipo". Es la ÚNICA lectura de
// esos inputs: la vista previa y el botón "Aplicar" la comparten a
// propósito, porque antes cada una interpretaba distinto un campo vacío
// (la vista previa lo tomaba como 0 y "Aplicar" como 1), así que el
// reparto que se aplicaba no era el que la vista previa había
// prometido. Un campo vacío o con basura vale 1 (peso neutro); un 0
// escrito a propósito sí se respeta.
function readTypeWeights() {
  const weights = {};
  document.querySelectorAll('.points-weight-input').forEach(inp => {
    const v = parseFloat(inp.value);
    weights[inp.dataset.type] = Number.isFinite(v) && v >= 0 ? v : 1;
  });
  return weights;
}

// Cambia entre "Equitativo" (sin configuración) y "Por tipo" (muestra
// el peso editable de cada tipo presente) — no aplica nada todavía,
// solo decide qué hace el botón "Aplicar".
let _pointsToolMode = 'byType';

export function setPointsToolMode(mode) {
  _pointsToolMode = mode;
  const equalBtn = document.getElementById('points-mode-equal');
  const byTypeBtn = document.getElementById('points-mode-byType');
  const weightsEditor = document.getElementById('points-weights-editor');
  if (equalBtn) equalBtn.className = mode === 'equal' ? 'btn btn-primary' : 'btn btn-ghost';
  if (byTypeBtn) byTypeBtn.className = mode === 'byType' ? 'btn btn-primary' : 'btn btn-ghost';
  if (equalBtn) equalBtn.style.flex = '1';
  if (byTypeBtn) byTypeBtn.style.flex = '1';
  if (weightsEditor) weightsEditor.style.display = (mode === 'byType') ? 'flex' : 'none';
}

// Botón "Aplicar": recalcula el puntaje de TODAS las preguntas visibles
// según el modo elegido y vuelve a renderizar — se avisa por toast que
// esto reemplaza cualquier valor puesto a mano, ya que no hay forma de
// aplicarlo solo a algunas sin resultar confuso.
export function applyPointsDistribution() {
  // Los pesos que el docente acaba de escribir viven en inputs que
  // renderEditor() va a reconstruir desde cero más abajo — hay que
  // leerlos ANTES de perderlos, y guardarlos para volver a pintarlos
  // en el panel ya aplicado (si no, el panel se veía "reiniciado" al
  // pulsar Aplicar, como si no hubiera pasado nada).
  const mode = _pointsToolMode;
  const weights = readTypeWeights();

  syncParseResultFromDOM();
  const totalPoints = _editorTotalPoints();
  if (!totalPoints) {
    showToast('No hay un total de puntos definido para este examen', 'error');
    return;
  }
  autoDistributePoints(estado.currentParseResult.questions, totalPoints, mode, weights);
  renderEditor(estado.currentParseResult);
  lucide.createIcons();

  // Reabre el panel con el mismo modo y los mismos pesos que el
  // docente acababa de configurar, para que vea de inmediato el
  // resultado sobre las tarjetas de abajo en vez de que el panel se
  // cierre solo y parezca que no pasó nada.
  setPointsToolMode(mode);
  document.querySelectorAll('.points-weight-input').forEach(inp => {
    if (inp.dataset.type in weights) inp.value = weights[inp.dataset.type];
  });
  updatePointsWeightPreview();
  const panel = document.getElementById('points-tool-panel');
  if (panel && !panel.classList.contains('panel-open')) {
    _closeOtherCollapsiblePanels('points-tool-panel');
    _openCollapsiblePanel(panel, 'flex');
  }
  _updateToggleAllPanelsLabel();

  // El toast dice el resultado concreto (no solo "listo"): con el panel
  // abierto y la lista de preguntas abajo, es la señal más clara de que
  // el botón sí hizo algo y de cuánto se repartió en total.
  showToast(
    `${fmtPoints(totalPoints)} pts repartidos entre ${estado.currentParseResult.questions.length} preguntas — revisa cada una antes de generar el XML`,
    'info'
  );
}

// Contador en vivo "X / Y pts": no bloquea nada, solo ayuda a notar un
// desbalance mientras el docente edita puntos a mano. Delegado a nivel
// de contenedor para no tener que atar un listener a cada input nuevo
// cada vez que se renderiza el editor.
export function updatePointsAssignedLabel() {
  const label = document.getElementById('points-assigned-label');
  if (!label) return;
  let sum = 0;
  document.querySelectorAll('.q-points').forEach(inp => { sum += parseFloat(inp.value) || 0; });
  const total = _editorTotalPoints();
  label.textContent = `${fmtPoints(sum)} / ${fmtPoints(total)} pts`;
}

// Vista previa en vivo del panel "Por tipo": mientras el docente
// escribe un peso, se calcula al instante cuánto le tocaría a cada
// pregunta de ese tipo CON LOS PESOS ACTUALES — sin tocar todavía el
// puntaje real de ninguna pregunta (eso solo pasa al pulsar Aplicar).
// Así se ve de inmediato, por ejemplo, que si un tipo se lleva todo el
// peso los demás quedan en 0, en vez de tener que adivinar y aplicar
// para recién enterarse.
export function updatePointsWeightPreview() {
  const previews = document.querySelectorAll('.points-weight-preview');
  if (!previews.length) return;
  const totalPoints = _editorTotalPoints();
  // La vista previa no reimplementa la fórmula: corre el MISMO
  // autoDistributePoints() que el botón "Aplicar", pero sobre una copia
  // de juguete (solo el tipo de cada tarjeta) para no tocar ninguna
  // pregunta de verdad. Así es imposible que prometa un reparto y luego
  // se aplique otro.
  const mock = [...document.querySelectorAll('#editor-questions-container .editor-card')]
    .map(card => ({ type: card.dataset.qtype }));
  if (!mock.length || !totalPoints) {
    previews.forEach(el => { el.textContent = '—'; });
    return;
  }
  autoDistributePoints(mock, totalPoints, _pointsToolMode, readTypeWeights());
  const range = {};
  mock.forEach(q => {
    const r = range[q.type] || (range[q.type] = { min: q.points, max: q.points });
    r.min = Math.min(r.min, q.points);
    r.max = Math.max(r.max, q.points);
  });
  previews.forEach(el => {
    const r = range[el.dataset.type];
    if (!r) { el.textContent = '—'; return; }
    // El reparto de céntimos sobrantes puede dejar 0.01 de diferencia
    // dentro de un mismo tipo — se muestra el rango en vez de un valor
    // único que no sería cierto para todas.
    el.textContent = r.min === r.max
      ? `${fmtPoints(r.min)} pts c/u`
      : `${fmtPoints(r.min)}–${fmtPoints(r.max)} pts c/u`;
  });
}
