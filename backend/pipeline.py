"""
pipeline.py — Normalización de un documento subido (PDF/TXT) hasta la
respuesta que consume el editor: {questions, answer_key, ...}.

Vive fuera de main.py para que la MISMA lógica la usen tanto los
endpoints HTTP (/api/parse, /api/normalize_with_ai) como el script de
evaluación (dev/eval.py) — así la evaluación mide exactamente lo que
ejecuta la app, no una copia que se pueda desincronizar.

Todas las funciones son síncronas (pdfplumber y la llamada a Gemini
bloquean); main.py las corre en threadpool.
"""

import copy
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException

from config import ENRICH_PDF_TEXT, NORMALIZER_MODE, NORMALIZER_MODE_AI
# get_api_key ya no se usa aquí (la comprobación la hace el proveedor de IA), pero
# las pruebas lo sustituyen en este módulo: se conserva el nombre.
from credenciales import get_api_key  # noqa: F401
import confianza
import ia_proveedor
import origen_pdf
import originales
from extractor import (
    MAX_IMAGE_PAGES,
    DocumentoDemasiadoGrande,
    comprobar_paginas,
    extract_pages_text,
    extract_pages_enriched_and_tables,
    get_colored_pages,
    join_pages_with_markers,
    extract_text_and_images_from_pdf,
    extract_text_from_pdf,
    extract_text_from_txt,
    render_all_pages_as_images,
)
from extractor_docx import DocxInvalido, leer_docx
from formatter import verify_and_format, extract_structured, extract_missing, comprobar_cancelacion
from imagenes import asignar_imagenes, candidatas_omitidas_numeradas, extraer_imagenes_pdf
from schema_adapter import adapt
import mark_resolver
from mark_resolver import resolve_answer_marks, resolve_table_marks, resolve_tf_marks
from parser import parse_answer_key, build_questions
from validator import (
    partition_questions,
    pre_validate_raw_text,
    estimate_notice_count,
    estimate_expected_questions,
)

logger = logging.getLogger(__name__)

# Aviso genérico cuando el PDF tiene texto en color pero todavía no se sabe
# (o no se pudo determinar) si ese color marca respuestas. _marks_notice lo
# reemplaza por uno concreto cuando las marcas se resolvieron en código.
COLOR_MARKS_NOTICE = "Hay marcas de color que no se pudieron leer. Revisa las preguntas con «revisar marca»."

# Un PDF escaneado no tiene capa de texto: ni el color ni ninguna otra marca se
# puede leer en código, solo la ve el modelo en la imagen. Medido (dev/eval x10,
# marcas en rojo contrafácticas): devolvió lo que él cree correcto en 8,7 de 9
# preguntas en vez de lo que el docente marcó. El aviso lo dice sin rodeos.
SCANNED_MARKS_NOTICE = (
    "Escaneado: verifica cada respuesta contra el original. Si las respuestas están marcadas por color "
    "u otra marca, la IA las lee de la imagen y puede reemplazarlas por lo que ella cree correcto."
)

# Nombre de la marca en el aviso: cualquier color es simplemente "color".
_MARK_LABELS = {"resaltado": "resaltado", "subrayado": "subrayado", "negrita": "negrita", "mixta": "marcas"}


def _marks_notice(mark: Any, applied: int, n_table: int, n_uncertain: int,
                  fallback: Any, n_tf: int = 0) -> Any:
    """Aviso corto cuando las respuestas salieron de marcas del documento
    (color, resaltado, subrayado, negrita o X en un cuadro). applied y
    n_table cuentan las preguntas que llegan al editor con la respuesta
    leída de la marca; n_uncertain no se usa en el texto (esas preguntas ya
    llevan su propia etiqueta «revisar marca»)."""
    kinds = []
    if mark and applied:
        kinds.append(_MARK_LABELS.get(mark, "color"))
    if n_table:
        kinds.append("cuadro con X")
    if n_tf:
        kinds.append("marca en verdadero/falso")
    if not kinds:
        return fallback
    return f"Respuestas identificadas por {' y '.join(kinds)}. Revísalas antes de aprobar."


_COLOR_HINT_MIN_LEN = 20  # evita anclar con un enunciado demasiado corto/genérico

# Recibe eventos de avance para la pantalla de carga (ver main.py, los
# endpoints *_stream). Nunca es obligatorio: sin él, el flujo es idéntico.
ProgressCallback = Optional[Callable[[Dict[str, Any]], None]]


def _emit(progress: ProgressCallback, **event: Any) -> None:
    if progress is None:
        return
    try:
        progress(event)
    except Exception:  # noqa: BLE001 — un aviso de progreso nunca debe romper la conversión
        logger.debug("No se pudo emitir un evento de progreso", exc_info=True)


def _ai_progress(progress: ProgressCallback, expected: int):
    """Adapta el conteo de preguntas que reporta formatter al evento que
    consume la pantalla de carga."""
    if progress is None:
        return None
    return lambda done: _emit(progress, type="progress", done=done, expected=expected)


def _ai_retry(progress: ProgressCallback):
    """Aviso de "esperando y reintentando" (Google saturado, límite por
    minuto): la pantalla lo muestra para que no parezca que se colgó."""
    if progress is None:
        return None
    return lambda message: _emit(progress, type="stage", key="retry", message=message)


def _tag_color_review_hints(valid_questions: List[Dict[str, Any]], colored_pages_text: List[str]) -> None:
    """
    Marca in-place cada pregunta multichoice cuya página de origen tenía
    texto de color, agregando data["color_review_hint"] = True. Se ubica la
    página de origen por coincidencia del ENUNCIADO (no de las opciones:
    muchos exámenes reutilizan el mismo set de opciones A/B/C/D en varias
    preguntas distintas — anclar por opción daba falsos positivos casi
    universales; el enunciado, en cambio, es prácticamente único por
    pregunta). Es un heurístico aproximado, no exacto, ya que el prefiltro
    de IA renumera y reescribe el documento (ver REGLA 7) y no conserva de
    qué página vino cada pregunta. Sirve solo para dirigir la revisión
    manual del usuario, no para bloquear nada, así que un falso positivo
    ocasional no es grave.
    """
    normalized_pages = [" ".join(t.split()).lower() for t in colored_pages_text]

    for q in valid_questions:
        if q.get("type") != "multichoice":
            continue
        stem = (q.get("data") or {}).get("stem", "")
        candidate = " ".join(stem.split()).lower()
        if len(candidate) < _COLOR_HINT_MIN_LEN:
            continue
        if any(candidate in page_text for page_text in normalized_pages):
            q["data"]["color_review_hint"] = True


def _mensaje_error_pdf(exc: Exception) -> Optional[str]:
    """Mensaje claro y en español para un fallo conocido al abrir/leer un PDF
    (None si no se reconoce). Antes se mostraba «Error al extraer el texto del
    archivo: » con el detalle vacío (pdfminer lanza PDFPasswordIncorrect sin
    mensaje)."""
    cadena = list(_cadena_de_excepciones(exc))
    if any(type(e).__name__ in ("PDFPasswordIncorrect", "PDFEncryptionError") or "password" in str(e).lower()
           for e in cadena):
        return ("El PDF está protegido con contraseña y no se puede leer. Ábrelo con la contraseña, "
                "quítale la protección (por ejemplo, «Imprimir» → «Guardar como PDF») y súbelo de nuevo.")
    if any(type(e).__name__ in ("PDFSyntaxError", "PSEOF", "PSSyntaxError", "PDFException", "PDFNoValidXRef",
                                "PDFTextExtractionNotAllowed", "PdfminerException", "PDFObjectNotFound",
                                "PDFXRefFallback") for e in cadena):
        return ("El PDF parece dañado o no se puede leer. Ábrelo en un lector de PDF y vuelve a guardarlo "
                "(«Imprimir» → «Guardar como PDF»), o prueba con otra copia del archivo.")
    return None


def _cadena_de_excepciones(exc: BaseException, profundidad: int = 5):
    """La excepción y las que lleva dentro: pdfplumber envuelve la de pdfminer
    en PdfminerException (con la causa en args[0] y str() vacío), así que
    mirar solo el tipo de afuera confundía «con contraseña» con «dañado»."""
    vistas = set()
    pendientes = [(exc, 0)]
    while pendientes:
        actual, nivel = pendientes.pop(0)
        if id(actual) in vistas or nivel > profundidad:
            continue
        vistas.add(id(actual))
        yield actual
        hijos = [a for a in getattr(actual, "args", ()) if isinstance(a, BaseException)]
        hijos += [e for e in (actual.__cause__, actual.__context__) if e is not None]
        pendientes.extend((h, nivel + 1) for h in hijos)


def _detalle_lectura(exc: Exception, prefijo: str) -> str:
    """Detalle para el docente: el mensaje conocido, o el prefijo con lo que
    diga la excepción (o su nombre si viene vacía)."""
    return _mensaje_error_pdf(exc) or f"{prefijo}: {str(exc).strip() or type(exc).__name__}"


def _comprobar_entrada(raw_bytes: bytes, suffix: str) -> None:
    """Antes de leer el documento (lo más caro después de la IA): sin la
    credencial del proveedor de IA no hay conversión posible (cada proveedor
    sabe qué le falta: ver ia_proveedor.comprobar_listo), y un PDF con
    demasiadas páginas se rechaza sin procesarlo."""
    try:
        ia_proveedor.proveedor_actual().comprobar_listo()
    except ia_proveedor.IASinClaveError as exc:
        raise HTTPException(status_code=503, detail=exc.mensaje)
    except ia_proveedor.ErrorConfiguracionIA as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    if suffix == ".pdf":
        try:
            comprobar_paginas(raw_bytes)
        except DocumentoDemasiadoGrande as exc:
            raise HTTPException(status_code=413, detail=str(exc))
        except Exception as exc:  # noqa: BLE001
            # Con contraseña se avisa de inmediato y con claridad; cualquier
            # otro PDF dañado lo informa la extracción, como siempre.
            mensaje = _mensaje_error_pdf(exc)
            if mensaje and "contraseña" in mensaje:
                raise HTTPException(status_code=422, detail=mensaje)


def _hay_marca_de_respuestas(marks, respaldo: bool) -> bool:
    """¿El documento marca de verdad las respuestas (color, resaltado,
    subrayado, negrita)? Es lo que decide si vale la pena el reintento de
    calidad de la IA (hasta 3 llamadas completas): antes bastaba CUALQUIER
    texto no gris (un encabezado azul) o cualquier página con una imagen o
    fórmulas. Usa el mismo criterio que mark_resolver aplicará después: una
    marca que se repite en al menos 2 líneas cortas con aspecto de opción.
    Sin texto enriquecido no se puede saber: se usa `respaldo`."""
    if not marks:
        return respaldo
    try:
        return mark_resolver.detectar_marca(marks[0]) is not None
    except Exception:  # noqa: BLE001 — sin poder decidir, el comportamiento de siempre
        logger.debug("No se pudo detectar la marca de respuestas", exc_info=True)
        return respaldo


def _aviso_paginas(total: int, enviadas: int, hay_texto: bool) -> Optional[str]:
    """Aviso cuando solo las primeras `enviadas` de `total` páginas llegaron a
    la IA como imagen. En un escaneado (sin texto) el resto se pierde por
    completo, y como no hay texto no había forma de estimar cuántas preguntas
    faltaban (completeness_notice nunca saltaba)."""
    if total <= enviadas:
        return None
    if hay_texto:
        return (f"El PDF tiene {total} páginas y solo las primeras {enviadas} se enviaron a la IA como imagen "
                "(el texto de todas sí se leyó). Revisa que no falte nada en las últimas páginas: "
                "código en captura, imágenes o marcas de color.")
    return (f"El PDF tiene {total} páginas, pero solo las primeras {enviadas} se pudieron leer como imagen: "
            f"las preguntas de las páginas {enviadas + 1} a {total} NO están en el resultado. "
            f"Divide el examen en partes de hasta {enviadas} páginas y conviértelas por separado.")


def _adjuntar_original(resultado: Dict[str, Any], raw_bytes: bytes, filename: str) -> Dict[str, Any]:
    """«Revisión con el original»: si el documento es un PDF, el servidor lo conserva
    en memoria (ver originales.py) y la respuesta lleva su `original_id`. Nada del
    examen original va al Historial. Word y TXT no tienen original que mostrar."""
    if Path(filename).suffix.lower() == ".pdf":
        ident = originales.guardar(raw_bytes)
        if ident:
            resultado["original_id"] = ident
    return resultado


def parse_document(raw_bytes: bytes, filename: str, progress: ProgressCallback = None,
                   ia_cache: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _adjuntar_original(_parse_document(raw_bytes, filename, progress, ia_cache), raw_bytes, filename)


def _parse_document(raw_bytes: bytes, filename: str, progress: ProgressCallback = None,
                    ia_cache: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Flujo de /api/parse: texto (+ imágenes de páginas con imagen incrustada).

    ia_cache: diccionario opcional donde se guarda lo que respondió la IA. Si
    el llamador reintenta tras un fallo del postproceso (main.py), pasa el
    MISMO diccionario y la IA no se vuelve a llamar (un error determinista en
    el postproceso costaba el doble de llamadas)."""
    suffix = Path(filename).suffix.lower()
    if suffix not in (".pdf", ".txt", ".docx"):
        raise HTTPException(
            status_code=400,
            detail=f"Formato no soportado '{suffix}'. Se aceptan archivos .pdf, .docx (Word) o .txt.",
        )
    _comprobar_entrada(raw_bytes, suffix)

    # ── Extraer texto (+ imágenes de páginas con contenido visual) ─────
    # Las imágenes son solo de páginas que de verdad tienen una incrustada
    # (código en captura, texto marcado por color) — no se renderiza el
    # documento completo.
    _emit(progress, type="stage", key="extract", message="Leyendo el documento…")
    page_images: list = []
    # Imágenes de las preguntas, con el texto que las precede: después de la
    # IA se asignan a su pregunta y llegan a Moodle (ver imagenes.py).
    imagenes_preguntas = None
    docx = None
    try:
        if suffix == ".pdf":
            full_text, page_images = extract_text_and_images_from_pdf(raw_bytes)
            try:
                imagenes_preguntas = extraer_imagenes_pdf(raw_bytes)
            except Exception as exc:  # noqa: BLE001 — sin imágenes, la conversión sigue igual
                logger.warning("No se pudieron extraer las imágenes de '%s': %s", filename, exc)
        elif suffix == ".docx":
            docx = leer_docx(raw_bytes)
            full_text = docx.texto_plano
            imagenes_preguntas = docx.ubicaciones
            # Las mismas imágenes van a la IA (código en captura, gráficos).
            page_images = [im.imagen for im in docx.ubicaciones.imagenes[:MAX_IMAGE_PAGES]]
        else:
            full_text = extract_text_from_txt(raw_bytes)
    except DocxInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("Error extrayendo texto de '%s': %s", filename, exc)
        raise HTTPException(status_code=422, detail=_detalle_lectura(exc, "Error al extraer el texto del archivo"))

    if not full_text.strip():
        raise HTTPException(
            status_code=422,
            detail="El archivo no contiene texto legible.",
        )

    # ── Aviso informativo (no bloqueante): respuestas marcadas por color ──
    # colored_pages_text también se usa para marcar INDIVIDUALMENTE las
    # preguntas cuya página de origen tiene esa marca (ver
    # _tag_color_review_hints), en vez de un solo aviso genérico.
    # colored_page_numbers se calcula aquí mismo (mismo pdfplumber.open())
    # y se reutiliza más abajo en el modo JSON — antes se recalculaba con
    # una segunda pasada por todo el PDF (_colored_pages) más adelante.
    color_marks_notice = None
    colored_pages_text: list = []
    colored_page_numbers: List[int] = []
    if suffix == ".pdf":
        try:
            colored_page_numbers, colored_pages_text = get_colored_pages(raw_bytes)
            if colored_pages_text:
                color_marks_notice = COLOR_MARKS_NOTICE
        except Exception as exc:
            logger.warning("No se pudo chequear texto de color en '%s': %s", filename, exc)

    # ── Pre-validación local ─────────────────────────────────────────────
    try:
        pre_validate_raw_text(full_text)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": "Validación previa fallida:", "errors": [str(exc)]},
        )

    # Cuántas preguntas parece tener el documento ORIGINAL (antes de la IA)
    # — solo para poder avisar si el prefiltro terminó devolviendo bastantes
    # menos de las esperadas.
    estimated_question_count = estimate_notice_count(full_text)

    # ── Gemini prefiltro: normalizar estructura ──────────────────────────
    if suffix == ".pdf":
        marks = _deterministic_marks(raw_bytes)
    elif docx is not None:
        # Word ya trae sus marcas y tablas: mismo formato que un PDF de una página.
        marks = ([docx.texto_enriquecido], docx.tablas)
    else:
        marks = None

    comprobar_cancelacion()
    expected = estimate_expected_questions(full_text)
    # El reintento de calidad de la IA solo si el documento marca de verdad
    # las respuestas (ver _hay_marca_de_respuestas).
    reintento_calidad = _hay_marca_de_respuestas(marks, bool(colored_pages_text))
    en_cache = ia_cache is not None and ("payload" in ia_cache or "texto" in ia_cache)
    if not en_cache:
        _emit(progress, type="stage", key="ai", mode=NORMALIZER_MODE, expected=expected,
              images=len(page_images), message="La IA está ordenando las preguntas…")
    on_ai = _ai_progress(progress, expected)

    if NORMALIZER_MODE == "json":
        if ia_cache is not None and "payload" in ia_cache:
            logger.info("Reintento del postproceso: se reutiliza la respuesta de la IA ya obtenida.")
        else:
            if suffix == ".pdf":
                model_text = _model_text_json(raw_bytes, marks)
            elif docx is not None:
                model_text = join_pages_with_markers([docx.texto_enriquecido])
            else:
                model_text = full_text
            payload = extract_structured(model_text, page_images, progress=on_ai, on_retry=_ai_retry(progress),
                                       permitir_reintento_calidad=reintento_calidad)
            payload = _completar_omitidas(payload, imagenes_preguntas, page_images, _ai_retry(progress))
            if ia_cache is not None:
                ia_cache["payload"] = payload
        comprobar_cancelacion()
        _emit(progress, type="stage", key="review", message="Revisando respuestas y marcas del documento…")
        # Copia: el postproceso (adapt…) puede modificar el payload, y si hay
        # que reintentarlo tiene que partir de la respuesta original de la IA.
        payload = copy.deepcopy(ia_cache["payload"]) if ia_cache is not None else payload
        return _finalize_structured(
            filename, payload,
            estimated_question_count, colored_pages_text, color_marks_notice,
            colored_page_numbers, marks, imagenes_preguntas,
            pdf_bytes=raw_bytes if suffix == ".pdf" else None,
        )

    if ia_cache is not None and "texto" in ia_cache:
        logger.info("Reintento del postproceso: se reutiliza la respuesta de la IA ya obtenida.")
    else:
        model_text = "\n".join(marks[0]) if marks else full_text
        resultado_ia = verify_and_format(model_text, page_images, progress=on_ai, on_retry=_ai_retry(progress),
                                         permitir_reintento_calidad=reintento_calidad)
        if ia_cache is not None:
            ia_cache["texto"] = resultado_ia
        else:
            ia_cache = {"texto": resultado_ia}
    reformatted_text, was_reformatted = ia_cache["texto"]
    comprobar_cancelacion()
    _emit(progress, type="stage", key="review", message="Revisando respuestas y marcas del documento…")

    return finalize_parse_response(
        filename, full_text, reformatted_text, was_reformatted,
        estimated_question_count, colored_pages_text, color_marks_notice, marks,
        pdf_bytes=raw_bytes if suffix == ".pdf" else None,
    )


def normalize_document_with_ai(raw_bytes: bytes, filename: str, progress: ProgressCallback = None,
                               ia_cache: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _adjuntar_original(_normalize_document_with_ai(raw_bytes, filename, progress, ia_cache), raw_bytes, filename)


def _normalize_document_with_ai(raw_bytes: bytes, filename: str, progress: ProgressCallback = None,
                                ia_cache: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Flujo de /api/normalize_with_ai: renderiza el documento COMPLETO como
    imágenes y deja que Gemini lo lea visualmente, sin depender de que el
    PDF tenga una capa de texto extraíble (PDF escaneado, o con contenido
    visual que el modo normal no capturó).

    ia_cache: ver parse_document.
    """
    suffix = Path(filename).suffix.lower()
    if suffix != ".pdf":
        raise HTTPException(
            status_code=400,
            detail="Normalizar con IA solo aplica a archivos .pdf (un .txt ya es texto plano).",
        )
    _comprobar_entrada(raw_bytes, suffix)

    _emit(progress, type="stage", key="extract", message="Preparando las páginas del documento…")
    try:
        full_text = extract_text_from_pdf(raw_bytes)
        page_images, total_paginas = render_all_pages_as_images(raw_bytes, con_total=True)
        colored_page_numbers, colored_pages_text = get_colored_pages(raw_bytes)
    except Exception as exc:
        logger.error("Error extrayendo contenido de '%s' para normalizar: %s", filename, exc)
        raise HTTPException(status_code=422, detail=_detalle_lectura(exc, "Error al leer el archivo"))

    if not full_text.strip() and not page_images:
        raise HTTPException(
            status_code=422,
            detail="No se pudo extraer ningún contenido (ni texto ni páginas) del archivo.",
        )

    if not full_text.strip():
        color_marks_notice = SCANNED_MARKS_NOTICE
    else:
        color_marks_notice = COLOR_MARKS_NOTICE if colored_pages_text else None
    # Páginas que no llegaron a la IA (el PDF pasa del tope de páginas como imagen).
    aviso_paginas = _aviso_paginas(total_paginas, len(page_images), bool(full_text.strip()))
    if aviso_paginas:
        logger.warning("'%s': %d páginas, solo %d enviadas como imagen.", filename, total_paginas, len(page_images))

    # Sin pre_validate_raw_text aquí a propósito: esa validación exige
    # indicios de "pregunta"/"respuesta" en el TEXTO extraído, pero en el
    # caso escaneado (la razón de ser de este flujo) ese texto está vacío
    # por definición — toda la lectura depende de las imágenes.
    estimated_question_count = estimate_notice_count(full_text)

    comprobar_cancelacion()
    marks = _deterministic_marks(raw_bytes)
    # En un escaneado no hay texto del que estimar cuántas preguntas vienen:
    # expected=0 y la pantalla muestra solo el avance, sin "de ~N".
    expected = estimate_expected_questions(full_text) if full_text.strip() else 0
    reintento_calidad = _hay_marca_de_respuestas(marks, bool(colored_pages_text))
    en_cache = ia_cache is not None and ("payload" in ia_cache or "texto" in ia_cache)
    if not en_cache:
        _emit(progress, type="stage", key="ai", mode=NORMALIZER_MODE_AI, expected=expected,
              images=len(page_images), message="La IA está leyendo las páginas del documento…")
    on_ai = _ai_progress(progress, expected)

    if NORMALIZER_MODE_AI == "json":
        if ia_cache is not None and "payload" in ia_cache:
            logger.info("Reintento del postproceso: se reutiliza la respuesta de la IA ya obtenida.")
        else:
            model_text = _model_text_json(raw_bytes, marks)
            payload = extract_structured(model_text, page_images, progress=on_ai, on_retry=_ai_retry(progress),
                                       permitir_reintento_calidad=reintento_calidad)
            if ia_cache is not None:
                ia_cache["payload"] = payload
        comprobar_cancelacion()
        _emit(progress, type="stage", key="review", message="Revisando respuestas y marcas del documento…")
        payload = copy.deepcopy(ia_cache["payload"]) if ia_cache is not None else payload
        return _finalize_structured(
            filename, payload,
            estimated_question_count, colored_pages_text, color_marks_notice,
            colored_page_numbers, marks, aviso_paginas=aviso_paginas, pdf_bytes=raw_bytes,
            escaneado=not full_text.strip(),
        )

    if ia_cache is not None and "texto" in ia_cache:
        logger.info("Reintento del postproceso: se reutiliza la respuesta de la IA ya obtenida.")
    else:
        resultado_ia = verify_and_format(full_text, page_images, progress=on_ai, on_retry=_ai_retry(progress),
                                         permitir_reintento_calidad=reintento_calidad)
        if ia_cache is not None:
            ia_cache["texto"] = resultado_ia
        else:
            ia_cache = {"texto": resultado_ia}
    reformatted_text, was_reformatted = ia_cache["texto"]
    comprobar_cancelacion()
    _emit(progress, type="stage", key="review", message="Revisando respuestas y marcas del documento…")

    return finalize_parse_response(
        filename, full_text, reformatted_text, was_reformatted,
        estimated_question_count, colored_pages_text, color_marks_notice, marks,
        aviso_paginas=aviso_paginas, pdf_bytes=raw_bytes, escaneado=not full_text.strip(),
    )


def _deterministic_marks(raw_bytes: bytes):
    """(páginas enriquecidas, tablas) si ENRICH_PDF_TEXT está activo, o
    None. Se calcula una vez y sirve para el texto que va al modelo y para
    resolver las marcas en código después (mark_resolver)."""
    if not ENRICH_PDF_TEXT:
        return None
    try:
        return extract_pages_enriched_and_tables(raw_bytes)
    except Exception as exc:  # noqa: BLE001 — sin enriquecer, el flujo sigue igual que antes
        logger.warning("No se pudo enriquecer el texto del PDF: %s", exc)
        return None


def finalize_parse_response(
    filename: str,
    full_text: str,
    reformatted_text: str,
    was_reformatted: bool,
    estimated_question_count: int,
    colored_pages_text: List[str],
    color_marks_notice: Any,
    marks=None,
    aviso_paginas: Optional[str] = None,
    pdf_bytes: Optional[bytes] = None,
    escaneado: bool = False,
) -> Dict[str, Any]:
    """
    Cola común de ambos flujos: ya con el texto reformateado por Gemini, de
    aquí en adelante el procesamiento es idéntico sin importar cómo se
    obtuvo ese texto.
    """
    # ── Parse answer key del texto reformateado ──────────────────────────
    original_answer_key = parse_answer_key(full_text)
    answer_key = parse_answer_key(reformatted_text)

    # Combinar ambas claves para tener la lista completa (origen de verdad de lo que el usuario cargó)
    effective_answer_key = {**original_answer_key, **answer_key}

    if not effective_answer_key:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Error de estructura en el examen:",
                "errors": [
                    "No se encontró la sección RESPUESTAS o no pudo parsearse ninguna respuesta.",
                    "Verifica que el archivo contenga la sección 'RESPUESTAS' con el formato correcto."
                ]
            }
        )

    questions = build_questions(reformatted_text, effective_answer_key)

    if not questions:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Error de extracción:",
                "errors": [
                    f"Se encontraron {len(effective_answer_key)} respuestas en la clave pero no se pudo extraer ninguna pregunta del cuerpo del documento.",
                    "Verifica que las preguntas tengan el formato 'Pregunta N:'."
                ]
            }
        )

    # Página verificada y recuadro de cada pregunta (solo PDF con texto).
    _ubicar_en_pdf(questions, pdf_bytes)
    # Modo texto: la respuesta se atribuye al documento solo si él trae su
    # propia clave y la de la IA es idéntica (ver confianza.clave_documento_coincide).
    desde_documento = confianza.clave_documento_coincide(original_answer_key, answer_key)

    return _finalize_common(
        filename, questions, effective_answer_key, was_reformatted,
        estimated_question_count, colored_pages_text, color_marks_notice, marks,
        aviso_paginas=aviso_paginas, desde_documento=desde_documento, escaneado=escaneado,
    )


def _ubicar_en_pdf(questions: List[Dict[str, Any]], pdf_bytes: Optional[bytes]) -> int:
    """Escribe en cada pregunta que se pueda ubicar en el PDF su página
    VERIFICADA (data["page"], que reemplaza a la que dijo la IA) y su recuadro
    (data["recuadro"], fracciones 0–1 de la página). Las que no se ubican con
    certeza quedan como estaban (con la página de la IA, si la dio). Solo PDF
    con texto; ver origen_pdf.py. Informativo: nunca cambia una respuesta."""
    if not pdf_bytes:
        return 0
    try:
        ubicadas = origen_pdf.ubicar_preguntas(pdf_bytes, questions)
    except Exception as exc:  # noqa: BLE001 — sin ubicación, la conversión sigue igual
        logger.warning("No se pudieron ubicar las preguntas en el PDF: %s", exc)
        return 0
    n = 0
    for q in questions:
        u = ubicadas.get(q.get("num"))
        if u and isinstance(q.get("data"), dict):
            q["data"]["page"] = u["page"]
            q["data"]["recuadro"] = u["recuadro"]
            n += 1
    if n:
        logger.info("Preguntas ubicadas en el PDF: %d de %d.", n, len(questions))
    return n


# Cuántas preguntas omitidas hace falta detectar para intentar
# completarlas con una llamada dirigida (ver _completar_omitidas). Con
# más que esto, en la práctica el detector se está confundiendo con
# opciones numeradas o con la columna de un emparejamiento (probado con
# 3 exámenes reales sin ninguna omisión real: dio 9 "candidatas" en cada
# uno), no con omisiones de verdad — mejor no arriesgar una llamada de
# más y dejar la recuperación manual de siempre ("preguntas no
# incluidas" en el editor) como única red de seguridad, igual que si
# esta función no existiera.
MAX_OMITIDAS_A_COMPLETAR = 3


def _completar_omitidas(payload: Dict[str, Any], imagenes_preguntas, page_images, on_retry) -> Dict[str, Any]:
    """
    Antes de adaptar la respuesta de la IA: revisa en código (sin gastar
    otra llamada) si hay preguntas NUMERADAS del documento que la IA se
    saltó por completo (ver imagenes.candidatas_omitidas_numeradas) y, si
    son pocas, le pide a la IA SOLO esas en una llamada pequeña y las
    inserta en su lugar — mucho más barato que repetir la conversión
    entera, y ataca el fallo real más común observado en la práctica (la
    IA omite una pregunta que es solo una imagen con un enunciado corto).

    Es "mejor esfuerzo" de punta a punta: cualquier problema (sin
    candidatas, demasiadas, la detección falla, o la llamada de la IA no
    ayuda) deja `payload` intacto y la conversión sigue exactamente como
    si esta función no existiera — el aviso de "preguntas no incluidas"
    del editor sigue cubriendo lo que quede sin resolver.
    """
    if not imagenes_preguntas or not getattr(imagenes_preguntas, "lineas", None):
        return payload
    preguntas_raw = payload.get("preguntas") or []
    if not preguntas_raw:
        return payload
    # "data" con options/col_a/col_b (no solo el enunciado): el detector
    # necesita comparar contra las opciones YA devueltas para no confundir
    # una pregunta de verdad omitida con una opción numerada de la
    # pregunta anterior (ver el comentario en candidatas_omitidas_numeradas).
    def _liviana(p: Dict[str, Any]) -> Dict[str, Any]:
        opciones = {str(k): o.get("texto", "") for k, o in enumerate(p.get("opciones") or [])}
        izq = {str(k + 1): v for k, v in enumerate(p.get("items_izquierda") or [])}
        der = {chr(97 + k): v for k, v in enumerate(p.get("items_derecha") or [])}
        return {"stem": p.get("enunciado") or "", "options": opciones, "col_a": izq, "col_b": der}
    livianas = [{"num": i, "data": _liviana(p)} for i, p in enumerate(preguntas_raw, 1)]
    try:
        candidatas = candidatas_omitidas_numeradas(livianas, imagenes_preguntas, max_candidatas=MAX_OMITIDAS_A_COMPLETAR)
    except Exception as exc:  # noqa: BLE001 — nunca debe romper la conversión
        logger.warning("No se pudieron revisar preguntas omitidas: %s", exc)
        return payload
    if not (1 <= len(candidatas) <= MAX_OMITIDAS_A_COMPLETAR):
        return payload

    logger.info("Posibles preguntas omitidas por la IA: %d. Pidiendo solo esas…", len(candidatas))
    nuevas = extract_missing([c["texto"] for c in candidatas], page_images, on_retry=on_retry)
    if not nuevas:
        return payload

    # Cada respuesta se empareja con su candidata por el campo "orden" (el
    # número de fragmento que se le pidió a la IA), NO por posición: si la IA
    # devolvía menos preguntas, o las reordenaba, el texto de una candidata
    # quedaba en el hueco de otra (contenido alterado). Lo que no cuadra
    # (sin orden válido, repetido, de un fragmento que no existe) se descarta.
    por_fragmento: Dict[int, Dict[str, Any]] = {}
    for nueva in nuevas:
        if not isinstance(nueva, dict):
            continue
        orden = nueva.get("orden")
        if isinstance(orden, bool) or not isinstance(orden, (int, float)) or orden != int(orden):
            continue
        orden = int(orden)
        if not (1 <= orden <= len(candidatas)) or orden in por_fragmento:
            if orden in por_fragmento:  # dos respuestas para el mismo fragmento: ninguna es fiable
                por_fragmento[orden] = None  # type: ignore[assignment]
            continue
        por_fragmento[orden] = nueva
    emparejadas = [(c, por_fragmento.get(i)) for i, c in enumerate(candidatas, 1)]
    if not any(n for _, n in emparejadas):
        return payload

    # Cada una se inserta justo después de la pregunta que la precede (la
    # misma que ya estaba en el documento), con un "orden" propio a mitad
    # de camino hacia la siguiente — no hace falta tocar el de las demás.
    ordenes = [p.get("orden") or 0 for p in preguntas_raw]
    for candidata, nueva in emparejadas:
        if not nueva:
            continue
        despues_de = candidata["despues_de"]
        if despues_de and 1 <= despues_de <= len(preguntas_raw):
            anterior_orden = preguntas_raw[despues_de - 1].get("orden") or despues_de
        else:
            anterior_orden = 0
        posteriores = [o for o in ordenes if o > anterior_orden]
        siguiente_orden = min(posteriores) if posteriores else anterior_orden + 1
        nueva["orden"] = (anterior_orden + siguiente_orden) / 2
        nueva["_rescatada"] = True  # confianza.py: la recuperó un reintento, no la IA en la primera pasada
        preguntas_raw.append(nueva)
        ordenes.append(nueva["orden"])
    payload["preguntas"] = preguntas_raw
    return payload


def _model_text_json(raw_bytes: bytes, marks) -> str:
    """Texto para el modo JSON: por página con "[Página N]", y enriquecido
    (color y tablas) si ENRICH_PDF_TEXT está activo."""
    if marks:
        return join_pages_with_markers(marks[0])
    return join_pages_with_markers(extract_pages_text(raw_bytes))


def _finalize_structured(
    filename: str,
    payload: Dict[str, Any],
    estimated_question_count: int,
    colored_pages_text: List[str],
    color_marks_notice: Any,
    colored_page_numbers: List[int] = (),
    marks=None,
    imagenes_preguntas=None,
    aviso_paginas: Optional[str] = None,
    pdf_bytes: Optional[bytes] = None,
    escaneado: bool = False,
) -> Dict[str, Any]:
    """Modo JSON: la salida del modelo ya viene estructurada; el adaptador
    la deja en la misma forma que produce parser.py en el modo texto."""
    questions, answer_key = adapt(payload)
    rescatadas, desde_documento = confianza.senales_del_payload(payload)
    # Página verificada en el PDF (reemplaza a la que dijo la IA) y recuadro.
    _ubicar_en_pdf(questions, pdf_bytes)
    # Con la página de origen (la verificada, o la que informa el modelo), el
    # aviso "revisar marca de color" deja de ser un heurístico por texto: es
    # exacto por página.
    colored = set(colored_page_numbers)
    for q in questions:
        if q["type"] == "multichoice" and q["data"].get("page") in colored:
            q["data"]["color_review_hint"] = True
    if not questions:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Error de extracción:",
                "errors": ["No se identificó ninguna pregunta en el documento."],
            },
        )
    return _finalize_common(
        filename, questions, answer_key, True,
        estimated_question_count, colored_pages_text, color_marks_notice, marks,
        imagenes_preguntas, aviso_paginas=aviso_paginas,
        rescatadas=rescatadas, desde_documento=desde_documento, escaneado=escaneado,
    )


def _finalize_common(
    filename: str,
    questions: List[Dict[str, Any]],
    effective_answer_key: Dict[int, Dict[str, Any]],
    was_reformatted: bool,
    estimated_question_count: int,
    colored_pages_text: List[str],
    color_marks_notice: Any,
    marks=None,
    imagenes_preguntas=None,
    aviso_paginas: Optional[str] = None,
    rescatadas=(),
    desde_documento=(),
    escaneado: bool = False,
) -> Dict[str, Any]:
    """Cola compartida por ambos modos: marcas resueltas en código, modo
    tolerante, avisos y recorte de la clave a las preguntas válidas."""
    mark_result: Dict[str, Any] = {"mark": None, "applied": 0, "changed": 0}
    n_table = 0
    n_tf = 0
    if marks:
        pages, tables = marks
        # Siempre, no solo con texto en color: resaltado, subrayado y
        # negrita también son marcas. resolve_answer_marks decide si el
        # documento de verdad marca respuestas así (ver su docstring).
        mark_result = resolve_answer_marks(questions, effective_answer_key, pages)
        n_table = resolve_table_marks(questions, effective_answer_key, tables) if tables else 0
        n_tf = resolve_tf_marks(questions, effective_answer_key, pages)
        if mark_result["applied"] or n_table or n_tf:
            logger.info("Marcas resueltas en código: %d por marca (%s), %d por tabla, %d en verdadero/falso.",
                        mark_result["applied"], mark_result["mark"], n_table, n_tf)

    # Modo Tolerante: separar preguntas válidas de las que hay que omitir
    # en vez de bloquear TODA la conversión por una sola pregunta
    # problemática — el usuario revisa lo válido en el editor, y ve un
    # resumen de lo que se omitió y por qué.
    # Imágenes: se ubican con TODAS las preguntas (también las que se van a
    # omitir), para que la de una omitida no caiga en la anterior.
    # Siempre se llama: además quita la marca interna _comparte_imagen de la IA.
    omitidas_por_ia: List[Dict[str, Any]] = []
    n_img = asignar_imagenes(questions, imagenes_preguntas, omitidas_por_ia)
    if imagenes_preguntas and imagenes_preguntas.imagenes:
        logger.info("Imágenes asignadas a preguntas: %d de %d.", n_img, len(imagenes_preguntas.imagenes))

    valid_questions, skipped_questions = partition_questions(questions, effective_answer_key)
    # Preguntas con imagen que la IA no devolvió: se ofrecen para rescatar.
    skipped_questions.extend(omitidas_por_ia)

    if colored_pages_text:
        _tag_color_review_hints(valid_questions, colored_pages_text)
    # Una respuesta leída de la marca en código, o de la clave del documento,
    # no necesita "revisar marca": el aviso queda solo para las que la IA
    # tuvo que interpretar.
    for q in valid_questions:
        if q["data"].get("answer_from_marks") or effective_answer_key.get(q["num"], {}).get("from_key"):
            q["data"].pop("color_review_hint", None)
    # De dónde salió cada respuesta y cuánta confianza da (solo informativo;
    # ver confianza.py). Va después de las marcas y de «revisar marca», que son
    # sus entradas.
    confianza.etiquetar(valid_questions, effective_answer_key, rescatadas, desde_documento, escaneado=escaneado)
    n_uncertain = sum(1 for q in valid_questions if q["data"].get("color_review_hint"))
    from_marks = [q for q in valid_questions if q["data"].get("answer_from_marks")]
    color_marks_notice = _marks_notice(
        mark_result["mark"],
        sum(1 for q in from_marks if q["type"] == "multichoice"),
        sum(1 for q in from_marks if q["type"] == "matching"),
        n_uncertain, color_marks_notice,
        sum(1 for q in from_marks if q["type"] == "truefalse"),
    )

    if not valid_questions:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "No se pudo procesar ninguna pregunta del examen:",
                "errors": [r for sq in skipped_questions for r in sq["reasons"]] or [
                    "Ninguna pregunta del documento coincidió con un tipo soportado (opción múltiple, verdadero/falso, emparejamiento o completar)."
                ],
            }
        )

    # Aviso suave (no bloqueante) si el documento parecía tener bastantes
    # más preguntas de las que se terminaron procesando + omitiendo.
    processed_total = len(valid_questions) + len(skipped_questions)
    completeness_notice = None
    if estimated_question_count >= 3 and processed_total < estimated_question_count * 0.6:
        completeness_notice = (
            f"El documento original parecía tener alrededor de {estimated_question_count} "
            f"preguntas, pero solo se identificaron {processed_total}. Puede que algunas se "
            f"hayan pasado por alto — revisa el documento original para confirmar que no falte nada."
        )
    if aviso_paginas:
        completeness_notice = f"{aviso_paginas} {completeness_notice}" if completeness_notice else aviso_paginas

    # La clave que se manda de vuelta se recorta a solo las preguntas
    # válidas: /api/generate_xml vuelve a validar cruzando questions contra
    # answer_key uno a uno, y con las entradas de las omitidas todavía ahí
    # esa validación las marcaría como "falta el enunciado".
    valid_nums = {q["num"] for q in valid_questions}
    trimmed_answer_key = {num: info for num, info in effective_answer_key.items() if num in valid_nums}

    return {
        "filename": filename,
        "questions": valid_questions,
        "answer_key": trimmed_answer_key,
        "was_reformatted": was_reformatted,
        "skipped_questions": skipped_questions,
        "completeness_notice": completeness_notice,
        "color_marks_notice": color_marks_notice,
        "escaneado": bool(escaneado),
    }
