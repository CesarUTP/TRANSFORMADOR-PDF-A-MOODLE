/**
 * partes-pdf.js — «Partes del examen» en la pantalla de exportar: el orden de las partes y, si el docente
 * quiere, su propio nombre e indicación para cada una. Lo vacío lo escribe Cátedra solo (según el tipo y lo
 * que traigan sus preguntas); la vista previa manda esos textos para mostrarlos como sugerencia.
 */
import { LIMITE_INDICACION_PARTE, LIMITE_NOMBRE_PARTE, NOMBRES_PARTE, moverParte, ordenDePartesValido, textosDePartesValidos, tiposEnOrden } from './exportar-pdf-logica.js';
import { crearIconos, esc_html } from '../util.js';

const $ = id => document.getElementById(id);
const ROMANOS = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII'];

/** `alCambiar()`: cambió un texto; `alReordenar()`: cambió el orden (las versiones se numeran de otra forma). */
export function crearPartesPdf({ alCambiar, alReordenar }) {
  let questions = [];
  let orden = [];
  let textos = {};          // { tipo: { nombre, indicacion } } tal como está escrito (se limpia al enviar)
  const automaticas = {};   // { tipo: { nombre, indicacion } } lo que Cátedra escribiría

  const lista = () => $('pdf-partes-lista');
  const presentes = () => tiposEnOrden(questions, orden);
  const automatica = t => automaticas[t] || { nombre: NOMBRES_PARTE[t] || 'PREGUNTAS', indicacion: '' };

  function resumen() {
    const n = Object.keys(textosDePartesValidos(textos)).length;
    const piezas = [orden.length ? 'orden propio' : '', n ? `${n} con texto propio` : ''].filter(Boolean);
    $('pdf-resumen-partes').textContent = $('pdf-form').elements.partes.checked ? (piezas.join(' · ') || 'Automáticas') : 'Sin partes';
  }

  /** Las sugerencias (texto en gris) y el botón de copiar, sin redibujar: no se pierde lo que se está escribiendo. */
  function sugerencias() {
    lista().querySelectorAll('.parte-fila').forEach(fila => {
      const a = automatica(fila.dataset.tipo);
      const indicacion = fila.querySelector('.parte-indicacion');
      fila.querySelector('.parte-nombre').placeholder = a.nombre;
      indicacion.placeholder = a.indicacion || 'Indicación automática';
      fila.querySelector('.parte-copiar').hidden = !a.indicacion || !!indicacion.value.trim();
    });
  }

  function pintar() {
    const tipos = presentes();
    const boton = (clase, icono, texto, activo) => `<button type="button" class="btn btn-icon ${clase}" aria-label="${texto}" title="${texto}"${activo ? '' : ' disabled'}><i data-lucide="${icono}" style="width:15px;height:15px;" aria-hidden="true"></i></button>`;
    lista().innerHTML = tipos.map((t, i) => {
      const propio = textos[t] || {};
      const cual = `la parte ${ROMANOS[i]} (${NOMBRES_PARTE[t] || t})`;
      return `<li class="parte-fila" data-tipo="${esc_html(t)}">
        <div class="parte-cab">
          <span class="parte-num">${ROMANOS[i]}</span>
          <input type="text" class="form-input parte-nombre" maxlength="${LIMITE_NOMBRE_PARTE}" autocomplete="off" value="${esc_html(propio.nombre || '')}" aria-label="Nombre de ${esc_html(cual)}">
          ${boton('parte-subir', 'arrow-up', `Subir ${esc_html(cual)}`, i > 0)}
          ${boton('parte-bajar', 'arrow-down', `Bajar ${esc_html(cual)}`, i < tipos.length - 1)}
        </div>
        <textarea class="form-input parte-indicacion" rows="2" maxlength="${LIMITE_INDICACION_PARTE}" aria-label="Indicación de ${esc_html(cual)}">${esc_html(propio.indicacion || '')}</textarea>
        <button type="button" class="text-link parte-copiar" hidden>Editar a partir del texto automático</button>
      </li>`;
    }).join('');
    crearIconos(lista());
    sugerencias();
    resumen();
  }

  /** ¿Se dividen las partes? Sin partes no hay nada que ordenar. */
  function activar() {
    const si = $('pdf-form').elements.partes.checked;
    $('pdf-partes-cuerpo').hidden = !si;
    $('pdf-partes-apagadas').hidden = si;
    resumen();
  }

  function iniciar() {
    // Corre antes que el oyente del formulario: cuando este lee los datos, lo escrito ya está anotado.
    lista().addEventListener('input', e => {
      const fila = e.target.closest('.parte-fila');
      if (!fila) return;
      textos[fila.dataset.tipo] = { nombre: fila.querySelector('.parte-nombre').value, indicacion: fila.querySelector('.parte-indicacion').value };
      sugerencias();
      resumen();
    });
    lista().addEventListener('click', e => {
      const boton = e.target.closest('button');
      const fila = boton && boton.closest('.parte-fila');
      if (!fila) return;
      const t = fila.dataset.tipo;
      if (boton.classList.contains('parte-copiar')) {
        const area = fila.querySelector('.parte-indicacion');
        area.value = automatica(t).indicacion;
        area.dispatchEvent(new Event('input', { bubbles: true }));
        area.focus();
        return;
      }
      const dir = boton.classList.contains('parte-subir') ? -1 : 1;
      orden = moverParte(presentes(), orden, t, dir);
      pintar();
      const otro = lista().querySelector(`.parte-fila[data-tipo="${t}"] .${dir < 0 ? 'parte-subir' : 'parte-bajar'}`);
      (otro.disabled ? otro.parentElement.querySelector('button:not([disabled])') : otro)?.focus();
      alReordenar();
    });
    $('btn-pdf-partes-auto').addEventListener('click', () => {
      orden = [];
      textos = {};
      pintar();
      alReordenar();
      alCambiar();
    });
  }

  return {
    iniciar,
    activar,
    abrir(examen) {
      questions = examen.questions;
      Object.keys(automaticas).forEach(k => delete automaticas[k]);
      pintar();
    },
    /** Pone el orden y los textos (de lo recordado o de un perfil). */
    llenar(nuevoOrden, nuevosTextos) {
      orden = ordenDePartesValido(nuevoOrden);
      textos = textosDePartesValidos(nuevosTextos);
      pintar();
    },
    leer: () => ({ orden_partes: [...orden], textos_partes: textosDePartesValidos(textos) }),
    /** Lo que dijo la vista previa que escribiría en cada parte: [{ tipo, nombre, indicacion }]. */
    sugerir(partes) {
      if (!Array.isArray(partes)) return;
      partes.forEach(p => { if (p && typeof p.tipo === 'string') automaticas[p.tipo] = { nombre: String(p.nombre || ''), indicacion: String(p.indicacion || '') }; });
      sugerencias();
    },
  };
}
