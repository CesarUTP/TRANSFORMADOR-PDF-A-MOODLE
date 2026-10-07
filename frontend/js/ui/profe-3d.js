/**
 * profe-3d.js — el personaje 3D del asistente flotante (ui/asistente.js): un robot redondo y amable.
 *
 * Está armado entero con código (three.js): ningún modelo ni imagen descargados. Cabeza esférica blanca con un visor
 * azul marino donde se dibujan dos ojos felices (arcos celestes) y dos mejillas ámbar, antena con una bolita ámbar,
 * cuerpo ovalado con una placa ámbar y dos brazos: el derecho de la pantalla saluda, el izquierdo cuelga relajado.
 * Respira, parpadea, sigue el puntero con la mirada y la cámara (paralaje) y SACA LA MANO para saludar.
 * Formas simples y un solo color por pieza (la paleta de Cátedra: azul marino, ámbar y celeste): no añadir detalles
 * sin que el usuario lo pida. El nombre del archivo y de crearProfe() se conservan de cuando era un profe de carne y hueso.
 * Si el equipo no tiene WebGL, crearProfe() devuelve null y el asistente muestra un ícono en su lugar.
 */
import {
  BufferGeometry, CapsuleGeometry, Color, CylinderGeometry, DirectionalLight, DoubleSide, Float32BufferAttribute, Group,
  HemisphereLight, MathUtils, Mesh, MeshBasicMaterial, MeshStandardMaterial, PerspectiveCamera, Scene, SphereGeometry,
  SRGBColorSpace, TorusGeometry, WebGLRenderer,
} from '../vendor/three/three-profe.js';

const COLOR = {
  cabeza: '#f1f5f9', cuerpo: '#e2e8f0', brazo: '#cbd5e1', mano: '#f1f5f9', metal: '#94a3b8',
  visor: '#1e3a5f', ojo: '#7dd3fc', ambar: '#fbbf24',
};

/** Radio de la cabeza: todo lo demás se mide con él. */
const R = 1;

/** Material mate de un solo color. */
const mate = (color, rugosidad = 0.5, metal = 0) => new MeshStandardMaterial({ color: new Color(color), roughness: rugosidad, metalness: metal });

function malla(geometria, material, pos = [0, 0, 0], escala = [1, 1, 1]) {
  const m = new Mesh(geometria, material);
  m.position.set(...pos);
  m.scale.set(...escala);
  return m;
}

/** Profundidad de la esfera de la cabeza en (x, y): lo pegado a la cara (visor, ojos, mejillas) no flota ni se hunde. */
const zEsfera = (x, y, extra = 0) => Math.sqrt(Math.max(0, R * R - x * x - y * y)) + extra;

/**
 * El visor: una pastilla curva (un rectángulo muy redondeado) pegada a la esfera de la cabeza. Se arma con anillos
 * concéntricos y cada punto se proyecta sobre la esfera, así sigue su curvatura.
 */
function visorSobreEsfera(mitadAncho, mitadAlto, anillos = 10, lados = 64) {
  const pos = [];
  const punto = (s, th) => {
    const c = Math.cos(th), sn = Math.sin(th);
    const x = s * mitadAncho * Math.sign(c) * Math.pow(Math.abs(c), 2 / 3.4);
    const y = s * mitadAlto * Math.sign(sn) * Math.pow(Math.abs(sn), 2 / 3.4);
    return [x, y, zEsfera(x, y, 0.008)];
  };
  pos.push(0, 0, zEsfera(0, 0, 0.008));
  for (let k = 1; k <= anillos; k++) {
    for (let i = 0; i < lados; i++) pos.push(...punto(k / anillos, (i / lados) * Math.PI * 2));
  }
  const idx = [];
  for (let i = 0; i < lados; i++) idx.push(0, 1 + i, 1 + ((i + 1) % lados));
  for (let k = 1; k < anillos; k++) {
    const a = 1 + (k - 1) * lados, b = 1 + k * lados;
    for (let i = 0; i < lados; i++) {
      const j = (i + 1) % lados;
      idx.push(a + i, b + i, b + j, a + i, b + j, a + j);
    }
  }
  const g = new BufferGeometry();
  g.setAttribute('position', new Float32BufferAttribute(pos, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

/** Un brazo completo: hombro → codo → mano. `lado` 1 = derecho de la pantalla, -1 = izquierdo. */
function armarBrazo(lado) {
  const brazo = mate(COLOR.brazo, 0.55);
  const hombro = new Group();
  hombro.position.set(lado * 0.98, -1.28, 0.05);
  hombro.add(malla(new SphereGeometry(0.16, 18, 14), brazo));
  hombro.add(malla(new CapsuleGeometry(0.15, 0.5, 8, 18), brazo, [0, 0.4, 0]));
  const codo = new Group();
  codo.position.set(0, 0.78, 0);
  codo.add(malla(new SphereGeometry(0.15, 16, 12), brazo));
  codo.add(malla(new CapsuleGeometry(0.135, 0.42, 8, 18), brazo, [0, 0.34, 0]));
  const mano = new Group();
  mano.position.set(0, 0.78, 0);
  mano.add(malla(new SphereGeometry(0.22, 22, 16), mate(COLOR.mano, 0.45)));
  codo.add(mano);
  hombro.add(codo);
  return { hombro, codo, mano };
}

// ── El personaje ────────────────────────────────────────────────────────
function armarPersonaje() {
  const raiz = new Group();

  // Cuerpo ovalado con una placa ámbar al frente.
  const cuerpo = new Group();
  cuerpo.position.set(0, -1.62, 0);
  cuerpo.add(malla(new SphereGeometry(1, 40, 30), mate(COLOR.cuerpo, 0.5, 0.04), [0, 0, 0], [0.96, 0.84, 0.7]));
  const placa = new Group();                       // sigue la curva del pecho: un poco inclinada hacia arriba
  placa.position.set(0, 0.56, 0.5);
  placa.rotation.x = -0.5;
  const pastilla = malla(new CapsuleGeometry(0.1, 0.4, 6, 14), mate(COLOR.ambar, 0.4), [0, 0, 0], [1, 1, 0.5]);
  pastilla.rotation.z = Math.PI / 2;
  placa.add(pastilla);
  cuerpo.add(placa);
  raiz.add(cuerpo);

  // Los dos brazos: el derecho de la pantalla sube y saluda; el izquierdo queda relajado al costado.
  const derecho = armarBrazo(1);
  const izquierdo = armarBrazo(-1);
  raiz.add(derecho.hombro, izquierdo.hombro);

  // Cabeza: una esfera blanca con visor, ojos felices, mejillas y antena.
  const cabeza = new Group();
  cabeza.position.set(0, 0.12, 0);
  cabeza.add(malla(new SphereGeometry(R, 56, 40), mate(COLOR.cabeza, 0.4, 0.05)));
  cabeza.add(new Mesh(visorSobreEsfera(0.875, 0.4), new MeshStandardMaterial({ color: new Color(COLOR.visor), roughness: 0.18, metalness: 0.35, side: DoubleSide })));

  // Ojos felices: dos arcos celestes («^ ^») sobre el visor. Parpadean aplastándose.
  const ojos = new Group();
  const luz = new MeshBasicMaterial({ color: COLOR.ojo });
  for (const lado of [-1, 1]) {
    const x = lado * 0.37, y = -0.03;
    const ojo = new Group();
    ojo.position.set(x, y, zEsfera(x, y, 0.02));
    ojo.rotation.y = Math.atan2(x, zEsfera(x, y));          // sigue la curvatura de la cabeza
    const arco = malla(new TorusGeometry(0.2, 0.046, 12, 36, 2.0), luz);
    arco.rotation.z = Math.PI / 2 - 1.0;                     // centrado: un arco que sube y baja
    arco.position.y = -0.1;
    ojo.add(arco);
    ojos.add(ojo);
  }
  cabeza.add(ojos);

  // Mejillas ámbar (dos puntos pequeños en el borde bajo del visor).
  const mejillas = new Group();
  for (const lado of [-1, 1]) {
    const x = lado * 0.66, y = -0.24;
    mejillas.add(malla(new SphereGeometry(0.045, 12, 10), new MeshBasicMaterial({ color: COLOR.ambar }), [x, y, zEsfera(x, y, 0.02)]));
  }
  cabeza.add(mejillas);

  // Antena con una bolita ámbar.
  const antena = new Group();
  antena.position.set(0, R - 0.02, 0);
  antena.add(malla(new CylinderGeometry(0.035, 0.035, 0.3, 10), mate(COLOR.metal, 0.4, 0.2), [0, 0.15, 0]));
  antena.add(malla(new SphereGeometry(0.095, 16, 12), mate(COLOR.ambar, 0.35), [0, 0.34, 0]));
  cabeza.add(antena);

  raiz.add(cabeza);
  return { raiz, cabeza, cuerpo, hombro: derecho.hombro, codo: derecho.codo, mano: derecho.mano, hombroIzq: izquierdo.hombro, codoIzq: izquierdo.codo, ojos, mejillas, antena };
}

/**
 * Crea el personaje dentro de `lienzo` (un <canvas>). Devuelve { saludar, mirar, parar, reanudar, destruir } o null
 * si no hay WebGL. `animado: false` dibuja un solo cuadro (para quien pide menos movimiento).
 */
export function crearProfe(lienzo, { animado = true } = {}) {
  let renderer;
  try {
    renderer = new WebGLRenderer({ canvas: lienzo, alpha: true, antialias: true, powerPreference: 'low-power' });
  } catch (_) {
    return null;
  }
  renderer.outputColorSpace = SRGBColorSpace;
  renderer.setClearColor(0x000000, 0);
  const ajustar = () => {
    const l = Math.max(1, Math.round(lienzo.clientWidth || 100));
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(l, l, false);
  };
  ajustar();

  const escena = new Scene();
  // Luz sencilla: cielo suave, una luz principal y un contraluz para el volumen.
  escena.add(new HemisphereLight(0xffffff, 0xbfd0ea, 1.7));
  const principal = new DirectionalLight(0xffffff, 1.7);
  principal.position.set(2.5, 3.5, 5.5);
  escena.add(principal);
  const contraluz = new DirectionalLight(0xdbeaff, 0.8);
  contraluz.position.set(-2, 2.5, -4);
  escena.add(contraluz);

  const camara = new PerspectiveCamera(30, 1, 0.1, 60);
  const CAM = { x: 0, y: -0.3, z: 8.4, mira: -0.55 };
  camara.position.set(CAM.x, CAM.y, CAM.z);
  camara.lookAt(0, CAM.mira, 0);

  const p = armarPersonaje();
  escena.add(p.raiz);

  // Estado de la animación.
  let t = 0, saludo = 0, alza = 0, parpadeo = 0, proximoParpadeo = 2.4;
  let objetivoX = 0, objetivoY = 0, miraX = 0, miraY = 0;
  let corriendo = false, raf = 0, previo = 0, destruido = false;

  function cuadro(dt) {
    t += dt;
    const k = Math.min(1, dt * 6);
    if (saludo > 0) saludo -= dt;
    alza += ((saludo > 0 ? 1 : 0) - alza) * Math.min(1, dt * 4.5);
    const e = alza * alza * (3 - 2 * alza);                                              // suavizado

    // Respiración y balanceo suave.
    const resp = Math.sin(t * 1.7);
    p.cuerpo.scale.y = 1 + resp * 0.012;
    p.raiz.position.y = resp * 0.02;
    miraX += (objetivoX - miraX) * k;
    miraY += (objetivoY - miraY) * k;
    p.cabeza.rotation.y = miraX * 0.55;
    p.cabeza.rotation.x = -miraY * 0.3 + Math.sin(t * 6) * 0.04 * e;
    p.cabeza.rotation.z = Math.sin(t * 0.8) * 0.02 - miraX * 0.05 + Math.sin(t * 5) * 0.025 * e;
    p.cuerpo.rotation.y = miraX * 0.14;
    // La antena se bambolea un poco (más al saludar).
    p.antena.rotation.z = Math.sin(t * 2.3) * 0.05 + Math.sin(t * 9) * 0.1 * e;
    p.antena.rotation.x = Math.sin(t * 1.9) * 0.04;
    // Paralaje: la cámara se mueve un poco con el puntero, así se nota el volumen.
    camara.position.x = CAM.x + miraX * 0.55;
    camara.position.y = CAM.y - miraY * 0.28;
    camara.lookAt(0, CAM.mira, 0);

    // Brazo: del costado (colgando) a levantado, con la mano moviéndose de lado a lado.
    p.hombro.rotation.z = MathUtils.lerp(-2.95, -0.8, e);
    p.hombro.rotation.x = MathUtils.lerp(0, 0.1, e);
    const ola = Math.sin(t * 10) * e;
    p.codo.rotation.z = MathUtils.lerp(0.12, 0.75, e) + ola * 0.2;
    p.mano.rotation.z = ola * 0.45;
    // El otro brazo, relajado: cuelga y se mece apenas con la respiración (algo más abierto al saludar).
    p.hombroIzq.rotation.z = 2.95 + resp * 0.018 - 0.03 * e;
    p.codoIzq.rotation.z = -0.12 - resp * 0.015;

    // Cara: parpadeo y mejillas que se agrandan un poco al saludar.
    proximoParpadeo -= dt;
    if (proximoParpadeo <= 0) { parpadeo = 0.15; proximoParpadeo = 2.6 + Math.random() * 3.2; }
    if (parpadeo > 0) parpadeo -= dt;
    p.ojos.scale.y = parpadeo > 0 ? 0.1 : 1;
    p.mejillas.children.forEach(m => m.scale.setScalar(1 + 0.6 * e));
    renderer.render(escena, camara);
  }

  function bucle(ahora) {
    if (!corriendo) return;
    raf = requestAnimationFrame(bucle);
    const dt = Math.min(0.1, (ahora - previo) / 1000 || 0);
    if (dt < 1 / 34) return;          // unos 30 cuadros por segundo bastan para un ícono
    previo = ahora;
    cuadro(dt);
  }

  function reanudar() {
    if (destruido || corriendo) return;
    if (!animado) { cuadro(0.016); return; }
    corriendo = true;
    previo = performance.now();
    raf = requestAnimationFrame(bucle);
  }

  function parar() {
    corriendo = false;
    cancelAnimationFrame(raf);
  }

  const alRedimensionar = () => { ajustar(); if (!corriendo) cuadro(0); };
  window.addEventListener('resize', alRedimensionar);
  cuadro(0.016);

  return {
    /** El robot saca la mano y saluda durante unos segundos. */
    saludar(segundos = 2.6) {
      saludo = segundos;
      if (!animado) { alza = 1; cuadro(0.016); }
    },
    /** Hacia dónde mira: x e y entre -1 y 1 (0 = al frente). */
    mirar(x, y) { objetivoX = MathUtils.clamp(x, -1, 1); objetivoY = MathUtils.clamp(y, -1, 1); if (!animado) cuadro(0.016); },
    parar,
    reanudar,
    destruir() {
      destruido = true;
      parar();
      window.removeEventListener('resize', alRedimensionar);
      renderer.dispose();
    },
  };
}
