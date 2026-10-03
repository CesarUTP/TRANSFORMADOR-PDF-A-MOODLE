/**
 * cloze-segmentos.js — del texto "[A: opt1 / opt2]" de una pregunta de
 * completar (más la respuesta guardada en la clave) a la lista de segmentos
 * que dibuja el constructor visual, y de vuelta (texto + clave + huecos).
 * Lógica pura, sin DOM: se prueba sola (ver frontend/pruebas.html).
 *
 * Una opción cuyo propio texto lleva " / " ("10 / 2") o " | " ("x | y") no se
 * puede recuperar del texto unido. Por eso la clave guarda además la
 * estructura de cada hueco (answer_key[n].huecos, ver backend/modelo.py):
 *   [{ letra: 'A', options: ['10 / 2', '5'], correct_idx: [1] }]
 * con las opciones como LISTA y las correctas por posición (base 0). Se usa
 * solo si concuerda con el texto del enunciado y con la clave; si falta (un
 * historial o un borrador viejo) se parte el texto como siempre.
 */
import { findClozeBrackets, splitAnswers, splitOptions } from '../util.js';

const colapsar = (t) => String(t || '').split(/\s+/).filter(Boolean).join(' ');

/** Índices sin repetir, o null si no sirven (no es lista, vacía, o fuera de 0..n-1). */
export function indicesUtilizables(indices, n) {
  if (!Array.isArray(indices) || !indices.length) return null;
  const out = [];
  for (const i of indices) {
    if (!Number.isInteger(i) || i < 0 || i >= n) return null;
    if (!out.includes(i)) out.push(i);
  }
  return out;
}

/**
 * Lo que la estructura `huecos` de la clave dice del hueco `letra` cuyo texto
 * entre corchetes es `optionsRaw`: { options, indices } (indices = null si no
 * valen o la clave no los respalda), o null si no hay estructura utilizable
 * para ese hueco. Misma regla que backend/modelo.py:_hueco_de_estructura.
 */
export function huecoDeEstructura(huecos, letra, optionsRaw, keyAnswer) {
  if (!Array.isArray(huecos)) return null;
  const h = huecos.find(x => x && typeof x.letra === 'string' && x.letra.toUpperCase() === String(letra).toUpperCase()
    && Array.isArray(x.options) && x.options.every(o => typeof o === 'string'));
  if (!h) return null;
  if (String(optionsRaw || '').trim() !== h.options.join(' / ')) return null;
  let indices = indicesUtilizables(h.correct_idx, h.options.length);
  if (indices && !colapsar(keyAnswer).includes(colapsar(`${h.letra.toUpperCase()}. ${indices.map(i => h.options[i]).join(' | ')}`))) {
    indices = null;
  }
  return { options: h.options.slice(), indices };
}

// Convierte el texto crudo "[A: opt1 / opt2]" (+ la respuesta guardada
// en la clave) en una lista ordenada de segmentos {type:'text', value}
// y {type:'blank', options, correctIndices, multi}. Un espacio "multi"
// permite marcar más de una opción como correcta (Moodle MULTIRESPONSE_S,
// casillas) en vez de una sola (MULTICHOICE_S, opción única).
// Si la clave no trae la respuesta de un espacio, `correctIndices` queda
// VACÍO: nunca se marca una opción por su cuenta (sin marca en el documento
// no se inventa respuesta). El docente tiene que elegirla; mientras tanto
// el espacio se ve como incompleto (ver questionIssues).
export function parseClozeSegments(text, keyAnswer, huecos = null) {
  const keyMap = {}; // letra -> [respuestas correctas...]
  if (keyAnswer) {
    const keySlotRegex = /([A-Za-z])[\.:]\s*([^;\n]+)/g;
    let km;
    while ((km = keySlotRegex.exec(keyAnswer)) !== null) {
      const parts = splitAnswers(km[2]);
      if (parts.length) keyMap[km[1].toUpperCase()] = parts;
    }
  }

  const brackets = findClozeBrackets(text);
  // Clave de un solo espacio sin letra ("vegetal" a secas): vale para ese
  // espacio, igual que hace el backend (validator.py).
  if (!Object.keys(keyMap).length && brackets.length === 1 && (keyAnswer || '').trim()) {
    const solo = splitAnswers(keyAnswer);
    if (solo.length) keyMap[brackets[0].letter.toUpperCase()] = solo;
  }

  const segments = [];
  let last = 0;
  brackets.forEach(({ start, end, letter: rawLetter, optionsRaw }) => {
    if (start > last) segments.push({ type: 'text', value: text.slice(last, start) });
    const letter = rawLetter.toUpperCase();
    const propio = huecoDeEstructura(huecos, letter, optionsRaw, keyAnswer);
    const options = propio ? propio.options : splitOptions(optionsRaw);
    if (options.length === 0) options.push('', '');

    const wantedList = keyMap[letter] || [];
    let correctIndices = [];
    if (propio && propio.indices) {
      // La clave trae las correctas por posición: no hay texto que partir.
      segments.push({ type: 'blank', options, correctIndices: propio.indices.slice(), multi: propio.indices.length > 1 });
      last = end;
      return;
    }
    wantedList.forEach(wanted => {
      const idx = options.findIndex(o => o.toLowerCase() === wanted.toLowerCase());
      if (idx >= 0 && !correctIndices.includes(idx)) correctIndices.push(idx);
    });
    segments.push({ type: 'blank', options, correctIndices, multi: correctIndices.length > 1 });
    last = end;
  });
  if (last < (text || '').length || segments.length === 0) {
    segments.push({ type: 'text', value: (text || '').slice(last) });
  }
  return segments;
}

/**
 * El camino de vuelta: de los segmentos del constructor (los mismos de
 * parseClozeSegments) al texto "[A: x / y]", la clave "A. x; B. y | z" y la
 * estructura de cada hueco ({ letra, options, correct_idx }) que viaja en
 * answer_key[n].huecos. Las opciones vacías (filas agregadas y nunca
 * completadas) se omiten; un hueco sin opción marcada no lleva respuesta en
 * la clave (no se elige una por el docente) pero sí su estructura, con
 * correct_idx vacío, para no perder sus opciones.
 */
export function construirClozeDesdeSegmentos(segments) {
  let text = '';
  let letterCode = 65; // 'A'
  const answerParts = [];
  const huecos = [];
  segments.forEach(seg => {
    if (seg.type === 'text') {
      text += seg.value;
      return;
    }
    const letter = String.fromCharCode(letterCode++);
    const rawOpts = seg.options.map(o => o.trim());
    const opts = [];
    const nuevoIndice = new Map(); // posición en rawOpts -> posición en opts
    rawOpts.forEach((o, i) => { if (o.length > 0) { nuevoIndice.set(i, opts.length); opts.push(o); } });
    const correctIdx = [];
    seg.correctIndices.forEach(i => {
      if (nuevoIndice.has(i) && !correctIdx.includes(nuevoIndice.get(i))) correctIdx.push(nuevoIndice.get(i));
    });
    text += `[${letter}: ${opts.join(' / ')}]`;
    if (correctIdx.length) answerParts.push(`${letter}. ${correctIdx.map(i => opts[i]).join(' | ')}`);
    huecos.push({ letra: letter, options: opts, correct_idx: correctIdx });
  });
  return { text, answer: answerParts.join('; '), huecos };
}
