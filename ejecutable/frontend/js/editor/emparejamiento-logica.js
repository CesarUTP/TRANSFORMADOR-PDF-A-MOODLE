/**
 * emparejamiento-logica.js — las filas de una pregunta de emparejamiento y los DISTRACTORES.
 *
 * Un distractor es una opción de la columna B que NO es la pareja de ningún concepto de la
 * columna A (el docente puso más opciones que conceptos para que no se adivine por descarte).
 * En los datos es una letra de `col_b` que ningún valor de `pares` usa. En el editor es una fila
 * con la columna A vacía y marcada como «opción de más».
 *
 * Lógica pura (sin DOM): se prueba en Node (pruebas.js).
 */

/**
 * Filas que dibuja el editor, a partir de las parejas ya resueltas ([{left, right}]) y de los
 * datos de la pregunta: las parejas primero y, después, un distractor por cada opción de la
 * columna B que no es la pareja de nadie.
 *   `colB`:  {a: 'texto', b: …};  `pares`: {'1': 'a', …} (número de concepto → letra de la B).
 *   Sin `pares` (clave sin parejas) los distractores son las letras de B que sobran después de
 *   emparejar en orden (1-a, 2-b…), que es como el editor dibuja esas parejas.
 */
export function filasConDistractores(parejas, colA, colB, pares) {
  const filas = parejas.map(p => ({ left: p.left, right: p.right, distractor: false }));
  const B = colB || {};
  const letras = Object.keys(B).sort();
  const usadas = new Set();
  const hayPares = pares && Object.keys(pares).length > 0;
  if (hayPares) {
    Object.keys(colA || {}).forEach(k => { const l = String(pares[k] || '').toLowerCase(); if (l) usadas.add(l); });
  } else {
    letras.slice(0, Object.keys(colA || {}).length).forEach(l => usadas.add(l));
  }
  letras.filter(l => !usadas.has(l) && String(B[l] || '').trim())
    .forEach(l => filas.push({ left: '', right: String(B[l]), distractor: true }));
  return filas;
}

/**
 * Lo contrario: de las filas del editor [{left, right, distractor}] a los datos de la pregunta.
 * Las parejas se numeran seguidas (1, 2, 3…) con la letra de su posición (a, b, c…) y los
 * distractores siguen con las letras que quedan, así que la columna A nunca tiene huecos.
 * Una fila vacía por completo se descarta. Una pareja con solo un lado se conserva (el
 * validador la marca como incompleta); un distractor sin texto se descarta.
 */
export function datosDeFilas(filas) {
  const colA = {}, colB = {}, pares = {}, clave = [];
  let k = 0;
  const distractores = [];
  (filas || []).forEach(f => {
    const left = String(f.left || '').trim(), right = String(f.right || '').trim();
    if (f.distractor) { if (right) distractores.push(right); return; }
    if (!left && !right) return;
    const num = String(k + 1), letra = String.fromCharCode(97 + k);
    colA[num] = left;
    colB[letra] = right;
    pares[num] = letra;
    clave.push(`${num}-${letra}`);
    k++;
  });
  distractores.forEach((texto, d) => { colB[String.fromCharCode(97 + k + d)] = texto; });
  return { colA, colB, pares, clave: clave.join('; '), distractores: distractores.length };
}

/** «3 parejas», «2 parejas y 1 opción de más» (resumen de la tarjeta plegada). */
export function resumenDeFilas(parejas, distractores) {
  const base = parejas === 1 ? '1 pareja' : `${parejas} parejas`;
  if (!distractores) return base;
  return `${base} y ${distractores === 1 ? '1 opción de más' : `${distractores} opciones de más`}`;
}
