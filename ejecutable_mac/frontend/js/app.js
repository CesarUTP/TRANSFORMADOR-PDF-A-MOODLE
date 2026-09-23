/**
 * app.js — punto de entrada: conecta los eventos de la página.
 * 
 * Al final expone en `window` las funciones que el HTML llama desde
 * atributos onclick. Es el único lugar donde se toca `window`.
 */

import { borrarBorrador, guardarBorrador, guardarBorradorAhora, mostrarAvisoBorrador, retomarBorrador } from './borrador.js';
import { cancelConversion, clearFile, handleFileSelected, runConversion, runNormalizeWithAI } from './carga.js';
import { aiPromptText, btnConvert, btnCopyPrompt, btnRemoveFile, copyIcon, copyLabel, dropZone, fileInput, modalDisclaimer, modalHelp, modalHistory, modalTabs, pointsError, pointsInput } from './dom.js';
import { clozeAddOption, clozeInsertBlank, clozeRemoveBlank, clozeRemoveOption, clozeToggleMulti } from './editor/cloze.js';
import { refreshFilterChips, selectFilter, toggleFilterMenu } from './editor/filtros.js';
import { buildReviewRail, closeRailGrid, jumpRelative, jumpToNextFlagged, scheduleIssuesRefresh, toggleRailGrid } from './editor/panel.js';
import { toggleAddQuestionMenu } from './editor/paneles.js';
import { applyPointsDistribution, setPointsToolMode, togglePointsToolMenu, updatePointsAssignedLabel, updatePointsWeightPreview } from './editor/puntos-ui.js';
import { addMatchingPairRow, addNewQuestion, deleteQuestionCard, recoverSkippedQuestion, removeMatchingPairRow } from './editor/tarjetas.js';
import { estado, suscribir } from './estado.js';
import { closeHistory, confirmDeleteHistory, downloadHistory, loadHistoryList, openHistory, renderHistoryList, reopenHistory, startDeleteHistory } from './historial.js';
import { confirmDiscardReview, resetAll, showPanel } from './navegacion.js';
import { generateXml, saveFileToUser } from './resultado.js';
import { cerrarConfirmacion } from './ui/confirmar.js';
import { cerrarModal, closeDisclaimer, closeHelp, fileFingerprint, modalActivo, onTabKeydown, openDisclaimer, openHelp, switchTab } from './ui/modales.js';
import { applyTheme } from './ui/tema.js';
import { barraDeSubida, subir } from './subida.js';
import { showToast } from './ui/toast.js';

// ── Vistas que se actualizan solas cuando cambia el examen ──────────────
// Añadir, borrar o repartir puntos solo tiene que llamar a notificar():
// desde aquí se redibujan los chips de filtro (que a su vez refrescan el
// mapa de preguntas) y el contador "X / Y pts".
suscribir(() => {
  refreshFilterChips();
  updatePointsAssignedLabel();
  updatePointsWeightPreview();
  guardarBorrador();
});

// ── Funciones que el HTML llama desde atributos onclick ──────────────────
// Los módulos tienen ámbito propio, así que las que usa el HTML inline se
// publican aquí, en un solo lugar y de forma explícita.
Object.assign(window, { addMatchingPairRow, addNewQuestion, applyPointsDistribution, closeHistory, clozeAddOption, clozeInsertBlank, clozeRemoveBlank, clozeRemoveOption, clozeToggleMulti, confirmDeleteHistory, confirmDiscardReview, deleteQuestionCard, downloadHistory, generateXml, jumpToNextFlagged, loadHistoryList, openHelp, renderHistoryList, recoverSkippedQuestion, removeMatchingPairRow, reopenHistory, resetAll, selectFilter, setPointsToolMode, startDeleteHistory, toggleAddQuestionMenu, toggleFilterMenu, togglePointsToolMenu, toggleRailGrid });

// Init Lucide Icons
lucide.createIcons();

// La app abre SIEMPRE en modo claro, sin importar el tema del sistema ni
// lo que se eligió la vez anterior. El botón de tema sigue cambiándolo
// durante la sesión.
applyTheme(false);

// ¿Quedó una revisión a medias la última vez? Se ofrece retomarla.
mostrarAvisoBorrador();
document.getElementById('btn-draft-resume').addEventListener('click', retomarBorrador);
document.getElementById('btn-draft-discard').addEventListener('click', () => {
  borrarBorrador();
  showToast('Revisión sin terminar descartada', 'info');
  dropZone.focus();
});

document.getElementById('theme-toggle-btn').addEventListener('click', () => {
  applyTheme(document.documentElement.getAttribute('data-theme') !== 'dark');
});

document.getElementById('btn-help').addEventListener('click', () => openHelp('about'));

document.getElementById('btn-close-modal').addEventListener('click', closeHelp);

modalHelp.addEventListener('click', e => { if (e.target === modalHelp) closeHelp(); });

// Escape cierra el modal de más arriba (el que tiene el foco), sea cual
// sea: Guía, Historial, aviso de imágenes o confirmación.
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  const activo = modalActivo();
  if (!activo) return;
  e.preventDefault();
  if (activo.id === 'modal-confirm') cerrarConfirmacion();
  else cerrarModal(activo);
});

modalTabs.forEach(tab => {
  tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  tab.addEventListener('keydown', onTabKeydown);
});

btnCopyPrompt.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(aiPromptText.textContent);
    copyLabel.textContent = 'Copiado';
    copyIcon.setAttribute('data-lucide', 'check');
    lucide.createIcons();
    setTimeout(() => {
      copyLabel.textContent = 'Copiar instrucciones';
      copyIcon.setAttribute('data-lucide', 'copy');
      lucide.createIcons();
    }, 2500);
  } catch (_) {
    showToast('No se pudo copiar: selecciona el texto y cópialo a mano', 'error');
  }
});

// Cada edición en el editor revisa las preguntas incompletas y guarda
// el borrador (ambos con un pequeño retraso).
['input', 'change', 'click'].forEach(evt => {
  document.addEventListener(evt, e => {
    if (e.target.closest && e.target.closest('#editor-questions-container')) {
      scheduleIssuesRefresh();
      if (evt !== 'click') guardarBorrador();
    }
  }, true);
});

// La altura del header cambia con el ancho: al redimensionar se
// recoloca el panel de revisión (con un cuadro de retraso).
let _resizeRaf = 0;
window.addEventListener('resize', () => {
  if (!document.body.classList.contains('editor-active')) return;
  cancelAnimationFrame(_resizeRaf);
  _resizeRaf = requestAnimationFrame(buildReviewRail);
});

// En pantallas angostas la grilla abierta se cierra con Escape o con un
// clic fuera del panel, como cualquier menú desplegable.
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || modalActivo()) return;
  closeRailGrid();
});

document.addEventListener('click', e => {
  const rail = document.getElementById('review-rail');
  if (rail?.classList.contains('grid-open') && !rail.contains(e.target)) closeRailGrid();
});

// Atajos del editor (la lista está en la Guía → Revisión, «¿Cómo reviso?»):
// J / K siguiente / anterior, I siguiente incompleta, R siguiente para
// revisar, ? abre la Guía en esa pestaña. Solo cuando no se está
// escribiendo en un campo ni hay un modal abierto.
document.addEventListener('keydown', e => {
  if (!document.body.classList.contains('editor-active') || modalActivo()) return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const t = e.target;
  if (t.closest && t.closest('input, textarea, select, [contenteditable="true"]')) return;
  if (e.key === '?') { e.preventDefault(); openHelp('review'); return; }
  const k = e.key.toLowerCase();
  if (k === 'j') { e.preventDefault(); jumpRelative(1); }
  else if (k === 'k') { e.preventDefault(); jumpRelative(-1); }
  else if (k === 'i') { e.preventDefault(); jumpToNextFlagged('incomplete'); }
  else if (k === 'r') { e.preventDefault(); jumpToNextFlagged('review'); }
});

// Si se cierra o recarga la ventana a mitad de la revisión, el borrador
// se guarda al instante (sin esperar el retraso).
window.addEventListener('pagehide', () => {
  if (document.body.classList.contains('editor-active')) guardarBorradorAhora();
});

document.getElementById('editor-questions-container').addEventListener('input', e => {
  if (e.target.classList.contains('q-points')) updatePointsAssignedLabel();
  if (e.target.classList.contains('points-weight-input')) updatePointsWeightPreview();
});

document.getElementById('btn-close-disclaimer').addEventListener('click', closeDisclaimer);

document.getElementById('btn-disclaimer-cancel').addEventListener('click', closeDisclaimer);

modalDisclaimer.addEventListener('click', e => { if (e.target === modalDisclaimer) closeDisclaimer(); });

document.getElementById('btn-disclaimer-continue').addEventListener('click', () => {
  estado.disclaimerAcknowledgedFor = fileFingerprint(estado.selectedFile);
  closeDisclaimer();
  runConversion(estado.pendingConversionPoints, 'images');
});

document.getElementById('btn-error-normalize').addEventListener('click', () => {
  const ptsVal = parseFloat(pointsInput.value) || 100;
  runNormalizeWithAI(ptsVal);
});

btnConvert.addEventListener('click', async () => {
  if (!estado.selectedFile) return;
  const ptsVal = parseFloat(pointsInput.value);
  if (isNaN(ptsVal) || ptsVal <= 0) {
    pointsError.style.display = 'block';
    pointsInput.setAttribute('aria-invalid', 'true');
    pointsInput.focus();
    return;
  }
  pointsError.style.display = 'none';
  pointsInput.removeAttribute('aria-invalid');

  // Aviso previo de "caso especial" (imágenes incrustadas: código en
  // captura, marcas de respuesta solo por color) — solo para PDF, y
  // solo si el usuario no lo confirmó ya para este mismo archivo. Se
  // muestra ANTES de arrancar el procesamiento pesado para que el
  // usuario decida si prefiere normalizar el documento con el Prompt IA
  // de la guía antes de continuar.
  const fp = fileFingerprint(estado.selectedFile);
  if (estado.selectedFile.name.toLowerCase().endsWith('.pdf') && estado.disclaimerAcknowledgedFor !== fp) {
    // Este chequeo sube el PDF entero: con archivos grandes tarda, así
    // que el botón se bloquea (sin doble clic) y bajo el nombre del
    // archivo aparece una barra con el avance real de la subida.
    const barra = barraDeSubida(estado.selectedFile);
    const labelOriginal = btnConvert.innerHTML;
    btnConvert.disabled = true;
    btnConvert.setAttribute('aria-busy', 'true');
    btnConvert.innerHTML = '<i data-lucide="loader-2" style="width:20px;height:20px;animation:spinSlow 0.8s linear infinite;"></i> Revisando el archivo…';
    lucide.createIcons();
    try {
      const checkForm = new FormData();
      checkForm.append('file', estado.selectedFile);
      const checkRes = await subir('/api/check_special_cases', checkForm, {
        onSubida: (enviados, total) => barra.progreso(enviados, total),
        onSubido: () => barra.revisando(),
      });
      if (checkRes.status === 200) {
        const checkData = JSON.parse(checkRes.text);
        if (checkData.has_special_images) {
          estado.pendingConversionPoints = ptsVal;
          openDisclaimer();
          return;
        }
      }
    } catch (_) {
      // Si el chequeo previo falla (p. ej. sin conexión momentánea), no
      // bloqueamos la conversión por esto: se omite el aviso y se
      // procede directo, igual que antes de que existiera este chequeo.
    } finally {
      barra.fin();
      btnConvert.innerHTML = labelOriginal;
      btnConvert.removeAttribute('aria-busy');
      btnConvert.disabled = !estado.selectedFile;
      lucide.createIcons();
    }
  }

  await runConversion(ptsVal);
});

document.getElementById('btn-history').addEventListener('click', openHistory);
document.getElementById('btn-close-history').addEventListener('click', closeHistory);

modalHistory.addEventListener('click', e => { if (e.target === modalHistory) closeHistory(); });

document.getElementById('btn-cancel-progress').addEventListener('click', cancelConversion);

// Dropzone Events
dropZone.addEventListener('click', () => fileInput.click());

dropZone.addEventListener('keydown', e => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
});

dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });

dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));

dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  if (e.dataTransfer.files[0]) handleFileSelected(e.dataTransfer.files[0]);
});

fileInput.addEventListener('change', () => { if (fileInput.files[0]) handleFileSelected(fileInput.files[0]); });

btnRemoveFile.addEventListener('click', e => { e.stopPropagation(); clearFile(); dropZone.focus(); });

document.getElementById('btn-download').addEventListener('click', async () => {
  if (!estado.downloadBlob) return;
  const saved = await saveFileToUser(estado.downloadBlob, estado.downloadFilename, 'XML guardado en tu equipo');
  if (saved) document.getElementById('btn-download-label').textContent = 'Descargar otra vez';
});

// Volver a la revisión desde la pantalla final: el editor sigue intacto
// (solo estaba oculto), así que se puede corregir y generar de nuevo.
document.getElementById('btn-back-to-review').addEventListener('click', () => {
  showPanel('editor');
  buildReviewRail();
});

// Reset Handlers
document.getElementById('btn-reset-success').addEventListener('click', () => {
  resetAll();
  mostrarAvisoBorrador();
});

document.getElementById('btn-reset-error').addEventListener('click', () => {
  if (estado.errorReturnPanel === 'editor') {
    // El error vino de generar el XML: el trabajo del docente sigue
    // intacto en el editor, así que se vuelve ahí.
    showPanel('editor');
    buildReviewRail();
  } else {
    // Error leyendo el archivo: se vuelve al paso 1 CONSERVANDO el
    // archivo elegido (antes había que buscarlo de nuevo).
    showPanel('upload');
  }
});
