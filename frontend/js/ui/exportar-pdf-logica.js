/**
 * exportar-pdf-logica.js — la parte de «Exportar examen en PDF» que no toca el DOM
 * (se prueba en Node). El diálogo vive en exportar-pdf.js.
 */

/** Mismos topes que backend/exportar_pdf.py (LIMITE_CAMPO y LIMITE_INSTRUCCIONES). */
export const LIMITE_CAMPO = 160;
export const LIMITE_INSTRUCCIONES = 1500;
/** Caracteres base64 de un logo (~1,5 MB): el mismo tope del servidor. */
export const LIMITE_LOGO = 2000000;

export const CONTENIDOS = ['examen_y_clave', 'solo_examen', 'solo_clave', 'folleto_hoja_clave'];
export const PAPELES = ['carta', 'legal', 'a4'];
export const MARGENES = ['normal', 'estrechos', 'moderados', 'anchos'];
export const FUENTES = ['dejavu', 'arial', 'times'];
/** Tamaños (pt) que acepta el servidor y los de siempre. */
export const RENGLONES_MIN = 2;
export const RENGLONES_MAX = 24;
export const TAM_MIN = 7;
export const TAM_MAX = 20;
export const ROTULOS = ['facilitador', 'docente', 'profesor'];
/** Cómo se llama cada opción (para los resúmenes). */
export const ROTULOS_NOMBRES = { facilitador: 'FACILITADOR', docente: 'DOCENTE', profesor: 'PROFESOR' };
export const PAPELES_NOMBRES = { carta: 'Carta', legal: 'Legal', a4: 'A4' };
export const MARGENES_NOMBRES = { normal: 'normales', estrechos: 'estrechos', moderados: 'moderados', anchos: 'anchos' };
export const FUENTES_NOMBRES = { dejavu: 'DejaVu Sans', arial: 'Arial', times: 'Times New Roman' };
export const ACTIVIDADES = ['Parcial', 'Quiz', 'Prueba corta', 'Examen final', 'Taller', 'Evaluación diagnóstica'];

/** Lo que se recuerda entre exámenes (no la fecha: cambia cada vez). */
const GUARDADOS = ['institucion', 'facultad', 'departamento', 'rotulo_docente', 'logo_izquierdo', 'logo_derecho', 'materia', 'docente', 'actividad', 'grupo', 'instrucciones', 'contenido', 'papel', 'margenes', 'fuente_titulos', 'tam_titulos', 'fuente_preguntas', 'tam_preguntas', 'campos_estudiante', 'partes', 'mezclar', 'puntos_por_pregunta', 'renglones_ensayo'];

const VACIOS = {
  institucion: '', facultad: '', departamento: '', rotulo_docente: 'facilitador', logo_izquierdo: '', logo_derecho: '', materia: '', docente: '', actividad: '', grupo: '', fecha: '', instrucciones: '',
  contenido: 'examen_y_clave', papel: 'carta', margenes: 'moderados', fuente_titulos: 'dejavu', tam_titulos: 11, fuente_preguntas: 'dejavu', tam_preguntas: 10, campos_estudiante: true, partes: true, mezclar: true, puntos_por_pregunta: true, renglones_ensayo: 6,
};

const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];

/** Un tamaño de letra como número entre TAM_MIN y TAM_MAX (acepta «12» o «12,5»), con medios puntos; null si no sirve. */
export function tamanoValido(v) {
  const n = typeof v === 'string' ? Number(v.trim().replace(',', '.')) : v;
  if (typeof n !== 'number' || !Number.isFinite(n) || n < TAM_MIN || n > TAM_MAX) return null;
  return Math.round(n * 2) / 2;
}

/** Un entero entre `min` y `max` (acepta «8» o 8); null si no sirve. */
export function enteroEn(v, min, max) {
  const n = typeof v === 'string' ? Number(v.trim()) : v;
  return typeof n === 'number' && Number.isInteger(n) && n >= min && n <= max ? n : null;
}

/** Lo que guarda un perfil de encabezado: el encabezado y el formato, NO lo propio de cada examen. */
export const PERFIL_CAMPOS = ['institucion', 'facultad', 'departamento', 'docente', 'rotulo_docente', 'instrucciones',
  'logo_izquierdo', 'logo_derecho', 'papel', 'margenes', 'fuente_titulos', 'tam_titulos', 'fuente_preguntas',
  'tam_preguntas', 'campos_estudiante', 'partes', 'mezclar', 'puntos_por_pregunta', 'renglones_ensayo'];

/** Los datos de un perfil (validados campo por campo; lo que falte toma su valor de siempre). */
export function datosDePerfil(datos) {
  const v = valoresIniciales(datos);
  return Object.fromEntries(PERFIL_CAMPOS.map(k => [k, v[k]]));
}

/** Los datos del diálogo con un perfil aplicado: materia, actividad, grupo, fecha y «qué incluir» no cambian. */
export function aplicarPerfil(actuales, perfil) {
  return { ...actuales, ...datosDePerfil(perfil) };
}

/** El nombre de un perfil: una línea, sin «/» ni «\», de 1 a 60 caracteres; '' si no sirve. */
export function nombrePerfil(n) {
  return String(n == null ? '' : n).replace(/[\\/]+/g, '-').replace(/\s+/g, ' ').trim().slice(0, 60);
}

/** ¿Es una imagen en base64 (sin el «data:…» delante) de un tamaño razonable? */
export function logoValido(v) {
  return typeof v === 'string' && v.length > 0 && v.length <= LIMITE_LOGO && /^[A-Za-z0-9+/]+={0,2}$/.test(v);
}

/** Medidas (ancho, alto) para reducir un logo a como mucho `max` píxeles de lado sin deformarlo. */
export function medidasReducidas(ancho, alto, max = 320) {
  if (!(ancho > 0) || !(alto > 0)) return null;
  const k = Math.min(1, max / Math.max(ancho, alto));
  return { ancho: Math.max(1, Math.round(ancho * k)), alto: Math.max(1, Math.round(alto * k)) };
}

/** Una línea de texto: sin saltos ni espacios de sobra, con tope de largo. */
export function limpiarCampo(v, max = LIMITE_CAMPO) {
  return String(v == null ? '' : v).replace(/\s+/g, ' ').trim().slice(0, max);
}

/** Texto de varias líneas (instrucciones): conserva los saltos de línea. */
export function limpiarTexto(v, max = LIMITE_INSTRUCCIONES) {
  return String(v == null ? '' : v).replace(/\r\n?/g, '\n').replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim().slice(0, max);
}

/** «2026-10-12» (lo que da <input type="date">) como «12 de octubre de 2026»; '' si no es una fecha. */
export function fechaLegible(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ''));
  if (!m) return '';
  const mes = Number(m[2]), dia = Number(m[3]);
  if (mes < 1 || mes > 12 || dia < 1 || dia > 31) return '';
  return `${dia} de ${MESES[mes - 1]} de ${m[1]}`;
}

/**
 * Valores con que se abre el diálogo: lo guardado de la última vez, validado campo
 * por campo (lo guardado pudo editarse a mano o venir de otra versión).
 */
export function valoresIniciales(guardado) {
  const out = { ...VACIOS };
  if (!guardado || typeof guardado !== 'object') return out;
  for (const k of ['institucion', 'facultad', 'departamento', 'materia', 'docente', 'actividad', 'grupo']) {
    if (typeof guardado[k] === 'string') out[k] = limpiarCampo(guardado[k]);
  }
  if (typeof guardado.instrucciones === 'string') out.instrucciones = limpiarTexto(guardado.instrucciones);
  if (CONTENIDOS.includes(guardado.contenido)) out.contenido = guardado.contenido;
  if (PAPELES.includes(guardado.papel)) out.papel = guardado.papel;
  if (MARGENES.includes(guardado.margenes)) out.margenes = guardado.margenes;
  for (const k of ['fuente_titulos', 'fuente_preguntas']) {
    if (FUENTES.includes(guardado[k])) out[k] = guardado[k];
  }
  for (const k of ['tam_titulos', 'tam_preguntas']) {
    const n = tamanoValido(guardado[k]);
    if (n !== null) out[k] = n;
  }
  if (ROTULOS.includes(guardado.rotulo_docente)) out.rotulo_docente = guardado.rotulo_docente;
  for (const k of ['logo_izquierdo', 'logo_derecho']) {
    if (logoValido(guardado[k])) out[k] = guardado[k];
  }
  if (typeof guardado.campos_estudiante === 'boolean') out.campos_estudiante = guardado.campos_estudiante;
  if (typeof guardado.partes === 'boolean') out.partes = guardado.partes;
  if (typeof guardado.mezclar === 'boolean') out.mezclar = guardado.mezclar;
  if (typeof guardado.puntos_por_pregunta === 'boolean') out.puntos_por_pregunta = guardado.puntos_por_pregunta;
  const r = enteroEn(guardado.renglones_ensayo, RENGLONES_MIN, RENGLONES_MAX);
  if (r !== null) out.renglones_ensayo = r;
  return out;
}

/** Lo que se guarda para la próxima vez. */
export function paraGuardar(datos) {
  const v = valoresIniciales(datos);
  return Object.fromEntries(GUARDADOS.map(k => [k, v[k]]));
}

/** Los datos del diálogo, limpios y listos para enviar al servidor. */
export function datosParaEnviar(crudos) {
  const v = valoresIniciales(crudos);
  v.fecha = limpiarCampo(crudos && crudos.fecha);
  return v;
}

/** El cuerpo de POST /api/exportar_pdf: el mismo examen que se envió para el XML + los datos. */
export function cuerpoPdf(examen, datos) {
  return {
    filename: examen.filename,
    total_points: examen.total_points,
    questions: examen.questions,
    answer_key: examen.answer_key,
    datos: datosParaEnviar(datos),
  };
}

/** El nombre de archivo de una cabecera Content-Disposition (con tildes si trae filename*). */
export function nombreDeDescarga(cabecera, respaldo) {
  const utf8 = cabecera && /filename\*=UTF-8''([^;]+)/i.exec(cabecera);
  if (utf8) {
    try { return decodeURIComponent(utf8[1]); } catch (_) { /* cae al nombre simple */ }
  }
  const ascii = cabecera && /filename="([^"]+)"/.exec(cabecera);
  return ascii ? ascii[1] : respaldo;
}

/** Los avisos de la cabecera X-PDF-Info como lista de textos (vacía si no hay o no se entiende). */
export function avisosDelPdf(cabecera) {
  try {
    const info = JSON.parse(cabecera || '{}');
    return Array.isArray(info.avisos) ? info.avisos.filter(a => typeof a === 'string' && a.trim()) : [];
  } catch (_) {
    return [];
  }
}
