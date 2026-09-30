"""
xml_builder.py — Converts parsed question data into Moodle XML.

Generates XML that conforms to the Moodle XML Question Format spec:
  - UTF-8 encoding
  - CDATA sections for HTML content
  - Correct tag structure per question type (multichoice, truefalse, matching, cloze)
"""

import html
import logging
import math
import re
from typing import Dict, List, Optional

from config import (
    TYPE_WEIGHTS,
    MULTICHOICE_PENALTY,
    FEEDBACK_CORRECT,
    FEEDBACK_INCORRECT,
    DEFAULT_MATCHING_STEM,
)
from models import QuestionStats
from answer_matching import (
    TRUEFALSE_ALIAS, RespuestaNoResuelta, clave_de_columna, clave_de_huecos, find_cloze_brackets,
    normalizar_numero, resolver_hueco_cloze, resolver_opcion, split_answers, split_options,
)

logger = logging.getLogger(__name__)


def compute_grades(
    questions: List[dict],
    total_points: float,
) -> Dict[str, float]:
    """
    Calculate the grade (defaultgrade) per question type so that
    all questions together sum exactly to `total_points`.

    Formula:
        unit = total_points / Σ(weight_i × count_i)
        grade_type = weight_type × unit
    """
    counts: Dict[str, int] = {t: 0 for t in TYPE_WEIGHTS}
    for q in questions:
        t = q["type"]
        if t in counts:
            counts[t] += 1

    total_weight = sum(TYPE_WEIGHTS[t] * counts[t] for t in TYPE_WEIGHTS)
    if total_weight == 0:
        return {t: 1.0 for t in TYPE_WEIGHTS}

    unit = total_points / total_weight
    return {t: round(TYPE_WEIGHTS[t] * unit, 7) for t in TYPE_WEIGHTS}


# XML 1.0 no admite estos caracteres de control (ni siquiera escapados): un
# \x0c (salto de página, o un \f de un \frac mal escapado que llegó del
# editor) o un \x0b (salto de línea "manual" de Word pegado a mano) rompía
# TODA la exportación con "CData section not finished" — un examen entero
# se perdía por un carácter en una sola pregunta.
_CONTROL_INVALIDO = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _sin_control(text: str) -> str:
    return _CONTROL_INVALIDO.sub("", text)


def esc(text: str) -> str:
    """HTML-escape text for safe embedding in XML."""
    return html.escape(_sin_control(str(text)), quote=True)


def cdata(text: str) -> str:
    """Wrap text in a CDATA section (required by Moodle for HTML content)."""
    return f"<![CDATA[{text}]]>"


def texto_html(text: str) -> str:
    """Enunciado/retroalimentación como HTML: escapa, y convierte los
    saltos de línea del enunciado (código, listas propias) en <br> y los
    espacios de apertura de cada línea en &nbsp; — si no, el HTML los
    colapsa a uno solo y el código pierde la sangría, y antes el enunciado
    entero se veía corrido en un solo renglón (la retroalimentación sí
    convertía el salto de línea, pero el enunciado no)."""
    escapado = esc(text)
    lineas = [re.sub(r"^ +", lambda m: "&nbsp;" * len(m.group(0)), ln) for ln in escapado.split("\n")]
    return "<br>".join(lineas)


def strip_accents(s: str) -> str:
    return (s.replace('á', 'a').replace('é', 'e').replace('í', 'i')
             .replace('ó', 'o').replace('ú', 'u')
             .replace('Á', 'A').replace('É', 'E').replace('Í', 'I')
             .replace('Ó', 'O').replace('Ú', 'U')
             .replace('ñ', 'n').replace('Ñ', 'N'))


def _pesos_cloze(n_huecos: int, peso_total: Optional[int]) -> List[int]:
    """Pesos enteros (Moodle no admite decimales) de los `n_huecos` huecos de
    una pregunta de completar para que sumen `peso_total` (mínimo 1 por
    hueco). Sin peso_total, todos pesan 1."""
    if not peso_total:
        return [1] * n_huecos
    total = max(n_huecos, int(peso_total))
    base, resto = divmod(total, n_huecos)
    return [base + (1 if i < resto else 0) for i in range(n_huecos)]


_ESCALAS = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 25, 30, 40, 50, 70, 100, 200, 500, 1000)


def _nota_de(q: dict, grades: Dict[str, float]) -> float:
    """<defaultgrade> de una pregunta: su puntaje propio del editor o, si no
    llegó, el reparto por peso de tipo."""
    q_points = q.get("points")
    has_points = (isinstance(q_points, (int, float)) and not isinstance(q_points, bool)
                  and math.isfinite(q_points) and q_points >= 0)
    return q_points if has_points else grades.get(q["type"], 1.0)


def _plan_puntos(questions: List[dict], grades: Dict[str, float]) -> tuple:
    """(escala, {id(pregunta): <defaultgrade> final}) para que el total y el
    valor de cada pregunta en Moodle coincidan con el editor.

    Moodle IGNORA el <defaultgrade> de «Completar»: vale la suma de los
    pesos (enteros) de sus huecos. Para que valga lo mismo que en el editor:
      1. Se busca el factor más chico (1, 2, 3…) que multiplicado por TODOS
         los puntos deja cada «Completar» casi entero (≤ 0,5 % de error) y
         con al menos 1 por hueco. Multiplicar todo por igual no cambia la
         nota final: Moodle la calcula sobre el total.
      2. El pequeño resto de redondear esos pesos se reparte entre las
         demás preguntas, así el total en Moodle es exactamente el del
         editor × factor (ej. 100 → 100, no 102,9).
    """
    notas = {id(q): _nota_de(q, grades) for q in questions}
    casos = []
    for q in questions:
        if q.get("type") == "cloze" and "error" not in q and notas[id(q)] > 0:
            huecos = max(1, len(find_cloze_brackets((q.get("data") or {}).get("text", ""))))
            casos.append((notas[id(q)], huecos))

    def cabe(k: int, tolerancia: float) -> bool:
        return all(n * k >= h and abs(round(n * k) - n * k) <= tolerancia * n * k for n, h in casos)

    escala = next((k for k in _ESCALAS if cabe(k, 0.005)), None)
    if escala is None:
        escala = next((k for k in _ESCALAS if cabe(k, 0.06)), 1)
    finales = {i: round(n * escala, 7) for i, n in notas.items()}

    huecos_de = {id(q): max(1, len(find_cloze_brackets((q.get("data") or {}).get("text", ""))))
                 for q in questions if q.get("type") == "cloze" and "error" not in q and finales[id(q)] > 0}
    suma_resto = sum(v for i, v in finales.items() if i not in huecos_de)
    if huecos_de and suma_resto > 0:
        suma_cloze = sum(max(huecos_de[i], round(finales[i])) for i in huecos_de)
        factor = (sum(finales.values()) - suma_cloze) / suma_resto
        if 0.95 <= factor <= 1.05:
            for i in finales:
                if i not in huecos_de:
                    finales[i] = round(finales[i] * factor, 7)
    return escala, finales


def _html_fuera_de_huecos(texto: str, inicio_de_linea: bool) -> str:
    """Trozo de enunciado de un Cloze (fuera de los huecos) como HTML: escapa
    (sin tocar las comillas, como antes), convierte los saltos de línea en <br>
    y los espacios de apertura de cada línea en &nbsp; (misma idea que
    texto_html: si no, el HTML colapsa la sangría del código y el enunciado se
    ve en un solo renglón). `inicio_de_linea`: el trozo empieza al comienzo de
    una línea (no justo después de un hueco)."""
    lineas = html.escape(_sin_control(texto).replace("\r\n", "\n"), quote=False).split("\n")
    lineas = [
        re.sub(r"^ +", lambda m: "&nbsp;" * len(m.group(0)), ln) if (i > 0 or inicio_de_linea) else ln
        for i, ln in enumerate(lineas)
    ]
    return "<br>".join(lineas)


def convert_cloze_to_moodle(cloze_text: str, q_num: int, answer_key: Dict[int, dict],
                            peso_total: Optional[int] = None, como_html: bool = False) -> str:
    """
    Convert [A: correct_option / option2 / option3] brackets to
    Moodle {1:MULTICHOICE_S:=correct~opt2~opt3} syntax.
    Handles multiple embedded gaps (A, B, C...) dynamically.

    Uses the "_S" (shuffled) variant deliberately: plain MULTICHOICE inside
    a Cloze question ignores the quiz's "shuffle within questions" setting
    and always shows options in the authored order — a well-known Moodle
    behavior (see MDL-10971). MULTICHOICE_S is the variant that actually
    responds to that setting, while still defaulting to unshuffled when the
    teacher leaves shuffling off, so this is a strict improvement with no
    downside for anyone who doesn't want shuffling.

    Si la respuesta de la clave de un hueco no identifica UNA de sus opciones
    (no está, o coincide por igual con varias) lanza RespuestaNoResuelta: no
    se marca la primera opción en su lugar (el validador ya lo rechaza antes;
    esto es la segunda barrera). Con `como_html`, el texto de fuera de los
    huecos sale escapado y con <br>/&nbsp; (lo que va dentro de <questiontext
    format="html">) y los huecos escapados sin tocar sus barras y comillas de escape.
    """

    def escape_cloze_syntax(s: str) -> str:
        """Escape Moodle's own Cloze delimiter characters (~ # { } and the
        backslash itself) so a literal occurrence in an option's text isn't
        misread as a syntax separator — e.g. an option like "50~60" would
        otherwise be parsed as two separate options."""
        return (s.replace('\\', '\\\\')
                 .replace('~', '\\~')
                 .replace('#', '\\#')
                 .replace('/', '\\/')
                 .replace('"', '\\"')
                 .replace('{', '\\{')
                 .replace('}', '\\}'))

    key_info = answer_key.get(q_num, {})
    raw_key_ans = str(key_info.get("answer", ""))

    # Respuestas por hueco ("A. respuesta A; B. respuesta B"). Un hueco puede
    # tener MÁS DE UNA respuesta correcta, unidas con " | " (así marca el
    # editor de la app un hueco de "seleccionar varias"); un hueco normal es
    # una lista de un elemento. Misma función que usa el validador.
    brackets_all = find_cloze_brackets(cloze_text)
    slot_answers = clave_de_huecos(raw_key_ans, len(brackets_all), brackets_all[0][2] if brackets_all else "")

    # Moodle IGNORA el <defaultgrade> de una pregunta de completar: su nota
    # máxima es la suma de los pesos de sus huecos. Por eso los pesos se
    # reparten para que sumen los puntos de la pregunta (peso_total).
    n_huecos = max(1, len(find_cloze_brackets(cloze_text)))
    pesos = _pesos_cloze(n_huecos, peso_total)
    usados: List[str] = []

    def render_slot(letter: str, options_raw: str) -> Optional[str]:
        """Texto Moodle para UN espacio, o None si no hay opciones (el
        corchete original se deja tal cual, igual que antes)."""
        options = split_options(options_raw)
        if not options:
            return None

        # Cuáles opciones son las correctas de este hueco — normalmente una,
        # pero uno de "seleccionar varias" puede marcar más. Cada respuesta de
        # la clave debe identificar UNA opción (resolver_hueco_cloze, la misma
        # función del validador); si no, no se adivina: antes se marcaba la
        # primera opción («Caracas» con Lima/Quito/Bogotá salía «=Lima»).
        correct_indices: List[int] = []
        for target_ans in slot_answers.get(letter, []):
            target_ans = target_ans.strip()
            if not target_ans:
                continue
            match_idx, motivo = resolver_hueco_cloze(target_ans, options)
            if match_idx is None:
                raise RespuestaNoResuelta(
                    f"Pregunta {q_num} (cloze): la respuesta '{target_ans[:60]}' del espacio [{letter}] "
                    + ("es ambigua: coincide con varias opciones." if motivo == "ambigua"
                       else "no coincide con ninguna de las opciones.")
                )
            if match_idx not in correct_indices:
                correct_indices.append(match_idx)

        if not correct_indices:
            raise RespuestaNoResuelta(
                f"Pregunta {q_num} (cloze): el espacio [{letter}] no tiene una respuesta correcta en la clave."
            )

        def render_option(i: int, opt: str) -> str:
            # NO se le quitan las tildes: eso cambia lo que lee el
            # estudiante ("Perú" se mostraba como "Peru"). Es distinto del
            # strip_accents de más abajo (shortanswer), que solo AGREGA una
            # variante sin tilde a la respuesta — nunca reemplaza el texto
            # que ve el estudiante.
            text = escape_cloze_syntax(opt)
            if i in correct_indices:
                return f"={text}"
            # Una opción INCORRECTA cuyo texto empieza por "=" o "%" (el
            # operador "==", "%") se leería como marcador de respuesta
            # correcta / de porcentaje: "%0%" fija explícitamente 0 %
            # (sintaxis %fracción% de la documentación de Moodle).
            return f"%0%{text}" if text[:1] in ("=", "%") else text

        moodle_options = [render_option(i, opt) for i, opt in enumerate(options)]
        # El número antes del tipo ("{N:MULTICHOICE_S:…}") es el PESO de
        # ese hueco en Moodle, no su posición: con A=1, B=2, C=3, D=4 el
        # cuarto hueco valía 4 veces más que el primero. Los huecos pesan
        # igual (o lo más parecido posible: ver _pesos_cloze).
        slot_num = str(pesos[min(len(usados), len(pesos) - 1)])
        usados.append(letter)
        # Un solo "=" -> selección única (MULTICHOICE_S, radio/desplegable).
        # Dos o más -> varias respuestas correctas a la vez (MULTIRESPONSE_S,
        # casillas). Moodle reparte el 100% automáticamente entre las
        # marcadas con "=", no hace falta calcular porcentajes aquí.
        qtype_name = "MULTIRESPONSE_S" if len(correct_indices) > 1 else "MULTICHOICE_S"
        return f"{{{slot_num}:{qtype_name}:{'~'.join(moodle_options)}}}"

    # Reconstruye el texto reemplazando cada espacio por su sintaxis Moodle.
    # No se usa re.sub porque find_cloze_brackets balancea corchetes
    # internos (ver su docstring) — algo que una sola expresión regular no
    # puede hacer.
    out: List[str] = []
    last = 0
    for start, end, letter, options_raw in brackets_all:
        replacement = render_slot(letter.upper(), options_raw.strip())
        hueco = replacement if replacement is not None else cloze_text[start:end]
        if como_html:
            out.append(_html_fuera_de_huecos(cloze_text[last:start], last == 0))
            out.append(html.escape(_sin_control(hueco), quote=False))
        else:
            out.append(cloze_text[last:start])
            out.append(hueco)
        last = end
    if como_html:
        out.append(_html_fuera_de_huecos(cloze_text[last:], last == 0))
    else:
        out.append(cloze_text[last:])
    return "".join(out)




def _questiontext(html_text: str, data: dict, name: str) -> List[str]:
    """<questiontext> con sus imágenes y, si la hay, la retroalimentación
    general. Las imágenes van como las exporta el propio Moodle: <img
    src="@@PLUGINFILE@@/nombre"> en el texto y el archivo en base64 dentro
    de <questiontext> (<file ... encoding="base64">). Sus nombres y
    contenido ya vienen validados (validator.py → imagenes.errores_imagenes)."""
    imagenes = data.get("images") or []
    html_imgs = "".join(
        f'<p><img src="@@PLUGINFILE@@/{im["name"]}" alt="{esc("Imagen de " + name)}"></p>' for im in imagenes
    )
    lines = ['    <questiontext format="html">',
             f'      <text>{cdata(html_text + html_imgs)}</text>']
    lines += [f'      <file name="{im["name"]}" path="/" encoding="base64">{im["b64"]}</file>' for im in imagenes]
    lines.append('    </questiontext>')
    # Retroalimentación OPCIONAL: solo si el docente la dejó (o venía en el
    # documento). Moodle la muestra al estudiante después de responder.
    feedback = str(data.get("feedback") or "").strip()
    if feedback:
        lines.append('    <generalfeedback format="html">')
        lines.append(f'      <text>{cdata("<p>" + texto_html(feedback) + "</p>")}</text>')
        lines.append('    </generalfeedback>')
    return lines

def _avisar_puntos_cloze(stats: QuestionStats, num: int, raw_text: str, grade_val: float) -> None:
    """Avisa (sin bloquear) cuando una pregunta de «Completar» valdrá en
    Moodle distinto que en el editor. Moodle ignora <defaultgrade> y suma los
    pesos ENTEROS de los huecos, con mínimo 1 por hueco (_pesos_cloze): con 0
    puntos vale igual «n huecos», y con menos puntos que huecos también sube.
    No hay forma de expresar un peso 0 (Moodle lo toma como «sin peso» = 1),
    así que se deja el comportamiento y se informa."""
    huecos = max(1, len(find_cloze_brackets(raw_text)))
    en_moodle = sum(_pesos_cloze(huecos, round(grade_val) if grade_val > 0 else None))
    if abs(en_moodle - grade_val) <= 0.06 * grade_val and grade_val > 0:
        return
    aviso = (
        f"La pregunta {num} (Completar) tiene {grade_val:g} punto(s) en el editor, pero Moodle le dará "
        f"{en_moodle} ({huecos} hueco(s), mínimo 1 punto por hueco): el total del examen en Moodle "
        f"será distinto al del editor. Ajusta los puntos al importar."
    )
    stats.avisos.append(aviso)
    logger.warning(aviso)


# Moodle usa "/" para separar categoría y subcategoría: un "/" en el nombre
# ("Parcial 1/2 2026") creaba subcategorías sin que el docente lo pidiera. El
# campo de la interfaz es un NOMBRE (sin jerarquía documentada), así que cada
# "/" pasa a "-". Se recortan espacios, se descartan caracteres de control y se
# acota la longitud (Moodle guarda hasta 255).
CATEGORIA_MAX = 200
CATEGORIA_POR_DEFECTO = "mis-preguntas"


def sanear_categoria(categoria: str) -> str:
    nombre = _sin_control(str(categoria or "")).replace("/", "-")
    nombre = " ".join(nombre.split())[:CATEGORIA_MAX].strip()
    return nombre or CATEGORIA_POR_DEFECTO


def build_xml(
    questions: List[dict],
    answer_key: Dict[int, dict],
    category: str = "mis-preguntas",
    grades: Optional[Dict[str, float]] = None,
) -> tuple[str, QuestionStats]:
    """
    Generate the full Moodle XML string from the list of parsed questions.

    The output conforms to the Moodle XML Question Format:
      - <?xml version="1.0" encoding="UTF-8"?> header
      - <quiz> root element
      - Category header as dummy <question type="category">
      - Each question with required tags: <name>, <questiontext>, <defaultgrade>
      - CDATA sections for all HTML content

    Args:
        grades: dict mapping question type → defaultgrade value.
                If None, defaults to 1.0 for all types.
    Returns:
        (xml_string, QuestionStats)
    """
    if grades is None:
        grades = {t: 1.0 for t in TYPE_WEIGHTS}
    stats = QuestionStats()
    category = sanear_categoria(category)
    escala, notas_finales = _plan_puntos(questions, grades)
    stats.escala = escala
    xml_parts: List[str] = []
    xml_parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    xml_parts.append('<quiz>')

    # Category header (spec: dummy question with type="category")
    xml_parts.append('  <question type="category">')
    xml_parts.append(f'    <category><text>$course$/{esc(category)}</text></category>')
    xml_parts.append('  </question>')

    # El banco de preguntas de Moodle no conserva el orden del archivo al
    # importar — a menudo re-lista las preguntas ordenadas alfabéticamente
    # por nombre. Sin relleno de ceros, "P10" y "P11" ordenan alfabéticamente
    # ANTES que "P2" (comportamiento documentado y muy reportado por
    # profesores). Rellenar con ceros según la cantidad de preguntas del
    # examen (P01, P02... P10) hace que el orden alfabético coincida con el
    # numérico sin importar cuántas preguntas tenga el examen.
    name_width = len(str(max((q["num"] for q in questions), default=1)))

    for q in questions:
        num: int = q["num"]
        qtype: str = q["type"]
        data: dict = q["data"]
        key_info = answer_key.get(num, {})
        correct_answer: str = key_info.get("answer", "")
        name = f"P{num:0{name_width}d}"

        # Puntaje: el docente puede fijar un valor propio por pregunta desde
        # el editor (ya no todas las preguntas de un tipo valen lo mismo a
        # la fuerza — necesario sobre todo para Ensayo/Respuesta Corta,
        # donde el peso "genérico por tipo" no tiene forma de acertar).
        # Si no llega (payload viejo o pregunta sin tocar), cae al reparto
        # por peso de tipo de siempre — nunca falta un <defaultgrade>.
        # OJO con el `>= 0`: un docente puede poner a propósito un tipo en
        # peso 0 desde "Distribuir puntos" (esas preguntas quedan en 0 pts).
        # Con `> 0` ese 0 se descartaba como "no vino puntaje" y el XML
        # terminaba dándoles el puntaje por peso de tipo — lo contrario de
        # lo que el editor mostraba en pantalla.
        # _nota_de descarta Infinity/NaN (Infinity pasaba "q_points >= 0" y
        # quedaba como <defaultgrade>inf</defaultgrade> en el XML).
        grade_val = notas_finales[id(q)]

        # ── multichoice ──
        # Spec: <answer fraction="100"/"0"> for each choice, <single>, <shuffleanswers>
        if qtype == "multichoice":
            stem = data["stem"]
            options: Dict[str, str] = data["options"]

            # correct_answer puede listar MÁS DE UNA respuesta correcta,
            # separadas por " | " (pregunta de "selecciona todas las que
            # correspondan"). El caso normal de una sola respuesta es
            # simplemente una lista de un elemento, así que el comportamiento
            # de siempre queda intacto.
            # Cada respuesta debe identificar UNA opción (resolver_opcion, la
            # misma función del validador: texto igual > letra > texto sin
            # tildes > subcadena única > respuesta cortada única). Si no, no
            # se adivina: antes se marcaba la «A» en silencio, y con la clave
            # «Python» y las opciones «Java / Python 2 / Python 3» salía Java.
            correct_letters: List[str] = []
            for target in split_answers(correct_answer):
                match_letter, motivo = resolver_opcion(target, options)
                if match_letter is None:
                    raise RespuestaNoResuelta(
                        f"Pregunta {num} (multichoice): la respuesta '{target[:60]}' "
                        + ("es ambigua: coincide con varias opciones." if motivo == "ambigua"
                           else "no coincide con ninguna de las opciones.")
                    )
                if match_letter not in correct_letters:
                    correct_letters.append(match_letter)

            if not correct_letters:
                raise RespuestaNoResuelta(f"Pregunta {num} (multichoice): no hay respuesta correcta en la clave.")

            is_single = len(correct_letters) == 1

            xml_parts.append('  <question type="multichoice">')
            xml_parts.append(f'    <name><text>{esc(name)}</text></name>')
            xml_parts.extend(_questiontext(f"<p>{texto_html(stem)}</p>", data, name))
            xml_parts.append(f'    <defaultgrade>{grade_val}</defaultgrade>')
            xml_parts.append(f'    <penalty>{MULTICHOICE_PENALTY}</penalty>')
            xml_parts.append('    <shuffleanswers>1</shuffleanswers>')
            xml_parts.append(f'    <single>{"true" if is_single else "false"}</single>')
            xml_parts.append('    <answernumbering>abc</answernumbering>')

            # Con varias respuestas correctas, Moodle sólo suma el puntaje
            # total si los fraction positivos de las correctas suman 100 —
            # se reparte parejo entre ellas (2 correctas -> 50% c/u, etc.),
            # igual que ya hacemos para "varias respuestas" en Cloze.
            correct_fraction = round(100.0 / len(correct_letters), 5) if not is_single else 100

            # "Selecciona todas las que correspondan" (is_single=False): las
            # incorrectas necesitan una fracción NEGATIVA, no 0 — con 0, un
            # estudiante que marca TODAS las opciones (correctas e
            # incorrectas) igual suma el 100% de las correctas y se lleva la
            # nota completa sin haber discriminado nada. Es la propia
            # recomendación de Moodle ("Multiple Choice question type"):
            # repartir -100% entre las incorrectas para que marcarlas TODAS
            # cancele exactamente el 100% de las correctas. Con una sola
            # respuesta correcta (radio, is_single=True) esto no aplica: el
            # estudiante solo puede marcar una opción a la vez, así que 0%
            # en las demás ya es el comportamiento estándar y correcto.
            incorrect_count = len(options) - len(correct_letters)
            incorrect_fraction = round(-100.0 / incorrect_count, 5) if (not is_single and incorrect_count) else 0

            # Iterar dinámicamente sobre las opciones encontradas (no limitado a
            # A-D): una pregunta con opción E o más ya no se descarta en silencio.
            for letter in sorted(options.keys()):
                is_correct = letter in correct_letters
                fraction = correct_fraction if is_correct else incorrect_fraction
                feedback = FEEDBACK_CORRECT if is_correct else FEEDBACK_INCORRECT
                xml_parts.append(f'    <answer fraction="{fraction}">')
                xml_parts.append(f'      <text>{cdata(esc(options[letter]))}</text>')
                xml_parts.append(f'      <feedback><text>{cdata(feedback)}</text></feedback>')
                xml_parts.append('    </answer>')

            xml_parts.append('  </question>')
            stats.multichoice += 1

        # ── truefalse ──
        # Spec: exactly 2 <answer> tags (true + false), fraction 100/0
        elif qtype == "truefalse":
            stem = data["stem"]
            if correct_answer.strip().lower() not in TRUEFALSE_ALIAS:
                raise RespuestaNoResuelta(
                    f"Pregunta {num} (truefalse): la respuesta '{correct_answer[:40]}' no es Verdadero ni Falso."
                )
            is_true = TRUEFALSE_ALIAS[correct_answer.strip().lower()]

            xml_parts.append('  <question type="truefalse">')
            xml_parts.append(f'    <name><text>{esc(name)}</text></name>')
            xml_parts.extend(_questiontext(f"<p>{texto_html(stem)}</p>", data, name))
            xml_parts.append(f'    <defaultgrade>{grade_val}</defaultgrade>')

            if is_true:
                xml_parts.append('    <answer fraction="100">')
                xml_parts.append('      <text>true</text>')
                xml_parts.append(f'      <feedback><text>{cdata(FEEDBACK_CORRECT)}</text></feedback>')
                xml_parts.append('    </answer>')
                xml_parts.append('    <answer fraction="0">')
                xml_parts.append('      <text>false</text>')
                xml_parts.append(f'      <feedback><text>{cdata(FEEDBACK_INCORRECT)}</text></feedback>')
                xml_parts.append('    </answer>')
            else:
                xml_parts.append('    <answer fraction="0">')
                xml_parts.append('      <text>true</text>')
                xml_parts.append(f'      <feedback><text>{cdata(FEEDBACK_INCORRECT)}</text></feedback>')
                xml_parts.append('    </answer>')
                xml_parts.append('    <answer fraction="100">')
                xml_parts.append('      <text>false</text>')
                xml_parts.append(f'      <feedback><text>{cdata(FEEDBACK_CORRECT)}</text></feedback>')
                xml_parts.append('    </answer>')

            xml_parts.append('  </question>')
            stats.truefalse += 1

        # ── matching ──
        # Spec: <subquestion> with <text> + <answer><text>, <shuffleanswers>
        elif qtype == "matching":
            col_a: Dict[str, str] = data.get("col_a", {})
            col_b: Dict[str, str] = data.get("col_b", {})
            pairs_map: Dict[str, str] = key_info.get("pairs", {})

            pairs_ordered: list[tuple[str, str]] = []
            letras_usadas: set = set()
            a_keys = sorted(col_a.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x))

            # Cada elemento de la Columna A se une a SU pareja de la Columna B
            # según la clave número→letra (no por posición). La letra se busca
            # sin distinguir mayúsculas (clave_de_columna, la misma función del
            # validador). Si la clave falta o no resuelve, NO se inventa el
            # orden secuencial 1-a, 2-b, 3-c…: antes, ante una clave que no
            # resolvía, el XML salía con parejas equivocadas sin avisar.
            if not pairs_map:
                raise RespuestaNoResuelta(f"Pregunta {num} (matching): no hay una clave de respuestas 'número-letra'.")
            for a_k in a_keys:
                letter = clave_de_columna(col_b, pairs_map.get(str(a_k), ""))
                a_val = col_a[a_k].strip()
                if letter is None:
                    raise RespuestaNoResuelta(
                        f"Pregunta {num} (matching): el elemento {a_k} de la Columna A no tiene una "
                        f"pareja válida en la clave (letra '{pairs_map.get(str(a_k), '')}')."
                    )
                b_val = col_b[letter].strip()
                if a_val and b_val:
                    pairs_ordered.append((a_val, b_val))
                    letras_usadas.add(letter)

            # Distractores: elementos de la Columna B que no son la pareja de
            # NINGÚN elemento de la A (el docente puso más opciones que
            # preguntas a propósito, para que no se adivine por descarte).
            # Antes desaparecían del XML sin avisar. Van como subpregunta
            # con el <text> vacío: es la forma estándar de Moodle para un
            # distractor en "emparejamiento" (spec: "an answer with no
            # matching question").
            for letra in sorted(col_b.keys()):
                b_val = col_b[letra].strip()
                if letra not in letras_usadas and b_val:
                    pairs_ordered.append(("", b_val))

            stem = data.get("stem")
            if not stem:
                stem = DEFAULT_MATCHING_STEM

            xml_parts.append('  <question type="matching">')
            xml_parts.append(f'    <name><text>{esc(name)}</text></name>')
            xml_parts.extend(_questiontext(f"<p>{texto_html(stem)}</p>", data, name))
            xml_parts.append(f'    <defaultgrade>{grade_val}</defaultgrade>')
            xml_parts.append('    <shuffleanswers>true</shuffleanswers>')

            for col_a_text, col_b_text in pairs_ordered:
                xml_parts.append('    <subquestion format="html">')
                xml_parts.append(f'      <text>{cdata(esc(col_a_text))}</text>')
                xml_parts.append(f'      <answer><text>{cdata(esc(col_b_text))}</text></answer>')
                xml_parts.append('    </subquestion>')

            xml_parts.append('  </question>')
            stats.matching += 1

        # ── cloze ──
        # Spec: questiontext contains {N:TYPE:...} syntax, no separate <answer> tags
        elif qtype == "cloze":
            raw_text = data["text"]
            cloze_text = convert_cloze_to_moodle(raw_text, num, answer_key,
                                                 peso_total=round(grade_val) if grade_val > 0 else None,
                                                 como_html=True)
            _avisar_puntos_cloze(stats, num, raw_text, grade_val)

            xml_parts.append('  <question type="cloze">')
            xml_parts.append(f'    <name><text>{esc(name)}</text></name>')
            xml_parts.extend(_questiontext(f"<p>{cloze_text}</p>", data, name))
            xml_parts.append(f'    <defaultgrade>{grade_val}</defaultgrade>')
            xml_parts.append('  </question>')
            stats.cloze += 1

        # ── essay ──
        # Spec: sin respuesta real ni grade que calificar — el docente
        # califica manualmente en Moodle.
        elif qtype == "essay":
            stem = data["stem"]

            xml_parts.append('  <question type="essay">')
            xml_parts.append(f'    <name><text>{esc(name)}</text></name>')
            xml_parts.extend(_questiontext(f"<p>{texto_html(stem)}</p>", data, name))
            xml_parts.append(f'    <defaultgrade>{grade_val}</defaultgrade>')
            xml_parts.append('    <answer fraction="0">')
            xml_parts.append('      <text></text>')
            xml_parts.append('    </answer>')
            xml_parts.append('  </question>')
            stats.essay += 1

        # ── shortanswer ──
        # Spec: <answer> con el texto esperado; <usecase>0</usecase> para no
        # exigir coincidencia exacta de mayúsculas/minúsculas.
        elif qtype == "shortanswer":
            stem = data["stem"]

            xml_parts.append('  <question type="shortanswer">')
            xml_parts.append(f'    <name><text>{esc(name)}</text></name>')
            xml_parts.extend(_questiontext(f"<p>{texto_html(stem)}</p>", data, name))
            xml_parts.append(f'    <defaultgrade>{grade_val}</defaultgrade>')
            xml_parts.append('    <usecase>0</usecase>')
            # Un "*" es el comodín de shortanswer en Moodle (coincide con
            # cualquier texto): una respuesta que sea literalmente "*" (o lo
            # contenga) debe escaparse a "\*", si no acepta cualquier cosa.
            respuesta_sa = correct_answer.replace('*', '\\*')
            xml_parts.append('    <answer fraction="100">')
            xml_parts.append(f'      <text>{cdata(esc(respuesta_sa))}</text>')
            xml_parts.append(f'      <feedback><text>{cdata(FEEDBACK_CORRECT)}</text></feedback>')
            xml_parts.append('    </answer>')

            # Moodle NO ignora tildes automáticamente (<usecase> solo afecta
            # mayúsculas/minúsculas) — un estudiante que escriba la misma
            # respuesta sin tilde ("fotosintesis") quedaría marcado como
            # incorrecto frente a "Fotosíntesis". Se agrega la variante sin
            # tildes como segunda respuesta válida, con el mismo puntaje —
            # la forma recomendada por la propia documentación de Moodle
            # para aceptar más de una grafía de la misma respuesta.
            unaccented = strip_accents(respuesta_sa)
            if unaccented != respuesta_sa:
                xml_parts.append('    <answer fraction="100">')
                xml_parts.append(f'      <text>{cdata(esc(unaccented))}</text>')
                xml_parts.append(f'      <feedback><text>{cdata(FEEDBACK_CORRECT)}</text></feedback>')
                xml_parts.append('    </answer>')

            xml_parts.append('  </question>')
            stats.shortanswer += 1

        # ── numerical ──
        # Spec: <answer> con un valor numérico; <tolerance> (0 = coincidencia exacta).
        elif qtype == "numerical":
            stem = data["stem"]

            xml_parts.append('  <question type="numerical">')
            xml_parts.append(f'    <name><text>{esc(name)}</text></name>')
            xml_parts.extend(_questiontext(f"<p>{texto_html(stem)}</p>", data, name))
            xml_parts.append(f'    <defaultgrade>{grade_val}</defaultgrade>')
            # El validador ya acepta "3,5" (coma decimal, común al copiar un
            # documento en español) convirtiéndola a "3.5" para comprobar que
            # es un número — pero aquí se escribía tal cual ("3,5") en el
            # XML, y Moodle no entiende la coma como separador decimal.
            valor_numerico = normalizar_numero(correct_answer)
            if valor_numerico is None:
                raise RespuestaNoResuelta(
                    f"Pregunta {num} (numerical): la respuesta '{correct_answer[:40]}' no es un número válido."
                )
            xml_parts.append('    <answer fraction="100">')
            xml_parts.append(f'      <text>{esc(valor_numerico)}</text>')
            xml_parts.append('      <tolerance>0</tolerance>')
            xml_parts.append(f'      <feedback><text>{cdata(FEEDBACK_CORRECT)}</text></feedback>')
            xml_parts.append('    </answer>')
            xml_parts.append('  </question>')
            stats.numerical += 1

    xml_parts.append('</quiz>')
    return "\n".join(xml_parts), stats
