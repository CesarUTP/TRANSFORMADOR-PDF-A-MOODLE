/**
 * orden.js — los botones «Subir», «Bajar» y «Duplicar» de cada pregunta y de cada enunciado compartido.
 * La lógica está en orden-logica.js.
 */
import { duplicarPregunta, moverGrupo, moverPregunta, reordenar } from './orden-logica.js';
import { renderEditor, syncParseResultFromDOM } from './tarjetas.js';
import { abiertasEnOrden } from './plegado.js';
import { estado } from '../estado.js';
import { showToast } from '../ui/toast.js';

const _tarjetas = () => Array.from(document.querySelectorAll('#editor-questions-container .editor-card'));

/**
 * Aplica un cambio de orden y vuelve a dibujar. La vista sigue a lo que se movió: el botón pulsado queda
 * donde estaba en la pantalla y con el foco, para poder pulsarlo varias veces seguidas.
 * `cambio(res)` devuelve el selector del elemento a seguir después de dibujar (o null si no cambió nada).
 */
function _cambiar(boton, cambio) {
  const antes = boton.getBoundingClientRect().top;
  const abiertas = abiertasEnOrden();
  syncParseResultFromDOM();
  const res = estado.currentParseResult;
  const previas = [...res.questions];
  const selector = cambio(res);
  if (!selector) return false;
  // Lo abierto y plegado va con cada pregunta (una copia hereda el de su original).
  const porPregunta = new Map(previas.map((q, i) => [q, abiertas[i]]));
  renderEditor(res, { abiertas: res.questions.map((q, i) => (porPregunta.has(q) ? porPregunta.get(q) : porPregunta.get(res.questions[i - 1]))) });
  const nuevo = document.querySelector(`#editor-questions-container ${selector}`);
  if (nuevo) {
    window.scrollBy({ top: nuevo.getBoundingClientRect().top - antes, behavior: 'auto' });
    // En un extremo el botón queda desactivado: el foco pasa a su pareja.
    (nuevo.disabled ? nuevo.parentElement.querySelector('button:not([disabled])') : nuevo)?.focus({ preventScroll: true });
  }
  return true;
}

function _mover(boton, dir) {
  const pos = _tarjetas().indexOf(boton.closest('.editor-card'));
  if (pos < 0) return;
  _cambiar(boton, res => {
    const m = moverPregunta(res.questions, pos, dir);
    if (!m) return null;
    reordenar(res, m.orden);
    return `.editor-card[data-qnum="${m.nueva + 1}"] .${dir < 0 ? 'btn-subir' : 'btn-bajar'}`;
  });
}

export const subirPregunta = boton => _mover(boton, -1);
export const bajarPregunta = boton => _mover(boton, 1);

function _moverBloque(boton, dir) {
  const desde = Number(boton.closest('.bloque-compartido')?.dataset.desde);
  _cambiar(boton, res => {
    const m = moverGrupo(res.questions, desde, dir);
    if (!m) return null;
    reordenar(res, m.orden);
    return `.bloque-compartido[data-desde="${m.nueva}"] .${dir < 0 ? 'btn-subir' : 'btn-bajar'}`;
  });
}

export const subirGrupo = boton => _moverBloque(boton, -1);
export const bajarGrupo = boton => _moverBloque(boton, 1);

export function duplicarTarjeta(boton) {
  const pos = _tarjetas().indexOf(boton.closest('.editor-card'));
  if (pos < 0) return;
  const hecho = _cambiar(boton, res => {
    const nueva = duplicarPregunta(res, pos);
    return nueva === null ? null : `.editor-card[data-qnum="${pos + 1}"] .btn-duplicar`;
  });
  if (hecho) showToast(`Pregunta ${pos + 1} duplicada: la copia es la ${pos + 2}. Revisa los puntos del total.`, 'info');
}
