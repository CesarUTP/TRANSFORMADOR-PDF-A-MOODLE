/**
 * sugerencias.js — «Sugerir respuesta con IA» (IA asistida, 2.0).
 *
 * Cuando la clave del documento no trae la respuesta de una pregunta, la IA puede
 * PROPONERLA. Reglas del producto que aquí se cumplen:
 *   · nunca se aplica sola: se muestra la propuesta (con su motivo) y solo «Aceptar»
 *     la pone en la tarjeta;
 *   · queda marcada: la pregunta sale con origen «Sugerida por IA — verifica» y
 *     confianza baja (y entra en «Revisar primero») mientras el docente no la edite;
 *   · es reversible: «Deshacer» devuelve la respuesta que había.
 * El servidor valida la propuesta contra las opciones de la pregunta (backend/ayuda_ia.py).
 */
import { apiFetch } from '../api.js';
import { notificar } from '../estado.js';
import { showToast } from '../ui/toast.js';
import { crearIconos, esc_html } from '../util.js';
import { collectEditorData } from './tarjetas.js';
import { describirSugerencia } from './sugerencias-logica.js';

const MAX_SIMULTANEAS = 2;
let enCurso = 0;

const tarjetas = () => Array.from(document.querySelectorAll('#editor-questions-container .editor-card'));

// ── Aplicar la propuesta a la tarjeta, y poder deshacerla ─────────────────
const CONTROLES = '.q-opt-correct, .q-ans, .q-sa-answer, .q-nu-answer, .pair-right, .cloze-option-row input[type="radio"], .cloze-option-row input[type="checkbox"]';

/** Foto de los controles que definen la respuesta (para «Deshacer»). */
function fotoRespuesta(card) {
  return Array.from(card.querySelectorAll(CONTROLES)).map(el => ({ el, checked: el.checked, value: el.value }));
}

function restaurar(card, foto) {
  foto.forEach(({ el, checked, value }) => {
    if (el.type === 'checkbox' || el.type === 'radio') el.checked = checked; else el.value = value;
  });
  delete card.dataset.firmaSugerida;
  avisarCambio(card);
}

function avisarCambio(card) {
  card.dispatchEvent(new Event('change', { bubbles: true }));
  notificar('respuesta sugerida');
}

/** Pone la propuesta en los controles de la tarjeta. Devuelve false si no pudo. */
export function aplicarSugerencia(card, tipo, sug) {
  if (tipo === 'multichoice') {
    const letras = new Set(sug.letras);
    card.querySelectorAll('.q-opt-correct').forEach(cb => { cb.checked = letras.has(cb.dataset.letter); });
  } else if (tipo === 'truefalse') {
    const sel = card.querySelector('.q-ans');
    if (!sel) return false;
    sel.value = sug.respuesta;
  } else if (tipo === 'shortanswer' || tipo === 'numerical') {
    const campo = card.querySelector('.q-sa-answer, .q-nu-answer');
    if (!campo) return false;
    campo.value = sug.respuesta;
  } else if (tipo === 'matching') {
    // Cada fila empareja un elemento de la columna A con su pareja: la propuesta
    // cambia QUÉ pareja lleva cada fila, con los mismos textos que ya hay.
    const filas = Array.from(card.querySelectorAll('.matching-pair-row'));
    const derechas = filas.map(f => f.querySelector('.pair-right').value);
    for (const [n, letra] of Object.entries(sug.pares)) {
      const fila = filas[Number(n) - 1];
      const origen = letra.charCodeAt(0) - 97;
      if (!fila || origen < 0 || origen >= derechas.length) return false;
      fila.querySelector('.pair-right').value = derechas[origen];
    }
  } else if (tipo === 'cloze') {
    const huecos = Array.from(card.querySelectorAll('.cloze-blank-card'));
    for (const [letra, idx] of Object.entries(sug.huecos)) {
      const hueco = huecos[letra.charCodeAt(0) - 65];
      const filas = hueco ? Array.from(hueco.querySelectorAll('.cloze-option-row')) : [];
      if (!filas[idx]) return false;
      filas.forEach((f, k) => { const m = f.querySelector('input[type="radio"], input[type="checkbox"]'); if (m) m.checked = k === idx; });
    }
  } else {
    return false;
  }
  return true;
}

// ── La propuesta en pantalla ──────────────────────────────────────────────
function mostrarPropuesta(card, pos, pregunta, datos) {
  card.querySelector(':scope .q-ia-respuesta')?.remove();
  const tipo = datos.tipo;
  const texto = describirSugerencia(tipo, datos.sugerencia, pregunta);
  const box = document.createElement('div');
  // `q-ia-propuesta`: «Generar XML» avisa de las propuestas sin aceptar ni descartar.
  box.className = 'q-ia-propuesta q-ia-respuesta';
  box.setAttribute('role', 'group');
  box.setAttribute('aria-label', `Respuesta sugerida por la IA para la pregunta ${pos}`);
  box.innerHTML = `
    <p class="q-ia-cambios-titulo"><i data-lucide="wand-sparkles" aria-hidden="true"></i> Respuesta sugerida por la IA <span class="opcional">— no se aplica hasta que la aceptes</span></p>
    <p class="q-ia-cambios-texto"><strong>${esc_html(texto)}</strong></p>
    ${datos.motivo ? `<p class="card-note"><strong>Motivo:</strong> ${esc_html(datos.motivo)}</p>` : ''}
    <p class="card-note">El documento no traía esta respuesta: es una propuesta de la IA, verifícala con tu documento. Si la aceptas, queda marcada «Sugerida por IA».</p>
    <div class="q-ia-acciones">
      <button type="button" class="btn btn-success btn-sm q-ia-aceptar"><i data-lucide="check" style="width:14px;height:14px;"></i> Aceptar</button>
      <button type="button" class="btn btn-ghost btn-sm q-ia-descartar"><i data-lucide="x" style="width:14px;height:14px;"></i> Descartar</button>
    </div>`;
  card.querySelector('.q-sugerir').insertAdjacentElement('afterend', box);
  crearIconos(box);

  box.querySelector('.q-ia-aceptar').addEventListener('click', () => {
    const foto = fotoRespuesta(card);
    if (!aplicarSugerencia(card, tipo, datos.sugerencia)) {
      box.remove();
      showToast('No se pudo aplicar la propuesta a esta pregunta. Márcala tú.', 'error');
      return;
    }
    box.remove();
    // La firma de la respuesta recién puesta: mientras siga igual, el origen es «sugerida»;
    // si el docente la cambia después, pasa a «Editada por ti» (ver collectEditorData).
    const firmas = [];
    collectEditorData({ conImagenes: false, firmas });
    card.dataset.firmaSugerida = firmas[pos - 1];
    avisarCambio(card);
    showToast(`Respuesta sugerida aplicada en la pregunta ${pos}. Verifícala con tu documento`, 'success', {
      accion: { texto: 'Deshacer', alPulsar: () => { restaurar(card, foto); return null; } },
    });
  });
  box.querySelector('.q-ia-descartar').addEventListener('click', () => {
    box.remove();
    notificar('propuesta descartada');
  });
  box.querySelector('.q-ia-aceptar').focus({ preventScroll: true });
}

/** Acción del botón «Sugerir respuesta con IA» (data-accion="sugerirRespuesta"). */
export async function sugerirRespuesta(btn) {
  const card = btn.closest('.editor-card');
  if (!card || btn.disabled) return;
  if (enCurso >= MAX_SIMULTANEAS) {
    showToast(`Ya hay ${MAX_SIMULTANEAS} peticiones a la IA en curso. Espera a que termine una y vuelve a pulsar.`, 'info');
    return;
  }
  const pos = tarjetas().indexOf(card);
  const { questions, answer_key } = collectEditorData();
  const pregunta = questions[pos];
  if (!pregunta) return;

  const etiqueta = btn.querySelector('span');
  const textoBtn = etiqueta.textContent;
  btn.style.minWidth = `${btn.offsetWidth}px`;
  btn.disabled = true;
  btn.setAttribute('aria-busy', 'true');
  etiqueta.textContent = 'Pensando…';
  btn.querySelector('svg, i')?.classList.add('girando');
  enCurso++;
  try {
    const res = await apiFetch('/api/sugerir_respuesta', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pregunta, respuesta: answer_key[pos + 1] ?? null }),
    });
    const datos = await res.json().catch(() => ({}));
    if (!res.ok) {
      const d = datos.detail;
      throw new Error(typeof d === 'string' ? d : 'La IA no pudo responder. Intenta de nuevo.');
    }
    if (!card.isConnected) {
      showToast('La pregunta cambió mientras la IA respondía y su propuesta se descartó. Vuelve a pedirla.', 'info');
      return;
    }
    mostrarPropuesta(card, pos + 1, pregunta, datos);
  } catch (e) {
    showToast(e instanceof TypeError ? 'No se pudo conectar con la aplicación.' : e.message, 'error');
  } finally {
    enCurso--;
    btn.disabled = false;
    btn.removeAttribute('aria-busy');
    btn.style.minWidth = '';
    etiqueta.textContent = textoBtn;
    btn.querySelectorAll('.girando').forEach(el => el.classList.remove('girando'));
  }
}
