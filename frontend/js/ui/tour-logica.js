/**
 * tour-logica.js — los recorridos guiados («Recorrido» de cada pantalla) sin tocar el DOM (se prueba en Node).
 * Cada recorrido es una lista de pasos { el, titulo, texto, lado }: `el` es el selector del elemento que se
 * resalta (null: un paso de presentación, en el centro). Los pasos cuyo elemento no está en pantalla se
 * saltan (por ejemplo, el de la «Pág. N» cuando el examen no es un PDF). Los textos son HTML escrito aquí, nunca datos del docente.
 * El recorrido lo dibuja driver.js (js/vendor/driver); ver tour.js.
 */

export const CLAVE_VISTOS = 'conversor.tours';

export const TOURS = {
  inicio: {
    pasos: [
      { el: '#inicio-titulo', titulo: 'Tres formas de empezar', texto: 'Todas terminan igual: en el <b>editor</b>, y de ahí salen el <b>XML para Moodle</b>, el PDF o el Word para imprimir y, si quieres, varias versiones.', lado: 'bottom' },
      { el: '#inicio-documento', titulo: 'Convertir un documento', texto: 'Si la evaluación ya está en <b>Word, PDF o TXT</b>: Cátedra la lee y tú revisas las preguntas.', lado: 'bottom' },
      { el: '#inicio-cero', titulo: 'Crear desde cero', texto: 'Abre el editor vacío: eliges el tipo de cada pregunta y la escribes.', lado: 'bottom' },
      { el: '#inicio-xml', titulo: 'Editar un Moodle XML', texto: 'Abre un XML que ya tengas para corregirlo y volver a generarlo.', lado: 'bottom' },
      { el: '#btn-materias', titulo: 'Mis materias', texto: 'Tu biblioteca: todas tus evaluaciones ordenadas por materia, para reabrirlas, descargarlas o exportarlas en PDF o Word.', lado: 'bottom' },
      { el: '#btn-perfil', titulo: 'Mi perfil', texto: 'Guarda tu nombre y los encabezados de tu institución (con logos) una sola vez: saldrán solos en cada PDF o Word.', lado: 'bottom' },
      { el: '#btn-help', titulo: 'Guía', texto: 'Aquí está la explicación completa. Además, el <b>robot ayudante</b> de la esquina de abajo a la izquierda te explica cualquier pantalla: haz clic en él cuando quieras repetir un recorrido.', lado: 'bottom' },
    ],
  },
  cargar: {
    pasos: [
      { el: '.stepper', titulo: 'Tres pasos', texto: '<b>Cargas</b> tu archivo, <b>revisas</b> las preguntas y <b>exportas</b>: el XML para Moodle, el PDF o el Word, o varias versiones.', lado: 'bottom' },
      { el: '#drop-zone', titulo: 'Elige tu archivo', texto: 'Arrástralo aquí o haz clic para buscarlo. Para convertir: <b>PDF</b>, <b>Word</b> o <b>TXT</b>. Para editar: un <b>Moodle XML</b>.', lado: 'right' },
      { el: '#category-input', titulo: 'Categoría de Moodle', texto: 'El nombre de la carpeta donde quedarán las preguntas en el <b>Banco de preguntas</b> de Moodle. Por ejemplo: <i>Parcial-Historia-2026</i>.', lado: 'bottom' },
      { el: '#points-input', titulo: 'Puntaje total', texto: 'Cuánto vale toda la evaluación. Después, en el editor, Cátedra lo reparte entre las preguntas y tú lo ajustas; o escribes cuánto vale cada tipo y el total sale de la suma.', lado: 'bottom' },
      { el: '#materia-select', titulo: 'Materia (opcional)', texto: 'Elige a qué materia pertenece, o crea una nueva desde aquí. Así la encuentras después en <b>Mis materias</b>, y con materia la evaluación <b>no se borra sola</b> cuando se llena el espacio.', lado: 'top' },
      { el: '#actividad-input', titulo: 'Tipo de actividad (opcional)', texto: 'Para distinguirlo dentro de la materia: <i>Parcial 1</i>, <i>Quiz 2</i>… Sale en el encabezado al imprimirlo.', lado: 'top' },
      { el: '#btn-convert', titulo: 'Continuar', texto: 'Se activa cuando eliges un archivo. Al convertir un documento, Cátedra lo lee en unos segundos; un XML se abre al instante.', lado: 'top' },
      { el: '#btn-volver-inicio', titulo: 'Volver', texto: 'Regresa a la elección de cómo empezar.', lado: 'bottom' },
    ],
  },
  revision: {
    pasos: [
      { el: '#editor-datos', titulo: 'Datos de la evaluación', texto: 'Nombre de la actividad, puntaje total, categoría de Moodle, materia y tipo de actividad. El total se reparte solo entre las preguntas hasta que cambies algún punto.', lado: 'bottom' },
      { el: '.editor-vacio', titulo: 'Tu primera pregunta', texto: 'Elige el tipo y escríbela. Llega vacía: Cátedra no pone texto ni respuestas por ti.', lado: 'top' },
      { el: '.editor-head', titulo: 'Compara y corrige', texto: 'Si convertiste un documento, compara cada pregunta con él: la lectura puede tener errores o respuestas faltantes. Cátedra <b>no inventa nada</b>; lo dudoso queda marcado para que lo veas.', lado: 'bottom' },
      { el: '.editor-card .card-toggle', titulo: 'Cada pregunta es una fila', texto: 'Muestra su número, tipo, enunciado y la respuesta que lleva. Haz clic para abrirla y editarla. Las que piden revisión se abren solas.', lado: 'bottom' },
      { el: '.editor-card .proc-pagina', titulo: 'Pág. N: compara con el original', texto: 'Si tu evaluación es un PDF, este botón abre el <b>recorte de la página</b> donde está la pregunta, junto a la respuesta que propone Cátedra y qué tan segura está.', lado: 'bottom' },
      { el: '.editor-card .card-orden', titulo: 'Ordenar y duplicar', texto: 'Sube o baja una pregunta, o duplícala para usarla como base de otra. Las de un <b>enunciado compartido</b> se mueven dentro de su grupo, y el grupo entero con las flechas de su bloque.', lado: 'bottom' },
      { el: '.elegir-tipo', titulo: 'Enunciado compartido', texto: 'Cuando de un mismo caso, texto o figura salen <b>varias preguntas</b>, elige <b>Enunciado compartido</b> entre los tipos. Queda en un <b>marco</b> con su texto, sus imágenes y sus preguntas, que puedes plegar entero; lo de fuera es independiente. En papel sale una sola vez y en Moodle va dentro de cada pregunta.', lado: 'top' },
      { el: '[data-accion="toggleFilterMenu"]', titulo: 'Mostrar', texto: 'Deja ver solo un tipo de pregunta, las que conviene <b>revisar primero</b> o los <b>posibles problemas</b>. Las que ocultes igual van al XML.', lado: 'bottom' },
      { el: '[data-accion="togglePointsToolMenu"]', titulo: 'Puntos', texto: 'Cuánto suman frente al total. Repártelos igual para todas, o escribe cuántos puntos vale <b>cada pregunta de cada tipo</b>: el total de la evaluación es la suma. Puedes deshacerlo.', lado: 'bottom' },
      { el: '#review-rail', titulo: 'Mapa de la evaluación', texto: 'Un cuadro por pregunta: <b>rojo</b> = incompleta, <b>ámbar</b> = para revisar. Haz clic para ir a esa pregunta; con las teclas <kbd>J</kbd> y <kbd>K</kbd> avanzas y retrocedes.', lado: 'top' },
      { el: '#btn-generate-xml', titulo: 'Generar XML', texto: 'Cuando todo esté bien. No avanza mientras haya preguntas incompletas o propuestas de la IA sin aceptar ni descartar.', lado: 'top' },
      { el: '#btn-discard-review', titulo: 'Descartar', texto: 'Borra lo que estás revisando y vuelve al inicio (pide confirmación). Se guarda solo en este equipo, por si cierras la ventana.', lado: 'top' },
    ],
  },
  final: {
    pasos: [
      { el: '#success-title', titulo: '¡Tu XML está listo!', texto: 'La evaluación quedó guardada en tu equipo (en <b>Mis materias</b>). Esto es lo que puedes hacer ahora.', lado: 'bottom' },
      { el: '#btn-download', titulo: 'Descargar Moodle XML', texto: 'Guarda el archivo. Para usarlo en Moodle: <b>Banco de preguntas → Importar → Formato XML de Moodle</b>.', lado: 'bottom' },
      { el: '#btn-exportar-pdf', titulo: 'Exportar evaluación', texto: 'Para tenerlo en papel con su clave, en <b>PDF</b> o en <b>Word</b> editable, o con hoja de respuestas aparte; cada documento se descarga por separado. Se abre una pantalla con <b>vista previa</b>.', lado: 'bottom' },
      { el: '#exito-materia', titulo: 'Guardada en tu materia', texto: 'Aquí ves en qué materia quedó y puedes cambiarla.', lado: 'bottom' },
      { el: '#btn-back-to-review', titulo: 'Volver al editor', texto: '¿Viste un error? Regresa, corrige y genera el XML otra vez.', lado: 'bottom' },
      { el: '#points-chart-card', titulo: 'Resumen', texto: 'Cuántas preguntas y cuántos puntos hay de cada tipo.', lado: 'top' },
      { el: '#btn-reset-success', titulo: 'Empezar otra evaluación', texto: 'Vuelve al inicio para empezar con otra.', lado: 'top' },
    ],
  },
  biblioteca: {
    pasos: [
      { el: '#vm-cuerpo .vm-cab', titulo: 'Tu biblioteca', texto: 'Cada <b>materia</b> es un espacio con todas sus evaluaciones. Elige una para reabrir, descargar o exportar sus evaluaciones en PDF o Word.', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-cab-acciones [data-accion="nuevaMateria"]', titulo: 'Nueva materia', texto: 'Créala con un nombre y un color. Opcionalmente le pones su perfil de encabezado, su docente y su grupo: el PDF los usará solos.', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-cab-acciones [data-accion="abrirTodos"]', titulo: 'Todas las evaluaciones', texto: 'La lista completa, de la más reciente a la más antigua, con buscador.', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-ordenar', titulo: 'Ordenar con ayuda', texto: 'Si tienes evaluaciones sin materia, Cátedra propone a cuál pertenece cada una según su categoría y su nombre. <b>Tú decides</b> qué se mueve.', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-tarjetas .vm-tarjeta:not(.vm-tarjeta-sin)', titulo: 'Una materia', texto: 'Haz clic para entrar. El lápiz la edita, la archiva o la borra (borrar una materia <b>no</b> borra sus evaluaciones).', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-tarjeta-sin', titulo: 'Sin materia', texto: 'Las evaluaciones sin materia. Cuando se llena el espacio, <b>estas se borran primero</b>; mueve a una materia lo que quieras conservar.', lado: 'top' },
      { el: '#vm-cuerpo .vm-aviso', titulo: 'Aviso de espacio', texto: 'Aparece cuando el espacio se está llenando (300 evaluaciones o 400 MB).', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-uso', titulo: 'Cuánto espacio usas', texto: 'Cuántas evaluaciones tienes guardadas y cuánto ocupan.', lado: 'top' },
    ],
  },
  bibliotecaLista: {
    pasos: [
      { el: '#vm-cuerpo .vm-cab', titulo: 'Las evaluaciones de esta lista', texto: 'Aquí están las evaluaciones ya convertidas. Con <b>Mis materias</b> (arriba a la izquierda) vuelves a tus materias.', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-cab-acciones [data-accion="nuevoExamenEnMateria"]', titulo: 'Nueva evaluación en esta materia', texto: 'Vuelve al inicio con esta materia ya elegida.', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-cab-acciones [data-accion="editarMateria"]', titulo: 'Editar materia', texto: 'Cambia su nombre y color, ponle perfil de encabezado, docente y grupo predeterminados, archívala o bórrala.', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-cab-acciones [data-accion="abrirAsistente"]', titulo: 'Ordenar con ayuda', texto: 'Propone a qué materia pertenece cada evaluación según su categoría y su nombre. <b>Tú decides</b> qué se mueve.', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-buscar', titulo: 'Buscar', texto: 'Por nombre del archivo, categoría, tipo de actividad o fecha. No distingue mayúsculas ni tildes.', lado: 'bottom' },
      { el: '#vm-cuerpo #vm-seleccion', titulo: 'Elegir varios', texto: 'Marca <b>Elegir todas</b> o algunas evaluaciones para <b>moverlas</b> a una materia o <b>borrarlas</b> de una vez. Útil para limpiar pruebas.', lado: 'bottom' },
      { el: '#vm-cuerpo .vm-fila .vm-fila-acciones', titulo: 'Qué hacer con una evaluación', texto: '<b>Reabrir</b> la abre en el editor; <b>Exportar</b> la saca en PDF o Word; <b>XML</b> la descarga otra vez.', lado: 'left' },
      { el: '#vm-cuerpo .vm-organizar-boton', titulo: 'Organizar', texto: 'Cambia su materia o su tipo de actividad, o bórrala.', lado: 'left' },
    ],
  },
  perfil: {
    pasos: [
      { el: '#vp-form', titulo: 'Mis datos', texto: 'Tu nombre y cómo te llamas en el encabezado (<i>Facilitador</i>, <i>Docente</i> o <i>Profesor</i>). Los escribes una vez y salen en cada PDF o Word.', lado: 'bottom' },
      { el: '[data-accion="nuevoPerfilEnc"]', titulo: 'Perfiles de encabezado', texto: 'Un perfil guarda la <b>institución, los logos, las indicaciones generales y el formato de impresión</b>, con vista previa. Crea uno por cada institución donde das clase.', lado: 'bottom' },
      { el: '#vp-perfiles .vp-perfil', titulo: 'Tu perfil', texto: '<b>Editar</b> lo cambia, <b>Duplicar</b> hace una copia para variarla, y la papelera lo borra.', lado: 'bottom' },
      { el: '#vp-perfiles .vp-perfil [data-accion="predeterminadoPerfilEnc"]', titulo: 'Perfil predeterminado', texto: 'El perfil predeterminado es con el que empieza la pantalla de exportar.', lado: 'top' },
      { el: null, titulo: 'Qué se aplica al exportar', texto: 'Al exportar un PDF, la pantalla empieza con lo de la <b>materia</b> (su perfil, docente y grupo); si no, con tu <b>perfil predeterminado</b> y tus datos; si no, con lo último que escribiste. Siempre puedes cambiarlo en esa evaluación.' },
    ],
  },
  pdf: {
    pasos: [
      { el: '#pdf-pestanas', titulo: 'Cuatro pestañas', texto: '<b>Evaluación</b> es lo que cambia cada vez; <b>Encabezado</b>, <b>Página</b> y <b>Preguntas</b> se configuran una vez y se recuerdan.', lado: 'bottom', pestana: 'pdf-tab-examen' },
      { el: '#pdf-datos-examen', titulo: 'Datos de esta evaluación', texto: 'Materia, tipo de actividad, grupo y fecha: salen en el encabezado. Al elegir una materia se rellenan su perfil, su docente y su grupo. Todo es opcional.', lado: 'right', pestana: 'pdf-tab-examen' },
      { el: '#pdf-grupo-incluir', titulo: '¿Cómo contestan?', texto: '<b>En la misma evaluación</b>, o <b>en una hoja aparte</b>: una hoja de preguntas para repartir, una hoja para que el estudiante conteste y la clave ya llena.', lado: 'right', pestana: 'pdf-tab-examen' },
      { el: '#pdf-grupo-formato', titulo: 'Formato del archivo', texto: '<b>PDF</b> para imprimir, <b>Word</b> (.docx) para editarlo antes, o los dos en un ZIP. Salen del mismo plan: mismas preguntas, mismo orden de las opciones y misma clave. La vista previa es la del PDF.', lado: 'right', pestana: 'pdf-tab-examen' },
      { el: '#pdf-versiones', titulo: 'Versiones de la evaluación', texto: 'Con una evaluación grande como banco (por ejemplo 100 preguntas) puedes sacar <b>varios parciales distintos</b>: elige cuántas versiones y cuántas preguntas lleva cada una, al azar o <b>por tipo</b> (todas las de verdadero o falso, 25 de selección múltiple…). Cada versión sale con su clave, en un ZIP (con PDF, Word o los dos).', lado: 'right', pestana: 'pdf-tab-examen' },
      { el: '#pdf-perfil', titulo: 'Perfil de encabezado', texto: 'Carga de una vez lo que guardaste de <b>Encabezado</b>, <b>Página</b> y <b>Preguntas</b>. Los perfiles se administran en <b>Mi perfil</b>.', lado: 'right', pestana: 'pdf-tab-encabezado' },
      { el: '#pdf-sec-encabezado', titulo: 'Institución y docente', texto: 'Institución, facultad, departamento y docente. Debajo, los logos (uno o dos) y las indicaciones generales.', lado: 'right', pestana: 'pdf-tab-encabezado' },
      { el: '#pdf-grupo-portada', titulo: 'En la primera hoja', texto: 'El cuadro con los datos del estudiante y el <b>cuadro de puntos</b>: el valor de cada parte y un renglón para anotar lo obtenido al corregir.', lado: 'right', pestana: 'pdf-tab-encabezado' },
      { el: '#pdf-sec-formato', titulo: 'La hoja y la letra', texto: 'Papel, márgenes, tipo y tamaño de letra y, abajo, cuánto <b>espacio para responder</b>: el recuadro de desarrollo y el del procedimiento.', lado: 'right', pestana: 'pdf-tab-pagina' },
      { el: '#pdf-grupo-opciones', titulo: 'Opciones y puntos', texto: 'Si se <b>mezclan las opciones</b> (para que la clave no delate las respuestas), si cada pregunta dice cuánto vale y <b>puntos enteros</b>: el PDF usa solo enteros (7 pts en vez de 6,67) y el Moodle XML no cambia.', lado: 'right', pestana: 'pdf-tab-preguntas' },
      { el: '#pdf-sec-partes', titulo: 'Partes de la evaluación', texto: 'Cambia el <b>orden</b> de las partes, haz que una empiece <b>en hoja nueva</b> y, si quieres, escribe tu propio nombre e indicación. Si la evaluación tiene imágenes, debajo eliges su tamaño y su posición.', lado: 'right', pestana: 'pdf-tab-preguntas' },
      { el: '#pdf-previa', titulo: 'Vista previa', texto: 'La página tal como saldrá; se actualiza al cambiar cualquier dato. Con versiones, cada una tiene su pestaña, y ahí mismo ajustas sus <b>puntos</b> para que sumen el total que quieres.', lado: 'left' },
      { el: '#btn-pdf-exportar', titulo: 'Exportar', texto: 'Pregunta <b>qué quieres imprimir</b> (la evaluación o la hoja de preguntas, la hoja de respuestas o la clave) y, en PDF, si va <b>normal</b> o en <b>modo folleto</b>: dos páginas por cara, para doblar y ahorrar papel. El XML no cambia.', lado: 'top' },
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
  return pasos.filter(p => p.el === null || p.el === undefined || existe(p.el, p));
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
  return !estado.descartado && !estado.vistos.includes('inicio');
}

// ── El asistente flotante (ui/asistente.js) ──────────────────────────────
/** Los ids de las ventanas encima de las cuales el asistente sigue disponible (con su recorrido). */
const CONTEXTO_POR_VENTANA = { 'vista-pdf': 'pdf', 'vista-perfil': 'perfil', 'vista-materias': 'biblioteca' };
const CONTEXTO_POR_PANEL = { inicio: 'inicio', upload: 'cargar', editor: 'revision', success: 'final' };

/**
 * Qué recorrido toca ahora: el de la ventana de más arriba si es una con recorrido; si hay otra ventana
 * (confirmación, Guía, clave…) o una pantalla de espera, null y el asistente se esconde.
 */
export function contextoDeAyuda({ ventana = null, panel = 'inicio' } = {}) {
  if (ventana) return Object.hasOwn(CONTEXTO_POR_VENTANA, ventana) ? CONTEXTO_POR_VENTANA[ventana] : null;
  return Object.hasOwn(CONTEXTO_POR_PANEL, panel) ? CONTEXTO_POR_PANEL[panel] : null;
}

export const MENSAJES = {
  inicio: { titulo: '¿No sabes por dónde empezar?', texto: '¡Déjame ayudarte! Te explico las tres formas de empezar.' },
  cargar: { titulo: '¿Qué pongo aquí?', texto: 'Te enseño esta pantalla paso a paso.' },
  revision: { titulo: '¿Qué reviso primero?', texto: 'Te muestro cómo revisar las preguntas y qué significa cada color.' },
  final: { titulo: '¿Y ahora qué hago?', texto: 'Te explico cómo llevar el XML a Moodle y qué más puedes hacer.' },
  biblioteca: { titulo: '¿Cómo funcionan las materias?', texto: 'Te enseño a ordenar y a encontrar tus evaluaciones.' },
  perfil: { titulo: '¿Para qué sirve tu perfil?', texto: 'Te cuento cómo guardar tu nombre y tus encabezados.' },
  pdf: { titulo: '¿Qué opciones tiene la exportación?', texto: 'Te explico cada parte de esta pantalla.' },
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
