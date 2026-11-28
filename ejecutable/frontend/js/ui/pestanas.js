/**
 * pestanas.js — pestañas accesibles (3.2): un `role="tablist"` cuyos botones muestran cada uno su panel.
 * Flechas, Inicio y Fin cambian de pestaña, como en cualquier aplicación.
 */

/** La posición a la que lleva una tecla en `total` pestañas; null si la tecla no es de pestañas. */
export function pestanaTrasTecla(tecla, actual, total) {
  if (tecla === 'ArrowRight') return (actual + 1) % total;
  if (tecla === 'ArrowLeft') return (actual - 1 + total) % total;
  if (tecla === 'Home') return 0;
  if (tecla === 'End') return total - 1;
  return null;
}

/** `lista`: el elemento con role="tablist"; `alMostrar()`: se avisa al cambiar de pestaña. */
export function crearPestanas(lista, alMostrar = () => {}) {
  const botones = [...lista.querySelectorAll('[role="tab"]')];
  const panelDe = b => document.getElementById(b.getAttribute('aria-controls'));

  function mostrar(id, { foco = false } = {}) {
    const elegido = botones.find(b => b.id === id) || botones[0];
    botones.forEach(b => {
      const si = b === elegido;
      b.setAttribute('aria-selected', String(si));
      b.tabIndex = si ? 0 : -1;
      panelDe(b).hidden = !si;
    });
    if (foco) elegido.focus();
    alMostrar(elegido.id);
  }

  lista.addEventListener('click', e => {
    const b = e.target.closest('[role="tab"]');
    if (b) mostrar(b.id);
  });
  lista.addEventListener('keydown', e => {
    // En un menú vertical las flechas de arriba y abajo hacen lo mismo que las de los lados.
    const vertical = lista.getAttribute('aria-orientation') === 'vertical';
    const tecla = vertical ? ({ ArrowDown: 'ArrowRight', ArrowUp: 'ArrowLeft' }[e.key] || e.key) : e.key;
    const n = pestanaTrasTecla(tecla, botones.indexOf(e.target), botones.length);
    if (n === null) return;
    e.preventDefault();
    mostrar(botones[n].id, { foco: true });
  });

  return {
    mostrar,
    /** Muestra la pestaña donde está `elemento` (para llevar al docente al campo con un problema). */
    mostrarElemento(elemento) {
      const b = botones.find(x => panelDe(x).contains(elemento));
      if (b) mostrar(b.id);
    },
    actual: () => (botones.find(b => b.getAttribute('aria-selected') === 'true') || botones[0]).id,
  };
}
