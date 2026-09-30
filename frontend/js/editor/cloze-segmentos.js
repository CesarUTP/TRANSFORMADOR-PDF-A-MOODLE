/**
 * cloze-segmentos.js — del texto "[A: opt1 / opt2]" de una pregunta de
 * completar (más la respuesta guardada en la clave) a la lista de segmentos
 * que dibuja el constructor visual. Lógica pura, sin DOM: se prueba sola
 * (ver frontend/pruebas.html).
 */
import { findClozeBrackets, splitAnswers, splitOptions } from '../util.js';

// Convierte el texto crudo "[A: opt1 / opt2]" (+ la respuesta guardada
// en la clave) en una lista ordenada de segmentos {type:'text', value}
// y {type:'blank', options, correctIndices, multi}. Un espacio "multi"
// permite marcar más de una opción como correcta (Moodle MULTIRESPONSE_S,
// casillas) en vez de una sola (MULTICHOICE_S, opción única).
// Si la clave no trae la respuesta de un espacio, `correctIndices` queda
// VACÍO: nunca se marca una opción por su cuenta (sin marca en el documento
// no se inventa respuesta). El docente tiene que elegirla; mientras tanto
// el espacio se ve como incompleto (ver questionIssues).
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
    const options = splitOptions(optionsRaw);
    if (options.length === 0) options.push('', '');

    const wantedList = keyMap[letter] || [];
    let correctIndices = [];
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
