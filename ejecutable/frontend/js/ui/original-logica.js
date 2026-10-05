/**
 * original-logica.js — la parte de «Revisión con el original» que no toca el DOM
 * (se prueba en Node). El modal vive en original.js.
 */

/** Niveles de zoom del recorte (el servidor lo dibuja a esa resolución). */
export const ZOOMS = [1, 1.5, 2, 3];

/** Siguiente nivel de zoom (delta +1 / -1), sin salirse de ZOOMS. */
export function zoomVecino(zoom, delta) {
  const i = ZOOMS.findIndex(z => z === zoom);
  const base = i < 0 ? 0 : i;
  return ZOOMS[Math.min(ZOOMS.length - 1, Math.max(0, base + delta))];
}

/** ¿Es un recuadro [x0, y0, x1, y1] de fracciones de la página, con área? */
export function recuadroValido(r) {
  return Array.isArray(r) && r.length === 4 && r.every(v => typeof v === 'number' && v >= 0 && v <= 1)
    && r[2] - r[0] >= 0.005 && r[3] - r[1] >= 0.005;
}

/** Página del original de una pregunta (entero desde 1), o null. */
export function paginaDe(data) {
  return data && Number.isInteger(data.page) && data.page > 0 ? data.page : null;
}

/**
 * Dirección de la imagen. `vista` «recorte» solo se pide si hay recuadro: sin él
 * (dos columnas, escaneados, páginas giradas) siempre es la página completa.
 */
export function urlOriginal(id, pagina, { vista = 'recorte', recuadro = null, zoom = 1 } = {}) {
  const con = recuadroValido(recuadro);
  const p = new URLSearchParams();
  p.set('vista', vista === 'pagina' || !con ? 'pagina' : 'recorte');
  if (con) p.set('recuadro', recuadro.map(v => Number(v.toFixed(4))).join(','));
  if (zoom && zoom !== 1) p.set('zoom', String(zoom));
  return `/api/original/${encodeURIComponent(id)}/pagina/${pagina}?${p.toString()}`;
}

/**
 * A qué posición ir desde `actual` (índice) moviéndose `delta` (+1/-1) por la
 * lista de `marcas` (booleanos). Con `soloMarcadas` salta a la siguiente marcada
 * en esa dirección; sin ella, a la contigua. -1 si no hay a dónde ir.
 */
export function vecino(marcas, actual, delta, soloMarcadas = false) {
  const paso = delta < 0 ? -1 : 1;
  for (let i = actual + paso; i >= 0 && i < marcas.length; i += paso) {
    if (!soloMarcadas || marcas[i]) return i;
  }
  return -1;
}
