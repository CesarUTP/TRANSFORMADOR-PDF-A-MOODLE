/**
 * procedencia.js — de dónde sale la respuesta de cada pregunta y qué tan segura es.
 *
 * Lógica pura (sin DOM, salvo el HTML que arma como texto): las pruebas de
 * pruebas.js la corren en Node y en el navegador. El backend escribe, dentro
 * del `data` de cada pregunta, campos OPCIONALES:
 *
 *   origen_respuesta  "documento" | "marca" | "ia" | "docente" | "sugerida"
 *   confianza         "alta" | "media" | "baja"
 *   page              página del original (entero, desde 1)
 *   recuadro          [x0, y0, x1, y1] de la pregunta en esa página (para la 2.0:
 *                     aquí no se dibuja, solo se conserva intacto)
 *
 * Sin ellos la tarjeta se ve como siempre. «docente» lo pone ESTE módulo cuando
 * el docente cambia la respuesta correcta (ver respuestaCambio): la clave o la
 * marca del documento mandan, y lo que toca el docente queda dicho.
 */
import { esc_html } from '../util.js';

export const ORIGENES = ['documento', 'marca', 'ia', 'docente', 'sugerida'];
export const CONFIANZAS = ['alta', 'media', 'baja'];

/** Nombre del filtro «Revisar primero» (se suma a los tipos de pregunta). */
export const FILTRO_REVISAR = 'revisar';
/** Filtro «Posibles problemas»: preguntas con un aviso de calidad (calidad.js). */
export const FILTRO_PROBLEMAS = 'problemas';

const ORIGEN = {
  documento: {
    texto: 'Clave del documento', icono: 'file-check', tono: 'neutral',
    tip: 'La respuesta correcta está escrita en la clave o en el texto del documento.',
  },
  marca: {
    texto: 'Marca del documento', icono: 'highlighter', tono: 'neutral',
    tip: 'La respuesta se tomó de una marca del documento (color, resaltado, subrayado, negrita o X), leída por el programa sin que la IA la interprete.',
  },
  ia: {
    texto: 'Interpretada por la IA — revisar', icono: 'sparkles', tono: 'aviso',
    tip: 'El documento no marca la respuesta: la propuso la IA. Confírmala con tu documento antes de generar el XML.',
  },
  sugerida: {
    texto: 'Sugerida por IA — verifica', icono: 'wand-sparkles', tono: 'aviso',
    tip: 'La clave no traía esta respuesta: la propuso la IA y tú la aceptaste. Verifícala con tu documento antes de generar el XML.',
  },
  docente: {
    texto: 'Editada por ti', icono: 'user-pen', tono: 'docente',
    tip: 'Cambiaste la respuesta correcta de esta pregunta. Ya no depende del documento ni de la IA.',
  },
};

const CONFIANZA = {
  alta: {
    texto: 'Confianza alta', icono: 'shield-check', tono: 'neutral',
    tip: 'Se leyó con claridad. Aun así, compárala con tu documento.',
  },
  media: {
    texto: 'Confianza media', icono: 'shield-half', tono: 'suave',
    tip: 'Hay alguna duda en la lectura o en la respuesta: conviene compararla con el documento.',
  },
  baja: {
    texto: 'Confianza baja', icono: 'shield-alert', tono: 'aviso',
    tip: 'Poco segura: revísala con el documento antes de generar el XML.',
  },
};

export const origenValido = (v) => ORIGENES.includes(v);
export const confianzaValida = (v) => CONFIANZAS.includes(v);
export const paginaValida = (v) => Number.isInteger(v) && v > 0;

/**
 * Las «chips» de procedencia de una pregunta, en el orden en que se muestran:
 * página, origen de la respuesta y confianza. Devuelve [] si no hay nada que
 * mostrar. `tipo` evita hablar de «respuesta» en un ensayo (no la tiene).
 */
export function chipsDeProcedencia(data, tipo) {
  const d = data && typeof data === 'object' ? data : {};
  const chips = [];
  if (paginaValida(d.page)) {
    chips.push({
      clave: 'pagina', texto: `Pág. ${d.page}`, icono: 'file-text', tono: 'neutral',
      tip: 'Página del documento original',
      aria: `Pág. ${d.page}, página del documento original`,
    });
  }
  const docente = d.origen_respuesta === 'docente';
  if (origenValido(d.origen_respuesta) && tipo !== 'essay') {
    const o = ORIGEN[d.origen_respuesta];
    chips.push({
      clave: 'origen', valor: d.origen_respuesta, texto: o.texto, icono: o.icono, tono: o.tono, tip: o.tip,
      aria: `Origen de la respuesta: ${o.texto}. ${o.tip}`,
    });
  }
  // Si el docente editó la respuesta, la confianza de la lectura original ya
  // no habla de lo que hay en pantalla: no se muestra.
  if (confianzaValida(d.confianza) && !docente) {
    const c = CONFIANZA[d.confianza];
    chips.push({
      clave: 'confianza', valor: d.confianza, texto: c.texto, icono: c.icono, tono: c.tono, tip: c.tip,
      aria: `${c.texto} en la respuesta. ${c.tip}`,
    });
  }
  return chips;
}

/**
 * Lo que la tarjeta muestra de verdad: la página y solo lo que se SALE de lo
 * normal. «Clave del documento», «Marca del documento» y «Confianza alta» son
 * el caso corriente y salen en casi todas las tarjetas, así que se omiten: lo
 * que queda a la vista (IA, editada por ti, confianza media o baja) es lo que
 * pide atención. El detalle completo sigue en chipsDeProcedencia.
 */
export function chipsVisibles(data, tipo) {
  return chipsDeProcedencia(data, tipo).filter(c =>
    c.clave === 'pagina'
    || (c.clave === 'origen' && (c.valor === 'ia' || c.valor === 'docente' || c.valor === 'sugerida'))
    || (c.clave === 'confianza' && c.valor !== 'alta'));
}

/**
 * HTML de la fila de chips ('' si no hay ninguna). Los íconos los dibuja crearIconos().
 * Con `original` (hay un PDF en esta sesión) el chip de la página es un BOTÓN que
 * abre la «Revisión con el original»; sin él (Historial, Word, TXT) es solo informativo.
 */
export function chipsHtml(chips, { original = false } = {}) {
  return chips.map(c => {
    const icono = `<i data-lucide="${esc_html(c.icono)}" aria-hidden="true"></i><span aria-hidden="true">${esc_html(c.texto)}</span>`;
    const clases = `proc-chip proc-${esc_html(c.tono)} proc-${esc_html(c.clave)}`;
    if (original && c.clave === 'pagina') {
      return `<button type="button" class="${clases} proc-boton" data-accion="verOriginal" data-este`
        + ` title="Ver esta pregunta en el documento original" aria-label="${esc_html(c.texto)}: ver esta pregunta en el documento original">${icono}</button>`;
    }
    return `<span class="${clases}" role="img" title="${esc_html(c.tip)}" aria-label="${esc_html(c.aria)}">${icono}</span>`;
  }).join('');
}

/**
 * Copia de una pregunta para armar lo que se envía al generar el XML, sin sus
 * imágenes (se leen de la tarjeta). Es la que conserva `origen_respuesta`,
 * `confianza`, `page` y `recuadro`: viajan dentro de `data`, que se copia entero.
 */
export function copiaSinImagenes(original) {
  const { images: _imagenes, ...datos } = (original && original.data) || {};
  return JSON.parse(JSON.stringify({ ...original, data: datos }));
}

// ── ¿La respuesta correcta cambió? ──────────────────────────────────────
/**
 * Resumen estable de la respuesta correcta de UNA tarjeta, para compararla con
 * la que tenía al dibujarse. Solo cuenta lo que cambia la respuesta: las letras
 * marcadas (no el texto de las opciones erróneas), V/F, los huecos de
 * «Completar» y su opción correcta, las parejas, el texto de respuesta corta o
 * el número. `p` trae lo que lee collectEditorData de la tarjeta.
 */
export function firmaRespuesta(tipo, p = {}) {
  const t = String(p.respuesta ?? '').trim();
  switch (tipo) {
    case 'multichoice': return `mc:${(p.letras || []).join(',')}`;
    case 'truefalse': return `tf:${t.toLowerCase()}`;
    case 'cloze': return `cl:${t}|${(p.huecos || []).join('¦')}`;
    case 'matching': return `mt:${JSON.stringify([p.colA || {}, p.colB || {}, p.pares || {}])}`;
    case 'essay': return 'es:';
    default: return `${tipo}:${t}`;
  }
}

/** ¿Cambió la respuesta desde que se dibujó la tarjeta? Sin referencia, nunca. */
export function respuestaCambio(firmaInicial, firmaActual) {
  if (typeof firmaInicial !== 'string' || typeof firmaActual !== 'string') return false;
  return firmaInicial !== firmaActual;
}

/**
 * Pone el origen «docente» en `data` si la respuesta cambió; si no, no toca nada
 * (un simple foco o clic nunca marca). Devuelve `data` (se modifica en su sitio).
 * `confianza`, `page` y `recuadro` se dejan EXACTAMENTE como estaban, salvo cuando la
 * respuesta es la que propuso la IA y el docente aceptó (`sugerida`): origen «sugerida»
 * y confianza baja.
 */
export function marcarSiCambio(data, cambio, sugerida = false) {
  if (cambio && data && typeof data === 'object') {
    if (sugerida) {
      // La respuesta es exactamente la que propuso la IA y el docente aceptó: queda dicho
      // (y con confianza baja: la IA no la leyó del documento, la propuso).
      data.origen_respuesta = 'sugerida';
      data.confianza = 'baja';
    } else {
      data.origen_respuesta = 'docente';
    }
  }
  return data;
}

// ── Qué revisar primero ─────────────────────────────────────────────────
/** Respuesta poco segura o propuesta por la IA, y que el docente aún no tocó. */
export function necesitaRevisarPrimero(data) {
  if (!data || data.origen_respuesta === 'docente') return false;
  return data.confianza === 'baja' || data.origen_respuesta === 'ia' || data.origen_respuesta === 'sugerida';
}

/** Por qué conviene revisarla primero (texto corto para el mapa del examen), o ''. */
export function motivoRevisarPrimero(data) {
  if (!necesitaRevisarPrimero(data)) return '';
  const ia = data.origen_respuesta === 'ia' || data.origen_respuesta === 'sugerida', baja = data.confianza === 'baja';
  if (ia && baja) return 'respuesta interpretada por la IA con confianza baja';
  return ia ? 'respuesta interpretada por la IA' : 'confianza baja en la respuesta';
}

/**
 * Cualquier motivo para marcar la pregunta «para revisar» (mapa del examen y
 * salto con R): los avisos de siempre, más lo anterior. El aviso viejo
 * `low_confidence` se deja de contar cuando llega `confianza` = baja: es la misma
 * señal y ya la cubre necesitaRevisarPrimero (que sí respeta al docente).
 */
export function requiereRevision(data) {
  if (!data) return false;
  return !!(data.from_table || data.color_review_hint || data.rescatada
    || (data.low_confidence && data.confianza !== 'baja')
    || necesitaRevisarPrimero(data));
}

/** El aviso viejo «confianza baja» (imagen poco clara) solo se muestra si `confianza` no lo cubre. */
export function mostrarAvisoConfianzaLegado(data) {
  return !!(data && data.low_confidence && data.confianza !== 'baja');
}

/** El aviso viejo «respuesta por marca» se oculta cuando ya hay un origen que lo dice. */
export function mostrarAvisoMarcaLegado(data) {
  return !!(data && data.answer_from_marks && !origenValido(data.origen_respuesta));
}

/** ¿Una tarjeta entra en el filtro activo? (`all`, un tipo, o «revisar»). */
export function coincideConFiltro(filtro, { tipo, revisar, problemas = false }) {
  if (filtro === 'all') return true;
  if (filtro === FILTRO_REVISAR) return !!revisar;
  if (filtro === FILTRO_PROBLEMAS) return !!problemas;
  return tipo === filtro;
}

/** Cuántas preguntas conviene revisar primero. */
export function contarRevisarPrimero(preguntas) {
  return (preguntas || []).filter(q => necesitaRevisarPrimero(q && q.data)).length;
}
