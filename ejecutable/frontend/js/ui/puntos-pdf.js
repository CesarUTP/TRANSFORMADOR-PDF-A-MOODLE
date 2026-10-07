/**
 * puntos-pdf.js (interfaz) — el panel «Puntos en el PDF» de la pantalla de exportar (2.7): con «Puntos enteros»
 * activado, el PDF lleva su propia copia de los puntos, en enteros y con el mismo total; aquí se ve qué valdrá cada
 * pregunta, en qué se distingue de Moodle y, si se quiere, se cambia un valor a mano o el total del PDF.
 *
 * El reparto vive en ../puntos-pdf.js (lógica pura). Nada de esto cambia el editor ni el Moodle XML.
 */
import { esc_html } from '../util.js';
import { examenConPuntos, puntosParaPdf } from '../puntos-pdf.js';

const $ = id => document.getElementById(id);
const fmt = n => String(Math.round(Number(n) * 100) / 100).replace('.', ',');
const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;

export function crearPuntosPdf({ alCambiar }) {
  let examen = null;
  let total = null;          // el total del PDF que eligió el docente (null = el del editor, redondeado)
  let ediciones = {};        // { num: entero } lo que cambió a mano

  const resultado = () => puntosParaPdf(examen, { total, ediciones });

  function pintarAvisos(r) {
    const nota = $('pdf-pts-nota');
    const lineas = [];
    lineas.push(`En el PDF cada pregunta vale un número entero y el PDF suma ${fmt(r.total)} puntos.`);
    if (!r.diferencias.length && r.total === r.totalEditor) {
      lineas.push('Coincide con los puntos de Moodle.');
    } else {
      const ej = r.diferencias[0];
      const partes = [];
      if (ej) partes.push(`la pregunta ${ej.num} vale ${fmt(ej.moodle)} en Moodle y ${fmt(ej.pdf)} en el PDF`);
      partes.push(r.total === r.totalEditor ? `el total es el mismo (${fmt(r.total)})` : `el total de Moodle es ${fmt(r.totalEditor)} y el del PDF ${fmt(r.total)}`);
      lineas.push(`En Moodle las preguntas conservan los puntos del editor: ${partes.join('; ')}.`);
    }
    const nEditadas = Object.keys(ediciones).length;
    if (nEditadas) lineas.push(`Cambiaste a mano ${plural(nEditadas, 'pregunta', 'preguntas')}: el total del PDF es la suma de lo que ves en la lista.`);
    else if (!r.uniforme) lineas.push('No se pueden repartir esos puntos en iguales dentro de cada tipo: algunas preguntas del mismo tipo valen 1 punto más (las primeras).');
    if (r.ceros > 0) lineas.push(`${plural(r.ceros, 'pregunta quedó', 'preguntas quedaron')} en 0 puntos: el total es menor que el número de preguntas. Sube el total del PDF.`);
    nota.replaceChildren(...lineas.map((t, i) => {
      const p = document.createElement('p');
      p.textContent = t;
      if (i === 0) p.className = 'pts-principal';
      if (r.ceros > 0 && t.includes('0 puntos')) p.className = 'pts-alerta';
      return p;
    }));
    const alt = $('pdf-pts-alt');
    const botones = [];
    if (total !== null) botones.push(`<button type="button" class="btn btn-ghost btn-sm" data-pts-total="">Volver a ${esc_html(fmt(r.totalEditor))} puntos</button>`);
    r.alternativas.forEach(a => botones.push(`<button type="button" class="btn btn-ghost btn-sm" data-pts-total="${a.total}">Usar ${a.total} puntos (todas iguales por tipo)</button>`));
    alt.innerHTML = botones.join('');
    alt.hidden = !botones.length;
    $('pdf-pts-detalle-resumen').textContent = `${fmt(r.total)} pts`;
  }

  function pintarLista(r) {
    $('pdf-pts-lista').replaceChildren(...examen.questions.map(q => {
      const li = document.createElement('li');
      li.className = 'ver-pregunta';
      const enunciado = String((q.data && q.data.stem) || '').replace(/\s+/g, ' ').trim();
      const moodle = Number(q.points);
      const difiere = Number.isFinite(moodle) && Math.abs(moodle - r.porNum[q.num]) > 0.005;
      li.innerHTML = `<span class="ver-pregunta-num">${esc_html(q.num)}.</span>`
        + `<span class="ver-pregunta-texto" title="${esc_html(enunciado)}">${esc_html(enunciado.slice(0, 60) || '(sin enunciado)')}`
        + `${difiere ? `<small>Moodle: ${esc_html(fmt(moodle))}</small>` : ''}</span>`
        + `<input type="number" class="form-input" min="0" step="1" data-num="${esc_html(q.num)}" value="${r.porNum[q.num]}" aria-label="Puntos de la pregunta ${esc_html(q.num)} en el PDF">`;
      return li;
    }));
  }

  /** Muestra u oculta el panel y lo pone al día. `visible` = «Puntos enteros» activo y sin versiones. */
  function pintar(visible) {
    const panel = $('pdf-pts-panel');
    panel.hidden = !visible || !examen;
    if (panel.hidden) return;
    const r = resultado();
    pintarAvisos(r);
    if (!panel.dataset.lista || panel.dataset.lista !== JSON.stringify([total, ediciones])) {
      pintarLista(r);
      panel.dataset.lista = JSON.stringify([total, ediciones]);
    }
  }

  function cambiarTotal(nuevo) {
    total = nuevo;
    ediciones = {};
    $('pdf-pts-panel').dataset.lista = '';
    alCambiar();
  }

  function valorEditado(ev) {
    const inp = ev.target.closest('input[data-num]');
    if (!inp) return;
    const valor = Number(String(inp.value).replace(',', '.'));
    if (!Number.isInteger(valor) || valor < 0) return;      // un decimal se espera: al salir se redondea
    const num = Number(inp.dataset.num);
    const sinEditar = puntosParaPdf(examen, { total }).porNum[num];
    if (valor === sinEditar) delete ediciones[num]; else ediciones[num] = valor;
    // La lista no se rehace mientras se escribe; solo la suma y las notas.
    $('pdf-pts-panel').dataset.lista = JSON.stringify([total, ediciones]);
    pintarAvisos(resultado());
    alCambiar();
  }

  function iniciar() {
    const panel = $('pdf-pts-panel');
    panel.addEventListener('click', ev => {
      const b = ev.target.closest('[data-pts-total]');
      if (!b) return;
      cambiarTotal(b.dataset.ptsTotal === '' ? null : Number(b.dataset.ptsTotal));
    });
    panel.addEventListener('input', valorEditado);
    panel.addEventListener('change', ev => {
      const inp = ev.target.closest('input[data-num]');
      if (!inp) return;
      const valor = Number(String(inp.value).replace(',', '.'));
      if (Number.isFinite(valor) && valor >= 0 && !Number.isInteger(valor)) { inp.value = String(Math.round(valor)); valorEditado({ target: inp }); }
      else if (!Number.isFinite(valor) || valor < 0) inp.value = String(resultado().porNum[Number(inp.dataset.num)]);
    });
  }

  return {
    iniciar, pintar,
    abrir(ex) { examen = ex; total = null; ediciones = {}; $('pdf-pts-panel').dataset.lista = ''; },
    cerrar() { examen = null; },
    /** El examen tal como va al PDF: las mismas preguntas con los puntos enteros (el original no se toca). */
    examenParaPdf: () => examenConPuntos(examen, resultado()),
  };
}
