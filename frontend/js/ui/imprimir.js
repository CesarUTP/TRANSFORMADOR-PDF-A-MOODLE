/**
 * imprimir.js — la ventana «¿Qué quieres imprimir?» (3.2): un documento cada vez (el examen o la hoja de
 * preguntas, la hoja de respuestas o la clave), con su vista previa; el PDF, además, normal o en modo folleto. Se queda abierta
 * para descargar el siguiente. La lógica pura está en exportar-pdf-logica.js; pedir y guardar el archivo lo
 * hace exportar-pdf.js.
 */
import { LETRA_PLEGADO, admiteFolleto, documentosDe, pasosDePlegado, resumenDePapel, textoDeDescarga } from './exportar-pdf-logica.js';
import { abrirModal, cerrarModal } from './modales.js';
import { crearIconos, esc_html } from '../util.js';

const $ = id => document.getElementById(id);

/**
 * `vista(extra, pagina, signal)`: pide la vista previa → { url, paginas } o { mensaje }.
 * `descargar(extra, documento)`: genera y guarda → { guardado } o { mensaje }.
 */
export function crearImprimir({ vista, descargar }) {
  const modal = $('modal-imprimir');
  let opciones = { contenido: 'examen_y_clave', formato: 'pdf', versiones: 0 };
  let documentos = [];
  const hechos = new Set();               // los documentos ya descargados desde que se abrió
  const previa = { pagina: 1, paginas: 1, url: null, controlador: null, temporizador: null };
  let ocupada = false;

  const elegido = () => modal.querySelector('input[name="imp_documento"]:checked')?.value || documentos[0]?.id || '';
  // Con «Word» no hay modo folleto, aunque la última vez (en PDF) se hubiera elegido.
  const plegado = () => admiteFolleto(opciones.formato) && modal.querySelector('input[name="imp_modo"]:checked')?.value === 'folleto';
  const extra = () => ({ documento: elegido(), plegado: plegado(), letra_plegado: Number($('imp-letra').value) || LETRA_PLEGADO });

  function error(texto) {
    $('imp-error').textContent = texto || '';
    $('imp-error').hidden = !texto;
  }

  function pintarDocumentos() {
    const actual = elegido();
    $('imp-lista').innerHTML = documentos.map((d, i) => `<label class="pdf-opcion">
      <input type="radio" name="imp_documento" value="${esc_html(d.id)}"${(actual ? d.id === actual : i === 0) ? ' checked' : ''}>
      <span><strong>${esc_html(d.nombre)}</strong>${hechos.has(d.id) ? ' <em class="imp-hecho"><i data-lucide="check" aria-hidden="true"></i>Descargado</em>' : ''}<small>${esc_html(d.texto)}</small></span>
    </label>`).join('');
    crearIconos($('imp-lista'));
  }

  function pintarTextos() {
    const folleto = plegado();
    $('imp-modos').hidden = !admiteFolleto(opciones.formato);
    $('imp-folleto').hidden = !folleto;
    $('imp-pasos').innerHTML = pasosDePlegado(opciones.formato).map(p => `<li>${esc_html(p)}</li>`).join('');
    $('imp-nota-word').hidden = opciones.formato === 'pdf';
    $('imp-descargar-texto').textContent = textoDeDescarga({ formato: opciones.formato, versiones: opciones.versiones, ocupada });
    $('btn-imp-descargar').disabled = ocupada;
  }

  function pintarBarra() {
    $('imp-vista-pagina').textContent = `${plegado() ? 'Cara' : 'Página'} ${previa.pagina} de ${previa.paginas}`;
    $('btn-imp-vista-ant').disabled = previa.pagina <= 1;
    $('btn-imp-vista-sig').disabled = previa.pagina >= previa.paginas;
  }

  function soltarImagen() {
    if (previa.url) URL.revokeObjectURL(previa.url);
    previa.url = null;
    $('imp-vista-img').removeAttribute('src');
    $('imp-vista-img').hidden = true;
  }

  function detener() {
    clearTimeout(previa.temporizador);
    if (previa.controlador) previa.controlador.abort();
    previa.controlador = null;
  }

  async function refrescar(pagina = previa.pagina) {
    detener();
    const ctl = new AbortController();
    previa.controlador = ctl;
    const marco = $('imp-vista-marco');
    marco.classList.add('cargando');
    if ($('imp-vista-img').hidden) $('imp-vista-estado').textContent = 'Preparando la vista previa…';
    try {
      const r = await vista(extra(), pagina, ctl.signal);
      if (ctl.signal.aborted) return;
      if (r.mensaje) {
        soltarImagen();
        $('imp-vista-estado').textContent = r.mensaje;
        $('imp-papel').textContent = '';
        return;
      }
      previa.paginas = r.paginas;
      previa.pagina = Math.min(pagina, r.paginas);
      if (previa.url) URL.revokeObjectURL(previa.url);
      previa.url = r.url;
      $('imp-vista-img').src = r.url;
      $('imp-vista-img').hidden = false;
      $('imp-vista-estado').textContent = '';
      $('imp-papel').textContent = resumenDePapel({ paginas: r.paginas, plegado: plegado() });
      pintarBarra();
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      $('imp-vista-estado').textContent = 'No se pudo preparar la vista previa. Inténtalo de nuevo.';
    } finally {
      if (previa.controlador === ctl) { marco.classList.remove('cargando'); previa.controlador = null; }
    }
  }

  function cambio() {
    error('');
    pintarTextos();
    previa.pagina = 1;
    previa.paginas = 1;
    pintarBarra();
    $('imp-papel').textContent = '';
    detener();
    previa.temporizador = setTimeout(() => refrescar(1), 250);
  }

  async function alDescargar() {
    if (ocupada) return;
    error('');
    ocupada = true;
    pintarTextos();
    const documento = documentos.find(d => d.id === elegido());
    try {
      const r = await descargar(extra(), documento);
      if (r.mensaje) error(r.mensaje);
      else if (r.guardado) { hechos.add(documento.id); pintarDocumentos(); }
    } finally {
      ocupada = false;
      pintarTextos();
    }
  }

  return {
    iniciar() {
      $('imp-lista').addEventListener('change', cambio);
      modal.querySelectorAll('input[name="imp_modo"]').forEach(r => r.addEventListener('change', cambio));
      $('imp-letra').addEventListener('change', cambio);
      $('btn-imp-descargar').addEventListener('click', alDescargar);
      $('btn-imp-listo').addEventListener('click', () => cerrarModal(modal));
      $('btn-imp-cerrar').addEventListener('click', () => cerrarModal(modal));
      modal.addEventListener('click', e => { if (e.target === modal) cerrarModal(modal); });
      $('btn-imp-vista-ant').addEventListener('click', () => refrescar(previa.pagina - 1));
      $('btn-imp-vista-sig').addEventListener('click', () => refrescar(previa.pagina + 1));
    },
    /** `datos`: { contenido, formato, versiones (cuántas; 0 = sin versiones), plegado, letra_plegado }. */
    abrir(datos) {
      opciones = datos;
      documentos = documentosDe(datos.contenido);
      hechos.clear();
      ocupada = false;
      $('imp-lista').innerHTML = '';
      pintarDocumentos();
      modal.querySelector(`input[name="imp_modo"][value="${datos.plegado ? 'folleto' : 'normal'}"]`).checked = true;
      $('imp-letra').value = String(datos.letra_plegado || LETRA_PLEGADO);
      soltarImagen();
      abrirModal(modal, {
        foco: modal.querySelector('input[name="imp_documento"]:checked'),
        onClose: () => { detener(); soltarImagen(); },
      });
      cambio();
    },
  };
}
