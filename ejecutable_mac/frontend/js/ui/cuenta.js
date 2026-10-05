/**
 * cuenta.js — los números del resumen final suben hasta su valor.
 *
 * Es el momento más raro de la app (pasa una vez por examen) y el único donde
 * un poco de movimiento celebra algo: por eso se anima aquí y en ningún otro
 * lado. Dura medio segundo, arranca rápido y frena (ease-out), y con «reducir
 * movimiento» no hace nada. Al terminar el texto vuelve EXACTAMENTE al original,
 * así que el número final nunca depende de la animación.
 */
const DURACION_MS = 550;
const NUMERO = /^(\D*)(\d+(?:\.\d+)?)(.*)$/s;

const _sinMovimiento = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

function _formato(valor, decimales) {
  return decimales ? Number(valor.toFixed(decimales)).toString() : String(Math.round(valor));
}

/** Anima el primer número de cada elemento que coincida con `selector` dentro de `raiz`. */
export function animarCifras(raiz, selector = '[data-cuenta]') {
  if (!raiz || _sinMovimiento()) return;
  raiz.querySelectorAll(selector).forEach(el => {
    const original = el.textContent;
    const m = NUMERO.exec(original);
    if (!m) return;
    const [, antes, num, despues] = m;
    const fin = Number(num);
    const decimales = (num.split('.')[1] || '').length;
    if (!Number.isFinite(fin) || fin === 0) return;
    const inicio = performance.now();
    const paso = ahora => {
      const t = Math.min((ahora - inicio) / DURACION_MS, 1);
      const suave = 1 - Math.pow(1 - t, 4);
      el.textContent = t < 1 ? `${antes}${_formato(fin * suave, decimales)}${despues}` : original;
      if (t < 1) requestAnimationFrame(paso);
    };
    requestAnimationFrame(paso);
  });
}
