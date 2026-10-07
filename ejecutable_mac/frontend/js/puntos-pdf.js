/**
 * puntos-pdf.js — puntos ENTEROS para el PDF (2.7).
 *
 * El editor y el Moodle XML conservan los puntos como están (con centésimas si hace falta: Moodle suma solo). Para
 * el papel, en cambio, un decimal («6,67 pts») complica calificar y deja errores de redondeo, así que el PDF puede
 * llevar su PROPIA copia de los puntos, en enteros, con el mismo total. Nada de esto toca al editor.
 *
 * El reparto, en dos pasos:
 *   A) Valores enteros IGUALES para todas las preguntas de un mismo tipo, que sumen el total exacto (la lectura más
 *      limpia en papel: «cada una de opción múltiple vale 7»). Solo se intenta si el docente no puso valores propios
 *      distintos dentro de un tipo, y cada tipo se queda a menos de 1 punto de lo que valía.
 *   B) Si no hay tal reparto (15 preguntas de un tipo y 100 puntos), se reparte en enteros con el método del resto
 *      mayor: dentro de un tipo, dos preguntas difieren como máximo en 1 punto (las primeras valen 1 más), y se
 *      ofrecen totales cercanos que sí se reparten en iguales.
 *
 * Lógica pura (sin DOM): se prueba en Node con dev/test_frontend.mjs.
 */

const TOLERANCIA = 1e-6;
/** Dentro de un tipo, los puntos del reparto automático del editor difieren como mucho 0,01. */
const MARGEN_MISMO_TIPO = 0.0101;

const positivo = v => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : 0);

export const esEntero = n => Number.isFinite(n) && Math.abs(n - Math.round(n)) < TOLERANCIA;

/** ¿Todas las preguntas de un mismo tipo valen lo mismo? */
function igualesPorTipo(puntos, tipos) {
  const visto = new Map();
  return puntos.every((p, i) => {
    if (!visto.has(tipos[i])) { visto.set(tipos[i], p); return true; }
    return visto.get(tipos[i]) === p;
  });
}

/** Paso A: valores enteros iguales por tipo que sumen `total`, a menos de 1 punto de lo ideal; null si no hay. */
function uniformePorTipo(escalados, tipos, total, factor) {
  const grupos = new Map();
  escalados.forEach((v, i) => {
    if (!grupos.has(tipos[i])) grupos.set(tipos[i], []);
    grupos.get(tipos[i]).push(v);
  });
  const info = [];
  for (const [tipo, valores] of grupos) {
    if (Math.max(...valores) - Math.min(...valores) > MARGEN_MISMO_TIPO * Math.max(1, factor)) return null;
    const media = valores.reduce((a, b) => a + b, 0) / valores.length;
    const piso = Math.floor(media + TOLERANCIA);
    const opciones = esEntero(media) ? [Math.round(media)] : (piso >= 1 ? [piso, piso + 1] : [1]);
    info.push({ tipo, cuantas: valores.length, media, opciones });
  }
  let mejor = null;
  const elegidos = [];
  (function visitar(k, suma, error) {
    if (k === info.length) {
      if (suma === total && (mejor === null || error < mejor.error - 1e-9)) mejor = { error, valores: [...elegidos] };
      return;
    }
    for (const v of info[k].opciones) {
      elegidos[k] = v;
      visitar(k + 1, suma + v * info[k].cuantas, error + info[k].cuantas * (v - info[k].media) ** 2);
    }
  })(0, 0, 0);
  if (!mejor) return null;
  const porTipo = new Map(info.map((g, i) => [g.tipo, mejor.valores[i]]));
  return tipos.map(t => porTipo.get(t));
}

/** Paso B: método del resto mayor en enteros; a igual resto, la pregunta que va antes. */
function restoMayor(escalados, total) {
  const pisos = escalados.map(v => Math.floor(v + TOLERANCIA));
  let sobran = total - pisos.reduce((a, b) => a + b, 0);
  const orden = escalados
    .map((v, i) => ({ i, resto: Math.round((v - pisos[i]) * 1e7) / 1e7 }))
    .sort((a, b) => (b.resto - a.resto) || (a.i - b.i));
  for (let k = 0; sobran > 0 && orden.length; k = (k + 1) % orden.length, sobran--) pisos[orden[k].i] += 1;
  return pisos;
}

/**
 * Reparte `ideales` (los puntos de cada pregunta, con decimales) en ENTEROS que suman `total` (por defecto, la suma
 * de los ideales redondeada). `tipos[i]` es el tipo de la pregunta i.
 * Devuelve { puntos, total, uniforme, ceros }: `uniforme` = cada tipo vale lo mismo en todas sus preguntas, y
 * `ceros` = cuántas preguntas que valían algo quedaron en 0 (el total no alcanza para todas).
 */
export function repartirEnteros(ideales, tipos, total = null) {
  const v = ideales.map(positivo);
  if (!v.length) return { puntos: [], total: 0, uniforme: true, ceros: 0 };
  const suma = v.reduce((a, b) => a + b, 0);
  let meta = total === null || total === undefined ? Math.round(suma) : Math.round(Number(total));
  if (!Number.isFinite(meta) || meta < 0) meta = 0;
  // Sin puntos de partida (todo en 0) se reparte en partes iguales.
  const escalados = suma > 0 ? v.map(x => (x * meta) / suma) : v.map(() => meta / v.length);
  const factor = suma > 0 ? meta / suma : 1;
  const puntos = uniformePorTipo(escalados, tipos, meta, factor) || restoMayor(escalados, meta);
  const ceros = escalados.filter((x, i) => x > TOLERANCIA && puntos[i] === 0).length;
  return { puntos, total: meta, uniforme: igualesPorTipo(puntos, tipos), ceros };
}

/**
 * Totales cercanos (uno por debajo y uno por encima, si los hay) en los que todas las preguntas de un tipo valen lo
 * mismo: [{ total, puntos }] del más cercano al más lejano.
 */
export function alternativasDeTotal(ideales, tipos, total, alcance = 20) {
  const meta = Math.round(Number(total));
  const salida = [];
  for (const sentido of [-1, 1]) {
    for (let d = 1; d <= alcance; d++) {
      const t = meta + sentido * d;
      if (t < 1) break;
      const r = repartirEnteros(ideales, tipos, t);
      if (r.uniforme && r.ceros === 0) { salida.push({ total: t, puntos: r.puntos, distancia: d }); break; }
    }
  }
  return salida.sort((a, b) => a.distancia - b.distancia);
}

/**
 * Los puntos del PDF de un examen completo.
 * `opciones`: { total: el total entero que se quiere en el PDF (por defecto, el del editor), ediciones: { num: entero }
 * con lo que el docente cambió a mano }.
 * Devuelve { porNum, total, totalEditor, uniforme, ceros, diferencias, alternativas }.
 */
export function puntosParaPdf(examen, { total = null, ediciones = {} } = {}) {
  const preguntas = Array.isArray(examen && examen.questions) ? examen.questions : [];
  const ideales = preguntas.map(q => positivo(q.points));
  const tipos = preguntas.map(q => q.type);
  const suma = ideales.reduce((a, b) => a + b, 0);
  const sinPuntos = suma <= 0;
  const meta = total !== null && total !== undefined ? total : (sinPuntos ? Number(examen.total_points) : null);
  const r = repartirEnteros(ideales, tipos, meta);
  const porNum = {};
  preguntas.forEach((q, i) => {
    const propio = ediciones[q.num];
    porNum[q.num] = esEntero(propio) && propio >= 0 ? Math.round(propio) : r.puntos[i];
  });
  const finales = preguntas.map(q => porNum[q.num]);
  const totalPdf = finales.reduce((a, b) => a + b, 0);
  const diferencias = preguntas
    .map((q, i) => ({ num: q.num, moodle: ideales[i], pdf: porNum[q.num] }))
    .filter(d => Math.abs(d.moodle - d.pdf) > 0.005);
  const uniforme = igualesPorTipo(finales, tipos);
  return {
    porNum,
    total: totalPdf,
    totalEditor: Math.round(suma * 100) / 100,
    uniforme,
    ceros: preguntas.filter((q, i) => ideales[i] > TOLERANCIA && porNum[q.num] === 0).length,
    diferencias,
    alternativas: uniforme || sinPuntos ? [] : alternativasDeTotal(ideales, tipos, r.total),
  };
}

/** Una copia del examen con los puntos del PDF (el examen original no se toca). */
export function examenConPuntos(examen, resultado) {
  return {
    ...examen,
    total_points: Math.max(0.01, resultado.total),
    questions: examen.questions.map(q => ({ ...q, points: resultado.porNum[q.num] !== undefined ? resultado.porNum[q.num] : q.points })),
  };
}
