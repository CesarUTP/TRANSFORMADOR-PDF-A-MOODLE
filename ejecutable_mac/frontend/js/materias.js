/**
 * materias.js — las materias del docente (Mis materias): la lista que se comparte entre pantallas, el
 * selector «Materia» (paso 1, pantalla final y diálogo del PDF) y la ventana para crear o editar una.
 * La pantalla de la biblioteca vive en biblioteca.js.
 */
import { apiFetch } from './api.js';
import { estado } from './estado.js';
import { confirmar } from './ui/confirmar.js';
import { abrirModal, cerrarModal } from './ui/modales.js';
import { ACTIVIDADES } from './ui/exportar-pdf-logica.js';
import { showToast } from './ui/toast.js';
import { crearIconos, detalleDeError, friendlyHttpError } from './util.js';
import { COLORES, LIMITE_CAMPO, LIMITE_NOMBRE, activas, avisoDeLimite, existeNombre, nombreLimpio, ordenarMaterias, plural, variableDeColor } from './materias-logica.js';

const $ = id => document.getElementById(id);
const NUEVA = '__nueva__';
const CLAVE_ULTIMA = 'conversor.materia';

/** Las materias tal como las dio el servidor (con examenes, bytes y ultimo). */
let lista = [];
const oyentes = new Set();

export function materias() { return lista; }
export function materiaPorId(id) { return id == null ? null : lista.find(m => m.id === Number(id)) || null; }
export function nombreDeMateria(id) { return (materiaPorId(id) || {}).nombre || ''; }

/** Avisa cuando la lista cambia (la biblioteca y los selectores se redibujan). */
export function alCambiarMaterias(fn) { oyentes.add(fn); return () => oyentes.delete(fn); }

function avisar() {
  for (const fn of oyentes) {
    try { fn(lista); } catch (err) { console.error('Un oyente de materias falló:', err); }
  }
}

/** Pide la lista al servidor. Si falla deja la que había y devuelve null (la app sigue sin materias). */
export async function cargarMaterias() {
  try {
    const res = await apiFetch('/api/materias');
    if (!res.ok) return null;
    lista = ordenarMaterias(await res.json());
    avisar();
    return lista;
  } catch (_) {
    return null;
  }
}

async function mensajeDe(res, respaldo) {
  let msg = friendlyHttpError(res.status);
  try { msg = detalleDeError((await res.json()).detail, msg); } catch (_) { /* se queda el genérico */ }
  return typeof msg === 'string' && msg ? msg : respaldo;
}

/** Llamada que cambia algo: devuelve { ok, datos } o { ok: false, mensaje, estado }. */
export async function llamar(url, metodo, cuerpo) {
  try {
    const res = await apiFetch(url, {
      method: metodo,
      ...(cuerpo !== undefined ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo) } : {}),
    });
    if (!res.ok) return { ok: false, estado: res.status, mensaje: await mensajeDe(res, 'No se pudo completar. Inténtalo de nuevo.') };
    return { ok: true, datos: await res.json().catch(() => ({})) };
  } catch (_) {
    return { ok: false, estado: 0, mensaje: 'No se pudo conectar con la aplicación. Inténtalo de nuevo.' };
  }
}

// ── Lo último que se eligió ─────────────────────────────────────────────
export function materiaRecordada() {
  try {
    const id = Number(localStorage.getItem(CLAVE_ULTIMA));
    return Number.isInteger(id) && materiaPorId(id) && !materiaPorId(id).archivada ? id : null;
  } catch (_) { return null; }
}

export function recordarMateria(id) {
  try {
    if (id == null) localStorage.removeItem(CLAVE_ULTIMA);
    else localStorage.setItem(CLAVE_ULTIMA, String(id));
  } catch (_) { /* sin almacenamiento: no se recuerda */ }
}

// ── Selector de materia ─────────────────────────────────────────────────
const opcion = (valor, texto) => Object.assign(document.createElement('option'), { value: valor, textContent: texto });

/**
 * Rellena un <select> con «Sin materia», las materias activas (y la archivada que ya estaba elegida) y,
 * si `conNueva`, «Nueva materia…». `valor`: id elegido (null = sin materia).
 */
export function llenarSelectMateria(sel, { valor = null, conNueva = true, etiquetaSin = 'Sin materia' } = {}) {
  const elegida = materiaPorId(valor);
  const visibles = [...activas(lista), ...(elegida && elegida.archivada ? [elegida] : [])];
  sel.replaceChildren(
    opcion('', etiquetaSin),
    ...visibles.map(m => opcion(String(m.id), m.archivada ? `${m.nombre} (archivada)` : m.nombre)),
    ...(conNueva ? [opcion(NUEVA, '＋ Nueva materia…')] : []),
  );
  sel.value = elegida ? String(elegida.id) : '';
}

/** El id elegido en un selector (null = sin materia; NUEVA no cuenta). */
export function valorDeSelect(sel) {
  const n = Number(sel.value);
  return sel.value && sel.value !== NUEVA && Number.isInteger(n) ? n : null;
}

/**
 * Hace que elegir «Nueva materia…» abra la ventana de crear y deje elegida la nueva (o devuelva el
 * selector a lo que tenía si se cancela). `alElegir(id|null)` se llama con cada elección real.
 */
export function enlazarSelectMateria(sel, alElegir) {
  if (sel.dataset.enlazado) return; // un selector se enlaza una sola vez
  sel.dataset.enlazado = '1';
  let previo = sel.value;
  sel.addEventListener('change', async () => {
    if (sel.value !== NUEVA) { previo = sel.value; alElegir(valorDeSelect(sel)); return; }
    const nueva = await abrirFormularioMateria({});
    llenarSelectMateria(sel, { valor: nueva ? nueva.id : (previo ? Number(previo) : null), conNueva: sel.dataset.sinNueva !== '1' });
    previo = sel.value;
    alElegir(valorDeSelect(sel));
  });
}

// ── Crear o editar una materia ──────────────────────────────────────────
let formulario = null; // { materia, resolver }
let nombresPerfiles = [];

function pintarColores(elegido) {
  const fila = $('mat-colores');
  fila.replaceChildren(...COLORES.map(c => {
    const etiqueta = document.createElement('label');
    etiqueta.className = 'mat-color';
    etiqueta.title = c.etiqueta;
    const radio = Object.assign(document.createElement('input'), { type: 'radio', name: 'mat-color', value: c.id, checked: c.id === elegido });
    radio.setAttribute('aria-label', c.etiqueta);
    const punto = document.createElement('span');
    punto.style.background = `var(${c.variable})`;
    etiqueta.append(radio, punto);
    return etiqueta;
  }));
}

async function llenarPerfiles(elegido) {
  const sel = $('mat-perfil');
  try {
    const res = await apiFetch('/api/perfiles_pdf');
    nombresPerfiles = res.ok ? (await res.json()).map(p => p.nombre) : [];
  } catch (_) { nombresPerfiles = []; }
  const nombres = elegido && !nombresPerfiles.includes(elegido) ? [...nombresPerfiles, elegido] : nombresPerfiles;
  sel.replaceChildren(opcion('', 'Ninguno'), ...nombres.map(n => opcion(n, nombresPerfiles.includes(n) ? n : `${n} (ya no existe)`)));
  sel.value = elegido || '';
  resumirDefectos();
}

function resumirDefectos() {
  const partes = [$('mat-perfil').value, $('mat-docente').value.trim(), $('mat-grupo').value.trim()].filter(Boolean);
  $('mat-resumen-defectos').textContent = partes.length ? partes.join(' · ') : 'Ninguno';
}

function errorDeFormulario(texto) {
  const el = $('mat-error');
  el.textContent = texto || '';
  el.hidden = !texto;
}

function cerrarFormulario(resultado) {
  if (!formulario) return;
  const { resolver } = formulario;
  formulario = null;
  cerrarModal($('modal-materia'));
  resolver(resultado);
}

/**
 * Abre la ventana de crear (sin `materia`) o editar una materia. Devuelve una promesa con la materia
 * guardada, o null si se cancela. `{ borrada: true }` si se borró (solo editando).
 */
export function abrirFormularioMateria({ materia = null, nombreInicial = '' } = {}) {
  if (formulario) cerrarFormulario(null);
  return new Promise(resolver => {
    formulario = { materia, resolver };
    const edita = !!materia;
    $('mat-titulo-texto').textContent = edita ? 'Editar materia' : 'Nueva materia';
    $('mat-nombre').value = edita ? materia.nombre : nombreInicial;
    $('mat-docente').value = edita ? materia.docente || '' : '';
    $('mat-grupo').value = edita ? materia.grupo || '' : '';
    $('mat-defectos').open = edita && !!(materia.perfil || materia.docente || materia.grupo);
    pintarColores(edita ? materia.color : COLORES[lista.length % COLORES.length].id);
    llenarPerfiles(edita ? materia.perfil : '');
    errorDeFormulario('');
    $('btn-mat-guardar').disabled = false;
    $('btn-mat-borrar').hidden = !edita;
    const arch = $('btn-mat-archivar');
    arch.hidden = !edita;
    if (edita) arch.textContent = materia.archivada ? 'Volver a activarla' : 'Archivar';
    abrirModal($('modal-materia'), { foco: $('mat-nombre'), onClose: () => { if (formulario) cerrarFormulario(null); } });
  });
}

async function guardarFormulario(e) {
  e.preventDefault();
  if (!formulario) return;
  const nombre = nombreLimpio($('mat-nombre').value, LIMITE_NOMBRE);
  if (!nombre) { errorDeFormulario('Escribe el nombre de la materia.'); $('mat-nombre').focus(); return; }
  const { materia } = formulario;
  if (existeNombre(lista, nombre, materia ? materia.id : null)) { errorDeFormulario('Ya tienes una materia con ese nombre.'); $('mat-nombre').focus(); return; }
  const cuerpo = {
    nombre,
    color: (document.querySelector('input[name="mat-color"]:checked') || {}).value || 'azul',
    perfil: $('mat-perfil').value || null,
    docente: nombreLimpio($('mat-docente').value, LIMITE_CAMPO) || null,
    grupo: nombreLimpio($('mat-grupo').value, LIMITE_CAMPO) || null,
  };
  $('btn-mat-guardar').disabled = true;
  const r = materia ? await llamar(`/api/materias/${materia.id}`, 'PATCH', cuerpo) : await llamar('/api/materias', 'POST', cuerpo);
  $('btn-mat-guardar').disabled = false;
  if (!r.ok) { errorDeFormulario(r.mensaje); return; }
  await cargarMaterias();
  showToast(materia ? `Materia «${r.datos.nombre}» actualizada` : `Materia «${r.datos.nombre}» creada`);
  cerrarFormulario(r.datos);
}

async function archivarDesdeFormulario() {
  const { materia } = formulario || {};
  if (!materia) return;
  const r = await llamar(`/api/materias/${materia.id}`, 'PATCH', { archivada: !materia.archivada });
  if (!r.ok) { errorDeFormulario(r.mensaje); return; }
  await cargarMaterias();
  showToast(materia.archivada ? `«${materia.nombre}» vuelve a estar activa` : `«${materia.nombre}» archivada: sus exámenes se conservan`, 'info');
  cerrarFormulario(r.datos);
}

async function borrarDesdeFormulario() {
  const { materia } = formulario || {};
  if (!materia) return;
  const n = (materiaPorId(materia.id) || materia).examenes || 0;
  const ok = await confirmar({
    titulo: '¿Borrar esta materia?',
    mensaje: n
      ? `Se borrará la materia «${materia.nombre}». Sus ${plural(n, 'examen', 'exámenes')} NO se borran: pasan a «Sin materia», y ahí son lo primero que se borra cuando el Historial se llena.`
      : `Se borrará la materia «${materia.nombre}». No tiene exámenes.`,
    confirmar: 'Borrar la materia',
    cancelar: 'Conservarla',
  });
  if (!ok || !formulario) return;
  const r = await llamar(`/api/materias/${materia.id}`, 'DELETE');
  if (!r.ok) { errorDeFormulario(r.mensaje); return; }
  await cargarMaterias();
  showToast(`Materia «${materia.nombre}» borrada`, 'info');
  cerrarFormulario({ borrada: true, id: materia.id });
}

/** Una materia nueva desde el asistente o desde un nombre escrito: si ya existe, devuelve esa. */
export async function crearOEncontrarMateria(nombre) {
  const limpio = nombreLimpio(nombre, LIMITE_NOMBRE);
  if (!limpio) return null;
  const hay = lista.find(m => existeNombre([m], limpio));
  if (hay) return hay;
  const r = await llamar('/api/materias', 'POST', { nombre: limpio, color: COLORES[lista.length % COLORES.length].id });
  if (!r.ok) return null;
  await cargarMaterias();
  return r.datos;
}

export { variableDeColor };

// ── Paso 1 (cargar el examen) y pantalla final ──────────────────────────
/** La materia y la actividad elegidas en el paso 1: lo que se guarda junto al examen. */
export function leerPaso1() {
  return {
    materia_id: valorDeSelect($('materia-select')),
    actividad: nombreLimpio($('actividad-input').value, LIMITE_CAMPO) || null,
  };
}

/** Deja elegida una materia en el paso 1 (con la lista al día). */
export function elegirEnPaso1(id) {
  llenarSelectMateria($('materia-select'), { valor: id });
  recordarMateria(valorDeSelect($('materia-select')));
}

/** Un examen nuevo: la actividad no se arrastra del anterior (la materia sí: se suele convertir varios seguidos). */
export function reiniciarPaso1() {
  $('actividad-input').value = '';
}

function redibujarPaso1() {
  const sel = $('materia-select');
  llenarSelectMateria(sel, { valor: valorDeSelect(sel) ?? materiaRecordada() });
}

/** Pantalla final: en qué materia quedó guardado el examen (se puede cambiar) y el aviso si el Historial se llena. */
export async function mostrarExito(historialId, materiaId) {
  const caja = $('exito-materia');
  const sel = $('exito-materia-sel');
  const aviso = $('exito-uso');
  estado.historialId = Number.isInteger(historialId) ? historialId : null;
  caja.hidden = estado.historialId === null;
  aviso.hidden = true;
  if (estado.historialId === null) return;
  llenarSelectMateria(sel, { valor: materiaId });
  try {
    const res = await apiFetch('/api/history/uso');
    const uso = res.ok ? await res.json() : null;
    const a = avisoDeLimite(uso);
    if (a) {
      aviso.innerHTML = `<i data-lucide="alert-triangle"></i><div style="min-width:0;"><p style="font-weight:700;margin:0 0 4px;"></p><p></p></div>`;
      aviso.querySelector('p').textContent = a.titulo;
      aviso.querySelectorAll('p')[1].textContent = a.texto;
      aviso.hidden = false;
      crearIconos(aviso);
    }
  } catch (_) { /* el aviso es un extra: sin él no pasa nada */ }
}

async function cambiarMateriaDeExito(id) {
  if (estado.historialId == null) return;
  const r = await llamar(`/api/history/${estado.historialId}`, 'PATCH', { materia_id: id });
  const sel = $('exito-materia-sel');
  if (!r.ok) {
    showToast(r.mensaje, 'error');
    llenarSelectMateria(sel, { valor: estado.currentUploadMetadata ? estado.currentUploadMetadata.materia_id : null });
    return;
  }
  if (estado.currentUploadMetadata) estado.currentUploadMetadata.materia_id = id;
  if (estado.exportable) estado.exportable.materia_id = id;
  await cargarMaterias();
  showToast(id == null ? 'El examen quedó sin materia' : `Guardado en «${nombreDeMateria(id)}»`, 'info');
}

export function iniciarMaterias() {
  $('actividades-lista').replaceChildren(...ACTIVIDADES.map(a => Object.assign(document.createElement('option'), { value: a })));
  $('mat-form').addEventListener('submit', guardarFormulario);
  $('mat-form').addEventListener('input', resumirDefectos);
  $('mat-form').addEventListener('change', resumirDefectos);
  $('btn-mat-cancelar').addEventListener('click', () => cerrarFormulario(null));
  $('btn-mat-cerrar').addEventListener('click', () => cerrarFormulario(null));
  $('btn-mat-archivar').addEventListener('click', archivarDesdeFormulario);
  $('btn-mat-borrar').addEventListener('click', borrarDesdeFormulario);
  $('modal-materia').addEventListener('click', e => { if (e.target === $('modal-materia')) cerrarFormulario(null); });
  crearIconos($('modal-materia'));
  // Paso 1 y pantalla final.
  llenarSelectMateria($('materia-select'));
  enlazarSelectMateria($('materia-select'), id => recordarMateria(id));
  enlazarSelectMateria($('exito-materia-sel'), cambiarMateriaDeExito);
  alCambiarMaterias(redibujarPaso1);
  cargarMaterias().then(() => { if (lista.length) elegirEnPaso1(materiaRecordada()); });
}
