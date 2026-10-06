/**
 * materias-logica.js — «Mis materias» sin tocar el DOM (se prueba en Node).
 * La pantalla vive en biblioteca.js y el selector de materia en materias.js.
 */

/** Los colores de una materia: el nombre es lo que guarda el servidor (database.COLORES_MATERIA). */
export const COLORES = [
  { id: 'azul', etiqueta: 'Azul', variable: '--color-mc' },
  { id: 'verde', etiqueta: 'Verde', variable: '--color-tf' },
  { id: 'ambar', etiqueta: 'Ámbar', variable: '--color-mt' },
  { id: 'violeta', etiqueta: 'Violeta', variable: '--color-cl' },
  { id: 'rosa', etiqueta: 'Rosa', variable: '--color-es' },
  { id: 'turquesa', etiqueta: 'Turquesa', variable: '--color-sa' },
  { id: 'naranja', etiqueta: 'Naranja', variable: '--color-nu' },
  { id: 'gris', etiqueta: 'Gris', variable: '--color-text-subtle' },
];

export const LIMITE_NOMBRE = 80;
export const LIMITE_CAMPO = 160;

/** La variable CSS del color de una materia (azul si el nombre no se conoce). */
export function variableDeColor(id) {
  return (COLORES.find(c => c.id === id) || COLORES[0]).variable;
}

/** Sin mayúsculas, tildes ni espacios de sobra: «Cálculo», «CALCULO» y « calculo » son lo mismo. */
export function normalizar(t) {
  return String(t == null ? '' : t).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
}

/** Un nombre de una línea, sin espacios de sobra y con tope de largo. */
export function nombreLimpio(t, max = LIMITE_NOMBRE) {
  return String(t == null ? '' : t).replace(/\s+/g, ' ').trim().slice(0, max);
}

/** ¿Ya hay una materia con ese nombre? (`exceptoId`: la que se está editando). */
export function existeNombre(materias, nombre, exceptoId = null) {
  const k = normalizar(nombre);
  return !!k && materias.some(m => m.id !== exceptoId && normalizar(m.nombre) === k);
}

/** Las materias por nombre (con tildes y eñes en su sitio), activas primero. */
export function ordenarMaterias(materias) {
  return [...materias].sort((a, b) => (a.archivada === b.archivada ? 0 : a.archivada ? 1 : -1)
    || a.nombre.localeCompare(b.nombre, 'es', { sensitivity: 'base' }));
}

export function activas(materias) { return materias.filter(m => !m.archivada); }
export function archivadas(materias) { return materias.filter(m => m.archivada); }

/** Los exámenes de una materia; `null` = los que no tienen materia; 'todos' = todos. */
export function examenesDe(examenes, materiaId) {
  if (materiaId === 'todos') return examenes;
  return examenes.filter(e => (e.materia_id == null ? null : e.materia_id) === materiaId);
}

/** Filtra por nombre del archivo, categoría, actividad o fecha (sin mayúsculas ni tildes). */
export function filtrarExamenes(examenes, texto, nombreMateria = () => '') {
  const q = normalizar(texto);
  if (!q) return examenes;
  return examenes.filter(e => normalizar(`${e.filename} ${e.category} ${e.actividad || ''} ${e.fecha || ''} ${nombreMateria(e.materia_id)}`).includes(q));
}

export function formatoBytes(b) {
  const n = Number(b) || 0;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(n < 10 * 1024 * 1024 ? 1 : 0)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

/** «Hace 3 días», «ayer»… para la fecha (SQLite la guarda en UTC y sin zona) de la última actividad. */
export function fechaCorta(iso, ahora = Date.now()) {
  if (!iso) return '';
  const t = new Date(String(iso).replace(' ', 'T') + (String(iso).endsWith('Z') ? '' : 'Z')).getTime();
  if (Number.isNaN(t)) return '';
  const dias = Math.floor((ahora - t) / 86400000);
  if (dias <= 0) return 'hoy';
  if (dias === 1) return 'ayer';
  if (dias < 30) return `hace ${dias} días`;
  const meses = Math.floor(dias / 30);
  return meses < 12 ? `hace ${meses} ${meses === 1 ? 'mes' : 'meses'}` : `hace ${Math.floor(meses / 12)} ${Math.floor(meses / 12) === 1 ? 'año' : 'años'}`;
}

export function plural(n, uno, varios) { return `${n} ${n === 1 ? uno : varios}`; }

/**
 * El aviso de que el Historial se está llenando (null si hay espacio de sobra).
 * `uso` es la respuesta de GET /api/history/uso.
 */
export function avisoDeLimite(uso) {
  if (!uso || !uso.cerca_del_limite) return null;
  const lleno = uso.porcentaje >= 100;
  const sin = uso.sin_materia || 0;
  const usado = `${plural(uso.examenes, 'examen guardado', 'exámenes guardados')} (${formatoBytes(uso.bytes)}) de ${uso.maximo_examenes}`;
  const que = sin > 0
    ? `Al llenarse se borran primero los exámenes sin materia (hoy ${sin}), los más antiguos antes. Pasa a una materia lo que quieras conservar.`
    : 'Todos tus exámenes tienen materia: al llenarse se borrarán los más antiguos. Borra los que ya no necesites.';
  return {
    nivel: lleno ? 'lleno' : 'aviso',
    titulo: lleno ? 'El Historial está lleno' : 'El Historial se está llenando',
    texto: `${usado}. ${que}`,
  };
}

/** Una línea con lo usado, para mostrar siempre. */
export function textoUso(uso) {
  if (!uso) return '';
  return `${plural(uso.examenes, 'examen', 'exámenes')} · ${formatoBytes(uso.bytes)} · ${Math.round(uso.porcentaje)} % del espacio`;
}

// ── Asistente para ordenar los exámenes sin materia ──────────────────────
// Propone una materia a partir de la categoría de Moodle o, si no hay, del nombre del archivo.
// Es solo una pista: el docente ve cada propuesta, la puede cambiar o desmarcar, y nada se aplica solo.

/** Palabras que dicen QUÉ ES el examen, no de qué materia: se quitan para quedarse con la materia. */
const RUIDO = new Set(['parcial', 'parciales', 'quiz', 'quizz', 'examen', 'examenes', 'exam', 'final', 'prueba', 'pruebas', 'corta', 'corto',
  'taller', 'talleres', 'evaluacion', 'evaluaciones', 'diagnostica', 'diagnostico', 'test', 'tarea', 'tareas', 'preguntas', 'pregunta', 'mis',
  'moodle', 'xml', 'pdf', 'docx', 'txt', 'copia', 'version', 'banco', 'unidad', 'tema', 'semestre', 'bimestre', 'trimestre', 'periodo', 'nuevo',
  'editado', 'respuestas', 'clave']);
const RELLENO = new Set(['de', 'del', 'la', 'el', 'las', 'los', 'para', 'y']);

/** ¿El texto es solo un número, un año, un ordinal (1ro, 2do, 3er, 1º) o «v2»? */
function esNumerico(t) {
  return /^\d+(er|ro|do|to|vo|mo|º|°|a|o)?$/.test(t) || /^v\d+$/.test(t) || /^\d{4}-\d{1,2}$/.test(t);
}

/** La materia que parece tener un examen según su categoría o su archivo; null si no hay pista. */
export function nombreSugerido(examen) {
  const cat = nombreLimpio(examen.category || '');
  const catSirve = cat && normalizar(cat) !== 'mis-preguntas' && normalizar(cat) !== 'mis preguntas';
  const archivo = nombreLimpio(String(examen.filename || '').replace(/\.[A-Za-z0-9]{2,5}$/, ''));
  for (const fuente of catSirve ? [cat, archivo] : [archivo]) {
    const n = materiaDeTexto(fuente);
    if (n) return n;
  }
  return null;
}

function materiaDeTexto(texto) {
  const palabras = String(texto)
    .replace(/\b\d+(er|ro|do|to|vo|mo|º|°)(?![\p{L}])/giu, ' ')   // 1ro, 2do, 3er…
    .replace(/(\p{L})(\d)/gu, '$1 $2').replace(/(\d)(\p{L})/gu, '$1 $2')   // «Quiz3» es «Quiz 3»
    .replace(/[_\-.()[\]+,;:/\\]+/g, ' ').split(/\s+/).filter(Boolean);
  const utiles = palabras.filter(p => !RUIDO.has(normalizar(p)) && !esNumerico(normalizar(p)));
  while (utiles.length && RELLENO.has(normalizar(utiles[0]))) utiles.shift();
  while (utiles.length && RELLENO.has(normalizar(utiles[utiles.length - 1]))) utiles.pop();
  if (!utiles.length) return null;
  let nombre = utiles.join(' ');
  if (nombre === nombre.toLowerCase() || nombre === nombre.toUpperCase()) {
    nombre = utiles.map((p, i) => (i > 0 && RELLENO.has(normalizar(p)) ? p.toLowerCase() : p.charAt(0).toUpperCase() + p.slice(1).toLowerCase())).join(' ');
  }
  nombre = nombreLimpio(nombre);
  return normalizar(nombre).length >= 3 ? nombre : null;
}

/** Si una propuesta es la misma materia que una existente o empieza igual («Historia» y «Historia de Panamá»). */
function materiaParecida(clave, materias) {
  const exacta = materias.find(m => normalizar(m.nombre) === clave);
  if (exacta) return exacta;
  return materias.find(m => {
    const k = normalizar(m.nombre);
    return k.startsWith(clave + ' ') || clave.startsWith(k + ' ');
  }) || null;
}

/**
 * Agrupa los exámenes sin materia por la materia que parecen tener.
 * Devuelve { grupos: [{ nombre, materiaId|null, ids, ejemplos }], sinPista: [ids] }.
 * `materiaId` no es null si ya existe una materia igual o parecida (entonces `nombre` es la suya).
 */
export function sugerirMaterias(sinMateria, materias) {
  const porClave = new Map();
  const sinPista = [];
  for (const e of sinMateria) {
    const n = nombreSugerido(e);
    if (!n) { sinPista.push(e.id); continue; }
    const k = normalizar(n);
    if (!porClave.has(k)) porClave.set(k, { nombre: n, ids: [], ejemplos: [] });
    const g = porClave.get(k);
    g.ids.push(e.id);
    if (g.ejemplos.length < 3) g.ejemplos.push(e.filename);
  }
  const grupos = [];
  for (const [k, g] of porClave) {
    const existente = materiaParecida(k, materias);
    grupos.push({ nombre: existente ? existente.nombre : g.nombre, materiaId: existente ? existente.id : null, ids: g.ids, ejemplos: g.ejemplos });
  }
  // Dos propuestas que acaban en la misma materia existente se juntan.
  const juntos = new Map();
  for (const g of grupos) {
    const k = g.materiaId != null ? `m${g.materiaId}` : `n${normalizar(g.nombre)}`;
    if (!juntos.has(k)) juntos.set(k, g);
    else { const a = juntos.get(k); a.ids.push(...g.ids); a.ejemplos = [...a.ejemplos, ...g.ejemplos].slice(0, 3); }
  }
  return { grupos: [...juntos.values()].sort((a, b) => b.ids.length - a.ids.length || a.nombre.localeCompare(b.nombre, 'es')), sinPista };
}

/** Los ids que hay que mover a cada materia según lo que el docente dejó marcado: [{ nombre, materiaId, ids }]. */
export function planDelAsistente(grupos, marcados) {
  return grupos
    .map((g, i) => ({ g, i }))
    .filter(({ i }) => marcados[i] && marcados[i].marcado !== false)
    .map(({ g, i }) => ({ nombre: nombreLimpio(marcados[i].nombre ?? g.nombre), materiaId: marcados[i].nombre != null && normalizar(marcados[i].nombre) !== normalizar(g.nombre) ? null : g.materiaId, ids: g.ids }))
    .filter(p => p.nombre);
}
