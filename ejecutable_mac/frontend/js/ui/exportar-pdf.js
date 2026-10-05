/**
 * exportar-pdf.js — «Exportar examen en PDF»: el diálogo que pide los datos de la portada
 * (docente, materia, actividad…) y descarga el examen impreso con su clave.
 *
 * Es un documento de apoyo: el PDF sale de las MISMAS preguntas que se enviaron para el
 * Moodle XML (estado.exportable) y no cambia nada de él. Lo escrito se recuerda para el
 * próximo examen (localStorage, solo en este equipo; si no hay almacenamiento, no pasa nada).
 */
import { apiFetch } from '../api.js';
import { saveFileToUser } from '../resultado.js';
import { estado } from '../estado.js';
import { detalleDeError, friendlyHttpError } from '../util.js';
import { abrirModal, cerrarModal } from './modales.js';
import { showToast } from './toast.js';
import {
  ACTIVIDADES, avisosDelPdf, cuerpoPdf, fechaLegible, medidasReducidas, nombreDeDescarga, paraGuardar, valoresIniciales,
} from './exportar-pdf-logica.js';

const CLAVE_GUARDADO = 'conversor.exportar_pdf';
const $ = id => document.getElementById(id);
const modal = $('modal-pdf');
const form = $('pdf-form');
const errorEl = $('pdf-error');
const btnExportar = $('btn-pdf-exportar');
const CAMPOS_TEXTO = ['institucion', 'facultad', 'departamento', 'materia', 'docente', 'actividad', 'grupo', 'instrucciones'];
const LADOS = { logo_izquierdo: 'izq', logo_derecho: 'der' };
/** Los logos elegidos (base64 sin «data:»); '' = sin logo. */
const logos = { logo_izquierdo: '', logo_derecho: '' };
const MAX_ARCHIVO_LOGO = 8 * 1024 * 1024;

function leerGuardado() {
  try { return JSON.parse(localStorage.getItem(CLAVE_GUARDADO) || 'null'); } catch (_) { return null; }
}

function guardar(datos) {
  try { localStorage.setItem(CLAVE_GUARDADO, JSON.stringify(paraGuardar(datos))); } catch (_) { /* sin almacenamiento: se pregunta de nuevo la próxima vez */ }
}

function llenar(v) {
  CAMPOS_TEXTO.forEach(k => { $(`pdf-${k}`).value = v[k]; });
  $('pdf-fecha').value = '';
  form.elements.contenido.value = v.contenido;
  form.elements.papel.value = v.papel;
  form.elements.margenes.value = v.margenes;
  form.elements.campos_estudiante.checked = v.campos_estudiante;
  form.elements.partes.checked = v.partes;
  form.elements.mezclar.checked = v.mezclar;
  form.elements.rotulo_docente.value = v.rotulo_docente;
  Object.keys(LADOS).forEach(k => mostrarLogo(k, v[k]));
}

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

/** Reduce la imagen elegida (como mucho 320 px de lado, con su transparencia) y devuelve su base64. */
function reducirLogo(archivo) {
  return new Promise((resolver, rechazar) => {
    const url = URL.createObjectURL(archivo);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const m = medidasReducidas(img.naturalWidth, img.naturalHeight);
      if (!m) { rechazar(new Error('vacía')); return; }
      const lienzo = document.createElement('canvas');
      lienzo.width = m.ancho; lienzo.height = m.alto;
      lienzo.getContext('2d').drawImage(img, 0, 0, m.ancho, m.alto);
      resolver(lienzo.toDataURL('image/png').split(',')[1]);
    };
    img.onerror = () => { URL.revokeObjectURL(url); rechazar(new Error('ilegible')); };
    img.src = url;
  });
}

async function logoElegido(clave, archivo) {
  if (!archivo) return;
  mostrarError('');
  if (!/^image\/(png|jpe?g|gif|webp)$/.test(archivo.type) || archivo.size > MAX_ARCHIVO_LOGO) {
    mostrarError('El logo debe ser una imagen PNG, JPG, GIF o WebP de menos de 8 MB.');
    return;
  }
  try {
    mostrarLogo(clave, await reducirLogo(archivo));
  } catch (_) {
    mostrarError('No se pudo leer esa imagen. Prueba con otra.');
  }
}

/** Lo que hay escrito ahora en el diálogo (la fecha va ya con su nombre de mes). */
function leer() {
  const datos = { fecha: fechaLegible($('pdf-fecha').value) };
  CAMPOS_TEXTO.forEach(k => { datos[k] = $(`pdf-${k}`).value; });
  datos.contenido = form.elements.contenido.value;
  datos.papel = form.elements.papel.value;
  datos.margenes = form.elements.margenes.value;
  datos.campos_estudiante = form.elements.campos_estudiante.checked;
  datos.partes = form.elements.partes.checked;
  datos.mezclar = form.elements.mezclar.checked;
  datos.rotulo_docente = form.elements.rotulo_docente.value;
  Object.assign(datos, logos);
  return datos;
}

function mostrarError(texto) {
  errorEl.textContent = texto || '';
  errorEl.hidden = !texto;
  form.classList.toggle('has-error', !!texto);
}

function ocupado(si) {
  btnExportar.disabled = si;
  $('btn-pdf-exportar-etiqueta').textContent = si ? 'Generando el PDF…' : 'Exportar PDF';
}

export function abrirExportarPdf() {
  if (!estado.exportable) {
    showToast('Genera primero el XML: el PDF sale del mismo examen.', 'error');
    return;
  }
  llenar(valoresIniciales(leerGuardado()));
  mostrarError('');
  ocupado(false);
  abrirModal(modal, { foco: $('pdf-materia') });
}

function cerrar() {
  cerrarModal(modal);
}

async function exportar(e) {
  e.preventDefault();
  if (!estado.exportable || btnExportar.disabled) return;
  const datos = leer();
  mostrarError('');
  ocupado(true);
  try {
    const res = await apiFetch('/api/exportar_pdf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cuerpoPdf(estado.exportable, datos)),
    });
    if (!res.ok) {
      let msg = friendlyHttpError(res.status);
      try { const json = await res.json(); msg = detalleDeError(json.detail, msg); } catch (_) { /* se queda el genérico */ }
      mostrarError(typeof msg === 'string' ? msg : (msg.errors || []).join(' '));
      return;
    }
    const avisos = avisosDelPdf(res.headers.get('X-PDF-Info'));
    const nombre = nombreDeDescarga(res.headers.get('Content-Disposition'), 'examen.pdf');
    const guardado = await saveFileToUser(await res.blob(), nombre,
      'PDF guardado en tu equipo' + (avisos.length ? '. ' + avisos.join(' ') : ''));
    // Si cerró el diálogo de «Guardar como» sin guardar, se queda aquí para poder intentarlo otra vez.
    if (guardado) {
      guardar(datos);
      cerrar();
    }
  } catch (err) {
    mostrarError('No se pudo generar el PDF. Tu revisión y el XML no se ven afectados: inténtalo de nuevo.');
  } finally {
    ocupado(false);
  }
}

export function iniciarExportarPdf() {
  $('pdf-actividades').replaceChildren(...ACTIVIDADES.map(a => Object.assign(document.createElement('option'), { value: a })));
  form.addEventListener('submit', exportar);
  Object.entries(LADOS).forEach(([clave, lado]) => {
    $(`pdf-logo-${lado}-archivo`).addEventListener('change', e => logoElegido(clave, e.target.files[0]));
    $(`pdf-logo-${lado}-quitar`).addEventListener('click', () => mostrarLogo(clave, ''));
  });
  $('btn-pdf-cancelar').addEventListener('click', cerrar);
  $('btn-pdf-cerrar').addEventListener('click', cerrar);
  modal.addEventListener('click', ev => { if (ev.target === modal) cerrar(); });
}
