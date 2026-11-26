/**
 * compartido.js — el bloque «Enunciado compartido» del editor: se dibuja encima de la primera pregunta de
 * su grupo, con su texto y las preguntas que abarca. La lógica está en compartido-logica.js.
 */
import { cambiarRango, contextoDe, crearTramo, limitesDeTramo, quitarTramo, rotuloDeTramo, tramoEn, tramosCompartidos } from './compartido-logica.js';
import { autoGrowTextarea, renderEditor, syncParseResultFromDOM } from './tarjetas.js';
import { abiertasEnOrden } from './plegado.js';
import { estado } from '../estado.js';
import { showToast } from '../ui/toast.js';
import { esc_html } from '../util.js';

/** El HTML de un bloque (lo inserta renderEditor antes de la tarjeta `tramo.desde`). */
export function bloqueCompartidoHtml(questions, tramo) {
  const { minimo, maximo } = limitesDeTramo(questions, tramo);
  const opciones = (a, b, elegida) => Array.from({ length: b - a + 1 }, (_, k) => a + k)
    .map(i => `<option value="${i}"${i === elegida ? ' selected' : ''}>${i + 1}</option>`).join('');
  const id = `compartido-${tramo.desde}`;
  const flecha = (dir, activo) => `<button type="button" class="btn btn-icon btn-mover btn-${dir}" data-accion="${dir}Grupo" data-este
          aria-label="${dir === 'subir' ? 'Subir' : 'Bajar'} el enunciado compartido con sus preguntas (${esc_html(rotuloDeTramo(tramo))})"
          title="${dir === 'subir' ? 'Subir' : 'Bajar'} el grupo completo"${activo ? '' : ' disabled'}>
          <i data-lucide="arrow-${dir === 'subir' ? 'up' : 'down'}" style="width:15px;height:15px;" aria-hidden="true"></i></button>`;
  return `<section class="bloque-compartido" data-desde="${tramo.desde}" data-hasta="${tramo.hasta}" aria-labelledby="${id}-titulo">
    <div class="compartido-cabecera">
      <h3 id="${id}-titulo"><i data-lucide="text-quote" aria-hidden="true"></i> Enunciado compartido</h3>
      <div class="compartido-rango">
        <label for="${id}-desde">De la pregunta</label>
        <select id="${id}-desde" class="form-input compartido-desde" data-accion-cambio="cambiarRangoCompartido" data-este>${opciones(minimo, tramo.hasta, tramo.desde)}</select>
        <label for="${id}-hasta">a la</label>
        <select id="${id}-hasta" class="form-input compartido-hasta" data-accion-cambio="cambiarRangoCompartido" data-este>${opciones(tramo.desde, maximo, tramo.hasta)}</select>
        ${flecha('subir', tramo.desde > 0)}
        ${flecha('bajar', tramo.hasta < questions.length - 1)}
        <button type="button" class="btn btn-icon btn-danger-text" data-accion="quitarCompartido" data-este
          aria-label="Quitar el enunciado compartido (${esc_html(rotuloDeTramo(tramo))})" title="Quitar el enunciado compartido (las preguntas se quedan)">
          <i data-lucide="trash-2" style="width:15px;height:15px;" aria-hidden="true"></i>
        </button>
      </div>
    </div>
    <textarea class="compartido-texto form-input" rows="3" aria-label="Texto del enunciado compartido (${esc_html(rotuloDeTramo(tramo))})"
      placeholder="Escribe el caso, texto o situación del que se pregunta. No escribas los números de las preguntas: se agregan solos.">${esc_html(tramo.texto)}</textarea>
    <p class="card-note">En el PDF y el Word sale una sola vez, antes de estas preguntas. En Moodle va dentro de cada una. Si lo dejas vacío, no sale.</p>
  </section>`;
}

const _tarjetas = () => Array.from(document.querySelectorAll('#editor-questions-container .editor-card'));

// Vuelve a dibujar el editor conservando lo abierto y deja el foco donde se indique.
function _redibujar(selectorFoco) {
  renderEditor(estado.currentParseResult, { abiertas: abiertasEnOrden() });
  const foco = selectorFoco && document.querySelector(`#editor-questions-container ${selectorFoco}`);
  if (foco) foco.focus();
}

export function crearCompartido(boton) {
  const pos = _tarjetas().indexOf(boton.closest('.editor-card'));
  if (pos < 0) return;
  const abiertas = abiertasEnOrden();
  syncParseResultFromDOM();
  const tramo = crearTramo(estado.currentParseResult.questions, pos);
  if (!tramo) return;
  renderEditor(estado.currentParseResult, { abiertas });
  document.querySelector(`.bloque-compartido[data-desde="${tramo.desde}"] .compartido-texto`)?.focus();
}

export function cambiarRangoCompartido(select) {
  const bloque = select.closest('.bloque-compartido');
  if (!bloque) return;
  const desde = Number(bloque.querySelector('.compartido-desde').value);
  const hasta = Number(bloque.querySelector('.compartido-hasta').value);
  const original = Number(bloque.dataset.desde);
  const cual = select.classList.contains('compartido-desde') ? '.compartido-desde' : '.compartido-hasta';
  syncParseResultFromDOM();
  const qs = estado.currentParseResult.questions;
  const tramo = tramoEn(qs, original);
  if (!tramo) return;
  const nuevo = cambiarRango(qs, tramo, desde, hasta);
  _redibujar(`.bloque-compartido[data-desde="${nuevo.desde}"] ${cual}`);
}

export function quitarCompartido(boton) {
  const bloque = boton.closest('.bloque-compartido');
  if (!bloque) return;
  const desde = Number(bloque.dataset.desde);
  syncParseResultFromDOM();
  const qs = estado.currentParseResult.questions;
  const tramo = tramoEn(qs, desde);
  if (!tramo) return;
  // Se recuerdan las preguntas (no sus posiciones) para poder deshacer aunque entre medias se borre alguna.
  const huella = q => JSON.stringify([q.type, q.data.stem ?? q.data.text, q.data.options, q.data.col_a]);
  const miembros = qs.slice(tramo.desde, tramo.hasta + 1).map(huella);
  quitarTramo(qs, tramo);
  _redibujar();
  showToast('Enunciado compartido quitado', 'info', {
    accion: { texto: 'Deshacer', alPulsar: () => {
      syncParseResultFromDOM();
      estado.currentParseResult.questions.forEach(q => {
        if (contextoDe(q) === null && miembros.includes(huella(q))) q.data.contexto = tramo.texto;
      });
      _redibujar();
    } },
  });
}

// Lo que se escribe en un bloque pasa a todas sus preguntas (collectEditorData copia `data` tal cual).
function _escribir(bloque, texto) {
  const tarjetas = _tarjetas();
  for (let i = Number(bloque.dataset.desde); i <= Number(bloque.dataset.hasta); i++) {
    const q = estado.currentParseResult?.questions?.[Number(tarjetas[i]?.dataset.idx)];
    if (q) q.data.contexto = texto;
  }
}

/** Un bloque se esconde cuando el filtro esconde todas sus preguntas. */
export function actualizarVisibilidadCompartidos() {
  const tarjetas = _tarjetas();
  document.querySelectorAll('#editor-questions-container .bloque-compartido').forEach(bloque => {
    const suyas = tarjetas.slice(Number(bloque.dataset.desde), Number(bloque.dataset.hasta) + 1);
    const visible = suyas.some(c => c.style.display !== 'none');
    const estabaOculto = bloque.style.display === 'none';
    bloque.style.display = visible ? '' : 'none';
    if (visible && estabaOculto) bloque.querySelectorAll('textarea').forEach(autoGrowTextarea);
  });
}

/** Tras dibujar el editor: marca las tarjetas que están en un grupo y ajusta el alto de los textos. */
export function prepararCompartidos(container, questions) {
  const tarjetas = Array.from(container.querySelectorAll('.editor-card'));
  tramosCompartidos(questions).forEach(t => {
    for (let i = t.desde; i <= t.hasta; i++) tarjetas[i]?.classList.add('en-grupo');
  });
  tarjetas.forEach(c => { const b = c.querySelector('.q-compartir'); if (b && c.classList.contains('en-grupo')) b.hidden = true; });
  container.querySelectorAll('.compartido-texto').forEach(autoGrowTextarea);
}

export function registrarCompartidos(container) {
  container.addEventListener('input', e => {
    if (e.target.classList.contains('compartido-texto')) _escribir(e.target.closest('.bloque-compartido'), e.target.value);
  });
}
