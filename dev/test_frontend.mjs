// Pruebas del frontend sin navegador (para la terminal y el CI).
//
//   node dev/test_frontend.mjs
//
// 1. Corre EXACTAMENTE las mismas pruebas de lógica pura que frontend/pruebas.html
//    (están en frontend/js/pruebas.js; aquí solo se prepara un DOM falso mínimo).
// 2. Comprueba que todo frontend/js/**/*.js (salvo vendor/) no tiene errores de
//    sintaxis y que sus importaciones relativas apuntan a archivos que existen.
//
// Sin dependencias: solo Node >= 20. No toca la red, la clave ni los datos.
import { execFileSync } from 'node:child_process';
import { copyFileSync, mkdtempSync, readdirSync, readFileSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const RAIZ = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const JS = join(RAIZ, 'frontend', 'js');
let fallas = 0;
const ok = (t) => console.log(`  ok   ${t}`);
const falla = (t, d = '') => { fallas++; console.log(`  FALLA ${t}${d ? ' — ' + d : ''}`); };

// ── DOM falso mínimo ─────────────────────────────────────────────────
// Solo lo que tocan los módulos que importa pruebas.js: getElementById,
// createElement('div') con textContent/innerHTML/style/remove, body.append y
// localStorage. Los módulos no se modifican: se les da este entorno antes del import.
class Elemento {
  constructor() { this.id = ''; this.textContent = ''; this.style = {}; this.offsetWidth = 0; this._padre = null; this.hijos = []; }
  get innerHTML() { return String(this.textContent).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  append(...nodos) { for (const n of nodos) { n._padre = this; this.hijos.push(n); } }
  remove() { if (this._padre) this._padre.hijos = this._padre.hijos.filter(h => h !== this); this._padre = null; }
  buscar(id) {
    for (const h of this.hijos) { if (h.id === id) return h; const r = h.buscar(id); if (r) return r; }
    return null;
  }
}
const body = new Elemento();
const almacen = new Map();
const localStorageFalso = {
  getItem: (k) => (almacen.has(k) ? almacen.get(k) : null),
  setItem: (k, v) => { almacen.set(k, String(v)); },
  removeItem: (k) => { almacen.delete(k); },
};
const poner = (nombre, valor) => Object.defineProperty(globalThis, nombre, { value: valor, configurable: true, writable: true });
poner('document', { body, createElement: () => new Elemento(), getElementById: (id) => body.buscar(id) });
poner('window', {});
poner('localStorage', localStorageFalso); // Node 22+ trae un localStorage propio: se reemplaza

// ── 1. Pruebas de lógica ─────────────────────────────────────────────
console.log('Pruebas de lógica del frontend (las mismas de pruebas.html):');
const { ejecutarPruebas } = await import(pathToFileURL(join(JS, 'pruebas.js')).href);
const resultados = ejecutarPruebas();
for (const { nombre, error } of resultados) {
  if (error === null) ok(nombre); else falla(nombre, error);
}
console.log(`  (${resultados.length} pruebas de lógica)`);

// ── 2. Sintaxis e importaciones de todo frontend/js ──────────────────
console.log('Sintaxis e importaciones de frontend/js/**/*.js:');
function archivosJs(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const ruta = join(dir, e.name);
    if (e.isDirectory()) return e.name === 'vendor' ? [] : archivosJs(ruta);
    return e.name.endsWith('.js') ? [ruta] : [];
  });
}
const archivos = archivosJs(JS).sort();
// `node --check` trata un .js como CommonJS si no hay "type": "module", así que
// cada archivo se copia con extensión .mjs a una carpeta temporal para comprobar
// su sintaxis como módulo ES (igual que lo carga el navegador).
const tmp = mkdtempSync(join(tmpdir(), 'conv-front-'));
try {
  for (const [i, f] of archivos.entries()) {
    const rel = relative(RAIZ, f).split(sep).join('/');
    const copia = join(tmp, `${i}.mjs`);
    copyFileSync(f, copia);
    let bien = true;
    try {
      execFileSync(process.execPath, ['--check', copia], { stdio: 'pipe' });
    } catch (e) {
      bien = false;
      const msg = String(e.stderr || e.message).split('\n').filter(Boolean).slice(0, 4).join(' | ');
      falla(`${rel}: error de sintaxis`, msg.replace(/\S*conv-front-\S*\.mjs/g, rel));
    }
    const codigo = readFileSync(f, 'utf8');
    for (const m of codigo.matchAll(/(?:^|\n)\s*(?:import|export)\s[^'"`;]*?from\s*['"](\.{1,2}\/[^'"]+)['"]|(?:^|\n)\s*import\s*['"](\.{1,2}\/[^'"]+)['"]/g)) {
      const dest = resolve(dirname(f), m[1] || m[2]);
      if (!existsSync(dest)) { bien = false; falla(`${rel}: la importación «${m[1] || m[2]}» no existe`); }
    }
    if (bien) ok(rel);
  }
} finally {
  rmSync(tmp, { recursive: true, force: true });
}

// ── 3. Los recorridos guiados apuntan a elementos que existen ─────────
// Un paso cuyo elemento se renombró dejaría de mostrarse sin avisar (tour.js salta lo que no encuentra).
// Aquí se comprueba que cada #id, .clase y [atributo] de un paso aparece en index.html o en los módulos.
console.log('Recorridos guiados (frontend/js/ui/tour-logica.js):');
{
  const { TOURS } = await import(pathToFileURL(join(JS, 'ui', 'tour-logica.js')).href);
  const fuentes = [readFileSync(join(RAIZ, 'frontend', 'index.html'), 'utf8'), ...archivos.map((f) => readFileSync(f, 'utf8'))].join('\n');
  const hay = (token) => fuentes.includes(token);
  for (const [nombre, t] of Object.entries(TOURS)) {
    let bien = true;
    for (const [i, p] of t.pasos.entries()) {
      if (!p.titulo || !p.texto) { bien = false; falla(`${nombre} paso ${i + 1}: sin título o sin texto`); }
      if (p.el === null) continue;
      for (const m of String(p.el).matchAll(/#([\w-]+)|\.([\w-]+)|\[data-accion="([\w]+)"\]/g)) {
        const token = m[1] ? `id="${m[1]}"` : m[2] ? m[2] : `data-accion="${m[3]}"`;
        if (!hay(token)) { bien = false; falla(`${nombre} paso ${i + 1}: «${p.el}» no existe (falta ${token})`); }
      }
    }
    if (bien) ok(`${nombre}: ${t.pasos.length} pasos`);
  }
}

console.log(fallas === 0 ? '\nTODO OK' : `\n${fallas} FALLA(S)`);
process.exit(fallas === 0 ? 0 : 1);
