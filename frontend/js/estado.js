/**
 * estado.js — el estado que comparten varios módulos, y el aviso de que cambió.
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

// ── Quién quiere enterarse de que el examen cambió ────────────────────────
// Lo que se calcula A PARTIR del examen (el mapa de preguntas, los chips de
// filtro, el contador de puntos) no debería actualizarse a mano en cada
// sitio que agrega o borra una pregunta: era fácil olvidar uno y que la
// pantalla quedara desfasada. Ahora quien cambia el examen avisa una vez
// con notificar(), y cada vista derivada se suscribe en app.js.
const suscriptores = new Set();

/** Registra una función que se ejecuta con cada cambio. Devuelve cómo darse de baja. */
export function suscribir(fn) {
  suscriptores.add(fn);
  return () => suscriptores.delete(fn);
}

/**
 * Avisa de un cambio en el examen. `motivo` es solo informativo (útil al
 * depurar). Un suscriptor que falle no impide que corran los demás, y
 * ninguno debe volver a llamar a notificar(): son solo lectura.
 */
export function notificar(motivo = '') {
  for (const fn of suscriptores) {
    try {
      fn(estado, motivo);
    } catch (err) {
      console.error(`Suscriptor de estado falló (${motivo}):`, err);
    }
  }
}
