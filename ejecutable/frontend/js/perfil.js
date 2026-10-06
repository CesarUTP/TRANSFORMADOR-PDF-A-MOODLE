/**
 * perfil.js — «Mi perfil»: los datos del docente (nombre y cómo se le llama) y sus perfiles de encabezado
 * (institución, logos, indicaciones y formato de impresión), en una pantalla propia. Lo que se guarda aquí lo usa
 * el diálogo «Exportar examen en PDF» para empezar con todo ya puesto.
 *
 * Los datos viven en el servidor local: /api/yo (nombre, rótulo, perfil predeterminado) y /api/perfiles_pdf.
 */
import { apiFetch } from './api.js';
import { cargarMaterias, llamar, materias } from './materias.js';
import { crearIconos, esc_html } from './util.js';
import { confirmar } from './ui/confirmar.js';
import { ROTULOS_NOMBRES, RENGLONES_MAX, RENGLONES_MIN, cuerpoPdf, datosDePerfil, enteroEn, logoValido, nombrePerfil, tamanoValido } from './ui/exportar-pdf-logica.js';
import { MENSAJE_LOGO_INVALIDO, logoArchivoValido, reducirLogo } from './ui/logo-imagen.js';
import { abrirModal, cerrarModal } from './ui/modales.js';
import { showToast } from './ui/toast.js';
import { ejemploExamen, iniciales, materiasQueUsan, nombreCopia, nombreOcupado, ordenarPerfiles, resumenEncabezado, resumenFormato } from './perfil-logica.js';

const $ = id => document.getElementById(id);
const vistaEl = $('vista-perfil');
const editorEl = $('modal-perfil-enc');
const LADOS = { logo_izquierdo: 'izq', logo_derecho: 'der' };

let yoDatos = { nombre: '', rotulo_docente: 'facilitador', perfil_predeterminado: null };
let perfiles = [];
const oyentes = new Set();

/** Lo que se sabe del docente: { nombre, rotulo_docente, perfil_predeterminado }. */
export function datosDelDocente() { return { ...yoDatos }; }
/** Los perfiles de encabezado guardados: [{ nombre, datos }]. */
export function perfilesGuardados() { return perfiles; }
/** El perfil de encabezado predeterminado (o null). */
export function perfilPredeterminado() { return perfiles.find(p => p.nombre === yoDatos.perfil_predeterminado) || null; }
/** Avisa cuando cambian los datos del docente o sus perfiles. */
export function alCambiarPerfil(fn) { oyentes.add(fn); return () => oyentes.delete(fn); }

function avisar() {
  for (const fn of oyentes) {
    try { fn(); } catch (err) { console.error('Un oyente de perfil falló:', err); }
  }
}

export async function cargarYo() {
  try {
    const res = await apiFetch('/api/yo');
    if (res.ok) yoDatos = { ...yoDatos, ...(await res.json()) };
  } catch (_) { /* se queda lo que había */ }
  pintarAvatar();
  return yoDatos;
}

export async function cargarPerfilesGuardados() {
  try {
    const res = await apiFetch('/api/perfiles_pdf');
    if (res.ok) perfiles = await res.json();
  } catch (_) { /* se queda lo que había */ }
  return perfiles;
}

async function recargarTodo() {
  await Promise.all([cargarYo(), cargarPerfilesGuardados()]);
  pintar();
  avisar();
}

// ── Avatar de la cabecera ───────────────────────────────────────────────
function pintarAvatar() {
  const ini = iniciales(yoDatos.nombre);
  $('avatar-iniciales').textContent = ini;
  $('avatar-iniciales').hidden = !ini;
  $('avatar-icono').style.display = ini ? 'none' : '';
  $('vp-avatar').textContent = ini || '?';
  $('btn-perfil').title = yoDatos.nombre ? `Mi perfil: ${yoDatos.nombre}` : 'Mi perfil';
}

// ── La pantalla ─────────────────────────────────────────────────────────
export async function abrirPerfil() {
  if (vistaEl.classList.contains('open')) return;
  pintar();
  abrirModal(vistaEl, { foco: $('vp-cuerpo') });
  await recargarTodo();
  $('vp-cuerpo').focus({ preventScroll: true });
}

export function cerrarPerfil() { cerrarModal(vistaEl); }

function ejemploRotulo() {
  const r = ROTULOS_NOMBRES[$('vp-rotulo').value] || 'FACILITADOR';
  $('vp-ejemplo').textContent = `${r}: ${$('vp-nombre').value.trim() || 'Ing. Ana Pérez'}`;
}

function thumb(b64, alt) {
  return logoValido(b64) ? `<img src="data:image/png;base64,${b64}" alt="${esc_html(alt)}">` : '';
}

function tarjeta(p, predeterminado, usan) {
  const d = p.datos || {};
  const logos = thumb(d.logo_izquierdo, 'Logo izquierdo') + thumb(d.logo_derecho, 'Logo derecho');
  const esPred = p.nombre === predeterminado;
  const n = esc_html(p.nombre);
  return `<li class="vp-perfil${esPred ? ' es-predeterminado' : ''}">
    <div class="vp-perfil-cab">
      ${logos ? `<span class="vp-perfil-logos">${logos}</span>` : '<span class="vp-perfil-logos vacio"><i data-lucide="image" class="ico-16" aria-hidden="true"></i></span>'}
      <div class="vp-perfil-titulo">
        <strong>${n}</strong>
        ${esPred ? '<span class="vm-chip">Predeterminado</span>' : ''}
      </div>
    </div>
    <p class="vp-perfil-linea">${esc_html(resumenEncabezado(d))}</p>
    <p class="vp-perfil-linea vp-perfil-formato">${esc_html(resumenFormato(d))}</p>
    ${usan.length ? `<p class="vp-perfil-linea vp-perfil-formato">Lo usa${usan.length === 1 ? '' : 'n'} ${esc_html(usan.map(m => m.nombre).slice(0, 3).join(', '))}${usan.length > 3 ? ` y ${usan.length - 3} más` : ''}</p>` : ''}
    <div class="vp-perfil-acciones">
      <button type="button" class="btn btn-ghost btn-sm" data-accion="editarPerfilEnc" data-arg="${n}"><i data-lucide="pencil" class="ico-14"></i> Editar</button>
      <button type="button" class="btn btn-ghost btn-sm" data-accion="duplicarPerfilEnc" data-arg="${n}"><i data-lucide="copy" class="ico-14"></i> Duplicar</button>
      <button type="button" class="btn btn-ghost btn-sm" data-accion="predeterminadoPerfilEnc" data-arg="${n}" aria-pressed="${esPred}"><i data-lucide="${esPred ? 'star-off' : 'star'}" class="ico-14"></i> ${esPred ? 'Quitar por defecto' : 'Usar por defecto'}</button>
      <button type="button" class="btn btn-quiet btn-danger-text btn-sm" data-accion="borrarPerfilEnc" data-arg="${n}" aria-label="Borrar el perfil ${n}"><i data-lucide="trash-2" class="ico-14"></i></button>
    </div>
  </li>`;
}

function pintar() {
  pintarAvatar();
  if (document.activeElement !== $('vp-nombre')) $('vp-nombre').value = yoDatos.nombre || '';
  $('vp-rotulo').value = yoDatos.rotulo_docente || 'facilitador';
  ejemploRotulo();
  const lista = ordenarPerfiles(perfiles, yoDatos.perfil_predeterminado);
  const ul = $('vp-perfiles');
  if (!lista.length) {
    ul.innerHTML = `<li class="vm-vacio vp-vacio">
      <i data-lucide="file-text" aria-hidden="true"></i>
      <p class="vm-vacio-titulo">Todavía no tienes perfiles de encabezado</p>
      <p>Un perfil guarda tu institución, tus logos, las indicaciones generales y el formato de impresión. Créalo una vez y cada PDF empieza con todo puesto.</p>
      <button type="button" class="btn btn-primary btn-sm" data-accion="nuevoPerfilEnc">Crear mi primer perfil</button>
    </li>`;
  } else {
    const todas = materias();
    ul.innerHTML = lista.map(p => tarjeta(p, yoDatos.perfil_predeterminado, materiasQueUsan(todas, p.nombre))).join('');
  }
  crearIconos(vistaEl);
}

async function guardarDatos(e) {
  e.preventDefault();
  const boton = $('btn-vp-guardar');
  boton.disabled = true;
  const r = await llamar('/api/yo', 'PUT', { nombre: $('vp-nombre').value, rotulo_docente: $('vp-rotulo').value });
  boton.disabled = false;
  if (!r.ok) { showToast(r.mensaje, 'error'); return; }
  yoDatos = { ...yoDatos, ...r.datos };
  pintar();
  avisar();
  showToast('Tus datos quedaron guardados');
}

// ── Acciones sobre un perfil ────────────────────────────────────────────
const porNombre = nombre => perfiles.find(p => p.nombre === nombre);

export function nuevoPerfilEnc() { abrirEditor(null); }
export function editarPerfilEnc(nombre) { if (porNombre(nombre)) abrirEditor(nombre); }

export async function duplicarPerfilEnc(nombre) {
  const p = porNombre(nombre);
  if (!p) return;
  const copia = nombreCopia(nombre, perfiles.map(x => x.nombre));
  const r = await llamar(`/api/perfiles_pdf/${encodeURIComponent(copia)}`, 'PUT', p.datos);
  if (!r.ok) { showToast(r.mensaje, 'error'); return; }
  await recargarTodo();
  showToast(`Copia guardada como «${copia}»`);
}

export async function predeterminadoPerfilEnc(nombre) {
  const quitar = yoDatos.perfil_predeterminado === nombre;
  const r = await llamar('/api/yo', 'PUT', { perfil_predeterminado: quitar ? null : nombre });
  if (!r.ok) { showToast(r.mensaje, 'error'); return; }
  yoDatos = { ...yoDatos, ...r.datos };
  pintar();
  avisar();
  showToast(quitar ? `«${nombre}» ya no es el predeterminado` : `«${nombre}» se usará por defecto al exportar`, 'info');
}

export async function borrarPerfilEnc(nombre) {
  const usan = materiasQueUsan(materias(), nombre);
  const ok = await confirmar({
    titulo: '¿Borrar este perfil?',
    mensaje: `Se borrará el perfil «${nombre}».${usan.length ? ` ${usan.length === 1 ? 'La materia' : 'Las materias'} ${usan.map(m => `«${m.nombre}»`).join(', ')} se quedará${usan.length === 1 ? '' : 'n'} sin perfil por defecto.` : ''} Los PDF que ya exportaste no cambian.`,
    confirmar: 'Borrar el perfil',
    cancelar: 'Conservarlo',
  });
  if (!ok) return;
  const r = await llamar(`/api/perfiles_pdf/${encodeURIComponent(nombre)}`, 'DELETE');
  if (!r.ok && r.estado !== 404) { showToast(r.mensaje, 'error'); return; }
  await recargarTodo();
  await cargarMaterias();
  pintar();
  showToast(`Perfil «${nombre}» borrado`, 'info');
}

// ── El editor de un perfil ──────────────────────────────────────────────
let editando = null;       // nombre del perfil que se edita (null: uno nuevo)
const logosEd = { logo_izquierdo: '', logo_derecho: '' };
const vista = { abierta: false, temporizador: null, controlador: null, url: null };

function mostrarLogo(clave, b64) {
  const lado = LADOS[clave];
  logosEd[clave] = b64 || '';
  const img = $(`pe-logo-${lado}-vista`);
  if (b64) img.src = `data:image/png;base64,${b64}`; else img.removeAttribute('src');
  $(`pe-logo-${lado}-caja`).classList.toggle('con-logo', !!b64);
  $(`pe-logo-${lado}-quitar`).hidden = !b64;
  $(`pe-logo-${lado}-archivo`).value = '';
}

function errorEditor(texto) {
  $('pe-error').textContent = texto || '';
  $('pe-error').hidden = !texto;
}

function llenarEditor(nombre, d) {
  $('pe-nombre').value = nombre;
  ['institucion', 'facultad', 'departamento', 'instrucciones'].forEach(k => { $(`pe-${k}`).value = d[k] || ''; });
  $('pe-papel').value = d.papel; $('pe-margenes').value = d.margenes;
  $('pe-fuente-titulos').value = d.fuente_titulos; $('pe-tam-titulos').value = d.tam_titulos;
  $('pe-fuente-preguntas').value = d.fuente_preguntas; $('pe-tam-preguntas').value = d.tam_preguntas;
  $('pe-renglones').value = d.renglones_ensayo;
  $('pe-mezclar').checked = d.mezclar; $('pe-partes').checked = d.partes;
  $('pe-puntos').checked = d.puntos_por_pregunta; $('pe-campos').checked = d.campos_estudiante;
  Object.keys(LADOS).forEach(k => mostrarLogo(k, d[k]));
}

/** Lo escrito en el editor, sin validar (datosDePerfil lo valida campo por campo). */
function leerEditor() {
  return {
    institucion: $('pe-institucion').value, facultad: $('pe-facultad').value, departamento: $('pe-departamento').value,
    instrucciones: $('pe-instrucciones').value, papel: $('pe-papel').value, margenes: $('pe-margenes').value,
    fuente_titulos: $('pe-fuente-titulos').value, tam_titulos: $('pe-tam-titulos').value,
    fuente_preguntas: $('pe-fuente-preguntas').value, tam_preguntas: $('pe-tam-preguntas').value,
    renglones_ensayo: $('pe-renglones').value, mezclar: $('pe-mezclar').checked, partes: $('pe-partes').checked,
    puntos_por_pregunta: $('pe-puntos').checked, campos_estudiante: $('pe-campos').checked,
    ...logosEd,
  };
}

function problemaDelEditor(d) {
  if (tamanoValido(d.tam_titulos) === null || tamanoValido(d.tam_preguntas) === null) return 'El tamaño de la letra debe estar entre 7 y 20 puntos.';
  if (enteroEn(d.renglones_ensayo, RENGLONES_MIN, RENGLONES_MAX) === null) return `Los renglones por ensayo deben ser un número entero entre ${RENGLONES_MIN} y ${RENGLONES_MAX}.`;
  return '';
}

function abrirEditor(nombre) {
  editando = nombre;
  const existente = nombre ? porNombre(nombre) : null;
  $('pe-titulo-texto').textContent = existente ? 'Editar perfil de encabezado' : 'Nuevo perfil de encabezado';
  // Un perfil nuevo empieza con el formato de siempre; el predeterminado actual no se copia sin querer.
  llenarEditor(existente ? existente.nombre : '', datosDePerfil(existente ? existente.datos : null));
  // El primer perfil que se crea queda como predeterminado (es el que se va a querer casi siempre).
  $('pe-predeterminado').checked = existente ? yoDatos.perfil_predeterminado === existente.nombre : perfiles.length === 0;
  $('btn-pe-guardar').disabled = false;
  errorEditor('');
  $('pe-sec-formato').open = false;
  actualizarResumen();
  alternarVista(window.innerWidth >= 1100);
  abrirModal(editorEl, { foco: $('pe-nombre'), onClose: cerrarEditorLimpio });
}

function cerrarEditorLimpio() {
  detenerVista();
  soltarImagen();
  vista.abierta = false;
  $('pe-vista').hidden = true;
  $('pe-caja').classList.remove('modal-pdf-ancho');
}

function actualizarResumen() {
  $('pe-resumen-formato').textContent = resumenFormato(datosDePerfil(leerEditor()));
}

async function guardarEditor(e) {
  e.preventDefault();
  const crudo = leerEditor();
  const nombre = nombrePerfil($('pe-nombre').value);
  if (!nombre) { errorEditor('Escribe un nombre para el perfil.'); $('pe-nombre').focus(); return; }
  if (nombreOcupado(nombre, perfiles.map(p => p.nombre), editando)) { errorEditor('Ya tienes un perfil con ese nombre.'); $('pe-nombre').focus(); return; }
  const problema = problemaDelEditor(crudo);
  if (problema) { errorEditor(problema); return; }
  errorEditor('');
  $('btn-pe-guardar').disabled = true;
  try {
    if (editando && editando !== nombre) {
      const rn = await llamar(`/api/perfiles_pdf/${encodeURIComponent(editando)}/renombrar`, 'POST', { nuevo: nombre });
      if (!rn.ok) { errorEditor(rn.mensaje); return; }
    }
    // Lo que el editor no muestra (el nombre del docente que traían los perfiles de antes) se conserva.
    const base = editando && porNombre(editando) ? porNombre(editando).datos : null;
    const cuerpo = datosDePerfil({ ...(base || {}), ...crudo });
    const r = await llamar(`/api/perfiles_pdf/${encodeURIComponent(nombre)}`, 'PUT', cuerpo);
    if (!r.ok) { errorEditor(r.mensaje); return; }
    const eraPred = yoDatos.perfil_predeterminado === editando || yoDatos.perfil_predeterminado === nombre;
    const quiere = $('pe-predeterminado').checked;
    if (quiere || eraPred) {
      const ry = await llamar('/api/yo', 'PUT', { perfil_predeterminado: quiere ? nombre : null });
      if (!ry.ok) { errorEditor(ry.mensaje); return; }
    }
    cerrarModal(editorEl);
    await recargarTodo();
    await cargarMaterias();
    pintar();
    showToast(`Perfil «${nombre}» guardado`);
  } finally {
    $('btn-pe-guardar').disabled = false;
  }
}

// ── Vista previa del encabezado ─────────────────────────────────────────
function detenerVista() {
  clearTimeout(vista.temporizador);
  if (vista.controlador) vista.controlador.abort();
  vista.controlador = null;
}

function soltarImagen() {
  if (vista.url) URL.revokeObjectURL(vista.url);
  vista.url = null;
  $('pe-vista-img').removeAttribute('src');
  $('pe-vista-img').hidden = true;
}

async function refrescarVista() {
  detenerVista();
  const crudo = leerEditor();
  const estadoEl = $('pe-vista-estado');
  const marco = document.querySelector('#pe-vista .pdf-vista-marco');
  const problema = problemaDelEditor(crudo);
  if (problema) { estadoEl.textContent = problema; return; }
  const ctl = new AbortController();
  vista.controlador = ctl;
  marco.classList.add('cargando');
  if ($('pe-vista-img').hidden) estadoEl.textContent = 'Preparando la vista previa…';
  // Con los datos del propio perfil; lo que es de cada examen se rellena con un ejemplo.
  const datos = {
    ...datosDePerfil(crudo), materia: 'Materia de ejemplo', actividad: 'Parcial 1', grupo: '1IL-131', contenido: 'solo_examen',
    docente: yoDatos.nombre || 'Nombre del docente', rotulo_docente: yoDatos.rotulo_docente || 'facilitador',
  };
  try {
    const res = await apiFetch('/api/vista_previa_pdf?pagina=1', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cuerpoPdf(ejemploExamen(), datos)), signal: ctl.signal,
    });
    if (!res.ok) {
      soltarImagen();
      estadoEl.textContent = 'No se pudo preparar la vista previa.';
      return;
    }
    const url = URL.createObjectURL(await res.blob());
    if (vista.url) URL.revokeObjectURL(vista.url);
    vista.url = url;
    $('pe-vista-img').src = url;
    $('pe-vista-img').hidden = false;
    estadoEl.textContent = '';
  } catch (err) {
    if (err && err.name === 'AbortError') return;
    estadoEl.textContent = 'No se pudo preparar la vista previa. Inténtalo de nuevo.';
  } finally {
    if (vista.controlador === ctl) { marco.classList.remove('cargando'); vista.controlador = null; }
  }
}

function alternarVista(abrir = !vista.abierta) {
  vista.abierta = abrir;
  $('pe-vista').hidden = !abrir;
  $('pe-caja').classList.toggle('modal-pdf-ancho', abrir);
  $('btn-pe-vista').setAttribute('aria-pressed', String(abrir));
  if (abrir) refrescarVista(); else { detenerVista(); soltarImagen(); }
}

function cambioEnEditor() {
  actualizarResumen();
  if (vista.abierta) { clearTimeout(vista.temporizador); vista.temporizador = setTimeout(refrescarVista, 700); }
}

async function logoElegido(clave, archivo) {
  if (!archivo) return;
  errorEditor('');
  if (!logoArchivoValido(archivo)) { errorEditor(MENSAJE_LOGO_INVALIDO); return; }
  try { mostrarLogo(clave, await reducirLogo(archivo)); cambioEnEditor(); } catch (_) { errorEditor('No se pudo leer esa imagen. Prueba con otra.'); }
}

// ── Arranque ────────────────────────────────────────────────────────────
export function iniciarPerfil() {
  $('btn-perfil').addEventListener('click', abrirPerfil);
  $('btn-vp-cerrar').addEventListener('click', cerrarPerfil);
  $('vp-form').addEventListener('submit', guardarDatos);
  $('vp-form').addEventListener('input', ejemploRotulo);
  $('pe-form').addEventListener('submit', guardarEditor);
  $('pe-form').addEventListener('input', cambioEnEditor);
  $('pe-form').addEventListener('change', cambioEnEditor);
  Object.entries(LADOS).forEach(([clave, lado]) => {
    $(`pe-logo-${lado}-archivo`).addEventListener('change', e => logoElegido(clave, e.target.files[0]));
    $(`pe-logo-${lado}-quitar`).addEventListener('click', () => { mostrarLogo(clave, ''); cambioEnEditor(); });
  });
  $('btn-pe-vista').addEventListener('click', () => alternarVista());
  $('btn-pe-cancelar').addEventListener('click', () => cerrarModal(editorEl));
  $('btn-pe-cerrar').addEventListener('click', () => cerrarModal(editorEl));
  editorEl.addEventListener('click', e => { if (e.target === editorEl) cerrarModal(editorEl); });
  cargarYo();
  cargarPerfilesGuardados();
}
