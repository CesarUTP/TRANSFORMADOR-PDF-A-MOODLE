/* Cátedra · landing. Sin dependencias. Lo que hace:
   1) detecta el sistema y pone el botón de descarga con la versión y el tamaño REALES de la última release de GitHub
      (si la consulta falla, queda el enlace a «la última versión»);
   2) la «hoja de respuestas» fija sigue la lectura (navegación y progreso);
   3) las casillas de la pregunta 1 se marcan una vez, y las uniones del emparejamiento se dibujan al llegar. */
(() => {
  'use strict';

  const REPO = 'CesarUTP/TRANSFORMADOR-PDF-A-MOODLE';
  const URL_ULTIMA = `https://github.com/${REPO}/releases/latest`;
  const URL_API = `https://api.github.com/repos/${REPO}/releases/latest`;
  const CLAVE_CACHE = 'catedra.landing.release';
  const VIDA_CACHE_MS = 10 * 60 * 1000;

  const $ = (sel, raiz = document) => raiz.querySelector(sel);
  const $$ = (sel, raiz = document) => [...raiz.querySelectorAll(sel)];
  const reducido = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const NOMBRES = { mac: 'macOS', win: 'Windows' };

  // ── 1. Descarga ───────────────────────────────────────────────────────
  function detectarSO() {
    const plataforma = ((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || '').toLowerCase();
    const ua = (navigator.userAgent || '').toLowerCase();
    if (/android|iphone|ipad|ipod|cros/.test(ua)) return 'otro';
    if (/mac/.test(plataforma) && navigator.maxTouchPoints > 1) return 'otro';   // iPad con «Macintosh» en su agente
    if (/win/.test(plataforma) || /windows/.test(ua)) return 'win';
    if (/mac/.test(plataforma) || /macintosh|mac os x/.test(ua)) return 'mac';
    return 'otro';
  }

  const estado = { so: detectarSO(), release: null };

  /** Lo útil de la respuesta de GitHub, o null si no se entiende. Solo se aceptan enlaces de github.com. */
  function interpretar(datos) {
    if (!datos || !Array.isArray(datos.assets)) return null;
    const segura = u => typeof u === 'string' && u.startsWith('https://github.com/');
    const asset = ext => {
      const a = datos.assets.find(x => x && typeof x.name === 'string' && x.name.toLowerCase().endsWith(ext) && segura(x.browser_download_url));
      return a ? { url: a.browser_download_url, mb: Math.max(1, Math.round(Number(a.size || 0) / 1e6)) } : null;
    };
    return {
      version: String(datos.tag_name || '').replace(/^v/i, ''),
      url: segura(datos.html_url) ? datos.html_url : URL_ULTIMA,
      mac: asset('.dmg'),
      win: asset('.exe'),
    };
  }

  function leerCache() {
    try {
      const guardado = JSON.parse(sessionStorage.getItem(CLAVE_CACHE) || 'null');
      if (guardado && Date.now() - guardado.t < VIDA_CACHE_MS) return guardado.datos;
    } catch (_) { /* sin almacenamiento: se consulta */ }
    return null;
  }

  async function cargarRelease() {
    const enCache = leerCache();
    if (enCache) return interpretar(enCache);
    const control = new AbortController();
    const plazo = setTimeout(() => control.abort(), 6000);
    try {
      const res = await fetch(URL_API, { headers: { Accept: 'application/vnd.github+json' }, signal: control.signal });
      if (!res.ok) return null;
      const datos = await res.json();
      try { sessionStorage.setItem(CLAVE_CACHE, JSON.stringify({ t: Date.now(), datos })); } catch (_) { /* da igual */ }
      return interpretar(datos);
    } catch (_) {
      return null;
    } finally {
      clearTimeout(plazo);
    }
  }

  function textoMeta(r, so, asset) {
    if (!r) return '';
    const partes = [`Versión ${r.version}`];
    if (asset) partes.push(`${asset.mb} MB`);
    if (so === 'mac' && asset) partes.push('chip Apple (M1 o posterior)');
    return partes.join(' · ');
  }

  function pintarDescarga() {
    const r = estado.release;
    const so = estado.so;
    const asset = r && so !== 'otro' ? r[so] : null;

    let texto = 'Descargar desde GitHub';
    let enlace = r ? r.url : URL_ULTIMA;
    let secundario = false;
    let aviso = '';
    if (r && so === 'otro') {
      texto = 'Ver las descargas';
      aviso = 'Cátedra es una aplicación de escritorio: ábrela desde una computadora con macOS o Windows.';
    } else if (r && asset) {
      texto = `Descargar para ${NOMBRES[so]}`;
      enlace = asset.url;
    } else if (r) {
      texto = 'Ver la versión en GitHub';
      secundario = true;
      aviso = `El instalador de ${NOMBRES[so]} se publica aparte y todavía no está disponible. Mira la versión en GitHub para saber cuándo llega.`;
    }
    const meta = textoMeta(r, so, asset);

    $$('[data-dl-boton]').forEach(b => { b.href = enlace; b.classList.toggle('boton--secundario', secundario); });
    $$('[data-dl-texto]').forEach(t => { t.textContent = texto; });
    $$('[data-dl-meta]').forEach(m => { m.textContent = meta; });
    $$('[data-dl-aviso]').forEach(a => { a.textContent = aviso; a.hidden = !aviso; });
    $$('input[name="so"]').forEach(i => { i.checked = i.value === (so === 'otro' ? 'mac' : so); });

    if (r) {
      $$('[data-version]').forEach(e => { e.textContent = r.version || 'última en GitHub'; });
      const conTamano = asset || (so === 'otro' ? r.mac : null);
      $$('[data-tamano]').forEach(e => { e.textContent = conTamano ? `${conTamano.mb} MB` : '—'; });
      const disponibles = [r.mac ? 'macOS (chip Apple)' : '', r.win ? 'Windows' : ''].filter(Boolean);
      $$('[data-sistemas]').forEach(e => { e.textContent = disponibles.length ? disponibles.join(' · ') : '—'; });
      $$('[data-estado-mac]').forEach(e => { e.textContent = r.mac ? ` · ${r.mac.mb} MB` : ' · próximamente'; });
      $$('[data-estado-win]').forEach(e => { e.textContent = r.win ? ` · ${r.win.mb} MB` : ' · próximamente'; });
    }
  }

  $$('input[name="so"]').forEach(i => i.addEventListener('change', () => { estado.so = i.value; pintarDescarga(); }));
  pintarDescarga();
  cargarRelease().then(r => { if (r) { estado.release = r; pintarDescarga(); } });

  // ── 2. La hoja de respuestas sigue la lectura ─────────────────────────
  const enlaces = new Map($$('.respuestas a[data-parte]').map(a => [a.dataset.parte, a]));
  const secciones = [...enlaces.keys()].map(id => document.getElementById(id)).filter(Boolean);
  const orden = secciones.map(s => s.id);
  let actual = null;

  function marcar(id) {
    actual = id;
    const i = orden.indexOf(id);
    enlaces.forEach((a, k) => {
      a.classList.toggle('leida', orden.indexOf(k) < i);
      if (k === id) a.setAttribute('aria-current', 'location'); else a.removeAttribute('aria-current');
    });
  }

  function seguirLectura() {
    if (!secciones.length) return;
    const linea = innerHeight * 0.35;
    let id = orden[0];
    for (const s of secciones) if (s.getBoundingClientRect().top <= linea) id = s.id;
    if (innerHeight + scrollY >= document.documentElement.scrollHeight - 4) id = orden[orden.length - 1];
    if (id !== actual) marcar(id);
  }

  let pendiente = false;
  addEventListener('scroll', () => {
    if (pendiente) return;
    pendiente = true;
    requestAnimationFrame(() => { pendiente = false; seguirLectura(); });
  }, { passive: true });
  addEventListener('resize', seguirLectura);
  seguirLectura();

  // ── 3. Casillas de la pregunta 1 (una vez) ────────────────────────────
  const opciones = $('#opciones-apertura');
  if (opciones) {
    const marcarTodas = () => opciones.classList.add('marcadas');
    if (reducido) marcarTodas();
    else {
      requestAnimationFrame(() => requestAnimationFrame(marcarTodas));
      setTimeout(marcarTodas, 1500);   // por si el navegador no llega a pintar el primer cuadro
    }
  }

  // ── 4. Uniones del emparejamiento ─────────────────────────────────────
  const caja = $('#parejas-caja');
  if (caja) {
    const svg = $('.uniones', caja);
    const NS = 'http://www.w3.org/2000/svg';

    const dibujarUniones = () => {
      if (matchMedia('(max-width: 819px)').matches) { caja.classList.remove('con-uniones'); return; }
      const base = caja.getBoundingClientRect();
      svg.setAttribute('viewBox', `0 0 ${Math.round(base.width)} ${Math.round(base.height)}`);
      svg.replaceChildren();
      $$('.pareja', caja).forEach((p, i) => {
        const a = $('.necesidad', p).getBoundingClientRect();
        const b = $('.capacidad', p).getBoundingClientRect();
        const x1 = a.right - base.left, y1 = a.top + a.height / 2 - base.top;
        const x2 = b.left - base.left, y2 = b.top + b.height / 2 - base.top;
        const dx = (x2 - x1) / 2;
        const linea = document.createElementNS(NS, 'path');
        linea.setAttribute('d', `M${x1} ${y1} C${x1 + dx} ${y1} ${x2 - dx} ${y2} ${x2} ${y2}`);
        linea.setAttribute('pathLength', '1');
        linea.style.setProperty('--i', String(i));
        svg.append(linea);
        [[x1, y1], [x2, y2]].forEach(([cx, cy]) => {
          const punto = document.createElementNS(NS, 'circle');
          punto.setAttribute('cx', String(cx)); punto.setAttribute('cy', String(cy)); punto.setAttribute('r', '5');
          punto.style.setProperty('--i', String(i));
          svg.append(punto);
        });
      });
      caja.classList.add('con-uniones');
    };

    dibujarUniones();
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(dibujarUniones);
    if ('ResizeObserver' in window) new ResizeObserver(dibujarUniones).observe(caja); else addEventListener('resize', dibujarUniones);

    if (reducido || !('IntersectionObserver' in window)) caja.classList.add('dibujadas');
    else {
      const io = new IntersectionObserver(entradas => {
        if (entradas.some(e => e.isIntersecting)) { caja.classList.add('dibujadas'); io.disconnect(); }
      }, { threshold: 0.35 });
      io.observe(caja);
      setTimeout(() => caja.classList.add('dibujadas'), 8000);   // el contenido nunca se queda a medias
    }
  }

  // ── 5. Barra de descarga en pantallas estrechas ───────────────────────
  const barra = $('[data-barra-descarga]');
  const rapida = $('.descarga-rapida');
  const final = $('#descarga');
  if (barra && rapida && final && 'IntersectionObserver' in window) {
    let rapidaVisible = true, finalVisible = false;
    const actualizar = () => barra.classList.toggle('visible', !rapidaVisible && !finalVisible);
    new IntersectionObserver(e => { rapidaVisible = e[0].isIntersecting; actualizar(); }).observe(rapida);
    new IntersectionObserver(e => { finalVisible = e[0].isIntersecting; actualizar(); }, { threshold: 0.15 }).observe(final);
  }
})();
