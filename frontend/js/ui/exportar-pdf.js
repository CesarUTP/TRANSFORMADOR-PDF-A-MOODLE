/**
 * exportar-pdf.js — «Exportar examen en PDF»: la pantalla con los datos de la portada, el formato, las versiones
 * del examen y la vista previa, y la descarga del examen impreso con su clave (un PDF, o un ZIP con varias versiones).
 *
 * Es un documento de apoyo: el PDF sale de las MISMAS preguntas que se enviaron para el Moodle XML
 * (estado.exportable) o de las de un examen del Historial, y no cambia nada de él. Lo escrito se recuerda
 * para el próximo examen (localStorage, solo en este equipo); los perfiles de encabezado, con nombre,
 * viven en el servidor local (/api/perfiles_pdf).
 */
import { apiFetch } from '../api.js';
import { saveFileToUser } from '../resultado.js';
import { estado } from '../estado.js';
import { llenarSelectMateria, materiaPorId, valorDeSelect } from '../materias.js';
import { datosDelDocente } from '../perfil.js';
import { detalleDeError, friendlyHttpError } from '../util.js';
import { confirmar } from './confirmar.js';
import { MENSAJE_LOGO_INVALIDO, logoArchivoValido, reducirLogo } from './logo-imagen.js';
import { abrirModal, cerrarModal } from './modales.js';
import { showToast } from './toast.js';
import { crearVersiones } from './versiones.js';
import {
  ACTIVIDADES, RENGLONES_MAX, RENGLONES_MIN, aplicarPerfil, avisosDelPdf, cuerpoPdf, datosDePerfil, enteroEn, fechaLegible,
  nombreDeDescarga, nombrePerfil, paraGuardar, tamanoValido, valoresIniciales,
} from './exportar-pdf-logica.js';

const CLAVE_GUARDADO = 'conversor.exportar_pdf';
const $ = id => document.getElementById(id);
const modal = $('vista-pdf');
const form = $('pdf-form');
const errorEl = $('pdf-error');
const btnExportar = $('btn-pdf-exportar');
const CAMPOS_TEXTO = ['institucion', 'facultad', 'departamento', 'materia', 'docente', 'actividad', 'grupo', 'instrucciones'];
const LADOS = { logo_izquierdo: 'izq', logo_derecho: 'der' };
const PAPELES = { carta: 'Carta', legal: 'Legal', a4: 'A4' };
const FUENTES = { dejavu: 'DejaVu Sans', arial: 'Arial', times: 'Times New Roman' };
const MARGENES = { normal: 'normales', estrechos: 'estrechos', moderados: 'moderados', anchos: 'anchos' };

/** Lo que se exporta ahora: { filename, total_points, questions, answer_key }. */
let examen = null;
/** Los perfiles guardados: [{ nombre, datos }]. */
let perfiles = [];
/** Los logos elegidos (base64 sin «data:»); '' = sin logo. */
const logos = { logo_izquierdo: '', logo_derecho: '' };
const vista = { abierta: false, pagina: 1, paginas: 1, url: null, temporizador: null, controlador: null };
/** Las versiones del examen (2.5): su sección, sus pestañas y sus puntos viven en versiones.js. */
const versiones = crearVersiones({ alCambiar: () => cambioEnFormulario() });

// ── Lo recordado ────────────────────────────────────────────────────────
function leerGuardado() {
  try { return JSON.parse(localStorage.getItem(CLAVE_GUARDADO) || 'null'); } catch (_) { return null; }
}

function guardar(datos) {
  try { localStorage.setItem(CLAVE_GUARDADO, JSON.stringify(paraGuardar(datos))); } catch (_) { /* sin almacenamiento: se pregunta de nuevo la próxima vez */ }
}

// ── El formulario ───────────────────────────────────────────────────────
function llenarExamen(v) {
  ['materia', 'actividad', 'grupo'].forEach(k => { $(`pdf-${k}`).value = v[k]; });
  $('pdf-fecha').value = '';
  form.elements.contenido.value = v.contenido;
}

/** El encabezado y el formato (lo que guarda un perfil). */
function llenarPerfil(v) {
  ['institucion', 'facultad', 'departamento', 'docente', 'instrucciones'].forEach(k => { $(`pdf-${k}`).value = v[k]; });
  const f = form.elements;
  f.papel.value = v.papel;
  f.margenes.value = v.margenes;
  f.rotulo_docente.value = v.rotulo_docente;
  f.fuente_titulos.value = v.fuente_titulos;
  f.fuente_preguntas.value = v.fuente_preguntas;
  f.tam_titulos.value = v.tam_titulos;
  f.tam_preguntas.value = v.tam_preguntas;
  f.renglones_ensayo.value = v.renglones_ensayo;
  f.campos_estudiante.checked = v.campos_estudiante;
  f.partes.checked = v.partes;
  f.mezclar.checked = v.mezclar;
  f.puntos_por_pregunta.checked = v.puntos_por_pregunta;
  Object.keys(LADOS).forEach(k => mostrarLogo(k, v[k]));
}

/** Lo que hay escrito ahora en el diálogo (la fecha va ya con su nombre de mes). */
function leer() {
  const f = form.elements;
  const datos = { fecha: fechaLegible($('pdf-fecha').value) };
  CAMPOS_TEXTO.forEach(k => { datos[k] = $(`pdf-${k}`).value; });
  Object.assign(datos, {
    contenido: f.contenido.value, papel: f.papel.value, margenes: f.margenes.value, rotulo_docente: f.rotulo_docente.value,
    fuente_titulos: f.fuente_titulos.value, fuente_preguntas: f.fuente_preguntas.value,
    tam_titulos: f.tam_titulos.value, tam_preguntas: f.tam_preguntas.value,   // valoresIniciales() los valida (7–20 pt) al enviar
    renglones_ensayo: f.renglones_ensayo.value, campos_estudiante: f.campos_estudiante.checked, partes: f.partes.checked,
    mezclar: f.mezclar.checked, puntos_por_pregunta: f.puntos_por_pregunta.checked,
  }, logos);
  return datos;
}

/** El motivo por el que lo escrito no sirve, o '' si está bien. */
function problemaDe(datos) {
  if (tamanoValido(datos.tam_titulos) === null || tamanoValido(datos.tam_preguntas) === null) {
    return 'El tamaño de la letra debe estar entre 7 y 20 puntos.';
  }
  if (enteroEn(datos.renglones_ensayo, RENGLONES_MIN, RENGLONES_MAX) === null) {
    return `Los renglones por ensayo deben ser un número entero entre ${RENGLONES_MIN} y ${RENGLONES_MAX}.`;
  }
  return '';
}

function mostrarError(texto) {
  errorEl.textContent = texto || '';
  errorEl.hidden = !texto;
  form.classList.toggle('has-error', !!texto);
}

let generando = false;

function ocupado(si) {
  generando = si;
  actualizarPie();
}

/** El botón de exportar y la línea de abajo según haya o no versiones sorteadas. */
function actualizarPie() {
  const conVersiones = versiones.activa();
  const listas = versiones.listas();
  const etiqueta = $('btn-pdf-exportar-etiqueta');
  if (generando) etiqueta.textContent = conVersiones ? 'Generando las versiones…' : 'Generando el PDF…';
  else if (conVersiones) etiqueta.textContent = listas ? `Exportar ${versiones.cantidad()} versiones (ZIP)` : 'Exportar versiones';
  else etiqueta.textContent = 'Exportar PDF';
  btnExportar.disabled = generando || (conVersiones && !listas);
  let texto = '';
  if (conVersiones && !generando) {
    if (!versiones.cantidad()) texto = 'Sortea las versiones (a la izquierda) para poder exportarlas.';
    else if (!listas) texto = 'Cambiaste el plan de versiones: vuelve a sortear para exportar.';
    else {
      const r = versiones.resumen();
      texto = `Un ZIP con ${r.n} PDF, uno por versión, cada uno con su clave. El XML de Moodle no cambia.`;
    }
  }
  $('pdf-pie-texto').textContent = texto;
}

/** Lo que dice cada sección plegada, para saber qué hay dentro sin abrirla. */
function actualizarResumenes() {
  const d = leer();
  const nombres = [d.institucion, d.facultad, d.departamento].map(x => x.trim()).filter(Boolean);
  const nLogos = (d.logo_izquierdo ? 1 : 0) + (d.logo_derecho ? 1 : 0);
  $('pdf-resumen-encabezado').textContent = [nombres[0] || 'Sin institución', nLogos ? `${nLogos} logo${nLogos > 1 ? 's' : ''}` : ''].filter(Boolean).join(' · ');
  const preguntas = FUENTES[d.fuente_preguntas] || FUENTES.dejavu;
  $('pdf-resumen-formato').textContent = `${PAPELES[d.papel] || 'Carta'} · márgenes ${MARGENES[d.margenes] || ''} · ${preguntas} ${tamanoValido(d.tam_preguntas) ?? '?'} pt`;
}

// ── Logos ───────────────────────────────────────────────────────────────
function mostrarLogo(clave, b64) {
  const lado = LADOS[clave];
  logos[clave] = b64 || '';
  const img = $(`pdf-logo-${lado}-vista`);
  if (b64) img.src = `data:image/png;base64,${b64}`;
  else img.removeAttribute('src');
  $(`pdf-logo-${lado}-caja`).classList.toggle('con-logo', !!b64);
  $(`pdf-logo-${lado}-quitar`).hidden = !b64;
  $(`pdf-logo-${lado}-archivo`).value = '';
}

async function logoElegido(clave, archivo) {
  if (!archivo) return;
  mostrarError('');
  if (!logoArchivoValido(archivo)) {
    mostrarError(MENSAJE_LOGO_INVALIDO);
    return;
  }
  try {
    mostrarLogo(clave, await reducirLogo(archivo));
    cambioEnFormulario();
  } catch (_) {
    mostrarError('No se pudo leer esa imagen. Prueba con otra.');
  }
}

// ── Perfiles de encabezado ──────────────────────────────────────────────
const opcion = (valor, texto) => Object.assign(document.createElement('option'), { value: valor, textContent: texto });

async function cargarPerfiles(elegir = '') {
  try {
    const res = await apiFetch('/api/perfiles_pdf');
    perfiles = res.ok ? await res.json() : [];
  } catch (_) {
    perfiles = [];
  }
  const sel = $('pdf-perfil');
  sel.replaceChildren(opcion('', 'Sin perfil'), ...perfiles.map(p => opcion(p.nombre, p.nombre)));
  sel.value = perfiles.some(p => p.nombre === elegir) ? elegir : '';
  $('btn-pdf-perfil-borrar').hidden = !sel.value;
}

// ── Materia (de «Mis materias») ─────────────────────────────────────────
/**
 * Elegir una materia pone su nombre y, si los tiene, su perfil de encabezado, su docente y su grupo.
 * «Otra: escribirla» deja el nombre a mano. Lo que se aplica se puede cambiar después en el mismo diálogo.
 */
function elegirMateria(id, { aplicar = true } = {}) {
  const m = materiaPorId(id);
  llenarSelectMateria($('pdf-materia-sel'), { valor: m ? m.id : null, conNueva: false, etiquetaSin: 'Otra: escribirla' });
  $('pdf-materia').hidden = !!m;
  if (!m) return;
  $('pdf-materia').value = m.nombre;
  if (!aplicar) return;
  if (m.perfil && perfiles.some(p => p.nombre === m.perfil)) {
    $('pdf-perfil').value = m.perfil;
    perfilElegido();
  }
  if (m.docente) $('pdf-docente').value = m.docente;
  if (m.grupo) $('pdf-grupo').value = m.grupo;
  actualizarResumenes();
}

/** Mi nombre y cómo me llamo (de «Mi perfil») mandan sobre lo que traiga un perfil o lo recordado. */
function aplicarDocente() {
  const d = datosDelDocente();
  if (d.nombre) $('pdf-docente').value = d.nombre;
  if (d.nombre || d.rotulo_docente !== 'facilitador') form.elements.rotulo_docente.value = d.rotulo_docente;
}

function perfilElegido() {
  const p = perfiles.find(x => x.nombre === $('pdf-perfil').value);
  $('btn-pdf-perfil-borrar').hidden = !p;
  if (!p) return;
  // El perfil pone el encabezado y el formato; la materia, la actividad, el grupo y la fecha no se tocan.
  llenarPerfil(aplicarPerfil(valoresIniciales(leer()), p.datos));
  aplicarDocente();
  mostrarError('');
  cambioEnFormulario();
}

function abrirNombreDePerfil() {
  $('pdf-perfil-nuevo').hidden = false;
  $('pdf-perfil-nombre').value = $('pdf-perfil').value;
  $('pdf-perfil-nombre').focus();
}

function cerrarNombreDePerfil() {
  $('pdf-perfil-nuevo').hidden = true;
}

async function guardarPerfil() {
  const nombre = nombrePerfil($('pdf-perfil-nombre').value);
  if (!nombre) { mostrarError('Escribe un nombre para el perfil.'); return; }
  const datos = leer();
  const problema = problemaDe(datos);
  if (problema) { mostrarError(problema); return; }
  mostrarError('');
  try {
    const res = await apiFetch(`/api/perfiles_pdf/${encodeURIComponent(nombre)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(datosDePerfil(datos)),
    });
    if (!res.ok) {
      let msg = friendlyHttpError(res.status);
      try { msg = detalleDeError((await res.json()).detail, msg); } catch (_) { /* se queda el genérico */ }
      mostrarError(typeof msg === 'string' ? msg : 'No se pudo guardar el perfil.');
      return;
    }
    cerrarNombreDePerfil();
    await cargarPerfiles(nombre);
    showToast(`Perfil «${nombre}» guardado`);
  } catch (_) {
    mostrarError('No se pudo guardar el perfil. Inténtalo de nuevo.');
  }
}

async function borrarPerfil() {
  const nombre = $('pdf-perfil').value;
  if (!nombre) return;
  const ok = await confirmar({
    titulo: '¿Borrar este perfil?',
    mensaje: `Se borrará el perfil «${nombre}». Los datos que ya están en el diálogo y los PDF que ya exportaste no cambian.`,
    confirmar: 'Borrar el perfil',
    cancelar: 'Conservarlo',
  });
  if (!ok) return;
  try {
    const res = await apiFetch(`/api/perfiles_pdf/${encodeURIComponent(nombre)}`, { method: 'DELETE' });
    if (!res.ok && res.status !== 404) throw new Error('falló');
    await cargarPerfiles('');
    showToast(`Perfil «${nombre}» borrado`, 'info');
  } catch (_) {
    mostrarError('No se pudo borrar el perfil. Inténtalo de nuevo.');
  }
}

// ── Vista previa ────────────────────────────────────────────────────────
function actualizarBarraDeVista() {
  $('pdf-vista-pagina').textContent = `Página ${vista.pagina} de ${vista.paginas}`;
  $('btn-pdf-vista-ant').disabled = vista.pagina <= 1;
  $('btn-pdf-vista-sig').disabled = vista.pagina >= vista.paginas;
}

function detenerVista() {
  clearTimeout(vista.temporizador);
  if (vista.controlador) vista.controlador.abort();
  vista.controlador = null;
}

function soltarImagenDeVista() {
  if (vista.url) URL.revokeObjectURL(vista.url);
  vista.url = null;
  $('pdf-vista-img').removeAttribute('src');
  $('pdf-vista-img').hidden = true;
}

const MENSAJE_VISTA = {
  sin_sortear: 'Sortea las versiones y aquí verás cada una.',
  desfasada: 'Cambiaste el plan: vuelve a sortear para ver las versiones nuevas.',
};

async function refrescarVista(pagina = vista.pagina) {
  detenerVista();
  const marco = document.querySelector('#pdf-previa .pdf-vista-marco');
  const estadoEl = $('pdf-vista-estado');
  const img = $('pdf-vista-img');
  const datos = leer();
  const problema = problemaDe(datos);
  if (problema) { estadoEl.textContent = problema; return; }
  const modo = versiones.estadoVista();
  if (MENSAJE_VISTA[modo]) {
    soltarImagenDeVista();
    estadoEl.textContent = MENSAJE_VISTA[modo];
    vista.paginas = 1;
    vista.pagina = 1;
    actualizarBarraDeVista();
    return;
  }
  const ctl = new AbortController();
  vista.controlador = ctl;
  marco.classList.add('cargando');
  if (img.hidden) estadoEl.textContent = 'Preparando la vista previa…';
  try {
    const res = await apiFetch(`/api/vista_previa_pdf?pagina=${pagina}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(modo === 'version' ? versiones.cuerpoVista(datos) : cuerpoPdf(examen, datos)),
      signal: ctl.signal,
    });
    if (!res.ok) {
      let msg = friendlyHttpError(res.status);
      try { msg = detalleDeError((await res.json()).detail, msg); } catch (_) { /* se queda el genérico */ }
      soltarImagenDeVista();
      estadoEl.textContent = typeof msg === 'string' ? msg : (msg.errors || []).join(' ');
      return;
    }
    vista.paginas = Number(res.headers.get('X-PDF-Paginas')) || 1;
    vista.pagina = Math.min(pagina, vista.paginas);
    const url = URL.createObjectURL(await res.blob());
    if (vista.url) URL.revokeObjectURL(vista.url);
    vista.url = url;
    img.src = url;
    img.hidden = false;
    estadoEl.textContent = '';
    actualizarBarraDeVista();
  } catch (err) {
    if (err && err.name === 'AbortError') return;
    estadoEl.textContent = 'No se pudo preparar la vista previa. Inténtalo de nuevo.';
  } finally {
    if (vista.controlador === ctl) { marco.classList.remove('cargando'); vista.controlador = null; }
  }
}

/** Todo cambio del formulario: actualiza los resúmenes y la línea de abajo, y rehace la vista previa. */
function cambioEnFormulario() {
  actualizarResumenes();
  actualizarPie();
  if (vista.abierta) {
    clearTimeout(vista.temporizador);
    vista.temporizador = setTimeout(() => refrescarVista(), 700);
  }
}

// ── Abrir, cerrar y exportar ────────────────────────────────────────────
/** `origen`: un examen del Historial ({ filename, total_points, questions, answer_key }); sin él, el recién generado. */
export function abrirExportarPdf(origen = null) {
  examen = origen && Array.isArray(origen.questions) ? origen : estado.exportable;
  if (!examen) {
    showToast('Genera primero el XML: el PDF sale del mismo examen.', 'error');
    return;
  }
  const v = valoresIniciales(leerGuardado());
  llenarExamen(v);
  llenarPerfil(v);
  const n = examen.questions.length;
  $('pdf-examen-nombre').textContent = `${examen.filename} · ${n} pregunta${n === 1 ? '' : 's'}. Todos los datos son opcionales y se recuerdan para el próximo examen.`;
  $('pdf-migas-examen').textContent = examen.filename;
  mostrarError('');
  ocupado(false);
  cerrarNombreDePerfil();
  versiones.abrir(examen);
  vista.abierta = true;
  vista.pagina = 1;
  soltarImagenDeVista();
  // La materia del examen (si la tiene) manda sobre lo recordado: pone su nombre, su perfil, su docente y su grupo.
  const examenAbierto = examen;
  const idMateria = examen.materia_id != null && materiaPorId(examen.materia_id) ? examen.materia_id : null;
  elegirMateria(idMateria, { aplicar: false });
  if (examen.actividad) $('pdf-actividad').value = examen.actividad;
  actualizarResumenes();
  // Orden de prioridad: la materia (su perfil, docente y grupo) > mi perfil predeterminado y mis datos > lo recordado.
  cargarPerfiles('').then(() => {
    if (examen !== examenAbierto) return;
    const pred = datosDelDocente().perfil_predeterminado;
    const materiaElegida = materiaPorId(idMateria);
    if (pred && perfiles.some(x => x.nombre === pred) && !(materiaElegida && materiaElegida.perfil)) {
      $('pdf-perfil').value = pred;
      perfilElegido();
    }
    aplicarDocente();
    if (idMateria != null) elegirMateria(idMateria);
    actualizarResumenes();
    actualizarPie();
    refrescarVista(1);
  });
  abrirModal(modal, { foco: $('pdf-config'), onClose: alCerrar });
  $('pdf-config').scrollTop = 0;
  $('pdf-previa').scrollTop = 0;
}

/** Se cierre como se cierre (botón, Escape…): se corta lo que estaba en marcha y se suelta lo pesado. */
function alCerrar() {
  vista.abierta = false;
  detenerVista();
  soltarImagenDeVista();
  versiones.cerrar();
}

function cerrar() {
  cerrarModal(modal);
}

async function exportar(e) {
  e.preventDefault();
  if (!examen || btnExportar.disabled) return;
  const datos = leer();
  mostrarError('');
  const problema = problemaDe(datos);
  if (problema) { mostrarError(problema); return; }
  const conVersiones = versiones.activa();
  if (conVersiones) {
    if (!versiones.listas()) { mostrarError('Sortea las versiones antes de exportarlas.'); return; }
    const mal = versiones.desajustes();
    if (mal.length) {
      const meta = versiones.objetivo();
      const ok = await confirmar({
        titulo: 'Algunas versiones no suman el total',
        mensaje: `El total deseado es ${meta} puntos y ${mal.map(m => `la versión ${m.etiqueta} suma ${m.total}`).join(', ')}. ¿Exportar así de todos modos?`,
        confirmar: 'Exportar de todos modos',
        cancelar: 'Volver a ajustar',
      });
      if (!ok) return;
    }
  }
  ocupado(true);
  try {
    const res = await apiFetch(conVersiones ? '/api/exportar_versiones' : '/api/exportar_pdf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(conVersiones ? versiones.cuerpoExportar(datos) : cuerpoPdf(examen, datos)),
    });
    if (!res.ok) {
      let msg = friendlyHttpError(res.status);
      try { const json = await res.json(); msg = detalleDeError(json.detail, msg); } catch (_) { /* se queda el genérico */ }
      mostrarError(typeof msg === 'string' ? msg : (msg.errors || []).join(' '));
      return;
    }
    const avisos = avisosDelPdf(res.headers.get('X-PDF-Info'));
    const nombre = nombreDeDescarga(res.headers.get('Content-Disposition'), conVersiones ? 'versiones.zip' : 'examen.pdf');
    const guardado = await saveFileToUser(await res.blob(), nombre,
      (conVersiones ? 'Versiones guardadas en un ZIP en tu equipo' : 'PDF guardado en tu equipo') + (avisos.length ? '. ' + avisos.join(' ') : ''));
    // Si cerró el diálogo de «Guardar como» sin guardar, se queda aquí para poder intentarlo otra vez.
    if (guardado) {
      guardar(datos);
      cerrar();
    }
  } catch (err) {
    mostrarError(`No se pudo generar ${versiones.activa() ? 'las versiones' : 'el PDF'}. Tu revisión y el XML no se ven afectados: inténtalo de nuevo.`);
  } finally {
    ocupado(false);
  }
}

export function iniciarExportarPdf() {
  $('pdf-actividades').replaceChildren(...ACTIVIDADES.map(a => Object.assign(document.createElement('option'), { value: a })));
  form.addEventListener('submit', exportar);
  form.addEventListener('input', cambioEnFormulario);
  form.addEventListener('change', cambioEnFormulario);
  Object.entries(LADOS).forEach(([clave, lado]) => {
    $(`pdf-logo-${lado}-archivo`).addEventListener('change', e => logoElegido(clave, e.target.files[0]));
    $(`pdf-logo-${lado}-quitar`).addEventListener('click', () => { mostrarLogo(clave, ''); cambioEnFormulario(); });
  });
  $('pdf-perfil').addEventListener('change', perfilElegido);
  $('pdf-materia-sel').addEventListener('change', () => { elegirMateria(valorDeSelect($('pdf-materia-sel'))); if ($('pdf-materia-sel').value === '') $('pdf-materia').focus(); cambioEnFormulario(); });
  $('btn-pdf-perfil-guardar').addEventListener('click', abrirNombreDePerfil);
  $('btn-pdf-perfil-ok').addEventListener('click', guardarPerfil);
  $('btn-pdf-perfil-cancelar').addEventListener('click', cerrarNombreDePerfil);
  $('btn-pdf-perfil-borrar').addEventListener('click', borrarPerfil);
  // Enter en el nombre del perfil guarda el perfil; no exporta el PDF.
  $('pdf-perfil-nombre').addEventListener('keydown', ev => {
    if (ev.key === 'Enter') { ev.preventDefault(); guardarPerfil(); }
  });
  $('btn-pdf-vista-ant').addEventListener('click', () => refrescarVista(vista.pagina - 1));
  $('btn-pdf-vista-sig').addEventListener('click', () => refrescarVista(vista.pagina + 1));
  $('btn-pdf-cancelar').addEventListener('click', cerrar);
  $('btn-pdf-cerrar').addEventListener('click', cerrar);
  versiones.iniciar();
}
