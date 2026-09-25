/**
 * acerca.js — «Acerca de»: versión y actualizaciones, API de Gemini,
 * privacidad y datos, información legal, avisos de terceros y créditos.
 *
 * Lo que depende de este equipo (versión, rutas donde se guardan los datos,
 * estado de la clave) se pide al servidor local al abrir. Los textos de
 * las licencias (legal/avisos-terceros.txt, ~500 KB) se cargan solo si se
 * despliegan.
 */
import { apiFetch } from '../api.js';
import { abrirEnlaceExterno } from '../util.js';
import { abrirAjustesClave } from './clave.js';
import { abrirModal, cerrarModal } from './modales.js';

const modal = document.getElementById('modal-acerca');
const $ = id => document.getElementById(id);
const estadoVersion = $('acerca-estado-version');
const btnBuscar = $('btn-acerca-buscar');
const btnDescargar = $('btn-acerca-descargar');
let _urlDescarga = null;

// Un mensaje distinto para cada caso: nunca «al día» cuando en realidad no
// se pudo preguntar (ver backend/actualizaciones.py).
const MOTIVOS_ERROR = {
  conexion: 'no hay conexión a internet. Revísala y vuelve a pulsar «Buscar actualizaciones».',
  servidor: 'el servidor de actualizaciones no respondió. Inténtalo más tarde.',
  respuesta: 'la respuesta del servidor de actualizaciones no era válida. Inténtalo más tarde.',
  local: 'la aplicación no respondió. Ciérrala y vuelve a abrirla.',
};

function _hora() {
  return new Date().toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' });
}

function _mostrarActualizacion(info) {
  btnDescargar.hidden = true;
  if (info && info.estado === 'nueva') {
    estadoVersion.textContent = `Hay una versión nueva: la ${info.version} (tienes la ${info.actual}).${info.notas ? ' ' + info.notas : ''}`;
    estadoVersion.dataset.tono = 'nueva';
    $('acerca-descargar-texto').textContent = `Descargar la versión ${info.version}`;
    _urlDescarga = info.url;
    btnDescargar.hidden = false;
  } else if (info && info.estado === 'al_dia') {
    estadoVersion.textContent = `Estás al día: la ${info.actual} es la versión más reciente. Comprobado a las ${_hora()}.`;
    estadoVersion.dataset.tono = 'al-dia';
  } else {
    const motivo = MOTIVOS_ERROR[info && info.motivo] || MOTIVOS_ERROR.local;
    estadoVersion.textContent = `No se pudo comprobar si hay una versión nueva: ${motivo}`;
    estadoVersion.dataset.tono = 'error';
  }
}

async function _buscarActualizacion(forzar) {
  btnBuscar.disabled = true;
  if (forzar) { estadoVersion.textContent = 'Buscando actualizaciones…'; estadoVersion.dataset.tono = ''; }
  try {
    const res = await apiFetch(`/api/actualizacion${forzar ? '?forzar=true' : ''}`);
    _mostrarActualizacion(res.ok ? await res.json() : null);
  } catch (_) {
    _mostrarActualizacion(null);
  } finally {
    btnBuscar.disabled = false;
  }
}

async function _estadoClave() {
  const el = $('acerca-api-estado');
  try {
    const res = await apiFetch('/api/api-key');
    const e = await res.json();
    if (e.configurada) {
      el.textContent = e.origen === 'entorno'
        ? `Configurada desde un archivo .env (modo desarrollo); termina en ····${e.final}.`
        : `Configurada y guardada cifrada en este equipo; termina en ····${e.final}.`;
      $('acerca-api-boton').textContent = 'Cambiar o quitar la clave';
    } else {
      el.textContent = 'Sin configurar: la necesitas para convertir exámenes. Es gratis.';
      $('acerca-api-boton').textContent = 'Configurar la clave';
    }
  } catch (_) {
    el.textContent = 'No se pudo consultar el estado de la clave.';
  }
}

async function _datosDelEquipo() {
  try {
    const res = await apiFetch('/api/acerca');
    const d = await res.json();
    $('acerca-version').textContent = d.version;
    $('acerca-ruta-historial').textContent = d.historial;
    $('acerca-ruta-clave').textContent = d.clave;
    $('acerca-ruta-registro').textContent = d.registro;
  } catch (_) { /* quedan los guiones */ }
}

export function abrirAcerca() {
  abrirModal(modal);
  _datosDelEquipo();
  _estadoClave();
  _buscarActualizacion(false);
}

export function cerrarAcerca() {
  cerrarModal(modal);
}

// ── Eventos ─────────────────────────────────────────────────────────────
$('btn-close-acerca').addEventListener('click', cerrarAcerca);
modal.addEventListener('click', e => { if (e.target === modal) cerrarAcerca(); });
btnBuscar.addEventListener('click', () => _buscarActualizacion(true));
btnDescargar.addEventListener('click', () => { if (_urlDescarga) abrirEnlaceExterno(_urlDescarga); });
$('btn-acerca-api').addEventListener('click', abrirAjustesClave);
modal.querySelectorAll('[data-url]').forEach(btn => {
  btn.addEventListener('click', () => abrirEnlaceExterno(btn.dataset.url));
});
// Al guardar o quitar la clave (el modal de la clave se abre encima).
document.addEventListener('clave-cambiada', _estadoClave);

$('acerca-licencias').addEventListener('toggle', async e => {
  const pre = $('acerca-licencias-texto');
  if (!e.target.open || pre.dataset.cargado) return;
  try {
    const res = await fetch('legal/avisos-terceros.txt');
    if (!res.ok) throw new Error(String(res.status));
    pre.textContent = await res.text();   // texto plano, nunca HTML
    pre.dataset.cargado = '1';
  } catch (_) {
    pre.textContent = 'No se pudieron cargar los textos de las licencias.';
  }
});
