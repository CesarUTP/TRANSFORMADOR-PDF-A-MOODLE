/**
 * calidad.js — avisos de calidad de las preguntas (IA asistida, 2.0), SIN IA.
 *
 * Detecta, con reglas fijas y sin llamar a nadie:
 *   · preguntas duplicadas o casi duplicadas (mismo enunciado y opciones);
 *   · opciones repetidas, o una opción correcta que también aparece como incorrecta;
 *   · opciones que dependen de su posición («todas las anteriores», «A y B»), que
 *     Moodle deja sin sentido porque MEZCLA el orden de las opciones;
 *   · emparejamientos con elementos repetidos; huecos de «Completar» con opciones iguales;
 *   · preguntas de opción múltiple con TODAS las opciones marcadas como correctas.
 *
 * Son avisos, no errores: nunca bloquean nada ni cambian una respuesta. Lógica
 * pura (sin DOM): se prueba en Node (pruebas.js).
 */

const sinTildes = (t) => String(t || '').normalize('NFD').replace(/[̀-ͯ]/g, '');

/**
 * Texto comparable de un ENUNCIADO: minúsculas, sin tildes, sin los signos de puntuación del
 * español, espacios colapsados. Los OPERADORES se conservan («x | y» ≠ «x || y», «≤» ≠ «≥»):
 * en un examen de programación o de matemáticas son lo que distingue una pregunta de otra.
 */
export function normalizar(t) {
  return sinTildes(t).toLowerCase().replace(/[¿?¡!.,;:"“”«»'()]/g, ' ').replace(/\s+/g, ' ').trim();
}

/** Texto de una OPCIÓN para ver si dos dicen lo mismo: solo minúsculas y espacios (con tildes y signos). */
const normalizarOpcion = (t) => String(t || '').toLowerCase().replace(/\s+/g, ' ').trim();

const palabras = (t) => new Set(normalizar(t).split(' ').filter(Boolean));

function parecido(A, B) {
  if (!A.size || !B.size) return 0;
  let comunes = 0;
  A.forEach(p => { if (B.has(p)) comunes++; });
  return comunes / (A.size + B.size - comunes);
}

/** Parecido entre dos textos (0 a 1): palabras en común sobre palabras en total. */
export function similitud(a, b) {
  return parecido(palabras(a), palabras(b));
}

/** Cuánto se parecen el enunciado y las opciones de dos preguntas para llamarlas duplicadas. */
export const UMBRAL_DUPLICADA = 0.85;

function firma(q) {
  const d = q.data || {};
  const base = q.type === 'cloze' ? String(d.text || '').replace(/\[[A-Za-z]:[^\]]*\]/g, ' ') : String(d.stem || '');
  const opciones = q.type === 'multichoice' ? Object.values(d.options || {}).map(normalizar).sort().join(' ')
    : q.type === 'matching' ? Object.values(d.col_a || {}).map(normalizar).sort().join(' ') : '';
  return { base, opciones };
}

const ANTERIORES = /\b(?:todas|ninguna|ambas|cualquiera|alguna)\s+(?:de\s+)?(?:las\s+|los\s+)?(?:anteriores|opciones|respuestas|de\s+arriba)\b|\ball of the above\b|\bnone of the above\b/i;
const LETRAS = /^(?:solo\s+|s[oó]lo\s+)?(?:las?\s+(?:opciones?\s+)?)?[a-e](?:\s*(?:,|y|e|o)\s*[a-e])+\.?$/i;
const POSICION = /\b(?:la\s+)?(?:opci[oó]n|respuesta|alternativa)\s+[a-e]\b/i;

function opcionesRepetidas(opciones) {
  const vistas = new Map();
  const dobles = [];
  Object.entries(opciones || {}).forEach(([letra, texto]) => {
    const n = normalizarOpcion(texto);
    if (!n) return;
    if (vistas.has(n)) dobles.push([vistas.get(n), letra]);
    else vistas.set(n, letra);
  });
  return dobles;
}

/**
 * `questions` y `answerKey` como los entrega collectEditorData(). `conImagen[i]` dice si la
 * pregunta i tiene imágenes: dos preguntas con enunciados genéricos («Observa el programa…»)
 * que se distinguen por su imagen NO se comparan. Devuelve un arreglo (una entrada por
 * pregunta, en orden) con la lista de avisos de cada una.
 */
export function detectarProblemas(questions, answerKey = {}, { conImagen = [] } = {}) {
  const qs = Array.isArray(questions) ? questions : [];
  const avisos = qs.map(() => []);

  qs.forEach((q, i) => {
    const d = (q && q.data) || {};
    if (q.type === 'multichoice') {
      const opciones = d.options || {};
      const dobles = opcionesRepetidas(opciones);
      if (dobles.length) {
        const [a, b] = dobles[0];
        avisos[i].push(`Las opciones ${a} y ${b} dicen lo mismo`);
      }
      const posicionales = Object.entries(opciones).filter(([, t]) => ANTERIORES.test(String(t)) || LETRAS.test(String(t).trim()));
      if (posicionales.length) {
        avisos[i].push(`La opción ${posicionales[0][0]} depende de las demás («${String(posicionales[0][1]).trim().slice(0, 40)}»): Moodle mezcla el orden de las opciones y dejará de tener sentido`);
      } else if (POSICION.test(String(d.stem || ''))) {
        avisos[i].push('El enunciado se refiere a una opción por su letra: Moodle mezcla el orden de las opciones');
      }
      const clave = (answerKey || {})[q.num] || {};
      const marcadas = Array.isArray(clave.correct_idx) ? clave.correct_idx : [];
      const total = Object.keys(opciones).length;
      if (total >= 2 && marcadas.length === total) avisos[i].push('Todas las opciones están marcadas como correctas');
      // Una opción marcada correcta que otra, sin marcar, repite
      const letras = Object.keys(opciones).sort();
      const correctas = new Set(marcadas.map(k => letras[k]).filter(Boolean));
      dobles.forEach(([a, b]) => {
        if (correctas.has(a) !== correctas.has(b)) avisos[i].push(`La opción ${correctas.has(a) ? a : b} es correcta pero ${correctas.has(a) ? b : a} dice lo mismo y no lo es`);
      });
    } else if (q.type === 'matching') {
      const dobleB = opcionesRepetidas(d.col_b);
      if (dobleB.length) avisos[i].push(`Dos elementos de la columna B son iguales (${dobleB[0][0]} y ${dobleB[0][1]}): la pareja es ambigua`);
      const dobleA = opcionesRepetidas(d.col_a);
      if (dobleA.length) avisos[i].push(`Dos elementos de la columna A son iguales (${dobleA[0][0]} y ${dobleA[0][1]})`);
    } else if (q.type === 'cloze') {
      const huecos = ((answerKey || {})[q.num] || {}).huecos;
      if (Array.isArray(huecos)) {
        huecos.forEach((h, k) => {
          const rep = opcionesRepetidas(Object.fromEntries((h.options || []).map((o, j) => [String(j + 1), o])));
          if (rep.length) avisos[i].push(`El espacio ${k + 1} tiene opciones repetidas`);
        });
      }
    }
  });

  // Duplicadas: cada pareja se avisa en las DOS preguntas, con el número de la otra.
  // Los conjuntos de palabras se arman UNA vez por pregunta: esto corre tras cada pausa al
  // escribir y con 150 preguntas son ~11 000 parejas.
  // Son duplicadas si el enunciado Y las opciones se parecen (con el mismo enunciado y
  // opciones distintas, o con distinto enunciado, son preguntas diferentes).
  const firmas = qs.map(firma);
  const base = firmas.map(f => palabras(f.base));
  const opciones = firmas.map(f => palabras(f.opciones));
  for (let i = 0; i < qs.length; i++) {
    for (let j = i + 1; j < qs.length; j++) {
      if (qs[i].type !== qs[j].type || conImagen[i] || conImagen[j]) continue;
      if (base[i].size < 2 || parecido(base[i], base[j]) < UMBRAL_DUPLICADA) continue;
      if ((opciones[i].size || opciones[j].size) && parecido(opciones[i], opciones[j]) < UMBRAL_DUPLICADA) continue;
      avisos[i].push(`Parece repetida con la pregunta ${qs[j].num}`);
      avisos[j].push(`Parece repetida con la pregunta ${qs[i].num}`);
    }
  }
  return avisos;
}
