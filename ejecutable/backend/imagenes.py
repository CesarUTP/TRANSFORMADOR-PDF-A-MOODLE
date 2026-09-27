"""
imagenes.py — las imágenes del examen llegan a Moodle dentro de su pregunta.

La IA lee las imágenes (código en captura, gráficos), pero antes la pregunta
llegaba a Moodle sin ellas. Aquí, en código y sin IA:

  1. Del documento se toman sus líneas de texto y sus imágenes, cada una con
     su POSICIÓN (PDF: página y altura; Word: n.º de párrafo).
  2. Después de la IA, se ubica en esas líneas dónde EMPIEZA cada pregunta:
     con el enunciado que devolvió la IA (así se encuentran también las
     preguntas sin número) o, si no se puede, por su número entre las
     vecinas ya ubicadas.
  3. Cada imagen va a:
       - la pregunta que empieza en su MISMO renglón (un Word exportado a
         PDF pone la imagen en el párrafo de la pregunta: "9. [imagen] ¿qué
         tipo de error es?", con el número alineado con la imagen), o
       - si no, a una de sus dos vecinas: la de ARRIBA o la de ABAJO. La
         cercanía sola no basta (en el parcial de Computación el código
         está en un punto «14.» vacío y es de «15. Cuántos errores tiene el
         código», la de abajo; el de la 17 es de «17. Del siguiente
         código…», la de arriba). Decide el enunciado:
           a) "el siguiente código", "a continuación" miran hacia ABAJO: la
              imagen es de la pregunta de arriba;
           b) si la de arriba no habla de ningún código/imagen/figura y la
              de abajo sí (y empieza pegada a la imagen), es de la de abajo;
           c) si nada decide, la de arriba (el orden habitual: enunciado y
              luego su imagen).
         (Se probó pedirle a la IA una marca «usa_imagen» por pregunta: la
         ponía en casi todas las de una página con imágenes, y empeoraba.)
     El docente puede moverla a la pregunta anterior o siguiente en el
     editor si aun así queda mal.
  3b. Preguntas ENCADENADAS: "15. ¿Cuántos errores tiene el código? / 6 /
     Escribe cuáles son los errores" son dos preguntas sobre la MISMA
     imagen. La que viene justo después de una pregunta con imagen, sin
     imagen propia, recibe una copia si la IA dice que es la misma
     (comparte_imagen_anterior) o, sin esa marca, si habla de «el código», «la imagen»…
     y empieza a pocas líneas. Como mucho _MAX_CADENA seguidas.
  3c. Preguntas que la IA OMITIÓ: una imagen sin dueño cuyo texto de
     arriba es un enunciado que ninguna pregunta usó («17. Del siguiente
     código cuál sería el resultado») se devuelve como pregunta omitida,
     con su imagen, para rescatarla con un clic en el editor (pasó en 3 de
     4 conversiones reales del parcial de Computación).
  4. Se guardan reducidas y en base64 en data["images"]; el editor las
     muestra (se pueden quitar) y xml_builder las incrusta con <file
     encoding="base64"> y @@PLUGINFILE@@, como las exporta Moodle.

Se ubican TODAS las preguntas (también las que luego se omiten): así la
imagen de una pregunta omitida no termina pegada a la anterior. Una imagen
sin pregunta que le corresponda con certeza se descarta.
"""

import base64
import io
import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pdfplumber
from PIL import Image

from extractor import MAX_PAGINAS, MAX_PIXELES_RENDER

logger = logging.getLogger(__name__)

MAX_IMAGENES = 30             # por documento
MAX_POR_PREGUNTA = 5
LADO_MAX = 1000               # px del lado mayor al guardarla
MAX_BYTES_PNG = 350 * 1024    # por encima, se guarda como JPEG
MAX_BYTES_IMAGEN = 2 * 1024 * 1024
NOMBRE_VALIDO = re.compile(r"^[A-Za-z0-9_-]{1,60}\.(png|jpg)$")
MIMES = {"png": "image/png", "jpg": "image/jpeg"}
_B64 = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
# Una línea que abre una pregunta numerada: "12.", "12)", "Pregunta 12".
_NUMERADA = re.compile(r"^\s*(?:pregunta\s*)?(\d{1,3})\s*[.):-]", re.IGNORECASE)
_LETRA_LISTA = re.compile(r"^\s*[a-zA-Z]\s*[.):-]")  # "a.", "b)": columna de un emparejamiento
# Un número suelto ("14."): la numeración de Word puso una imagen en su
# propio punto de la lista.
_SOLO_NUMERO = re.compile(r"^\s*\d{1,3}\s*[.)]?\s*$")

Posicion = Tuple[float, ...]   # PDF: (página, altura); Word: (n.º de párrafo,)


@dataclass
class Linea:
    pos: Posicion
    texto: str


@dataclass
class ImagenUbicada:
    """Una imagen y la franja que ocupa: `inicio`–`fin` en las mismas
    coordenadas que las líneas (una línea dentro de la franja está en el
    mismo renglón que la imagen)."""
    imagen: Image.Image
    inicio: Posicion
    fin: Posicion


@dataclass
class Ubicaciones:
    lineas: List[Linea] = field(default_factory=list)
    imagenes: List[ImagenUbicada] = field(default_factory=list)


# ── Extracción desde PDF ───────────────────────────────────────────────────

def extraer_imagenes_pdf(raw: bytes) -> Ubicaciones:
    """Líneas de texto e imágenes del PDF con su posición. Se descartan:
    páginas escaneadas (una imagen del tamaño de la hoja), imágenes
    diminutas y las que se repiten en la misma posición en varias páginas
    (logos, encabezados)."""
    from pdfplumber.utils import cluster_objects

    ub = Ubicaciones()
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        paginas = pdf.pages[:MAX_PAGINAS]
        repetidas = Counter(
            (round(im["x0"]), round(im["top"]), round(im["width"]), round(im["height"]))
            for p in paginas for im in p.images
        )
        for n, page in enumerate(paginas, 1):
            for l in cluster_objects(page.extract_words(), "top", tolerance=3):
                palabras = sorted(l, key=lambda w: w["x0"])
                ub.lineas.append(Linea((n, min(w["top"] for w in l)), " ".join(w["text"] for w in palabras)))
            for im in sorted(page.images, key=lambda i: i["top"]):
                if len(ub.imagenes) >= MAX_IMAGENES:
                    break
                ancho, alto = im["width"], im["height"]
                if ancho > page.width * 0.85 and alto > page.height * 0.85:
                    continue  # página escaneada
                if ancho < 40 or alto < 20:
                    continue  # viñeta, ícono
                if repetidas[(round(im["x0"]), round(im["top"]), round(ancho), round(alto))] > 1 and len(paginas) > 1:
                    continue  # logo o encabezado repetido
                caja = (max(0, im["x0"]), max(0, im["top"]), min(page.width, im["x1"]), min(page.height, im["bottom"]))
                ancho_pt, alto_pt = caja[2] - caja[0], caja[3] - caja[1]
                if ancho_pt <= 0 or alto_pt <= 0:
                    continue
                # DPI fija (150) sin límite: una página con un MediaBox
                # gigante (visto: 5000 pt) e imágenes estiradas produce un
                # recorte de más de 100 millones de píxeles y ~500 MB por
                # imagen. Se limita como en extractor._render (misma
                # fórmula) para acotar el tamaño real, no el DPI nominal.
                dpi_recorte = 150
                if ancho_pt * alto_pt * (dpi_recorte / 72) ** 2 > MAX_PIXELES_RENDER:
                    dpi_recorte = max(1, int(72 * (MAX_PIXELES_RENDER / (ancho_pt * alto_pt)) ** 0.5))
                try:
                    recorte = page.crop(caja).to_image(resolution=dpi_recorte).original
                except Exception:  # noqa: BLE001 — una imagen que no se puede recortar se omite
                    continue
                # Margen de 4 pt: el número de la pregunta se alinea con el
                # borde inferior de una imagen en el mismo renglón.
                ub.imagenes.append(ImagenUbicada(recorte, (n, im["top"] - 4), (n, im["bottom"] + 4)))
    ub.lineas.sort(key=lambda l: l.pos)
    return ub


# ── Ubicar preguntas y asignar imágenes ────────────────────────────────────

def _normalizar(texto: str) -> str:
    t = re.sub(r"⟦/?[^⟧]*⟧", "", texto or "")
    t = re.sub(r"\\\(.*?\\\)", " ", t)                       # fórmulas LaTeX
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"^\s*(?:pregunta\s*)?\d{1,3}\s*[.):-]?\s*", "", t)  # "12." / "Pregunta 12:"
    t = " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())
    # "… imprime 17 ( ) Verdadero ( ) Falso": las opciones de un V/F suelen
    # venir en la misma línea del enunciado y no son parte de él.
    return re.sub(r"\s+(?:verdadero|cierto|v)\s+(?:falso|f)$", "", t)


def _empieza(linea: str, enunciado: str) -> bool:
    """Coincidencia fuerte: la línea es el COMIENZO del enunciado (por
    palabras completas: "imprime 3" no es el comienzo de "imprime 30"), o
    el enunciado entero más algo que trae la línea (opciones en la misma
    línea)."""
    if len(linea) < 8 or not enunciado:
        return False
    if (enunciado == linea or enunciado.startswith(linea + " ")
            or (len(enunciado) >= 20 and linea.startswith(enunciado + " "))):
        return True
    # Tolerante a errores menores: la IA corrige la ortografía del documento
    # («coreponda» → «corresponda») y la coincidencia exacta fallaba. Solo
    # con líneas largas y casi idénticas al comienzo del enunciado.
    if len(linea) >= 20:
        inicio = enunciado[:len(linea) + 3]
        return SequenceMatcher(None, linea, inicio, autojunk=False).ratio() >= 0.92
    return False


def _aparece(linea: str, enunciado: str) -> bool:
    """Coincidencia débil: la línea está al final o dentro del enunciado (la
    IA puso delante el código que transcribió de una imagen: "Ejemplo:
    print(…) ¿qué tipo de error es?"). Solo se usa con líneas numeradas."""
    if len(linea) < 12 or not enunciado:
        return False
    return enunciado.endswith(" " + linea) or (len(linea) >= 25 and f" {linea} " in f" {enunciado} ")


def _sin_prefijo_transcrito(enunciado: str, linea_doc: str) -> Optional[str]:
    """Si el enunciado trae, delante de la pregunta real del documento, el
    código que la IA transcribió de una imagen (REGLA 9: "Ejemplo:
    print(…) ¿qué tipo de error es?" cuando el documento solo trae "15.
    ¿Qué tipo de error es?"), devuelve el enunciado SIN ese prefijo — la
    imagen que se le acaba de adjuntar ya muestra ese código, no hace
    falta repetirlo en texto. Verifica la coincidencia palabra por palabra
    (no solo por longitud) para no cortar mal un enunciado que en verdad
    solo se PARECE al final; si algo no cuadra, devuelve None y se deja el
    enunciado tal como vino (mejor una duplicación que un enunciado roto)."""
    enunciado_norm = _normalizar(enunciado)
    linea_norm = _normalizar(linea_doc)
    palabras_linea = linea_norm.split()
    if len(linea_norm) < 12 or not palabras_linea or enunciado_norm == linea_norm:
        return None
    if not enunciado_norm.endswith(" " + linea_norm):
        return None
    palabras_enun = list(re.finditer(r"\S+", enunciado))
    if len(palabras_enun) < len(palabras_linea):
        return None
    cola = palabras_enun[-len(palabras_linea):]
    for span, esperada in zip(cola, palabras_linea):
        if _normalizar(span.group()) != esperada:
            return None
    return enunciado[cola[0].start():].strip()


def _quitar_transcripciones_redundantes(questions: List[Dict[str, Any]], lineas: List[Linea],
                                        inicios: List[Optional[int]]) -> None:
    """Recorre las preguntas que acaban de recibir una imagen y, si su
    enunciado trae delante el código transcrito de esa misma imagen (ver
    _sin_prefijo_transcrito), lo quita: la imagen ya lo muestra."""
    for q, k in zip(questions, inicios):
        if k is None:
            continue
        d = q.get("data") or {}
        if not d.get("images"):
            continue
        for campo in ("stem", "text"):
            if d.get(campo):
                limpio = _sin_prefijo_transcrito(d[campo], lineas[k].texto)
                if limpio:
                    d[campo] = limpio
                break


# Cuántas líneas hacia adelante se busca el inicio de la siguiente pregunta:
# evita que un enunciado se "encuentre" en una opción de otra página.
_VENTANA = 60


def _ubicar_preguntas(questions: List[Dict[str, Any]], lineas: List[Linea],
                     imagenes: Sequence["ImagenUbicada"] = ()) -> List[Optional[int]]:
    """Índice (en `lineas`) donde empieza cada pregunta, en orden, o None."""
    norm = [_normalizar(l.texto) for l in lineas]
    # Un número suelto en el renglón de una imagen y seguido directamente
    # por otro número («14.» al pie de una captura y luego «15. ¿Cuántos
    # errores…?») es un punto de lista que solo contiene la imagen, no el
    # comienzo de una pregunta. «10.» + imagen + sus opciones sí lo es.
    en_imagen = {k for k, l in enumerate(lineas) if _SOLO_NUMERO.match(l.texto)
                 and any(im.inicio <= l.pos <= im.fin for im in imagenes)
                 and (k + 1 >= len(lineas) or _NUMERADA.match(lineas[k + 1].texto))}
    numeros = [(int(m.group(1)) if (m := _NUMERADA.match(l.texto)) else None) for l in lineas]
    inicio: List[Optional[int]] = []
    cursor = 0
    for q in questions:
        enunciado = _normalizar(q["data"].get("stem") or q["data"].get("text") or "")
        rango = range(cursor, min(len(lineas), cursor + _VENTANA))
        k = next((k for k in rango if _empieza(norm[k], enunciado)), None)
        if k is None:
            k = next((k for k in rango if numeros[k] is not None and _aparece(norm[k], enunciado)), None)
        inicio.append(k)
        if k is not None:
            cursor = k + 1
    # Preguntas que no se ubicaron por su texto (ej. "10." seguido solo de
    # una imagen): si entre sus vecinas ubicadas hay tantas líneas numeradas
    # como preguntas sin ubicar, se asignan en orden.
    i = 0
    while i < len(inicio):
        if inicio[i] is not None:
            i += 1
            continue
        fin = i
        while fin < len(inicio) and inicio[fin] is None:
            fin += 1
        desde = (inicio[i - 1] + 1) if i > 0 else 0
        hasta = inicio[fin] if fin < len(inicio) else len(lineas)
        numeradas = [x for x in range(desde, hasta) if numeros[x] is not None and x not in en_imagen]
        if len(numeradas) == fin - i:
            inicio[i:fin] = numeradas
        i = fin
    return inicio


def codificar(img: Image.Image) -> Dict[str, str]:
    """Reduce la imagen (lado mayor ≤ LADO_MAX) y la devuelve en base64:
    PNG si es liviana (capturas de código, diagramas), si no JPEG."""
    img = img.copy()
    if img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGBA")
    img.thumbnail((LADO_MAX, LADO_MAX))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    ext = "png"
    if buf.tell() > MAX_BYTES_PNG:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=85, optimize=True)
        ext = "jpg"
    return {"ext": ext, "b64": base64.b64encode(buf.getvalue()).decode("ascii")}


def _es_de_otra(lineas: List[Linea], desde: Posicion, hasta: Posicion, q: Dict[str, Any], inicios: set) -> bool:
    opciones = {_normalizar(o) for o in (q["data"].get("options") or {}).values()} - {""}
    for l in lineas:
        if desde < l.pos < hasta:
            if _NUMERADA.match(l.texto) and l.pos not in inicios:
                return True
            if opciones and _normalizar(l.texto) in opciones:
                return True
    return False


_OBJETO = r"(?:c[oó]digos?|programas?|imag[eé]n(?:es)?|figuras?|diagramas?|gr[aá]fic[oa]s?|capturas?|scripts?|fragmentos?|pseudoc[oó]digo|ejemplos?)"
_ADELANTE = re.compile(r"\b(?:siguientes?\s+(?:\w+\s+){0,2}" + _OBJETO + r"|" + _OBJETO + r"\s+(?:\w+\s+){0,1}siguientes?"
                       r"|a\s+continuaci[oó]n|(?:de|m[aá]s)\s+abajo)\b", re.I)
_MENCION = re.compile(r"\b" + _OBJETO + r"\b", re.I)


def _enunciado(q: Dict[str, Any]) -> str:
    d = q.get("data") or {}
    return str(d.get("stem") or d.get("text") or "")


def _mira_adelante(q: Dict[str, Any]) -> bool:
    """"Del siguiente código…", "…a continuación": su imagen viene DESPUÉS."""
    return bool(_ADELANTE.search(_enunciado(q)))


def _menciona(q: Dict[str, Any]) -> bool:
    """Habla de un código, programa, imagen, figura…"""
    return bool(_MENCION.search(_enunciado(q)))


def _pegada(lineas: List[Linea], fin: Posicion, inicio_q: Posicion) -> bool:
    """La pregunta empieza justo debajo de la imagen: entre ambas solo hay,
    como mucho, un número suelto."""
    return not any(fin < l.pos < inicio_q and not _SOLO_NUMERO.match(l.texto) for l in lineas)


def _elegir(arriba: Dict[str, Any], abajo: Dict[str, Any]) -> Dict[str, Any]:
    """Entre las dos vecinas posibles, de quién es la imagen (ver el
    docstring del módulo: a, b, c)."""
    if _mira_adelante(arriba):
        return arriba
    # «Rellenar el cuadro…» arriba y «¿Cuántos errores tiene el código?»
    # abajo: solo la de abajo habla de algo que se muestra.
    if _menciona(abajo) and not _menciona(arriba):
        return abajo
    return arriba


# «el código», «este programa», «dicha imagen»: algo que ya se mostró.
_YA_MOSTRADO = re.compile(r"\b(?:el|la|los|las|este|esta|estos|ese|esa|dicho|dicha|del|al)\s+" + _OBJETO + r"\b", re.I)
MOTIVO_OMITIDA = ("La IA no incluyó esta pregunta, que en el documento tiene una imagen. "
                  "Revísala: si corresponde, agrégala con su imagen (como pregunta de ensayo).")
_MAX_CADENA = 3       # preguntas seguidas que comparten una imagen
_CERCA_LINEAS = 8     # sin marca de la IA: la siguiente empieza a ≤ 8 líneas


def _compartir(questions: List[Dict[str, Any]], inicios: List[Optional[int]]) -> int:
    """Copia la imagen a las preguntas encadenadas (ver 3b del docstring)."""
    copias = 0
    cadena = 0
    for k in range(1, len(questions)):
        q, prev = questions[k], questions[k - 1]
        d, dp = q["data"], prev["data"]
        if d.get("images") or not dp.get("images"):
            cadena = 0
            continue
        # La marca de la IA (comparte_imagen_anterior): en pruebas reales la
        # pone solo en la pregunta encadenada.
        ia = d.get("_comparte_imagen")
        if ia is None:
            cerca = (inicios[k] is not None and inicios[k - 1] is not None
                     and 0 < inicios[k] - inicios[k - 1] <= _CERCA_LINEAS)
            if not (cerca and _YA_MOSTRADO.search(_enunciado(q)) and not _mira_adelante(q)):
                cadena = 0
                continue
        elif not ia:
            cadena = 0
            continue
        if cadena >= _MAX_CADENA:
            continue
        d["images"] = [{**im, "name": f"pregunta{q['num']}-{n}.{im['name'].rsplit('.', 1)[1]}"}
                       for n, im in enumerate(dp["images"][:MAX_POR_PREGUNTA], 1)]
        cadena += 1
        copias += 1
    return copias


def _enunciado_omitido(lineas: List[Linea], img: ImagenUbicada, ubicadas, questions) -> Optional[Tuple[str, Optional[int]]]:
    """El enunciado de una pregunta que la IA no devolvió, justo encima de
    una imagen sin dueño, y el número de la pregunta que la precede."""
    arriba = [(pos, q) for pos, _, q in ubicadas if pos < img.inicio]
    desde = arriba[-1][0] if arriba else (img.inicio[0],) + (0.0,) * (len(img.inicio) - 1)
    previa = arriba[-1][1] if arriba else None
    usados = set()
    if previa:
        d = previa["data"]
        usados = {_normalizar(o) for o in (d.get("options") or {}).values()}
        usados |= {_normalizar(v) for k in ("col_a", "col_b") for v in (d.get(k) or {}).values()}
    enunciado_previo = _normalizar(_enunciado(previa)) if previa else ""
    bloque: List[str] = []
    for l in reversed([l for l in lineas if desde < l.pos < img.inicio]):
        n = _normalizar(l.texto)
        if not n or n in usados or (enunciado_previo and n in enunciado_previo):
            break
        bloque.insert(0, l.texto.strip())
        if _NUMERADA.match(l.texto) or len(bloque) >= 4:
            break
    texto = re.sub(r"^\s*(?:pregunta\s*)?\d{1,3}\s*[.):-]\s*", "", " ".join(bloque), flags=re.I).strip()
    texto = re.sub(r"⟦/?[^⟧]*⟧", "", texto)
    if len(_normalizar(texto)) < 12:
        return None
    ya = {_normalizar(_enunciado(q)) for q in questions}
    if any(_normalizar(texto) in e for e in ya if e):
        return None
    return texto, (previa["num"] if previa else None)


def candidatas_omitidas_numeradas(questions: List[Dict[str, Any]], ub: Ubicaciones,
                                  max_candidatas: int = 8) -> List[Dict[str, Any]]:
    """
    Líneas numeradas del documento ("17.", "23)") que NINGUNA pregunta
    devuelta por la IA reclama como su propio inicio: casi siempre es una
    pregunta que la IA se saltó entera (visto en la práctica: ~3 de cada 4
    conversiones del parcial de Computación omitían una o dos, casi
    siempre "17. Del siguiente código…" o una encadenada sin número).

    Se usa para pedirle a la IA, en una sola llamada pequeña y dirigida,
    SOLO esas preguntas — ver pipeline._completar_omitidas. Si no hay
    ninguna, o hay más de `max_candidatas` (señal de que algo más general
    salió mal, no de un par de omisiones puntuales), no vale la pena
    intentarlo: se deja como estaba, para que el aviso de "preguntas no
    incluidas" del editor sea la red de seguridad de siempre.

    Cada candidata trae su texto (sin el número ni las marcas ⟦⟧) y el
    número de la pregunta que la precede entre las ya ubicadas (None si
    es la primera del documento), para insertarla en su lugar.
    """
    inicios = _ubicar_preguntas(questions, ub.lineas)
    ubicadas = sorted(((ub.lineas[k].pos, n, q) for n, (q, k) in enumerate(zip(questions, inicios)) if k is not None),
                      key=lambda t: (t[0], t[1]))
    reclamadas = {pos for pos, _, _ in ubicadas}
    ya = {_normalizar(_enunciado(q)) for q in questions} - {""}

    def _opciones(q: Dict[str, Any]) -> set:
        """Normaliza todas las opciones/columnas de una pregunta, para
        distinguir "esta línea numerada es una pregunta nueva" de "esta
        línea numerada es, por casualidad, una de las opciones de la
        pregunta anterior" (visto: un Word que numera sus listas sin
        distinguir pregunta de opción — "1. ¿...?" seguido de "2. Entero
        (int)" — deja la primera opción con el número de una "pregunta 2"
        que en realidad no existe)."""
        d = q.get("data") or {}
        vals = list((d.get("options") or {}).values())
        vals += list((d.get("col_a") or {}).values()) + list((d.get("col_b") or {}).values())
        return {_normalizar(v) for v in vals} - {""}

    candidatas: List[Dict[str, Any]] = []
    n = len(ub.lineas)
    i = 0
    while i < n:
        linea = ub.lineas[i]
        if linea.pos in reclamadas or not _NUMERADA.match(linea.texto):
            i += 1
            continue
        anterior = [(pos, q) for pos, _, q in ubicadas if pos < linea.pos]
        opciones_anterior = _opciones(anterior[-1][1]) if anterior else set()
        primera_linea = _normalizar(_NUMERADA.sub("", linea.texto, count=1))
        if primera_linea and primera_linea in opciones_anterior:
            i += 1
            continue
        # El bloque de esta candidata llega hasta la siguiente línea ya
        # reclamada, hasta otra línea numerada, hasta una lista con letras
        # ("a.", "b.": casi siempre columna de un emparejamiento cercano,
        # no continuación de esta candidata) o hasta que aparezca una línea
        # que YA es una opción de otra pregunta (mismo caso que arriba, pero
        # más adelante en el bloque) — lo que venga primero. Tope corto: un
        # bloque real rara vez pasa de unas pocas líneas.
        fin = i + 1
        tope = min(n, i + 8)
        while (fin < tope and ub.lineas[fin].pos not in reclamadas
               and not _NUMERADA.match(ub.lineas[fin].texto)
               and not _LETRA_LISTA.match(ub.lineas[fin].texto)
               and _normalizar(ub.lineas[fin].texto) not in opciones_anterior):
            fin += 1
        bloque = " ".join(x.texto.strip() for x in ub.lineas[i:fin])
        texto = re.sub(r"^\s*(?:pregunta\s*)?\d{1,3}\s*[.):-]\s*", "", bloque, flags=re.I).strip()
        texto = re.sub(r"⟦/?[^⟧]*⟧", "", texto).strip()
        norm = _normalizar(texto)
        if len(norm) >= 12 and not any(norm in e for e in ya if e):
            candidatas.append({
                "texto": texto,
                "despues_de": anterior[-1][1]["num"] if anterior else None,
                "pos": linea.pos,
            })
            if len(candidatas) > max_candidatas:
                break
        i = fin
    return candidatas


def asignar_imagenes(questions: List[Dict[str, Any]], ub: Optional[Ubicaciones],
                     omitidas: Optional[List[Dict[str, Any]]] = None) -> int:
    """Pone cada imagen en data["images"] de la pregunta que le corresponde
    (ver el docstring del módulo). Devuelve cuántas se asignaron. Quita de
    cada pregunta la marca interna _comparte_imagen. En `omitidas`, si se
    pasa, agrega las preguntas que la IA no devolvió (3c)."""
    try:
        return _asignar(questions, ub, omitidas) if ub and ub.imagenes else 0
    finally:
        for q in questions:
            (q.get("data") or {}).pop("_comparte_imagen", None)


def _asignar(questions: List[Dict[str, Any]], ub: Ubicaciones, omitidas: Optional[List[Dict[str, Any]]]) -> int:
    inicios = _ubicar_preguntas(questions, ub.lineas, ub.imagenes)
    ubicadas = sorted(((ub.lineas[k].pos, n, q) for n, (q, k) in enumerate(zip(questions, inicios)) if k is not None),
                      key=lambda t: (t[0], t[1]))
    inicios_pos = {pos for pos, _, _ in ubicadas}
    asignadas = 0
    for img in ub.imagenes:
        # 1.º la pregunta que empieza en el mismo renglón que la imagen.
        destino = next((q for pos, _, q in ubicadas if img.inicio <= pos <= img.fin), None)
        if destino is None:
            # 2.º una de sus vecinas. La de arriba solo si nada indica que la
            # imagen es de otra pregunta (una que la IA no devolvió, o la
            # imagen viene después de sus opciones); la de abajo solo si
            # empieza pegada a la imagen.
            arriba = [(pos, q) for pos, _, q in ubicadas if pos < img.inicio]
            abajo = [(pos, q) for pos, _, q in ubicadas if pos > img.fin]
            cand_arriba = (arriba[-1][1] if arriba and not _es_de_otra(
                ub.lineas, arriba[-1][0], img.inicio, arriba[-1][1], inicios_pos) else None)
            cand_abajo = abajo[0][1] if abajo and _pegada(ub.lineas, img.fin, abajo[0][0]) else None
            if cand_arriba and cand_abajo:
                destino = _elegir(cand_arriba, cand_abajo)
            elif cand_arriba:
                destino = cand_arriba
            elif cand_abajo and _menciona(cand_abajo) and not _mira_adelante(cand_abajo):
                destino = cand_abajo
        if destino is None:
            hallada = _enunciado_omitido(ub.lineas, img, ubicadas, questions) if omitidas is not None else None
            if hallada:
                texto, despues_de = hallada
                cod = codificar(img.imagen)
                omitidas.append({
                    "num": (despues_de or 0) + 1, "type": "essay",
                    "reasons": [f"{MOTIVO_OMITIDA}"], "preview": texto[:200],
                    "recoverable_data": {"stem": texto, "images": [
                        {"name": f"omitida{len(omitidas) + 1}-1.{cod['ext']}", "mime": MIMES[cod["ext"]], "b64": cod["b64"]}]},
                    "despues_de": despues_de,
                })
                logger.info("Posible pregunta omitida por la IA, con su imagen: %r", texto[:60])
            else:
                logger.info("Imagen sin pregunta que le corresponda con certeza: se omite.")
            continue
        lista = destino["data"].setdefault("images", [])
        if len(lista) >= MAX_POR_PREGUNTA:
            continue
        cod = codificar(img.imagen)
        nombre = f"pregunta{destino['num']}-{len(lista) + 1}.{cod['ext']}"
        lista.append({"name": nombre, "mime": MIMES[cod["ext"]], "b64": cod["b64"]})
        asignadas += 1
    if asignadas:
        n = _compartir(questions, inicios)
        if n:
            logger.info("Imagen compartida con %d pregunta(s) encadenada(s).", n)
        _quitar_transcripciones_redundantes(questions, ub.lineas, inicios)
    return asignadas


# ── Validación (llegan del navegador) ──────────────────────────────────────

def errores_imagenes(num: Any, imagenes: Any) -> List[str]:
    """Las imágenes vuelven del editor en /api/generate_xml: se comprueba su
    forma antes de meterlas en el XML (nombre, tipo, base64 y tamaño)."""
    if imagenes is None:
        return []
    if not isinstance(imagenes, list) or len(imagenes) > MAX_POR_PREGUNTA:
        return [f"Error: la Pregunta {num} tiene imágenes no válidas."]
    for im in imagenes:
        if not isinstance(im, dict):
            return [f"Error: la Pregunta {num} tiene imágenes no válidas."]
        nombre, mime, b64 = im.get("name"), im.get("mime"), im.get("b64")
        if not (isinstance(nombre, str) and NOMBRE_VALIDO.match(nombre)
                and mime == MIMES[nombre.rsplit(".", 1)[1]]
                and isinstance(b64, str) and _B64.match(b64)
                and len(b64) * 3 // 4 <= MAX_BYTES_IMAGEN):
            return [f"Error: la Pregunta {num} tiene una imagen no válida."]
    return []
