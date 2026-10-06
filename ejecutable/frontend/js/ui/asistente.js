/**
 * asistente.js — el asistente flotante: un profe 3D en la esquina (profe-3d.js) que saca la mano para saludar y ofrece el recorrido guiado de la pantalla en que estás («¿No sabes por dónde empezar? ¡Déjame ayudarte!»)
 * y lo empieza al hacer clic.
 *
 * Qué recorrido toca lo decide contextoDeAyuda() (tour-logica.js) según la ventana de más arriba y el panel; con
 * otras ventanas (confirmaciones, la Guía, la clave) o pantallas de espera, el asistente se esconde. El globo se
 * ofrece solo una vez por pantalla y sesión, y solo si ese recorrido no se hizo ya.
 */
import { estado } from '../estado.js';
import { crearIconos } from '../util.js';
import { modalActivo } from './modales.js';
import { crearProfe } from './profe-3d.js';
import { estadoDelTour, hayTourActivo, iniciarTour, silenciarOfertas } from './tour.js';
import { MENSAJES, contextoDeAyuda, debeSaludar } from './tour-logica.js';

const $ = id => document.getElementById(id);
const ESPERA_SALUDO_MS = 1600;
const DURACION_GLOBO_MS = 16000;

let contexto = null;
let profe = null;
let temporizadorAtencion = 0;
let temporizadorSaludo = 0;
let temporizadorGlobo = 0;
const yaOfrecidos = new Set();
const reducidoMovimiento = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

/** El profe saca la mano y saluda (y da un saltito el botón entero, por si el 3D no está). */
function saludar(segundos) {
  const boton = $('asistente-boton');
  boton.classList.remove('saludando');
  void boton.offsetWidth;             // reinicia la animación si ya estaba puesta
  boton.classList.add('saludando');
  if (profe) profe.saludar(segundos);
}

function globoAbierto() { return !$('asistente-burbuja').hidden; }

function cerrarGlobo() {
  clearTimeout(temporizadorGlobo);
  $('asistente-burbuja').hidden = true;
}

function abrirGlobo({ auto = false } = {}) {
  if (!contexto || hayTourActivo()) return;
  const m = MENSAJES[contexto];
  $('asistente-titulo').textContent = m.titulo;
  $('asistente-texto').textContent = m.texto;
  $('asistente-burbuja').hidden = false;
  saludar(auto ? 3.2 : 2.4);
  clearTimeout(temporizadorGlobo);
  // Un globo que apareció solo se va solo; si el docente lo pidió (cursor o foco encima), se queda.
  if (auto) temporizadorGlobo = setTimeout(cerrarGlobo, DURACION_GLOBO_MS);
}

/** Recalcula qué recorrido toca y si el asistente se ve (al abrir o cerrar una ventana, o cambiar de pantalla). */
function actualizar() {
  const ventana = modalActivo();
  const nuevo = contextoDeAyuda({ ventana: ventana ? ventana.id : null, panel: estado.panel });
  const raiz = $('asistente');
  const cambio = nuevo !== contexto;
  contexto = nuevo;
  raiz.hidden = !contexto;
  document.body.classList.toggle('con-asistente', !!contexto);
  if (!contexto) { cerrarGlobo(); clearTimeout(temporizadorSaludo); clearInterval(temporizadorAtencion); if (profe) profe.parar(); return; }
  if (profe) profe.reanudar();
  buscarAtencion();
  if (!cambio) return;
  cerrarGlobo();
  clearTimeout(temporizadorSaludo);
  if (debeSaludar(estadoDelTour(), contexto, yaOfrecidos)) {
    const para = contexto;
    temporizadorSaludo = setTimeout(() => {
      if (contexto !== para || hayTourActivo()) return;
      yaOfrecidos.add(para);
      abrirGlobo({ auto: true });
    }, ESPERA_SALUDO_MS);
  }
}

/** Mientras el recorrido de esta pantalla no se haya hecho, el profe vuelve a sacar la mano de vez en cuando para que se note. */
function buscarAtencion() {
  clearInterval(temporizadorAtencion);
  if (reducidoMovimiento || !contexto) return;
  temporizadorAtencion = setInterval(() => {
    if (!contexto || hayTourActivo() || document.hidden || globoAbierto()) return;
    const estadoTour = estadoDelTour();
    const hecho = contexto === 'biblioteca' ? ['biblioteca', 'bibliotecaLista'].some(n => estadoTour.vistos.includes(n)) : estadoTour.vistos.includes(contexto);
    if (!hecho && !estadoTour.descartado) saludar(2.2);
  }, 24000);
}

function empezar() {
  if (!contexto) return;
  yaOfrecidos.add(contexto);
  cerrarGlobo();
  iniciarTour(contexto);
}

export function iniciarAsistente() {
  const raiz = $('asistente');
  if (!raiz) return;
  const reducido = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  crearIconos(raiz);

  // El profe 3D (si hay WebGL); si no, queda el ícono de birrete.
  try { profe = crearProfe($('asistente-canvas'), { animado: !reducido }); } catch (_) { profe = null; }
  raiz.classList.toggle('sin-3d', !profe);

  const boton = $('asistente-boton');
  boton.addEventListener('click', empezar);
  $('asistente-si').addEventListener('click', empezar);
  $('asistente-cerrar').addEventListener('click', cerrarGlobo);
  $('asistente-silencio').addEventListener('click', () => { silenciarOfertas(); cerrarGlobo(); });
  // Con el cursor o el teclado encima, el globo aparece y no se va.
  boton.addEventListener('pointerenter', e => { if (e.pointerType === 'mouse') abrirGlobo(); });
  boton.addEventListener('focus', () => { if (boton.matches(':focus-visible')) abrirGlobo(); });
  raiz.addEventListener('pointerenter', () => clearTimeout(temporizadorGlobo));
  raiz.addEventListener('pointerleave', e => { if (e.pointerType === 'mouse' && globoAbierto()) temporizadorGlobo = setTimeout(cerrarGlobo, 1200); });
  // Escape cierra el globo si el foco está dentro del asistente.
  raiz.addEventListener('keydown', e => { if (e.key === 'Escape' && globoAbierto()) { e.stopPropagation(); cerrarGlobo(); boton.focus(); } });

  // La mirada y la cámara siguen al puntero.
  if (!reducido) {
    let ultimo = 0;
    window.addEventListener('pointermove', e => {
      const ahora = performance.now();
      if (!profe || raiz.hidden || ahora - ultimo < 24) return;   // unas 40 veces por segundo bastan
      ultimo = ahora;
      const r = boton.getBoundingClientRect();
      const dx = (e.clientX - (r.left + r.width / 2)) / Math.max(260, window.innerWidth * 0.45);
      const dy = (e.clientY - (r.top + r.height / 2)) / Math.max(260, window.innerHeight * 0.45);
      profe.mirar(dx, dy);
    }, { passive: true });
  }
  // Sin gastar batería con la ventana en segundo plano.
  document.addEventListener('visibilitychange', () => {
    if (!profe) return;
    if (document.hidden) profe.parar(); else if (!raiz.hidden) profe.reanudar();
  });

  document.addEventListener('modalcambio', actualizar);
  document.addEventListener('panelcambio', actualizar);
  window.addEventListener('tourfin', actualizar);
  actualizar();
}
