/**
 * actualizacion.js — aviso de versión nueva.
 *
 * Al arrancar se pregunta al servidor local si hay una versión más nueva
 * (él consulta version.json; ver backend/actualizaciones.py). Si la hay,
 * un aviso con un botón que abre la página de descarga en el navegador.
 * Sin internet o sin novedad no se muestra nada.
 */
import { apiFetch } from '../api.js';
import { abrirEnlaceExterno } from '../util.js';
import { showToast } from './toast.js';

export async function avisarSiHayVersionNueva() {
  let info;
  try {
    const res = await apiFetch('/api/actualizacion');
    if (!res.ok) return;
    info = await res.json();
  } catch (_) {
    return;
  }
  if (!info || !info.hay) return;
  // showToast pone el mensaje con textContent: las notas no se leen como HTML.
  const notas = info.notas ? ` ${info.notas}` : '';
  showToast(`Hay una versión nueva del conversor (${info.version}); tienes la ${info.actual}.${notas}`, 'info', {
    accion: { texto: 'Descargar', alPulsar: () => abrirEnlaceExterno(info.url) },
  });
}
