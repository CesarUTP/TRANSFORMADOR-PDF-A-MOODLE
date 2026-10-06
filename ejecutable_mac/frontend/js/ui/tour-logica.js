/**
 * tour-logica.js — los recorridos guiados («Recorrido» de cada pantalla) sin tocar el DOM (se prueba en Node).
 * Cada recorrido es una lista de pasos { el, titulo, texto, lado }: `el` es el selector del elemento que se
 * resalta (null: un paso de presentación, en el centro). Los pasos cuyo elemento no está en pantalla se
 * saltan (por ejemplo, el de la «Pág. N» cuando el examen no es un PDF). Los textos son HTML escrito aquí, nunca datos del docente.
 * El recorrido lo dibuja driver.js (js/vendor/driver); ver tour.js.
 */

export const CLAVE_VISTOS = 'conversor.tours';

export const TOURS = {
  cargar: {
    pasos: [
      { el: '.stepper', titulo: 'Así se convierte un examen', texto: 'Tres pasos: <b>cargas</b> tu examen, <b>revisas</b> lo que leyó la app y <b>descargas</b> el XML para Moodle (o el PDF para imprimirlo). Te enseño esta pantalla en un minuto.', lado: 'bottom' },
      { el: '#drop-zone', titulo: 'Elige tu examen', texto: 'Arrastra aquí el <b>PDF</b>, el <b>Word</b> o el <b>TXT</b> del examen, o haz clic para buscarlo. También sirve un <b>XML de Moodle</b> que ya tengas: se abre para corregirlo, sin IA.', lado: 'bottom' },
      { el: '#category-input', titulo: 'Categoría de Moodle', texto: 'El nombre de la carpeta donde quedarán las preguntas en el <b>Banco de preguntas</b> de Moodle. Por ejemplo: <i>Parcial-Historia-2026</i>.', lado: 'bottom' },
      { el: '#points-input', titulo: 'Puntaje total', texto: 'Cuánto vale todo el examen. Después, en la revisión, lo repartes entre las preguntas (la app lo hace por ti y tú lo ajustas).', lado: 'bottom' },
      { el: '#materia-select', titulo: 'Materia (opcional)', texto: 'Elige a qué materia pertenece, o crea una nueva desde aquí. Así lo encuentras después en <b>Mis materias</b>, y con materia el examen <b>no se borra solo</b> cuando el Historial se llena.', lado: 'top' },
      { el: '#actividad-input', titulo: 'Actividad (opcional)', texto: 'Un nombre para distinguirlo dentro de la materia: <i>Parcial 1</i>, <i>Quiz 2</i>…', lado: 'top' },
      { el: '#btn-convert', titulo: 'Convertir', texto: 'Se activa cuando eliges un archivo. La app lee el examen con ayuda de IA y te lleva a la revisión. Tarda unos segundos.', lado: 'top' },
      { el: '#btn-materias', titulo: 'Mis materias', texto: 'Tu biblioteca: todos los exámenes que conviertas, ordenados por materia, para reabrirlos, descargarlos o exportarlos en PDF.', lado: 'bottom' },
      { el: '#btn-perfil', titulo: 'Mi perfil', texto: 'Guarda tu nombre y los encabezados de tu institución (con logos) una sola vez: saldrán solos en cada PDF.', lado: 'bottom' },
      { el: '#btn-help', titulo: 'Guía', texto: 'Aquí está la explicación completa. Además, el <b>profe</b> de la esquina de abajo a la izquierda te explica cualquier pantalla: haz clic en él cuando quieras repetir un recorrido.', lado: 'bottom' },
    ],
  },
  revision: {
    pasos: [
      { el: '.editor-head', titulo: 'Revisa lo que leyó la app', texto: 'Compara cada pregunta con tu documento: la lectura puede tener errores o respuestas faltantes. La app <b>no inventa nada</b>; lo dudoso queda marcado para que lo veas.', lado: 'bottom' },
      { el: '.editor-card .card-toggle', titulo: 'Cada pregunta es una fila', texto: 'Muestra su número, tipo, enunciado y la respuesta que lleva. Haz clic para abrirla y editarla. Las que piden revisión se abren solas.', lado: 'bottom' },
      { el: '.editor-card .proc-pagina', titulo: 'Pág. N: compara con el original', texto: 'Si tu examen es un PDF, este botón abre el <b>recorte de la página</b> donde está la pregunta, junto a la respuesta que propone la app y qué tan segura está.', lado: 'bottom' },
      { el: '[data-accion="toggleFilterMenu"]', titulo: 'Mostrar', texto: 'Deja ver solo un tipo de pregunta, las que conviene <b>revisar primero</b> o los <b>posibles problemas</b>. Las que ocultes igual van al XML.', lado: 'bottom' },
      { el: '[data-accion="togglePointsToolMenu"]', titulo: 'Puntos', texto: 'Cuánto suman frente al total. Puedes repartirlos igual para todas o según el tipo de pregunta; siempre suman exacto.', lado: 'bottom' },
      { el: '#review-rail', titulo: 'Mapa del examen', texto: 'Un cuadro por pregunta: <b>rojo</b> = incompleta, <b>ámbar</b> = para revisar. Haz clic para ir a esa pregunta; con las teclas <kbd>J</kbd> y <kbd>K</kbd> avanzas y retrocedes.', lado: 'top' },
      { el: '#btn-generate-xml', titulo: 'Generar XML', texto: 'Cuando todo esté bien. No avanza mientras haya preguntas incompletas o propuestas de la IA sin aceptar ni descartar.', lado: 'top' },
      { el: '#btn-discard-review', titulo: 'Descartar', texto: 'Borra la revisión y vuelve al paso 1 (pide confirmación). Tu revisión se guarda sola en este equipo, por si cierras la ventana.', lado: 'top' },
    ],
  },
  final: {
    pasos: [
      { el: '#success-title', titulo: '¡Tu XML está listo!', texto: 'El examen quedó guardado en tu equipo (en <b>Mis materias</b>). Esto es lo que puedes hacer ahora.', lado: 'bottom' },
      { el: '#btn-download', titulo: 'Descargar Moodle XML', texto: 'Guarda el archivo. Para usarlo en Moodle: <b>Banco de preguntas → Importar → Formato XML de Moodle</b>.', lado: 'bottom' },
      { el: '#btn-exportar-pdf', titulo: 'Exportar examen en PDF', texto: 'Para tenerlo en papel con su clave, o como folleto de preguntas con hoja de respuestas. Se abre un diálogo con <b>vista previa</b>.', lado: 'bottom' },
      { el: '#exito-materia', titulo: 'Guardado en tu materia', texto: 'Aquí ves en qué materia quedó y puedes cambiarla.', lado: 'bottom' },
      { el: '#btn-back-to-review', titulo: 'Volver a la revisión', texto: '¿Viste un error? Regresa, corrige y genera el XML otra vez.', lado: 'bottom' },
      { el: '#points-chart-card', titulo: 'Resumen', texto: 'Cuántas preguntas y cuántos puntos hay de cada tipo.', lado: 'top' },
      { el: '#btn-reset-success', titulo: 'Convertir otro examen', texto: 'Vuelve al paso 1 para empezar con otro.', lado: 'top' },
    ],
  },
  biblioteca: {
    pasos: [
      { el: '#vm-cuerpo .vm-cab', titulo: 'Tu biblioteca', texto: 'Cada <b>materia</b> es un espacio con todos sus exámenes. Elige una para reabrirlos, descargarlos o exportarlos en PDF.', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-cab-acciones [data-accion="nuevaMateria"]', titulo: 'Nueva materia', texto: 'Créala con un nombre y un color. Opcionalmente le pones su perfil de encabezado, su docente y su grupo: el PDF los usará solos.', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-cab-acciones [data-accion="abrirTodos"]', titulo: 'Todos los exámenes', texto: 'La lista completa, del más reciente al más antiguo, con buscador.', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-ordenar', titulo: 'Ordenar con ayuda', texto: 'Si tienes exámenes sin materia, la app propone a cuál pertenece cada uno según su categoría y su nombre. <b>Tú decides</b> qué se mueve.', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-tarjetas .vm-tarjeta:not(.vm-tarjeta-sin):not(.vm-tarjeta-nueva)', titulo: 'Una materia', texto: 'Haz clic para entrar. El lápiz la edita, la archiva o la borra (borrar una materia <b>no</b> borra sus exámenes).', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-tarjeta-sin', titulo: 'Sin materia', texto: 'Los exámenes sin materia. Cuando el Historial se llena, <b>estos se borran primero</b>; mueve a una materia lo que quieras conservar.', lado: 'top' },
      { el: '#vm-cuerpo .vm-aviso', titulo: 'Aviso de espacio', texto: 'Aparece cuando el Historial se está llenando (300 exámenes o 400 MB).', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-uso', titulo: 'Cuánto espacio usas', texto: 'Cuántos exámenes tienes guardados y cuánto ocupan.', lado: 'top' },
    ],
  },
  bibliotecaLista: {
    pasos: [
      { el: '#vm-cuerpo .vm-cab', titulo: 'Los exámenes de esta lista', texto: 'Aquí están los exámenes ya convertidos. Con <b>Mis materias</b> (arriba a la izquierda) vuelves a tus materias.', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-cab-acciones [data-accion="nuevoExamenEnMateria"]', titulo: 'Nuevo examen en esta materia', texto: 'Vuelve al paso 1 con esta materia ya elegida.', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-cab-acciones [data-accion="editarMateria"]', titulo: 'Editar materia', texto: 'Cambia su nombre y color, ponle perfil de encabezado, docente y grupo por defecto, archívala o bórrala.', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-cab-acciones [data-accion="abrirAsistente"]', titulo: 'Ordenar con ayuda', texto: 'Propone a qué materia pertenece cada examen según su categoría y su nombre. <b>Tú decides</b> qué se mueve.', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-buscar', titulo: 'Buscar', texto: 'Por nombre del archivo, categoría, actividad o fecha. No distingue mayúsculas ni tildes.', lado: 'bottom' },
      { el: '#vm-cuerpo #vm-seleccion', titulo: 'Elegir varios', texto: 'Marca <b>Elegir todos</b> o algunos exámenes para <b>moverlos</b> a una materia o <b>borrarlos</b> de una vez. Útil para limpiar pruebas.', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-fila .vm-fila-acciones', titulo: 'Qué hacer con un examen', texto: '<b>Reabrir</b> vuelve a su revisión; <b>PDF</b> lo exporta para imprimir; <b>XML</b> lo descarga otra vez.', lado: 'left' },
      { el: '#vm-cuerpo .vm-organizar-boton', titulo: 'Organizar', texto: 'Cambia su materia o su actividad, o bórralo.', lado: 'left' },
    ],
  },
  perfil: {
    pasos: [
      { el: '#vp-form', titulo: 'Mis datos', texto: 'Tu nombre y cómo te llamas en el encabezado (<i>Facilitador</i>, <i>Docente</i> o <i>Profesor</i>). Los escribes una vez y salen en cada PDF.', lado: 'bottom' },
      { el: '[data-accion="nuevoPerfilEnc"]', titulo: 'Perfiles de encabezado', texto: 'Un perfil guarda la <b>institución, los logos, las indicaciones generales y el formato de impresión</b>, con vista previa. Crea uno por cada institución donde das clase.', lado: 'bottom' },
      { el: '#vp-perfiles .vp-perfil', titulo: 'Tu perfil', texto: '<b>Editar</b> lo cambia, <b>Duplicar</b> hace una copia para variarla, y la papelera lo borra.', lado: 'bottom' },
      { el: '#vp-perfiles .vp-perfil [data-accion="predeterminadoPerfilEnc"]', titulo: 'Usar por defecto', texto: 'El perfil predeterminado es con el que empieza el diálogo del PDF.', lado: 'top' },
      { el: null, titulo: 'Qué se aplica al exportar', texto: 'Al exportar un PDF, el diálogo empieza con lo de la <b>materia</b> (su perfil, docente y grupo); si no, con tu <b>perfil predeterminado</b> y tus datos; si no, con lo último que escribiste. Siempre puedes cambiarlo en ese examen.' },
    ],
  },
  pdf: {
    pasos: [
      { el: '#pdf-perfil', titulo: 'Perfil de encabezado', texto: 'Carga de una vez el encabezado y el formato que guardaste (institución, logos, márgenes, letra…). Los administras en <b>Mi perfil</b>.', lado: 'bottom' },
      { el: '#pdf-materia-sel', titulo: 'Materia', texto: 'Al elegir una materia se rellenan su perfil, su docente y su grupo.', lado: 'bottom' },
      { el: '#pdf-datos-examen', titulo: 'Datos de este examen', texto: 'Actividad, grupo y fecha: salen en el encabezado. Todo es opcional.', lado: 'bottom' },
      { el: '#pdf-grupo-incluir', titulo: 'Qué incluir', texto: 'El examen con su clave, solo uno de los dos, o <b>folleto + hoja de respuestas + clave</b>: un folleto de preguntas para repartir, una hoja para que el estudiante conteste y la clave ya llena.', lado: 'top' },
      { el: '#pdf-sec-encabezado', titulo: 'Encabezado de la institución', texto: 'Institución, facultad, logos (uno o dos) e indicaciones generales.', lado: 'top' },
      { el: '#pdf-sec-formato', titulo: 'Formato', texto: 'Papel, márgenes, tipo y tamaño de letra, renglones de los ensayos y si se <b>mezclan las opciones</b> (para que la clave no delate las respuestas).', lado: 'top' },
      { el: '#btn-pdf-vista', titulo: 'Vista previa', texto: 'Muestra la página tal como saldrá y se actualiza al cambiar cualquier dato.', lado: 'top' },
      { el: '#btn-pdf-exportar', titulo: 'Exportar PDF', texto: 'Genera el PDF y te deja elegir dónde guardarlo. El XML no cambia.', lado: 'top' },
    ],
  },
};

/** El recorrido que toca según dónde esté el docente: en una lista de «Mis materias» (hayLista) es otro que en su raíz. */
export function nombreDeTour(nombre, { hayLista = false } = {}) {
  if (nombre === 'biblioteca' && hayLista) return 'bibliotecaLista';
  return Object.hasOwn(TOURS, nombre) ? nombre : null;
}

/** Los pasos que se pueden mostrar ahora: los de presentación (sin elemento) y los cuyo elemento está en pantalla. */
export function pasosVisibles(pasos, existe) {
  return pasos.filter(p => p.el === null || p.el === undefined || existe(p.el));
}

export function leerVistos(raw) {
  try {
    const v = JSON.parse(raw || '{}');
    return v && typeof v === 'object' && !Array.isArray(v) ? { vistos: Array.isArray(v.vistos) ? v.vistos.filter(n => typeof n === 'string') : [], descartado: v.descartado === true } : { vistos: [], descartado: false };
  } catch (_) {
    return { vistos: [], descartado: false };
  }
}

export function marcarVisto(estado, nombre) {
  return { ...estado, vistos: estado.vistos.includes(nombre) ? estado.vistos : [...estado.vistos, nombre] };
}

/** ¿Se le ofrece el recorrido de bienvenida? Solo a quien aún no lo hizo ni lo descartó. */
export function debeOfrecer(estado) {
  return !estado.descartado && !estado.vistos.includes('cargar');
}

// ── El asistente flotante (ui/asistente.js) ──────────────────────────────
/** Los ids de las ventanas encima de las cuales el asistente sigue disponible (con su recorrido). */
const CONTEXTO_POR_VENTANA = { 'modal-pdf': 'pdf', 'vista-perfil': 'perfil', 'vista-materias': 'biblioteca' };
const CONTEXTO_POR_PANEL = { upload: 'cargar', editor: 'revision', success: 'final' };

/**
 * Qué recorrido toca ahora: el de la ventana de más arriba si es una con recorrido; si hay otra ventana
 * (confirmación, Guía, clave…) o una pantalla de espera, null y el asistente se esconde.
 */
export function contextoDeAyuda({ ventana = null, panel = 'upload' } = {}) {
  if (ventana) return Object.hasOwn(CONTEXTO_POR_VENTANA, ventana) ? CONTEXTO_POR_VENTANA[ventana] : null;
  return Object.hasOwn(CONTEXTO_POR_PANEL, panel) ? CONTEXTO_POR_PANEL[panel] : null;
}

export const MENSAJES = {
  cargar: { titulo: '¿No sabes por dónde empezar?', texto: '¡Déjame ayudarte! Te enseño esta pantalla paso a paso.' },
  revision: { titulo: '¿Qué reviso primero?', texto: 'Te muestro cómo revisar las preguntas y qué significa cada color.' },
  final: { titulo: '¿Y ahora qué hago?', texto: 'Te explico cómo llevar el XML a Moodle y qué más puedes hacer.' },
  biblioteca: { titulo: '¿Cómo funcionan las materias?', texto: 'Te enseño a ordenar y a encontrar tus exámenes.' },
  perfil: { titulo: '¿Para qué sirve tu perfil?', texto: 'Te cuento cómo guardar tu nombre y tus encabezados.' },
  pdf: { titulo: '¿Qué opciones tiene el PDF?', texto: 'Te explico cada parte de este diálogo.' },
};

/**
 * ¿Se le ofrece el recorrido con un globo, sin que lo pida? Solo si no pidió que dejara de ofrecerlos, aún
 * no hizo ese recorrido y no se le ofreció ya en esta sesión (`yaOfrecidos`: los contextos de esta sesión).
 */
export function debeSaludar(estado, contexto, yaOfrecidos) {
  if (!contexto || !Object.hasOwn(MENSAJES, contexto)) return false;
  const tour = contexto === 'biblioteca' ? ['biblioteca', 'bibliotecaLista'] : [contexto];
  return !estado.descartado && !tour.some(n => estado.vistos.includes(n)) && !yaOfrecidos.has(contexto);
}
