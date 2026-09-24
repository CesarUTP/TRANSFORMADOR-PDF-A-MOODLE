/**
 * api.js — peticiones al servidor local con el token de este arranque.
 *
 * El servidor rechaza cualquier petición a /api/ sin la cabecera
 * X-Conversor-Token (así ninguna otra página web abierta en el equipo puede
 * leer el historial, cambiar la clave ni gastar la cuota de Gemini; ver
 * backend/seguridad.py). El launcher abre la ventana en «…/#t=TOKEN»: el
 * fragmento nunca viaja al servidor. Se guarda en sessionStorage (sobrevive
 * a una recarga de la ventana) y se quita de la barra de direcciones.
 */

const CLAVE = 'conversor-token';

function leerToken() {
  const m = /(?:^|[#&])t=([A-Za-z0-9_-]+)/.exec(location.hash);
  if (m) {
    try { sessionStorage.setItem(CLAVE, m[1]); } catch (_) { /* sin almacenamiento: vale para esta carga */ }
    history.replaceState(null, '', location.pathname + location.search);
    return m[1];
  }
  try { return sessionStorage.getItem(CLAVE) || ''; } catch (_) { return ''; }
}

export const TOKEN = leerToken();
export const CABECERA_TOKEN = 'X-Conversor-Token';

/** fetch() con el token. Mismas opciones y respuesta que fetch(). */
export function apiFetch(url, opciones = {}) {
  const headers = new Headers(opciones.headers || {});
  headers.set(CABECERA_TOKEN, TOKEN);
  return fetch(url, { ...opciones, headers });
}
