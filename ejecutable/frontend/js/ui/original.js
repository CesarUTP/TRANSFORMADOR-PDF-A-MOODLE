/**
 * original.js — «Revisión con el original»: un modal con el recorte de la página
 * del documento donde está la pregunta, y junto a él la respuesta que propone la
 * app con su origen y su confianza.
 *
 * Se abre desde el chip «Pág. N» de cada tarjeta (solo si el servidor conserva el
 * PDF de esta sesión: ver backend/originales.py; en el Historial, con Word o TXT el
 * chip es solo informativo). El recorte lo dibuja el servidor bajo demanda: aquí no
 * se guarda ninguna imagen. Dentro del modal se pasa a la pregunta anterior o
 * siguiente (y a la anterior o siguiente «para revisar») sin cerrarlo; Esc lo cierra.
 */
import { apiFetch } from '../api.js';
import { collectEditorData } from '../editor/tarjetas.js';
import { resumenDe, abrirTarjeta } from '../editor/plegado.js';
import { scrollToEditorCard } from '../editor/panel.js';
import { chipsDeProcedencia, chipsHtml, necesitaRevisarPrimero, requiereRevision } from '../editor/procedencia.js';
import { estado } from '../estado.js';
import { crearIconos, esc_html } from '../util.js';
import { abrirModal, cerrarModal } from './modales.js';
import { paginaDe, recuadroValido, urlOriginal, vecino, zoomVecino } from './original-logica.js';

const $ = id => document.getElementById(id);

// Lo que el modal tiene a la vista ahora. Se arma al abrirlo (con lo que hay en el
// editor en ese momento) y no cambia mientras está abierto: el fondo está inerte.
let ctx = null; // { cards, datos: [{ card, q, key, pagina, recuadro }], pos, vista, zoom, peticion, url }

function _tarjetasVisibles() {
  return Array.from(document.querySelectorAll('#editor-questions-container .editor-card'))
    .filter(c => c.style.display !== 'none');
}

function _armarContexto(cardInicial) {
  const todas = Array.from(document.querySelectorAll('#editor-questions-container .editor-card'));
  const { questions, answer_key } = collectEditorData({ conImagenes: false });
  const datos = _tarjetasVisibles().map(card => {
    const i = todas.indexOf(card);
    const q = questions[i];
    const data = (q && q.data) || {};
    return { card, q, key: q ? answer_key[q.num] : null, pagina: paginaDe(data), recuadro: recuadroValido(data.recuadro) ? data.recuadro : null };
  });
  const pos = Math.max(0, datos.findIndex(d => d.card === cardInicial));
  return { datos, pos, vista: 'recorte', zoom: 1, peticion: 0, url: null };
}

/** Acción del chip «Pág. N» (data-accion="verOriginal"). */
export function verOriginal(btn) {
  const card = btn.closest('.editor-card');
  if (!card || !estado.originalId) return;
  ctx = _armarContexto(card);
  abrirModal($('modal-original'), { foco: $('orig-cerrar'), onClose: _alCerrar });
  _mostrar();
}

function _alCerrar() {
  _soltarImagen();
  const d = ctx && ctx.datos[ctx.pos];
  ctx = null;
  // El docente queda en la última pregunta que miró, abierta y a la vista.
  if (d && d.card.isConnected) {
    abrirTarjeta(d.card);
    scrollToEditorCard(d.card, { enfocar: true });
  }
}

function _soltarImagen() {
  const img = $('orig-imagen');
  if (img && img.dataset.objeto) URL.revokeObjectURL(img.dataset.objeto);
  if (img) { img.removeAttribute('src'); delete img.dataset.objeto; img.hidden = true; }
}

function _estadoImagen(texto, { error = false } = {}) {
  const el = $('orig-estado');
  el.hidden = !texto;
  el.textContent = texto || '';
  el.classList.toggle('es-error', error);
}

function _marcas() {
  return ctx.datos.map(d => !!d.card.dataset.revisar || d.card.dataset.review === '1'
    || (d.q && (necesitaRevisarPrimero(d.q.data) || requiereRevision(d.q.data))));
}

function _actualizarPie() {
  const marcas = _marcas();
  const hay = (delta, solo) => vecino(marcas, ctx.pos, delta, solo) >= 0;
  $('orig-ant').disabled = !hay(-1, false);
  $('orig-sig').disabled = !hay(1, false);
  $('orig-ant-rev').disabled = !hay(-1, true);
  $('orig-sig-rev').disabled = !hay(1, true);
}

function _mostrar() {
  const d = ctx.datos[ctx.pos];
  const q = d.q;
  const tipo = q ? q.type : '';
  $('orig-titulo').textContent = `Pregunta ${q ? q.num : ctx.pos + 1}${d.pagina ? ` · Pág. ${d.pagina}` : ''}`;
  $('orig-posicion').textContent = `${ctx.pos + 1} de ${ctx.datos.length}`;

  // La respuesta que propone la app, con su origen y su confianza (aquí SIEMPRE
  // completos, también «Clave del documento» y «Confianza alta»).
  const r = resumenDe(d.card, { largoEnunciado: 400, largoRespuesta: 300 });
  $('orig-enunciado').textContent = r.enunciado || 'Sin enunciado';
  const resp = $('orig-respuesta');
  resp.textContent = tipo === 'essay' ? 'Respuesta abierta: se califica a mano en Moodle.'
    : (r.falta ? 'Sin respuesta marcada todavía.' : r.respuesta);
  resp.classList.toggle('falta', !!r.falta && tipo !== 'essay');
  const chips = chipsDeProcedencia(q ? q.data : {}, tipo).filter(c => c.clave !== 'pagina');
  $('orig-chips').innerHTML = chipsHtml(chips);
  crearIconos($('orig-chips'));

  // Recorte o página completa. Sin recuadro solo hay página completa.
  const conRecuadro = !!d.recuadro;
  if (!conRecuadro) ctx.vista = 'pagina';
  $('orig-vista-recorte').disabled = !conRecuadro;
  $('orig-vista-recorte').title = conRecuadro ? '' : 'No se pudo ubicar esta pregunta dentro de la página: se muestra la página completa.';
  $('orig-vista-recorte').setAttribute('aria-pressed', ctx.vista === 'recorte' ? 'true' : 'false');
  $('orig-vista-pagina').setAttribute('aria-pressed', ctx.vista === 'pagina' ? 'true' : 'false');
  // El zoom agranda la imagen (el servidor la dibuja a esa resolución): el visor se desplaza.
  $('orig-imagen').style.width = `${ctx.zoom * 100}%`;
  $('orig-zoom-etiqueta').textContent = `${Math.round(ctx.zoom * 100)} %`;
  $('orig-zoom-menos').disabled = ctx.zoom <= 1;
  $('orig-zoom-mas').disabled = ctx.zoom >= 3;
  $('orig-nota').hidden = conRecuadro;
  _actualizarPie();
  _pedirImagen();
}

async function _pedirImagen() {
  const d = ctx.datos[ctx.pos];
  const mia = ++ctx.peticion;
  _soltarImagen();
  if (!d.pagina) {
    _estadoImagen('Esta pregunta no tiene una página del original asociada.', { error: true });
    return;
  }
  _estadoImagen('Cargando el original…');
  try {
    const res = await apiFetch(urlOriginal(estado.originalId, d.pagina,
      { vista: ctx.vista, recuadro: d.recuadro, zoom: ctx.zoom }));
    if (!ctx || mia !== ctx.peticion) return; // el docente ya pasó a otra
    if (!res.ok) {
      const datos = await res.json().catch(() => ({}));
      _estadoImagen(typeof datos.detail === 'string' ? datos.detail : 'No se pudo cargar el original.', { error: true });
      return;
    }
    const blob = await res.blob();
    if (!ctx || mia !== ctx.peticion) return;
    const img = $('orig-imagen');
    const url = URL.createObjectURL(blob);
    img.dataset.objeto = url;
    img.alt = `${ctx.vista === 'recorte' ? 'Recorte de la pregunta' : 'Página completa'} ${d.q ? d.q.num : ''} en la página ${d.pagina} del documento original`;
    img.src = url;
    img.hidden = false;
    _estadoImagen('');
    $('orig-visor').scrollTop = 0;
  } catch (e) {
    if (!ctx || mia !== ctx.peticion) return;
    _estadoImagen('No se pudo conectar con la aplicación para cargar el original.', { error: true });
  }
}

function _ir(delta, solo = false) {
  const i = vecino(_marcas(), ctx.pos, delta, solo);
  if (i < 0) return;
  ctx.pos = i;
  _mostrar();
}

/** Registra los botones del modal (una sola vez, desde app.js). */
export function iniciarOriginal() {
  const modal = $('modal-original');
  if (!modal) return;
  $('orig-cerrar').addEventListener('click', () => cerrarModal(modal));
  modal.addEventListener('click', e => { if (e.target === modal) cerrarModal(modal); });
  $('orig-ant').addEventListener('click', () => _ir(-1));
  $('orig-sig').addEventListener('click', () => _ir(1));
  $('orig-ant-rev').addEventListener('click', () => _ir(-1, true));
  $('orig-sig-rev').addEventListener('click', () => _ir(1, true));
  $('orig-vista-recorte').addEventListener('click', () => { if (ctx) { ctx.vista = 'recorte'; _mostrar(); } });
  $('orig-vista-pagina').addEventListener('click', () => { if (ctx) { ctx.vista = 'pagina'; _mostrar(); } });
  $('orig-zoom-menos').addEventListener('click', () => { if (ctx) { ctx.zoom = zoomVecino(ctx.zoom, -1); _mostrar(); } });
  $('orig-zoom-mas').addEventListener('click', () => { if (ctx) { ctx.zoom = zoomVecino(ctx.zoom, 1); _mostrar(); } });
  // Flechas: de una pregunta a otra (acción de teclado: sin animación).
  modal.addEventListener('keydown', e => {
    if (!ctx || e.ctrlKey || e.metaKey || e.altKey || e.target.closest('input, textarea, select')) return;
    if (e.key === 'ArrowLeft') { e.preventDefault(); _ir(-1, e.shiftKey); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); _ir(1, e.shiftKey); }
  });
}
