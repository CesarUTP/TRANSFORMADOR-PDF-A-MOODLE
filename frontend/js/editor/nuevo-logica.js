/**
 * nuevo-logica.js — lo que no toca el DOM al escribir un examen desde cero (3.2): sus datos de partida, las
 * preguntas en blanco y agregar o quitar opciones de selección múltiple. Se prueba en Node (pruebas.js).
 *
 * Regla de siempre: la app no inventa contenido. Una pregunta nueva de un examen desde cero llega vacía y sin
 * respuesta marcada; hasta que el docente la complete, queda señalada como incompleta y no se genera el XML.
 */

export const NOMBRE_SIN_TITULO = 'Evaluación sin título';
export const PUNTOS_INICIALES = 100;
export const MIN_OPCIONES = 2;
export const MAX_OPCIONES = 10;

/** Un nombre de examen que sirve también de nombre de archivo (sin extensión, que la pone la descarga). */
export function nombreDeExamen(texto) {
  const limpio = String(texto == null ? '' : texto)
    .replace(/[\\/:*?"<>|\u0000-\u001f]+/g, '-')
    .replace(/\s+/g, ' ').trim()
    .replace(/^\.+/, '')
    .replace(/(\.(xml|pdf|docx?|txt))+$/i, '')
    .slice(0, 120).trim();
  return limpio || NOMBRE_SIN_TITULO;
}

/** Los datos de un examen que empieza vacío. Los puntos se reparten solos hasta que el docente toque alguno. */
export function metaDesdeCero({ materia_id = null } = {}) {
  return {
    filename: NOMBRE_SIN_TITULO, nombre: '', category: 'mis-preguntas', total_points: PUNTOS_INICIALES,
    materia_id, actividad: null, desde_cero: true, reparto_auto: true,
  };
}

const EN_BLANCO = {
  multichoice: () => ({ stem: '', options: { A: '', B: '', C: '', D: '' } }),
  truefalse: () => ({ stem: '' }),
  matching: () => ({ stem: '', col_a: { 1: '', 2: '' }, col_b: { a: '', b: '' } }),
  cloze: () => ({ text: '' }),
  essay: () => ({ stem: '' }),
  shortanswer: () => ({ stem: '' }),
  numerical: () => ({ stem: '' }),
};

/** { pregunta, clave } de una pregunta nueva vacía; null si el tipo no existe. */
export function preguntaEnBlanco(type, num) {
  if (!Object.hasOwn(EN_BLANCO, type)) return null;
  return { pregunta: { num, type, data: EN_BLANCO[type]() }, clave: { type, answer: '' } };
}

const LETRAS = 'ABCDEFGHIJ';

/** Las opciones con una vacía más al final; null si ya hay el máximo. */
export function conOpcionNueva(options) {
  const letra = [...LETRAS].find(l => !Object.hasOwn(options || {}, l));
  if (!letra || Object.keys(options || {}).length >= MAX_OPCIONES) return null;
  return { ...options, [letra]: '' };
}

/**
 * Quita una opción y vuelve a poner las letras seguidas (A, B, C…), sin que las marcadas se muevan a otra.
 * Devuelve { options, marcadas } o null si no se puede (quedarían menos de dos).
 */
export function sinOpcion(options, marcadas, letra) {
  const entradas = Object.entries(options || {}).sort(([a], [b]) => a.localeCompare(b));
  if (!entradas.some(([l]) => l === letra) || entradas.length <= MIN_OPCIONES) return null;
  const nuevas = {}, quedan = [];
  entradas.filter(([l]) => l !== letra).forEach(([vieja, texto], i) => {
    nuevas[LETRAS[i]] = texto;
    if ((marcadas || []).includes(vieja)) quedan.push(LETRAS[i]);
  });
  return { options: nuevas, marcadas: quedan };
}
