/**
 * app.js — punto de entrada: conecta los eventos de la página.
 * 
 * Al final expone en `window` las funciones que el HTML llama desde
 * atributos onclick. Es el único lugar donde se toca `window`.
 */

import { clearFile, handleFileSelected, runConversion, runNormalizeWithAI } from './carga.js';
import { aiPromptText, btnConvert, btnCopyPrompt, btnRemoveFile, copyIcon, copyLabel, dropZone, fileInput, modalDisclaimer, modalHelp, modalHistory, modalTabs, pointsError, pointsInput } from './dom.js';
import { clozeAddOption, clozeInsertBlank, clozeRemoveBlank, clozeRemoveOption, clozeToggleMulti } from './editor/cloze.js';
import { refreshFilterChips, selectFilter, toggleFilterMenu } from './editor/filtros.js';
import { buildReviewRail, jumpToNextFlagged, scheduleIssuesRefresh, toggleRailGrid } from './editor/panel.js';
import { toggleAddQuestionMenu, toggleAllPanels } from './editor/paneles.js';
import { applyPointsDistribution, setPointsToolMode, togglePointsToolMenu, updatePointsAssignedLabel, updatePointsWeightPreview } from './editor/puntos-ui.js';
import { addMatchingPairRow, addNewQuestion, deleteQuestionCard, recoverSkippedQuestion } from './editor/tarjetas.js';
import { estado, suscribir } from './estado.js';
import { closeHistory, confirmDeleteHistory, downloadHistory, loadHistoryList, startDeleteHistory } from './historial.js';
import { resetAll, showPanel } from './navegacion.js';
import { generateXml, saveFileToUser } from './resultado.js';
import { closeDisclaimer, closeHelp, fileFingerprint, openDisclaimer, openHelp, switchTab } from './ui/modales.js';
import { applyTheme } from './ui/tema.js';
import { showToast } from './ui/toast.js';

// ── Vistas que se actualizan solas cuando cambia el examen ──────────────
// Añadir, borrar o repartir puntos solo tiene que llamar a notificar():
// desde aquí se redibujan los chips de filtro (que a su vez refrescan el
// mapa de preguntas) y el contador "X / Y pts".
suscribir(() => {
  refreshFilterChips();
  updatePointsAssignedLabel();
  updatePointsWeightPreview();
});

// ── Funciones que el HTML llama desde atributos onclick ──────────────────
// Los módulos tienen ámbito propio, así que las que usa el HTML inline se
// publican aquí, en un solo lugar y de forma explícita.
Object.assign(window, { addMatchingPairRow, addNewQuestion, applyPointsDistribution, closeHistory, clozeAddOption, clozeInsertBlank, clozeRemoveBlank, clozeRemoveOption, clozeToggleMulti, confirmDeleteHistory, deleteQuestionCard, downloadHistory, generateXml, jumpToNextFlagged, loadHistoryList, openHelp, recoverSkippedQuestion, resetAll, selectFilter, setPointsToolMode, startDeleteHistory, toggleAddQuestionMenu, toggleAllPanels, toggleFilterMenu, togglePointsToolMenu, toggleRailGrid });

// Init Lucide Icons
lucide.createIcons();

(function initTheme() {
  const saved = localStorage.getItem('theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  applyTheme(saved === 'dark' || (!saved && prefersDark));
})();

document.getElementById('theme-toggle-btn').addEventListener('click', () => {
  applyTheme(document.documentElement.getAttribute('data-theme') !== 'dark');
});

document.getElementById('btn-help').addEventListener('click', () => openHelp('about'));

document.getElementById('btn-close-modal').addEventListener('click', closeHelp);

modalHelp.addEventListener('click', e => { if (e.target === modalHelp) closeHelp(); });

// Escape cierra el modal que esté abierto en ese momento — antes solo
// funcionaba en la Guía; Historial y el aviso de imágenes incrustadas
// solo se podían cerrar con el mouse.
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  if (modalHelp.classList.contains('open')) closeHelp();
  else if (modalHistory.classList.contains('open')) closeHistory();
  else if (modalDisclaimer.classList.contains('open')) closeDisclaimer();
});

modalTabs.forEach(tab => tab.addEventListener('click', () => switchTab(tab.dataset.tab)));

btnCopyPrompt.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(aiPromptText.textContent);
    copyLabel.textContent = '¡Copiado Exitosamente!';
    copyIcon.setAttribute('data-lucide', 'check');
    lucide.createIcons();
    setTimeout(() => {
      copyLabel.textContent = 'Copiar Prompt';
      copyIcon.setAttribute('data-lucide', 'copy');
      lucide.createIcons();
    }, 2500);
  } catch (_) {
    showToast('Selecciona el texto manualmente', 'error');
  }
});

// State Variables

// Qué panel debe restaurar el botón "Intentar Nuevamente" de la pantalla
// de error: 'upload' si el error ocurrió leyendo el archivo (nada que
// conservar todavía), o 'editor' si ocurrió al generar el XML — en ese
// caso el usuario ya invirtió tiempo corrigiendo preguntas a mano y
// perderlo todo por, por ejemplo, olvidar marcar una casilla en una sola
// pregunta sería devastador para la experiencia.

// Huella del último archivo para el que el usuario ya confirmó el
// disclaimer de "contenido especial" (imágenes incrustadas) — evita
// volver a preguntarle si hace clic en Convertir más de una vez sin
// cambiar de archivo. Se resetea a null en clearFile()/showFilePreview().

['input', 'change', 'click'].forEach(evt => {
  document.addEventListener(evt, e => {
    if (e.target.closest && e.target.closest('#editor-questions-container')) scheduleIssuesRefresh();
  }, true);
});


// La altura del header cambia con el ancho (el subtítulo ocupa 1-3
// líneas): al redimensionar se recoloca el panel de revisión.
window.addEventListener('resize', () => {
  if (document.body.classList.contains('editor-active')) buildReviewRail();
});

// En pantallas angostas la grilla abierta se cierra con Escape o con un
// clic fuera del panel, como cualquier menú desplegable.
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.getElementById('review-rail')?.classList.remove('grid-open');
});

document.addEventListener('click', e => {
  const rail = document.getElementById('review-rail');
  if (rail?.classList.contains('grid-open') && !rail.contains(e.target)) rail.classList.remove('grid-open');
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
    return;
  }
  pointsError.style.display = 'none';

  // Aviso previo de "caso especial" (imágenes incrustadas: código en
  // captura, marcas de respuesta solo por color) — solo para PDF, y
  // solo si el usuario no lo confirmó ya para este mismo archivo. Se
  // muestra ANTES de arrancar el procesamiento pesado para que el
  // usuario decida si prefiere normalizar el documento con el Prompt IA
  // de la guía antes de continuar.
  const fp = fileFingerprint(estado.selectedFile);
  if (estado.selectedFile.name.toLowerCase().endsWith('.pdf') && estado.disclaimerAcknowledgedFor !== fp) {
    try {
      const checkForm = new FormData();
      checkForm.append('file', estado.selectedFile);
      const checkRes = await fetch('/api/check_special_cases', { method: 'POST', body: checkForm });
      if (checkRes.ok) {
        const checkData = await checkRes.json();
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
    }
  }

  await runConversion(ptsVal);
});

document.getElementById('btn-history').addEventListener('click', () => {
  modalHistory.classList.add('open');
  document.body.style.overflow = 'hidden';
  loadHistoryList();
});

modalHistory.addEventListener('click', e => { if (e.target === modalHistory) closeHistory(); });

// Dropzone Events
dropZone.addEventListener('click', () => fileInput.click());

dropZone.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') fileInput.click(); });

dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });

dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));

dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  if (e.dataTransfer.files[0]) handleFileSelected(e.dataTransfer.files[0]);
});

fileInput.addEventListener('change', () => { if (fileInput.files[0]) handleFileSelected(fileInput.files[0]); });

btnRemoveFile.addEventListener('click', e => { e.stopPropagation(); clearFile(); });

document.getElementById('btn-download').addEventListener('click', async () => {
  if (!estado.downloadBlob) return;
  await saveFileToUser(estado.downloadBlob, estado.downloadFilename, 'Archivo guardado en tu equipo');
});

// Reset Handlers
document.getElementById('btn-reset-success').addEventListener('click', resetAll);

document.getElementById('btn-reset-error').addEventListener('click', () => {
  if (estado.errorReturnPanel === 'editor') {
    // El error vino de generar el XML, no de leer el archivo: el usuario
    // ya editó preguntas a mano y ese trabajo sigue intacto en el DOM del
    // panel 2, así que se vuelve ahí en vez de reiniciar todo el flujo.
    showPanel('editor');
  } else {
    resetAll();
  }
});
