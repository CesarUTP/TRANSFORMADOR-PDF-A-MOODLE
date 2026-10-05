"""
importar_xml.py — importar un Moodle XML ya existente al editor (2.0).

El docente abre en la app un XML de Moodle (uno que descargó de esta app, o que
exportó de su banco de preguntas) y lo revisa/edita como un examen recién
convertido; al final vuelve a generar el XML. La salida sigue siendo SOLO Moodle XML.

No usa IA: lee el XML. Cada pregunta se convierte a la MISMA forma que entrega la IA
(la que consume schema_adapter.adapt), de modo que opciones por índice, huecos de
«Completar», parejas, validación y «preguntas omitidas» funcionan igual que siempre.

Tipos que entiende: opción múltiple (una o varias correctas), verdadero/falso,
emparejamiento, completar (huecos de opción múltiple), respuesta corta, numérica y
ensayo. Lo demás (calculadas, arrastrar y soltar, descripciones…) queda entre las
«preguntas no incluidas», con su motivo: NUNCA se inventa ni se descarta en silencio.

Seguridad: el XML es un archivo ajeno. Se lee con lxml sin resolver entidades ni red
(no hay XXE ni «billion laughs»), con tope de preguntas y de imágenes.

Es un módulo plano (sin paquetes): dev/sync_ejecutable.py solo copia los
backend/*.py de primer nivel.
"""

import base64
import binascii
import html
import io
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from lxml import etree
from PIL import Image

import confianza
import imagenes
from schema_adapter import adapt
from validator import partition_questions

logger = logging.getLogger(__name__)

MAX_PREGUNTAS = 500
MAX_BYTES_IMAGEN = imagenes.MAX_BYTES_IMAGEN

# Tipos de pregunta que no se pueden editar aquí, con el nombre que ve el docente.
_NO_SOPORTADOS = {
    "description": "un texto informativo (no es una pregunta)",
    "calculated": "calculada", "calculatedsimple": "calculada simple", "calculatedmulti": "calculada de opción múltiple",
    "ddwtos": "arrastrar y soltar sobre texto", "ddmarker": "arrastrar y soltar sobre una imagen",
    "ddimageortext": "arrastrar y soltar sobre una imagen", "gapselect": "seleccionar palabras que faltan",
    "ordering": "ordenar", "match": "emparejamiento antiguo", "multianswer_unsupported": "completar con respuestas de texto",
}

_FORMATO_TEXTO_PLANO = ("plain_text", "markdown")


# ── Leer el XML con seguridad ───────────────────────────────────────────────
def _raiz(raw: bytes):
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False,
                             remove_comments=True, remove_pis=True)
    try:
        raiz = etree.fromstring(raw, parser)
    except etree.XMLSyntaxError as exc:
        raise HTTPException(status_code=422, detail=(
            f"El archivo XML está dañado o incompleto y no se puede leer ({str(exc)[:120]})."))
    if raiz.tag != "quiz":
        raise HTTPException(status_code=422, detail=(
            "Este XML no es un archivo de preguntas de Moodle (le falta la etiqueta <quiz>). "
            "Elige uno que hayas exportado de Moodle o generado con esta aplicación."))
    return raiz


def _texto_de(nodo, ruta: str) -> str:
    """Contenido de <ruta><text>…</text></ruta> ('' si no está)."""
    t = nodo.find(f"{ruta}/text") if ruta else nodo.find("text")
    return (t.text or "") if t is not None else ""


def _formato_de(nodo, ruta: str) -> str:
    n = nodo.find(ruta) if ruta else nodo
    return (n.get("format") or "html") if n is not None else "html"


# ── HTML de Moodle → texto del editor ───────────────────────────────────────
_BR = re.compile(r"<br\s*/?>", re.I)
_PARRAFO_FIN_INICIO = re.compile(r"</p\s*>\s*<p\b[^>]*>", re.I)
_BLOQUE = re.compile(r"</?(?:p|div|li|tr|h[1-6]|pre)\b[^>]*>", re.I)
_ETIQUETA = re.compile(r"<[^>]+>")
_PLUGINFILE = re.compile(r"""<img\b[^>]*?src\s*=\s*["']@@PLUGINFILE@@/([^"']+)["'][^>]*>""", re.I)


def html_a_texto(s: str, formato: str = "html") -> str:
    """El texto que escribiría el docente: <br> y párrafos como saltos de línea, sin etiquetas,
    entidades decodificadas (&nbsp; → espacio: la sangría del código vuelve a ser espacios)."""
    s = s or ""
    if formato in _FORMATO_TEXTO_PLANO:
        return s.replace("\r\n", "\n").strip()
    s = _PLUGINFILE.sub("", s)
    s = _BR.sub("\n", s)
    s = _PARRAFO_FIN_INICIO.sub("\n\n", s)
    s = _BLOQUE.sub("\n", s)
    s = _ETIQUETA.sub("", s)
    s = html.unescape(s).replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    lineas = [ln.rstrip() for ln in s.split("\n")]
    s = "\n".join(lineas)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip("\n").strip()


# ── Imágenes de la pregunta ─────────────────────────────────────────────────
def _tipo_imagen(datos: bytes) -> Optional[str]:
    if datos[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if datos[:3] == b"\xff\xd8\xff":
        return "jpg"
    return None


def _imagenes_de(qn, html_texto: str, num: int, avisos: List[str]) -> List[Dict[str, str]]:
    """Las imágenes de <questiontext> (<file … encoding="base64">) que la pregunta usa, solo PNG y JPEG."""
    archivos: Dict[str, bytes] = {}
    for f in qn.findall("questiontext/file"):
        nombre = f.get("name") or ""
        try:
            archivos[nombre] = base64.b64decode("".join((f.text or "").split()), validate=True)
        except (binascii.Error, ValueError):
            avisos.append(f"La pregunta {num} trae una imagen dañada («{nombre[:40]}») y no se importó.")
    usados = [n for n in re.findall(r"@@PLUGINFILE@@/([^\"'>\s]+)", html_texto)]
    orden = [n for n in dict.fromkeys(usados) if n in archivos] or list(archivos)
    salida: List[Dict[str, str]] = []
    for nombre in orden:
        datos = archivos[nombre]
        ext = _tipo_imagen(datos)
        if ext is None or len(datos) > MAX_BYTES_IMAGEN:
            motivo = "no es PNG ni JPEG" if ext is None else "pesa más de 2 MB"
            avisos.append(f"La pregunta {num} trae una imagen («{nombre[:40]}») que {motivo}: no se importó.")
            continue
        try:
            Image.open(io.BytesIO(datos)).verify()
        except Exception:  # noqa: BLE001 — una imagen rara no debe romper la importación
            avisos.append(f"La pregunta {num} trae una imagen («{nombre[:40]}») que no se pudo leer: no se importó.")
            continue
        if len(salida) >= imagenes.MAX_POR_PREGUNTA:
            avisos.append(f"La pregunta {num} tiene más de {imagenes.MAX_POR_PREGUNTA} imágenes: solo se importaron las primeras.")
            break
        salida.append({"name": f"pregunta{num}-{len(salida) + 1}.{ext}",
                       "mime": "image/png" if ext == "png" else "image/jpeg",
                       "b64": base64.b64encode(datos).decode("ascii")})
    return salida


# ── «Completar» (multianswer): los huecos {n:MULTICHOICE:=a~b#feedback} ─────
_HUECO = re.compile(r"\{(\d*):([A-Za-z_]+):((?:[^}\\]|\\.)*)\}")


def _delimitador_vale(previo: str) -> bool:
    """Un «~», «#» o «}» solo cuenta si no lo precede «\\» ni un «&» o «&amp;» (así lo lee Moodle)."""
    return not (previo.endswith("\\") or previo.endswith("&") or previo.endswith("&amp;"))


def _partir_hueco(cuerpo: str) -> List[Tuple[str, bool]]:
    """Cuerpo de un hueco de opciones → [(texto, correcta)]. Quita la retroalimentación (#…),
    las marcas «=» / «%n%» y los escapes («\\}» y «\\#»), y decodifica las entidades."""
    opciones: List[str] = []
    actual = ""
    for ch in cuerpo + "~":
        if ch == "~" and _delimitador_vale(actual):
            opciones.append(actual)
            actual = ""
        else:
            actual += ch
    salida: List[Tuple[str, bool]] = []
    for o in opciones:
        corte = next((i for i, c in enumerate(o) if c == "#" and _delimitador_vale(o[:i])), None)
        if corte is not None:
            o = o[:corte]
        correcta = False
        if o.startswith("="):
            correcta, o = True, o[1:]
        else:
            m = re.match(r"^%(-?\d+(?:\.\d+)?)%", o)
            if m:
                correcta, o = float(m.group(1)) > 0, o[m.end():]
        o = html.unescape(o.replace("\\}", "}").replace("\\#", "#"))
        salida.append((o.strip(), correcta))
    return salida


def _es_hueco_de_opciones(etiqueta: str) -> bool:
    e = etiqueta.upper()
    return e.startswith(("MC", "MR", "MULTICHOICE", "MULTIRESPONSE")) and not e.startswith(("MW",))


def _cloze_a_payload(html_texto: str, formato: str) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    """(enunciado con [A], [B]…, huecos) o None si algún hueco no es de opciones (respuesta corta, numérico)."""
    huecos: List[Dict[str, Any]] = []
    trozos: List[str] = []
    ultimo = 0
    for m in _HUECO.finditer(html_texto):
        if not _es_hueco_de_opciones(m.group(2)):
            return None
        opciones = _partir_hueco(m.group(3))
        if not opciones:
            return None
        letra = chr(65 + len(huecos))
        huecos.append({"marcador": letra, "opciones": [{"texto": t, "correcta": c} for t, c in opciones if t != "" or c]})
        trozos.append(html_texto[ultimo:m.start()])
        trozos.append(f"[{letra}]")
        ultimo = m.end()
    if not huecos or len(huecos) > 26:
        return None
    trozos.append(html_texto[ultimo:])
    # El texto se convierte a texto del editor con los marcadores puestos (no contienen etiquetas).
    return html_a_texto("".join(trozos), formato), huecos


# ── Una pregunta del XML → la forma que entrega la IA ───────────────────────
def _fraccion(a) -> float:
    try:
        return float(a.get("fraction", "0"))
    except ValueError:
        return 0.0


def _respuestas(qn) -> List[Tuple[str, float]]:
    return [(html_a_texto(_texto_de(a, ""), a.get("format") or "html"), _fraccion(a)) for a in qn.findall("answer")]


def _pregunta_a_payload(qn, num: int, avisos: List[str]):
    """(payload, imágenes) o (None, motivo) si el tipo no se puede editar."""
    tipo = qn.get("type") or ""
    fmt = _formato_de(qn, "questiontext")
    crudo = _texto_de(qn, "questiontext")
    enunciado = html_a_texto(crudo, fmt)
    base: Dict[str, Any] = {
        "orden": num, "enunciado": enunciado, "respuesta_marcada": True, "confianza": "alta",
        "retroalimentacion": html_a_texto(_texto_de(qn, "generalfeedback"), _formato_de(qn, "generalfeedback")),
    }
    imgs = _imagenes_de(qn, crudo, num, avisos)

    if tipo == "multichoice":
        resp = _respuestas(qn)
        if not resp:
            return None, "no tiene respuestas"
        return {**base, "tipo": "multichoice", "opciones": [
            {"letra_original": "", "texto": t, "correcta": f > 0} for t, f in resp]}, imgs
    if tipo == "truefalse":
        resp = _respuestas(qn)
        verdadera = next((t.strip().lower() for t, f in resp if f > 0), "")
        valor = {"true": "Verdadero", "verdadero": "Verdadero", "false": "Falso", "falso": "Falso"}.get(verdadera)
        if valor is None:
            return {**base, "tipo": "truefalse", "respuesta_texto": "", "respuesta_marcada": False}, imgs
        return {**base, "tipo": "truefalse", "respuesta_texto": valor}, imgs
    if tipo == "shortanswer":
        resp = [t for t, f in _respuestas(qn) if f > 0 and t.strip() and t.strip() != "*"]
        return {**base, "tipo": "shortanswer", "respuesta_texto": resp[0] if resp else "",
                "respuesta_marcada": bool(resp)}, imgs
    if tipo == "numerical":
        resp = [t for t, f in _respuestas(qn) if f > 0 and t.strip()]
        return {**base, "tipo": "numerical", "respuesta_texto": resp[0] if resp else "",
                "respuesta_marcada": bool(resp)}, imgs
    if tipo == "essay":
        return {**base, "tipo": "essay"}, imgs
    if tipo == "matching":
        izquierda: List[str] = []
        derecha: List[str] = []
        parejas: List[Dict[str, int]] = []
        for sub in qn.findall("subquestion"):
            izq = html_a_texto(_texto_de(sub, ""), sub.get("format") or "html")
            der = html_a_texto(_texto_de(sub, "answer"), "html")
            if der and der not in derecha:
                derecha.append(der)
            if izq:
                izquierda.append(izq)
                if der:
                    parejas.append({"izquierda": len(izquierda), "derecha": derecha.index(der) + 1})
        if len(izquierda) < 1 or not derecha:
            return None, "no tiene parejas"
        return {**base, "tipo": "matching", "items_izquierda": izquierda, "items_derecha": derecha, "parejas": parejas}, imgs
    if tipo in ("cloze", "multianswer"):  # en el XML se llama «cloze»; «multianswer» es su nombre interno
        convertido = _cloze_a_payload(crudo, fmt)
        if convertido is None:
            return None, ("completar con espacios de respuesta corta o numérica (aquí solo se editan los espacios con opciones)")
        texto, huecos = convertido
        return {**base, "tipo": "cloze", "enunciado": texto, "huecos": huecos}, imgs
    return None, _NO_SOPORTADOS.get(tipo, f"de un tipo que esta aplicación no edita («{tipo or 'desconocido'}»)")


def _categoria(raiz) -> Optional[str]:
    for qn in raiz.findall("question"):
        if qn.get("type") == "category":
            ruta = _texto_de(qn, "category").strip()
            ruta = re.sub(r"^\$[a-z]+\$/", "", ruta)
            ruta = re.sub(r"^top/?", "", ruta)
            ultimo = ruta.rstrip("/").split("/")[-1].strip()
            return ultimo or None
    return None


def importar_xml(raw: bytes, filename: str = "importado.xml") -> Dict[str, Any]:
    """Moodle XML → el mismo resultado que /api/parse (preguntas, clave y omitidas), más `importado`,
    `categoria` y `puntos_total`. Lanza HTTPException 422 con un mensaje para el docente si no se puede."""
    raiz = _raiz(raw)
    qns = [q for q in raiz.findall("question") if q.get("type") != "category"]
    if not qns:
        raise HTTPException(status_code=422, detail="El XML no trae ninguna pregunta.")
    if len(qns) > MAX_PREGUNTAS:
        raise HTTPException(status_code=422, detail=f"El XML trae {len(qns)} preguntas: el máximo es {MAX_PREGUNTAS}. Divídelo en varios.")

    avisos: List[str] = []
    payloads: List[Dict[str, Any]] = []
    imgs_por_num: Dict[int, List[Dict[str, str]]] = {}
    puntos: Dict[int, float] = {}
    no_incluidas: List[Dict[str, Any]] = []
    for qn in qns:
        num = len(payloads) + 1
        payload, extra = _pregunta_a_payload(qn, num, avisos)
        if payload is None:
            texto = html_a_texto(_texto_de(qn, "questiontext"), _formato_de(qn, "questiontext"))
            nombre = html_a_texto(_texto_de(qn, "name"), "plain_text")
            no_incluidas.append({
                "num": len(payloads) + len(no_incluidas) + 1, "type": qn.get("type") or "?",
                "preview": (" ".join((texto or nombre).split()))[:160],
                "reasons": [f"Esta pregunta es {extra}: no se puede editar aquí y no se incluyó."],
                "recoverable_data": None, "_tras_payload": len(payloads),
            })
            continue
        payloads.append(payload)
        if extra:
            imgs_por_num[num] = extra
        try:
            g = float(qn.findtext("defaultgrade") or 0)
        except ValueError:
            g = 0.0
        if g > 0:
            puntos[num] = round(g, 4)

    if not payloads:
        raise HTTPException(status_code=422, detail={
            "message": "No se pudo importar ninguna pregunta del XML:",
            "errors": [r for sq in no_incluidas for r in sq["reasons"]]})

    preguntas, clave = adapt({"preguntas": payloads})
    for q in preguntas:
        if q["num"] in imgs_por_num:
            q["data"]["images"] = imgs_por_num[q["num"]]
        if q["num"] in puntos:
            q["points"] = puntos[q["num"]]
    validas, omitidas = partition_questions(preguntas, clave)
    # Todo lo que dice el XML es «del documento»: nada lo interpretó una IA.
    confianza.etiquetar(validas, clave, desde_documento={q["num"] for q in validas})
    for q in validas:
        q["data"].pop("low_confidence", None)

    nums_validas = {q["num"] for q in validas}
    # Cada no incluida dice después de cuántas preguntas INCLUIDAS iba (así «Añadir con lo ya
    # extraído» la vuelve a poner en su lugar): las que descartó el validador tienen su número
    # de pregunta; las que no se pudieron convertir, cuántas había antes de ellas.
    resultado_omitidas = []
    for o in omitidas:
        resultado_omitidas.append({**o, "despues_de": sum(1 for n in nums_validas if n < o["num"])})
    for o in no_incluidas:
        tras = o.pop("_tras_payload")
        resultado_omitidas.append({**o, "despues_de": sum(1 for n in nums_validas if n <= tras)})
    resultado_omitidas.sort(key=lambda o: o["despues_de"])
    if not validas:
        raise HTTPException(status_code=422, detail={
            "message": "No se pudo importar ninguna pregunta del XML:",
            "errors": [r for sq in resultado_omitidas for r in sq["reasons"]]})
    puntos_total = round(sum(q.get("points") or 0 for q in validas), 4)
    return {
        "filename": filename,
        "questions": validas,
        "answer_key": {n: info for n, info in clave.items() if n in nums_validas},
        "was_reformatted": False,
        "skipped_questions": resultado_omitidas,
        "completeness_notice": " ".join(avisos) if avisos else None,
        "color_marks_notice": None,
        "escaneado": False,
        "importado": True,
        "categoria": _categoria(raiz),
        "puntos_total": puntos_total or None,
    }
