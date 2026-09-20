/**
 * util.js — ayudas sin estado: formato, escape de HTML y color.
 */

// File Helpers
export function formatBytes(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

export function esc_html(s) {
  const div = document.createElement('div');
  div.textContent = s == null ? '' : String(s);
  return div.innerHTML;
}

// Traduce el motivo técnico que devuelve el validador (pensado para el
// panel de errores estricto, tipo log) a una frase en lenguaje llano
// para el resumen de preguntas omitidas — reconoce los patrones más
// comunes y da una explicación breve; si no reconoce el patrón, al
// menos le quita el prefijo "Error:" para que no se vea tan crudo.
export function humanizeSkipReason(reason) {
  reason = reason || '';
  if (/no pudo transcribir con confianza/.test(reason)) {
    return 'Esta pregunta incluye una imagen que no se pudo leer con claridad (borrosa, cortada o de baja calidad).';
  }
  if (/no tiene una respuesta correcta especificada/.test(reason) || /no se encontró la respuesta correcta del espacio/.test(reason)) {
    return 'No se encontró ninguna respuesta marcada para esta pregunta en el documento original.';
  }
  if (/no es un número válido/.test(reason)) {
    const m = reason.match(/respuesta '([^']*)'/);
    return `La respuesta indicada${m ? ` ("${m[1]}")` : ''} no es un número — revisa que esté escrita como número en el documento original.`;
  }
  if (/no coincide con ninguna de las opciones/.test(reason)) {
    return 'La respuesta marcada no coincide con ninguna de las opciones de esta pregunta — puede haber un error de transcripción.';
  }
  if (/inválida.*Verdadero.*Falso/.test(reason)) {
    return 'La respuesta de esta pregunta no quedó clara como "Verdadero" o "Falso".';
  }
  if (/falta '(stem)'/.test(reason) || /no se pudo interpretar el enunciado/.test(reason)) {
    return 'No se encontró el enunciado de esta pregunta.';
  }
  if (/falta '(options)'/.test(reason) || /opciones marcadas con letras/.test(reason) || /falta opciones válidas/.test(reason)) {
    return 'No se encontraron opciones de respuesta válidas para esta pregunta.';
  }
  if (/la opción '.*' de la Pregunta \d+ \(multichoice\) no tiene texto/.test(reason)) {
    return 'Una de las opciones de esta pregunta quedó sin texto.';
  }
  if (/no se encontró ningún espacio en blanco/.test(reason) || /no se detectaron espacios/.test(reason) || /etiqueta Moodle vacía/.test(reason) || /espacio \[.*\] está vacío/.test(reason) || /formato inválido en espacio/.test(reason)) {
    return 'Hay un problema con uno de los espacios en blanco de esta pregunta de completar.';
  }
  if (/columna|matching|par\(es\)|elemento/i.test(reason)) {
    return 'Hay un problema con las columnas o las parejas de este emparejamiento — revisa que coincidan con el documento original.';
  }
  if (/no se encontró su enunciado en el documento/.test(reason)) {
    return 'Esta pregunta aparece en la clave de respuestas, pero no se encontró su enunciado en el documento.';
  }
  return reason.replace(/^Error:\s*/i, '');
}

// ── Gráfica de pastel: puntos totales por tipo ─────────────────────────
// Cada porción representa el SUBTOTAL de puntos del tipo (preguntas del
// tipo × pts/pregunta), no el conteo de preguntas — un tipo con pocas
// preguntas pero pts/pregunta alto (emparejar, completar) puede pesar
// más de lo que su cantidad sugiere.
export function getCssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function hexToRgb(hex) {
  const clean = hex.replace('#', '');
  const full = clean.length === 3 ? clean.split('').map(c => c + c).join('') : clean;
  const num = parseInt(full, 16);
  return { r: (num >> 16) & 255, g: (num >> 8) & 255, b: num & 255 };
}

// Luminancia relativa (WCAG) para elegir texto blanco o negro legible
// encima de cada porción coloreada, sin importar el tono ni el tema.
export function textColorOnFill(hex) {
  const { r, g, b } = hexToRgb(hex);
  const [rs, gs, bs] = [r, g, b].map(v => {
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  const luminance = 0.2126 * rs + 0.7152 * gs + 0.0722 * bs;
  return luminance > 0.5 ? '#0f172a' : '#ffffff';
}

export function polarToCartesian(cx, cy, r, angleDeg) {
  const rad = (angleDeg - 90) * Math.PI / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

export function describeArcSlice(cx, cy, r, startAngle, endAngle) {
  const start = polarToCartesian(cx, cy, r, endAngle);
  const end = polarToCartesian(cx, cy, r, startAngle);
  const largeArcFlag = endAngle - startAngle <= 180 ? '0' : '1';
  return `M ${cx} ${cy} L ${start.x} ${start.y} A ${r} ${r} 0 ${largeArcFlag} 0 ${end.x} ${end.y} Z`;
}

// Mensaje de respaldo cuando el servidor responde con error pero sin un
// cuerpo JSON legible (.detail) que explique qué pasó — antes se le
// mostraba al usuario un desnudo "Error (500)", que no dice nada
// accionable. Cubre los códigos que de verdad pueden ocurrir en este
// flujo (archivo muy pesado, límite de la API de IA, backend caído).
export function friendlyHttpError(status) {
  const known = {
    413: 'El archivo es demasiado pesado para procesarlo. Intenta con un PDF más liviano o divide el examen en partes.',
    429: 'El servicio de IA está recibiendo demasiadas solicitudes en este momento. Espera un minuto y vuelve a intentarlo.',
    500: 'Ocurrió un error inesperado en el servidor al procesar tu examen.',
    502: 'El servidor no pudo completar la solicitud. Vuelve a intentarlo en unos segundos.',
    503: 'El servicio no está disponible en este momento. Vuelve a intentarlo en unos segundos.',
    504: 'La solicitud tardó demasiado en responder. Vuelve a intentarlo — si tu examen es muy largo, puede tomar más tiempo del esperado.',
  };
  return known[status] || `El servidor respondió con un error (código ${status}). Vuelve a intentarlo; si el problema persiste, revisa que el archivo no esté dañado.`;
}

export function formatMMSS(totalSeconds) {
  const s = Math.max(0, Math.round(totalSeconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}
