/**
 * logo-imagen.js — elegir y reducir el logo de un encabezado (lo comparten el diálogo de exportar el PDF
 * y el editor de perfiles de encabezado de Mi perfil).
 */
import { medidasReducidas } from './exportar-pdf-logica.js';

export const MAX_ARCHIVO_LOGO = 8 * 1024 * 1024;

/** ¿Es una imagen que se puede usar de logo (PNG, JPG, GIF o WebP de menos de 8 MB)? */
export function logoArchivoValido(archivo) {
  return !!archivo && /^image\/(png|jpe?g|gif|webp)$/.test(archivo.type) && archivo.size <= MAX_ARCHIVO_LOGO;
}

export const MENSAJE_LOGO_INVALIDO = 'El logo debe ser una imagen PNG, JPG, GIF o WebP de menos de 8 MB.';

/** Reduce la imagen elegida (como mucho 320 px de lado, con su transparencia) y devuelve su base64. */
export function reducirLogo(archivo) {
  return new Promise((resolver, rechazar) => {
    const url = URL.createObjectURL(archivo);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const m = medidasReducidas(img.naturalWidth, img.naturalHeight);
      if (!m) { rechazar(new Error('vacía')); return; }
      const lienzo = document.createElement('canvas');
      lienzo.width = m.ancho; lienzo.height = m.alto;
      lienzo.getContext('2d').drawImage(img, 0, 0, m.ancho, m.alto);
      resolver(lienzo.toDataURL('image/png').split(',')[1]);
    };
    img.onerror = () => { URL.revokeObjectURL(url); rechazar(new Error('ilegible')); };
    img.src = url;
  });
}
