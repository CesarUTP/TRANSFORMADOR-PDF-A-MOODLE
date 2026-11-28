/**
 * imagenes-papel.js — «Tamaño y posición de las imágenes» en la pantalla de exportar: cada imagen puede salir
 * pequeña, mediana, grande o de margen a margen en el papel, y a la izquierda, al centro o a la derecha. No
 * cambia la evaluación ni el XML: lo elegido se recuerda solo en este equipo (por la propia imagen, así sirve
 * aunque la evaluación se vuelva a abrir).
 */
import { crearIconos, esc_html } from '../util.js';
import { huellaDeImagen, imagenesDelExamen, posicionesParaEnviar, rotuloDeImagen, tamanosParaEnviar } from './exportar-pdf-logica.js';

const $ = id => document.getElementById(id);
const TOPE = 300;                       // imágenes recordadas; se olvidan las más antiguas
const TAMANOS = [['pequena', 'Pequeña'], ['', 'Mediana'], ['grande', 'Grande'], ['completo', 'Todo el ancho']];
const POSICIONES = [['', 'Izquierda', 'align-left'], ['centro', 'Centro', 'align-center'], ['derecha', 'Derecha', 'align-right']];

// Un recuerdo por cosa elegida: { huella: valor }.
function _recuerdo(clave) {
  const leer = () => {
    try {
      const v = JSON.parse(localStorage.getItem(clave) || '{}');
      return v && typeof v === 'object' && !Array.isArray(v) ? v : {};
    } catch (_) { return {}; }
  };
  const guardar = (huella, valor) => {
    const todo = leer();
    delete todo[huella];
    if (valor) todo[huella] = valor;
    const claves = Object.keys(todo);
    claves.slice(0, Math.max(0, claves.length - TOPE)).forEach(k => delete todo[k]);
    try { localStorage.setItem(clave, JSON.stringify(todo)); } catch (_) { /* sin almacenamiento: vale para esta vez */ }
  };
  return { leer, guardar };
}

export function crearImagenesPapel({ alCambiar }) {
  let imagenes = [];                    // [{ huella, mime, b64, usos: ['3:0'], preguntas: [3], compartida? }]
  const tamanos = _recuerdo('conversor.exportar_pdf.imagenes');
  const posiciones = _recuerdo('conversor.exportar_pdf.imagenes_posicion');
  let elegidos = { tam: {}, pos: {} };

  function pintar() {
    $('pdf-sec-imagenes').hidden = !imagenes.length;
    $('pdf-imagenes-lista').innerHTML = imagenes.map((im, i) => {
      const cuales = rotuloDeImagen(im);
      const tam = elegidos.tam[im.huella] || '';
      return `<li class="vpdf-imagen">
        <img src="data:${esc_html(im.mime)};base64,${esc_html(im.b64)}" alt="">
        <p class="vpdf-imagen-nombre" id="pdf-imagen-${i}-t">${esc_html(cuales)}</p>
        <div class="vpdf-imagen-controles">
          <select id="pdf-imagen-${i}" class="form-input" data-huella="${esc_html(im.huella)}" data-que="tam" aria-label="Tamaño de la imagen (${esc_html(cuales)})">
            ${TAMANOS.map(([v, t]) => `<option value="${v}"${tam === v ? ' selected' : ''}>${t}</option>`).join('')}
          </select>
          <div class="vpdf-segmentos vpdf-posicion" role="radiogroup" aria-label="Posición de la imagen (${esc_html(cuales)})"
            title="${tam === 'completo' ? 'A todo el ancho ocupa de margen a margen' : ''}">
            ${POSICIONES.map(([v, t, icono]) => `<label title="${t}"><input type="radio" name="pdf-imagen-pos-${i}" value="${v}" data-huella="${esc_html(im.huella)}" data-que="pos" aria-label="${t}"${(elegidos.pos[im.huella] || '') === v ? ' checked' : ''}${tam === 'completo' ? ' disabled' : ''}><span><i data-lucide="${icono}" aria-hidden="true"></i></span></label>`).join('')}
          </div>
        </div>
      </li>`;
    }).join('');
    crearIconos($('pdf-imagenes-lista'));
  }

  return {
    iniciar() {
      // Corre antes que el oyente del formulario: cuando este lee los datos, lo elegido ya está anotado.
      $('pdf-imagenes-lista').addEventListener('change', e => {
        const { huella, que } = e.target.dataset;
        if (!huella) return;
        if (e.target.value) elegidos[que][huella] = e.target.value;
        else delete elegidos[que][huella];
        (que === 'tam' ? tamanos : posiciones).guardar(huella, e.target.value);
        if (que === 'tam') {            // a todo el ancho no hay posición que elegir
          const completo = e.target.value === 'completo';
          const grupo = e.target.parentElement.querySelector('.vpdf-posicion');
          grupo.title = completo ? 'A todo el ancho ocupa de margen a margen' : '';
          grupo.querySelectorAll('input').forEach(r => { r.disabled = completo; });
        }
        alCambiar();
      });
    },
    abrir(examen) {
      imagenes = imagenesDelExamen(examen.questions).map(im => ({ ...im, huella: huellaDeImagen(im.b64) }));
      elegidos = { tam: tamanos.leer(), pos: posiciones.leer() };
      pintar();
    },
    leer: () => ({
      tam_imagenes: tamanosParaEnviar(imagenes, elegidos.tam),
      // A todo el ancho no se manda posición.
      alin_imagenes: posicionesParaEnviar(imagenes.filter(im => elegidos.tam[im.huella] !== 'completo'), elegidos.pos),
    }),
  };
}
