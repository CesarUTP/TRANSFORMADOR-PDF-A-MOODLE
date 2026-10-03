/**
 * respuesta-indices.js — las respuestas correctas de una pregunta de opción
 * múltiple como POSICIONES, además del texto.
 *
 * La clave guarda las correctas como texto unido con " | " ("B | D"). Una
 * opción cuyo propio texto lleva " | " ("x | y", típico de programación) se
 * partía en dos al volver a leer la clave. Por eso answer_key[n].correct_idx
 * trae las posiciones (base 0) de las opciones correctas en las letras
 * ORDENADAS de data.options (A→0, B→1…): con ellas no hay texto que partir.
 * Mismas reglas que backend/modelo.py (PreguntaMultichoice.resolver_correctas):
 * las posiciones solo valen si son enteros dentro de rango Y las opciones que
 * señalan, unidas con " | ", dicen lo mismo que el texto de la clave; si no
 * (clave vieja, texto editado aparte), se analiza el texto como siempre.
 *
 * Lógica pura, sin DOM: se prueba sola (ver frontend/pruebas.html). Para el
 * Cloze la misma idea vive en cloze-segmentos.js (answer_key[n].huecos).
 */
import { indicesUtilizables } from './cloze-segmentos.js';

const colapsar = (t) => String(t || '').split(/\s+/).filter(Boolean).join(' ');
const letrasOrdenadas = (options) => Object.keys(options || {}).sort();

/**
 * Las letras de las opciones correctas según `clave.correct_idx`, o null si la
 * clave no las trae, no valen o no concuerdan con su texto (`clave.answer`).
 */
export function letrasCorrectasPorIndice(options, clave) {
  if (!clave || typeof clave !== 'object') return null;
  const letras = letrasOrdenadas(options);
  const usables = indicesUtilizables(clave.correct_idx, letras.length);
  if (!usables) return null;
  const marcadas = usables.map(i => letras[i]);
  const textos = marcadas.map(L => options[L]);
  if (colapsar(textos.join(' | ')) !== colapsar(clave.answer)) return null;
  return marcadas;
}

/**
 * La entrada de answer_key para una pregunta de opción múltiple con las
 * opciones `letrasMarcadas` como correctas: { answer, correct_idx? }.
 * Una opción marcada sin texto no cuenta (el validador ya señala la vacía);
 * sin ninguna marcada no hay correct_idx.
 */
export function claveDeOpcionMultiple(options, letrasMarcadas) {
  const letras = letrasOrdenadas(options);
  const conTexto = (letrasMarcadas || []).filter(L => String((options || {})[L] || '').length > 0);
  const idx = [];
  conTexto.forEach(L => {
    const i = letras.indexOf(L);
    if (i >= 0 && !idx.includes(i)) idx.push(i);
  });
  const clave = { answer: conTexto.map(L => options[L]).join(' | ') };
  if (idx.length) clave.correct_idx = idx;
  return clave;
}
