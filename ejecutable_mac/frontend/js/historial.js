/**
 * historial.js — historial de conversiones guardadas.
 */
import { modalHistory } from './dom.js';
import { saveFileToUser } from './resultado.js';
import { showToast } from './ui/toast.js';
import { esc_html } from './util.js';

export async function loadHistoryList() {
  const list = document.getElementById('history-list');
  list.innerHTML = '<div style="padding:24px;text-align:center;color:var(--color-text-muted);">Cargando historial de conversiones...</div>';

  try {
    const res = await fetch('/api/history');
    if (!res.ok) throw new Error('Error al consultar servidor');
    const data = await res.json();
    if (data.length === 0) {
      list.innerHTML = `<div style="padding:36px 24px;text-align:center;">
        <i data-lucide="inbox" style="width:32px;height:32px;color:var(--color-text-subtle);margin-bottom:12px;"></i>
        <p style="color:var(--color-text-muted);font-size:14px;margin-bottom:4px;">No hay conversiones guardadas aún.</p>
        <p style="color:var(--color-text-subtle);font-size:12.5px;margin-bottom:16px;">Cada examen que conviertas queda aquí para que puedas volver a descargarlo cuando lo necesites.</p>
        <button type="button" class="btn btn-primary" onclick="closeHistory()" style="padding:10px 20px;font-size:13px;">Convertir tu primer examen</button>
      </div>`;
      lucide.createIcons();
      return;
    }
    list.innerHTML = data.map(item => `
      <div style="padding:14px 16px;border-bottom:1px solid var(--color-border-subtle);display:flex;align-items:center;justify-content:space-between;gap:10px;">
        <div style="min-width:0;">
          <strong style="display:block;font-size:14px;color:var(--color-text);">${esc_html(item.filename)}</strong>
          <span style="font-size:12px;color:var(--color-text-muted);">${esc_html(item.category)} &bull; ${item.total_points} pts &bull; ${new Date(item.created_at).toLocaleString()}</span>
        </div>
        <div style="display:flex;gap:6px;align-items:center;flex-shrink:0;">
          <button class="btn btn-ghost" data-filename="${esc_html(item.filename)}" onclick="downloadHistory(${item.id}, this.dataset.filename)" style="padding:6px 12px;font-size:12.5px;">
            <i data-lucide="download" style="width:14px;height:14px;"></i> Descargar XML
          </button>
          <div class="history-action-slot" data-id="${item.id}" style="display:flex;align-items:center;">
            <button type="button" class="btn btn-ghost" onclick="startDeleteHistory(this)" style="padding:6px 10px;color:var(--color-error);" title="Borrar del historial" aria-label="Borrar esta entrada del historial">
              <i data-lucide="trash-2" style="width:14px;height:14px;"></i>
            </button>
          </div>
        </div>
      </div>
    `).join('');
    lucide.createIcons();
  } catch (err) {
    list.innerHTML = `<div style="padding:24px;text-align:center;">
      <p style="color:var(--color-error);font-size:14px;margin-bottom:12px;">No se pudo cargar el historial.</p>
      <button type="button" class="btn btn-ghost" onclick="loadHistoryList()" style="padding:8px 16px;font-size:13px;">
        <i data-lucide="refresh-cw" style="width:14px;height:14px;"></i> Reintentar
      </button>
    </div>`;
    lucide.createIcons();
  }
}

export function closeHistory() {
  modalHistory.classList.remove('open');
  document.body.style.overflow = '';
}

export async function downloadHistory(id, originalFilename) {
  try {
    const res = await fetch(`/api/history/${id}/download`);
    if (!res.ok) throw new Error('Falló descarga');
    const blob = await res.blob();
    const stem = originalFilename.split('.').slice(0, -1).join('.') || originalFilename;
    const outName = stem + '.xml';

    await saveFileToUser(blob, outName, 'XML descargado exitosamente');
  } catch (err) {
    showToast("Error descargando historial: " + err.message, 'error');
  }
}

// Borrar una entrada del historial: pide confirmación en línea (Sí/No)
// en vez de un window.confirm() nativo, que en la ventana de escritorio
// (pywebview) no siempre se muestra de forma consistente entre SO.
export function startDeleteHistory(btn) {
  const slot = btn.closest('.history-action-slot');
  if (!slot) return;
  const id = slot.dataset.id;
  slot.innerHTML = `
    <span style="font-size:12px;color:var(--color-text-muted);margin-right:2px;">¿Borrar?</span>
    <button type="button" onclick="confirmDeleteHistory(${id})" style="background:none;border:none;color:var(--color-error);font-weight:800;font-size:12.5px;cursor:pointer;padding:4px 6px;">Sí</button>
    <button type="button" onclick="loadHistoryList()" style="background:none;border:none;color:var(--color-text-muted);font-size:12.5px;cursor:pointer;padding:4px 6px;">No</button>
  `;
}

export async function confirmDeleteHistory(id) {
  try {
    const res = await fetch(`/api/history/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('delete failed');
    showToast('Entrada eliminada del historial', 'info');
  } catch (err) {
    showToast('No se pudo borrar la entrada', 'error');
  } finally {
    loadHistoryList();
  }
}
