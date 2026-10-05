/**
 * plegado-logica.js — la parte de plegado.js que no toca el DOM (se prueba en Node).
 */

/** Tope de tarjetas que se abren solas: más sería otra vez el muro de tarjetas. */
export const MAX_ABIERTAS = 3;
const LARGO_ENUNCIADO = 140;

/**
 * Qué tarjetas se abren al dibujar un examen NUEVO. `estados` trae, por tarjeta
 * y en orden, { incompleta, revisar }. Devuelve un arreglo de booleanos.
 * Pura: se prueba en Node.
 */
export function abiertasPorDefecto(estados) {
  const lista = Array.isArray(estados) ? estados : [];
  const abiertas = lista.map(() => false);
  let n = 0;
  lista.forEach((e, i) => {
    if (e && (e.incompleta || e.revisar) && n < MAX_ABIERTAS) { abiertas[i] = true; n++; }
  });
  if (!n && abiertas.length) abiertas[0] = true;
  return abiertas;
}

/** Texto corto de una sola línea (espacios y saltos colapsados), con «…» si se corta. */
export function recortar(texto, max = LARGO_ENUNCIADO) {
  const t = String(texto ?? '').replace(/\s+/g, ' ').trim();
  return t.length > max ? `${t.slice(0, max - 1).trimEnd()}…` : t;
}

