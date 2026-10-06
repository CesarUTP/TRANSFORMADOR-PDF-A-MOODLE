/**
 * pruebas.js — pruebas de la lógica pura del editor.
 * Un solo juego de pruebas para dos entornos: pruebas.html las muestra en el
 * navegador y dev/test_frontend.mjs las corre en Node (CI) con un DOM falso.
 * Este módulo solo REGISTRA las pruebas y exporta `ejecutarPruebas()`; el
 * «cómo se muestra» va al final y solo actúa si la página trae su lista.
 * En archivo aparte y no dentro del HTML: la política de seguridad de las
 * páginas (backend/seguridad.py) no deja correr scripts en línea.
 */
import { autoDistributePoints, fmtPoints, DEFAULT_TYPE_WEIGHTS } from './puntos.js';
import { questionIssues } from './validacion.js';
import { construirClozeDesdeSegmentos, huecoDeEstructura, indicesUtilizables, parseClozeSegments } from './editor/cloze-segmentos.js';
import { claveDeOpcionMultiple, letrasCorrectasPorIndice } from './editor/respuesta-indices.js';
import * as proc from './editor/procedencia.js';
import { MAX_ABIERTAS, abiertasPorDefecto, recortar } from './editor/plegado-logica.js';
import { detectarProblemas, normalizar, similitud } from './editor/calidad.js';
import { faltaRespuesta } from './validacion.js';
import { describirSugerencia } from './editor/sugerencias-logica.js';
import { LIMITE_CAMPO, PERFIL_CAMPOS, aplicarPerfil, datosDePerfil, enteroEn, nombrePerfil, tamanoValido, avisosDelPdf, cuerpoPdf, datosParaEnviar, fechaLegible, limpiarCampo, limpiarTexto, logoValido, medidasReducidas, nombreDeDescarga, paraGuardar, valoresIniciales } from './ui/exportar-pdf-logica.js';
import { COLORES, activas, archivadas, avisoDeLimite, examenesDe, existeNombre, fechaCorta, filtrarExamenes, formatoBytes, nombreSugerido, normalizar as normalizarMateria, ordenarMaterias, planDelAsistente, sugerirMaterias, textoUso, variableDeColor } from './materias-logica.js';
import { CLAVE_VISTOS, TOURS, debeOfrecer, leerVistos, marcarVisto, nombreDeTour, pasosVisibles } from './ui/tour-logica.js';
import { ejemploExamen, iniciales, materiasQueUsan, nombreCopia, nombreOcupado, ordenarPerfiles, resumenEncabezado, resumenFormato } from './perfil-logica.js';
import { ZOOMS, paginaDe, recuadroValido, urlOriginal, vecino, zoomVecino } from './ui/original-logica.js';
import { duracionValida, estimarDuracion, onProgressQueue, onProgressStage, stopProgress } from './progreso.js';
import { avisosDelXml, crearIconos, detalleDeError, esc_html, findClozeBrackets, humanizeSkipReason, splitAnswers, splitOptions } from './util.js';

const casos = [];
function prueba(nombre, fn) { casos.push({ nombre, fn }); }
function igual(a, b, msg = '') {
  const x = JSON.stringify(a), y = JSON.stringify(b);
  if (x !== y) throw new Error(`${msg} esperado ${y}, obtenido ${x}`);
}

/** Corre todas las pruebas registradas. Devuelve [{ nombre, error }] (error es null si pasó). */
export function ejecutarPruebas() {
  return casos.map(({ nombre, fn }) => {
    try { fn(); return { nombre, error: null }; }
    catch (e) { return { nombre, error: e.message }; }
  });
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

// ── De dónde sale la respuesta y qué tan segura es (editor/procedencia.js) ──
const textos = (chips) => chips.map(c => c.texto);

prueba('procedencia: sin campos no hay chips (la tarjeta se ve como siempre)', () => {
  igual(proc.chipsDeProcedencia({}, 'multichoice'), []);
  igual(proc.chipsDeProcedencia(null, 'multichoice'), []);
  igual(proc.chipsDeProcedencia({ stem: 'x', low_confidence: true }, 'truefalse'), []);
  igual(proc.chipsHtml([]), '');
});
prueba('procedencia: página, origen y confianza salen en ese orden y con texto claro', () => {
  const chips = proc.chipsDeProcedencia({ page: 3, origen_respuesta: 'documento', confianza: 'alta' }, 'multichoice');
  igual(textos(chips), ['Pág. 3', 'Clave del documento', 'Confianza alta']);
  igual(chips[0].tip, 'Página del documento original');
  igual(chips.every(c => c.icono && c.tip && c.aria.length > c.texto.length), true);
});
prueba('procedencia: los tres orígenes y las tres confianzas tienen su etiqueta', () => {
  const o = (v) => textos(proc.chipsDeProcedencia({ origen_respuesta: v }, 'multichoice'));
  igual(o('documento'), ['Clave del documento']);
  igual(o('marca'), ['Marca del documento']);
  igual(o('ia'), ['Interpretada por la IA — revisar']);
  igual(o('docente'), ['Editada por ti']);
  const c = (v) => textos(proc.chipsDeProcedencia({ confianza: v }, 'multichoice'));
  igual([c('alta'), c('media'), c('baja')], [['Confianza alta'], ['Confianza media'], ['Confianza baja']]);
});
prueba('procedencia: nunca solo color (cada chip trae ícono y texto) y lo dudoso se marca como «aviso»', () => {
  const chips = proc.chipsDeProcedencia({ origen_respuesta: 'ia', confianza: 'baja' }, 'cloze');
  igual(chips.map(c => c.tono), ['aviso', 'aviso']);
  const html = proc.chipsHtml(chips);
  igual(html.includes('data-lucide="sparkles"') && html.includes('data-lucide="shield-alert"'), true);
  igual(html.includes('aria-label="'), true);
  igual(html.includes('Interpretada por la IA — revisar'), true);
});
prueba('procedencia: «docente» oculta la confianza; un ensayo no habla de origen de respuesta', () => {
  igual(textos(proc.chipsDeProcedencia({ page: 2, origen_respuesta: 'docente', confianza: 'baja' }, 'multichoice')), ['Pág. 2', 'Editada por ti']);
  igual(textos(proc.chipsDeProcedencia({ page: 2, origen_respuesta: 'documento' }, 'essay')), ['Pág. 2']);
});
prueba('procedencia: valores raros se ignoran (y nada se inyecta como HTML)', () => {
  igual(proc.chipsDeProcedencia({ page: 0, origen_respuesta: 'otro', confianza: 'altísima' }, 'multichoice'), []);
  igual(proc.chipsDeProcedencia({ page: '<img onerror=x>', origen_respuesta: '"><b>' }, 'multichoice'), []);
  igual(proc.chipsDeProcedencia({ page: 2.5 }, 'multichoice'), []);
});

prueba('respuesta cambiada: sin cambio (foco, clic) no cuenta; sin referencia tampoco', () => {
  const f = proc.firmaRespuesta('multichoice', { letras: ['B'], respuesta: 'Java' });
  igual(proc.respuestaCambio(f, proc.firmaRespuesta('multichoice', { letras: ['B'], respuesta: 'Java' })), false);
  igual(proc.respuestaCambio(undefined, f), false);
  igual(proc.respuestaCambio(f, undefined), false);
});
prueba('respuesta cambiada: otra opción, V/F, huecos, parejas, texto o número sí cuentan', () => {
  const cambia = (tipo, antes, despues) => proc.respuestaCambio(proc.firmaRespuesta(tipo, antes), proc.firmaRespuesta(tipo, despues));
  igual(cambia('multichoice', { letras: ['B'] }, { letras: ['B', 'D'] }), true);
  igual(cambia('truefalse', { respuesta: 'Verdadero' }, { respuesta: 'Falso' }), true);
  igual(cambia('cloze', { respuesta: 'A. 10', huecos: ['A:10 / 20'] }, { respuesta: 'A. 20', huecos: ['A:10 / 20'] }), true);
  igual(cambia('cloze', { respuesta: 'A. 10', huecos: ['A:10 / 20'] }, { respuesta: 'A. 10', huecos: ['A:10 / 20 / 30'] }), true);
  const par = (b) => ({ colA: { 1: 'Sol' }, colB: { a: b }, pares: { 1: 'a' } });
  igual(cambia('matching', par('Estrella'), par('Planeta')), true);
  igual(cambia('shortanswer', { respuesta: 'ATP' }, { respuesta: 'ADN' }), true);
  igual(cambia('numerical', { respuesta: '3' }, { respuesta: '4' }), true);
});
prueba('respuesta cambiada: corregir el texto de una opción errónea no cambia la respuesta', () => {
  const a = proc.firmaRespuesta('multichoice', { letras: ['A'], respuesta: 'Python' });
  const b = proc.firmaRespuesta('multichoice', { letras: ['A'], respuesta: 'Python' });
  igual(proc.respuestaCambio(a, b), false);
  igual(proc.respuestaCambio(proc.firmaRespuesta('truefalse', { respuesta: 'verdadero ' }), proc.firmaRespuesta('truefalse', { respuesta: 'Verdadero' })), false);
});
prueba('marcarSiCambio: pone «docente» solo si cambió y deja confianza, page y recuadro idénticos', () => {
  const base = () => ({ stem: 'x', origen_respuesta: 'ia', confianza: 'baja', page: 4, recuadro: [0.1, 0.2, 0.9, 0.5] });
  const sin = proc.marcarSiCambio(base(), false);
  igual(sin, base());
  const con = proc.marcarSiCambio(base(), true);
  igual(con, { ...base(), origen_respuesta: 'docente' });
  igual(proc.marcarSiCambio(null, true), null);
  igual(proc.marcarSiCambio({}, true), { origen_respuesta: 'docente' });
});

prueba('revisar primero: confianza baja u origen IA, salvo que el docente ya la editó', () => {
  igual(proc.necesitaRevisarPrimero({ confianza: 'baja' }), true);
  igual(proc.necesitaRevisarPrimero({ origen_respuesta: 'ia', confianza: 'alta' }), true);
  igual(proc.necesitaRevisarPrimero({ origen_respuesta: 'documento', confianza: 'media' }), false);
  igual(proc.necesitaRevisarPrimero({ origen_respuesta: 'marca' }), false);
  igual(proc.necesitaRevisarPrimero({ origen_respuesta: 'docente', confianza: 'baja' }), false);
  igual(proc.necesitaRevisarPrimero({}), false);
  igual(proc.necesitaRevisarPrimero(undefined), false);
  igual(proc.motivoRevisarPrimero({ confianza: 'baja' }), 'confianza baja en la respuesta');
  igual(proc.motivoRevisarPrimero({ origen_respuesta: 'ia' }), 'respuesta interpretada por la IA');
  igual(proc.motivoRevisarPrimero({ origen_respuesta: 'ia', confianza: 'baja' }), 'respuesta interpretada por la IA con confianza baja');
  igual(proc.motivoRevisarPrimero({ confianza: 'alta' }), '');
});
prueba('revisar primero: se suma a los avisos de siempre sin duplicar el de confianza baja', () => {
  igual(proc.requiereRevision({ from_table: true }), true);
  igual(proc.requiereRevision({ low_confidence: true }), true);                       // sin campos nuevos: como antes
  igual(proc.requiereRevision({ low_confidence: true, confianza: 'alta' }), true);
  igual(proc.requiereRevision({ low_confidence: true, confianza: 'baja', origen_respuesta: 'docente' }), false);
  igual(proc.requiereRevision({ origen_respuesta: 'ia' }), true);
  igual(proc.requiereRevision({ origen_respuesta: 'documento', confianza: 'alta' }), false);
  igual(proc.mostrarAvisoConfianzaLegado({ low_confidence: true }), true);
  igual(proc.mostrarAvisoConfianzaLegado({ low_confidence: true, confianza: 'baja' }), false);
  igual(proc.mostrarAvisoMarcaLegado({ answer_from_marks: true }), true);
  igual(proc.mostrarAvisoMarcaLegado({ answer_from_marks: true, origen_respuesta: 'marca' }), false);
});
prueba('filtro «Revisar primero» reutiliza el filtro por tipo: todas, un tipo o las dudosas', () => {
  const preg = [
    { type: 'multichoice', data: { origen_respuesta: 'ia' } },
    { type: 'truefalse', data: { confianza: 'baja' } },
    { type: 'truefalse', data: { origen_respuesta: 'documento', confianza: 'alta' } },
    { type: 'essay', data: {} },
    { type: 'cloze', data: { origen_respuesta: 'docente', confianza: 'baja' } },
  ];
  const ver = (f) => preg.filter(q => proc.coincideConFiltro(f, { tipo: q.type, revisar: proc.necesitaRevisarPrimero(q.data) })).length;
  igual([ver('all'), ver('truefalse'), ver(proc.FILTRO_REVISAR), ver('cloze')], [5, 2, 2, 1]);
  igual(proc.contarRevisarPrimero(preg), 2);
  igual(proc.contarRevisarPrimero(null), 0);
});

prueba('conservación: los 4 campos salen idénticos al copiar la pregunta, sin las imágenes', () => {
  const q = {
    num: 7, type: 'multichoice', points: 2.5,
    data: { stem: 'x', options: { A: 'a', B: 'b' }, images: [{ mime: 'image/png', b64: 'AAAA' }],
      origen_respuesta: 'marca', confianza: 'media', page: 12, recuadro: [0.05, 0.1, 0.95, 0.4] },
  };
  const c = proc.copiaSinImagenes(q);
  for (const campo of ['origen_respuesta', 'confianza', 'page', 'recuadro']) igual(c.data[campo], q.data[campo], campo);
  igual('images' in c.data, false);
  igual(c.num, 7);
  c.data.recuadro[0] = 9;                       // es una copia: no toca la original
  igual(q.data.recuadro[0], 0.05);
});
prueba('conservación: borrador, reabrir del Historial, borrar y deshacer, cambiar tipo y repartir puntos no pierden los campos', () => {
  const campos = (d) => ({ o: d.origen_respuesta, c: d.confianza, p: d.page, r: d.recuadro });
  const q0 = { num: 3, type: 'truefalse', points: 1,
    data: { stem: 'x', origen_respuesta: 'ia', confianza: 'baja', page: 5, recuadro: [0.1, 0.25, 0.9, 0.6] } };
  const esperado = campos(q0.data);
  // borrador (localStorage) y editor_json del Historial: ida y vuelta por JSON
  const vuelta = JSON.parse(JSON.stringify({ questions: [q0], answer_key: { 3: { type: 'truefalse', answer: 'Verdadero' } } }));
  igual(campos(vuelta.questions[0].data), esperado);
  // collectEditorData en cada recorrido: se copia con copiaSinImagenes
  let q = proc.copiaSinImagenes(vuelta.questions[0]);
  // borrar y deshacer: el objeto borrado se guarda tal cual y se reinserta
  const borrada = q; const res = { questions: [] }; res.questions.splice(0, 0, borrada);
  q = proc.copiaSinImagenes(res.questions[0]);
  igual(campos(q.data), esperado);
  // cambiar de tipo (V/F → respuesta corta) y repartir puntos: solo cambia el origen
  q.type = 'shortanswer'; proc.marcarSiCambio(q.data, true);
  autoDistributePoints([q], 10, 'byType');
  igual(campos(q.data), { ...esperado, o: 'docente' });
  q = proc.copiaSinImagenes(q);
  igual(campos(q.data), { ...esperado, o: 'docente' });
});

// ── Respuestas por índice (opciones con « | » o « / » dentro) ─────────
prueba('indicesUtilizables: enteros dentro de rango, sin repetir; si no, null', () => {
  igual(indicesUtilizables([1, 0, 1], 3), [1, 0]);
  igual(indicesUtilizables([], 3), null);
  igual(indicesUtilizables(undefined, 3), null);
  igual(indicesUtilizables([3], 3), null);
  igual(indicesUtilizables([-1], 3), null);
  igual(indicesUtilizables(['1'], 3), null);
  igual(indicesUtilizables([1.5], 3), null);
});

prueba('opción múltiple: una opción "x | y" marcada viaja como posición y no se parte', () => {
  const op = { A: 'a || b', B: 'x | y', C: 'x & y', D: 'ninguna' };
  const clave = claveDeOpcionMultiple(op, ['B']);
  igual(clave, { answer: 'x | y', correct_idx: [1] });
  igual(letrasCorrectasPorIndice(op, clave), ['B']);
  // varias correctas, una de ellas con " | " dentro
  const varias = claveDeOpcionMultiple(op, ['A', 'B']);
  igual(varias, { answer: 'a || b | x | y', correct_idx: [0, 1] });
  igual(letrasCorrectasPorIndice(op, varias), ['A', 'B']);
  igual(splitAnswers(varias.answer), ['a || b', 'x', 'y']); // el texto solo no alcanza
});

prueba('opción múltiple: sin posiciones, o con texto distinto, se vuelve al texto de siempre', () => {
  const op = { A: 'x | y', B: 'z' };
  igual(letrasCorrectasPorIndice(op, { answer: 'z' }), null);                       // clave vieja
  igual(letrasCorrectasPorIndice(op, { answer: 'z', correct_idx: [0] }), null);      // texto editado aparte
  igual(letrasCorrectasPorIndice(op, { answer: 'x | y', correct_idx: [5] }), null); // fuera de rango
  igual(letrasCorrectasPorIndice(op, null), null);
  igual(claveDeOpcionMultiple(op, []), { answer: '' });                             // nada marcado: sin correct_idx
  igual(claveDeOpcionMultiple({ A: '', B: 'z' }, ['A']), { answer: '' });            // opción vacía no cuenta
});

prueba('completar: una opción "10 / 2" se conserva entera con la estructura de huecos', () => {
  const texto = 'Resultado: [A: 10 / 2 / 5 / 3]';
  const huecos = [{ letra: 'A', options: ['10 / 2', '5', '3'], correct_idx: [0] }];
  // el texto solo se parte mal...
  igual(parseClozeSegments(texto, 'A. 10 / 2')[1].options, ['10', '2', '5', '3']);
  // ...con la estructura no
  const [, hueco] = parseClozeSegments('Resultado: [A: 10 / 2 / 5 / 3]', 'A. 10 / 2', huecos);
  igual(hueco.options, ['10 / 2', '5', '3']);
  igual(hueco.correctIndices, [0]);
});

prueba('completar: una correcta "x | y" y varias correctas con la estructura', () => {
  const huecos = [
    { letra: 'A', options: ['x | y', 'z'], correct_idx: [0] },
    { letra: 'B', options: ['a', 'b | c', 'd'], correct_idx: [1, 2] },
  ];
  const texto = '[A: x | y / z] y [B: a / b | c / d]';
  const clave = 'A. x | y; B. b | c | d';
  const bs = parseClozeSegments(texto, clave, huecos).filter(s => s.type === 'blank');
  igual(bs.map(b => b.options), [['x | y', 'z'], ['a', 'b | c', 'd']]);
  igual(bs.map(b => b.correctIndices), [[0], [1, 2]]);
  igual(bs.map(b => b.multi), [false, true]);
});

prueba('completar: ida y vuelta del constructor (texto, clave y huecos) sin perder nada', () => {
  const segs = [
    { type: 'text', value: 'Calcula ' },
    { type: 'blank', options: ['10 / 2', ' ', '5', 'x | y'], correctIndices: [0, 3], multi: true },
    { type: 'text', value: ' y ' },
    { type: 'blank', options: ['uno', 'dos'], correctIndices: [], multi: false },
  ];
  const r = construirClozeDesdeSegmentos(segs);
  igual(r.text, 'Calcula [A: 10 / 2 / 5 / x | y] y [B: uno / dos]');
  igual(r.answer, 'A. 10 / 2 | x | y');
  igual(r.huecos, [
    { letra: 'A', options: ['10 / 2', '5', 'x | y'], correct_idx: [0, 2] },
    { letra: 'B', options: ['uno', 'dos'], correct_idx: [] },
  ]);
  const vuelta = parseClozeSegments(r.text, r.answer, r.huecos);
  igual(vuelta.filter(s => s.type === 'blank').map(b => [b.options, b.correctIndices]),
    [[['10 / 2', '5', 'x | y'], [0, 2]], [['uno', 'dos'], []]]);
});

prueba('completar: estado viejo (sin huecos) o que ya no concuerda se reconstruye como antes', () => {
  igual(parseClozeSegments('Es [A: uno / dos]', 'A. dos')[1].correctIndices, [1]);
  igual(parseClozeSegments('Es [A: uno / dos]', 'A. dos', undefined)[1].correctIndices, [1]);
  igual(parseClozeSegments('Es [A: uno / dos]', 'A. dos', [])[1].correctIndices, [1]);
  // enunciado editado por otro lado: la estructura vieja se ignora
  const vieja = [{ letra: 'A', options: ['uno', 'tres'], correct_idx: [1] }];
  igual(parseClozeSegments('Es [A: uno / dos]', 'A. tres', vieja)[1].options, ['uno', 'dos']);
  igual(huecoDeEstructura(vieja, 'A', 'uno / dos', 'A. tres'), null);
  // clave editada aparte: se conservan las opciones pero las posiciones no valen
  const h = huecoDeEstructura([{ letra: 'A', options: ['uno', 'dos'], correct_idx: [0] }], 'A', 'uno / dos', 'A. dos');
  igual(h, { options: ['uno', 'dos'], indices: null });
  igual(parseClozeSegments('Es [A: uno / dos]', 'A. dos', [{ letra: 'A', options: ['uno', 'dos'], correct_idx: [0] }])[1].correctIndices, [1]);
});

// ── Tarjetas plegables (editor/plegado-logica.js) y chips visibles ──────────
prueba('plegado: sin avisos solo se abre la primera; con avisos, las que piden revisión (tope MAX_ABIERTAS)', () => {
  igual(abiertasPorDefecto([{}, {}, {}]), [true, false, false]);
  igual(abiertasPorDefecto([{}, { revisar: true }, {}, { incompleta: true }]), [false, true, false, true]);
  const muchas = Array.from({ length: 10 }, () => ({ revisar: true }));
  const r = abiertasPorDefecto(muchas);
  igual(r.filter(Boolean).length, MAX_ABIERTAS);
  igual(r.slice(0, MAX_ABIERTAS), [true, true, true]);
});
prueba('plegado: listas vacías o inválidas no rompen', () => {
  igual(abiertasPorDefecto([]), []);
  igual(abiertasPorDefecto(null), []);
});
prueba('plegado: el resumen se recorta a una línea con «…» y colapsa espacios y saltos', () => {
  igual(recortar('  Hola\n\n  mundo  '), 'Hola mundo');
  igual(recortar(null), '');
  const largo = recortar('palabra '.repeat(50), 40);
  igual(largo.length <= 40 && largo.endsWith('…'), true);
  igual(recortar('corto', 10), 'corto');
});
prueba('chips visibles: solo la página y lo que se sale de lo normal', () => {
  const t = (d, tipo = 'multichoice') => textos(proc.chipsVisibles(d, tipo));
  igual(t({ page: 3, origen_respuesta: 'documento', confianza: 'alta' }), ['Pág. 3']);
  igual(t({ page: 3, origen_respuesta: 'marca', confianza: 'alta' }), ['Pág. 3']);
  igual(t({ page: 3, origen_respuesta: 'marca', confianza: 'media' }), ['Pág. 3', 'Confianza media']);
  igual(t({ origen_respuesta: 'ia', confianza: 'baja' }), ['Interpretada por la IA — revisar', 'Confianza baja']);
  igual(t({ origen_respuesta: 'docente', confianza: 'baja' }), ['Editada por ti']);
  igual(t({}), []);
});
prueba('chips visibles: no cambian lo que chipsDeProcedencia sabe (el detalle completo sigue ahí)', () => {
  igual(textos(proc.chipsDeProcedencia({ page: 3, origen_respuesta: 'documento', confianza: 'alta' }, 'multichoice')),
    ['Pág. 3', 'Clave del documento', 'Confianza alta']);
});

// ── Revisión con el original (ui/original-logica.js) ─────────────────────────
prueba('original: la dirección de la imagen lleva página, vista, recuadro y zoom', () => {
  const rec = [0.1, 0.2, 0.6, 0.3];
  igual(urlOriginal('abc', 3, { vista: 'recorte', recuadro: rec, zoom: 1 }), '/api/original/abc/pagina/3?vista=recorte&recuadro=0.1%2C0.2%2C0.6%2C0.3');
  igual(urlOriginal('abc', 3, { vista: 'pagina', recuadro: rec, zoom: 2 }), '/api/original/abc/pagina/3?vista=pagina&recuadro=0.1%2C0.2%2C0.6%2C0.3&zoom=2');
  // sin recuadro válido solo hay página completa, aunque se pida el recorte
  igual(urlOriginal('abc', 1, { vista: 'recorte', recuadro: null }), '/api/original/abc/pagina/1?vista=pagina');
  igual(urlOriginal('abc', 1, { vista: 'recorte', recuadro: [0.5, 0.5, 0.5, 0.5] }), '/api/original/abc/pagina/1?vista=pagina');
});
prueba('original: el id se escapa en la dirección', () => {
  igual(urlOriginal('a/b?c', 1).startsWith('/api/original/a%2Fb%3Fc/pagina/1'), true);
});
prueba('original: recuadro y página válidos', () => {
  igual(recuadroValido([0, 0, 1, 1]), true);
  igual([null, [], [0, 0, 1], [0, 0, 2, 1], [0.6, 0, 0.1, 1], ['a', 0, 1, 1]].map(recuadroValido), [false, false, false, false, false, false]);
  igual([paginaDe({ page: 4 }), paginaDe({ page: 0 }), paginaDe({ page: 2.5 }), paginaDe({}), paginaDe(null)], [4, null, null, null, null]);
});
prueba('original: zoom entre los niveles, sin salirse', () => {
  igual(ZOOMS, [1, 1.5, 2, 3]);
  igual([zoomVecino(1, 1), zoomVecino(1, -1), zoomVecino(3, 1), zoomVecino(2, -1), zoomVecino(7, 1)], [1.5, 1, 3, 1.5, 1.5]);
});
prueba('original: pasar a la contigua y a la siguiente «para revisar»', () => {
  const marcas = [false, true, false, false, true, false];
  igual([vecino(marcas, 0, 1), vecino(marcas, 5, 1), vecino(marcas, 0, -1)], [1, -1, -1]);
  igual([vecino(marcas, 0, 1, true), vecino(marcas, 1, 1, true), vecino(marcas, 4, 1, true), vecino(marcas, 4, -1, true), vecino(marcas, 5, -1, true), vecino(marcas, 1, -1, true)], [1, 4, -1, 1, 4, -1]);
  igual(vecino([], 0, 1), -1);
});
prueba('original: el chip «Pág. N» es botón solo si hay original en esta sesión', () => {
  const chips = proc.chipsDeProcedencia({ page: 3, origen_respuesta: 'ia' }, 'multichoice');
  const sin = proc.chipsHtml(chips);
  const con = proc.chipsHtml(chips, { original: true });
  igual(sin.includes('<button'), false);
  igual(con.split('<button').length - 1, 1);
  igual(con.includes('data-accion="verOriginal"') && con.includes('ver esta pregunta en el documento original'), true);
  // el de origen sigue siendo informativo
  igual(con.includes('role="img"'), true);
});

// ── IA asistida: avisos de calidad sin IA (editor/calidad.js) y sugerencias ────
const pmc = (num, stem, opciones, correct) => ({ num, type: 'multichoice', data: { stem, options: Object.fromEntries(opciones.map((o, i) => [String.fromCharCode(65 + i), o])) }, _c: correct });
const clavesDe = (qs) => Object.fromEntries(qs.map(q => [q.num, { type: q.type, correct_idx: q._c || [] }]));

prueba('calidad: normalizar y similitud ignoran tildes, mayúsculas y signos', () => {
  igual(normalizar('¿Cuál es el RÍO más largo?'), 'cual es el rio mas largo');
  igual(similitud('El río Amazonas', 'el rio amazonas!'), 1);
  igual(similitud('uno dos', 'tres cuatro'), 0);
});
prueba('calidad: dos preguntas casi iguales se avisan en las dos, con el número de la otra', () => {
  const qs = [
    pmc(1, '¿Cuál es el planeta más grande del sistema solar?', ['Marte', 'Júpiter', 'Venus'], [1]),
    pmc(2, '¿Qué gas respiramos?', ['Oxígeno', 'Helio'], [0]),
    pmc(3, 'Cual es el planeta mas grande del sistema solar', ['Júpiter', 'Marte', 'Venus'], [0]),
  ];
  const r = detectarProblemas(qs, clavesDe(qs));
  igual(r[0], ['Parece repetida con la pregunta 3']);
  igual(r[2], ['Parece repetida con la pregunta 1']);
  igual(r[1], []);
});
prueba('calidad: preguntas distintas o de otro tipo no se marcan como repetidas', () => {
  const a = pmc(1, '¿Cuánto es 2 + 2?', ['3', '4'], [1]);
  const b = { num: 2, type: 'truefalse', data: { stem: '¿Cuánto es 2 + 2?' } };
  const c = pmc(3, '¿Cuánto es 3 + 3?', ['5', '6'], [1]);
  igual(detectarProblemas([a, b, c], clavesDe([a, b, c])), [[], [], []]);
});
prueba('calidad: enunciados cortos y genéricos se comparan también por sus opciones', () => {
  const a = pmc(1, 'Elige la correcta', ['rojo', 'azul'], [0]);
  const b = pmc(2, 'Elige la correcta', ['perro', 'gato'], [0]);
  igual(detectarProblemas([a, b], clavesDe([a, b])), [[], []]);
  const c = pmc(3, 'Elige la correcta', ['rojo', 'azul'], [1]);
  igual(detectarProblemas([a, c], clavesDe([a, c])).map(x => x.length), [1, 1]);
});
prueba('calidad: los operadores y signos distinguen opciones y preguntas (programación y matemáticas)', () => {
  const ops = pmc(1, '¿Qué operador hace una O bit a bit?', ['x | y', 'x || y', 'x & y'], [0]);
  igual(detectarProblemas([ops], clavesDe([ops]))[0], []);
  const sim = pmc(2, '¿Qué desigualdad describe «x es mayor o igual que 5»?', ['x ≠ 5', 'x ≤ 5', 'x ≥ 5'], [2]);
  igual(detectarProblemas([sim], clavesDe([sim]))[0], []);
  const comillas = pmc(3, '¿Cuál va entre comillas?', ['"Hola"', "'Hola'", '«Hola»'], [2]);
  igual(detectarProblemas([comillas], clavesDe([comillas]))[0], []);
  const a = pmc(4, 'Elige la salida del programa', ['x | y', 'z'], [0]);
  const b = pmc(5, 'Elige la salida del programa', ['x || y', 'z'], [0]);
  igual(detectarProblemas([a, b], clavesDe([a, b])), [[], []]);
});
prueba('calidad: mismo enunciado y distintas opciones NO son duplicadas; con imagen tampoco se comparan', () => {
  const a = pmc(1, 'Observa el siguiente programa. ¿Cuál es su resultado?', ['Error', 'None', 'False', 'True'], [0]);
  const b = pmc(2, 'Observa el siguiente programa. ¿Cuál es su resultado?', ['16', '10', '12', '24'], [0]);
  igual(detectarProblemas([a, b], clavesDe([a, b])), [[], []]);
  const c = pmc(3, 'Observa el siguiente programa. ¿Cuál es su resultado?', ['Error', 'None', 'False', 'True'], [1]);
  igual(detectarProblemas([a, c], clavesDe([a, c])).map(x => x.length), [1, 1]);
  igual(detectarProblemas([a, c], clavesDe([a, c]), { conImagen: [true, false] }), [[], []]);
});
prueba('calidad: opciones repetidas, opción correcta repetida como incorrecta y todas marcadas', () => {
  const rep = pmc(1, '¿Cuál?', ['Sí', 'No', 'sí'], [0]);
  const r = detectarProblemas([rep], clavesDe([rep]))[0];
  igual(r.some(t => t.startsWith('Las opciones A y C dicen lo mismo')), true);
  igual(r.some(t => t.includes('es correcta pero C dice lo mismo')), true);
  const todas = pmc(2, '¿Cuáles?', ['uno', 'dos'], [0, 1]);
  igual(detectarProblemas([todas], clavesDe([todas]))[0], ['Todas las opciones están marcadas como correctas']);
});
prueba('calidad: «todas las anteriores» y «A y B» dependen del orden, que Moodle mezcla', () => {
  const t = pmc(1, '¿Cuáles son frutas?', ['Manzana', 'Pera', 'Todas las anteriores'], [2]);
  igual(detectarProblemas([t], clavesDe([t]))[0].length, 1);
  igual(detectarProblemas([t], clavesDe([t]))[0][0].includes('Moodle mezcla el orden'), true);
  const l = pmc(2, '¿Cuáles?', ['uno', 'dos', 'A y B'], [2]);
  igual(detectarProblemas([l], clavesDe([l]))[0].length, 1);
  const e = pmc(3, 'Según la opción B, ¿qué pasa?', ['x', 'y', 'z'], [0]);
  igual(detectarProblemas([e], clavesDe([e]))[0][0].includes('letra'), true);
  const ok1 = pmc(4, '¿Cuál es el planeta rojo?', ['Marte', 'Venus'], [0]);
  igual(detectarProblemas([ok1], clavesDe([ok1])), [[]]);
});
prueba('calidad: emparejamiento y completar con elementos repetidos', () => {
  const m = { num: 1, type: 'matching', data: { stem: 'x', col_a: { 1: 'uno', 2: 'dos' }, col_b: { a: 'igual', b: 'Igual' } } };
  igual(detectarProblemas([m], {})[0].length, 1);
  const c = { num: 1, type: 'cloze', data: { text: 'Es [A: x / x]' } };
  igual(detectarProblemas([c], { 1: { huecos: [{ options: ['x', 'x'] }] } })[0], ['El espacio 1 tiene opciones repetidas']);
  igual(detectarProblemas([], {}), []);
  igual(detectarProblemas(null), []);
});
prueba('IA asistida: «Sugerir respuesta» solo cuando FALTA la respuesta', () => {
  igual(faltaRespuesta(['Falta marcar la respuesta correcta']), true);
  igual(faltaRespuesta(['Falta la respuesta']), true);
  igual(faltaRespuesta(['Falta elegir Verdadero o Falso']), true);
  igual(faltaRespuesta(['Falta marcar la respuesta correcta del espacio 2']), true);
  igual(faltaRespuesta(['Falta el enunciado', 'Hay una opción vacía']), false);
  igual(faltaRespuesta(['La respuesta debe ser un número']), false);
  igual(faltaRespuesta([]), false);
  igual(faltaRespuesta(null), false);
});
prueba('IA asistida: lo aceptado queda «sugerida» y con confianza baja; lo editado, «docente»', () => {
  const d1 = { confianza: 'media', page: 2 };
  proc.marcarSiCambio(d1, true, true);
  igual([d1.origen_respuesta, d1.confianza, d1.page], ['sugerida', 'baja', 2]);
  const d2 = { confianza: 'alta' };
  proc.marcarSiCambio(d2, true, false);
  igual([d2.origen_respuesta, d2.confianza], ['docente', 'alta']);
  const d3 = { confianza: 'alta' };
  proc.marcarSiCambio(d3, false, true);
  igual(d3.origen_respuesta, undefined);
});
prueba('IA asistida: lo sugerido sale en «Revisar primero» y con su etiqueta', () => {
  igual(proc.necesitaRevisarPrimero({ origen_respuesta: 'sugerida', confianza: 'baja' }), true);
  igual(proc.necesitaRevisarPrimero({ origen_respuesta: 'docente', confianza: 'baja' }), false);
  igual(textos(proc.chipsVisibles({ origen_respuesta: 'sugerida', confianza: 'baja' }, 'multichoice')), ['Sugerida por IA — verifica', 'Confianza baja']);
  igual(proc.motivoRevisarPrimero({ origen_respuesta: 'sugerida', confianza: 'baja' }), 'respuesta interpretada por la IA con confianza baja');
  igual(proc.coincideConFiltro('problemas', { tipo: 'x', problemas: true }), true);
  igual(proc.coincideConFiltro('problemas', { tipo: 'x', problemas: false }), false);
});
prueba('IA asistida: la propuesta se lee en palabras', () => {
  const q = { data: { options: { A: 'Marte', B: 'Júpiter' }, col_a: { 1: 'Perú' }, col_b: { a: 'Lima' } } };
  igual(describirSugerencia('multichoice', { letras: ['B'] }, q), 'B. Júpiter');
  igual(describirSugerencia('matching', { pares: { 1: 'a' } }, q), 'Perú → Lima');
  igual(describirSugerencia('cloze', { huecos: { A: 1 } }, q), 'Espacio A: opción 2');
  igual(describirSugerencia('truefalse', { respuesta: 'Falso' }, q), 'Falso');
});

prueba('Exportar PDF: lo guardado se valida campo por campo', () => {
  const v = valoresIniciales({ docente: '  Ana   Pérez ', papel: 'folio', contenido: 'solo_clave', campos_estudiante: 'sí', materia: 5, institucion: 'x'.repeat(500) });
  igual(v.docente, 'Ana Pérez');
  igual(v.papel, 'carta');                       // desconocido: el de siempre
  igual(valoresIniciales(null).margenes, 'moderados');
  igual(valoresIniciales({ margenes: 'anchos' }).margenes, 'anchos');
  igual(valoresIniciales({ margenes: 'enormes' }).margenes, 'moderados');
  igual(v.contenido, 'solo_clave');
  igual(valoresIniciales({ contenido: 'folleto_hoja_clave' }).contenido, 'folleto_hoja_clave');
  igual(v.campos_estudiante, true);              // no es booleano: el de siempre
  igual(v.materia, '');                          // no es texto
  igual(v.institucion.length, LIMITE_CAMPO);
  igual(valoresIniciales(null).contenido, 'examen_y_clave');
  igual(valoresIniciales(null).partes, true);
  igual(valoresIniciales(null).mezclar, true);
  igual(valoresIniciales({ mezclar: false }).mezclar, false);
  igual(valoresIniciales({ mezclar: 'no' }).mezclar, true);
  igual(valoresIniciales({ partes: false }).partes, false);
  igual(valoresIniciales({ partes: 'no' }).partes, true);
  igual(valoresIniciales('basura').papel, 'carta');
});
prueba('Exportar PDF: no se recuerda la fecha y sí lo demás', () => {
  const g = paraGuardar({ docente: 'Ana', fecha: '12 de octubre de 2026', papel: 'a4', instrucciones: 'Sin calculadora.' });
  igual('fecha' in g, false);
  igual([g.docente, g.papel, g.instrucciones], ['Ana', 'a4', 'Sin calculadora.']);
});
prueba('Exportar PDF: fecha legible y textos limpios', () => {
  igual(fechaLegible('2026-10-12'), '12 de octubre de 2026');
  igual(fechaLegible('2026-02-03'), '3 de febrero de 2026');
  igual(fechaLegible(''), '');
  igual(fechaLegible('12/10/2026'), '');
  igual(fechaLegible('2026-13-01'), '');
  igual(limpiarCampo('  a \n  b\t c '), 'a b c');
  igual(limpiarTexto('uno\r\n\n\n\ndos  tres'), 'uno\n\ndos tres');
});
prueba('Exportar PDF: el cuerpo lleva el mismo examen del XML y los datos limpios', () => {
  const examen = { filename: 'a.docx', total_points: 20, questions: [{ num: 1 }], answer_key: { 1: { answer: 'A' } } };
  const c = cuerpoPdf(examen, { docente: ' Ana ', fecha: '12 de octubre de 2026', contenido: 'solo_examen' });
  igual([c.filename, c.total_points, c.questions, c.answer_key], ['a.docx', 20, [{ num: 1 }], { 1: { answer: 'A' } }]);
  igual([c.datos.docente, c.datos.fecha, c.datos.contenido, c.datos.papel], ['Ana', '12 de octubre de 2026', 'solo_examen', 'carta']);
});
prueba('Exportar PDF: nombre del archivo y avisos de la respuesta', () => {
  igual(nombreDeDescarga("attachment; filename=\"examen.pdf\"; filename*=UTF-8''Ex%C3%A1men.pdf", 'x.pdf'), 'Exámen.pdf');
  igual(nombreDeDescarga('attachment; filename="a.pdf"', 'x.pdf'), 'a.pdf');
  igual(nombreDeDescarga(null, 'x.pdf'), 'x.pdf');
  igual(avisosDelPdf('{"paginas":3,"avisos":["Uno.","  "]}'), ['Uno.']);
  igual(avisosDelPdf('no es json'), []);
  igual(avisosDelPdf(null), []);
});

prueba('Exportar PDF: logos y encabezado de la institución', () => {
  igual(logoValido('iVBORw0KGgo='), true);
  igual(logoValido(''), false);
  igual(logoValido('data:image/png;base64,AAAA'), false);   // se guarda sin el «data:» delante
  igual(logoValido(5), false);
  igual(medidasReducidas(1600, 800), { ancho: 320, alto: 160 });
  igual(medidasReducidas(100, 50), { ancho: 100, alto: 50 });   // no se agranda
  igual(medidasReducidas(0, 50), null);
  const v = valoresIniciales({ facultad: ' Ingeniería ', rotulo_docente: 'jefe', logo_derecho: 'AAAA', logo_izquierdo: '<script>' });
  igual([v.facultad, v.rotulo_docente, v.logo_derecho, v.logo_izquierdo], ['Ingeniería', 'facilitador', 'AAAA', '']);
  igual(paraGuardar({ logo_izquierdo: 'AAAA', fecha: 'x' }).logo_izquierdo, 'AAAA');
});

prueba('Exportar PDF: tipo de letra y tamaños', () => {
  igual(tamanoValido('12'), 12);
  igual(tamanoValido('12,5'), 12.5);
  igual(tamanoValido(10.3), 10.5);          // medios puntos
  igual(tamanoValido('6'), null);
  igual(tamanoValido(21), null);
  igual(tamanoValido(''), null);
  igual(tamanoValido('abc'), null);
  igual(tamanoValido(NaN), null);
  const v = valoresIniciales({ fuente_titulos: 'times', tam_titulos: '12', fuente_preguntas: 'comic', tam_preguntas: 99 });
  igual([v.fuente_titulos, v.tam_titulos, v.fuente_preguntas, v.tam_preguntas], ['times', 12, 'dejavu', 10]);
  const d = valoresIniciales(null);
  igual([d.fuente_titulos, d.tam_titulos, d.fuente_preguntas, d.tam_preguntas], ['dejavu', 11, 'dejavu', 10]);
  igual(datosParaEnviar({ tam_titulos: '12', tam_preguntas: '10' }).tam_titulos, 12);
});

prueba('Exportar PDF: puntos por pregunta y renglones del ensayo', () => {
  const d = valoresIniciales(null);
  igual([d.puntos_por_pregunta, d.renglones_ensayo], [true, 6]);
  igual(valoresIniciales({ puntos_por_pregunta: false, renglones_ensayo: '10' }).renglones_ensayo, 10);
  igual(valoresIniciales({ puntos_por_pregunta: false }).puntos_por_pregunta, false);
  igual(valoresIniciales({ renglones_ensayo: 99 }).renglones_ensayo, 6);
  igual(valoresIniciales({ renglones_ensayo: 3.5 }).renglones_ensayo, 6);
  igual(enteroEn('8', 2, 24), 8);
  igual(enteroEn('', 2, 24), null);
  igual(enteroEn(1, 2, 24), null);
});
prueba('Exportar PDF: perfiles de encabezado', () => {
  igual(nombrePerfil('  UTP   Panamá '), 'UTP Panamá');
  igual(nombrePerfil('a/b\\c'), 'a-b-c');
  igual(nombrePerfil('x'.repeat(100)).length, 60);
  igual(nombrePerfil(null), '');
  igual(nombrePerfil('   '), '');
  const p = datosDePerfil({ institucion: ' UTP ', margenes: 'anchos', materia: 'NO', fecha: 'NO', contenido: 'solo_clave', logo_izquierdo: 'AAAA' });
  igual(Object.keys(p), PERFIL_CAMPOS);
  igual([p.institucion, p.margenes, p.logo_izquierdo, 'materia' in p, 'contenido' in p], ['UTP', 'anchos', 'AAAA', false, false]);
  const actuales = { ...valoresIniciales(null), materia: 'Física', actividad: 'Parcial 1', grupo: '3A', fecha: '12 de octubre de 2026', contenido: 'solo_clave', institucion: 'Otra' };
  const m = aplicarPerfil(actuales, { institucion: 'UTP', papel: 'legal' });
  igual([m.institucion, m.papel, m.materia, m.actividad, m.grupo, m.fecha, m.contenido], ['UTP', 'legal', 'Física', 'Parcial 1', '3A', '12 de octubre de 2026', 'solo_clave']);
});

// ── Mis materias (2.3) ─────────────────────────────────────────────────────
prueba('Mis materias: nombres sin mayúsculas ni tildes y sin repetir', () => {
  igual(normalizarMateria('  Cálculo   II '), 'calculo ii');
  const ms = [{ id: 1, nombre: 'Cálculo' }, { id: 2, nombre: 'Física' }];
  igual(existeNombre(ms, 'CALCULO'), true);
  igual(existeNombre(ms, 'calculo', 1), false, 'la que se edita no cuenta');
  igual(existeNombre(ms, '   '), false);
  igual(existeNombre(ms, 'Historia'), false);
});

prueba('Mis materias: colores y orden', () => {
  igual(variableDeColor('rosa'), '--color-es');
  igual(variableDeColor('no-existe'), COLORES[0].variable);
  const ms = [{ id: 1, nombre: 'Zoología', archivada: false }, { id: 2, nombre: 'Álgebra', archivada: true }, { id: 3, nombre: 'Ética', archivada: false }, { id: 4, nombre: 'Biología', archivada: false }];
  igual(ordenarMaterias(ms).map(m => m.nombre), ['Biología', 'Ética', 'Zoología', 'Álgebra'], 'las archivadas al final; con tildes en su sitio');
  igual(activas(ms).length, 3);
  igual(archivadas(ms).map(m => m.id), [2]);
});

prueba('Mis materias: exámenes de una materia, sin materia y todos; búsqueda', () => {
  const ex = [
    { id: 1, filename: 'a.pdf', category: 'Hist', materia_id: 7, actividad: 'Parcial 1', fecha: '3 oct 2026' },
    { id: 2, filename: 'b.pdf', category: 'Cálculo', materia_id: null },
    { id: 3, filename: 'c.docx', category: 'x', materia_id: 7, actividad: 'Quiz' },
  ];
  igual(examenesDe(ex, 7).map(e => e.id), [1, 3]);
  igual(examenesDe(ex, null).map(e => e.id), [2]);
  igual(examenesDe(ex, 'todos').length, 3);
  igual(filtrarExamenes(ex, 'calculo').map(e => e.id), [2], 'sin tildes');
  igual(filtrarExamenes(ex, 'parcial').map(e => e.id), [1], 'por actividad');
  igual(filtrarExamenes(ex, 'oct 2026').map(e => e.id), [1], 'por fecha');
  igual(filtrarExamenes(ex, 'historia', id => (id === 7 ? 'Historia' : '')).map(e => e.id), [1, 3], 'por nombre de la materia');
  igual(filtrarExamenes(ex, '').length, 3);
});

prueba('Mis materias: tamaños y fechas', () => {
  igual(formatoBytes(500), '500 B');
  igual(formatoBytes(2048), '2 KB');
  igual(formatoBytes(5 * 1024 * 1024), '5.0 MB');
  igual(formatoBytes(120 * 1024 * 1024), '120 MB');
  const ahora = Date.parse('2026-10-10T12:00:00Z');
  igual(fechaCorta('2026-10-10 08:00:00', ahora), 'hoy');
  igual(fechaCorta('2026-10-09 08:00:00', ahora), 'ayer');
  igual(fechaCorta('2026-10-01 08:00:00', ahora), 'hace 9 días');
  igual(fechaCorta('2026-07-01 08:00:00', ahora), 'hace 3 meses');
  igual(fechaCorta('2024-07-01 08:00:00', ahora), 'hace 2 años');
  igual(fechaCorta('basura', ahora), '');
  igual(fechaCorta('', ahora), '');
});

prueba('Mis materias: el aviso de que el Historial se llena', () => {
  igual(avisoDeLimite(null), null);
  igual(avisoDeLimite({ cerca_del_limite: false }), null);
  const base = { cerca_del_limite: true, examenes: 270, bytes: 50 * 1024 * 1024, maximo_examenes: 300, porcentaje: 90, sin_materia: 40 };
  const a = avisoDeLimite(base);
  igual(a.nivel, 'aviso');
  igual(a.titulo, 'El Historial se está llenando');
  igual(a.texto.includes('sin materia (hoy 40)'), true, 'dice cuántos son lo primero que se borra');
  const lleno = avisoDeLimite({ ...base, examenes: 300, porcentaje: 100, sin_materia: 0 });
  igual(lleno.nivel, 'lleno');
  igual(lleno.texto.includes('Todos tus exámenes tienen materia'), true, 'si no hay sin materia, lo dice');
  igual(textoUso({ examenes: 1, bytes: 2048, porcentaje: 0.3 }), '1 examen · 2 KB · 0 % del espacio');
});

prueba('Mis materias: la materia que sugiere la categoría o el archivo', () => {
  const sug = (category, filename = 'x.pdf') => nombreSugerido({ category, filename });
  igual(sug('Parcial-Historia-2026'), 'Historia');
  igual(sug('Quiz 2 - Cálculo II - 2026-1'), 'Cálculo II');
  igual(sug('PARCIAL DE FÍSICA'), 'Física', 'todo en mayúsculas se escribe normal');
  igual(sug('historia de panamá'), 'Historia de Panamá', 'las palabras de relleno quedan en minúscula');
  igual(sug('mis-preguntas', 'Examen Final Programación Web.docx'), 'Programación Web', 'sin categoría útil, usa el archivo');
  igual(sug('Parcial-1', 'Redes_Quiz3.pdf'), 'Redes', 'si la categoría solo dice qué es, usa el archivo');
  igual(sug('mis-preguntas', 'examen.pdf'), null, 'sin pista');
  igual(sug('', 'parcial 2.pdf'), null);
  igual(sug('Ab'), null, 'demasiado corto para ser una materia');
});

prueba('Mis materias: el asistente agrupa por materia y reconoce las que ya existen', () => {
  const ms = [{ id: 10, nombre: 'Historia de Panamá' }, { id: 11, nombre: 'Cálculo' }];
  const sin = [
    { id: 1, category: 'Parcial-Historia-2026', filename: 'a.pdf' },
    { id: 2, category: 'Quiz Historia', filename: 'b.pdf' },
    { id: 3, category: 'Examen Calculo 1', filename: 'c.pdf' },
    { id: 4, category: 'Parcial Redes', filename: 'd.pdf' },
    { id: 5, category: 'mis-preguntas', filename: 'examen.pdf' },
  ];
  const { grupos, sinPista } = sugerirMaterias(sin, ms);
  igual(sinPista, [5]);
  igual(grupos.map(g => [g.nombre, g.materiaId, g.ids]), [['Historia de Panamá', 10, [1, 2]], ['Cálculo', 11, [3]], ['Redes', null, [4]]], '«Historia» es la existente «Historia de Panamá»; «Calculo» es «Cálculo»; Redes es nueva');
  const marcados = [{ marcado: true, nombre: 'Historia de Panamá' }, { marcado: false, nombre: 'Cálculo' }, { marcado: true, nombre: 'Redes y Comunicaciones' }];
  igual(planDelAsistente(grupos, marcados), [
    { nombre: 'Historia de Panamá', materiaId: 10, ids: [1, 2] },
    { nombre: 'Redes y Comunicaciones', materiaId: null, ids: [4] },
  ], 'lo desmarcado no se mueve; un nombre cambiado a mano es otra materia');
  const cambiado = planDelAsistente(grupos, [{ marcado: true, nombre: 'Panamá' }, { marcado: false, nombre: 'x' }, { marcado: false, nombre: 'y' }]);
  igual(cambiado, [{ nombre: 'Panamá', materiaId: null, ids: [1, 2] }]);
  igual(sugerirMaterias([], ms), { grupos: [], sinPista: [] });
});

// ── Mi perfil (2.3) ────────────────────────────────────────────────────────
prueba('Mi perfil: las iniciales del avatar ignoran los tratamientos', () => {
  igual(iniciales('Ing. Ana Pérez'), 'AP');
  igual(iniciales('Dra. María de los Ángeles Ruiz'), 'MD');
  igual(iniciales('ana'), 'A');
  igual(iniciales('  Prof.  '), '', 'solo un tratamiento: sin iniciales');
  igual(iniciales(''), '');
  igual(iniciales(null), '');
  igual(iniciales('Álvaro Ñúñez'), 'ÁÑ', 'con tildes y eñes');
  igual(iniciales('123 456'), '');
});

prueba('Mi perfil: resúmenes de un perfil', () => {
  igual(resumenEncabezado({ institucion: 'UTP', facultad: ' ', departamento: 'Software' }), 'UTP · Software');
  igual(resumenEncabezado({}), 'Sin institución');
  igual(resumenFormato({ papel: 'legal', margenes: 'anchos', fuente_preguntas: 'times', tam_preguntas: 12 }), 'Legal · márgenes anchos · Times New Roman 12 pt');
  igual(resumenFormato({}), 'Carta · márgenes moderados · DejaVu Sans 10 pt');
});

prueba('Mi perfil: orden, copias y nombres repetidos', () => {
  const ps = [{ nombre: 'Zeta' }, { nombre: 'Álamo' }, { nombre: 'Medio' }];
  igual(ordenarPerfiles(ps, 'Medio').map(p => p.nombre), ['Medio', 'Álamo', 'Zeta'], 'el predeterminado primero');
  igual(ordenarPerfiles(ps, null).map(p => p.nombre), ['Álamo', 'Medio', 'Zeta']);
  igual(nombreCopia('UTP', ['UTP']), 'UTP (copia)');
  igual(nombreCopia('UTP', ['UTP', 'utp (copia)']), 'UTP (copia 2)');
  igual(nombreCopia('x'.repeat(60), ['x'.repeat(60)]).length <= 60, true, 'cabe en 60 caracteres');
  igual(nombreOcupado('utp', ['UTP', 'Otro']), true);
  igual(nombreOcupado('UTP', ['UTP'], 'UTP'), false, 'el que se edita no cuenta');
  igual(nombreOcupado('', ['UTP']), false);
  igual(materiasQueUsan([{ id: 1, perfil: 'UTP' }, { id: 2, perfil: null }, { id: 3, perfil: 'UTP' }], 'UTP').map(m => m.id), [1, 3]);
});

prueba('Mi perfil: el examen de ejemplo es un examen válido', () => {
  const e = ejemploExamen();
  igual(e.questions.length, 2);
  igual(Object.keys(e.answer_key).length, e.questions.length);
  igual(e.questions.every(q => q.points > 0 && q.data.stem), true);
  igual(e.questions.reduce((a, q) => a + q.points, 0), e.total_points);
});

// ── Recorridos guiados ─────────────────────────────────────────────────────
prueba('Recorridos: cada uno tiene pasos completos y lados válidos', () => {
  igual(Object.keys(TOURS).sort(), ['biblioteca', 'bibliotecaLista', 'cargar', 'final', 'pdf', 'perfil', 'revision']);
  for (const [nombre, t] of Object.entries(TOURS)) {
    igual(t.pasos.length >= 4, true, `${nombre}: muy corto`);
    for (const p of t.pasos) {
      igual(!!p.titulo && !!p.texto, true, `${nombre}: paso sin título o texto`);
      igual([undefined, 'top', 'bottom', 'left', 'right'].includes(p.lado), true, `${nombre}: lado inválido`);
      igual(p.el === null || typeof p.el === 'string', true, `${nombre}: elemento inválido`);
    }
  }
});

prueba('Recorridos: se saltan los pasos cuyo elemento no está en pantalla', () => {
  const pasos = [{ el: null }, { el: '#a' }, { el: '#b' }, { el: '.c' }];
  igual(pasosVisibles(pasos, s => s === '#b').map(p => p.el), [null, '#b']);
  igual(pasosVisibles(pasos, () => false).length, 1, 'el de presentación siempre queda');
  igual(pasosVisibles([], () => true), []);
});

prueba('Recorridos: «Mis materias» elige el de la raíz o el de una lista', () => {
  igual(nombreDeTour('biblioteca', { hayLista: false }), 'biblioteca');
  igual(nombreDeTour('biblioteca', { hayLista: true }), 'bibliotecaLista');
  igual(nombreDeTour('revision', { hayLista: true }), 'revision');
  igual(nombreDeTour('no-existe'), null);
  igual(nombreDeTour('__proto__'), null);
});

prueba('Recorridos: lo visto se recuerda y la bienvenida se ofrece una sola vez', () => {
  igual(CLAVE_VISTOS, 'conversor.tours');
  const vacio = leerVistos(null);
  igual(vacio, { vistos: [], descartado: false });
  igual(debeOfrecer(vacio), true);
  const visto = marcarVisto(vacio, 'cargar');
  igual(visto.vistos, ['cargar']);
  igual(debeOfrecer(visto), false);
  igual(marcarVisto(visto, 'cargar').vistos, ['cargar'], 'no se repite');
  igual(debeOfrecer({ vistos: [], descartado: true }), false, 'descartada');
  igual(debeOfrecer(marcarVisto(vacio, 'pdf')), true, 'otro recorrido no cuenta como la bienvenida');
  igual(leerVistos('basura'), vacio);
  igual(leerVistos('[1,2]'), vacio);
  igual(leerVistos('{"vistos":["a",3,"b"],"descartado":"si"}'), { vistos: ['a', 'b'], descartado: false });
});

// ── Cómo se muestra (solo en pruebas.html; en Node no hay lista y no hace nada) ──
const lista = document.getElementById('lista');
if (lista) {
  const resultados = ejecutarPruebas();
  let ok = 0, mal = 0;
  for (const { nombre, error } of resultados) {
    if (error === null) {
      ok++;
      lista.insertAdjacentHTML('beforeend', `<li>✅ ${nombre}</li>`);
    } else {
      mal++;
      lista.insertAdjacentHTML('beforeend', `<li class="mal">❌ ${nombre} — ${error}</li>`);
    }
  }
  const resumen = document.getElementById('resumen');
  resumen.textContent = mal === 0 ? `✅ ${ok} pruebas, todas pasan` : `❌ ${mal} fallan de ${ok + mal}`;
  resumen.className = mal === 0 ? 'ok' : 'fail';
  window.__resultado = { ok, mal };
}
