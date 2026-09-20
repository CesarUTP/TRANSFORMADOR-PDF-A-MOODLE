/**
 * estado.js — el estado que comparten varios módulos.
 * 
 * Es un objeto único (no variables sueltas): así cualquier módulo lee y
 * escribe el mismo dato, y se ve de dónde sale cada cosa.
 */

export const estado = {
  /** Archivo elegido en el paso 1 (File). */
  selectedFile: null,
  /** XML generado, listo para descargar (Blob). */
  downloadBlob: null,
  downloadFilename: '',
  /** Última respuesta del backend: preguntas y clave. */
  currentParseResult: null,
  /** Nombre, categoría y puntaje total del examen en curso. */
  currentUploadMetadata: null,
  /** A qué paso vuelve el botón de la pantalla de error. */
  errorReturnPanel: 'upload',
  /** Huella del archivo para el que ya se aceptó el aviso de imágenes. */
  disclaimerAcknowledgedFor: null,
  /** Puntaje total que espera la conversión tras aceptar el aviso. */
  pendingConversionPoints: null,
};
