/**
 * compartido.js — el «Enunciado compartido» del editor: un marco que encierra su texto, sus imágenes y sus
 * preguntas, para que se vea qué va dentro y qué es independiente. Se crea desde las tarjetas para agregar
 * preguntas, se le agregan preguntas una a una y se puede plegar entero. La lógica está en compartido-logica.js.
 */
import { cambiarRango, contextoDe, empezarCompartido, imagenesDelEnunciado, imagenesQueTendria, limitesDeTramo, ponerImagenes, posicionEnCompartido, posicionesLibres, quitarTramo, rotuloDeTramo, tramoEn, tramosCompartidos, usarEnPregunta } from './compartido-logica.js';
import { bloqueDeImagenesHtml, imagenesDeEnunciado, MAX_POR_PREGUNTA } from './imagenes.js';
import { reordenar } from './orden-logica.js';
import { autoGrowTextarea, crearPreguntaNueva, irAPreguntaNueva, renderEditor, syncParseResultFromDOM, tarjetasParaCompartido } from './tarjetas.js';
import { abiertasEnOrden } from './plegado.js';
import { estado } from '../estado.js';
import { showToast } from '../ui/toast.js';
import { crearIconos, esc_html, scrollBehavior } from '../util.js';

const NOTA = 'En el PDF y el Word sale una sola vez, antes de sus preguntas. En Moodle va dentro de cada una. Si lo dejas vacío y sin imágenes, no sale.';
const CAMPO = 'Escribe el caso, texto o situación del que se pregunta. No escribas los números de las preguntas: se agregan solos.';

// Un grupo se reconoce por su texto (las posiciones cambian al borrar o mover). `_activo`: el grupo al que se
// le están agregando preguntas (sus tipos a la vista); `_plegados`: los que están recogidos.
let _activo = null;
const _plegados = new Set();

/** Una evaluación recién abierta empieza sin ningún enunciado activo ni plegado. */
export function reiniciarCompartidos() { _activo = null; _plegados.clear(); }

/** ¿Hay un enunciado esperando preguntas? Entonces el panel general para agregar no se muestra. */
export function hayCompartidoEnMarcha(grupos, pendiente) {
  return !!pendiente || grupos.some(t => t.texto === _activo);
}

const _icono = nombre => `<i data-lucide="${nombre}" style="width:15px;height:15px;" aria-hidden="true"></i>`;

/** Abre el marco de un grupo, con su cabecera (lo inserta renderEditor antes de su primera pregunta). */
export function abrirGrupoHtml(questions, tramo) {
  const { minimo, maximo } = limitesDeTramo(questions, tramo);
  const opciones = (a, b, elegida) => Array.from({ length: b - a + 1 }, (_, k) => a + k)
    .map(i => `<option value="${i}"${i === elegida ? ' selected' : ''}>${i + 1}</option>`).join('');
  const id = `compartido-${tramo.desde}`;
  const rotulo = esc_html(rotuloDeTramo(tramo));
  const plegado = _plegados.has(tramo.texto);
  const flecha = (dir, activo) => `<button type="button" class="btn btn-icon btn-mover btn-${dir}" data-accion="${dir}Grupo" data-este
          aria-label="${dir === 'subir' ? 'Subir' : 'Bajar'} el enunciado compartido con sus preguntas (${rotulo})"
          title="${dir === 'subir' ? 'Subir' : 'Bajar'} el grupo completo"${activo ? '' : ' disabled'}>${_icono(`arrow-${dir === 'subir' ? 'up' : 'down'}`)}</button>`;
  return `<div class="grupo-compartido${plegado ? ' plegado' : ''}" data-desde="${tramo.desde}" role="group" aria-label="Enunciado compartido: ${rotulo.toLowerCase()}">
  <section class="bloque-compartido" data-desde="${tramo.desde}" data-hasta="${tramo.hasta}" aria-labelledby="${id}-titulo">
    <div class="compartido-cabecera">
      <div class="compartido-titulo">
        <button type="button" class="btn btn-icon compartido-plegar" data-accion="plegarCompartido" data-este aria-expanded="${!plegado}"
          aria-label="${plegado ? 'Mostrar' : 'Plegar'} las preguntas de este enunciado (${rotulo.toLowerCase()})"
          title="${plegado ? 'Mostrar sus preguntas' : 'Plegar sus preguntas'}"><i data-lucide="chevron-down" aria-hidden="true"></i></button>
        <h3 id="${id}-titulo"><i data-lucide="text-quote" aria-hidden="true"></i> Enunciado compartido</h3>
      </div>
      <div class="compartido-rango">
        <label for="${id}-desde">De la pregunta</label>
        <select id="${id}-desde" class="form-input compartido-desde" data-accion-cambio="cambiarRangoCompartido" data-este>${opciones(minimo, tramo.hasta, tramo.desde)}</select>
        <label for="${id}-hasta">a la</label>
        <select id="${id}-hasta" class="form-input compartido-hasta" data-accion-cambio="cambiarRangoCompartido" data-este>${opciones(tramo.desde, maximo, tramo.hasta)}</select>
        ${flecha('subir', tramo.desde > 0)}
        ${flecha('bajar', tramo.hasta < questions.length - 1)}
        <button type="button" class="btn btn-icon btn-danger-text" data-accion="quitarCompartido" data-este
          aria-label="Quitar el enunciado compartido (${rotulo})" title="Quitar el enunciado compartido (las preguntas se quedan)">${_icono('trash-2')}</button>
      </div>
    </div>
    <textarea class="compartido-texto form-input" rows="3" aria-label="Texto del enunciado compartido (${rotulo})"
      placeholder="${CAMPO}">${esc_html(tramo.texto)}</textarea>
    ${bloqueDeImagenesHtml(imagenesDelEnunciado(questions[tramo.desde]))}
    <p class="card-note">${NOTA}</p>
  </section>`;
}

function _panelHtml(grupo, titulo, ayuda, { terminar = false, extra = '' } = {}) {
  return `<div class="elegir-tipo compartido-panel" data-grupo="${grupo}">
    <div class="add-head">
      <h3>${titulo}</h3>
      ${terminar ? `<button type="button" class="btn btn-ghost btn-sm" data-accion="terminarCompartido">${_icono('check')} Terminar enunciado compartido</button>` : ''}
    </div>
    <p>${ayuda}</p>
    ${tarjetasParaCompartido('Tipo de la pregunta nueva del enunciado compartido')}
    ${extra}
  </div>`;
}

/** Cierra el marco de un grupo: los tipos para agregarle preguntas (o el botón que los muestra) y su resumen. */
export function cerrarGrupoHtml(tramo) {
  const cuales = esc_html(rotuloDeTramo(tramo).toLowerCase());
  const pie = tramo.texto === _activo
    ? _panelHtml(tramo.desde, 'Agrega otra pregunta a este enunciado',
      'Elige el tipo. Queda dentro del enunciado compartido. Para escribir preguntas independientes, termina el enunciado.', { terminar: true })
    : `<div class="grupo-fin">
      <p><i data-lucide="corner-left-up" aria-hidden="true"></i> Aquí termina el enunciado compartido (${cuales})</p>
      <button type="button" class="btn btn-ghost btn-sm" data-accion="activarCompartido" data-arg-n="${tramo.desde}">${_icono('plus')} Agregar pregunta a este enunciado</button>
    </div>`;
  return `${pie}
    <button type="button" class="grupo-resumen" data-accion="plegarCompartido" data-este></button>
  </div>`;
}

/** El enunciado que todavía no tiene preguntas: su texto, sus imágenes y qué tipo de pregunta se le agrega. */
export function grupoPendienteHtml(questions, pendiente) {
  const libres = posicionesLibres(questions);
  const existentes = libres.length ? `<div class="compartido-existentes">
      <label for="compartido-usar">O ponlo en preguntas que ya tienes, empezando por la</label>
      <select id="compartido-usar" class="form-input" data-accion-cambio="usarCompartidoEn" data-este>
        <option value="">Elegir…</option>${libres.map(i => `<option value="${i}">${i + 1}</option>`).join('')}
      </select>
    </div>` : '';
  return `<div class="grupo-compartido es-pendiente" role="group" aria-label="Enunciado compartido nuevo">
  <section class="bloque-compartido es-pendiente" aria-labelledby="compartido-nuevo-titulo">
    <div class="compartido-cabecera">
      <div class="compartido-titulo"><h3 id="compartido-nuevo-titulo"><i data-lucide="text-quote" aria-hidden="true"></i> Enunciado compartido</h3></div>
      <div class="compartido-rango">
        <button type="button" class="btn btn-icon btn-danger-text" data-accion="quitarCompartidoPendiente"
          aria-label="Quitar el enunciado compartido" title="Quitar el enunciado compartido">${_icono('trash-2')}</button>
      </div>
    </div>
    <textarea class="compartido-texto form-input" rows="3" aria-label="Texto del enunciado compartido" placeholder="${CAMPO}">${esc_html(pendiente.texto)}</textarea>
    ${bloqueDeImagenesHtml(pendiente.images || [])}
    <p class="card-note">${NOTA}</p>
  </section>
  ${_panelHtml('pendiente', 'Agrega la primera pregunta de este enunciado', 'Elige el tipo. Queda dentro del enunciado compartido.', { extra: existentes })}
  </div>`;
}

// Vuelve a dibujar el editor conservando lo abierto y deja el foco donde se indique.
function _redibujar(selectorFoco) {
  renderEditor(estado.currentParseResult, { abiertas: abiertasEnOrden() });
  const foco = selectorFoco && document.querySelector(`#editor-questions-container ${selectorFoco}`);
  if (foco) foco.focus();
}

/** Lleva a un enunciado y pone el cursor en su texto. `cual`: 'pendiente' o un grupo. */
export function irACompartido(cual) {
  const selector = cual === 'pendiente' ? '.bloque-compartido.es-pendiente' : `.bloque-compartido[data-desde="${cual.desde}"]`;
  const bloque = document.querySelector(`#editor-questions-container ${selector}`);
  if (!bloque) return;
  bloque.scrollIntoView({ behavior: scrollBehavior(), block: 'start' });
  bloque.querySelector('.compartido-texto').focus({ preventScroll: true });
}

/** La tarjeta «Enunciado compartido»: crea el espacio para su texto, aún sin preguntas. */
export function nuevoCompartido() {
  syncParseResultFromDOM();
  const cual = empezarCompartido(estado.currentParseResult);
  _activo = cual === 'pendiente' ? null : cual.texto;
  if (cual !== 'pendiente') _plegados.delete(cual.texto);
  renderEditor(estado.currentParseResult);
  irACompartido(cual);
}

/** Uno de los tipos de un enunciado: agrega esa pregunta al final de su grupo. */
export function agregarEnCompartido(boton) {
  const grupo = boton.closest('[data-grupo]')?.dataset.grupo;
  const abiertas = abiertasEnOrden();
  syncParseResultFromDOM();
  const res = estado.currentParseResult;
  const tramo = grupo === 'pendiente' ? null : tramoEn(res.questions, Number(grupo));
  const texto = tramo ? tramo.texto : res.compartido_pendiente?.texto;
  if (typeof texto !== 'string') return;
  const nueva = crearPreguntaNueva(boton.dataset.tipo, res.questions.length + 1);
  if (!nueva) return;
  nueva.pregunta.data.contexto = texto;
  ponerImagenes(nueva.pregunta, tramo ? imagenesDelEnunciado(res.questions[tramo.desde]) : res.compartido_pendiente.images || []);
  const pos = posicionEnCompartido(res.questions, tramo);
  const orden = [...res.questions];
  orden.splice(pos, 0, nueva.pregunta);
  reordenar(res, orden, new Map([[nueva.pregunta, nueva.clave]]));
  if (!tramo) delete res.compartido_pendiente;
  _activo = texto;
  abiertas.splice(pos, 0, true);
  renderEditor(res, { abiertas });
  showToast(`Pregunta ${pos + 1} agregada al enunciado compartido`);
  irAPreguntaNueva(pos + 1);
}

/** «Agregar pregunta a este enunciado»: muestra sus tipos (y esconde el panel general). */
export function activarCompartido(desde) {
  syncParseResultFromDOM();
  const tramo = tramoEn(estado.currentParseResult.questions, desde);
  if (!tramo) return;
  _activo = tramo.texto;
  _redibujar();
  const panel = document.querySelector('#editor-questions-container .compartido-panel');
  panel?.scrollIntoView({ behavior: scrollBehavior(), block: 'center' });
  panel?.querySelector('.tipo-nuevo')?.focus({ preventScroll: true });
}

/** «Terminar enunciado compartido»: lo que se agregue después ya es independiente. */
export function terminarCompartido() {
  syncParseResultFromDOM();
  _activo = null;
  _redibujar();
  const general = document.querySelector('#editor-questions-container .elegir-tipo:not(.compartido-panel)');
  general?.scrollIntoView({ behavior: scrollBehavior(), block: 'center' });
  general?.querySelector('button')?.focus({ preventScroll: true });
}

// ── Plegar un enunciado con sus preguntas ───────────────────────────────

function _ponerPlegado(grupo, plegado) {
  const texto = grupo.querySelector('.compartido-texto')?.value ?? '';
  if (plegado) _plegados.add(texto);
  else _plegados.delete(texto);
  grupo.classList.toggle('plegado', plegado);
  const boton = grupo.querySelector('.compartido-plegar');
  if (boton) {
    boton.setAttribute('aria-expanded', String(!plegado));
    boton.title = plegado ? 'Mostrar sus preguntas' : 'Plegar sus preguntas';
    boton.setAttribute('aria-label', boton.getAttribute('aria-label').replace(/^(Mostrar|Plegar)/, plegado ? 'Mostrar' : 'Plegar'));
  }
  // Las tarjetas estaban ocultas: sus campos recalculan el alto al volver a verse.
  if (!plegado) grupo.querySelectorAll('textarea').forEach(autoGrowTextarea);
}

export function plegarCompartido(boton) {
  const grupo = boton.closest('.grupo-compartido');
  if (!grupo) return;
  const plegar = !grupo.classList.contains('plegado');
  _ponerPlegado(grupo, plegar);
  actualizarResumenesDeGrupos();
  // El botón del resumen desaparece al abrir: el foco pasa a la flecha de la cabecera.
  if (!plegar) grupo.querySelector('.compartido-plegar')?.focus({ preventScroll: true });
}

/** Si la tarjeta está en un enunciado plegado, se abre (para ir a ella desde el mapa o un aviso). */
export function mostrarSuGrupo(card) {
  const grupo = card?.closest('.grupo-compartido.plegado');
  if (grupo) _ponerPlegado(grupo, false);
}

/** «Abrir todas» también abre los enunciados plegados. */
export function desplegarCompartidos() {
  document.querySelectorAll('#editor-questions-container .grupo-compartido.plegado').forEach(g => _ponerPlegado(g, false));
}

/** Lo que un enunciado plegado dice de sus preguntas ocultas. */
export function actualizarResumenesDeGrupos() {
  document.querySelectorAll('#editor-questions-container .grupo-compartido:not(.es-pendiente)').forEach(grupo => {
    const resumen = grupo.querySelector(':scope > .grupo-resumen');
    if (!resumen) return;
    const cards = [...grupo.querySelectorAll(':scope > .editor-card')];
    const puntos = Math.round(cards.reduce((a, c) => a + (parseFloat(c.querySelector('.q-points')?.value) || 0), 0) * 100) / 100;
    const mal = cards.filter(c => c.dataset.issues).length;
    const revisar = cards.filter(c => !c.dataset.issues && c.dataset.review === '1').length;
    const html = `<i data-lucide="chevron-right" aria-hidden="true"></i>
      <span><strong>${cards.length === 1 ? '1 pregunta plegada' : `${cards.length} preguntas plegadas`}</strong> · ${String(puntos).replace('.', ',')} pts${
  mal ? ` · <span class="resumen-mal">${mal === 1 ? '1 incompleta' : `${mal} incompletas`}</span>` : ''}${
  revisar ? ` · <span class="resumen-revisar">${revisar} para revisar</span>` : ''}</span><em>Mostrar</em>`;
    if (resumen.dataset.html === html) return;
    resumen.dataset.html = html;
    resumen.innerHTML = html;
    crearIconos(resumen);
  });
}

// ── Cambiar qué preguntas abarca, o quitarlo ────────────────────────────

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
  const llena = _sinSitio(qs.slice(desde, hasta + 1), imagenesDelEnunciado(qs[tramo.desde]));
  if (llena) { _redibujar(`.bloque-compartido[data-desde="${tramo.desde}"] ${cual}`); _avisarSinSitio(llena); return; }
  const nuevo = cambiarRango(qs, tramo, desde, hasta);
  _redibujar(`.bloque-compartido[data-desde="${nuevo.desde}"] ${cual}`);
}

// La primera pregunta que no tendría sitio para las imágenes del enunciado además de las suyas.
const _sinSitio = (preguntas, imagenes) => preguntas.find(q => imagenesQueTendria(q, imagenes) > MAX_POR_PREGUNTA);
const _avisarSinSitio = q => showToast(`La pregunta ${q.num} no tiene sitio: admite ${MAX_POR_PREGUNTA} imágenes contando las del enunciado`, 'error');

/** «O ponlo en preguntas que ya tienes»: el enunciado pasa a esa pregunta; el resto se elige en su cabecera. */
export function usarCompartidoEn(select) {
  if (select.value === '') return;
  syncParseResultFromDOM();
  const res = estado.currentParseResult;
  const q = res.questions[Number(select.value)];
  if (q && _sinSitio([q], res.compartido_pendiente?.images || [])) { _redibujar(); _avisarSinSitio(q); return; }
  const tramo = usarEnPregunta(res, Number(select.value));
  if (!tramo) return;
  _activo = null;
  _redibujar(`.bloque-compartido[data-desde="${tramo.desde}"] .compartido-hasta`);
}

export function quitarCompartidoPendiente() {
  syncParseResultFromDOM();
  const quitado = estado.currentParseResult.compartido_pendiente;
  if (!quitado) return;
  delete estado.currentParseResult.compartido_pendiente;
  _redibujar();
  if (!quitado.texto.trim() && !(quitado.images || []).length) return;
  showToast('Enunciado compartido quitado', 'info', {
    accion: { texto: 'Deshacer', alPulsar: () => {
      syncParseResultFromDOM();
      estado.currentParseResult.compartido_pendiente = quitado;
      _redibujar();
    } },
  });
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
  const imagenes = imagenesDelEnunciado(qs[tramo.desde]).map(im => ({ ...im }));
  quitarTramo(qs, tramo);
  _redibujar();
  showToast('Enunciado compartido quitado', 'info', {
    accion: { texto: 'Deshacer', alPulsar: () => {
      syncParseResultFromDOM();
      estado.currentParseResult.questions.forEach(q => {
        if (contextoDe(q) !== null || !miembros.includes(huella(q))) return;
        q.data.contexto = tramo.texto;
        ponerImagenes(q, imagenes);
      });
      _redibujar();
    } },
  });
}

// ── Lo que se escribe o se adjunta en la cabecera ───────────────────────

// El texto de un bloque pasa a todas sus preguntas (collectEditorData copia `data` tal cual).
function _escribir(bloque, texto) {
  if (bloque.classList.contains('es-pendiente')) {
    const pendiente = estado.currentParseResult?.compartido_pendiente;
    if (pendiente) pendiente.texto = texto;
    return;
  }
  const grupo = bloque.closest('.grupo-compartido');
  grupo.querySelectorAll(':scope > .editor-card').forEach(card => {
    const q = estado.currentParseResult?.questions?.[Number(card.dataset.idx)];
    if (!q) return;
    // El grupo se reconoce por su texto: lo que estaba activo o plegado lo sigue estando.
    if (q.data.contexto === _activo && grupo.querySelector(':scope > .compartido-panel')) _activo = texto;
    q.data.contexto = texto;
  });
  if (grupo.classList.contains('plegado')) _plegados.add(texto);
}

/** Un grupo se esconde cuando el filtro esconde todas sus preguntas. */
export function actualizarVisibilidadCompartidos() {
  document.querySelectorAll('#editor-questions-container .grupo-compartido:not(.es-pendiente)').forEach(grupo => {
    const visible = [...grupo.querySelectorAll(':scope > .editor-card')].some(c => c.style.display !== 'none');
    const estabaOculto = grupo.style.display === 'none';
    grupo.style.display = visible ? '' : 'none';
    if (visible && estabaOculto) grupo.querySelectorAll('.compartido-texto').forEach(autoGrowTextarea);
  });
}

/** Tras dibujar el editor: marca las tarjetas que están en un grupo y ajusta el alto de los textos. */
export function prepararCompartidos(container) {
  container.querySelectorAll('.grupo-compartido > .editor-card').forEach(c => c.classList.add('en-grupo'));
  container.querySelectorAll('.compartido-texto').forEach(autoGrowTextarea);
  actualizarResumenesDeGrupos();
}

export function registrarCompartidos(container) {
  container.addEventListener('input', e => {
    if (e.target.classList.contains('compartido-texto')) _escribir(e.target.closest('.bloque-compartido'), e.target.value);
    // Al agregar o quitar una imagen del enunciado que aún no tiene preguntas, se guarda con él.
    if (e.target.classList.contains('bloque-compartido') && e.target.classList.contains('es-pendiente')) {
      const pendiente = estado.currentParseResult?.compartido_pendiente;
      if (pendiente) pendiente.images = imagenesDeEnunciado(e.target);
    }
  });
}
