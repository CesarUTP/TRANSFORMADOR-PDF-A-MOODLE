/**
 * versiones.js — la sección «Versiones del examen» de la pantalla de exportar el PDF (2.5): el docente elige
 * cuántas versiones quiere y cuántas preguntas lleva cada una (al azar o por tipo), se sortean, y cada versión
 * se revisa en su pestaña (con su vista previa y sus puntos, que se pueden ajustar) antes de descargar el ZIP.
 *
 * Aquí solo vive lo que toca el DOM; el sorteo, el orden y los puntos están en ../versiones-logica.js y el PDF de
 * cada versión lo arma backend/versiones.py a partir del examen completo (la clave nunca viaja copiada).
 */
import { confirmar } from './confirmar.js';
import { cuerpoPdf } from './exportar-pdf-logica.js';
import { crearIconos, esc_html } from '../util.js';
import {
  MAX_VERSIONES, composicion, cuadra, cuotasProporcionales, examenDeVersion, numsEnOrden, planInicial, preguntasPorVersion,
  preguntasRepetidas, puntosDeVersion, repartirVersion, resumenPorTipo, revisarPlan, semillaNueva, sortear, totalDeVersion, versionesParaEnviar,
} from '../versiones-logica.js';

const $ = id => document.getElementById(id);
const fmt = n => String(Math.round(Number(n) * 100) / 100).replace('.', ',');
const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;

export function crearVersiones({ alCambiar }) {
  let examen = null;
  let plan = null;
  let versiones = [];          // lo sorteado: [{ etiqueta, nums, semilla, puntos }]
  let actual = 0;
  let desfasado = false;       // el plan cambió después de sortear
  let temporizadorPuntos = null;

  const tipos = () => (examen ? resumenPorTipo(examen.questions) : []);
  const activa = () => !!examen && $('pdf-ver-activar').checked;
  const listas = () => activa() && versiones.length > 0 && !desfasado;
  const opciones = datos => ({ partes: !datos || datos.partes !== false, barajarPreguntas: $('pdf-ver-barajar').checked });
  const objetivo = () => Number($('pdf-ver-objetivo').value);

  // ── El plan (lo que el docente pide) ────────────────────────────────────
  function pintarTipos() {
    const caja = $('pdf-ver-tipos');
    caja.replaceChildren(...tipos().map(t => {
      const fila = document.createElement('div');
      fila.className = 'ver-tipo';
      fila.innerHTML = `<span class="ver-tipo-nombre">${esc_html(t.nombre)}<small>Hay ${t.cantidad} en el examen</small></span>`
        + `<input type="number" class="form-input" min="0" max="${t.cantidad}" step="1" data-tipo="${esc_html(t.tipo)}" aria-label="Cuántas de «${esc_html(t.nombre)}» en cada versión" value="${Number(plan.cuotas[t.tipo]) || 0}">`
        + `<button type="button" class="btn btn-quiet btn-sm" data-todas="${esc_html(t.tipo)}">Todas</button>`;
      return fila;
    }));
  }

  function pintarPlan() {
    $('pdf-ver-n').value = plan.versiones;
    $('pdf-ver-total').value = plan.total;
    $('pdf-ver-total').max = String(examen.questions.length);
    document.querySelectorAll('input[name="ver_modo"]').forEach(r => { r.checked = r.value === plan.modo; });
    $('pdf-ver-sin-repetir').checked = plan.sinRepetir;
    $('pdf-ver-total-caja').hidden = plan.modo === 'por_tipo';
    $('pdf-ver-tipos').hidden = plan.modo !== 'por_tipo';
    if (plan.modo === 'por_tipo') pintarTipos();
  }

  /** Lo que hay escrito en el formulario pasa al plan (sin corregirlo: revisarPlan dice qué no sirve). */
  function leerPlan() {
    plan.versiones = $('pdf-ver-n').value;
    plan.total = $('pdf-ver-total').value;
    const modo = document.querySelector('input[name="ver_modo"]:checked');
    const nuevo = modo ? modo.value : 'aleatorio';
    if (nuevo !== plan.modo) {
      plan.modo = nuevo;
      if (nuevo === 'por_tipo') {
        const k = Number(plan.total);
        plan.cuotas = cuotasProporcionales(tipos(), Number.isInteger(k) && k >= 1 ? Math.min(k, examen.questions.length) : Math.round(examen.questions.length / 2));
      } else {
        plan.total = Math.max(1, preguntasPorVersion({ ...plan, modo: 'por_tipo' }, tipos())) || plan.total;
        $('pdf-ver-total').value = plan.total;
      }
      pintarPlan();
    }
    plan.sinRepetir = $('pdf-ver-sin-repetir').checked;
    if (plan.modo === 'por_tipo') {
      document.querySelectorAll('#pdf-ver-tipos input[data-tipo]').forEach(inp => { plan.cuotas[inp.dataset.tipo] = inp.value; });
    }
    return plan;
  }

  function pintarResumen() {
    const rev = revisarPlan(plan, examen.questions);
    const hay = examen.questions.length;
    const resumen = $('pdf-ver-resumen');
    const lista = $('pdf-ver-avisos');
    lista.replaceChildren();
    const aviso = (texto, clase = '') => { const li = document.createElement('li'); li.className = clase; li.textContent = texto; lista.append(li); };
    if (rev.errores.length) {
      resumen.textContent = '';
      rev.errores.forEach(e => aviso(e, 'error'));
    } else {
      const n = Number(plan.versiones);
      const usadas = Math.min(hay, n * rev.porVersion - rev.repiten);
      resumen.textContent = `${plural(n, 'versión', 'versiones')} de ${plural(rev.porVersion, 'pregunta', 'preguntas')}: se usan ${usadas} de las ${hay} del examen`
        + (rev.repiten > 0 ? '.' : plan.sinRepetir ? ', sin repetir ninguna.' : '.');
      rev.avisos.forEach(a => aviso(a));
      if (!plan.sinRepetir && n > 1 && rev.repiten === 0 && n * rev.porVersion <= hay) {
        aviso('«No repetir» está apagado: una misma pregunta puede salir en varias versiones.');
      }
    }
    if (desfasado) aviso('Cambiaste el plan: vuelve a sortear para que las versiones lo sigan.');
    $('btn-pdf-ver-sortear').disabled = rev.errores.length > 0;
    $('btn-pdf-ver-sortear-texto').textContent = versiones.length ? 'Sortear de nuevo' : 'Sortear las versiones';
  }

  // ── Las versiones sorteadas ─────────────────────────────────────────────
  function pintarPestanas() {
    const barra = $('pdf-ver-tabs');
    const hay = listas() || (activa() && versiones.length > 0);
    barra.hidden = !hay;
    $('pdf-ver-panel').hidden = !hay;
    if (!hay) return;
    barra.replaceChildren(...versiones.map((v, i) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'ver-tab' + (cuadra(v, examen.questions, objetivo()) ? '' : ' desajuste');
      b.dataset.i = String(i);
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', String(i === actual));
      b.tabIndex = i === actual ? 0 : -1;
      b.innerHTML = `Versión ${esc_html(v.etiqueta)}<small>${plural(v.nums.length, 'pregunta', 'preguntas')} · ${fmt(totalDeVersion(v, examen.questions))} pts</small>`;
      return b;
    }));
    pintarPanel();
  }

  function pintarPanel() {
    const v = versiones[actual];
    if (!v) return;
    const comp = composicion(v, examen.questions).map(c => `${c.nombre} ${c.cantidad}`).join(' · ');
    $('pdf-ver-composicion').textContent = `Versión ${v.etiqueta}: ${plural(v.nums.length, 'pregunta', 'preguntas')} (${comp}).`
      + (preguntasRepetidas(versiones) > 0 && versiones.length > 1 ? ` ${plural(preguntasRepetidas(versiones), 'pregunta sale', 'preguntas salen')} en más de una versión.` : '');
    pintarSuma();
    const puntos = puntosDeVersion(v, examen.questions);
    const porNum = new Map(examen.questions.map(q => [q.num, q]));
    $('pdf-ver-preguntas').replaceChildren(...numsEnOrden(v, examen.questions, opciones()).map((n, k) => {
      const q = porNum.get(n);
      const li = document.createElement('li');
      li.className = 'ver-pregunta';
      const enunciado = String((q.data && q.data.stem) || '').replace(/\s+/g, ' ').trim();
      li.innerHTML = `<span class="ver-pregunta-num">${k + 1}.</span>`
        + `<span class="ver-pregunta-texto" title="${esc_html(enunciado)}">${esc_html(enunciado.slice(0, 70) || '(sin enunciado)')}<small>#${n}</small></span>`
        + `<input type="number" class="form-input" min="0" step="any" data-num="${n}" value="${puntos[n]}" aria-label="Puntos de la pregunta ${k + 1}">`;
      return li;
    }));
  }

  function pintarSuma() {
    const v = versiones[actual];
    if (!v) return;
    const total = totalDeVersion(v, examen.questions);
    const meta = objetivo();
    const bien = cuadra(v, examen.questions, meta);
    const suma = $('pdf-ver-suma');
    suma.textContent = bien ? `La versión ${v.etiqueta} suma ${fmt(total)} puntos.` : `La versión ${v.etiqueta} suma ${fmt(total)} puntos y el total deseado es ${fmt(meta)}. Usa «Ajustar» o cambia los puntos de abajo.`;
    suma.classList.toggle('desajuste', !bien);
    $('pdf-ver-detalle-resumen').textContent = `${fmt(total)} pts`;
    const tab = $('pdf-ver-tabs').children[actual];
    if (tab) {
      tab.classList.toggle('desajuste', !bien);
      tab.querySelector('small').textContent = `${plural(v.nums.length, 'pregunta', 'preguntas')} · ${fmt(total)} pts`;
    }
  }

  function repintarTodo() {
    if (!examen) return;
    pintarResumen();
    pintarPestanas();
  }

  // ── Acciones ────────────────────────────────────────────────────────────
  async function sortearAhora() {
    leerPlan();
    if (revisarPlan(plan, examen.questions).errores.length) { pintarResumen(); return; }
    if (versiones.some(v => Object.keys(v.puntos).length)) {
      const ok = await confirmar({
        titulo: '¿Sortear de nuevo?',
        mensaje: 'Las versiones actuales se reemplazan y los puntos que cambiaste a mano se pierden.',
        confirmar: 'Sortear de nuevo',
        cancelar: 'Conservar las actuales',
      });
      if (!ok) return;
    }
    versiones = sortear(examen.questions, plan, semillaNueva());
    actual = 0;
    desfasado = false;
    repintarTodo();
    crearIconos($('pdf-versiones'));
    alCambiar();
    const primera = $('pdf-ver-tabs').querySelector('.ver-tab');
    if (primera) primera.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  function elegirPestana(i) {
    if (i < 0 || i >= versiones.length || i === actual) return;
    actual = i;
    [...$('pdf-ver-tabs').children].forEach((b, k) => { b.setAttribute('aria-selected', String(k === i)); b.tabIndex = k === i ? 0 : -1; });
    pintarPanel();
    alCambiar();
  }

  function ajustar(indice) {
    const meta = objetivo();
    if (!(meta > 0)) { $('pdf-ver-objetivo').focus(); return; }
    const modo = $('pdf-ver-reparto').value;
    (indice === null ? versiones : [versiones[indice]]).forEach(v => { v.puntos = repartirVersion(v, examen.questions, meta, modo); });
    pintarPestanas();
    alCambiar();
  }

  function puntosEditados(ev) {
    const inp = ev.target.closest('input[data-num]');
    if (!inp) return;
    const valor = Number(String(inp.value).replace(',', '.'));
    if (!Number.isFinite(valor) || valor < 0) return;
    versiones[actual].puntos[Number(inp.dataset.num)] = valor;
    pintarSuma();
    clearTimeout(temporizadorPuntos);
    temporizadorPuntos = setTimeout(alCambiar, 0);
  }

  function alEditarPlan(ev) {
    if (ev.target.closest('#pdf-ver-activar')) {
      $('pdf-ver-cuerpo').hidden = !activa();
      repintarTodo();
      alCambiar();
      return;
    }
    leerPlan();
    if (versiones.length) desfasado = true;
    pintarResumen();
    pintarPestanas();
    alCambiar();
  }

  // ── Lo que ve y usa el resto de la pantalla ─────────────────────────────
  function iniciar() {
    const zona = $('pdf-versiones');
    zona.addEventListener('input', ev => { if (ev.target.matches('#pdf-ver-n, #pdf-ver-total, #pdf-ver-tipos input')) alEditarPlan(ev); });
    zona.addEventListener('change', ev => { if (ev.target.matches('#pdf-ver-activar, input[name="ver_modo"], #pdf-ver-sin-repetir')) alEditarPlan(ev); else if (ev.target.matches('#pdf-ver-barajar')) { pintarPanel(); alCambiar(); } });
    zona.addEventListener('click', ev => {
      const todas = ev.target.closest('[data-todas]');
      if (todas) {
        const inp = zona.querySelector(`input[data-tipo="${CSS.escape(todas.dataset.todas)}"]`);
        const t = tipos().find(x => x.tipo === todas.dataset.todas);
        if (inp && t) { inp.value = String(t.cantidad); alEditarPlan({ target: inp }); }
        return;
      }
      if (ev.target.closest('#btn-pdf-ver-sortear')) sortearAhora();
    });
    const previa = $('pdf-previa');
    previa.addEventListener('click', ev => {
      const tab = ev.target.closest('.ver-tab');
      if (tab) { elegirPestana(Number(tab.dataset.i)); return; }
      if (ev.target.closest('#btn-pdf-ver-ajustar')) ajustar(actual);
      else if (ev.target.closest('#btn-pdf-ver-ajustar-todas')) ajustar(null);
    });
    previa.addEventListener('input', ev => {
      if (ev.target.closest('#pdf-ver-preguntas')) puntosEditados(ev);
      else if (ev.target.closest('#pdf-ver-objetivo')) { pintarPestanas(); }
    });
    $('pdf-ver-tabs').addEventListener('keydown', ev => {
      const salto = { ArrowRight: 1, ArrowLeft: -1 }[ev.key];
      if (!salto || !versiones.length) return;
      ev.preventDefault();
      const i = (actual + salto + versiones.length) % versiones.length;
      elegirPestana(i);
      $('pdf-ver-tabs').children[i].focus();
    });
  }

  /** Empieza con un examen nuevo: nada sorteado, el plan de siempre. */
  function abrir(ex) {
    examen = ex;
    plan = planInicial(ex.questions);
    versiones = [];
    actual = 0;
    desfasado = false;
    $('pdf-ver-activar').checked = false;
    $('pdf-ver-cuerpo').hidden = true;
    $('pdf-ver-barajar').checked = true;
    $('pdf-ver-objetivo').value = String(Math.round(Number(ex.total_points) * 100) / 100 || 100);
    $('pdf-ver-reparto').value = 'byType';
    // Con un solo tipo de pregunta o muy pocas, sacar versiones no tiene sentido: la sección se esconde.
    $('pdf-versiones').hidden = ex.questions.length < 2;
    pintarPlan();
    repintarTodo();
  }

  function cerrar() {
    examen = null;
    versiones = [];
  }

  /** Qué debe mostrar la vista previa: 'normal' (el examen entero), 'sin_sortear', 'desfasada' o 'version'. */
  function estadoVista() {
    if (!activa()) return 'normal';
    if (!versiones.length) return 'sin_sortear';
    return desfasado ? 'desfasada' : 'version';
  }

  /** El cuerpo para la vista previa de la versión que se está viendo. */
  function cuerpoVista(datos) {
    const v = versiones[actual];
    return cuerpoPdf(examenDeVersion(examen, v, opciones(datos)), { ...datos, version: v.etiqueta });
  }

  /** El cuerpo de POST /api/exportar_versiones: el examen completo y las versiones. */
  function cuerpoExportar(datos) {
    return { ...cuerpoPdf(examen, { ...datos, version: '' }), versiones: versionesParaEnviar(examen, versiones, opciones(datos)) };
  }

  /** Las versiones cuya suma no es el total deseado: [{ etiqueta, total }]. */
  function desajustes() {
    return versiones.filter(v => !cuadra(v, examen.questions, objetivo()))
      .map(v => ({ etiqueta: v.etiqueta, total: totalDeVersion(v, examen.questions) }));
  }

  return {
    iniciar, abrir, cerrar, activa, listas, estadoVista, cuerpoVista, cuerpoExportar, desajustes,
    objetivo, cantidad: () => versiones.length, resumen: () => ({ n: versiones.length, porVersion: versiones[0] ? versiones[0].nums.length : 0 }),
    MAX_VERSIONES,
  };
}
