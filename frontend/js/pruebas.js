/**
 * pruebas.js — pruebas de la lógica pura del editor (ver pruebas.html).
 * En archivo aparte y no dentro del HTML: la política de seguridad de las
 * páginas (backend/seguridad.py) no deja correr scripts en línea.
 */
import { autoDistributePoints, fmtPoints, DEFAULT_TYPE_WEIGHTS } from './puntos.js';
import { questionIssues } from './validacion.js';
import { parseClozeSegments } from './editor/cloze-segmentos.js';
import { duracionValida, estimarDuracion, onProgressQueue, onProgressStage, stopProgress } from './progreso.js';
import { avisosDelXml, crearIconos, detalleDeError, esc_html, findClozeBrackets, humanizeSkipReason, splitAnswers, splitOptions } from './util.js';

const lista = document.getElementById('lista');
let ok = 0, mal = 0;

function prueba(nombre, fn) {
  try {
    fn();
    ok++;
    lista.insertAdjacentHTML('beforeend', `<li>✅ ${nombre}</li>`);
  } catch (e) {
    mal++;
    lista.insertAdjacentHTML('beforeend', `<li class="mal">❌ ${nombre} — ${e.message}</li>`);
  }
}
function igual(a, b, msg = '') {
  const x = JSON.stringify(a), y = JSON.stringify(b);
  if (x !== y) throw new Error(`${msg} esperado ${y}, obtenido ${x}`);
}

const preguntas = (tipos) => tipos.map((t, i) => ({ num: i + 1, type: t }));
const suma = (qs) => Math.round(qs.reduce((a, q) => a + q.points, 0) * 100) / 100;

// ── Separadores de respuestas y opciones ────────────────────────────
prueba('varias respuestas se separan por " | "', () => {
  igual(splitAnswers('Opción B | Opción D'), ['Opción B', 'Opción D']);
});
prueba('la opción "|" sola es texto, no separador', () => {
  igual(splitAnswers('|'), ['|']);
  igual(splitAnswers('| | &'), ['|', '&']);
});
prueba('"km/h" y "TCP/IP" no se parten como opciones Cloze', () => {
  igual(splitOptions('km/h / m/s² / kg/m'), ['km/h', 'm/s²', 'kg/m']);
  igual(splitOptions('TCP/IP / UDP'), ['TCP/IP', 'UDP']);
});
prueba('findClozeBrackets no corta un hueco con código como "arr[0]"', () => {
  const bs = findClozeBrackets('[A: opción1 / arr[0] / arr[1]] y otro [B: uno / dos]');
  igual(bs.map(b => b.letter), ['A', 'B']);
  igual(splitOptions(bs[0].optionsRaw), ['opción1', 'arr[0]', 'arr[1]']);
});
prueba('esc_html también escapa comillas (seguro dentro de un atributo)', () => {
  const out = esc_html('a" onmouseover="alert(1)<b>x</b>');
  igual(out.includes('"'), false);
  igual(out.includes('<b>'), false);
});
prueba('questionIssues no confunde un hueco Cloze con código', () => {
  const q = { type: 'cloze', data: { text: '¿Qué imprime arr[0] si arr = [A: [10, 20, 30] / 10 / arr[1]]?' } };
  igual(questionIssues(q, { answer: 'A. 10' }), []);
});

// ── Reparto de puntos ───────────────────────────────────────────────
prueba('equitativo: la suma cuadra exacto', () => {
  const qs = preguntas(['multichoice', 'truefalse', 'cloze']);
  autoDistributePoints(qs, 100, 'equal');
  igual(suma(qs), 100);
});

prueba('equitativo con decimales feos (7 preguntas, 20 pts)', () => {
  const qs = preguntas(Array(7).fill('multichoice'));
  autoDistributePoints(qs, 20, 'equal');
  igual(suma(qs), 20);
});

prueba('por tipo: peso 2 vale el doble que peso 1', () => {
  const qs = preguntas(['multichoice', 'truefalse']);   // pesos 2 y 1
  autoDistributePoints(qs, 30, 'byType');
  igual([qs[0].points, qs[1].points], [20, 10]);
});

prueba('por tipo: la suma cuadra con pesos personalizados', () => {
  const qs = preguntas(['multichoice', 'matching', 'essay', 'truefalse', 'cloze']);
  autoDistributePoints(qs, 17.5, 'byType', { multichoice: 4, matching: 1, essay: 1, truefalse: 1, cloze: 1 });
  igual(suma(qs), 17.5);
});

prueba('peso 0 se respeta (no se convierte en 1)', () => {
  const qs = preguntas(['multichoice', 'truefalse']);
  autoDistributePoints(qs, 10, 'byType', { multichoice: 1, truefalse: 0 });
  igual([qs[0].points, qs[1].points], [10, 0]);
});

prueba('todos los pesos en 0 cae a reparto equitativo', () => {
  const qs = preguntas(['multichoice', 'truefalse']);
  autoDistributePoints(qs, 10, 'byType', { multichoice: 0, truefalse: 0 });
  igual([qs[0].points, qs[1].points], [5, 5]);
});

prueba('dos preguntas del mismo tipo difieren como mucho en 0.01', () => {
  const qs = preguntas(Array(3).fill('multichoice'));
  autoDistributePoints(qs, 10, 'byType');
  const p = qs.map(q => q.points);
  igual(Math.max(...p) - Math.min(...p) <= 0.01, true);
});

prueba('total inválido no toca los puntos', () => {
  const qs = preguntas(['multichoice']);
  qs[0].points = 7;
  autoDistributePoints(qs, 0, 'equal');
  autoDistributePoints(qs, NaN, 'equal');
  igual(qs[0].points, 7);
});

prueba('fmtPoints deja los números legibles', () => {
  igual([fmtPoints(2), fmtPoints(2.5), fmtPoints(1.333)], ['2', '2.5', '1.33']);
});

prueba('los pesos por defecto cubren los 7 tipos', () => {
  igual(Object.keys(DEFAULT_TYPE_WEIGHTS).sort(),
    ['cloze', 'essay', 'matching', 'multichoice', 'numerical', 'shortanswer', 'truefalse']);
});

// ── Preguntas incompletas ───────────────────────────────────────────
const mc = (extra = {}, key = 'Dos') => [
  { num: 1, type: 'multichoice', data: { stem: '¿Pregunta?', options: { A: 'Uno', B: 'Dos' }, ...extra } },
  { type: 'multichoice', answer: key },
];

prueba('pregunta completa no tiene problemas', () => {
  igual(questionIssues(...mc()), []);
});

prueba('falta el enunciado', () => {
  igual(questionIssues(...mc({ stem: '   ' })), ['Falta el enunciado']);
});

prueba('falta marcar la respuesta correcta', () => {
  igual(questionIssues(...mc({}, '')), ['Falta marcar la respuesta correcta']);
});

prueba('menos de dos opciones', () => {
  igual(questionIssues(...mc({ options: { A: 'Uno' } })), ['Faltan opciones (mínimo 2)']);
});

prueba('una opción vacía entre varias', () => {
  igual(questionIssues(...mc({ options: { A: 'Uno', B: 'Dos', C: '' } })), ['Hay una opción vacía']);
});

prueba('verdadero/falso sin elegir', () => {
  igual(questionIssues({ num: 1, type: 'truefalse', data: { stem: 'Afirmación.' } },
    { type: 'truefalse', answer: '' }), ['Falta elegir Verdadero o Falso']);
  igual(questionIssues({ num: 1, type: 'truefalse', data: { stem: 'Afirmación.' } },
    { type: 'truefalse', answer: 'Falso' }), []);
});

prueba('emparejamiento: pareja a medias y mínimo de 2', () => {
  const q = { num: 1, type: 'matching', data: { stem: 'Une', col_a: { 1: 'Perú', 2: 'Chile' }, col_b: { a: 'Lima', b: '' } } };
  igual(questionIssues(q, { type: 'matching', answer: '1-a' }),
    ['Hay una pareja incompleta', 'Faltan parejas (mínimo 2)']);
});

prueba('completar: sin espacios y con un espacio vacío', () => {
  igual(questionIssues({ num: 1, type: 'cloze', data: { text: 'Sin espacios' } }, { answer: '' }),
    ['Faltan los espacios para completar']);
  igual(questionIssues({ num: 1, type: 'cloze', data: { text: 'La capital es [A: ]' } }, { answer: '' }),
    ['Un espacio no tiene opciones']);
  igual(questionIssues({ num: 1, type: 'cloze', data: { text: 'La capital es [A: Lima / Quito]' } }, { answer: 'A. Lima' }), []);
});

// «Completar»: sin marca en el documento no se inventa respuesta.
prueba('completar sin clave: el espacio queda sin marcar (no se elige la 1.ª opción)', () => {
  const [, hueco] = parseClozeSegments('La capital es [A: Lima / Quito].', '');
  igual(hueco.correctIndices, []);
  igual(hueco.multi, false);
  igual(parseClozeSegments('Es [A: uno / dos]', 'B. otra')[1].correctIndices, []);
});

prueba('completar con clave: se marca la opción que dice la clave', () => {
  igual(parseClozeSegments('La capital es [A: Lima / Quito].', 'A. Quito')[1].correctIndices, [1]);
  igual(parseClozeSegments('[A: x / y] y [B: 1 / 2]', 'A. y; B. 1 | 2').filter(s => s.type === 'blank').map(s => s.correctIndices), [[1], [0, 1]]);
});

prueba('completar: clave sin letra para un único espacio se respeta', () => {
  igual(parseClozeSegments('Es un [A: vegetal / mineral]', 'vegetal')[1].correctIndices, [0]);
  igual(parseClozeSegments('Es un [A: vegetal / mineral]', 'mineral')[1].correctIndices, [1]);
});

prueba('completar: la clave que no coincide con ninguna opción deja el espacio sin marcar', () => {
  igual(parseClozeSegments('Es [A: uno / dos]', 'A. tres')[1].correctIndices, []);
});

prueba('completar sin respuesta en la clave es una pregunta incompleta', () => {
  const q = { num: 1, type: 'cloze', data: { text: 'La capital es [A: Lima / Quito].' } };
  igual(questionIssues(q, { answer: '' }), ['Falta marcar la respuesta correcta del espacio 1']);
  igual(questionIssues(q, undefined), ['Falta marcar la respuesta correcta del espacio 1']);
  igual(questionIssues(q, { answer: 'A. Lima' }), []);
});

prueba('completar: avisa qué espacios faltan por marcar', () => {
  const q = { num: 1, type: 'cloze', data: { text: '[A: a / b] uno [B: c / d] dos [C: e / f]' } };
  igual(questionIssues(q, { answer: 'B. c' }), ['Falta marcar la respuesta correcta de los espacios 1, 3']);
  igual(questionIssues(q, { answer: 'A. a; B. c; C. f' }), []);
  igual(questionIssues(q, { answer: 'A. a; B. SIN_RESPUESTA; C. f' }), ['Falta marcar la respuesta correcta del espacio 2']);
});

prueba('completar: la clave de un solo espacio sin letra vale (como en el backend)', () => {
  const q = { num: 1, type: 'cloze', data: { text: 'Es un [A: vegetal / mineral]' } };
  igual(questionIssues(q, { answer: 'vegetal' }), []);
});

prueba('completar: un espacio sin opciones no repite el aviso de falta de marca', () => {
  igual(questionIssues({ num: 1, type: 'cloze', data: { text: 'La capital es [A: ]' } }, { answer: '' }),
    ['Un espacio no tiene opciones']);
});

prueba('respuesta corta y numérica', () => {
  igual(questionIssues({ num: 1, type: 'shortanswer', data: { stem: '¿Capital?' } }, { answer: '' }),
    ['Falta la respuesta']);
  igual(questionIssues({ num: 1, type: 'numerical', data: { stem: '2+2' } }, { answer: 'cuatro' }),
    ['La respuesta debe ser un número']);
  igual(questionIssues({ num: 1, type: 'numerical', data: { stem: '2+2' } }, { answer: '4,5' }), []);
});

prueba('ensayo solo necesita enunciado', () => {
  igual(questionIssues({ num: 1, type: 'essay', data: { stem: 'Explica…' } }, { answer: '' }), []);
});

// La versión anterior (cuadrática), como referencia: la nueva debe dar
// exactamente lo mismo en cualquier texto.
function _clozeAnterior(text) {
  const out = []; let i = 0; const n = text.length;
  while (i < n) {
    if (text[i] !== '[') { i++; continue; }
    const m = /^([A-Za-z]):\s*/.exec(text.slice(i + 1));
    if (!m) { i++; continue; }
    const b = i + 1 + m[0].length; let d = 1, j = b;
    while (j < n && d) { if (text[j] === '[') d++; else if (text[j] === ']') d--; j++; }
    if (d) { i++; continue; }
    out.push({ start: i, end: j, letter: m[1], optionsRaw: text.slice(b, j - 1) }); i = j;
  }
  return out;
}

prueba('findClozeBrackets da lo mismo que la versión anterior en 3 000 textos al azar', () => {
  let semilla = 7;
  const azar = () => (semilla = (semilla * 1103515245 + 12345) % 2147483648) / 2147483648;
  for (let k = 0; k < 3000; k++) {
    const t = Array.from({ length: Math.floor(azar() * 60) }, () => '[]A: x/b'[Math.floor(azar() * 8)]).join('');
    igual(findClozeBrackets(t), _clozeAnterior(t), `texto «${t}»`);
  }
});

prueba('findClozeBrackets con 100 000 «[A:» tarda menos de 200 ms', () => {
  const t0 = performance.now();
  findClozeBrackets('[A:'.repeat(100000));
  const ms = performance.now() - t0;
  if (ms > 200) throw new Error(`tardó ${Math.round(ms)} ms`);
});

// ── Duración estimada de la conversión ──────────────────────────────
prueba('duracionValida descarta lo que no es una conversión real', () => {
  igual([0, 0.2, 5, 90, 3600, 3601, 1.7e9, -4, NaN, Infinity, null, undefined, '12'].map(duracionValida),
    [false, false, true, true, true, false, false, false, false, false, false, false, false]);
});

prueba('estimarDuracion promedia solo las duraciones válidas', () => {
  igual(estimarDuracion([10, 20, 30], 'text'), 20);
  igual(estimarDuracion([10, 1.7e9, 30, NaN, -5], 'text'), 20);
});

prueba('estimarDuracion sin datos válidos cae al valor por defecto del tipo', () => {
  igual(estimarDuracion([], 'text'), 12);
  igual(estimarDuracion(undefined, 'images'), 40);
  igual(estimarDuracion([1.7e9, 1.7e9], 'normalize'), 90);
  igual(estimarDuracion('basura', 'inventado'), 12);
});

prueba('stopProgress(true) sin startProgress no guarda ninguna duración', () => {
  const CLAVE = 'moodle_conversion_timings_v1';
  const respaldo = localStorage.getItem(CLAVE);
  const nodos = ['progress-bar-fill', 'progress-elapsed', 'progress-eta'].map(id => {
    const el = document.createElement('div'); el.id = id; document.body.append(el); return el;
  });
  try {
    localStorage.setItem(CLAVE, '{}');
    stopProgress(true); // como hace generateXml: nunca se llamó a startProgress
    igual(JSON.parse(localStorage.getItem(CLAVE)), {});
  } finally {
    nodos.forEach(n => n.remove());
    if (respaldo === null) localStorage.removeItem(CLAVE); else localStorage.setItem(CLAVE, respaldo);
  }
});

// ── Textos de error ─────────────────────────────────────────────────
prueba('detalleDeError: un texto se deja tal cual', () => {
  igual(detalleDeError('El archivo está vacío.', 'x'), 'El archivo está vacío.');
  igual(detalleDeError('   ', 'respaldo'), 'respaldo');
});

prueba('detalleDeError: una lista 422 de FastAPI no se vuelve «[object Object]»', () => {
  const t = detalleDeError([{ loc: ['body', 'file'], msg: 'Field required', type: 'missing' }], 'x');
  igual(typeof t, 'string');
  igual(t.includes('object'), false);
  igual(t.includes('«file»'), true);
  igual(detalleDeError([{ loc: ['body', 'points'], msg: 'Input should be a valid number', type: 'float_parsing' }], 'x').includes('valid number'), true);
  igual(detalleDeError([], 'respaldo'), 'respaldo');
});

prueba('detalleDeError: un objeto con errors se conserva y uno con message da el texto', () => {
  const o = { message: 'Errores', errors: ['a', 'b'] };
  igual(detalleDeError(o, 'x'), o);
  igual(detalleDeError({ message: 'Algo pasó' }, 'x'), 'Algo pasó');
  igual(detalleDeError({}, 'respaldo'), 'respaldo');
  igual(detalleDeError(null, 'respaldo'), 'respaldo');
});

prueba('humanizeSkipReason: un motivo desconocido va como detalle tras una frase clara', () => {
  const t = humanizeSkipReason('Error: algo raro con la Pregunta 3 (zzz).');
  igual(t.startsWith('Esta pregunta no pasó la verificación'), true);
  igual(t.includes('(detalle: algo raro con la Pregunta 3 (zzz).)'), true);
  igual(humanizeSkipReason('').includes('detalle'), false);
  igual(humanizeSkipReason('no tiene una respuesta correcta especificada').startsWith('No se encontró'), true);
});

prueba('crearIconos no falla sin la biblioteca de íconos ni sin root', () => {
  const previo = window.lucide;
  try {
    window.lucide = undefined;
    crearIconos(); crearIconos(document.body);
    const llamadas = [];
    window.lucide = { createIcons: (o) => llamadas.push(o) };
    crearIconos(document.body); crearIconos();
    igual(llamadas[0].root === document.body, true);
    igual(llamadas[1], undefined);
  } finally { window.lucide = previo; }
});

// ── «En cola» y avisos al generar el XML ────────────────────────────
prueba('etapa «queue»: muestra el aviso sin cambiar el subtítulo y la siguiente etapa lo quita', () => {
  const nodos = ['progress-subtitle', 'progress-detail', 'progress-bar-fill'].map(id => {
    const el = document.createElement('div'); el.id = id; document.body.append(el); return el;
  });
  try {
    nodos[0].textContent = 'Leyendo el texto del examen…';
    onProgressStage({ type: 'stage', key: 'queue', message: 'Hay otras conversiones en curso…' });
    igual(nodos[1].textContent, 'Hay otras conversiones en curso…');
    igual(nodos[0].textContent, 'Leyendo el texto del examen…');
    onProgressStage({ type: 'stage', key: 'extract', message: 'Extrayendo…' });
    igual(nodos[1].textContent, '');
    igual(nodos[0].textContent, 'Extrayendo…');
    onProgressQueue({}); // sin mensaje: texto por defecto
    igual(nodos[1].textContent, 'En cola: esperando otra conversión…');
  } finally { nodos.forEach(n => n.remove()); }
});

prueba('avisosDelXml: el motivo del Historial va primero y lo raro se ignora', () => {
  igual(avisosDelXml({}), []);
  igual(avisosDelXml(null), []);
  igual(avisosDelXml({ avisos: ['a', '', 3, null, 'b'] }), ['a', 'b']);
  igual(avisosDelXml({ historial_guardado: true, aviso_historial: 'x' }), []);
  igual(avisosDelXml({ historial_guardado: false, aviso_historial: 'No se guardó', avisos: ['a'] }), ['No se guardó', 'a']);
  igual(avisosDelXml({ historial_guardado: false }).length, 1);
});

const resumen = document.getElementById('resumen');
resumen.textContent = mal === 0 ? `✅ ${ok} pruebas, todas pasan` : `❌ ${mal} fallan de ${ok + mal}`;
resumen.className = mal === 0 ? 'ok' : 'fail';
window.__resultado = { ok, mal };
