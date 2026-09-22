/**
 * validacion.js — qué le falta a una pregunta para poder generar el XML.
 *
 * Son las MISMAS reglas que backend/validator.py, aplicadas mientras el
 * docente edita: lo que aquí sale como problema es lo que haría fallar
 * "Aprobar". La validación que manda sigue siendo la del backend.
 *
 * Lógica pura: no toca el DOM ni el estado global, así se puede probar
 * sola (ver frontend/pruebas.html).
 */
import { findClozeBrackets, splitOptions } from './util.js';

// ── Preguntas incompletas (revisión en vivo) ───────────────────────────
// Mismas reglas que el validador del backend (validator.py): lo que
// aquí se marca como incompleto es lo que haría fallar "Aprobar". Se
// revisa mientras el docente edita, no recién al generar el XML.
export function questionIssues(q, key) {
  const issues = [];
  const d = q.data || {};
  const ans = ((key && key.answer) || '').trim();
  if (q.type !== 'cloze' && !(d.stem || '').trim()) issues.push('Falta el enunciado');
  if (q.type === 'multichoice') {
    const opts = Object.values(d.options || {});
    const filled = opts.filter(o => (o || '').trim());
    if (filled.length < 2) issues.push('Faltan opciones (mínimo 2)');
    else if (filled.length < opts.length) issues.push('Hay una opción vacía');
    if (!ans) issues.push('Falta marcar la respuesta correcta');
  } else if (q.type === 'truefalse') {
    if (!/^(verdadero|falso)$/i.test(ans)) issues.push('Falta elegir Verdadero o Falso');
  } else if (q.type === 'matching') {
    const a = d.col_a || {}, b = d.col_b || {};
    const keys = Object.keys(a);
    const complete = keys.filter(k => (a[k] || '').trim() && (b[String.fromCharCode(96 + Number(k))] || '').trim());
    if (complete.length < keys.length) issues.push('Hay una pareja incompleta');
    if (complete.length < 2) issues.push('Faltan parejas (mínimo 2)');
  } else if (q.type === 'cloze') {
    // findClozeBrackets balancea los corchetes internos (una opción de
    // código como "arr[0]") — la regex manual que había antes se
    // detenía en el PRIMER "]" y desincronizaba este aviso en vivo del
    // resultado real que calcula el backend (ver RESULTADOS.md).
    const text = d.text || '';
    const blanks = findClozeBrackets(text);
    if (!blanks.length) issues.push('Faltan los espacios para completar');
    else if (blanks.some(({ optionsRaw }) => splitOptions(optionsRaw).length === 0)) issues.push('Un espacio no tiene opciones');
    let cursor = 0, rest = '';
    blanks.forEach(({ start, end }) => { rest += text.slice(cursor, start); cursor = end; });
    rest += text.slice(cursor);
    if (!rest.trim()) issues.push('Falta el texto de la pregunta');
  } else if (q.type === 'shortanswer') {
    if (!ans) issues.push('Falta la respuesta');
  } else if (q.type === 'numerical') {
    if (!ans) issues.push('Falta la respuesta');
    else if (isNaN(Number(ans.replace(',', '.')))) issues.push('La respuesta debe ser un número');
  }
  return issues;
}
