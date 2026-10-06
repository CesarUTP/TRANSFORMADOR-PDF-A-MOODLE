/**
 * tour.js — los recorridos guiados de cada pantalla, con driver.js (MIT, copiado en js/vendor/driver).
 * Lo empieza el asistente flotante (ui/asistente.js) con iniciarTour(<nombre>) y resalta, paso a paso, las partes
 * de la pantalla y explica para qué sirven. Los pasos están en tour-logica.js.
 */
import { CLAVE_VISTOS, TOURS, leerVistos, marcarVisto, nombreDeTour, pasosVisibles } from './tour-logica.js';

let activo = null;

/** ¿Hay un recorrido en pantalla? (Escape lo cierra a él, no a la ventana de debajo.) */
export function hayTourActivo() { return !!activo; }

function leer() {
  try { return leerVistos(localStorage.getItem(CLAVE_VISTOS)); } catch (_) { return leerVistos(null); }
}

function guardar(estado) {
  try { localStorage.setItem(CLAVE_VISTOS, JSON.stringify(estado)); } catch (_) { /* sin almacenamiento: se vuelve a ofrecer */ }
}

function enPantalla(selector) {
  const el = document.querySelector(selector);
  return !!el && el.getClientRects().length > 0;
}

export function iniciarTour(nombre) {
  const driverJs = window.driver && window.driver.js && window.driver.js.driver;
  if (!driverJs) return;   // la biblioteca no cargó: el botón no hace nada en vez de fallar
  const clave = nombreDeTour(nombre, { hayLista: !!document.getElementById('vm-lista') });
  if (!clave) return;
  if (activo) { activo.destroy(); activo = null; }
  const pasos = pasosVisibles(TOURS[clave].pasos, enPantalla);
  if (!pasos.length) return;
  const reducido = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const instancia = driverJs({
    steps: pasos.map(p => ({
      ...(p.el ? { element: p.el } : {}),
      popover: { title: p.titulo, description: p.texto, ...(p.el ? { side: p.lado || 'bottom', align: 'start' } : {}) },
    })),
    popoverClass: 'tour-popover',
    nextBtnText: 'Siguiente',
    prevBtnText: 'Anterior',
    doneBtnText: 'Entendido',
    progressText: '{{current}} de {{total}}',
    showProgress: true,
    allowClose: true,
    animate: !reducido,
    smoothScroll: !reducido,
    overlayColor: '#030712',
    overlayOpacity: 0.68,
    stagePadding: 6,
    stageRadius: 10,
    // Se cierre como se cierre (Entendido, la equis, Escape o un clic fuera) pasa por aquí: onDestroyed de driver.js
    // solo se llama cuando la animación del paso ya terminó, y con la ventana en segundo plano no siempre llega.
    onDestroyStarted: () => {
      instancia.destroy();
      if (activo !== instancia) return;
      activo = null;
      guardar(marcarVisto(leer(), clave));
      window.dispatchEvent(new Event('tourfin'));
    },
  });
  activo = instancia;
  instancia.drive();
}

/** Que el asistente no vuelva a ofrecer recorridos con un globo (sigue disponible al hacer clic en él). */
export function silenciarOfertas() {
  guardar({ ...leer(), descartado: true });
}

export function estadoDelTour() { return leer(); }
