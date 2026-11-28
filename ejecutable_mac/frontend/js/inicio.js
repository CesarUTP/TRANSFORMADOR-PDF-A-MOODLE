/**
 * inicio.js — la pantalla «¿Cómo quieres empezar?» (3.2): convertir un documento, escribir un examen desde cero
 * o abrir un Moodle XML. Soltar un archivo sobre ella lleva directo a su camino.
 */
import { abrirEnEditor, resumenDelBorrador } from './borrador.js';
import { clearFile, handleFileSelected, ponerModoCarga } from './carga.js';
import { metaDesdeCero } from './editor/nuevo-logica.js';
import { estado } from './estado.js';
import { leerPaso1 } from './materias.js';
import { showPanel } from './navegacion.js';
import { confirmar } from './ui/confirmar.js';

function irACarga(modo) {
  clearFile();
  ponerModoCarga(modo);
  showPanel('upload');
}

export const empezarConDocumento = () => irACarga('documento');
export const empezarConXml = () => irACarga('xml');

export function volverAlInicio() {
  clearFile();
  showPanel('inicio');
}

/** Directo al editor, con un examen vacío. Si hay una revisión a medias, se pregunta antes de reemplazarla. */
export async function empezarDesdeCero() {
  const previa = resumenDelBorrador();
  if (previa) {
    const ok = await confirmar({
      titulo: 'Tienes una evaluación sin terminar',
      mensaje: `«${previa.nombre}» (${previa.preguntas} pregunta${previa.preguntas === 1 ? '' : 's'}) se reemplazará en cuanto agregues la primera pregunta de la evaluación nueva.`,
      confirmar: 'Empezar la evaluación nueva',
      cancelar: 'Conservarla',
    });
    if (!ok) return;
  }
  clearFile();
  estado.downloadBlob = null;
  estado.downloadFilename = '';
  estado.exportable = null;
  estado.historialId = null;
  // La materia que estuviera elegida (por ejemplo, al llegar desde «Mis materias») acompaña al examen nuevo.
  abrirEnEditor(metaDesdeCero({ materia_id: leerPaso1().materia_id }), { questions: [], answer_key: {} });
}

export function iniciarInicio() {
  const panel = document.getElementById('panel-inicio');
  const conArchivos = e => [...(e.dataTransfer?.types || [])].includes('Files');
  panel.addEventListener('dragover', e => {
    if (!conArchivos(e)) return;
    e.preventDefault();
    panel.classList.add('arrastrando');
  });
  panel.addEventListener('dragleave', e => {
    if (!panel.contains(e.relatedTarget)) panel.classList.remove('arrastrando');
  });
  panel.addEventListener('drop', e => {
    if (!conArchivos(e)) return;
    e.preventDefault();
    panel.classList.remove('arrastrando');
    const archivo = e.dataTransfer.files[0];
    if (!archivo) return;
    irACarga(/\.xml$/i.test(archivo.name) ? 'xml' : 'documento');
    handleFileSelected(archivo);
  });
}
