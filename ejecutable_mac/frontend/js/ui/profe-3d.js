/**
 * profe-3d.js — «el profe»: el personaje 3D del asistente flotante (ui/asistente.js).
 *
 * Es un busto MINIMALISTA y sobrio (un docente universitario, no un muñeco) armado entero con código (three.js):
 * ningún modelo ni imagen descargados. Proporciones de adulto —cabeza ovalada, hombros anchos, cuello—, formas
 * simples y un solo color por pieza: pelo corto, ojos redondos con brillo, lentes redondos de pasta gruesa,
 * mejillas rosadas, sonrisa amable, saco azul marino liso con la camisa en V. Respira, parpadea, sigue el puntero con la mirada
 * y la cámara (paralaje) y SACA LA MANO para saludar.
 * Si el equipo no tiene WebGL, crearProfe() devuelve null y el asistente muestra un ícono en su lugar.
 */
import {
  BufferGeometry, CapsuleGeometry, CircleGeometry, Color, CylinderGeometry, DirectionalLight, DoubleSide, Float32BufferAttribute, Group,
  HemisphereLight, MathUtils, Mesh, MeshBasicMaterial, MeshStandardMaterial, PerspectiveCamera, Scene, Shape, ShapeGeometry, SphereGeometry,
  SRGBColorSpace, TorusGeometry, WebGLRenderer,
} from '../vendor/three/three-profe.js';

const COLOR = { piel: '#e8b08a', pielSombra: '#d39874', pelo: '#2d231f', saco: '#243f6b', camisa: '#f1f4f8', ojo: '#241d1b', boca: '#8f4f43', montura: '#16171b', mejilla: '#f08f8f' };

const suave = (a, b, x) => { const t = MathUtils.clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

// ── La forma de la cabeza ───────────────────────────────────────────────
// Un superelipsoide |x/a|^n + |y/b|^n + |z/c|^n = 1 con n un poco mayor que 2: una esfera algo más «llena», de
// dibujo animado. Lo pegado a la cara (ojos, sonrisa) calcula su profundidad con zCara() para no flotar.
const CAB = { a: 0.89, b: 1.04, c: 0.92, n: 2.5 };
/** La mandíbula se afina hacia abajo: una cara de adulto, no una pelota. */
const afinado = y => 1 - 0.2 * Math.pow(Math.max(0, -y / CAB.b - 0.1), 1.25);

function zCara(x, y) {
  const v = 1 - Math.pow(Math.abs(x / afinado(y) / CAB.a), CAB.n) - Math.pow(Math.abs(y / CAB.b), CAB.n);
  return v > 0 ? CAB.c * Math.pow(v, 1 / CAB.n) : 0;
}

function superelipsoide(dx, dy, dz, a, b, c, n = CAB.n) {
  const k = Math.pow(Math.pow(Math.abs(dx), n) + Math.pow(Math.abs(dy), n) + Math.pow(Math.abs(dz), n), 1 / n) || 1;
  return [dx / k * a, dy / k * b, dz / k * c];
}

/** Superficie paramétrica (longitud φ con 0 = al frente, y θ desde la coronilla). `thetaMax(φ)` recorta por abajo. */
function superficie({ cols = 64, filas = 40, thetaMax = () => Math.PI, punto }) {
  const pos = [];
  for (let i = 0; i < cols; i++) {
    const phi = (i / cols) * Math.PI * 2;
    const tm = thetaMax(phi);
    for (let j = 0; j <= filas; j++) {
      const t = j / filas, theta = t * tm;
      const s = Math.sin(theta);
      pos.push(...punto(s * Math.sin(phi), Math.cos(theta), s * Math.cos(phi), t));
    }
  }
  const idx = [];
  const id = (i, j) => (i % cols) * (filas + 1) + j;
  for (let i = 0; i < cols; i++) {
    for (let j = 0; j < filas; j++) {
      const a = id(i, j), b = id(i + 1, j), c = id(i + 1, j + 1), d = id(i, j + 1);
      idx.push(a, d, b, b, d, c);
    }
  }
  const g = new BufferGeometry();
  g.setAttribute('position', new Float32BufferAttribute(pos, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

/** Material mate de un solo color (el aspecto «de arcilla» del personaje). */
const mate = (color, rugosidad = 0.62) => new MeshStandardMaterial({ color: new Color(color), roughness: rugosidad, metalness: 0 });

function malla(geometria, material, pos = [0, 0, 0], escala = [1, 1, 1]) {
  const m = new Mesh(geometria, material);
  m.position.set(...pos);
  m.scale.set(...escala);
  return m;
}

/** Un brazo completo: hombro → codo → mano. `lado` 1 = derecho de la pantalla, -1 = izquierdo. */
function armarBrazo(lado, piel, saco) {
  const hombro = new Group();
  hombro.position.set(lado * 1.36, -1.42, 0.1);
  hombro.add(malla(new SphereGeometry(0.31, 22, 16), saco));
  hombro.add(malla(new CapsuleGeometry(0.255, 0.75, 8, 20), saco, [0, 0.5, 0]));
  const codo = new Group();
  codo.position.set(0, 1.0, 0);
  codo.add(malla(new SphereGeometry(0.235, 18, 14), saco));
  codo.add(malla(new CapsuleGeometry(0.21, 0.6, 8, 20), saco, [0, 0.45, 0]));
  const mano = new Group();
  mano.position.set(0, 0.98, 0);
  mano.scale.setScalar(1.15);
  mano.add(malla(new SphereGeometry(1, 22, 16), piel, [0, 0.14, 0], [0.17, 0.2, 0.07]));                 // palma
  for (const [x, alto, giro] of [[-0.105, 0.2, 0.22], [-0.035, 0.24, 0.07], [0.035, 0.24, -0.07], [0.105, 0.2, -0.22]]) {
    const dedo = malla(new CapsuleGeometry(0.034, alto, 6, 10), piel, [x + Math.sin(-giro) * alto * 0.45, 0.28 + alto * 0.5, 0]);
    dedo.rotation.z = giro;
    mano.add(dedo);
  }
  const pulgar = malla(new CapsuleGeometry(0.038, 0.15, 6, 10), piel, [-0.2 * lado, 0.12, 0.01]);
  pulgar.rotation.z = 0.95 * lado;
  mano.add(pulgar);
  codo.add(mano);
  hombro.add(codo);
  return { hombro, codo, mano };
}

// ── El personaje ────────────────────────────────────────────────────────
function armarPersonaje() {
  const raiz = new Group();
  const piel = mate(COLOR.piel, 0.55);
  const saco = mate(COLOR.saco, 0.72);

  // Hombros anchos (una cápsula horizontal), torso y cuello de adulto.
  const cuerpo = new Group();
  const hombros = malla(new CapsuleGeometry(0.46, 2.0, 10, 28), saco, [0, -1.62, 0], [1, 1, 0.78]);
  hombros.rotation.z = Math.PI / 2;
  cuerpo.add(hombros);
  cuerpo.add(malla(new CapsuleGeometry(0.95, 1.3, 12, 32), saco, [0, -3.0, 0], [1.28, 1, 0.72]));
  cuerpo.add(malla(new CylinderGeometry(0.34, 0.4, 0.75, 28), mate(COLOR.pielSombra, 0.6), [0, -1.04, 0.03]));     // cuello
  // Camisa en V: un solo triángulo blanco sobre el saco.
  const triangulo = new Shape();
  triangulo.moveTo(-0.34, 0); triangulo.lineTo(0.34, 0); triangulo.lineTo(0, -0.95); triangulo.closePath();
  const camisa = new Mesh(new ShapeGeometry(triangulo), new MeshStandardMaterial({ color: new Color(COLOR.camisa), roughness: 0.8, side: DoubleSide }));
  camisa.position.set(0, -1.28, 0.74);
  camisa.rotation.x = -0.12;
  cuerpo.add(camisa);
  cuerpo.position.y = 0.2;
  raiz.add(cuerpo);

  // Los dos brazos: el derecho de la pantalla sube y saluda; el izquierdo queda relajado al costado.
  const derecho = armarBrazo(1, piel, saco);
  const izquierdo = armarBrazo(-1, piel, saco);
  raiz.add(derecho.hombro, izquierdo.hombro);

  // Cabeza: ovalada, con casquete de pelo corto.
  const cabeza = new Group();
  cabeza.position.set(0, 0.3, 0);
  cabeza.add(new Mesh(superficie({
    cols: 64, filas: 44,
    punto: (dx, dy, dz) => { const [x, y, z] = superelipsoide(dx, dy, dz, CAB.a, CAB.b, CAB.c); return [x * afinado(y), y, z]; },
  }), piel));

  // Pelo: una cáscara un poco más grande con su línea de nacimiento (baja en las sienes y la nuca).
  cabeza.add(new Mesh(superficie({
    cols: 72, filas: 28,
    thetaMax: phi => {
      const lejos = Math.abs(((phi + Math.PI) % (Math.PI * 2)) - Math.PI);                 // distancia angular al frente
      return Math.PI * (0.29 + 0.19 * suave(0.16 * Math.PI, 0.5 * Math.PI, lejos) + 0.05 * suave(0.6 * Math.PI, Math.PI, lejos));
    },
    punto: (dx, dy, dz, t) => {
      const [x, y, z] = superelipsoide(dx, dy, dz, CAB.a * 1.06, CAB.b * 1.045, CAB.c * 1.07, 2.4);
      const fuera = 1 - 0.05 * suave(0.85, 1, t);                                          // el borde se pega a la piel
      return [x * fuera, y * fuera + 0.03, z * fuera - 0.04];
    },
  }), mate(COLOR.pelo, 0.5)));

  // Orejas pequeñas.
  for (const lado of [-1, 1]) cabeza.add(malla(new SphereGeometry(1, 16, 12), piel, [lado * (CAB.a * 0.98), -0.04, 0.03], [0.07, 0.19, 0.14]));

  // Nariz pequeña y redonda.
  cabeza.add(malla(new SphereGeometry(1, 18, 14), mate(COLOR.pielSombra, 0.6), [0, -0.1, zCara(0, -0.1) + 0.012], [0.075, 0.075, 0.07]));

  // Ojos redondos y brillantes, con una cejita encima.
  const ojos = new Group();
  const blanco = new MeshBasicMaterial({ color: '#ffffff' });
  for (const lado of [-1, 1]) {
    const x = lado * 0.3, y = 0.08;
    const ojo = new Group();
    ojo.position.set(x, y, zCara(x, y) - 0.004);
    ojo.add(malla(new SphereGeometry(1, 22, 18), mate(COLOR.ojo, 0.25), [0, 0, 0], [0.072, 0.088, 0.04]));
    ojo.add(malla(new SphereGeometry(0.02, 10, 8), blanco, [0.024, 0.03, 0.036]));                      // brillo
    ojos.add(ojo);
    const ceja = malla(new CapsuleGeometry(0.018, 0.17, 4, 8), mate(COLOR.pelo, 0.6), [x, 0.4, zCara(x, 0.4) + 0.014]);
    ceja.rotation.z = Math.PI / 2 - lado * 0.1;
    cabeza.add(ceja);
  }
  cabeza.add(ojos);

  // Lentes redondos de pasta gruesa.
  const montura = mate(COLOR.montura, 0.35);
  for (const lado of [-1, 1]) {
    const x = lado * 0.3, y = 0.08;
    const aro = malla(new TorusGeometry(0.2, 0.036, 12, 40), montura, [x, y, zCara(x, y) + 0.03], [1.08, 1, 1]);
    aro.rotation.y = lado * 0.2;
    cabeza.add(aro);
  }
  const puente = malla(new CylinderGeometry(0.02, 0.02, 0.13, 8), montura, [0, 0.11, zCara(0, 0.11) + 0.035]);
  puente.rotation.z = Math.PI / 2;
  cabeza.add(puente);

  // Mejillas rosadas.
  for (const lado of [-1, 1]) {
    const mx = lado * 0.52, my = -0.2;
    const mej = new Mesh(new CircleGeometry(0.1, 24), new MeshBasicMaterial({ color: COLOR.mejilla, transparent: true, opacity: 0.5, depthWrite: false }));
    mej.position.set(mx, my, zCara(mx, my) + 0.01);
    mej.rotation.y = lado * 0.6;
    cabeza.add(mej);
  }

  // Sonrisa amable: un arco con las puntas hacia arriba.
  const boca = new Group();
  const arco = 1.5;
  boca.position.set(0, -0.06, zCara(0.2, -0.32) + 0.03);
  const sonrisa = malla(new TorusGeometry(0.32, 0.02, 10, 32, arco), mate(COLOR.boca, 0.6));
  sonrisa.rotation.z = -Math.PI / 2 - arco / 2;
  boca.add(sonrisa);
  cabeza.add(boca);

  raiz.add(cabeza);
  return { raiz, cabeza, cuerpo, hombro: derecho.hombro, codo: derecho.codo, mano: derecho.mano, hombroIzq: izquierdo.hombro, codoIzq: izquierdo.codo, ojos, boca };
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
  const CAM = { x: 0, y: -0.2, z: 8.6, mira: -0.6 };
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
    p.cuerpo.scale.y = 1 + resp * 0.01;
    p.raiz.position.y = resp * 0.018;
    miraX += (objetivoX - miraX) * k;
    miraY += (objetivoY - miraY) * k;
    p.cabeza.rotation.y = miraX * 0.55;
    p.cabeza.rotation.x = -miraY * 0.3 + Math.sin(t * 6) * 0.05 * e + 0.02;
    p.cabeza.rotation.z = Math.sin(t * 0.8) * 0.02 - miraX * 0.05 + Math.sin(t * 5) * 0.025 * e;
    p.cuerpo.rotation.y = miraX * 0.14;
    // Paralaje: la cámara se mueve un poco con el puntero, así se nota el volumen.
    camara.position.x = CAM.x + miraX * 0.55;
    camara.position.y = CAM.y - miraY * 0.28;
    camara.lookAt(0, CAM.mira, 0);

    // Brazo: del costado (colgando) a levantado, con la manopla moviéndose de lado a lado.
    p.hombro.rotation.z = MathUtils.lerp(-2.95, -0.6, e);
    p.hombro.rotation.x = MathUtils.lerp(0, 0.1, e);
    const ola = Math.sin(t * 10) * e;
    p.codo.rotation.z = MathUtils.lerp(0.12, 1.0, e) + ola * 0.2;
    p.mano.rotation.z = ola * 0.45;
    // El otro brazo, relajado: cuelga y se mece apenas con la respiración (algo más abierto al saludar).
    p.hombroIzq.rotation.z = 2.95 + resp * 0.018 - 0.03 * e;
    p.codoIzq.rotation.z = -0.12 - resp * 0.015;

    // Cara: parpadeo y sonrisa que se ensancha al saludar.
    proximoParpadeo -= dt;
    if (proximoParpadeo <= 0) { parpadeo = 0.15; proximoParpadeo = 2.6 + Math.random() * 3.2; }
    if (parpadeo > 0) parpadeo -= dt;
    p.ojos.scale.y = parpadeo > 0 ? 0.1 : 1;
    p.boca.scale.set(1 + 0.12 * e, 1 + 0.3 * e, 1);
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
    /** El profe saca la mano y saluda durante unos segundos. */
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
