/**
 * historial.js — historial de conversiones guardadas.
 */
import { apiFetch } from './api.js';
import { abrirEnEditor } from './borrador.js';
import { modalHistory } from './dom.js';
import { saveFileToUser } from './resultado.js';
import { abrirModal, cerrarModal } from './ui/modales.js';
import { showToast } from './ui/toast.js';
import { esc_html } from './util.js';

export async function openHistory() {
  searchInput.value = '';
  abrirModal(modalHistory, { foco: document.getElementById('btn-close-history') });
  await loadHistoryList();
  // Con entradas, el cursor queda listo en el buscador.
  if (!searchWrap.hidden && modalHistory.classList.contains('open')) searchInput.focus();
}

export function closeHistory() {
  cerrarModal(modalHistory);
}

function _fecha(iso) {
  // SQLite guarda "YYYY-MM-DD HH:MM:SS" en UTC, sin zona: se marca como
  // UTC para que se muestre en la hora local del docente.
  const d = new Date(String(iso).replace(' ', 'T') + (String(iso).endsWith('Z') ? '' : 'Z'));
  return isNaN(d) ? String(iso) : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

// ── Buscador ────────────────────────────────────────────────────────────
// Filtra en el navegador, al instante, por nombre de archivo, categoría o
// fecha. No distingue mayúsculas ni tildes ("examen" encuentra "Exámen").
let _datos = [];
const searchWrap = document.getElementById('history-search-wrap');
const searchInput = document.getElementById('history-search');
const countEl = document.getElementById('history-count');

function _norm(t) {
  return String(t).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
}

// Resalta la coincidencia en el texto original. Solo si cada carácter
// normaliza a exactamente uno (casi siempre): así los índices coinciden.
function _resaltar(texto, q) {
  const safe = esc_html(texto);
  if (!q) return safe;
  const chars = [...String(texto)];
  const norm = chars.map(_norm);
  if (norm.some(c => c.length !== 1)) return safe;
  const i = norm.join('').indexOf(q);
  if (i < 0) return safe;
  const antes = chars.slice(0, i).join(''), med = chars.slice(i, i + q.length).join(''), desp = chars.slice(i + q.length).join('');
  return `${esc_html(antes)}<mark>${esc_html(med)}</mark>${esc_html(desp)}`;
}

searchInput.addEventListener('input', () => renderHistoryList());
// Escape con texto escrito borra la búsqueda; sin texto, cierra el modal.
searchInput.addEventListener('keydown', e => {
  if (e.key === 'Escape' && searchInput.value) {
    e.preventDefault();
    e.stopPropagation();
    searchInput.value = '';
    renderHistoryList();
  }
});

/** `enfocarId`: tras recargar la lista, devuelve el foco a la papelera de esa entrada. */
export async function loadHistoryList(enfocarId = null) {
  const list = document.getElementById('history-list');
  list.setAttribute('aria-busy', 'true');
  list.innerHTML = '<p style="padding:24px;text-align:center;color:var(--color-text-muted);">Cargando historial…</p>';

  try {
    const res = await apiFetch('/api/history');
    if (!res.ok) throw new Error('Error al consultar servidor');
    _datos = (await res.json()).map(item => ({ ...item, fecha: _fecha(item.created_at) }));
    searchWrap.hidden = _datos.length === 0;
    renderHistoryList(enfocarId);
    lucide.createIcons();
  } catch (err) {
    searchWrap.hidden = true;
    list.innerHTML = `<div style="padding:24px;text-align:center;">
      <p style="color:var(--color-error);font-size:var(--text-md);margin:0 auto 12px;">No se pudo cargar el historial.</p>
      <button type="button" class="btn btn-ghost btn-sm" data-accion="loadHistoryList">
        <i data-lucide="refresh-cw" style="width:14px;height:14px;"></i> Reintentar
      </button>
    </div>`;
    lucide.createIcons();
  } finally {
    list.removeAttribute('aria-busy');
  }
}

export function renderHistoryList(enfocarId = null) {
  const list = document.getElementById('history-list');
  if (_datos.length === 0) {
    countEl.textContent = '';
    list.innerHTML = `<div style="padding:36px 24px;text-align:center;">
      <i data-lucide="inbox" style="width:32px;height:32px;color:var(--color-text-subtle);margin-bottom:12px;"></i>
      <p style="color:var(--color-text);font-size:var(--text-md);font-weight:700;margin:0 auto 4px;">Todavía no hay conversiones guardadas</p>
      <p style="color:var(--color-text-muted);font-size:var(--text-sm);margin:0 auto 16px;">Cada examen que conviertas queda aquí para volver a descargarlo o reabrir su revisión.</p>
      <button type="button" class="btn btn-primary btn-sm" data-accion="closeHistory">Convertir tu primer examen</button>
    </div>`;
    lucide.createIcons();
    return;
  }

  const q = _norm(searchInput.value.trim());
  const visibles = q
    ? _datos.filter(item => _norm(`${item.filename} ${item.category} ${item.fecha}`).includes(q))
    : _datos;
  countEl.textContent = q ? `${visibles.length} de ${_datos.length}` : `${_datos.length} en total`;

  if (visibles.length === 0) {
    list.innerHTML = `<div style="padding:32px 24px;text-align:center;">
      <p style="color:var(--color-text);font-size:var(--text-md);font-weight:700;margin:0 auto 4px;">Sin resultados para «${esc_html(searchInput.value.trim())}»</p>
      <p style="color:var(--color-text-muted);font-size:var(--text-sm);margin:0 auto 14px;">Prueba con parte del nombre del archivo, la categoría o la fecha (ej. «sep 2026»).</p>
      <button type="button" class="btn btn-ghost btn-sm" id="btn-history-clear">Borrar búsqueda</button>
    </div>`;
    document.getElementById('btn-history-clear').addEventListener('click', () => {
      searchInput.value = '';
      renderHistoryList();
      searchInput.focus();
    });
    return;
  }

  list.innerHTML = `<ul style="list-style:none;margin:0;padding:0;">${visibles.map(item => `
    <li class="history-row" data-id="${item.id}" style="padding:14px 8px;border-bottom:1px solid var(--color-border-subtle);display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;">
      <div style="min-width:0;flex:1 1 220px;">
        <strong style="display:block;font-size:var(--text-md);color:var(--color-text);overflow-wrap:anywhere;">${_resaltar(item.filename, q)}</strong>
        <span style="font-size:12px;color:var(--color-text-muted);">${_resaltar(item.category, q)} · ${esc_html(item.total_points)} pts · ${_resaltar(item.fecha, q)}</span>
      </div>
      <div class="history-action-slot" style="display:flex;gap:6px;align-items:center;flex-shrink:0;">
        ${item.has_editor ? `<button type="button" class="btn btn-ghost btn-sm" data-accion="reopenHistory" data-arg-n="${item.id}" title="Abrir de nuevo la revisión de este examen">
          <i data-lucide="pencil" style="width:14px;height:14px;"></i> Reabrir
        </button>` : ''}
        <button type="button" class="btn btn-ghost btn-sm" data-filename="${esc_html(item.filename)}" data-id="${item.id}" data-accion="downloadHistoryDesdeBoton" data-este>
          <i data-lucide="download" style="width:14px;height:14px;"></i> Descargar XML
        </button>
        <button type="button" class="btn btn-icon btn-danger-text history-delete" data-accion="startDeleteHistory" data-este title="Borrar del historial" aria-label="Borrar «${esc_html(item.filename)}» del historial">
          <i data-lucide="trash-2" style="width:15px;height:15px;"></i>
        </button>
      </div>
    </li>`).join('')}</ul>`;
  lucide.createIcons();
  if (enfocarId != null) list.querySelector(`.history-row[data-id="${enfocarId}"] .history-delete`)?.focus();
}

/** Botón «Descargar» de una entrada: el id y el nombre van en sus data-*. */
export function downloadHistoryDesdeBoton(btn) {
  return downloadHistory(Number(btn.dataset.id), btn.dataset.filename);
}

export async function downloadHistory(id, originalFilename) {
  try {
    const res = await apiFetch(`/api/history/${id}/download`);
    if (!res.ok) throw new Error('Falló descarga');
    const blob = await res.blob();
    const nombre = String(originalFilename).normalize('NFC');
    const stem = nombre.split('.').slice(0, -1).join('.') || nombre;
    await saveFileToUser(blob, stem + '.xml', 'XML guardado en tu equipo');
  } catch (err) {
    showToast('No se pudo descargar ese XML. Vuelve a intentarlo.', 'error');
  }
}

// Reabre en el editor un examen ya convertido (con sus ediciones y
// puntos), para corregirlo y generar el XML otra vez.
export async function reopenHistory(id) {
  try {
    const res = await apiFetch(`/api/history/${id}/editor`);
    if (!res.ok) throw new Error('sin datos');
    const d = await res.json();
    closeHistory();
    abrirEnEditor(
      { filename: d.filename, category: d.category, total_points: d.total_points },
      { questions: d.questions, answer_key: d.answer_key, skipped_questions: d.skipped_questions || [] },
    );
    showToast(`Revisión de «${d.filename}» reabierta`, 'info');
  } catch (_) {
    showToast('No se pudo reabrir esa revisión', 'error');
  }
}

// Borrar una entrada: confirmación en línea (en vez de window.confirm(),
// que en la ventana de escritorio no se ve igual en todos los sistemas).
// Botones de tamaño completo y el foco en la opción segura.
export function startDeleteHistory(btn) {
  const row = btn.closest('.history-row');
  const slot = row?.querySelector('.history-action-slot');
  if (!slot) return;
  const id = row.dataset.id;
  slot.innerHTML = `
    <span style="font-size:var(--text-sm);color:var(--color-text);font-weight:700;margin-right:2px;" id="del-q-${id}">¿Borrar del historial?</span>
    <button type="button" class="btn btn-danger btn-sm" data-accion="confirmDeleteHistory" data-arg-n="${id}" aria-describedby="del-q-${id}">Borrar</button>
    <button type="button" class="btn btn-ghost btn-sm history-cancel" data-accion="renderHistoryList" data-arg-n="${id}">Cancelar</button>
  `;
  slot.querySelector('.history-cancel').focus();
}

export async function confirmDeleteHistory(id) {
  try {
    const res = await apiFetch(`/api/history/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('delete failed');
    showToast('Entrada borrada del historial', 'info');
  } catch (err) {
    showToast('No se pudo borrar la entrada', 'error');
  } finally {
    await loadHistoryList();
    document.getElementById('btn-close-history')?.focus();
  }
}
