/**
 * puntos.js — reparto del puntaje total entre las preguntas.
 *
 * El reparto se hace en céntimos con el método del resto mayor para que
 * la suma cuadre SIEMPRE con el total que definió el docente.
 *
 * Lógica pura: no toca el DOM ni el estado global, así se puede probar
 * sola (ver frontend/pruebas.html).
 */

import { findClozeBrackets } from './util.js';

export const fmtPoints = n => Number(n).toFixed(2).replace(/\.?0+$/, '');

// Pesos por defecto para "Distribuir puntos → Por tipo". Reflejan los
// mismos valores que TYPE_WEIGHTS en backend/config.py (el backend los
// usa como red de seguridad si una pregunta llega sin `points`; aquí
// son el punto de partida editable que ve el docente en el panel de
// distribución — si se cambian en un lado, conviene revisar el otro).
export const DEFAULT_TYPE_WEIGHTS = {
  truefalse: 1, shortanswer: 1, numerical: 1,
  multichoice: 2, matching: 3, cloze: 3, essay: 3,
};

// Recalcula y SOBREESCRIBE el campo `points` de cada pregunta en
// `questions` (mutación en el sitio). No hay cálculo oculto: esto es
// exactamente lo que corre la primera vez que se parsea un examen
// (modo 'byType', para no cambiar el comportamiento de siempre) y lo
// que corre de nuevo cuando el docente pulsa "Aplicar" en el panel de
// distribución rápida.
//   mode 'equal':  total_points repartido en partes iguales entre
//                  TODAS las preguntas, sin importar el tipo.
//   mode 'byType': misma fórmula que compute_grades() en el backend
//                  (unit = total / Σ peso_i·cantidad_i), pero resuelta
//                  aquí para poder mostrarla y dejarla editar en vivo.
// OJO con `w[t] || 1`: en JS, 0 es "falsy", así que ese patrón convertía
// silenciosamente cualquier peso puesto en 0 a 1 — un docente que
// quisiera "que este tipo no reciba nada" no podía lograrlo, y si
// ponía TODOS los pesos en 0 el resultado terminaba siendo un reparto
// equitativo sin ningún aviso de que 0 no se había respetado. Este
// helper solo cae al default (1) cuando el peso no es un número válido
// (campo vacío o NaN) — 0 se respeta tal cual.
function _weightOrDefault(w, type) {
  const v = w[type];
  return (typeof v === 'number' && Number.isFinite(v) && v >= 0) ? v : 1;
}

// ── «Según el tipo»: el docente escribe cuántos puntos vale UNA pregunta de cada tipo ──────────────────
// Ejemplo: 10 de opción múltiple a 2 puntos y 5 de completar a 5 puntos: el examen vale 20 + 25 = 45. El total
// del examen es la SUMA (no un dato que haya que cuadrar). Reemplaza al reparto por «pesos relativos», que
// obligaba a repartir un total fijo y daba valores como 3.57 por pregunta.

/** ¿Un valor escrito sirve como puntaje de un tipo? (número finito y no negativo) */
export function puntajeValido(v) {
  return typeof v === 'number' && Number.isFinite(v) && v >= 0;
}

/**
 * Puntos de cada pregunta cuando se fija lo que vale cada tipo.
 *   items:   [{ type, huecos, actual }]  (`huecos`: espacios de un «Completar»; `actual`: puntos que tiene hoy)
 *   porTipo: { tipo: número | null }     (un tipo sin valor válido no se toca: cada pregunta conserva `actual`)
 * «Completar» vale puntos ENTEROS, al menos uno por espacio (así lo calcula Moodle). Lo demás se redondea a centésimas.
 */
export function puntosPorTipo(items, porTipo) {
  return items.map(it => {
    const v = porTipo ? porTipo[it.type] : null;
    if (!puntajeValido(v)) return Number(it.actual) || 0;
    if (it.type === 'cloze' && v > 0) return Math.max(Math.max(1, it.huecos || 0), Math.round(v));
    return Math.round(v * 100) / 100;
  });
}

/** La suma de los puntos, en centésimas exactas. */
export function sumaDePuntos(puntos) {
  return Math.round(puntos.reduce((a, b) => a + (Number(b) || 0), 0) * 100) / 100;
}

/** Aplica «puntos por tipo» a las preguntas del editor (mutación en el sitio). Devuelve el total del examen. */
export function aplicarPuntosPorTipo(questions, porTipo) {
  const items = questions.map(q => ({
    type: q.type,
    huecos: q.type === 'cloze' && q.data && typeof q.data.text === 'string' ? Math.max(1, findClozeBrackets(q.data.text).length) : 0,
    actual: q.points,
  }));
  const puntos = puntosPorTipo(items, porTipo);
  questions.forEach((q, i) => { q.points = puntos[i]; });
  return sumaDePuntos(puntos);
}

/**
 * Lo que vale hoy cada pregunta de un tipo, para precargar el campo: el valor común o, si las preguntas valen
 * distinto (o no hay), null. Con null el campo queda vacío («varía») y ese tipo no se toca hasta que el docente
 * escriba algo: precargar un promedio cambiaría puntos sin que nadie lo pidiera.
 */
export function puntajeComunDe(puntos) {
  const v = puntos.map(Number).filter(Number.isFinite);
  if (!v.length) return null;
  const min = Math.min(...v), max = Math.max(...v);
  return max - min <= 0.0101 ? Math.round(v[0] * 100) / 100 : null;
}

/** Huecos de un «Completar» (mínimo 1) y lo que Moodle le dará: puntos ENTEROS, al menos uno por hueco. */
export function puntosEnMoodle(texto, puntos) {
  const huecos = Math.max(1, findClozeBrackets(texto).length);
  const dados = Number(puntos);
  return { huecos, enMoodle: dados > 0 ? Math.max(huecos, Math.round(dados)) : huecos };
}

// Reparte `totalCents` entre las posiciones según `shares`, en céntimos y con el
// método del resto mayor: la suma da SIEMPRE `totalCents`. Entre preguntas
// empatadas, los céntimos sobrantes se dan por turnos entre los tipos (1ª de
// cada tipo, 2ª de cada tipo…) en vez de vaciarlos sobre el primer tipo: si no,
// dos tipos con el MISMO peso podían mostrar valores distintos (1.93 vs 1.92
// pts c/u), que se lee como un error aunque la suma cuadre.
function repartirCentimos(shares, tipos, totalCents) {
  const totalShare = shares.reduce((a, b) => a + b, 0);
  const exact = shares.map(s => (totalShare > 0 ? (s / totalShare) * totalCents : 0));
  const cents = exact.map(v => Math.floor(v));
  const leftover = totalCents - cents.reduce((a, b) => a + b, 0);
  const seenPerType = {};
  const byRemainder = exact
    .map((v, i) => {
      const t = tipos[i];
      const turn = seenPerType[t] = (seenPerType[t] === undefined ? 0 : seenPerType[t] + 1);
      return { i, turn, frac: v - Math.floor(v) };
    })
    .sort((a, b) => (b.frac - a.frac) || (a.turn - b.turn) || (a.i - b.i));
  for (let k = 0; k < leftover && k < byRemainder.length; k++) cents[byRemainder[k].i] += 1;
  return cents;
}

// Moodle IGNORA los puntos de una pregunta de «Completar»: le da la suma de los
// pesos ENTEROS de sus huecos, con mínimo 1 por hueco. Para que el editor y
// Moodle digan lo mismo, «Completar» vale aquí siempre puntos enteros (al menos
// uno por hueco) y la diferencia con el reparto exacto la absorben las demás
// preguntas, así el total sigue siendo el del docente. (Antes el XML multiplicaba
// TODOS los puntos por un factor: un examen de 100 puntos llegaba a Moodle con 700.)
// Modifica `cents` en el sitio. Si no hay forma de cuadrarlo (los mínimos no caben
// en el total, o el total no es entero y todas son «Completar») lo deja como está.
// Solo actúa sobre preguntas con su texto a la vista (sin él no se sabe cuántos huecos tiene).
function completarEnteros(questions, shares, cents, totalCents) {
  const huecos = questions.map(q => {
    const texto = q && q.type === 'cloze' && q.data ? q.data.text : null;
    return typeof texto === 'string' ? Math.max(1, findClozeBrackets(texto).length) : 0;
  });
  const clozes = [], otras = [];
  questions.forEach((q, i) => {
    if (huecos[i] > 0 && shares[i] > 0) clozes.push(i);
    else if (shares[i] > 0) otras.push(i);
  });
  if (!clozes.length) return;

  if (!otras.length) {
    // Todo es «Completar»: se reparten puntos enteros (si el total lo es).
    if (totalCents % 100 !== 0) return;
    const total = totalCents / 100;
    const minimos = clozes.reduce((a, i) => a + huecos[i], 0);
    if (minimos > total) return;
    const suma = clozes.reduce((a, i) => a + shares[i], 0);
    const exacto = clozes.map(i => (shares[i] / suma) * total);
    const enteros = clozes.map((i, k) => Math.max(huecos[i], Math.floor(exacto[k])));
    let resto = total - enteros.reduce((a, b) => a + b, 0);
    const orden = clozes.map((i, k) => ({ k, frac: exacto[k] - Math.floor(exacto[k]) })).sort((a, b) => (b.frac - a.frac) || (a.k - b.k));
    if (resto < 0) return;   // los mínimos ya se pasaron del total
    for (let n = 0; resto > 0; n++, resto--) enteros[orden[n % orden.length].k] += 1;
    clozes.forEach((i, k) => { cents[i] = enteros[k] * 100; });
    return;
  }

  const nuevos = clozes.map(i => Math.max(huecos[i], Math.round(cents[i] / 100)) * 100);
  const resto = totalCents - nuevos.reduce((a, b) => a + b, 0);
  if (resto < 0) return;     // los enteros no caben en el total: se deja el reparto exacto
  const parte = repartirCentimos(otras.map(i => shares[i]), otras.map(i => questions[i].type), resto);
  clozes.forEach((i, k) => { cents[i] = nuevos[k]; });
  otras.forEach((i, k) => { cents[i] = parte[k]; });
}

export function autoDistributePoints(questions, totalPoints, mode, weights) {
  if (!questions || !questions.length) return;
  const total = Number(totalPoints);
  if (!Number.isFinite(total) || total <= 0) return;

  // Peso de cada pregunta: 1 para todas en modo equitativo, o el peso
  // de su tipo en modo "Por tipo".
  const w = weights || DEFAULT_TYPE_WEIGHTS;
  let shares = questions.map(q => (mode === 'equal' ? 1 : _weightOrDefault(w, q.type)));
  let totalWeight = shares.reduce((a, b) => a + b, 0);
  if (totalWeight <= 0) {
    // Caso degenerado: todos los pesos en 0 (o negativos) no tiene una
    // solución matemática (dividiría entre cero) — se cae a reparto
    // equitativo en vez de fallar en silencio.
    shares = questions.map(() => 1);
    totalWeight = questions.length;
  }

  // El reparto se hace en CÉNTIMOS con el método del resto mayor, no
  // redondeando cada pregunta por separado. Redondear una por una hacía
  // que la suma se fuera del total que el docente había fijado (7
  // preguntas de 1.74 + 3 de 2.61 daba 20.01 / 20 pts, y el contador de
  // arriba lo mostraba), justo lo contrario de lo que promete el panel.
  // Ahora se reparte el total exacto y los céntimos sobrantes se dan de
  // a uno a las preguntas con mayor resto, así que la suma SIEMPRE
  // cuadra; dentro de un mismo tipo dos preguntas pueden diferir como
  // mucho en 0.01 pts.
  const tipos = questions.map(q => q.type);
  const totalCents = Math.round(total * 100);
  const cents = repartirCentimos(shares, tipos, totalCents);
  completarEnteros(questions, shares, cents, totalCents);
  questions.forEach((q, i) => { q.points = cents[i] / 100; });
}
