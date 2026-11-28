/**
 * datos-examen.js — la tarjeta «Datos del examen» de un examen creado desde cero (3.2): nombre, puntaje total,
 * categoría, materia y actividad. Un examen convertido o importado trae esos datos del paso anterior y no la
 * muestra.
 */
import { guardarBorrador } from '../borrador.js';
import { estado } from '../estado.js';
import { enlazarSelectMateria, llenarSelectMateria } from '../materias.js';
import { nombreDeExamen } from './nuevo-logica.js';

const $ = id => document.getElementById(id);

/** Muestra u oculta la tarjeta y la pone al día (sin pisar lo que se está escribiendo en ella). */
export function pintarDatosExamen() {
  const caja = $('editor-datos');
  const meta = estado.currentUploadMetadata;
  const si = !!(meta && meta.desde_cero);
  caja.hidden = !si;
  if (!si || caja.contains(document.activeElement)) return;
  $('nuevo-nombre').value = meta.nombre || '';
  $('nuevo-puntos').value = meta.total_points;
  $('nuevo-categoria').value = meta.category;
  $('nuevo-actividad').value = meta.actividad || '';
  llenarSelectMateria($('nuevo-materia'), { valor: meta.materia_id });
}

/** `alCambiarTotal()`: cambió el puntaje total (hay que redibujar las preguntas). */
export function iniciarDatosExamen({ alCambiarTotal }) {
  const anotar = cambios => {
    if (!estado.currentUploadMetadata?.desde_cero) return;
    Object.assign(estado.currentUploadMetadata, cambios);
    guardarBorrador();
  };
  $('nuevo-nombre').addEventListener('input', e => anotar({ nombre: e.target.value, filename: nombreDeExamen(e.target.value) }));
  $('nuevo-categoria').addEventListener('input', e => anotar({ category: e.target.value.trim() || 'mis-preguntas' }));
  $('nuevo-actividad').addEventListener('input', e => anotar({ actividad: e.target.value.trim() || null }));
  $('nuevo-puntos').addEventListener('change', e => {
    const n = Number(e.target.value);
    if (!(Number.isFinite(n) && n > 0)) {            // no válido: se queda el total que había
      e.target.value = estado.currentUploadMetadata?.total_points ?? '';
      return;
    }
    anotar({ total_points: n });
    alCambiarTotal();
  });
  enlazarSelectMateria($('nuevo-materia'), id => anotar({ materia_id: id }));
}
