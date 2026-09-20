/**
 * tema.js — tema claro/oscuro.
 */

// Theme Toggle
export function applyTheme(dark) {
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  document.getElementById('icon-sun').style.display  = dark ? 'none'  : 'block';
  document.getElementById('icon-moon').style.display = dark ? 'block' : 'none';
  localStorage.setItem('theme', dark ? 'dark' : 'light');
}
