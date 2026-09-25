/**
 * clave.js — la clave de la API de Gemini de cada docente.
 *
 * Al abrir la app sin clave guardada aparece el modal de bienvenida como
 * paso obligatorio: explica cómo obtenerla gratis, abre Google AI Studio
 * y la comprueba con Google antes de guardarla. Después el mismo modal
 * se abre desde «Acerca de → API de Gemini» para cambiarla o quitarla.
 *
 * La clave nunca vuelve al navegador: el backend solo informa si hay una
 * y sus 4 últimos caracteres.
 */
import { apiFetch } from '../api.js';
import { abrirModal, cerrarModal } from './modales.js';
import { confirmar } from './confirmar.js';
import { showToast } from './toast.js';
import { abrirEnlaceExterno } from '../util.js';

const modal = document.getElementById('modal-apikey');
const titleText = document.getElementById('apikey-title-text');
const closeBtn = document.getElementById('btn-close-apikey');
const current = document.getElementById('apikey-current');
const currentDetail = document.getElementById('apikey-current-detail');
const form = document.getElementById('apikey-form');
const input = document.getElementById('apikey-input');
const inputLabel = document.getElementById('apikey-input-label');
const errorEl = document.getElementById('apikey-error');
const saveBtn = document.getElementById('btn-apikey-save');
const saveLabel = document.getElementById('btn-apikey-save-label');
const revealBtn = document.getElementById('btn-apikey-reveal');

let _estado = { configurada: false };

async function _pedirEstado() {
  const res = await apiFetch('/api/api-key');
  if (!res.ok) throw new Error('estado');
  _estado = await res.json();
  return _estado;
}

function _mostrarError(msg) {
  errorEl.textContent = msg;
  errorEl.hidden = !msg;
  form.classList.toggle('has-error', !!msg);
  input.setAttribute('aria-invalid', msg ? 'true' : 'false');
}

function _ocupado(si) {
  saveBtn.disabled = si;
  input.readOnly = si;
  if (si) {
    saveBtn.setAttribute('aria-busy', 'true');
    saveLabel.innerHTML = '<i data-lucide="loader-2" style="width:16px;height:16px;vertical-align:-3px;margin-right:6px;animation:spinSlow 0.8s linear infinite;"></i>Comprobando con Google…';
    if (window.lucide) lucide.createIcons();
  } else {
    saveBtn.removeAttribute('aria-busy');
    saveLabel.textContent = _estado.configurada ? 'Guardar la nueva clave' : 'Guardar y comenzar';
  }
}

function _ocultarClave() {
  input.type = 'password';
  revealBtn.setAttribute('aria-pressed', 'false');
  revealBtn.setAttribute('aria-label', 'Mostrar la clave');
  revealBtn.title = 'Mostrar la clave';
  document.getElementById('apikey-eye').style.display = '';
  document.getElementById('apikey-eye-off').style.display = 'none';
}

/**
 * `obligatorio`: sin clave no se puede usar la app, así que el modal no
 * tiene botón de cerrar ni se cierra con Escape o clic fuera.
 */
function _abrir(obligatorio) {
  modal.dataset.obligatorio = obligatorio ? 'true' : 'false';
  closeBtn.hidden = obligatorio;
  titleText.textContent = obligatorio ? 'Conecta tu API de Gemini' : 'API de Gemini';
  current.hidden = !_estado.configurada;
  if (_estado.configurada) {
    currentDetail.textContent = _estado.origen === 'entorno'
      ? `Termina en ····${_estado.final}. Viene de un archivo .env (modo desarrollo).`
      : `Termina en ····${_estado.final}. Para cambiarla, pega una nueva abajo.`;
  }
  inputLabel.textContent = _estado.configurada ? 'Pega aquí la nueva clave' : 'Pega aquí tu clave';
  input.value = '';
  _ocultarClave();
  _mostrarError('');
  _ocupado(false);
  modal.querySelector('.modal-body').scrollTop = 0;
  abrirModal(modal, { foco: input });
}

/** Al arrancar: si no hay clave, el modal de bienvenida. */
export async function comprobarClaveAlIniciar() {
  try {
    const e = await _pedirEstado();
    if (!e.configurada) _abrir(true);
  } catch (_) {
    // Sin respuesta del backend no se puede saber; la conversión
    // avisará igual si falta la clave.
  }
}

/** Desde «Acerca de → API de Gemini». */
export async function abrirAjustesClave() {
  try { await _pedirEstado(); } catch (_) { /* se abre con el último estado conocido */ }
  _abrir(!_estado.configurada);
}

export function cerrarAjustesClave() {
  if (modal.dataset.obligatorio === 'true') return;
  cerrarModal(modal);
}

/** Para Escape en app.js: el modal de bienvenida no se puede saltar. */
export function claveObligatoria() {
  return modal.dataset.obligatorio === 'true';
}

// ── Eventos ─────────────────────────────────────────────────────────────
closeBtn.addEventListener('click', cerrarAjustesClave);
modal.addEventListener('click', e => { if (e.target === modal) cerrarAjustesClave(); });

// Los enlaces se abren en el navegador del sistema (ver abrirEnlaceExterno).
modal.querySelectorAll('[data-url]').forEach(btn => {
  btn.addEventListener('click', () => abrirEnlaceExterno(btn.dataset.url));
});

revealBtn.addEventListener('click', () => {
  const ver = input.type === 'password';
  input.type = ver ? 'text' : 'password';
  revealBtn.setAttribute('aria-pressed', ver ? 'true' : 'false');
  const label = ver ? 'Ocultar la clave' : 'Mostrar la clave';
  revealBtn.setAttribute('aria-label', label);
  revealBtn.title = label;
  document.getElementById('apikey-eye').style.display = ver ? 'none' : '';
  document.getElementById('apikey-eye-off').style.display = ver ? '' : 'none';
  input.focus();
});

input.addEventListener('input', () => { if (!errorEl.hidden) _mostrarError(''); });

form.addEventListener('submit', async e => {
  e.preventDefault();
  if (saveBtn.disabled) return;
  const clave = input.value.replace(/\s+/g, '');
  if (!clave) {
    _mostrarError('Pega tu clave en el cuadro de texto.');
    input.focus();
    return;
  }
  const eraPrimeraVez = !_estado.configurada;
  _mostrarError('');
  _ocupado(true);
  try {
    const res = await apiFetch('/api/api-key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clave }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      _ocupado(false);
      _mostrarError(typeof data.detail === 'string' ? data.detail : 'No se pudo guardar la clave. Inténtalo otra vez.');
      input.focus();
      input.select();
      return;
    }
    _estado = data;
    input.value = '';
    document.dispatchEvent(new CustomEvent('clave-cambiada'));
    modal.dataset.obligatorio = 'false';
    cerrarModal(modal);
    showToast(eraPrimeraVez ? 'Clave guardada. Ya puedes convertir tus exámenes.' : 'Clave actualizada', 'success');
    if (eraPrimeraVez) document.getElementById('drop-zone')?.focus();
  } catch (_) {
    _ocupado(false);
    _mostrarError('No se pudo conectar con la aplicación. Ciérrala y vuelve a abrirla.');
  }
});

document.getElementById('btn-apikey-delete').addEventListener('click', async () => {
  const ok = await confirmar({
    titulo: '¿Quitar la clave de la API de Gemini?',
    mensaje: 'Se borrará de este equipo. Para volver a convertir exámenes tendrás que pegar una clave otra vez.',
    confirmar: 'Quitar clave',
    cancelar: 'Cancelar',
  });
  if (!ok) return;
  try {
    const res = await apiFetch('/api/api-key', { method: 'DELETE' });
    if (!res.ok) throw new Error('delete');
    _estado = await res.json();
    showToast('Clave quitada de este equipo', 'info');
    document.dispatchEvent(new CustomEvent('clave-cambiada'));
    // Sin clave (y sin .env de desarrollo), vuelve a ser paso obligatorio.
    _abrir(!_estado.configurada);
  } catch (_) {
    showToast('No se pudo quitar la clave', 'error');
  }
});
