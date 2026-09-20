/**
 * progreso.js — pantalla de carga: barra, tiempo estimado y avance real.
 * Aprende de las conversiones anteriores (localStorage) para afinar la estimación.
 */
import { readProgressStream } from './carga.js';
import { formatMMSS } from './util.js';

// Progress Simulation + tiempo transcurrido/estimado
//
// No hay forma de conocer el progreso REAL del backend (es una sola
// llamada HTTP bloqueante, sin WebSocket/SSE de por medio) — pero sí
// podemos aprender de cuánto ha tardado ESTE mismo navegador en
// conversiones anteriores del mismo "tipo" (texto plano, PDF con
// imágenes, o normalizar con IA — cada uno tiene un costo muy distinto)
// y usar ese promedio como estimado inicial, ajustándolo en vivo si la
// corrida actual va más lenta de lo previsto (para que el restante
// nunca llegue a 0:00 mientras el servidor sigue trabajando).
const TIMING_HISTORY_KEY = 'moodle_conversion_timings_v1';

const TIMING_DEFAULTS = { text: 12, images: 40, normalize: 90 };

const TIMING_HISTORY_MAX = 5;

function _loadTimingHistory() {
  try {
    return JSON.parse(localStorage.getItem(TIMING_HISTORY_KEY)) || {};
  } catch (_) {
    return {};
  }
}

function _getEstimatedDuration(kind) {
  const history = _loadTimingHistory()[kind];
  if (history && history.length > 0) {
    return history.reduce((a, b) => a + b, 0) / history.length;
  }
  return TIMING_DEFAULTS[kind] || TIMING_DEFAULTS.text;
}

function _recordDuration(kind, seconds) {
  try {
    const all = _loadTimingHistory();
    const list = all[kind] || [];
    list.push(seconds);
    while (list.length > TIMING_HISTORY_MAX) list.shift();
    all[kind] = list;
    localStorage.setItem(TIMING_HISTORY_KEY, JSON.stringify(all));
  } catch (_) {
    // localStorage no disponible (modo privado, cuota llena, etc.) — no
    // es crítico, simplemente no se aprende de esta corrida.
  }
}

let progressInterval;

let progressStartTime = 0;

let progressKind = 'text';

let progressEstimatedTotal = TIMING_DEFAULTS.text;

// Avance REAL que informa el backend (ver readProgressStream). Mientras
// no llegue ningún evento se usa la secuencia estimada de siempre; en
// cuanto llega uno, la pantalla pasa a reflejar lo que de verdad ocurre.
let progressReal = false;

let aiStartTime = 0;

let aiExpected = 0;

let aiDone = 0;

let aiMessage = '';

// Segundos por pregunta medidos en la evaluación (dev/eval_results):
// JSON ~0.7, texto ~0.3; con todas las páginas como imagen, más.
const SECONDS_PER_QUESTION_DEFAULTS = { json: 0.75, text: 0.35, normalize: 1.2 };

const SPQ_KEY = 'moodle_seconds_per_question_v1';

function _spqKey() {
  return progressKind === 'normalize' ? 'normalize' : (window._aiMode || 'json');
}

function _getSecondsPerQuestion() {
  try {
    const list = (JSON.parse(localStorage.getItem(SPQ_KEY)) || {})[_spqKey()];
    if (list && list.length) return list.reduce((a, b) => a + b, 0) / list.length;
  } catch (_) {}
  return SECONDS_PER_QUESTION_DEFAULTS[_spqKey()] || 0.75;
}

function _recordSecondsPerQuestion(value) {
  try {
    const all = JSON.parse(localStorage.getItem(SPQ_KEY)) || {};
    const list = all[_spqKey()] || [];
    list.push(value);
    while (list.length > TIMING_HISTORY_MAX) list.shift();
    all[_spqKey()] = list;
    localStorage.setItem(SPQ_KEY, JSON.stringify(all));
  } catch (_) {}
}

function _setProgressBar(pct) {
  document.getElementById('progress-bar-fill').style.transform = `scaleX(${Math.min(pct, 99) / 100})`;
}

function _setProgressDetail(text) {
  document.getElementById('progress-detail').textContent = text;
}

export function onProgressStage(ev) {
  progressReal = true;
  const elapsedSec = (Date.now() - progressStartTime) / 1000;
  if (ev.message) document.getElementById('progress-subtitle').textContent = ev.message;
  if (ev.key === 'extract') {
    _setProgressBar(4);
    _setProgressDetail('');
  } else if (ev.key === 'ai') {
    window._aiMode = ev.mode || 'json';
    aiMessage = ev.message || '';
    aiStartTime = Date.now();
    aiExpected = ev.expected || 0;
    aiDone = 0;
    _setProgressBar(8);
    if (aiExpected > 0) {
      _setProgressDetail(`Se detectaron ~${aiExpected} preguntas`);
      progressEstimatedTotal = elapsedSec + 3 + aiExpected * _getSecondsPerQuestion();
    } else {
      _setProgressDetail(ev.images ? `Leyendo ${ev.images} página(s) como imagen` : '');
    }
  } else if (ev.key === 'retry') {
    // Google saturado o límite por minuto: el backend espera y reintenta.
    // La respuesta vuelve a empezar desde cero, así que el ritmo se mide
    // de nuevo (aiStartTime = 0 → se reinicia con el próximo avance).
    const wait = Number((/(\d+)\s*s/.exec(ev.message || '') || [])[1] || 10);
    aiStartTime = 0;
    aiDone = 0;
    _setProgressDetail('Esperando al servicio de IA…');
    progressEstimatedTotal = elapsedSec + wait + 3 + (aiExpected || 20) * _getSecondsPerQuestion();
  } else if (ev.key === 'review') {
    _setProgressBar(96);
    _setProgressDetail(aiDone ? `${aiDone} preguntas procesadas · verificando…` : 'Verificando…');
    progressEstimatedTotal = elapsedSec + 1;
  }
}

export function onProgressCount(ev) {
  progressReal = true;
  aiDone = ev.done || 0;
  if (ev.expected) aiExpected = ev.expected;
  const now = Date.now();
  if (!aiStartTime) {
    // Primer avance tras un reintento: la IA volvió a responder.
    aiStartTime = now;
    if (aiMessage) document.getElementById('progress-subtitle').textContent = aiMessage;
  }
  const elapsedSec = (now - progressStartTime) / 1000;
  const aiElapsed = (now - aiStartTime) / 1000;
  // La estimación inicial se corrige con el ritmo REAL de esta
  // conversión en cuanto hay un par de preguntas para medirlo.
  const measured = aiDone >= 2 ? aiElapsed / aiDone : null;
  const spq = measured ?? _getSecondsPerQuestion();
  const total = aiExpected > 0 ? Math.max(aiExpected, aiDone) : 0;
  if (total > 0) {
    progressEstimatedTotal = elapsedSec + Math.max(total - aiDone, 0) * spq + 1.5;
    _setProgressBar(8 + 86 * Math.min(aiDone / total, 1));
    // El total es aproximado: en cuanto la IA pasa del estimado, se
    // deja de mostrar un "de ~N" que ya no es cierto ("33 de ~27").
    _setProgressDetail(aiExpected && aiDone <= aiExpected
      ? `${aiDone} de ~${aiExpected} preguntas procesadas`
      : `${aiDone} preguntas procesadas`);
  } else {
    _setProgressDetail(`${aiDone} preguntas procesadas`);
  }
}

export function startProgress(kind = 'text') {
  const pSubtitle = document.getElementById('progress-subtitle');
  const pFill = document.getElementById('progress-bar-fill');
  const elapsedEl = document.getElementById('progress-elapsed');
  const etaEl = document.getElementById('progress-eta');
  const sequence = [
    { time: 0,  text: 'Extrayendo texto del examen...' },
    { time: 3,  text: 'Analizando la estructura y preguntas...' },
    { time: 7,  text: 'Aplicando prefiltro de consistencia IA...' },
    { time: 14, text: 'Construyendo modelo de datos de preguntas...' }
  ];

  progressKind = kind;
  progressStartTime = Date.now();
  progressEstimatedTotal = _getEstimatedDuration(kind);
  progressReal = false;
  aiStartTime = 0;
  aiExpected = 0;
  aiDone = 0;
  aiMessage = '';
  _setProgressDetail('');

  document.getElementById('progress-timer-row').style.display = 'flex';
  pFill.style.transform = 'scaleX(0)';
  pSubtitle.textContent = sequence[0].text;
  elapsedEl.textContent = '0:00';
  etaEl.textContent = formatMMSS(progressEstimatedTotal);

  progressInterval = setInterval(() => {
    const elapsedSec = (Date.now() - progressStartTime) / 1000;

    // Sin eventos del backend todavía: secuencia estimada de siempre.
    // Con eventos, la barra y el texto los maneja onProgress*.
    if (!progressReal) {
      let pct = Math.min(elapsedSec * 7, 92);
      pFill.style.transform = `scaleX(${pct / 100})`;
      const stage = sequence.slice().reverse().find(s => elapsedSec >= s.time);
      if (stage && pSubtitle.textContent !== stage.text) {
        pSubtitle.textContent = stage.text;
      }
    }

    // Si ya vamos por el 90% del tiempo estimado y el servidor sigue
    // trabajando, el estimado era corto — se extiende para que el
    // restante no se quede pegado en 0:00 mientras se sigue esperando.
    if (elapsedSec >= progressEstimatedTotal * 0.9) {
      progressEstimatedTotal = elapsedSec / 0.9;
    }

    elapsedEl.textContent = formatMMSS(elapsedSec);
    etaEl.textContent = formatMMSS(Math.max(progressEstimatedTotal - elapsedSec, 1));
  }, 1000);
}

export function stopProgress(success) {
  clearInterval(progressInterval);
  if (success) {
    document.getElementById('progress-bar-fill').style.transform = 'scaleX(1)';
    const finalElapsed = (Date.now() - progressStartTime) / 1000;
    document.getElementById('progress-elapsed').textContent = formatMMSS(finalElapsed);
    document.getElementById('progress-eta').textContent = '0:00';
    // Solo se aprende de corridas EXITOSAS — una que falló a medio
    // camino (ej. error de red) no refleja cuánto tarda una conversión
    // real de este tipo, y contaminaría el promedio hacia abajo.
    _recordDuration(progressKind, finalElapsed);
    if (aiDone >= 3 && aiStartTime) {
      _recordSecondsPerQuestion((Date.now() - aiStartTime) / 1000 / aiDone);
    }
  }
}
