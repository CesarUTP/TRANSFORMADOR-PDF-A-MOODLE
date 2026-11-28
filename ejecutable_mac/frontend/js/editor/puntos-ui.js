/**
 * puntos-ui.js — panel "Distribuir puntos" (el cálculo vive en js/puntos.js).
 *
 * Dos formas de repartir:
 *   · «Igual para todas»: el total del examen se divide en partes iguales entre las preguntas.
 *   · «Según el tipo»:    el docente escribe cuántos puntos vale CADA pregunta de cada tipo y el total del
 *                         examen es la suma (10 de opción múltiple a 2 pts + 5 de completar a 5 pts = 45 pts).
 */
import { _openCollapsiblePanel, togglePanel } from './paneles.js';
import { renderEditor, syncParseResultFromDOM } from './tarjetas.js';
import { estado } from '../estado.js';
import { aplicarPuntosPorTipo, autoDistributePoints, fmtPoints, puntajeValido, puntosPorTipo, sumaDePuntos } from '../puntos.js';
import { showToast } from '../ui/toast.js';

// ── Panel "Distribuir puntos" ──────────────────────────────────────────
export function togglePointsToolMenu() {
  if (togglePanel('points-tool-panel', 'flex')) actualizarVistaPorTipo();
}

// Puntos totales del examen: los que el docente escribió al subir el archivo o,
// después de «Según el tipo», la suma que salió de ahí (nunca un 100 asumido) —
// un único lugar del que leerlos, para que el panel, la vista previa y el
// contador no puedan quedar diciendo cosas distintas.
export function _editorTotalPoints() {
  const t = estado.currentUploadMetadata ? Number(estado.currentUploadMetadata.total_points) : NaN;
  return Number.isFinite(t) && t > 0 ? t : 0;
}

// Lee lo que el docente escribió en «Según el tipo»: { tipo: número | null } (null = vacío o no válido: ese
// tipo no se toca). Es la ÚNICA lectura de esos campos: la vista previa y el botón «Aplicar» la comparten a
// propósito, para que lo que se aplica sea exactamente lo que la vista previa prometió.
function leerPuntosPorTipo() {
  const porTipo = {};
  document.querySelectorAll('.points-type-input').forEach(inp => {
    const v = inp.value.trim() === '' ? NaN : Number(inp.value);
    porTipo[inp.dataset.type] = puntajeValido(v) ? v : null;
  });
  return porTipo;
}

// Cambia entre "Igual para todas" y "Según el tipo" (muestra los puntos de cada tipo)
// — no aplica nada todavía, solo decide qué hace el botón "Aplicar".
let _pointsToolMode = 'byType';

export function setPointsToolMode(mode) {
  _pointsToolMode = mode;
  const equalBtn = document.getElementById('points-mode-equal');
  const byTypeBtn = document.getElementById('points-mode-byType');
  const editor = document.getElementById('points-weights-editor');
  if (equalBtn) { equalBtn.className = 'btn btn-sm ' + (mode === 'equal' ? 'btn-primary' : 'btn-ghost'); equalBtn.setAttribute('aria-pressed', mode === 'equal'); equalBtn.style.flex = '1'; }
  if (byTypeBtn) { byTypeBtn.className = 'btn btn-sm ' + (mode === 'byType' ? 'btn-primary' : 'btn-ghost'); byTypeBtn.setAttribute('aria-pressed', mode === 'byType'); byTypeBtn.style.flex = '1'; }
  if (editor) editor.style.display = (mode === 'byType') ? 'flex' : 'none';
  const ayudaTipo = document.getElementById('points-help-byType');
  const ayudaIgual = document.getElementById('points-help-equal');
  if (ayudaTipo) ayudaTipo.hidden = mode !== 'byType';
  if (ayudaIgual) ayudaIgual.hidden = mode !== 'equal';
}

// renderEditor() reconstruye la barra con «Según el tipo» y los puntos de hoy. Esto deja el
// panel como el docente lo tenía: el modo elegido y lo que escribió (`escritos`: tipo →
// texto del campo) en los tipos que siguen presentes. Sin esto, el botón resaltado decía
// una cosa y «Aplicar» hacía otra.
export function sincronizarPanelPuntos(escritos = {}) {
  setPointsToolMode(_pointsToolMode);
  document.querySelectorAll('.points-type-input').forEach(inp => {
    if (Object.hasOwn(escritos, inp.dataset.type)) {
      inp.value = escritos[inp.dataset.type];
      inp.dataset.escrito = '1';
    }
  });
  actualizarVistaPorTipo();
}

// Al abrir OTRO examen el panel vuelve a su estado de fábrica.
export function reiniciarPanelPuntos() {
  _pointsToolMode = 'byType';
}

// Botón "Aplicar": fija el puntaje de TODAS las preguntas según el modo elegido. Reemplaza los
// valores puestos a mano, así que el aviso ofrece "Deshacer" (restaura también el total del examen).
export function applyPointsDistribution() {
  // Lo escrito vive en inputs que renderEditor() va a reconstruir desde cero más abajo —
  // hay que leerlo ANTES de perderlo (renderEditor lo vuelve a poner por su cuenta).
  const mode = _pointsToolMode;
  const porTipo = leerPuntosPorTipo();

  syncParseResultFromDOM();
  // El docente decidió los puntos: a partir de aquí no se reparten solos (exámenes escritos desde cero).
  if (estado.currentUploadMetadata) estado.currentUploadMetadata.reparto_auto = false;
  const questions = estado.currentParseResult.questions;
  const anteriores = questions.map(q => q.points);
  const totalAntes = _editorTotalPoints();
  let totalNuevo = totalAntes;

  if (mode === 'equal') {
    if (!totalAntes) {
      showToast('No hay un puntaje total definido para esta evaluación', 'error');
      return;
    }
    autoDistributePoints(questions, totalAntes, 'equal');
  } else {
    if (!Object.values(porTipo).some(v => v !== null)) {
      showToast('Escribe cuántos puntos vale cada tipo de pregunta', 'error');
      return;
    }
    totalNuevo = aplicarPuntosPorTipo(questions, porTipo);
    if (!(totalNuevo > 0)) {
      questions.forEach((q, i) => { q.points = anteriores[i]; });
      showToast('La evaluación no puede valer 0 puntos: escribe al menos un tipo con puntos', 'error');
      return;
    }
    if (estado.currentUploadMetadata) estado.currentUploadMetadata.total_points = totalNuevo;
  }
  renderEditor(estado.currentParseResult);

  // Reabre el panel con el mismo modo y lo mismo que el docente acababa de escribir,
  // para que vea de inmediato el resultado sobre las tarjetas de abajo en vez de que
  // el panel se cierre solo y parezca que no pasó nada.
  setPointsToolMode(mode);
  actualizarVistaPorTipo();
  const panel = document.getElementById('points-tool-panel');
  if (panel && !panel.classList.contains('panel-open')) _openCollapsiblePanel(panel, 'flex');

  // El aviso dice el resultado concreto y permite volver atrás.
  const texto = mode === 'equal'
    ? `${fmtPoints(totalNuevo)} pts repartidos entre ${questions.length} preguntas`
    : `La evaluación ahora vale ${fmtPoints(totalNuevo)} pts${Math.abs(totalNuevo - totalAntes) > 0.009 ? ` (antes ${fmtPoints(totalAntes)})` : ''}`;
  showToast(texto, 'info', {
    accion: { texto: 'Deshacer', alPulsar: () => {
      syncParseResultFromDOM();
      estado.currentParseResult.questions.forEach((q, i) => { if (i < anteriores.length) q.points = anteriores[i]; });
      if (estado.currentUploadMetadata && totalAntes) estado.currentUploadMetadata.total_points = totalAntes;
      renderEditor(estado.currentParseResult);
      showToast('Se restauraron los puntos anteriores', 'info');
      return document.querySelector('[data-accion="applyPointsDistribution"]');
    } } }
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
  // Si la suma no coincide con el total, el botón lo señala (sin bloquear).
  const off = Math.abs(sum - total) > 0.009;
  label.closest('.toolbar-btn')?.classList.toggle('is-off', off);
  label.title = off ? 'La suma de los puntos no coincide con el total de la evaluación' : '';
}

// Vista previa en vivo de «Según el tipo»: mientras el docente escribe cuánto vale cada
// pregunta de un tipo, se muestra al instante el subtotal de ese tipo y el total del examen
// — sin tocar todavía el puntaje real de ninguna pregunta (eso solo pasa al pulsar Aplicar).
// No reimplementa la cuenta: corre el MISMO puntosPorTipo() que usa «Aplicar», así es
// imposible que prometa un total y luego se aplique otro.
export function actualizarVistaPorTipo() {
  const subtotales = document.querySelectorAll('.points-type-sub');
  const linea = document.getElementById('points-type-total');
  if (!subtotales.length) return;
  const tarjetas = [...document.querySelectorAll('#editor-questions-container .editor-card')];
  const items = tarjetas.map(card => ({
    type: card.dataset.qtype,
    huecos: card.dataset.qtype === 'cloze' ? Math.max(1, card.querySelectorAll('.cloze-blank-card').length) : 0,
    actual: parseFloat(card.querySelector('.q-points')?.value) || 0,
  }));
  const porTipo = leerPuntosPorTipo();
  const puntos = puntosPorTipo(items, porTipo);
  const suma = {};
  const sube = {};          // «Completar» con más espacios que puntos: Moodle da al menos 1 por espacio
  items.forEach((it, i) => {
    suma[it.type] = (suma[it.type] || 0) + puntos[i];
    if (it.type === 'cloze' && porTipo.cloze !== null && puntos[i] > Math.round(porTipo.cloze)) sube.cloze = true;
  });
  subtotales.forEach(el => {
    const t = el.dataset.type;
    el.textContent = porTipo[t] === null
      ? 'sin cambio'
      : `= ${fmtPoints(Math.round((suma[t] || 0) * 100) / 100)} pts${sube[t] ? '*' : ''}`;
  });
  if (linea) {
    const total = sumaDePuntos(puntos);
    const ahora = _editorTotalPoints();
    linea.textContent = `Total de la evaluación: ${fmtPoints(total)} pts`
      + (ahora && Math.abs(total - ahora) > 0.009 ? ` (ahora ${fmtPoints(ahora)})` : '')
      + (sube.cloze ? '. * Completar vale puntos enteros, al menos uno por espacio.' : '');
  }
}
