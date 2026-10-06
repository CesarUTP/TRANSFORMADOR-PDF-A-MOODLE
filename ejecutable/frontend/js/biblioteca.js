/**
 * biblioteca.js — «Mis materias»: una pantalla propia con las materias como espacios y, dentro de cada una,
 * los exámenes que se han convertido (reabrir, XML, PDF, mover, borrar). También «Sin materia» (lo primero que
 * se borra cuando el Historial se llena), «Todos» (la lista completa de siempre) y el asistente que propone
 * una materia para los exámenes viejos.
 *
 * Se abre con el mecanismo de los modales (foco, Escape, fondo inerte) pero ocupa toda la ventana. Los datos
 * salen de /api/history, /api/materias e /api/history/uso; las acciones sobre un examen, de historial.js.
 */
import { apiFetch } from './api.js';
import { borrarBorrador } from './borrador.js';
import { estado } from './estado.js';
import { borrarExamen, downloadHistory, exportarPdfHistorial, fechaLocal, reopenHistory } from './historial.js';
import {
  abrirFormularioMateria, cargarMaterias, crearOEncontrarMateria, elegirEnPaso1, enlazarSelectMateria, llamar,
  llenarSelectMateria, materiaPorId, materias, nombreDeMateria, valorDeSelect,
} from './materias.js';
import {
  activas, archivadas, avisoDeLimite, examenesDe, fechaCorta, filtrarExamenes, formatoBytes, nombreLimpio, normalizar, plural,
  planDelAsistente, sugerirMaterias, textoUso, variableDeColor,
} from './materias-logica.js';
import { resetAll } from './navegacion.js';
import { confirmar } from './ui/confirmar.js';
import { abrirModal, cerrarModal } from './ui/modales.js';
import { showToast } from './ui/toast.js';
import { crearIconos, esc_html } from './util.js';

const $ = id => document.getElementById(id);
const vistaEl = $('vista-materias');

/** Dónde está el docente: raiz (las materias), materia (una), sin (sin materia) o todos. */
const sitio = { nivel: 'raiz', materiaId: null };
let examenes = [];
let uso = null;
let busqueda = '';
const seleccion = new Set();
let cargado = false;

// ── Datos ───────────────────────────────────────────────────────────────
async function cargarExamenes() {
  try {
    const res = await apiFetch('/api/history');
    if (!res.ok) return false;
    examenes = (await res.json()).map(e => ({ ...e, fecha: fechaLocal(e.created_at) }));
    return true;
  } catch (_) { return false; }
}

async function cargarUso() {
  try {
    const res = await apiFetch('/api/history/uso');
    uso = res.ok ? await res.json() : null;
  } catch (_) { uso = null; }
}

async function recargar() {
  const [ok] = await Promise.all([cargarExamenes(), cargarMaterias(), cargarUso()]);
  cargado = ok;
  seleccion.forEach(id => { if (!examenes.some(e => e.id === id)) seleccion.delete(id); });
  if (sitio.nivel === 'materia' && !materiaPorId(sitio.materiaId)) irA('raiz');
  else pintar();
}

// ── Abrir y cerrar ──────────────────────────────────────────────────────
export async function abrirBiblioteca(destino = null) {
  if (vistaEl.classList.contains('open')) return;
  busqueda = '';
  seleccion.clear();
  if (destino) Object.assign(sitio, destino); else Object.assign(sitio, { nivel: 'raiz', materiaId: null });
  cargado = false;
  pintar();
  abrirModal(vistaEl, { foco: $('vm-cuerpo') });
  await recargar();
  $('vm-cuerpo').focus({ preventScroll: true });
}

export function cerrarBiblioteca() {
  cerrarModal(vistaEl);
}

/** Escape: dentro de una materia sube un nivel; en la raíz cierra. Devuelve true si lo atendió. */
export function escapeEnBiblioteca() {
  if (!vistaEl.classList.contains('open')) return false;
  if (sitio.nivel !== 'raiz') { irA('raiz'); return true; }
  cerrarBiblioteca();
  return true;
}

function irA(nivel, materiaId = null) {
  Object.assign(sitio, { nivel, materiaId });
  busqueda = '';
  seleccion.clear();
  pintar();
  $('vm-cuerpo').scrollTop = 0;
  $('vm-cuerpo').focus({ preventScroll: true });
}

export function bibliotecaRaiz() { irA('raiz'); }
export function abrirMateria(id) { irA('materia', id); }
export function abrirSinMateria() { irA('sin'); }
export function abrirTodos() { irA('todos'); }

// ── Piezas de HTML ──────────────────────────────────────────────────────
function aviso(a) {
  if (!a) return '';
  return `<div class="callout ${a.nivel === 'lleno' ? 'is-error' : 'is-warning'} vm-aviso" role="status">
    <i data-lucide="alert-triangle"></i>
    <div><p><strong>${esc_html(a.titulo)}</strong></p><p>${esc_html(a.texto)}</p></div>
  </div>`;
}

function pieDeUso() {
  return uso ? `<p class="vm-uso">${esc_html(textoUso(uso))}</p>` : '';
}

function chipActividad(e) {
  return e.actividad ? `<span class="vm-chip">${esc_html(e.actividad)}</span>` : '';
}

function chipMateria(e) {
  const m = materiaPorId(e.materia_id);
  return m
    ? `<span class="vm-chip vm-chip-materia"><span class="vm-punto" style="background:var(${variableDeColor(m.color)})"></span>${esc_html(m.nombre)}</span>`
    : '<span class="vm-chip vm-chip-sin">Sin materia</span>';
}

function resaltar(texto, q) {
  const seguro = esc_html(texto);
  if (!q) return seguro;
  const chars = [...String(texto)];
  const norm = chars.map(c => normalizar(c));
  if (norm.some(c => c.length !== 1)) return seguro;
  const i = norm.join('').indexOf(q);
  if (i < 0) return seguro;
  return `${esc_html(chars.slice(0, i).join(''))}<mark>${esc_html(chars.slice(i, i + q.length).join(''))}</mark>${esc_html(chars.slice(i + q.length).join(''))}`;
}

function fila(e, q, conMateria) {
  const marcada = seleccion.has(e.id);
  return `<li class="vm-fila" data-id="${e.id}">
    <div class="vm-fila-principal">
      <input type="checkbox" class="vm-casilla" data-accion-cambio="marcarExamen" data-arg-n="${e.id}" ${marcada ? 'checked' : ''} aria-label="Elegir «${esc_html(e.filename)}»">
      <div class="vm-fila-info">
        <strong>${resaltar(e.filename, q)}</strong>
        <span class="vm-meta">${chipActividad(e)}${conMateria ? chipMateria(e) : ''}${resaltar(e.category, q)} · ${esc_html(e.total_points)} pts · ${resaltar(e.fecha, q)}</span>
      </div>
      <div class="vm-fila-acciones">
        ${e.has_editor ? `<button type="button" class="btn btn-ghost btn-sm" data-accion="reabrirExamen" data-arg-n="${e.id}" title="Abrir de nuevo la revisión de este examen"><i data-lucide="pencil" class="ico-14"></i> Reabrir</button>` : ''}
        ${e.has_editor ? `<button type="button" class="btn btn-ghost btn-sm" data-accion="exportarPdfHistorial" data-arg-n="${e.id}" title="Configurar y exportar este examen en PDF, con su clave"><i data-lucide="file-text" class="ico-14"></i> PDF</button>` : ''}
        <button type="button" class="btn btn-ghost btn-sm" data-accion="descargarExamen" data-arg-n="${e.id}" title="Descargar el Moodle XML"><i data-lucide="download" class="ico-14"></i> XML</button>
        <button type="button" class="btn btn-ghost btn-sm vm-organizar-boton" data-accion="organizarExamen" data-arg-n="${e.id}" aria-expanded="false" aria-controls="vm-org-${e.id}" title="Cambiar su materia o su actividad, o borrarlo"><i data-lucide="folder-input" class="ico-14"></i> Organizar</button>
      </div>
    </div>
    <div class="vm-organizar" id="vm-org-${e.id}" hidden>
      <div class="form-group">
        <label class="field-label" for="vm-org-mat-${e.id}">Materia</label>
        <select id="vm-org-mat-${e.id}" class="form-input vm-org-materia"></select>
      </div>
      <div class="form-group">
        <label class="field-label" for="vm-org-act-${e.id}">Actividad</label>
        <input id="vm-org-act-${e.id}" class="form-input vm-org-actividad" type="text" maxlength="160" autocomplete="off" list="actividades-lista" value="${esc_html(e.actividad || '')}" placeholder="ej: Parcial 1">
      </div>
      <div class="vm-organizar-botones">
        <button type="button" class="btn btn-primary btn-sm" data-accion="guardarOrganizar" data-arg-n="${e.id}">Guardar</button>
        <button type="button" class="btn btn-quiet btn-danger-text btn-sm" data-accion="borrarExamenDeLista" data-arg-n="${e.id}"><i data-lucide="trash-2" class="ico-14"></i> Borrar el examen</button>
      </div>
    </div>
  </li>`;
}

function barraDeSeleccion() {
  const n = seleccion.size;
  return `<div class="vm-seleccion${n ? ' activa' : ''}" id="vm-seleccion" role="region" aria-label="Elegir exámenes">
    <div class="vm-seleccion-barra">
      <label class="vm-todo"><input type="checkbox" id="vm-todo" data-accion-cambio="elegirTodos"> <span id="vm-todo-texto">Elegir todos</span></label>
      <span id="vm-seleccion-n" aria-live="polite">${esc_html(n ? plural(n, 'examen elegido', 'exámenes elegidos') : '')}</span>
      <div class="vm-seleccion-acciones" id="vm-seleccion-acciones" ${n ? '' : 'hidden'}>
        <label class="vm-seleccion-mover">Mover a
          <select id="vm-mover-a" class="form-input"></select>
        </label>
        <button type="button" class="btn btn-primary btn-sm" data-accion="moverElegidos">Mover</button>
        <button type="button" class="btn btn-ghost btn-sm btn-danger-text" data-accion="borrarElegidos"><i data-lucide="trash-2" class="ico-14"></i> Borrar</button>
        <button type="button" class="btn btn-quiet btn-sm" data-accion="quitarSeleccion">Quitar selección</button>
      </div>
    </div>
  </div>`;
}

function buscador() {
  return `<div class="vm-buscar">
    <i data-lucide="search" aria-hidden="true"></i>
    <input type="search" id="vm-buscar" class="form-input" placeholder="Buscar por nombre, categoría, actividad o fecha" aria-label="Buscar en esta lista" aria-describedby="vm-cuenta" autocomplete="off" value="${esc_html(busqueda)}">
    <span id="vm-cuenta" class="vm-cuenta" aria-live="polite"></span>
  </div>`;
}

// ── Pantallas ───────────────────────────────────────────────────────────
function cabecera({ color = null, titulo, sub = '', acciones = '' }) {
  return `<header class="vm-cab">
    ${color ? `<span class="vm-cab-punto" style="background:var(${color})" aria-hidden="true"></span>` : ''}
    <div class="vm-cab-texto"><h2 id="vm-titulo" class="vm-titulo">${esc_html(titulo)}</h2>${sub ? `<p class="vm-sub">${sub}</p>` : ''}</div>
    <div class="vm-cab-acciones">${acciones}</div>
  </header>`;
}

function tarjeta(m) {
  const ultimo = m.ultimo ? ` · ${esc_html(fechaCorta(m.ultimo))}` : '';
  const detalle = [m.docente, m.grupo].filter(Boolean).map(esc_html).join(' · ');
  return `<li class="vm-tarjeta" style="--vm-color:var(${variableDeColor(m.color)})">
    <button type="button" class="vm-tarjeta-boton" data-accion="abrirMateria" data-arg-n="${m.id}" aria-label="Abrir ${esc_html(m.nombre)}: ${esc_html(plural(m.examenes, 'examen', 'exámenes'))}">
      <span class="vm-tarjeta-nombre">${esc_html(m.nombre)}</span>
      <span class="vm-tarjeta-cuenta">${esc_html(plural(m.examenes, 'examen', 'exámenes'))}${ultimo}</span>
      ${detalle ? `<span class="vm-tarjeta-detalle">${detalle}</span>` : ''}
    </button>
    <button type="button" class="btn btn-icon vm-tarjeta-editar" data-accion="editarMateria" data-arg-n="${m.id}" title="Editar «${esc_html(m.nombre)}»" aria-label="Editar la materia ${esc_html(m.nombre)}"><i data-lucide="pencil" class="ico-14"></i></button>
  </li>`;
}

function pintarRaiz() {
  const todas = materias();
  const vivas = activas(todas);
  const guardadas = archivadas(todas);
  const sin = examenesDe(examenes, null);
  let html = cabecera({
    titulo: 'Mis materias',
    sub: 'Cada materia es un espacio con todos sus exámenes. Elige una para reabrirlos, descargarlos o exportarlos en PDF.',
    acciones: `<button type="button" class="btn btn-primary btn-sm" data-accion="nuevaMateria"><i data-lucide="plus" class="ico-14"></i> Nueva materia</button>
      <button type="button" class="btn btn-ghost btn-sm" data-accion="abrirTodos"><i data-lucide="clock" class="ico-14"></i> Todos los exámenes</button>`,
  });
  html += aviso(avisoDeLimite(uso));
  if (sin.length) {
    const sugerencias = sugerirMaterias(sin, todas).grupos.length;
    html += `<div class="vm-ordenar callout">
      <i data-lucide="wand-sparkles"></i>
      <div><p><strong>${esc_html(plural(sin.length, 'examen sin materia', 'exámenes sin materia'))}</strong></p>
        <p>${sugerencias ? 'Puedo proponerte a qué materia pertenece cada uno, según su categoría y su nombre. Tú decides qué se mueve.' : 'Muévelos a una materia para conservarlos: cuando el Historial se llena, son lo primero que se borra.'}</p></div>
      ${sugerencias ? '<button type="button" class="btn btn-ghost btn-sm" data-accion="abrirAsistente">Ordenarlos con ayuda</button>' : ''}
    </div>`;
  }
  if (!vivas.length && !sin.length && !guardadas.length) {
    html += `<div class="vm-vacio">
      <i data-lucide="library" aria-hidden="true"></i>
      <p class="vm-vacio-titulo">${cargado ? 'Todavía no hay materias ni exámenes' : 'Cargando…'}</p>
      ${cargado ? '<p>Crea tu primera materia y, al convertir un examen, elígela en el paso 1: quedará guardado aquí.</p><button type="button" class="btn btn-primary btn-sm" data-accion="nuevaMateria">Crear una materia</button>' : ''}
    </div>`;
  } else {
    html += `<ul class="vm-tarjetas">${vivas.map(tarjeta).join('')}
      ${sin.length ? `<li class="vm-tarjeta vm-tarjeta-sin"><button type="button" class="vm-tarjeta-boton" data-accion="abrirSinMateria" aria-label="Abrir Sin materia: ${esc_html(plural(sin.length, 'examen', 'exámenes'))}">
        <span class="vm-tarjeta-nombre">Sin materia</span>
        <span class="vm-tarjeta-cuenta">${esc_html(plural(sin.length, 'examen', 'exámenes'))}</span>
        <span class="vm-tarjeta-detalle">Lo primero que se borra al llenarse</span></button></li>` : ''}
      <li class="vm-tarjeta vm-tarjeta-nueva"><button type="button" class="vm-tarjeta-boton" data-accion="nuevaMateria"><i data-lucide="plus" aria-hidden="true"></i><span class="vm-tarjeta-nombre">Nueva materia</span></button></li>
    </ul>`;
  }
  if (guardadas.length) {
    html += `<details class="vm-archivadas"><summary>Archivadas (${guardadas.length})</summary>
      <ul class="vm-tarjetas">${guardadas.map(tarjeta).join('')}</ul></details>`;
  }
  html += pieDeUso();
  return html;
}

function pintarLista(titulo) {
  return `${buscador()}${barraDeSeleccion()}<ul class="vm-lista" id="vm-lista" aria-label="${esc_html(titulo)}"></ul>`;
}

function pintarMateria() {
  const m = materiaPorId(sitio.materiaId);
  const partes = [plural(m.examenes, 'examen', 'exámenes'), m.docente, m.grupo, m.perfil ? `Perfil: ${m.perfil}` : ''].filter(Boolean);
  return cabecera({
    color: variableDeColor(m.color),
    titulo: m.nombre,
    sub: partes.map(esc_html).join(' · ') + (m.archivada ? ' · <strong>Archivada</strong>' : ''),
    acciones: `<button type="button" class="btn btn-primary btn-sm" data-accion="nuevoExamenEnMateria" data-arg-n="${m.id}" title="Vuelve al paso 1 con esta materia ya elegida"><i data-lucide="plus" class="ico-14"></i> Nuevo examen en esta materia</button>
      <button type="button" class="btn btn-ghost btn-sm" data-accion="editarMateria" data-arg-n="${m.id}"><i data-lucide="settings-2" class="ico-14"></i> Editar materia</button>`,
  }) + pintarLista(`Exámenes de ${m.nombre}`);
}

function pintarSin() {
  const n = examenesDe(examenes, null).length;
  return cabecera({
    titulo: 'Sin materia',
    sub: 'Los exámenes que no están en ninguna materia. Cuando el Historial se llena, estos se borran primero (los más antiguos antes).',
    acciones: n ? '<button type="button" class="btn btn-primary btn-sm" data-accion="abrirAsistente"><i data-lucide="wand-sparkles" class="ico-14"></i> Ordenarlos con ayuda</button>' : '',
  }) + aviso(avisoDeLimite(uso)) + pintarLista('Exámenes sin materia') + pieDeUso();
}

function pintarTodos() {
  return cabecera({
    titulo: 'Todos los exámenes',
    sub: 'Todo lo que has convertido, del más reciente al más antiguo.',
  }) + aviso(avisoDeLimite(uso)) + pintarLista('Todos los exámenes') + pieDeUso();
}

function pintarMigas() {
  const resto = $('vm-miga-resto');
  const actual = sitio.nivel === 'materia' ? nombreDeMateria(sitio.materiaId) : sitio.nivel === 'sin' ? 'Sin materia' : sitio.nivel === 'todos' ? 'Todos los exámenes' : '';
  resto.hidden = !actual;
  $('vm-miga-actual').textContent = actual;
  $('vm-miga-raiz').setAttribute('aria-current', actual ? 'false' : 'page');
}

function pintar() {
  if (sitio.nivel === 'materia' && !materiaPorId(sitio.materiaId)) { sitio.nivel = 'raiz'; sitio.materiaId = null; }
  const cuerpo = $('vm-cuerpo');
  cuerpo.setAttribute('aria-busy', String(!cargado));
  cuerpo.innerHTML = sitio.nivel === 'materia' ? pintarMateria() : sitio.nivel === 'sin' ? pintarSin() : sitio.nivel === 'todos' ? pintarTodos() : pintarRaiz();
  pintarMigas();
  if (sitio.nivel !== 'raiz') {
    pintarFilas();
    llenarSelectMateria($('vm-mover-a'), { valor: null, conNueva: true, etiquetaSin: 'Sin materia' });
    enlazarSelectMateria($('vm-mover-a'), () => {});
    const buscar = $('vm-buscar');
    buscar.addEventListener('input', () => { busqueda = buscar.value; pintarFilas(); });
    buscar.addEventListener('keydown', e => {
      if (e.key === 'Escape' && buscar.value) { e.preventDefault(); e.stopPropagation(); buscar.value = ''; busqueda = ''; pintarFilas(); }
    });
  }
  crearIconos(cuerpo);
}

/** Solo la lista de exámenes (al buscar o cambiar algo): así el cursor no se sale del buscador. */
function pintarFilas() {
  const lista = $('vm-lista');
  if (!lista) return;
  const base = examenesDe(examenes, sitio.nivel === 'materia' ? sitio.materiaId : sitio.nivel === 'sin' ? null : 'todos');
  const q = normalizar(busqueda.trim());
  const visibles = q ? filtrarExamenes(base, busqueda, nombreDeMateria) : base;
  $('vm-cuenta').textContent = base.length ? (q ? `${visibles.length} de ${base.length}` : plural(base.length, 'examen', 'exámenes')) : '';
  if (!visibles.length) {
    const vacio = q
      ? `<p class="vm-vacio-titulo">Sin resultados para «${esc_html(busqueda.trim())}»</p><p>Prueba con parte del nombre del archivo, la categoría, la actividad o la fecha.</p>`
      : !cargado
        ? '<p class="vm-vacio-titulo">Cargando…</p>'
        : sitio.nivel === 'materia'
          ? '<p class="vm-vacio-titulo">Esta materia todavía no tiene exámenes</p><p>Al convertir un examen, elige esta materia en el paso 1; o muévele uno desde «Sin materia» o «Todos los exámenes».</p>'
          : sitio.nivel === 'sin'
            ? '<p class="vm-vacio-titulo">Todos tus exámenes tienen materia</p>'
            : '<p class="vm-vacio-titulo">Todavía no hay conversiones guardadas</p><p>Cada examen que conviertas queda aquí para volver a descargarlo o reabrir su revisión.</p>';
    lista.innerHTML = `<li class="vm-vacio">${vacio}</li>`;
    actualizarSeleccion();
    return;
  }
  lista.innerHTML = visibles.map(e => fila(e, q, sitio.nivel !== 'materia')).join('');
  crearIconos(lista);
  actualizarSeleccion();
}

/** Los exámenes que se ven ahora en la lista (la materia o el sitio, con la búsqueda aplicada). */
function visiblesAhora() {
  const base = examenesDe(examenes, sitio.nivel === 'materia' ? sitio.materiaId : sitio.nivel === 'sin' ? null : 'todos');
  return normalizar(busqueda.trim()) ? filtrarExamenes(base, busqueda, nombreDeMateria) : base;
}

function actualizarSeleccion() {
  if (!$('vm-seleccion')) return;
  const n = seleccion.size;
  $('vm-seleccion-n').textContent = n ? plural(n, 'examen elegido', 'exámenes elegidos') : '';
  $('vm-seleccion-acciones').hidden = n === 0;
  $('vm-seleccion').classList.toggle('activa', n > 0);
  const vis = visiblesAhora();
  const marcados = vis.filter(e => seleccion.has(e.id)).length;
  const todo = $('vm-todo');
  todo.disabled = vis.length === 0;
  todo.checked = vis.length > 0 && marcados === vis.length;
  todo.indeterminate = marcados > 0 && marcados < vis.length;
  $('vm-todo-texto').textContent = busqueda.trim() ? `Elegir los ${vis.length} que se ven` : `Elegir todos (${vis.length})`;
}

/** «Elegir todos»: marca (o desmarca) todo lo que se ve en la lista, respetando la búsqueda. */
export function elegirTodos() {
  const vis = visiblesAhora();
  const todosMarcados = vis.length > 0 && vis.every(e => seleccion.has(e.id));
  vis.forEach(e => (todosMarcados ? seleccion.delete(e.id) : seleccion.add(e.id)));
  document.querySelectorAll('.vm-casilla').forEach(c => { c.checked = seleccion.has(Number(c.closest('.vm-fila').dataset.id)); });
  actualizarSeleccion();
}

/** Borra los exámenes elegidos (con confirmación que dice cuántos y qué se pierde). */
export async function borrarElegidos() {
  const ids = [...seleccion];
  if (!ids.length) return;
  const todosLosVisibles = ids.length === examenes.length;
  const ok = await confirmar({
    titulo: ids.length === 1 ? '¿Borrar este examen?' : `¿Borrar ${ids.length} exámenes?`,
    mensaje: `Se borrará${ids.length === 1 ? '' : 'n'} de este equipo ${todosLosVisibles ? 'TODO tu Historial' : plural(ids.length, 'examen', 'exámenes')}, con su XML y su revisión. Si ya los importaste en Moodle, allí no cambia nada. Esta acción no se puede deshacer.`,
    confirmar: ids.length === 1 ? 'Borrar el examen' : `Borrar ${ids.length} exámenes`,
    cancelar: 'Conservarlos',
  });
  if (!ok) return;
  const r = await llamar('/api/history/borrar', 'POST', { ids });
  if (!r.ok) { showToast(r.mensaje, 'error'); return; }
  showToast(`${plural(r.datos.borrados, 'examen borrado', 'exámenes borrados')}`, 'info');
  seleccion.clear();
  await recargar();
}

// ── Acciones sobre exámenes ─────────────────────────────────────────────
const examenPorId = id => examenes.find(e => e.id === id);

export async function reabrirExamen(id) {
  await reopenHistory(id, cerrarBiblioteca);
}

export function descargarExamen(id) {
  const e = examenPorId(id);
  if (e) downloadHistory(e.id, e.filename);
}

export function marcarExamen(id) {   // (actualizarSeleccion también deja bien la casilla «Elegir todos»)
  const casilla = document.querySelector(`.vm-fila[data-id="${id}"] .vm-casilla`);
  if (casilla && casilla.checked) seleccion.add(id); else seleccion.delete(id);
  actualizarSeleccion();
}

export function quitarSeleccion() {
  seleccion.clear();
  document.querySelectorAll('.vm-casilla').forEach(c => { c.checked = false; });
  actualizarSeleccion();
}

export function organizarExamen(id) {
  const panel = $(`vm-org-${id}`);
  const boton = document.querySelector(`.vm-fila[data-id="${id}"] .vm-organizar-boton`);
  if (!panel) return;
  const abrir = panel.hidden;
  panel.hidden = !abrir;
  boton?.setAttribute('aria-expanded', String(abrir));
  if (abrir) {
    const sel = panel.querySelector('.vm-org-materia');
    llenarSelectMateria(sel, { valor: examenPorId(id)?.materia_id ?? null, conNueva: true });
    enlazarSelectMateria(sel, () => {});
    sel.focus();
  }
}

export async function guardarOrganizar(id) {
  const panel = $(`vm-org-${id}`);
  if (!panel) return;
  const materiaId = valorDeSelect(panel.querySelector('.vm-org-materia'));
  const actividad = nombreLimpio(panel.querySelector('.vm-org-actividad').value, 160) || null;
  const r = await llamar(`/api/history/${id}`, 'PATCH', { materia_id: materiaId, actividad });
  if (!r.ok) { showToast(r.mensaje, 'error'); return; }
  showToast(materiaId == null ? 'Examen actualizado: sin materia' : `Examen guardado en «${nombreDeMateria(materiaId)}»`, 'info');
  await recargar();
}

export async function borrarExamenDeLista(id) {
  const e = examenPorId(id);
  if (!e) return;
  const ok = await confirmar({
    titulo: '¿Borrar este examen?',
    mensaje: `Se borrará «${e.filename}» de este equipo, con su XML y su revisión. Si ya lo importaste en Moodle, allí no cambia nada. Esta acción no se puede deshacer.`,
    confirmar: 'Borrar el examen',
    cancelar: 'Conservarlo',
  });
  if (!ok) return;
  if (await borrarExamen(id)) { showToast('Examen borrado', 'info'); await recargar(); }
}

export async function moverElegidos() {
  if (!seleccion.size) return;
  const sel = $('vm-mover-a');
  const destino = valorDeSelect(sel);
  const r = await llamar('/api/history/mover', 'POST', { ids: [...seleccion], materia_id: destino });
  if (!r.ok) { showToast(r.mensaje, 'error'); return; }
  showToast(`${plural(r.datos.movidos, 'examen movido', 'exámenes movidos')} a ${destino == null ? '«Sin materia»' : `«${nombreDeMateria(destino)}»`}`, 'info');
  seleccion.clear();
  await recargar();
}

// ── Acciones sobre materias ─────────────────────────────────────────────
export async function nuevaMateria() {
  const m = await abrirFormularioMateria({});
  if (m && m.id) { await recargar(); abrirMateria(m.id); }
}

export async function editarMateria(id) {
  const m = materiaPorId(id);
  if (!m) return;
  const r = await abrirFormularioMateria({ materia: m });
  if (!r) return;
  await recargar();
  if (r.borrada && sitio.materiaId === id) irA('raiz');
}

/** «Nuevo examen en esta materia»: vuelve al paso 1 con la materia ya elegida. */
export async function nuevoExamenEnMateria(id) {
  const m = materiaPorId(id);
  if (!m) return;
  if (estado.panel === 'editor') {
    const ok = await confirmar({
      titulo: '¿Empezar otro examen?',
      mensaje: 'Tienes una revisión abierta. Si empiezas otro examen se perderá la revisión actual, con todo lo que no hayas convertido a XML. Esta acción no se puede deshacer.',
      confirmar: 'Empezar otro y perder la revisión',
      cancelar: 'Seguir con mi revisión',
    });
    if (!ok) return;
    borrarBorrador();
  }
  cerrarBiblioteca();
  if (estado.panel === 'progress') {
    elegirEnPaso1(id);
    showToast(`Hay una conversión en curso. El próximo examen se guardará en «${m.nombre}».`, 'info');
    return;
  }
  resetAll();
  elegirEnPaso1(id);
  showToast(`Elige el examen: se guardará en «${m.nombre}»`, 'info');
  $('drop-zone').focus({ preventScroll: true });
}

// ── Asistente ───────────────────────────────────────────────────────────
let propuesta = { grupos: [], sinPista: [] };

export function abrirAsistente() {
  const sin = examenesDe(examenes, null);
  propuesta = sugerirMaterias(sin, materias());
  const lista = $('asi-lista');
  lista.replaceChildren(...propuesta.grupos.map((g, i) => {
    const li = document.createElement('li');
    li.className = 'asi-grupo';
    li.innerHTML = `<label class="asi-marca"><input type="checkbox" checked aria-label="Mover este grupo"></label>
      <div class="asi-datos">
        <input type="text" class="form-input asi-nombre" maxlength="80" autocomplete="off" aria-label="Materia propuesta para el grupo ${i + 1}">
        <p class="asi-detalle"></p>
      </div>`;
    li.querySelector('.asi-nombre').value = g.nombre;
    li.querySelector('.asi-detalle').textContent = `${plural(g.ids.length, 'examen', 'exámenes')} · ${g.materiaId != null ? 'ya existe esa materia' : 'materia nueva'} · ${g.ejemplos.join(', ')}`;
    return li;
  }));
  $('asi-intro').textContent = propuesta.grupos.length
    ? 'Esto es solo una propuesta, sacada de la categoría de Moodle y del nombre del archivo. Cambia el nombre de la materia o desmarca lo que no quieras mover: nada se mueve hasta que pulses el botón.'
    : 'No encontré pistas en los nombres de estos exámenes. Puedes elegirlos en «Sin materia» y moverlos a mano.';
  const sp = $('asi-sin-pista');
  sp.hidden = !propuesta.sinPista.length;
  sp.textContent = propuesta.sinPista.length ? `${plural(propuesta.sinPista.length, 'examen no tiene', 'exámenes no tienen')} pista en su nombre: se quedan en «Sin materia».` : '';
  $('asi-error').hidden = true;
  $('btn-asi-aplicar').disabled = !propuesta.grupos.length;
  abrirModal($('modal-asistente'), { foco: $('btn-asi-aplicar') });
}

async function aplicarAsistente() {
  const marcados = [...$('asi-lista').children].map(li => ({ marcado: li.querySelector('input[type="checkbox"]').checked, nombre: li.querySelector('.asi-nombre').value }));
  const plan = planDelAsistente(propuesta.grupos, marcados);
  const err = $('asi-error');
  if (!plan.length) { err.textContent = 'No hay nada marcado para mover.'; err.hidden = false; return; }
  $('btn-asi-aplicar').disabled = true;
  err.hidden = true;
  let movidos = 0;
  const usadas = new Set();
  try {
    for (const p of plan) {
      const m = p.materiaId != null ? materiaPorId(p.materiaId) : await crearOEncontrarMateria(p.nombre);
      if (!m) throw new Error(`No se pudo crear la materia «${p.nombre}».`);
      const r = await llamar('/api/history/mover', 'POST', { ids: p.ids, materia_id: m.id });
      if (!r.ok) throw new Error(r.mensaje);
      movidos += r.datos.movidos;
      usadas.add(m.id);
    }
  } catch (e) {
    err.textContent = e.message || 'No se pudo mover todo. Inténtalo de nuevo.';
    err.hidden = false;
    $('btn-asi-aplicar').disabled = false;
    await recargar();
    return;
  }
  cerrarModal($('modal-asistente'));
  showToast(`${plural(movidos, 'examen movido', 'exámenes movidos')} a ${plural(usadas.size, 'materia', 'materias')}`);
  await recargar();
}

// ── Arranque ────────────────────────────────────────────────────────────
export function iniciarBiblioteca() {
  $('btn-materias').addEventListener('click', () => abrirBiblioteca());
  $('btn-vm-cerrar').addEventListener('click', cerrarBiblioteca);
  $('btn-asi-cerrar').addEventListener('click', () => cerrarModal($('modal-asistente')));
  $('btn-asi-cancelar').addEventListener('click', () => cerrarModal($('modal-asistente')));
  $('btn-asi-aplicar').addEventListener('click', aplicarAsistente);
  $('modal-asistente').addEventListener('click', e => { if (e.target === $('modal-asistente')) cerrarModal($('modal-asistente')); });
}
