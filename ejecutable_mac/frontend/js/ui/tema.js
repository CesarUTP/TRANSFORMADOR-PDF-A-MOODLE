/**
 * tema.js — tema claro/oscuro.
 */

// El botón muestra la ACCIÓN (a qué tema cambia), no el estado actual:
// en oscuro se ve el sol ("pasar a claro"), en claro la luna.
export function applyTheme(dark) {
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  document.getElementById('icon-sun').style.display  = dark ? 'block' : 'none';
  document.getElementById('icon-moon').style.display = dark ? 'none'  : 'block';
  const btn = document.getElementById('theme-toggle-btn');
  const label = dark ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro';
  btn.setAttribute('aria-label', label);
  btn.title = label;
  try { localStorage.setItem('theme', dark ? 'dark' : 'light'); } catch (_) {}
  window.dispatchEvent(new Event('themechange'));
}
