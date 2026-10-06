/**
 * historial.js — lo que se hace con UN examen guardado: reabrir su revisión, descargar su XML, exportarlo en PDF
 * y borrarlo. La lista y las materias (la pantalla «Mis materias») viven en biblioteca.js.
 */
import { apiFetch } from './api.js';
import { abrirEnEditor } from './borrador.js';
import { cancelConversion } from './carga.js';
import { estado } from './estado.js';
import { saveFileToUser } from './resultado.js';
import { confirmar } from './ui/confirmar.js';
import { abrirExportarPdf } from './ui/exportar-pdf.js';
import { showToast } from './ui/toast.js';

/** «YYYY-MM-DD HH:MM:SS» (UTC, como lo guarda SQLite) en la hora local del docente. */
export function fechaLocal(iso) {
  const d = new Date(String(iso).replace(' ', 'T') + (String(iso).endsWith('Z') ? '' : 'Z'));
  return isNaN(d) ? String(iso) : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

/** Configurar y exportar un examen guardado en PDF, con su clave (sin reabrir la revisión). */
export async function exportarPdfHistorial(id) {
  try {
    const res = await apiFetch(`/api/history/${id}/editor`);
    if (!res.ok) throw new Error('sin datos');
    const d = await res.json();
    abrirExportarPdf({ filename: d.filename, total_points: d.total_points, questions: d.questions, answer_key: d.answer_key, materia_id: d.materia_id, actividad: d.actividad });
  } catch (_) {
    showToast('No se pudo preparar el PDF de este examen. Vuelve a intentarlo.', 'error');
  }
}

/** Descarga el XML de un examen guardado (con el diálogo «Guardar como» de la app). */
export async function downloadHistory(id, originalFilename) {
  try {
    const res = await apiFetch(`/api/history/${id}/download`);
    if (!res.ok) throw new Error('Falló descarga');
    const blob = await res.blob();
    const nombre = String(originalFilename).normalize('NFC');
    const stem = nombre.split('.').slice(0, -1).join('.') || nombre;
    await saveFileToUser(blob, stem + '.xml', 'XML guardado en tu equipo');
  } catch (err) {
    showToast('No se pudo descargar ese XML. Vuelve a intentarlo.', 'error');
  }
}

/** ¿Hay una revisión en pantalla (aunque «Mis materias» esté abierta encima)? */
export function hayRevisionAbierta() {
  return estado.panel === 'editor';
}

/**
 * Reabre en el editor un examen ya convertido (con sus ediciones y puntos), para corregirlo y generar el XML
 * otra vez. `antesDeAbrir` se llama justo antes de cambiar de pantalla (la biblioteca se cierra ahí).
 * Devuelve true si se reabrió.
 */
export async function reopenHistory(id, antesDeAbrir = null) {
  // Reabrir REEMPLAZA la revisión que hay en pantalla (o corta una conversión
  // en curso): antes ocurría sin preguntar y el trabajo se perdía.
  const enRevision = hayRevisionAbierta();
  const convirtiendo = !!estado.conversionAbort;
  if (enRevision || convirtiendo) {
    const n = document.querySelectorAll('#editor-questions-container .editor-card').length;
    const ok = await confirmar({
      titulo: '¿Reabrir este examen?',
      mensaje: enRevision
        ? `Tienes una revisión abierta${n ? ` (${n === 1 ? '1 pregunta' : `${n} preguntas`})` : ''}. Si reabres este examen se perderá la revisión actual, con todo lo que no hayas convertido a XML. Esta acción no se puede deshacer.`
        : 'Hay una conversión en curso. Si reabres este examen se cancelará y perderás lo que lleva de avance.',
      confirmar: enRevision ? 'Reabrir y perder la revisión actual' : 'Reabrir y cancelar la conversión',
      cancelar: enRevision ? 'Seguir con mi revisión' : 'Esperar la conversión',
    });
    if (!ok) return false;
  }
  try {
    const res = await apiFetch(`/api/history/${id}/editor`);
    if (!res.ok) throw new Error('sin datos');
    const d = await res.json();
    if (antesDeAbrir) antesDeAbrir();
    if (estado.conversionAbort) cancelConversion(); // corta la conversión antes de cambiar de pantalla
    abrirEnEditor(
      { filename: d.filename, category: d.category, total_points: d.total_points, materia_id: d.materia_id ?? null, actividad: d.actividad ?? null },
      { questions: d.questions, answer_key: d.answer_key, skipped_questions: d.skipped_questions || [] },
    );
    showToast(`Revisión de «${d.filename}» reabierta`, 'info');
    return true;
  } catch (_) {
    showToast('No se pudo reabrir esa revisión', 'error');
    return false;
  }
}

/** Borra un examen del Historial (la confirmación la pide quien llama). true si se borró. */
export async function borrarExamen(id) {
  try {
    const res = await apiFetch(`/api/history/${id}`, { method: 'DELETE' });
    if (!res.ok && res.status !== 404) throw new Error('delete failed');
    return true;
  } catch (_) {
    showToast('No se pudo borrar el examen', 'error');
    return false;
  }
}
