/**
 * puntos.js — reparto del puntaje total entre las preguntas.
 *
 * El reparto se hace en céntimos con el método del resto mayor para que
 * la suma cuadre SIEMPRE con el total que definió el docente.
 *
 * Lógica pura: no toca el DOM ni el estado global, así se puede probar
 * sola (ver frontend/pruebas.html).
 */

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
  const totalCents = Math.round(total * 100);
  const exact = shares.map(s => (s / totalWeight) * totalCents);
  const cents = exact.map(v => Math.floor(v));
  const leftover = totalCents - cents.reduce((a, b) => a + b, 0);
  // Entre preguntas empatadas, los céntimos sobrantes se reparten por
  // turnos entre los tipos (1ª de cada tipo, 2ª de cada tipo…) en vez de
  // vaciarlos sobre el primer tipo de la lista. Si no, dos tipos con el
  // MISMO peso podían terminar mostrando valores distintos (1.93 vs
  // 1.92 pts c/u), que se lee como un error aunque la suma cuadre.
  const seenPerType = {};
  const byRemainder = exact
    .map((v, i) => {
      const t = questions[i].type;
      const turn = seenPerType[t] = (seenPerType[t] === undefined ? 0 : seenPerType[t] + 1);
      return { i, turn, frac: v - Math.floor(v) };
    })
    .sort((a, b) => (b.frac - a.frac) || (a.turn - b.turn) || (a.i - b.i));
  for (let k = 0; k < leftover && k < byRemainder.length; k++) cents[byRemainder[k].i] += 1;

  questions.forEach((q, i) => { q.points = cents[i] / 100; });
}
