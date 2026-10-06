/**
 * perfil-logica.js — «Mi perfil» sin tocar el DOM (se prueba en Node): iniciales del avatar, resúmenes de un
 * perfil de encabezado, orden, nombre de una copia y el examen de ejemplo de la vista previa.
 */
import { FUENTES_NOMBRES, MARGENES_NOMBRES, PAPELES_NOMBRES } from './ui/exportar-pdf-logica.js';
import { normalizar } from './materias-logica.js';

/** Tratamientos que no cuentan para las iniciales: «Ing. Ana Pérez» es «AP», no «IA». */
const TRATAMIENTOS = new Set(['ing', 'dr', 'dra', 'prof', 'profa', 'profesor', 'profesora', 'lic', 'licda', 'mgtr', 'mag', 'msc', 'mtro', 'mtra',
  'phd', 'sr', 'sra', 'srta', 'arq', 'ph', 'd', 'don', 'dona', 'doña', 'mba', 'dipl', 'lcdo', 'lcda']);

/** Las iniciales (hasta dos) de un nombre; '' si no hay nombre. */
export function iniciales(nombre) {
  const palabras = String(nombre || '').split(/\s+/).map(p => p.replace(/[.,;:()]/g, '')).filter(Boolean)
    .filter(p => !TRATAMIENTOS.has(normalizar(p)));
  const conLetra = palabras.filter(p => /\p{L}/u.test(p));
  if (!conLetra.length) return '';
  const letra = p => ([...p].find(c => /\p{L}/u.test(c)) || '').toLocaleUpperCase('es');
  return conLetra.length === 1 ? letra(conLetra[0]) : letra(conLetra[0]) + letra(conLetra[1]);
}

/** «Universidad X · Facultad Y · Departamento Z» (lo que haya escrito); «Sin institución» si no hay nada. */
export function resumenEncabezado(datos) {
  const partes = [datos.institucion, datos.facultad, datos.departamento].map(x => String(x || '').trim()).filter(Boolean);
  return partes.length ? partes.join(' · ') : 'Sin institución';
}

/** «Carta · márgenes moderados · DejaVu Sans 10 pt». */
export function resumenFormato(datos) {
  const pt = Number(datos.tam_preguntas);
  return [PAPELES_NOMBRES[datos.papel] || 'Carta', `márgenes ${MARGENES_NOMBRES[datos.margenes] || 'moderados'}`,
    `${FUENTES_NOMBRES[datos.fuente_preguntas] || 'DejaVu Sans'} ${Number.isFinite(pt) ? pt : 10} pt`].join(' · ');
}

/** Los perfiles por nombre, con el predeterminado primero. */
export function ordenarPerfiles(perfiles, predeterminado) {
  return [...perfiles].sort((a, b) => (a.nombre === predeterminado ? -1 : b.nombre === predeterminado ? 1 : 0)
    || a.nombre.localeCompare(b.nombre, 'es', { sensitivity: 'base' }));
}

/** El nombre de una copia que no choca con los que hay: «X (copia)», «X (copia 2)»… (60 caracteres como máximo). */
export function nombreCopia(nombre, existentes, max = 60) {
  const hay = new Set(existentes.map(n => normalizar(n)));
  for (let i = 1; i < 1000; i++) {
    const sufijo = i === 1 ? ' (copia)' : ` (copia ${i})`;
    const candidato = nombre.slice(0, Math.max(1, max - sufijo.length)).trimEnd() + sufijo;
    if (!hay.has(normalizar(candidato))) return candidato;
  }
  return nombre.slice(0, max);
}

/** Cuántas materias usan un perfil por defecto. */
export function materiasQueUsan(materias, nombrePerfil) {
  return materias.filter(m => m.perfil === nombrePerfil);
}

/** ¿El nombre de un perfil ya lo tiene otro? (sin mayúsculas ni tildes; `actual`: el que se edita). */
export function nombreOcupado(nombre, existentes, actual = null) {
  const k = normalizar(nombre);
  return !!k && existentes.some(n => n !== actual && normalizar(n) === k);
}

/** El examen de ejemplo de la vista previa: lo que se envía a /api/vista_previa_pdf. */
export function ejemploExamen() {
  return {
    filename: 'Ejemplo.pdf',
    total_points: 20,
    questions: [
      { num: 1, type: 'multichoice', points: 10, data: { stem: '¿Cuál es la capital de Panamá?', options: { a: 'Colón', b: 'Ciudad de Panamá', c: 'David' } } },
      { num: 2, type: 'multichoice', points: 10, data: { stem: '¿Cuántos días tiene una semana?', options: { a: 'Cinco', b: 'Siete', c: 'Diez' } } },
    ],
    answer_key: { 1: { type: 'multichoice', answer: 'b' }, 2: { type: 'multichoice', answer: 'b' } },
  };
}
