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
/** «Modo folleto» (3.2): el tamaño de la letra (pt), los mismos topes que el servidor. */
export const LETRA_PLEGADO_MIN = 7;
export const LETRA_PLEGADO_MAX = 12;
export const LETRA_PLEGADO = 8.5;
export const DOCUMENTOS = ['examen', 'hoja', 'clave'];

/** Los documentos que se pueden descargar según cómo contestan los estudiantes: [{ id, nombre, texto }]. */
export function documentosDe(contenido) {
  const clave = texto => ({ id: 'clave', nombre: 'Clave de respuestas', texto });
  if (contenido === 'folleto_hoja_clave') {
    return [
      { id: 'examen', nombre: 'Hoja de preguntas', texto: 'Las preguntas, sin espacios para contestar. Se reparte a los estudiantes.' },
      { id: 'hoja', nombre: 'Hoja de respuestas', texto: 'Donde contesta el estudiante, con su nombre y calificación.' },
      clave('La hoja de respuestas ya llena. Solo para el docente.'),
    ];
  }
  return [
    { id: 'examen', nombre: 'Evaluación', texto: 'Cada pregunta con su espacio para contestar. Sin respuestas.' },
    clave('Cada respuesta con su letra y su texto. Solo para el docente.'),
  ];
}

/** Cuánto papel se gasta: en modo folleto cada hoja lleva dos caras y cuatro páginas. */
export function resumenDePapel({ paginas = 0, plegado = false } = {}) {
  const hoja = n => `${n} hoja${n === 1 ? '' : 's'}`;
  if (plegado) return `${hoja(Math.ceil(paginas / 2))} de papel, por ambas caras.`;
  if (paginas <= 1) return '1 página: 1 hoja.';
  return `${paginas} páginas: ${hoja(Math.ceil(paginas / 2))} a doble cara (${paginas} a una cara).`;
}

/** El «modo folleto» es solo del PDF: con «Word» no se ofrece, y con «PDF y Word» el Word sale normal. */
export function admiteFolleto(formato = 'pdf') {
  return formato !== 'word';
}

/** Cómo imprimir el PDF en modo folleto para que salga bien. */
export function pasosDePlegado(formato = 'pdf') {
  return [
    ...(formato === 'ambos' ? ['El modo folleto es solo del PDF: el Word del ZIP sale normal.'] : []),
    'Imprime a doble cara, volteando por el borde corto, a tamaño real (100 %) y sin activar el «folleto» de la impresora.',
    'Si tu impresora no imprime sola por ambas caras: imprime las páginas impares, vuelve a poner las hojas volteadas por el borde corto e imprime las pares. Prueba antes con una sola hoja.',
    'Apila las hojas en el orden en que salen y dóblalas juntas por la mitad.',
  ];
}

/** El botón de la ventana «¿Qué quieres imprimir?». */
export function textoDeDescarga({ formato = 'pdf', versiones = 0, ocupada = false } = {}) {
  if (ocupada) return 'Generando…';
  const que = formato === 'word' ? 'Word' : formato === 'ambos' ? 'PDF y Word' : 'PDF';
  return versiones ? `Descargar ${que} de las ${versiones} versiones (ZIP)` : `Descargar ${que}${formato === 'ambos' ? ' (ZIP)' : ''}`;
}

/** El archivo que se descarga (2.8): el PDF, el Word editable, o un ZIP con los dos. */
export const FORMATOS = ['pdf', 'word', 'ambos'];
export const PAPELES = ['carta', 'legal', 'a4'];
export const MARGENES = ['normal', 'estrechos', 'moderados', 'anchos'];
export const FUENTES = ['dejavu', 'arial', 'times'];
/** Tamaños (pt) que acepta el servidor y los de siempre. */
export const RENGLONES_MIN = 2;
export const RENGLONES_MAX = 24;
export const TAM_MIN = 7;
export const TAM_MAX = 20;
export const ROTULOS = ['facilitador', 'docente', 'profesor'];
/** Las partes del examen: un tipo de pregunta cada una (mismo nombre que en backend/plan_impreso.py). */
export const TIPOS_PARTE = ['multichoice', 'truefalse', 'matching', 'cloze', 'essay', 'shortanswer', 'numerical'];
export const NOMBRES_PARTE = {
  multichoice: 'SELECCIÓN MÚLTIPLE', truefalse: 'VERDADERO O FALSO', matching: 'EMPAREJAMIENTO', cloze: 'COMPLETAR',
  essay: 'DESARROLLO', shortanswer: 'RESPUESTA CORTA', numerical: 'RESPUESTA NUMÉRICA',
};
export const LIMITE_NOMBRE_PARTE = 80;
export const LIMITE_INDICACION_PARTE = 500;

/** Un orden de partes válido: tipos conocidos, sin repetir. */
export function ordenDePartesValido(v) {
  return Array.isArray(v) ? [...new Set(v.filter(t => TIPOS_PARTE.includes(t)))] : [];
}

/** { tipo: { nombre, indicacion } } solo con tipos conocidos y con lo que de verdad hay escrito. */
export function textosDePartesValidos(v) {
  const out = {};
  if (!v || typeof v !== 'object') return out;
  for (const t of TIPOS_PARTE) {
    const x = Object.hasOwn(v, t) ? v[t] : null;
    if (!x || typeof x !== 'object') continue;
    const nombre = limpiarCampo(x.nombre, LIMITE_NOMBRE_PARTE);
    const indicacion = limpiarCampo(x.indicacion, LIMITE_INDICACION_PARTE);
    if (nombre || indicacion) out[t] = { nombre, indicacion };
  }
  return out;
}

/**
 * Los tipos presentes en el examen en el orden en que se imprimen las partes: primero los del orden pedido y
 * detrás los demás, como aparecen (la misma regla que el servidor).
 */
export function tiposEnOrden(questions, orden = []) {
  const presentes = [...new Set((questions || []).map(q => q.type))];
  const lugar = t => (orden.includes(t) ? orden.indexOf(t) : orden.length);
  return presentes.map((t, i) => ({ t, i })).sort((a, b) => lugar(a.t) - lugar(b.t) || a.i - b.i).map(x => x.t);
}

/** El orden que resulta de mover un tipo (dir -1 o 1) entre los presentes; los ausentes se recuerdan detrás. */
export function moverParte(presentes, orden, tipo, dir) {
  const i = presentes.indexOf(tipo), j = i + dir;
  if (i < 0 || j < 0 || j >= presentes.length) return orden;
  const nuevos = [...presentes];
  [nuevos[i], nuevos[j]] = [nuevos[j], nuevos[i]];
  return [...nuevos, ...orden.filter(t => !nuevos.includes(t))];
}
/** Tamaños y posiciones de una imagen en el papel además de lo de siempre (mediana, a la izquierda); mismos
 * nombres que en backend/plan_impreso.py. «completo» ocupa de margen a margen, así que no tiene posición. */
export const TAMANOS_IMAGEN = ['pequena', 'grande', 'completo'];
export const POSICIONES_IMAGEN = ['centro', 'derecha'];

// { «número:posición»: valor } solo con claves y valores válidos (tope: el del servidor).
const _porImagen = (v, validos) => (!v || typeof v !== 'object' ? {}
  : Object.fromEntries(Object.entries(v).filter(([k, t]) => /^\d{1,6}:\d{1,3}$/.test(k) && validos.includes(t)).slice(0, 500)));
export const tamanosDeImagenValidos = v => _porImagen(v, TAMANOS_IMAGEN);
export const posicionesDeImagenValidas = v => _porImagen(v, POSICIONES_IMAGEN);

/** Las imágenes distintas de un examen: [{ mime, b64, usos: ['3:0'], preguntas: [3] }] en orden de aparición. */
export function imagenesDelExamen(questions) {
  const por = new Map();
  for (const q of questions || []) {
    const lista = q && q.data && Array.isArray(q.data.images) ? q.data.images : [];
    lista.forEach((im, i) => {
      if (!im || typeof im.b64 !== 'string' || !im.b64) return;
      if (!por.has(im.b64)) {
        const mime = typeof im.mime === 'string' && /^image\/[\w.+-]+$/.test(im.mime) ? im.mime : 'image/png';
        por.set(im.b64, { mime, b64: im.b64, usos: [], preguntas: [] });
      }
      const x = por.get(im.b64);
      if (im.compartida) x.compartida = true;
      x.usos.push(`${q.num}:${i}`);
      if (!x.preguntas.includes(q.num)) x.preguntas.push(q.num);
    });
  }
  return [...por.values()];
}

/** Una huella corta y estable de una imagen (FNV-1a de su base64 y su largo): para recordar su tamaño. */
export function huellaDeImagen(b64) {
  let h = 0x811c9dc5;
  for (let i = 0; i < b64.length; i++) h = Math.imul(h ^ b64.charCodeAt(i), 0x01000193);
  return `${(h >>> 0).toString(16)}-${b64.length}`;
}

function _paraEnviar(imagenes, elegidos) {
  const out = {};
  for (const im of imagenes) {
    const t = elegidos[im.huella];
    if (t) im.usos.forEach(u => { out[u] = t; });
  }
  return out;
}
/** Lo que se manda al servidor: cada uso de cada imagen con tamaño (o posición) elegido. */
export const tamanosParaEnviar = (imagenes, elegidos) => tamanosDeImagenValidos(_paraEnviar(imagenes, elegidos));
export const posicionesParaEnviar = (imagenes, elegidas) => posicionesDeImagenValidas(_paraEnviar(imagenes, elegidas));

/** «Pregunta 3», «Preguntas 1 a 5», «Preguntas 1, 3 y 4»; con «Enunciado compartido» si la imagen es de uno. */
export function rotuloDeImagen({ preguntas, compartida }) {
  const n = [...preguntas].sort((a, b) => a - b);
  const seguidas = n.every((x, i) => !i || x === n[i - 1] + 1);
  const cuales = n.length === 1 ? `${n[0]}` : seguidas && n.length > 2 ? `${n[0]} a ${n[n.length - 1]}`
    : `${n.slice(0, -1).join(', ')} y ${n[n.length - 1]}`;
  const texto = `${n.length === 1 ? 'pregunta' : 'preguntas'} ${cuales}`;
  return compartida ? `Enunciado compartido · ${texto}` : texto[0].toUpperCase() + texto.slice(1);
}

/** Cómo se llama cada opción (para los resúmenes). */
export const ROTULOS_NOMBRES = { facilitador: 'FACILITADOR', docente: 'DOCENTE', profesor: 'PROFESOR' };
export const PAPELES_NOMBRES = { carta: 'Carta', legal: 'Legal', a4: 'A4' };
export const MARGENES_NOMBRES = { normal: 'normales', estrechos: 'estrechos', moderados: 'moderados', anchos: 'anchos' };
export const FUENTES_NOMBRES = { dejavu: 'DejaVu Sans', arial: 'Arial', times: 'Times New Roman' };
export const ACTIVIDADES = ['Parcial', 'Quiz', 'Prueba corta', 'Examen final', 'Taller', 'Evaluación diagnóstica'];

/** Lo que se recuerda entre exámenes (no la fecha: cambia cada vez). */
const GUARDADOS = ['institucion', 'facultad', 'departamento', 'rotulo_docente', 'logo_izquierdo', 'logo_derecho', 'materia', 'docente', 'actividad', 'grupo', 'instrucciones', 'contenido', 'formato', 'papel', 'margenes', 'fuente_titulos', 'tam_titulos', 'fuente_preguntas', 'tam_preguntas', 'campos_estudiante', 'partes', 'mezclar', 'puntos_por_pregunta', 'puntos_enteros', 'renglones_ensayo', 'procedimiento_numerica', 'procedimiento_corta', 'renglones_procedimiento', 'orden_partes', 'textos_partes', 'plegado', 'letra_plegado', 'cuadro_puntos', 'saltos_partes'];

const VACIOS = {
  institucion: '', facultad: '', departamento: '', rotulo_docente: 'facilitador', logo_izquierdo: '', logo_derecho: '', materia: '', docente: '', actividad: '', grupo: '', fecha: '', instrucciones: '', version: '',
  contenido: 'examen_y_clave', formato: 'pdf', papel: 'carta', margenes: 'moderados', fuente_titulos: 'dejavu', tam_titulos: 11, fuente_preguntas: 'dejavu', tam_preguntas: 10, campos_estudiante: true, partes: true, mezclar: true, puntos_por_pregunta: true, puntos_enteros: true, renglones_ensayo: 6,
  procedimiento_numerica: false, procedimiento_corta: false, renglones_procedimiento: 4,
  documento: '', plegado: false, letra_plegado: 8.5, cuadro_puntos: false,
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
  'tam_preguntas', 'campos_estudiante', 'partes', 'mezclar', 'puntos_por_pregunta', 'puntos_enteros', 'renglones_ensayo',
  'procedimiento_numerica', 'procedimiento_corta', 'renglones_procedimiento', 'orden_partes', 'textos_partes',
  'cuadro_puntos', 'saltos_partes'];

/** Los datos de un perfil (validados campo por campo; lo que falte toma su valor de siempre). */
export function datosDePerfil(datos) {
  const v = valoresIniciales(datos);
  return Object.fromEntries(PERFIL_CAMPOS.map(k => [k, v[k]]));
}

/** Los datos del diálogo con un perfil aplicado: materia, actividad, grupo, fecha y «qué incluir» no cambian. */
export function aplicarPerfil(actuales, perfil) {
  const datos = datosDePerfil(perfil);
  // Los perfiles de antes no hablaban del procedimiento ni de las partes: no deben borrar lo que haya puesto.
  for (const k of ['procedimiento_numerica', 'procedimiento_corta', 'renglones_procedimiento', 'cuadro_puntos', 'saltos_partes']) {
    if (!perfil || perfil[k] === undefined) delete datos[k];
  }
  if (!datos.orden_partes.length) delete datos.orden_partes;
  if (!Object.keys(datos.textos_partes).length) delete datos.textos_partes;
  return { ...actuales, ...datos };
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
  const out = { ...VACIOS, orden_partes: [], textos_partes: {}, saltos_partes: [], tam_imagenes: {}, alin_imagenes: {} };
  if (!guardado || typeof guardado !== 'object') return out;
  for (const k of ['institucion', 'facultad', 'departamento', 'materia', 'docente', 'actividad', 'grupo']) {
    if (typeof guardado[k] === 'string') out[k] = limpiarCampo(guardado[k]);
  }
  if (typeof guardado.instrucciones === 'string') out.instrucciones = limpiarTexto(guardado.instrucciones);
  if (typeof guardado.version === 'string') out.version = limpiarCampo(guardado.version, 20);   // «A», «B»…: solo en las versiones de un examen
  if (CONTENIDOS.includes(guardado.contenido)) out.contenido = guardado.contenido;
  if (FORMATOS.includes(guardado.formato)) out.formato = guardado.formato;
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
  if (typeof guardado.puntos_enteros === 'boolean') out.puntos_enteros = guardado.puntos_enteros;   // sin dato (perfil viejo): activada
  const r = enteroEn(guardado.renglones_ensayo, RENGLONES_MIN, RENGLONES_MAX);
  if (r !== null) out.renglones_ensayo = r;
  for (const k of ['procedimiento_numerica', 'procedimiento_corta']) {
    if (typeof guardado[k] === 'boolean') out[k] = guardado[k];
  }
  const rp = enteroEn(guardado.renglones_procedimiento, RENGLONES_MIN, RENGLONES_MAX);
  if (rp !== null) out.renglones_procedimiento = rp;
  if (DOCUMENTOS.includes(guardado.documento)) out.documento = guardado.documento;   // un solo documento: solo al descargar
  if (typeof guardado.plegado === 'boolean') out.plegado = guardado.plegado;
  const letra = Number(guardado.letra_plegado);
  if (Number.isFinite(letra) && letra >= LETRA_PLEGADO_MIN && letra <= LETRA_PLEGADO_MAX) out.letra_plegado = letra;
  out.orden_partes = ordenDePartesValido(guardado.orden_partes);
  out.textos_partes = textosDePartesValidos(guardado.textos_partes);
  if (typeof guardado.cuadro_puntos === 'boolean') out.cuadro_puntos = guardado.cuadro_puntos;
  out.saltos_partes = ordenDePartesValido(guardado.saltos_partes);
  out.tam_imagenes = tamanosDeImagenValidos(guardado.tam_imagenes);   // propios de cada evaluación: no se guardan
  out.alin_imagenes = posicionesDeImagenValidas(guardado.alin_imagenes);
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

/** El texto del botón de exportar según el formato, las versiones y si se está generando. */
export function textoDelBoton({ formato = 'pdf', versiones = false, listas = false, cantidad = 0, generando = false } = {}) {
  const que = formato === 'word' ? 'Word' : formato === 'ambos' ? 'PDF y Word' : 'PDF';
  if (generando) return versiones ? 'Generando las versiones…' : (formato === 'ambos' ? 'Generando los archivos…' : `Generando el ${que}…`);
  if (versiones) return listas ? `Exportar ${cantidad} versiones (ZIP)` : 'Exportar versiones';
  return formato === 'ambos' ? 'Exportar PDF y Word (ZIP)' : `Exportar ${que}`;
}

/** Lo que lleva la descarga, para la línea de abajo cuando hay versiones: «un ZIP con 3 PDF…». */
export function resumenDeDescarga({ formato = 'pdf', cantidad = 0 } = {}) {
  const por = formato === 'word' ? `${cantidad} Word, uno por versión` : formato === 'ambos' ? `${cantidad} PDF y ${cantidad} Word, uno de cada por versión` : `${cantidad} PDF, uno por versión`;
  return `De cada documento que elijas recibirás un ZIP con ${por}. El Moodle XML no cambia.`;
}

/** El cuerpo de POST /api/exportar_examen (y /api/exportar_pdf): el mismo examen que se envió para el XML + los datos. */
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
