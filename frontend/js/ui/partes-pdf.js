/**
 * partes-pdf.js — «Partes del examen» en la pantalla de exportar: el orden de las partes, cuáles empiezan en
 * una hoja nueva y, si el docente quiere, su propio nombre e indicación para cada una. Lo vacío lo escribe
 * Cátedra solo (según el tipo y lo que traigan sus preguntas); la vista previa manda esos textos para
 * mostrarlos como sugerencia. La indicación va plegada: solo se despliega si se pide o ya tiene texto.
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
  let saltos = [];          // tipos cuya parte empieza en una hoja nueva
  const abiertas = new Set();   // tipos con la indicación desplegada

  const lista = () => $('pdf-partes-lista');
  const presentes = () => tiposEnOrden(questions, orden);
  const automatica = t => automaticas[t] || { nombre: NOMBRES_PARTE[t] || 'PREGUNTAS', indicacion: '' };

  /** Las sugerencias (texto en gris) y el botón de copiar, sin redibujar: no se pierde lo que se está escribiendo. */
  function sugerencias() {
    lista().querySelectorAll('.parte-fila').forEach(fila => {
      const a = automatica(fila.dataset.tipo);
      const indicacion = fila.querySelector('.parte-indicacion');
      fila.querySelector('.parte-nombre').placeholder = a.nombre;
      indicacion.placeholder = a.indicacion || 'Indicación automática';
      fila.querySelector('.parte-copiar').hidden = indicacion.hidden || !a.indicacion || !!indicacion.value.trim();
    });
  }

  function pintar() {
    const tipos = presentes();
    const boton = (clase, icono, texto, activo) => `<button type="button" class="btn btn-icon ${clase}" aria-label="${texto}" title="${texto}"${activo ? '' : ' disabled'}><i data-lucide="${icono}" style="width:15px;height:15px;" aria-hidden="true"></i></button>`;
    lista().innerHTML = tipos.map((t, i) => {
      const propio = textos[t] || {};
      const cual = `la parte ${ROMANOS[i]} (${NOMBRES_PARTE[t] || t})`;
      const abierta = abiertas.has(t) || !!(propio.indicacion || '').trim();
      return `<li class="parte-fila" data-tipo="${esc_html(t)}">
        <div class="parte-cab">
          <span class="parte-num">${ROMANOS[i]}</span>
          <input type="text" class="form-input parte-nombre" maxlength="${LIMITE_NOMBRE_PARTE}" autocomplete="off" value="${esc_html(propio.nombre || '')}" aria-label="Nombre de ${esc_html(cual)}">
          ${boton('parte-subir', 'arrow-up', `Subir ${esc_html(cual)}`, i > 0)}
          ${boton('parte-bajar', 'arrow-down', `Bajar ${esc_html(cual)}`, i < tipos.length - 1)}
        </div>
        <div class="parte-extras">
          <label class="parte-salto-rotulo"><input type="checkbox" class="parte-salto"${saltos.includes(t) ? ' checked' : ''} aria-label="Empezar en hoja nueva ${esc_html(cual)}"> En hoja nueva</label>
          <button type="button" class="text-link parte-ver" aria-expanded="${abierta}">${abierta ? 'Ocultar indicación' : 'Cambiar indicación'}</button>
        </div>
        <textarea class="form-input parte-indicacion" rows="3" maxlength="${LIMITE_INDICACION_PARTE}" aria-label="Indicación de ${esc_html(cual)}"${abierta ? '' : ' hidden'}>${esc_html(propio.indicacion || '')}</textarea>
        <button type="button" class="text-link parte-copiar" hidden>Editar a partir del texto automático</button>
      </li>`;
    }).join('');
    crearIconos(lista());
    sugerencias();
  }

  /** ¿Se dividen las partes? Sin partes no hay nada que ordenar ni cuadro de puntos. */
  function activar() {
    const f = $('pdf-form').elements;
    $('pdf-partes-cuerpo').hidden = !f.partes.checked;
    f.cuadro_puntos.disabled = !f.partes.checked;
  }

  function iniciar() {
    // Corre antes que el oyente del formulario: cuando este lee los datos, lo escrito ya está anotado.
    lista().addEventListener('input', e => {
      const fila = e.target.closest('.parte-fila');
      if (!fila) return;
      const t = fila.dataset.tipo;
      if (e.target.classList.contains('parte-salto')) {
        saltos = e.target.checked ? [...new Set([...saltos, t])] : saltos.filter(x => x !== t);
        return;
      }
      textos[t] = { nombre: fila.querySelector('.parte-nombre').value, indicacion: fila.querySelector('.parte-indicacion').value };
      sugerencias();
    });
    lista().addEventListener('click', e => {
      const boton = e.target.closest('button');
      const fila = boton && boton.closest('.parte-fila');
      if (!fila) return;
      const t = fila.dataset.tipo;
      if (boton.classList.contains('parte-ver')) {
        const area = fila.querySelector('.parte-indicacion');
        area.hidden = !area.hidden;
        if (area.hidden) abiertas.delete(t);
        else abiertas.add(t);
        boton.setAttribute('aria-expanded', String(!area.hidden));
        boton.textContent = area.hidden ? 'Cambiar indicación' : 'Ocultar indicación';
        sugerencias();
        if (!area.hidden) area.focus();
        return;
      }
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
      saltos = [];
      abiertas.clear();
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
      abiertas.clear();
      Object.keys(automaticas).forEach(k => delete automaticas[k]);
      pintar();
    },
    /** Pone el orden, los textos y las hojas nuevas (de lo recordado o de un perfil). */
    llenar(nuevoOrden, nuevosTextos, nuevosSaltos) {
      orden = ordenDePartesValido(nuevoOrden);
      textos = textosDePartesValidos(nuevosTextos);
      saltos = ordenDePartesValido(nuevosSaltos);
      pintar();
    },
    leer: () => ({ orden_partes: [...orden], textos_partes: textosDePartesValidos(textos), saltos_partes: [...saltos] }),
    /** Lo que dijo la vista previa que escribiría en cada parte: [{ tipo, nombre, indicacion }]. */
    sugerir(partes) {
      if (!Array.isArray(partes)) return;
      partes.forEach(p => { if (p && typeof p.tipo === 'string') automaticas[p.tipo] = { nombre: String(p.nombre || ''), indicacion: String(p.indicacion || '') }; });
      sugerencias();
    },
  };
}
