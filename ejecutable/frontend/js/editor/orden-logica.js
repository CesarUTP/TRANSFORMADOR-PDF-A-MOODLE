/**
 * orden-logica.js — mover y duplicar preguntas en el editor. Lógica pura (sin DOM): se prueba en Node.
 *
 * Un grupo con enunciado compartido no se parte al mover: una pregunta del grupo se mueve DENTRO de él, una
 * pregunta suelta salta el grupo vecino entero, y el grupo se mueve completo desde su bloque. Qué preguntas
 * comparten un enunciado solo cambia con «De la pregunta … a la …».
 */
import { tramoEn } from './compartido-logica.js';

/** La «unidad» que ocupa la posición `pos`: el grupo entero, o la pregunta sola. */
function unidadEn(questions, pos) {
  const t = tramoEn(questions, pos);
  return t ? { desde: t.desde, hasta: t.hasta } : { desde: pos, hasta: pos };
}

/** Qué puede hacer la pregunta en `pos`: { subir, bajar, enGrupo }. */
export function movimientosDe(questions, pos) {
  const t = tramoEn(questions, pos);
  if (t) return { subir: pos > t.desde, bajar: pos < t.hasta, enGrupo: true };
  return { subir: pos > 0, bajar: pos < questions.length - 1, enGrupo: false };
}

// Intercambia dos tramos seguidos de la lista (posiciones, ambas incluidas).
function intercambiar(lista, a, b) {
  return [...lista.slice(0, a.desde), ...lista.slice(b.desde, b.hasta + 1), ...lista.slice(a.desde, a.hasta + 1), ...lista.slice(b.hasta + 1)];
}

/** Mueve la pregunta en `pos` una vez (`dir`: -1 arriba, 1 abajo). { orden, nueva } o null si no puede. */
export function moverPregunta(questions, pos, dir) {
  const puede = movimientosDe(questions, pos);
  if (!questions[pos] || !(dir < 0 ? puede.subir : puede.bajar)) return null;
  if (puede.enGrupo) {
    const orden = [...questions];
    [orden[pos], orden[pos + dir]] = [orden[pos + dir], orden[pos]];
    return { orden, nueva: pos + dir };
  }
  const propia = { desde: pos, hasta: pos };
  const vecina = unidadEn(questions, pos + dir);
  const orden = dir < 0 ? intercambiar(questions, vecina, propia) : intercambiar(questions, propia, vecina);
  return { orden, nueva: orden.indexOf(questions[pos]) };
}

/** Mueve entero el grupo que empieza en `desde`. { orden, nueva (su primera posición) } o null si no puede. */
export function moverGrupo(questions, desde, dir) {
  const grupo = tramoEn(questions, desde);
  if (!grupo) return null;
  const al_lado = dir < 0 ? grupo.desde - 1 : grupo.hasta + 1;
  if (al_lado < 0 || al_lado >= questions.length) return null;
  const vecina = unidadEn(questions, al_lado);
  const orden = dir < 0 ? intercambiar(questions, vecina, grupo) : intercambiar(questions, grupo, vecina);
  return { orden, nueva: orden.indexOf(questions[grupo.desde]) };
}

/**
 * Pone las preguntas de `res` en el orden `orden` (los mismos objetos, quizá con alguno nuevo): renumera,
 * lleva cada clave con su pregunta y mantiene cada «no incluida» detrás de la pregunta a la que seguía.
 * `clavesNuevas`: Map pregunta → clave para las que no estaban.
 */
export function reordenar(res, orden, clavesNuevas = new Map()) {
  const claves = new Map(res.questions.map(q => [q, res.answer_key[q.num]]));
  const omitidas = res.skipped_questions || [];
  const anclas = omitidas.map(s => (Number.isInteger(s.despues_de) && s.despues_de > 0 ? res.questions[s.despues_de - 1] : null));
  const answer_key = {};
  orden.forEach((q, i) => {
    const clave = claves.get(q) || clavesNuevas.get(q);
    q.num = i + 1;
    if (clave) answer_key[i + 1] = clave;
  });
  res.questions = orden;
  res.answer_key = answer_key;
  anclas.forEach((q, k) => { if (q) omitidas[k].despues_de = orden.indexOf(q) + 1; });
  return res;
}

/** Inserta una copia de la pregunta `pos` justo después (con su clave, sus puntos y su enunciado compartido). */
export function duplicarPregunta(res, pos) {
  const original = res.questions[pos];
  if (!original) return null;
  const copia = JSON.parse(JSON.stringify(original));
  const clave = res.answer_key[original.num];
  const orden = [...res.questions];
  orden.splice(pos + 1, 0, copia);
  reordenar(res, orden, new Map(clave ? [[copia, JSON.parse(JSON.stringify(clave))]] : []));
  return pos + 1;
}
