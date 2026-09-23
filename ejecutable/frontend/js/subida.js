/**
 * subida.js — enviar el archivo al conversor informando cuánto se subió.
 *
 * fetch() no dice cuánto del archivo ya se envió; XMLHttpRequest sí
 * (xhr.upload.onprogress). Con un PDF de varios MB eso permite mostrar
 * una barra real ("12,3 de 24,0 MB") en vez de una pantalla quieta.
 * También va entregando la respuesta a medida que llega (onTexto), que
 * es lo que usa la lectura del avance en vivo (NDJSON).
 */
import { formatBytes } from './util.js';

/**
 * Envía `formData` por POST a `url`.
 *   onSubida(enviados, total)  — avance de la subida del archivo
 *   onSubido()                 — el archivo terminó de subir (el servidor ya trabaja)
 *   onTexto(textoAcumulado)    — la respuesta, a medida que llega
 *   signal                     — AbortController.signal para cancelar
 * Resuelve con { status, text }. Si se cancela, rechaza con un error
 * cuyo name es 'AbortError' (igual que fetch).
 */
export function subir(url, formData, { onSubida, onSubido, onTexto, signal } = {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    if (onSubida) xhr.upload.onprogress = e => { if (e.lengthComputable) onSubida(e.loaded, e.total); };
    if (onSubido) xhr.upload.onload = () => onSubido();
    if (onTexto) xhr.onprogress = () => onTexto(xhr.responseText);
    xhr.onload = () => resolve({ status: xhr.status, text: xhr.responseText });
    xhr.onerror = () => reject(new Error('sin conexión con el conversor'));
    xhr.onabort = () => { const e = new Error('cancelado'); e.name = 'AbortError'; reject(e); };
    if (signal) {
      if (signal.aborted) { xhr.abort(); return; }
      signal.addEventListener('abort', () => xhr.abort(), { once: true });
    }
    xhr.send(formData);
  });
}

// ── Barra de subida bajo el nombre del archivo (paso 1) ─────────────────
// Solo aparece si la operación dura más de 300 ms (con archivos chicos
// todo termina antes y no hay parpadeo). Primero muestra el avance real
// de la subida; después, mientras el conversor revisa el archivo ya
// recibido, la barra queda llena y el texto cuenta los segundos.
export function barraDeSubida(archivo) {
  const bar = document.getElementById('upload-bar');
  const fill = bar.querySelector('.upload-fill');
  const track = bar.querySelector('.upload-track');
  const text = bar.querySelector('.upload-text');
  let visible = false;
  let estadoTexto = 'Preparando el archivo…';
  let reloj = null;
  const timer = setTimeout(() => {
    visible = true;
    bar.hidden = false;
    text.textContent = estadoTexto;
  }, 300);

  const pintar = t => { estadoTexto = t; if (visible) text.textContent = t; };

  return {
    progreso(enviados, total) {
      bar.classList.remove('is-waiting');
      const f = total ? enviados / total : 0;
      fill.style.transform = `scaleX(${f})`;
      track.setAttribute('aria-valuenow', String(Math.round(f * 100)));
      pintar(`Subiendo ${formatBytes(enviados)} de ${formatBytes(total || archivo.size)}`);
    },
    revisando() {
      bar.classList.add('is-waiting');
      fill.style.transform = '';
      track.setAttribute('aria-valuenow', '100');
      const desde = Date.now();
      pintar('Archivo recibido · revisando su contenido…');
      clearInterval(reloj);
      reloj = setInterval(() => {
        const seg = Math.round((Date.now() - desde) / 1000);
        pintar(`Archivo recibido · revisando su contenido… ${seg} s`);
      }, 1000);
    },
    fin() {
      clearTimeout(timer);
      clearInterval(reloj);
      bar.hidden = true;
      bar.classList.remove('is-waiting');
      fill.style.transform = 'scaleX(0)';
      text.textContent = '';
    },
  };
}
