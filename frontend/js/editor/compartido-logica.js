/**
 * compartido-logica.js — enunciado compartido por varias preguntas («Del siguiente caso responda las
 * preguntas 1 a 5»). Lógica pura (sin DOM): se prueba en Node (pruebas.js).
 *
 * Cada pregunta del grupo lleva el MISMO texto en `data.contexto`, y las preguntas SEGUIDAS con el mismo
 * texto forman un grupo. En el editor un texto vacío ('') es un grupo que aún no se ha escrito; el servidor
 * lo ignora. Los números de las preguntas no se escriben: los pone quien imprime.
 *
 * Las imágenes del enunciado van en cada pregunta del grupo, marcadas con `compartida` y delante de las propias:
 * así viajan solas al XML (Moodle necesita su copia en cada pregunta) y el papel las saca una vez, con el
 * enunciado. Dos preguntas seguidas son del mismo grupo si coinciden el texto y esas imágenes.
 *
 * Un enunciado recién creado todavía no tiene preguntas: vive aparte, en `res.compartido_pendiente`
 * ({ texto, images }), hasta que se le agrega la primera o se pone en una que ya existe. Hay como mucho uno.
 */

/** El enunciado compartido de una pregunta, o null si no tiene (ni siquiera vacío). */
export function contextoDe(q) {
  const c = q && q.data ? q.data.contexto : undefined;
  return typeof c === 'string' ? c : null;
}

const _imagenes = q => (q && q.data && Array.isArray(q.data.images) ? q.data.images : []);
/** Las imágenes del enunciado compartido que lleva una pregunta. */
export const imagenesDelEnunciado = q => _imagenes(q).filter(im => im && im.compartida);
/** Las que son solo de la pregunta. */
export const imagenesPropias = q => _imagenes(q).filter(im => im && !im.compartida);

/** Deja en la pregunta estas imágenes del enunciado (delante) y las suyas propias, sin repetir ninguna. */
export function ponerImagenes(q, delEnunciado) {
  const propias = imagenesPropias(q).filter(p => !delEnunciado.some(c => c.b64 === p.b64));
  const lista = [...delEnunciado.map(im => ({ ...im, compartida: true })), ...propias];
  if (lista.length) q.data.images = lista;
  else delete q.data.images;
}

/** Cuántas imágenes tendría la pregunta con estas del enunciado además de las suyas. */
export function imagenesQueTendria(q, delEnunciado) {
  return delEnunciado.length + imagenesPropias(q).filter(p => !delEnunciado.some(c => c.b64 === p.b64)).length;
}

function _mismoGrupo(a, b) {
  const x = imagenesDelEnunciado(a), y = imagenesDelEnunciado(b);
  return contextoDe(a) !== null && contextoDe(a) === contextoDe(b) && x.length === y.length && x.every((im, i) => im.b64 === y[i].b64);
}

/** [{ desde, hasta, texto }] (posiciones, ambas incluidas) de cada grupo de la lista. */
export function tramosCompartidos(questions) {
  const tramos = [];
  (questions || []).forEach((q, i) => {
    const texto = contextoDe(q);
    if (texto === null) return;
    const ultimo = tramos[tramos.length - 1];
    if (ultimo && ultimo.hasta === i - 1 && _mismoGrupo(questions[i - 1], q)) ultimo.hasta = i;
    else tramos.push({ desde: i, hasta: i, texto });
  });
  return tramos;
}

/**
 * Al abrir una evaluación: la imagen que llevan TODAS las preguntas de un grupo de dos o más es del enunciado
 * (así la deja la lectura de un documento, y así sale ya en el papel): se marca para mostrarla una sola vez.
 */
export function marcarImagenesComunes(questions) {
  tramosCompartidos(questions).forEach(t => {
    const grupo = questions.slice(t.desde, t.hasta + 1);
    if (grupo.length < 2 || grupo.some(q => imagenesDelEnunciado(q).length)) return;
    const comunes = _imagenes(grupo[0]).filter(im => grupo.every(q => _imagenes(q).some(o => o.b64 === im.b64)));
    if (comunes.length) grupo.forEach(q => ponerImagenes(q, comunes));
  });
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
  const delEnunciado = imagenesDelEnunciado(questions[tramo.desde]);
  for (let i = tramo.desde; i <= tramo.hasta; i++) { delete questions[i].data.contexto; ponerImagenes(questions[i], []); }
  for (let i = a; i <= b; i++) { questions[i].data.contexto = tramo.texto; ponerImagenes(questions[i], delEnunciado); }
  return { desde: a, hasta: b, texto: tramo.texto };
}

/**
 * Empieza un enunciado compartido sin preguntas. Devuelve el que haya que rellenar: 'pendiente' (el nuevo, o
 * el que ya estaba sin preguntas) o el grupo del final si todavía está en blanco (si no, se juntarían).
 */
export function empezarCompartido(res) {
  if (res.compartido_pendiente) return 'pendiente';
  const ultimo = tramoEn(res.questions, res.questions.length - 1);
  if (ultimo && !ultimo.texto.trim() && !imagenesDelEnunciado(res.questions[ultimo.desde]).length) return ultimo;
  res.compartido_pendiente = { texto: '' };
  return 'pendiente';
}

/** Dónde va una pregunta nueva de un enunciado: tras la última de su grupo; si aún no tiene, al final. */
export function posicionEnCompartido(questions, tramo) {
  return tramo ? tramo.hasta + 1 : questions.length;
}

/** Las posiciones de las preguntas que no están en ningún grupo. */
export function posicionesLibres(questions) {
  return (questions || []).map((_, i) => i).filter(i => contextoDe(questions[i]) === null);
}

/** Pone el enunciado sin preguntas en una que ya existe y está libre. Devuelve su grupo, o null si no se puede. */
export function usarEnPregunta(res, pos) {
  const q = res.questions[pos];
  if (!res.compartido_pendiente || !q || contextoDe(q) !== null) return null;
  q.data.contexto = res.compartido_pendiente.texto;
  ponerImagenes(q, res.compartido_pendiente.images || []);
  delete res.compartido_pendiente;
  return tramoEn(res.questions, pos);
}

/** Quita el grupo: sus preguntas se quedan sin enunciado compartido; sus imágenes pasan a ser propias de cada una. */
export function quitarTramo(questions, tramo) {
  for (let i = tramo.desde; i <= tramo.hasta; i++) {
    delete questions[i].data.contexto;
    _imagenes(questions[i]).forEach(im => { delete im.compartida; });
  }
}

/** Una pregunta insertada EN MEDIO de un grupo pasa a ser parte de él (si no, lo partiría en dos). */
export function heredarContexto(questions, pos) {
  const q = questions[pos];
  const antes = questions[pos - 1];
  if (!q || contextoDe(q) !== null || !antes || !_mismoGrupo(antes, questions[pos + 1])) return false;
  q.data.contexto = contextoDe(antes);
  ponerImagenes(q, imagenesDelEnunciado(antes));
  return true;
}
