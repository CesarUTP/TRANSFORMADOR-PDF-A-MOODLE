/**
 * numero-logica.js — el separador de miles en las respuestas numéricas.
 *
 * «1,000» o «1.000» pueden ser mil o uno con tres decimales. La app toma la coma y el punto como DECIMAL
 * (Moodle solo entiende el punto), así que Moodle recibe 1.000 = 1, no 1000. Y un número con separadores de
 * miles de verdad («1,234.5», «1.234.567») no es un número que Moodle entienda. Este módulo reconoce los dos
 * casos para avisar al docente. Es la misma regla que backend/answer_matching.py (miles_ambiguo y
 * sin_separador_de_miles): las dos se prueban con la misma tabla de casos.
 *
 * Lógica pura (sin DOM): se prueba en Node (pruebas.js).
 */

const AMBIGUO = /^[+-]?[1-9]\d{0,2}[.,]\d{3}$/;
const CON_MILES = /^[+-]?\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?$/;

/** {leido, alterno} si el número es ambiguo («1,000» → {leido: '1.000', alterno: '1000'}); null si no. */
export function milesAmbiguo(texto) {
  const t = String(texto ?? '').trim();
  if (!AMBIGUO.test(t)) return null;
  return { leido: t.replace(',', '.'), alterno: t.replace(/[.,]/, '') };
}

/** El número sin separadores de miles si los lleva («1,234.5» → '1234.5'); null si no los lleva. */
export function sinSeparadorDeMiles(texto) {
  const t = String(texto ?? '').trim();
  if (!CON_MILES.test(t)) return null;
  const seps = [...t.matchAll(/[.,]/g)].map(m => ({ pos: m.index, c: m[0] }));
  if (seps.length < 2) return null;
  const { pos, c } = seps[seps.length - 1];
  const esDecimal = t.length - pos - 1 !== 3 || seps.slice(0, -1).some(s => s.c !== c);
  return esDecimal ? t.slice(0, pos).replace(/[.,]/g, '') + '.' + t.slice(pos + 1) : t.replace(/[.,]/g, '');
}

/** El texto de la pista cuando la respuesta numérica es ambigua; '' si no lo es. */
export function avisoDeMilesAmbiguo(texto) {
  const a = milesAmbiguo(texto);
  if (!a) return '';
  return `«${String(texto).trim()}» puede ser ${a.alterno} o ${a.leido}: Moodle lo recibirá como ${a.leido} (un decimal), no como ${a.alterno}. Si quieres ${a.alterno}, escríbelo sin separador de miles`;
}
