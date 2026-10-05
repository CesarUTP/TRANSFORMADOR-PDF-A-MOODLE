/**
 * sugerencias-logica.js — la parte de «Sugerir respuesta con IA» que no toca el DOM
 * (se prueba en Node). La interfaz vive en sugerencias.js.
 */

export function describirSugerencia(tipo, sug, pregunta) {
  const d = (pregunta && pregunta.data) || {};
  if (tipo === 'multichoice') {
    return sug.letras.map(L => `${L}. ${(d.options || {})[L] ?? ''}`).join('  ·  ');
  }
  if (tipo === 'matching') {
    return Object.entries(sug.pares).map(([n, L]) => `${(d.col_a || {})[n] ?? n} → ${(d.col_b || {})[L] ?? L}`).join('\n');
  }
  if (tipo === 'cloze') {
    return Object.entries(sug.huecos).map(([letra, idx]) => `Espacio ${letra}: opción ${idx + 1}`).join('  ·  ');
  }
  return String(sug.respuesta ?? '');
}

