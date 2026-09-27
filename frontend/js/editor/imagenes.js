/**
 * imagenes.js — Imágenes de cada pregunta en el editor.
 *
 * La asignación automática (backend/imagenes.py) puede equivocarse, así que
 * el docente tiene la última palabra:
 *   - quitar una imagen, o moverla a la pregunta anterior / siguiente con
 *     botones, o a cualquiera con «Mover a…» (la alternativa sin
 *     arrastrar: WCAG 2.5.7; ↑/↓ de a una no sirve con 40 preguntas);
 *   - arrastrarla y soltarla sobre cualquier otra pregunta;
 *   - agregar una imagen propia (botón o soltando un archivo sobre la
 *     pregunta). Se reduce y comprime aquí, igual que las del documento.
 *
 * La tarjeta es la fuente de verdad: cada <figure class="q-image"> lleva su
 * imagen en el src (data URL) y collectEditorData() las lee de ahí, así que
 * mover una imagen es mover su nodo.
 */

import { notificar } from '../estado.js';
import { showToast } from '../ui/toast.js';
import { esc_html, scrollBehavior } from '../util.js';

export const MAX_POR_PREGUNTA = 5;
const LADO_MAX = 1000;                    // mismo tope que backend/imagenes.py
const MAX_BYTES_PNG = 350 * 1024;         // por encima, JPEG
const MAX_BYTES_IMAGEN = 2 * 1024 * 1024; // lo que acepta el validador
const MAX_BYTES_ARCHIVO = 20 * 1024 * 1024;
const TIPOS_ARCHIVO = /^image\/(png|jpeg|gif|webp|bmp)$/;
const SRC_VALIDO = /^data:(image\/(?:png|jpeg));base64,([A-Za-z0-9+/]+={0,2})$/;

const _valida = im => im && /^image\/(png|jpeg)$/.test(im.mime) && /^[A-Za-z0-9+/]+={0,2}$/.test(im.b64 || '');

function _figuraHtml(im) {
  return `<figure class="q-image" draggable="true">
    <img src="data:${im.mime};base64,${im.b64}" alt="" draggable="false">
    <figcaption class="q-image-botones">
      <span class="q-image-asa" title="Arrastra para moverla a otra pregunta" aria-hidden="true"><i data-lucide="grip-horizontal" style="width:14px;height:14px;"></i></span>
      <button type="button" class="btn btn-icon" data-accion="moverImagenAnterior" data-este aria-label="Mover a la pregunta anterior" title="Mover a la pregunta anterior">
        <i data-lucide="arrow-up" style="width:14px;height:14px;"></i>
      </button>
      <button type="button" class="btn btn-icon" data-accion="moverImagenSiguiente" data-este aria-label="Mover a la pregunta siguiente" title="Mover a la pregunta siguiente">
        <i data-lucide="arrow-down" style="width:14px;height:14px;"></i>
      </button>
      <select class="q-image-mover" data-accion-cambio="moverImagenA" data-este aria-label="Mover la imagen a otra pregunta" title="Mover a otra pregunta">
        <option value="">Mover a…</option>
      </select>
      <button type="button" class="btn btn-icon q-image-quitar" data-accion="quitarImagen" data-este aria-label="Quitar la imagen" title="Quitar imagen">
        <i data-lucide="x" style="width:14px;height:14px;"></i>
      </button>
    </figcaption>
  </figure>`;
}

/** Bloque de imágenes de una tarjeta (siempre presente: permite agregar). */
export function imagenesHtml(q, i, N) {
  const imgs = (Array.isArray(q.data.images) ? q.data.images : []).filter(_valida);
  return `<div class="q-images${imgs.length ? '' : ' vacia'}">
    <p class="field-label" id="q-img-t-${i}">Imágenes <span class="opcional">(van a Moodle con la pregunta)</span></p>
    <div class="q-images-fila" role="list" aria-labelledby="q-img-t-${i}">${imgs.map(_figuraHtml).join('')}</div>
    <div class="q-images-acciones">
      <button type="button" class="btn btn-ghost btn-sm" data-accion="agregarImagen" data-este aria-label="Agregar imagen a la pregunta ${N}"
        title="También puedes arrastrar una imagen a la pregunta">
        <i data-lucide="image-plus" style="width:14px;height:14px;"></i> <span>Agregar imagen</span>
      </button>
      <span class="q-soltar-nota" aria-hidden="true"><i data-lucide="download" style="width:14px;height:14px;"></i> Soltar en la pregunta ${N}</span>
      <input type="file" class="q-image-archivo" accept="image/png,image/jpeg,image/gif,image/webp" multiple hidden
        data-accion-cambio="imagenElegida" data-este tabindex="-1" aria-hidden="true">
    </div>
  </div>`;
}

/** Las imágenes que tiene ahora una tarjeta, listas para el XML. */
export function imagenesDeTarjeta(card, qNum) {
  const out = [];
  card.querySelectorAll('.q-image img').forEach(img => {
    const m = SRC_VALIDO.exec(img.getAttribute('src') || '');
    if (!m || out.length >= MAX_POR_PREGUNTA) return;
    const ext = m[1] === 'image/png' ? 'png' : 'jpg';
    out.push({ name: `pregunta${qNum}-${out.length + 1}.${ext}`, mime: m[1], b64: m[2] });
  });
  return out;
}

/** Textos alternativos y estado vacío de una tarjeta. */
function _etiquetar(card) {
  const N = card.dataset.qnum || '';
  const figs = card.querySelectorAll('.q-image');
  figs.forEach((f, k) => {
    f.setAttribute('role', 'listitem');
    f.querySelector('img').alt = `Imagen ${k + 1} de la pregunta ${N}`;
  });
  card.querySelector('.q-images')?.classList.toggle('vacia', figs.length === 0);
}

/** Tras cualquier cambio: etiquetas, y guarda el borrador y revisa la
 * pregunta (el mismo camino que al escribir en un campo). */
function _actualizar(card) {
  if (!card) return;
  _etiquetar(card);
  card.dispatchEvent(new Event('input', { bubbles: true }));
}

/** Después de dibujar el editor. */
export function prepararImagenes(container) {
  container.querySelectorAll('.editor-card').forEach(_etiquetar);
}

function _tarjetas() { return Array.from(document.querySelectorAll('.editor-card')); }

/** La imagen que acaba de llegar se señala un momento: sin esto, al
 * moverla o agregarla no se veía qué cambió (y el aviso la tapaba). */
function _senalar(fig) {
  fig.classList.remove('llegando');
  void fig.offsetWidth;
  fig.classList.add('llegando');
  fig.addEventListener('animationend', () => fig.classList.remove('llegando'), { once: true });
  // Centrada: el aviso de abajo no la tapa.
  fig.scrollIntoView({ block: 'center', behavior: scrollBehavior() });
}

function _mover(fig, destino, botonFoco = null) {
  const origen = fig.closest('.editor-card');
  if (!destino || destino === origen) return false;
  if (destino.querySelectorAll('.q-image').length >= MAX_POR_PREGUNTA) {
    showToast(`La pregunta ${destino.dataset.qnum} ya tiene ${MAX_POR_PREGUNTA} imágenes`, 'error');
    return false;
  }
  const filaOrigen = fig.parentElement, siguiente = fig.nextSibling;
  destino.querySelector('.q-images-fila').append(fig);
  _actualizar(origen);
  _actualizar(destino);
  _senalar(fig);
  notificar('imagen movida');
  showToast(`Imagen movida de la pregunta ${origen.dataset.qnum} a la ${destino.dataset.qnum}`, 'info', {
    accion: { texto: 'Deshacer', alPulsar: () => {
      filaOrigen.insertBefore(fig, siguiente);
      _actualizar(origen);
      _actualizar(destino);
      _senalar(fig);
      return fig.querySelector(botonFoco || 'button');
    } },
  });
  return true;
}

function _moverRelativo(btn, paso) {
  const fig = btn.closest('.q-image');
  const cards = _tarjetas();
  const destino = cards[cards.indexOf(fig?.closest('.editor-card')) + paso];
  if (!fig || !destino) {
    showToast(paso < 0 ? 'Es la primera pregunta' : 'Es la última pregunta', 'info');
    return;
  }
  const sel = `[data-accion="${paso < 0 ? 'moverImagenAnterior' : 'moverImagenSiguiente'}"]`;
  if (_mover(fig, destino, sel)) fig.querySelector(sel)?.focus({ preventScroll: true });
}

export function moverImagenAnterior(btn) { _moverRelativo(btn, -1); }
export function moverImagenSiguiente(btn) { _moverRelativo(btn, 1); }

/** «Mover a…»: la lista se arma al abrirla (las preguntas cambian). */
function _llenarDestinos(select) {
  const propia = select.closest('.editor-card');
  const opciones = _tarjetas().map((card, k) => {
    const texto = (card.querySelector('.q-stem')?.value || card.querySelector('.cloze-preview')?.textContent || '').trim().replace(/\s+/g, ' ');
    const corto = texto.length > 42 ? `${texto.slice(0, 40)}…` : texto;
    return `<option value="${k}"${card === propia ? ' disabled' : ''}>Pregunta ${esc_html(card.dataset.qnum || k + 1)}${corto ? ` — ${esc_html(corto)}` : ''}</option>`;
  });
  select.innerHTML = `<option value="">Mover a…</option>${opciones.join('')}`;
}

export function moverImagenA(select) {
  const fig = select.closest('.q-image');
  const destino = _tarjetas()[Number(select.value)];
  select.value = '';
  if (fig && destino && _mover(fig, destino, '.q-image-mover')) fig.querySelector('.q-image-mover')?.focus({ preventScroll: true });
}

/** Quita una imagen de su pregunta (no llegará a Moodle). */
export function quitarImagen(btn) {
  const fig = btn.closest('.q-image');
  const card = btn.closest('.editor-card');
  if (!fig || !card) return;
  const fila = fig.parentElement, siguiente = fig.nextSibling;
  fig.remove();
  _actualizar(card);
  card.focus({ preventScroll: true });
  notificar('imagen quitada');
  showToast(`Imagen quitada de la pregunta ${card.dataset.qnum}`, 'info', {
    accion: { texto: 'Deshacer', alPulsar: () => {
      fila.insertBefore(fig, siguiente);
      _actualizar(card);
      _senalar(fig);
      return fig.querySelector('.q-image-quitar');
    } },
  });
}

export function agregarImagen(btn) {
  btn.closest('.q-images')?.querySelector('.q-image-archivo')?.click();
}

export function imagenElegida(input) {
  const card = input.closest('.editor-card');
  const archivos = Array.from(input.files || []);
  input.value = '';
  if (card) _agregarArchivos(card, archivos);
}

// ── Archivo → imagen reducida en base64 ─────────────────────────────────

function _base64(blob) {
  return new Promise((ok, mal) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result).split(',')[1] || '');
    r.onerror = () => mal(r.error);
    r.readAsDataURL(blob);
  });
}

function _canvasBlob(canvas, tipo, calidad) {
  return new Promise(ok => canvas.toBlob(ok, tipo, calidad));
}

async function _procesar(archivo) {
  if (!TIPOS_ARCHIVO.test(archivo.type)) throw new Error('Solo imágenes PNG, JPG, GIF o WebP.');
  if (archivo.size > MAX_BYTES_ARCHIVO) throw new Error('La imagen es demasiado grande (máximo 20 MB).');
  const bmp = await createImageBitmap(archivo);
  const escala = Math.min(1, LADO_MAX / Math.max(bmp.width, bmp.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(bmp.width * escala));
  canvas.height = Math.max(1, Math.round(bmp.height * escala));
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#fff'; // sin transparencia: en JPEG saldría negra
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
  bmp.close?.();
  let blob = await _canvasBlob(canvas, 'image/png');
  if (!blob || blob.size > MAX_BYTES_PNG) blob = await _canvasBlob(canvas, 'image/jpeg', 0.85);
  if (!blob || blob.size > MAX_BYTES_IMAGEN) throw new Error('No se pudo reducir la imagen lo suficiente.');
  return { mime: blob.type, b64: await _base64(blob) };
}

async function _agregarArchivos(card, archivos) {
  const fila = card.querySelector('.q-images-fila');
  if (!fila || !archivos.length) return;
  // Reducir una foto grande tarda: el botón lo dice mientras tanto.
  const btn = card.querySelector('[data-accion="agregarImagen"]');
  const etiqueta = btn?.querySelector('span');
  if (btn) { btn.disabled = true; btn.setAttribute('aria-busy', 'true'); btn.style.minWidth = `${btn.offsetWidth}px`; }
  if (etiqueta) etiqueta.textContent = 'Procesando…';
  const nuevas = [];
  let error = '';
  try {
    for (const archivo of archivos) {
      if (fila.querySelectorAll('.q-image').length >= MAX_POR_PREGUNTA) {
        error = `Cada pregunta admite hasta ${MAX_POR_PREGUNTA} imágenes.`;
        break;
      }
      try {
        fila.insertAdjacentHTML('beforeend', _figuraHtml(await _procesar(archivo)));
        nuevas.push(fila.lastElementChild);
      } catch (e) {
        error = `«${archivo.name}»: ${e?.message || 'no se pudo leer la imagen.'}`;
      }
    }
  } finally {
    if (btn) { btn.disabled = false; btn.removeAttribute('aria-busy'); btn.style.minWidth = ''; }
    if (etiqueta) etiqueta.textContent = 'Agregar imagen';
  }
  if (!nuevas.length) {
    if (error) showToast(error, 'error');
    return;
  }
  lucide.createIcons();
  _actualizar(card);
  _senalar(nuevas[nuevas.length - 1]);
  notificar('imagen agregada');
  // Un solo aviso con el resultado. Si algo se agregó, no es un error
  // (antes salía en rojo aunque la imagen sí entrara).
  const hecho = nuevas.length === 1 ? `Imagen agregada a la pregunta ${card.dataset.qnum}` : `${nuevas.length} imágenes agregadas a la pregunta ${card.dataset.qnum}`;
  showToast(error ? `${hecho}. ${error}` : hecho, error ? 'info' : 'success', {
    accion: { texto: 'Deshacer', alPulsar: () => {
      nuevas.forEach(f => f.remove());
      _actualizar(card);
      return btn;
    } },
  });
}

// ── Arrastrar y soltar ──────────────────────────────────────────────────
// Una imagen de otra pregunta o un archivo del equipo, soltados en
// cualquier parte de la tarjeta.

let _arrastrada = null;

function _hayArchivos(e) {
  return Array.from(e.dataTransfer?.types || []).includes('Files');
}

export function iniciarArrastreImagenes(container) {
  const llenar = e => { if (e.target.matches?.('.q-image-mover')) _llenarDestinos(e.target); };
  container.addEventListener('pointerdown', llenar);
  container.addEventListener('focusin', llenar);

  // Un archivo soltado fuera de una tarjeta (o de la zona de subida) haría
  // que la ventana lo abra y se perdería la revisión en curso.
  window.addEventListener('dragover', e => {
    if (!e.defaultPrevented && _hayArchivos(e)) { e.preventDefault(); e.dataTransfer.dropEffect = 'none'; }
  });
  window.addEventListener('drop', e => { if (_hayArchivos(e)) e.preventDefault(); });

  container.addEventListener('dragstart', e => {
    const fig = e.target.closest?.('.q-image');
    if (!fig) return;
    _arrastrada = fig;
    fig.classList.add('arrastrando');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', 'imagen-de-pregunta');
    document.body.classList.add('arrastrando-imagen');
  });
  container.addEventListener('dragend', () => {
    _arrastrada?.classList.remove('arrastrando');
    _arrastrada = null;
    document.body.classList.remove('arrastrando-imagen');
    container.querySelectorAll('.soltar-aqui').forEach(c => c.classList.remove('soltar-aqui'));
  });
  container.addEventListener('dragover', e => {
    const card = e.target.closest?.('.editor-card');
    if (!card || !(_arrastrada || _hayArchivos(e))) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = _arrastrada ? 'move' : 'copy';
    if (!card.classList.contains('soltar-aqui')) {
      container.querySelectorAll('.soltar-aqui').forEach(c => c.classList.remove('soltar-aqui'));
      if (card !== _arrastrada?.closest('.editor-card')) card.classList.add('soltar-aqui');
    }
  });
  container.addEventListener('dragleave', e => {
    const card = e.target.closest?.('.editor-card');
    if (card && !card.contains(e.relatedTarget)) card.classList.remove('soltar-aqui');
  });
  container.addEventListener('drop', e => {
    const card = e.target.closest?.('.editor-card');
    if (!card) return;
    card.classList.remove('soltar-aqui');
    if (_arrastrada) {
      e.preventDefault();
      _mover(_arrastrada, card);
    } else if (_hayArchivos(e)) {
      e.preventDefault();
      _agregarArchivos(card, Array.from(e.dataTransfer.files));
    }
  });
}
