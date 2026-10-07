/**
 * versiones-logica.js — varias versiones impresas de un mismo examen, sin tocar el DOM (se prueba en Node).
 *
 * El examen grande (por ejemplo 100 preguntas) sirve de banco: cada versión lleva algunas de sus preguntas,
 * sorteadas al azar, de forma totalmente aleatoria o con una cuota por tipo. La pantalla vive en
 * exportar-pdf.js y el armado de cada PDF en backend/versiones.py.
 *
 * Una versión es { etiqueta, nums, semilla, puntos }:
 *   - `nums`: los números de pregunta que lleva, en el orden del examen original;
 *   - `semilla`: de ahí sale el orden en que se imprimen (el mismo para la vista previa y para el PDF);
 *   - `puntos`: los puntos que el docente cambió ({ num: puntos }); lo que falta conserva el del examen.
 * La clave nunca se copia: se toma del examen completo, así que cada pregunta lleva SU respuesta.
 */
import { autoDistributePoints } from './puntos.js';

export const MAX_VERSIONES = 12;
export const MODOS = ['aleatorio', 'por_tipo'];

/** Cómo se llama cada tipo (el mismo nombre que en el editor). */
export const NOMBRES_TIPO = {
  multichoice: 'Opción múltiple', truefalse: 'Verdadero/Falso', matching: 'Emparejamiento', cloze: 'Completar',
  essay: 'Ensayo', shortanswer: 'Respuesta corta', numerical: 'Numérica',
};

const nombreDeTipo = t => NOMBRES_TIPO[t] || t;
const redondear = n => Math.round(n * 100) / 100;

// ── Azar con semilla (la misma semilla da siempre el mismo sorteo) ─────────
export function crearAzar(semilla) {
  let a = (Number(semilla) >>> 0) || 1;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Una semilla nueva (la hora y un poco de azar: no hace falta que sea impredecible). */
export function semillaNueva() {
  return (Math.floor(Math.random() * 0x7fffffff) ^ (Date.now() & 0x7fffffff)) >>> 0 || 1;
}

function barajar(lista, azar) {
  const a = [...lista];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(azar() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

// ── Lo que hay en el examen ────────────────────────────────────────────────
/** [{ tipo, nombre, cantidad, nums }] en el orden en que cada tipo aparece por primera vez. */
export function resumenPorTipo(questions) {
  const grupos = new Map();
  for (const q of questions) {
    if (!grupos.has(q.type)) grupos.set(q.type, { tipo: q.type, nombre: nombreDeTipo(q.type), cantidad: 0, nums: [] });
    const g = grupos.get(q.type);
    g.cantidad += 1;
    g.nums.push(q.num);
  }
  return [...grupos.values()];
}

/** «A», «B»… «Z», «AA»… */
export function etiquetaDe(i) {
  let n = i, s = '';
  do { s = String.fromCharCode(65 + (n % 26)) + s; n = Math.floor(n / 26) - 1; } while (n >= 0);
  return s;
}

/** Las cuotas por tipo que dan `total` preguntas en proporción a lo que hay de cada tipo. */
export function cuotasProporcionales(tipos, total) {
  const hay = tipos.reduce((a, t) => a + t.cantidad, 0);
  const cuotas = {};
  if (!hay) return cuotas;
  const exactas = tipos.map(t => (t.cantidad / hay) * total);
  const enteras = exactas.map(Math.floor);
  let sobran = Math.min(total, hay) - enteras.reduce((a, b) => a + b, 0);
  tipos.map((t, i) => ({ i, resto: exactas[i] - enteras[i] })).sort((a, b) => b.resto - a.resto || a.i - b.i)
    .forEach(({ i }) => { if (sobran > 0 && enteras[i] < tipos[i].cantidad) { enteras[i] += 1; sobran -= 1; } });
  tipos.forEach((t, i) => { cuotas[t.tipo] = Math.min(t.cantidad, enteras[i]); });
  return cuotas;
}

/** El plan con que se abre el sorteo: dos versiones con la mitad de las preguntas, sin repetir. */
export function planInicial(questions) {
  const total = questions.length;
  const mitad = Math.max(1, Math.round(total / 2));
  return {
    versiones: 2, modo: 'aleatorio', total: mitad,
    cuotas: cuotasProporcionales(resumenPorTipo(questions), mitad),
    sinRepetir: true,
  };
}

function enteroValido(v, min, max) {
  const n = typeof v === 'string' ? Number(v.trim()) : v;
  return typeof n === 'number' && Number.isInteger(n) && n >= min && n <= max ? n : null;
}

/** Cuántas preguntas lleva cada versión según el plan (null si el plan no sirve). */
export function preguntasPorVersion(plan, tipos) {
  if (plan.modo === 'por_tipo') return tipos.reduce((a, t) => a + (enteroValido(plan.cuotas[t.tipo], 0, t.cantidad) ?? 0), 0);
  return enteroValido(plan.total, 1, tipos.reduce((a, t) => a + t.cantidad, 0)) ?? 0;
}

/**
 * Revisa el plan. { errores: [texto], avisos: [texto], porVersion, repiten }:
 * `errores` impiden sortear; `avisos` no (por ejemplo, «no alcanzan para no repetir»).
 * `repiten` es cuántas preguntas se usarán en más de una versión como mínimo.
 */
export function revisarPlan(plan, questions) {
  const tipos = resumenPorTipo(questions);
  const errores = [], avisos = [];
  const hay = questions.length;
  const n = enteroValido(plan.versiones, 1, MAX_VERSIONES);
  if (n === null) errores.push(`Las versiones deben ser un número entre 1 y ${MAX_VERSIONES}.`);
  let porVersion = 0, repiten = 0;
  const grupos = [];
  if (plan.modo === 'por_tipo') {
    for (const t of tipos) {
      const q = enteroValido(plan.cuotas[t.tipo], 0, t.cantidad);
      if (q === null) { errores.push(`De «${t.nombre}» hay ${t.cantidad}: pide un número entre 0 y ${t.cantidad}.`); continue; }
      porVersion += q;
      grupos.push({ nombre: t.nombre, hay: t.cantidad, q });
    }
    if (!errores.length && porVersion < 1) errores.push('Pide al menos una pregunta de algún tipo.');
  } else {
    const q = enteroValido(plan.total, 1, hay);
    if (q === null) errores.push(`Las preguntas por versión deben ser un número entre 1 y ${hay}.`);
    else { porVersion = q; grupos.push({ nombre: '', hay, q }); }
  }
  if (!errores.length && n !== null) {
    for (const g of grupos) {
      const necesarias = n * g.q;
      if (necesarias > g.hay) {
        repiten += necesarias - g.hay;
        if (plan.sinRepetir) {
          avisos.push(g.nombre
            ? `De «${g.nombre}» hay ${g.hay} y ${n} versiones de ${g.q} necesitan ${necesarias}: algunas se repetirán entre versiones.`
            : `Hay ${g.hay} preguntas y ${n} versiones de ${g.q} necesitan ${necesarias}: algunas se repetirán entre versiones.`);
        }
      }
    }
  }
  return { errores, avisos, porVersion, repiten };
}

/** Reparte `quedan` elementos entre `n` versiones, `q` a cada una; sin repetir mientras alcance. */
function repartir(nums, q, n, sinRepetir, azar) {
  const salida = Array.from({ length: n }, () => []);
  if (q <= 0) return salida;
  if (!sinRepetir) {
    for (let v = 0; v < n; v++) salida[v] = barajar(nums, azar).slice(0, q);
    return salida;
  }
  // Una «ronda» es una baraja de todo el grupo: cada versión toma de la ronda lo que no tenga ya; cuando se
  // acaba, empieza otra. Así nada se repite hasta que ya se usó todo lo que había.
  let ronda = barajar(nums, azar);
  for (let v = 0; v < n; v++) {
    const elegidas = new Set();
    while (elegidas.size < q) {
      if (!ronda.length) ronda = barajar(nums.filter(x => !elegidas.has(x)), azar);
      const x = ronda.pop();
      if (!elegidas.has(x)) elegidas.add(x);
    }
    salida[v] = [...elegidas];
  }
  return salida;
}

/**
 * El sorteo: [{ etiqueta, nums, semilla, puntos }]. Con la misma semilla da lo mismo.
 * Lanza Error si el plan no sirve (revisarPlan dice por qué antes).
 */
export function sortear(questions, plan, semilla) {
  const rev = revisarPlan(plan, questions);
  if (rev.errores.length) throw new Error(rev.errores[0]);
  const azar = crearAzar(semilla);
  const n = Number(plan.versiones);
  const orden = new Map(questions.map((q, i) => [q.num, i]));
  const grupos = plan.modo === 'por_tipo'
    ? resumenPorTipo(questions).map(t => ({ nums: t.nums, q: Number(plan.cuotas[t.tipo]) }))
    : [{ nums: questions.map(q => q.num), q: Number(plan.total) }];
  const elegidas = Array.from({ length: n }, () => []);
  for (const g of grupos) {
    repartir(g.nums, g.q, n, plan.sinRepetir, azar).forEach((lista, v) => elegidas[v].push(...lista));
  }
  return elegidas.map((nums, v) => ({
    etiqueta: etiquetaDe(v),
    nums: nums.sort((a, b) => orden.get(a) - orden.get(b)),
    semilla: Math.floor(azar() * 0x7fffffff) + 1,
    puntos: {},
  }));
}

/** Cuántas preguntas figuran en más de una versión. */
export function preguntasRepetidas(versiones) {
  const veces = new Map();
  for (const v of versiones) for (const n of v.nums) veces.set(n, (veces.get(n) || 0) + 1);
  return [...veces.values()].filter(k => k > 1).length;
}

/** El orden en que se imprimen las preguntas de una versión (el mismo en la vista previa y en el PDF). */
export function numsEnOrden(version, questions, { partes = true, barajarPreguntas = true } = {}) {
  const porNum = new Map(questions.map((q, i) => [q.num, { q, i }]));
  const propias = version.nums.filter(n => porNum.has(n)).sort((a, b) => porNum.get(a).i - porNum.get(b).i);
  if (!barajarPreguntas) return propias;
  const azar = crearAzar(version.semilla);
  if (!partes) return barajar(propias, azar);
  // Con partes, cada tipo es una parte: el orden de las partes es el del examen y se baraja dentro de cada una.
  const tipos = [];
  const grupos = new Map();
  for (const n of propias) {
    const t = porNum.get(n).q.type;
    if (!grupos.has(t)) { grupos.set(t, []); tipos.push(t); }
    grupos.get(t).push(n);
  }
  return tipos.flatMap(t => barajar(grupos.get(t), azar));
}

// ── Puntos ─────────────────────────────────────────────────────────────────
/** Los puntos de cada pregunta de la versión: el del docente si lo cambió; si no, el del examen. */
export function puntosDeVersion(version, questions) {
  const porNum = new Map(questions.map(q => [q.num, q]));
  const salida = {};
  for (const n of version.nums) {
    const propio = version.puntos[n];
    const q = porNum.get(n);
    const p = propio !== undefined ? propio : (q && Number.isFinite(q.points) ? q.points : 0);
    salida[n] = Number.isFinite(p) && p >= 0 ? p : 0;
  }
  return salida;
}

/** La suma de los puntos de una versión (en centésimas exactas). */
export function totalDeVersion(version, questions) {
  return redondear(Object.values(puntosDeVersion(version, questions)).reduce((a, b) => a + b, 0));
}

/** Reparte `total` puntos entre las preguntas de la versión ('equal' o 'byType'); la suma cuadra siempre. */
export function repartirVersion(version, questions, total, modo = 'byType') {
  const porNum = new Map(questions.map(q => [q.num, q]));
  const copia = version.nums.filter(n => porNum.has(n)).map(n => ({ num: n, type: porNum.get(n).type }));
  autoDistributePoints(copia, total, modo);
  return Object.fromEntries(copia.map(q => [q.num, q.points]));
}

/** ¿La suma de la versión es el total que se quiere? (`objetivo` vacío = no se compara). */
export function cuadra(version, questions, objetivo) {
  const meta = Number(objetivo);
  if (!Number.isFinite(meta) || meta <= 0) return true;
  return Math.abs(totalDeVersion(version, questions) - meta) < 0.005;
}

// ── Lo que se envía al servidor ───────────────────────────────────────────
/**
 * El examen de UNA versión (para su vista previa): solo sus preguntas, en su orden, con sus puntos y SU clave.
 * `opciones`: { partes, barajarPreguntas }.
 */
export function examenDeVersion(examen, version, opciones = {}) {
  const orden = numsEnOrden(version, examen.questions, opciones);
  const porNum = new Map(examen.questions.map(q => [q.num, q]));
  const puntos = puntosDeVersion(version, examen.questions);
  const answer_key = {};
  for (const n of orden) if (examen.answer_key && examen.answer_key[n] !== undefined) answer_key[n] = examen.answer_key[n];
  return {
    filename: examen.filename,
    total_points: Math.max(0.01, totalDeVersion(version, examen.questions)),
    questions: orden.map(n => ({ ...porNum.get(n), points: puntos[n] })),
    answer_key,
  };
}

/** Las versiones tal como las pide POST /api/exportar_versiones (el examen completo va aparte). */
export function versionesParaEnviar(examen, versiones, opciones = {}) {
  return versiones.map(v => ({
    etiqueta: v.etiqueta,
    nums: numsEnOrden(v, examen.questions, opciones),
    puntos: Object.fromEntries(Object.entries(v.puntos).map(([k, p]) => [String(k), p])),
    total_points: Math.max(0.01, totalDeVersion(v, examen.questions)),
  }));
}

/** El resumen de lo sorteado por tipo: [{ nombre, cantidad }] para mostrar en cada versión. */
export function composicion(version, questions) {
  const tipos = new Map(questions.map(q => [q.num, q.type]));
  const cuenta = new Map();
  for (const n of version.nums) {
    const t = tipos.get(n);
    if (t) cuenta.set(t, (cuenta.get(t) || 0) + 1);
  }
  return resumenPorTipo(questions).filter(t => cuenta.has(t.tipo)).map(t => ({ tipo: t.tipo, nombre: t.nombre, cantidad: cuenta.get(t.tipo) }));
}
