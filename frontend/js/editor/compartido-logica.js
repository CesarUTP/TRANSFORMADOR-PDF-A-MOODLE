/**
 * compartido-logica.js — enunciado compartido por varias preguntas («Del siguiente caso responda las
 * preguntas 1 a 5»). Lógica pura (sin DOM): se prueba en Node (pruebas.js).
 *
 * Cada pregunta del grupo lleva el MISMO texto en `data.contexto`, y las preguntas SEGUIDAS con el mismo
 * texto forman un grupo. En el editor un texto vacío ('') es un grupo recién creado que aún no se ha
 * escrito; el servidor lo ignora. Los números de las preguntas no se escriben: los pone quien imprime.
 */

/** El enunciado compartido de una pregunta, o null si no tiene (ni siquiera vacío). */
export function contextoDe(q) {
  const c = q && q.data ? q.data.contexto : undefined;
  return typeof c === 'string' ? c : null;
}

/** [{ desde, hasta, texto }] (posiciones, ambas incluidas) de cada grupo de la lista. */
export function tramosCompartidos(questions) {
  const tramos = [];
  (questions || []).forEach((q, i) => {
    const texto = contextoDe(q);
    if (texto === null) return;
    const ultimo = tramos[tramos.length - 1];
    if (ultimo && ultimo.hasta === i - 1 && ultimo.texto === texto) ultimo.hasta = i;
    else tramos.push({ desde: i, hasta: i, texto });
  });
  return tramos;
}

/** El grupo al que pertenece la posición `pos`, o null. */
export function tramoEn(questions, pos) {
  return tramosCompartidos(questions).find(t => pos >= t.desde && pos <= t.hasta) || null;
}

/** «Preguntas 1 a 5», «Preguntas 1 y 2», «Pregunta 3» (posiciones desde 0). */
export function rotuloDeTramo({ desde, hasta }) {
  if (desde === hasta) return `Pregunta ${desde + 1}`;
  return `Preguntas ${desde + 1} ${hasta === desde + 1 ? 'y' : 'a'} ${hasta + 1}`;
}

/** Hasta dónde puede crecer un grupo sin meterse en otro: { minimo, maximo } (posiciones). */
export function limitesDeTramo(questions, tramo) {
  const tramos = tramosCompartidos(questions);
  const k = tramos.findIndex(t => t.desde === tramo.desde);
  return {
    minimo: k > 0 ? tramos[k - 1].hasta + 1 : 0,
    maximo: k >= 0 && k < tramos.length - 1 ? tramos[k + 1].desde - 1 : questions.length - 1,
  };
}

/** Mueve los bordes de un grupo (cambia las preguntas en el sitio). Devuelve el grupo nuevo. */
export function cambiarRango(questions, tramo, desde, hasta) {
  const { minimo, maximo } = limitesDeTramo(questions, tramo);
  const a = Math.min(Math.max(desde, minimo), maximo);
  const b = Math.min(Math.max(hasta, a), maximo);
  for (let i = tramo.desde; i <= tramo.hasta; i++) delete questions[i].data.contexto;
  for (let i = a; i <= b; i++) questions[i].data.contexto = tramo.texto;
  return { desde: a, hasta: b, texto: tramo.texto };
}

/** Un grupo nuevo, vacío, que empieza en `pos` y abarca también la siguiente si está libre. */
export function crearTramo(questions, pos) {
  if (!questions[pos] || contextoDe(questions[pos]) !== null) return null;
  questions[pos].data.contexto = '';
  const sig = questions[pos + 1];
  // Si la siguiente ya está en otro grupo, o en uno vacío, se deja como está.
  if (sig && contextoDe(sig) === null) sig.data.contexto = '';
  return tramoEn(questions, pos);
}

/** Quita el grupo: sus preguntas se quedan sin enunciado compartido. */
export function quitarTramo(questions, tramo) {
  for (let i = tramo.desde; i <= tramo.hasta; i++) delete questions[i].data.contexto;
}

/** Una pregunta insertada EN MEDIO de un grupo pasa a ser parte de él (si no, lo partiría en dos). */
export function heredarContexto(questions, pos) {
  const q = questions[pos];
  const antes = contextoDe(questions[pos - 1]);
  if (!q || contextoDe(q) !== null || antes === null || antes !== contextoDe(questions[pos + 1])) return false;
  q.data.contexto = antes;
  return true;
}
