"""
extractor_docx.py — lee un examen en Word (.docx) y lo deja en la MISMA forma
que el lector de PDF (extractor.py), así que el resto del flujo no cambia:

  - texto enriquecido: marcas ⟦rojo⟧…⟦/rojo⟧, ⟦resaltado⟧, ⟦subrayado⟧ y
    ⟦negrita⟧ (las mismas que produce _enriched_page_text) y las tablas como
    bloque [Tabla] | celda | … [/Tabla];
  - texto plano (sin marcas) para la pre-validación y los estimadores;
  - las filas de cada tabla, para resolver cuadros con X en código;
  - las imágenes, cada una con el texto que la precede (para asignarla a su
    pregunta; ver imagenes.py);
  - las ecuaciones de Word (OMML) convertidas a LaTeX entre \\( y \\).

En Word las marcas son datos del documento (el color de un tramo es un
atributo, no un trazo que interpretar), así que se leen con más certeza que
en un PDF. La numeración automática ("1.", "a)") no está en el texto: se
reconstruye desde numbering.xml.

Un .docx es un ZIP con XML dentro: se limita el tamaño descomprimido (un ZIP
armado a propósito puede ocupar gigas al abrirse) y el XML se lee sin
entidades externas ni red.
"""

import io
import logging
import re
import zipfile
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from lxml import etree
from PIL import Image

from extractor import _color_name, _is_marker_fill, _render_table
from imagenes import ImagenUbicada, Linea, Ubicaciones, cargar_reducida

logger = logging.getLogger(__name__)

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "v": "urn:schemas-microsoft-com:vml",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}
W = "{%s}" % NS["w"]
M = "{%s}" % NS["m"]
R_ID = "{%s}id" % NS["r"]
R_EMBED = "{%s}embed" % NS["r"]

MAX_DESCOMPRIMIDO = 80 * 1024 * 1024   # todo el .docx abierto
MAX_XML = 30 * 1024 * 1024             # un solo XML (document.xml, estilos…)
MAX_IMAGENES = 30
MAX_COLUMNAS_TABLA = 63  # el máximo de columnas de una tabla en Word
MAX_PIXELES_IMAGEN = 12_000_000  # ver el comentario en imagen()
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, remove_comments=True)



class DocxInvalido(ValueError):
    pass


@dataclass
class DocxLeido:
    texto_plano: str
    texto_enriquecido: str
    tablas: List[List[List[str]]] = field(default_factory=list)
    # Líneas e imágenes con su n.º de párrafo, para asignar cada imagen a
    # su pregunta después de la IA (ver imagenes.py).
    ubicaciones: Ubicaciones = field(default_factory=Ubicaciones)


# ── Formato de texto: estilos y marcas ─────────────────────────────────────

def _val(el, attr="val") -> Optional[str]:
    return None if el is None else el.get(W + attr)


def _encendido(el) -> bool:
    """<w:b/> o <w:b w:val="true"/> enciende; w:val="0"/"false" apaga."""
    return el is not None and (_val(el) or "true").lower() not in ("0", "false", "off", "none")


def _props(rpr) -> Dict[str, object]:
    """Propiedades de marca de un <w:rPr> (solo las que aparecen)."""
    out: Dict[str, object] = {}
    if rpr is None:
        return out
    c = rpr.find("w:color", NS)
    if c is not None and _val(c):
        out["color"] = _val(c)
    h = rpr.find("w:highlight", NS)
    if h is not None:
        out["resaltado"] = (_val(h) or "none").lower() != "none"
    shd = rpr.find("w:shd", NS)
    if shd is not None:
        # Mismo criterio que el resaltado en PDF (extractor._is_marker_fill):
        # solo un relleno con TONO (amarillo, verde, celeste…) es una marca.
        # El gris de un estilo de código o de un encabezado no lo es.
        rgb = _hex_a_rgb(_val(shd, "fill") or "auto")
        out["sombreado"] = bool(rgb and _is_marker_fill(rgb))
    u = rpr.find("w:u", NS)
    if u is not None:
        out["subrayado"] = (_val(u) or "single").lower() != "none"
    b = rpr.find("w:b", NS)
    if b is not None:
        out["negrita"] = _encendido(b)
    return out


def _estilos(z: zipfile.ZipFile) -> Dict[str, Dict[str, object]]:
    """styleId → propiedades de marca, resolviendo la herencia (basedOn)."""
    if "word/styles.xml" not in z.namelist():
        return {}
    raiz = etree.fromstring(_leer(z, "word/styles.xml"), _PARSER)
    crudos: Dict[str, Tuple[Optional[str], Dict[str, object]]] = {}
    for st in raiz.findall("w:style", NS):
        sid = _val(st, "styleId")
        if sid:
            crudos[sid] = (_val(st.find("w:basedOn", NS)), _props(st.find("w:rPr", NS)))
    resueltos: Dict[str, Dict[str, object]] = {}

    def resolver(sid: str) -> Dict[str, object]:
        if sid in resueltos:
            return resueltos[sid]
        # Iterativo, no recursivo: un documento real con miles de estilos
        # encadenados (cada uno "basedOn" el anterior) superaba el límite
        # de recursión de Python con la versión recursiva anterior, y
        # "maximum recursion depth exceeded" tumbaba la extracción entera.
        # Primero se sube la cadena hasta la raíz (o hasta un estilo ya
        # resuelto, o hasta detectar un ciclo), y después se combina de
        # arriba hacia abajo.
        cadena: List[str] = []
        visto = set()
        actual: Optional[str] = sid
        heredado: Dict[str, object] = {}
        while actual and actual not in visto:
            if actual in resueltos:
                heredado = resueltos[actual]
                break
            if actual not in crudos:
                break
            visto.add(actual)
            cadena.append(actual)
            actual = crudos[actual][0]
        for nodo in reversed(cadena):
            heredado = {**heredado, **crudos[nodo][1]}
            resueltos[nodo] = heredado
        return resueltos.get(sid, {})

    for sid in crudos:
        resolver(sid)
    return resueltos


def _hex_a_rgb(hexa: str):
    hexa = hexa.strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", hexa):
        return None
    return tuple(int(hexa[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _marca(props: Dict[str, object]) -> Optional[str]:
    """Una sola marca por tramo, con la misma prioridad que en PDF:
    color > resaltado > subrayado > negrita."""
    rgb = _hex_a_rgb(str(props.get("color") or ""))
    if rgb and max(abs(rgb[0] - rgb[1]), abs(rgb[1] - rgb[2]), abs(rgb[0] - rgb[2])) > 0.15:
        return _color_name(rgb)
    if props.get("resaltado") or props.get("sombreado"):
        return "resaltado"
    if props.get("subrayado"):
        return "subrayado"
    if props.get("negrita"):
        return "negrita"
    return None


# ── Ecuaciones (OMML → LaTeX) ──────────────────────────────────────────────

_SIMBOLOS = {
    "α": r"\alpha ", "β": r"\beta ", "γ": r"\gamma ", "δ": r"\delta ", "ε": r"\varepsilon ",
    "θ": r"\theta ", "λ": r"\lambda ", "μ": r"\mu ", "π": r"\pi ", "ρ": r"\rho ", "σ": r"\sigma ",
    "τ": r"\tau ", "φ": r"\varphi ", "ω": r"\omega ", "Δ": r"\Delta ", "Σ": r"\Sigma ", "Ω": r"\Omega ",
    "≤": r"\le ", "≥": r"\ge ", "≠": r"\ne ", "±": r"\pm ", "×": r"\times ", "÷": r"\div ", "·": r"\cdot ",
    "∞": r"\infty ", "→": r"\to ", "≈": r"\approx ", "∈": r"\in ", "∉": r"\notin ", "∪": r"\cup ",
    "∩": r"\cap ", "⊂": r"\subset ", "∀": r"\forall ", "∃": r"\exists ", "∂": r"\partial ", "∇": r"\nabla ",
    "−": "-", "√": r"\surd ",
}
_NARY = {"∑": r"\sum", "∏": r"\prod", "∫": r"\int", "∬": r"\iint", "∮": r"\oint", "⋃": r"\bigcup", "⋂": r"\bigcap"}
_ACENTOS = {"̂": r"\hat", "̄": r"\bar", "̃": r"\tilde", "⃗": r"\vec", "̇": r"\dot", "̈": r"\ddot"}
_FUNCIONES = {"sin", "cos", "tan", "cot", "sec", "csc", "log", "ln", "exp", "lim", "max", "min", "arcsin", "arccos", "arctan"}


def _texto_latex(t: str) -> str:
    return "".join(_SIMBOLOS.get(ch, "\\" + ch if ch in "{}%#&$_" else ch) for ch in t)


# w:sym: un carácter de una fuente de símbolos. En Word las casillas y
# palomitas de una respuesta marcada suelen ser Wingdings (F0FC = ✓); el
# código llega como 0xF0xx (área privada) y no dice nada sin esta tabla.
_WINGDINGS = {
    0xFC: "✓", 0xFB: "✗", 0xFE: "☑", 0xFD: "☒", 0xA8: "☐", 0x6F: "☐", 0x78: "☒",
}


def _simbolo(fuente: str, codigo: str) -> str:
    try:
        n = int(codigo, 16)
    except (TypeError, ValueError):
        return ""
    if "wingdings" in (fuente or "").lower():
        return _WINGDINGS.get(n & 0xFF, "")
    # Otra fuente: un carácter Unicode normal se conserva; un código del área
    # privada de una fuente de símbolos (viñetas, flechas) no se puede leer.
    return chr(n) if 0x20 <= n < 0xF000 else ""


def _hijo(el, nombre):
    return el.find(f"m:{nombre}", NS)


def _omml(el) -> str:
    """Convierte un nodo OMML a LaTeX (las construcciones de uso común en
    exámenes; lo desconocido se recorre y queda como texto)."""
    if el is None:
        return ""
    tag = etree.QName(el).localname
    sub = lambda n: _omml(_hijo(el, n))  # noqa: E731
    if tag == "r":
        return "".join(_texto_latex(t.text or "") for t in el.findall("m:t", NS))
    if tag == "f":
        return r"\frac{%s}{%s}" % (sub("num"), sub("den"))
    if tag == "sSup":
        return "{%s}^{%s}" % (sub("e"), sub("sup"))
    if tag == "sSub":
        return "{%s}_{%s}" % (sub("e"), sub("sub"))
    if tag == "sSubSup":
        return "{%s}_{%s}^{%s}" % (sub("e"), sub("sub"), sub("sup"))
    if tag == "rad":
        grado = sub("deg")
        return (r"\sqrt[%s]{%s}" % (grado, sub("e"))) if grado.strip() else r"\sqrt{%s}" % sub("e")
    if tag == "nary":
        chr_el = el.find("m:naryPr/m:chr", NS)
        op = _NARY.get(chr_el.get(M + "val") if chr_el is not None else "∫", r"\int")
        lim = ("_{%s}" % sub("sub") if sub("sub") else "") + ("^{%s}" % sub("sup") if sub("sup") else "")
        return "%s%s{%s}" % (op, lim, sub("e"))
    if tag == "d":
        pr = el.find("m:dPr", NS)
        beg = pr.find("m:begChr", NS) if pr is not None else None
        end = pr.find("m:endChr", NS) if pr is not None else None
        a = beg.get(M + "val") if beg is not None else "("
        b = end.get(M + "val") if end is not None else ")"
        a = {"{": r"\{", "": "."}.get(a, a)
        b = {"}": r"\}", "": "."}.get(b, b)
        return r"\left%s %s \right%s" % (a, ", ".join(_omml(e) for e in el.findall("m:e", NS)), b)
    if tag == "func":
        nombre = sub("fName").strip()
        nombre = "\\" + nombre if nombre in _FUNCIONES else r"\operatorname{%s}" % nombre
        return r"%s{%s}" % (nombre, sub("e"))
    if tag == "acc":
        chr_el = el.find("m:accPr/m:chr", NS)
        return r"%s{%s}" % (_ACENTOS.get(chr_el.get(M + "val") if chr_el is not None else "̂", r"\hat"), sub("e"))
    if tag == "bar":
        return r"\overline{%s}" % sub("e")
    if tag in ("limLow", "limUpp"):
        return "{%s}%s{%s}" % (sub("e"), "_" if tag == "limLow" else "^", sub("lim"))
    if tag == "m":
        filas = [" & ".join(_omml(e) for e in mr.findall("m:e", NS)) for mr in el.findall("m:mr", NS)]
        return r"\begin{matrix} %s \end{matrix}" % r" \\ ".join(filas)
    if tag == "eqArr":
        return r"\begin{aligned} %s \end{aligned}" % r" \\ ".join(_omml(e) for e in el.findall("m:e", NS))
    if tag.endswith("Pr") or tag in ("ctrlPr",):
        return ""
    return "".join(_omml(h) for h in el)


def _ecuacion(el) -> str:
    latex = " ".join(_omml(el).split())
    return f"\\({latex}\\)" if latex else ""


# ── Lectura del documento ──────────────────────────────────────────────────

def _entero_ooxml(el) -> int:
    """El w:val numérico de un elemento (gridSpan, gridBefore), acotado a
    las columnas que Word permite; lo ausente o ilegible es 0."""
    v = _val(el)
    return min(int(v), MAX_COLUMNAS_TABLA) if v and v.isdigit() else 0


def _leer(z: zipfile.ZipFile, nombre: str) -> bytes:
    info = z.getinfo(nombre)
    if info.file_size > MAX_XML:
        raise DocxInvalido("El documento de Word es demasiado grande para procesarlo.")
    return z.read(nombre)


@dataclass
class _Nivel:
    """Un nivel de una lista (<w:lvl>): cómo se cuenta y cómo se escribe."""
    formato: str
    plantilla: str
    inicio: int
    reinicio: Optional[int] = None   # w:lvlRestart (None: tras cualquier nivel superior)
    estilo: Optional[str] = None     # w:pStyle: estilo de párrafo ligado a este nivel


@dataclass
class _Lista:
    """Un <w:num>: la lista que usa un párrafo."""
    clave: str                                  # abstractNum al que cuenta (listas con el mismo continúan)
    niveles: Dict[str, _Nivel]
    inicios: Dict[str, int] = field(default_factory=dict)   # w:startOverride por nivel (reinicia)


def _nivel(lvl) -> _Nivel:
    inicio = _val(lvl.find("w:start", NS))
    reinicio = _val(lvl.find("w:lvlRestart", NS))
    return _Nivel(
        _val(lvl.find("w:numFmt", NS)) or "decimal",
        _val(lvl.find("w:lvlText", NS)) or "",
        int(inicio) if inicio and inicio.isdigit() else 1,
        int(reinicio) if reinicio and reinicio.isdigit() else None,
        _val(lvl.find("w:pStyle", NS)),
    )


def _numpr_estilos(z: zipfile.ZipFile) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    """styleId → (numId, ilvl) de la numeración que el ESTILO de párrafo
    declara en styles.xml (p. ej. «List Number»), con herencia basedOn. Solo
    están los estilos que terminan con numId."""
    if "word/styles.xml" not in z.namelist():
        return {}
    raiz = etree.fromstring(_leer(z, "word/styles.xml"), _PARSER)
    crudos: Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]] = {}
    for st in raiz.findall("w:style", NS):
        sid = _val(st, "styleId")
        if not sid:
            continue
        np_ = st.find("w:pPr/w:numPr", NS)
        crudos[sid] = (_val(st.find("w:basedOn", NS)),
                       _val(np_.find("w:numId", NS)) if np_ is not None else None,
                       _val(np_.find("w:ilvl", NS)) if np_ is not None else None)
    resueltos: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
    for sid in crudos:  # iterativo y con memoria, como _estilos (cadenas largas y ciclos)
        cadena: List[str] = []
        visto = set()
        actual: Optional[str] = sid
        heredado: Tuple[Optional[str], Optional[str]] = (None, None)
        while actual and actual not in visto:
            if actual in resueltos:
                heredado = resueltos[actual]
                break
            if actual not in crudos:
                break
            visto.add(actual)
            cadena.append(actual)
            actual = crudos[actual][0]
        for nodo in reversed(cadena):
            _, nid, lvl = crudos[nodo]
            heredado = (nid if nid is not None else heredado[0], lvl if lvl is not None else heredado[1])
            resueltos[nodo] = heredado
    return {sid: v for sid, v in resueltos.items() if v[0] is not None}


def _numeracion(z: zipfile.ZipFile, estilos_num: Dict[str, Tuple[Optional[str], Optional[str]]]) -> Dict[str, _Lista]:
    """numId → lista, desde numbering.xml: sus niveles (formato, plantilla,
    inicio), el abstractNum que comparte contador con otras listas y los
    reinicios (w:lvlOverride)."""
    if "word/numbering.xml" not in z.namelist():
        return {}
    nx = etree.fromstring(_leer(z, "word/numbering.xml"), _PARSER)
    abstractos: Dict[Optional[str], Tuple[Dict[str, _Nivel], Optional[str]]] = {}
    for a in nx.findall("w:abstractNum", NS):
        abstractos[_val(a, "abstractNumId")] = (
            {_val(lvl, "ilvl"): _nivel(lvl) for lvl in a.findall("w:lvl", NS)},
            _val(a.find("w:numStyleLink", NS)))
    nums = {_val(n, "numId"): n for n in nx.findall("w:num", NS)}

    def abstracto(aid: Optional[str], saltos: int = 0) -> Tuple[Optional[str], Dict[str, _Nivel]]:
        """Un abstractNum sin niveles que apunta a un estilo de lista
        (w:numStyleLink) usa los niveles de la lista de ese estilo."""
        niveles, vinculo = abstractos.get(aid, ({}, None))
        if niveles or not vinculo or saltos >= 3:
            return aid, niveles
        destino = nums.get((estilos_num.get(vinculo) or (None, None))[0])
        if destino is None:
            return aid, niveles
        return abstracto(_val(destino.find("w:abstractNumId", NS)), saltos + 1)

    listas: Dict[str, _Lista] = {}
    for nid, n in nums.items():
        clave, niveles = abstracto(_val(n.find("w:abstractNumId", NS)))
        niveles = dict(niveles)
        inicios: Dict[str, int] = {}
        for ov in n.findall("w:lvlOverride", NS):
            il = _val(ov, "ilvl")
            so = _val(ov.find("w:startOverride", NS))
            if il is not None and so and so.isdigit():
                inicios[il] = int(so)
            lvl = ov.find("w:lvl", NS)
            if il is not None and lvl is not None:
                niveles[il] = _nivel(lvl)
        listas[nid] = _Lista(str(clave), niveles, inicios)
    return listas


def _letras(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(97 + r) + s
    return s


MAX_INICIO_NUMERACION = 9999  # ver el comentario en _numeracion


def _romano(n: int) -> str:
    if n > MAX_INICIO_NUMERACION * 20:  # segunda barrera, por si n creciera por otro camino
        return str(n)
    out = ""
    for v, s in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
                 (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out, n = out + s, n - v
    return out


def _formatear(fmt: str, n: int) -> str:
    return {
        "decimal": str(n), "lowerLetter": _letras(n), "upperLetter": _letras(n).upper(),
        "lowerRoman": _romano(n), "upperRoman": _romano(n).upper(),
    }.get(fmt, "" if fmt in ("bullet", "none") else str(n))


_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # Word cifrado o .doc antiguo (no es un ZIP)
_DANADO = "El archivo Word está dañado o protegido con contraseña. Ábrelo en Word, quita la protección y guárdalo de nuevo como .docx."


def leer_docx(raw: bytes) -> DocxLeido:
    """Lee el .docx. Cualquier fallo de lectura por un archivo roto, cifrado
    o mal formado sale como DocxInvalido con un mensaje claro en español (el
    flujo lo muestra tal cual), no como el texto técnico de zipfile o lxml."""
    if raw[:8] == _OLE:
        # Un .docx con contraseña se guarda cifrado dentro de un contenedor
        # OLE, no como ZIP; un .doc antiguo tiene la misma firma.
        raise DocxInvalido("El archivo Word está protegido con contraseña o es un .doc antiguo. "
                           "Quita la protección, o ábrelo en Word y guárdalo como .docx.")
    try:
        return _leer_docx(raw)
    except DocxInvalido:
        raise
    except (zipfile.BadZipFile, etree.XMLSyntaxError, EOFError, zlib.error, NotImplementedError) as exc:
        logger.warning("Word ilegible: %s: %s", type(exc).__name__, exc)
        raise DocxInvalido(_DANADO) from exc
    except RuntimeError as exc:  # zipfile: «File … is encrypted, password required»
        if "encrypted" in str(exc).lower() or "password" in str(exc).lower():
            raise DocxInvalido(_DANADO) from exc
        raise


def _leer_docx(raw: bytes) -> DocxLeido:
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise DocxInvalido("El archivo no es un documento de Word (.docx) válido.")
    if sum(i.file_size for i in z.infolist()) > MAX_DESCOMPRIMIDO:
        raise DocxInvalido("El documento de Word es demasiado grande para procesarlo.")
    if "word/document.xml" not in z.namelist():
        raise DocxInvalido("El archivo no es un documento de Word (.docx) válido.")

    doc = etree.fromstring(_leer(z, "word/document.xml"), _PARSER)
    rels = {}
    if "word/_rels/document.xml.rels" in z.namelist():
        for e in etree.fromstring(_leer(z, "word/_rels/document.xml.rels"), _PARSER).iter("{%s}Relationship" % NS["rel"]):
            rels[e.get("Id")] = e.get("Target", "")
    estilos = _estilos(z)
    estilos_num = _numpr_estilos(z)
    numeracion = _numeracion(z, estilos_num)
    # Los contadores van por abstractNum y nivel: dos listas (numId) que
    # comparten abstractNum continúan la cuenta, salvo que una traiga
    # w:startOverride (reinicia al usarse por primera vez).
    contadores: Dict[Tuple[str, str], int] = {}
    usadas: set = set()  # (numId, nivel) ya usados: su startOverride ya se aplicó

    lineas_ricas: List[str] = []
    lineas_planas: List[str] = []
    tablas: List[List[List[str]]] = []
    imagenes: List[ImagenUbicada] = []

    def imagen(rid: Optional[str]) -> None:
        if not rid or rid not in rels or len(imagenes) >= MAX_IMAGENES:
            return
        destino = rels[rid]
        ruta = destino.lstrip("/") if destino.startswith("/") else "word/" + destino
        try:
            info = z.getinfo(ruta)
            if info.file_size > 20 * 1024 * 1024:
                return
            im = Image.open(io.BytesIO(z.read(ruta)))
            # Image.open() solo lee las dimensiones del encabezado (barato);
            # .load() decodifica los píxeles de verdad. Una imagen de
            # 12000×12000 (144 millones de píxeles, un solo color, cabe en
            # un .docx de 1 KB) se decodifica entera en memoria — Pillow
            # solo AVISA por debajo de 2× su propio límite, no la rechaza,
            # y referenciada varias veces en el documento se vieron más de
            # 2 GB de memoria por un archivo diminuto.
            if im.width * im.height > MAX_PIXELES_IMAGEN:
                return
            # Se guarda reducida (~2 MP): hasta 30 imágenes de 12 MP ocupaban
            # más de 1 GB, y a Moodle llegan a 1000 px de lado de todos modos.
            im = cargar_reducida(im)
        except Exception:  # noqa: BLE001 — EMF/WMF u otro formato que PIL no abre: se omite
            return
        # El párrafo en curso (aún no agregado a la lista): la imagen está en
        # su mismo renglón, como el "9. [imagen] ¿qué tipo de error es?".
        aqui = (len(lineas_planas),)
        imagenes.append(ImagenUbicada(im, aqui, aqui))

    def prefijo(p) -> str:
        np_ = p.find("w:pPr/w:numPr", NS)
        nid = _val(np_.find("w:numId", NS)) if np_ is not None else None
        lvl = _val(np_.find("w:ilvl", NS)) if np_ is not None else None
        estilo_p = _val(p.find("w:pPr/w:pStyle", NS))
        if nid is None and estilo_p in estilos_num:
            # Sin numeración propia: la del ESTILO del párrafo (p. ej. «Lista
            # con números»). Un numId propio, incluido el 0 («sin lista»), manda.
            nid, lvl_estilo = estilos_num[estilo_p]
            if lvl is None:
                lvl = lvl_estilo
            if lvl is None:  # el nivel que la lista liga a este estilo (w:lvl/w:pStyle)
                lista_e = numeracion.get(nid)
                lvl = next((k for k, v in sorted((lista_e.niveles if lista_e else {}).items())
                            if v.estilo == estilo_p), None)
        if np_ is None and nid is None:
            return ""
        lvl = lvl or "0"
        lista = numeracion.get(nid)
        if not lista or lvl not in lista.niveles:
            return ""
        nivel = lista.niveles[lvl]
        if nivel.formato == "bullet":
            return ""
        if (nid, lvl) not in usadas:
            usadas.add((nid, lvl))
            if lvl in lista.inicios:  # w:startOverride: esta lista reinicia aquí
                contadores[(lista.clave, lvl)] = lista.inicios[lvl] - 1
        actual = contadores.get((lista.clave, lvl), nivel.inicio - 1) + 1
        contadores[(lista.clave, lvl)] = actual
        for (c2, l2) in list(contadores):  # un nivel superior reinicia los inferiores
            if c2 == lista.clave and l2.isdigit() and lvl.isdigit() and int(l2) > int(lvl):
                # w:lvlRestart: 0 = nunca; n = solo tras un nivel de más arriba que el n-ésimo
                reinicio = lista.niveles[l2].reinicio if l2 in lista.niveles else None
                if reinicio is None or (reinicio > 0 and int(lvl) < reinicio):
                    del contadores[(c2, l2)]
        texto = nivel.plantilla
        for k, n_k in sorted(lista.niveles.items()):
            if k.isdigit():
                ini = lista.inicios.get(k, n_k.inicio)
                texto = texto.replace(f"%{int(k) + 1}", _formatear(n_k.formato, contadores.get((lista.clave, k), ini)))
        return (texto + " ") if texto.strip() else ""

    def parrafo(p, profundidad: int = 0) -> Tuple[str, str]:
        """(texto con marcas, texto plano) de un párrafo."""
        estilo_p = _val(p.find("w:pPr/w:pStyle", NS))
        base = estilos.get(estilo_p, {}) if estilo_p else {}
        tramos: List[Tuple[Optional[str], str]] = []
        # Párrafos de cuadros de texto: (rico, plano) ya armados, que se
        # agregan a continuación del párrafo que los contiene.
        cajas: List[Tuple[str, str]] = []

        def hijos_de_run(h):
            """Los hijos de un <w:r>, y el contenido de mc:AlternateContent:
            Word guarda ahí, dos veces, un dibujo o cuadro de texto (Choice
            para Word moderno, Fallback para el antiguo). Solo se lee UNA
            versión: la Choice, o la Fallback si no hay Choice."""
            for x in h:
                if not isinstance(x.tag, str):
                    continue
                if etree.QName(x).namespace == NS["mc"] and etree.QName(x).localname == "AlternateContent":
                    elegido = x.find("mc:Choice", NS)
                    if elegido is None:
                        elegido = x.find("mc:Fallback", NS)
                    if elegido is not None:
                        yield from hijos_de_run(elegido)
                else:
                    yield x

        def recorrer(el):
            for h in el:
                tag = etree.QName(h).localname if isinstance(h.tag, str) else ""
                ns = etree.QName(h).namespace if isinstance(h.tag, str) else ""
                if ns == NS["m"] and tag in ("oMath", "oMathPara"):
                    tramos.append((None, _ecuacion(h)))
                elif ns == NS["w"] and tag == "r":
                    rpr = h.find("w:rPr", NS)
                    estilo_r = _val(rpr.find("w:rStyle", NS)) if rpr is not None else None
                    props = {**base, **(estilos.get(estilo_r, {}) if estilo_r else {}), **_props(rpr)}
                    texto = []
                    for x in hijos_de_run(h):
                        t = etree.QName(x).localname if isinstance(x.tag, str) else ""
                        if t == "t":
                            texto.append(x.text or "")
                        elif t == "tab":
                            texto.append(" ")
                        elif t in ("br", "cr"):
                            texto.append("\n")
                        elif t == "noBreakHyphen":
                            texto.append("-")  # "-5" no puede pasar a "5"
                        elif t == "sym":
                            texto.append(_simbolo(_val(x, "font") or "", _val(x, "char") or ""))
                        elif t in ("drawing", "pict", "object"):
                            # Las imágenes de dentro de un cuadro de texto se
                            # leen con el cuadro (más abajo), no aquí.
                            for b in x.xpath(".//a:blip[not(ancestor::w:txbxContent)]", namespaces=NS):
                                imagen(b.get(R_EMBED))
                            for d in x.xpath(".//v:imagedata[not(ancestor::w:txbxContent)]", namespaces=NS):
                                imagen(d.get(R_ID))
                            if profundidad < 3:
                                for caja in x.xpath(".//w:txbxContent[not(ancestor::w:txbxContent)]", namespaces=NS):
                                    for pp in caja.findall(".//w:p", NS):
                                        cajas.append(parrafo(pp, profundidad + 1))
                    if texto:
                        tramos.append((_marca(props), "".join(texto)))
                elif ns == NS["mc"] and tag == "AlternateContent":
                    elegido = h.find("mc:Choice", NS)
                    if elegido is None:
                        elegido = h.find("mc:Fallback", NS)
                    if elegido is not None:
                        recorrer(elegido)
                elif ns == NS["w"] and tag in ("hyperlink", "ins", "smartTag", "sdt", "sdtContent",
                                               "fldSimple", "customXml", "moveTo"):
                    recorrer(h)

        pre = prefijo(p)  # antes de los cuadros de texto: la numeración va en orden
        recorrer(p)
        rico, plano, actual = [], [], None
        for marca, texto in tramos:
            plano.append(texto)
            if marca != actual:
                if actual:
                    rico.append(f"⟦/{actual}⟧")
                if marca:
                    rico.append(f"⟦{marca}⟧")
                actual = marca
            if marca and "\n" in texto:
                # Cada línea lleva su propia etiqueta cerrada: si el salto
                # suave (Shift+Enter) de una opción coloreada dejara la
                # etiqueta abierta, la marca quedaba repartida entre dos
                # líneas y ninguna la llevaba completa.
                texto = texto.replace("\n", f"⟦/{marca}⟧\n⟦{marca}⟧")
            rico.append(texto)
        if actual:
            rico.append(f"⟦/{actual}⟧")
        rico_s = re.sub(r"⟦([a-záéíóú]+)⟧⟦/\1⟧", "", pre + "".join(rico))
        plano_s = pre + "".join(plano)
        for r_caja, p_caja in cajas:
            if p_caja.strip():
                rico_s += "\n" + r_caja
                plano_s += "\n" + p_caja
        return rico_s, plano_s

    def bloque(contenedor):
        for el in contenedor:
            if not isinstance(el.tag, str):
                continue
            if el.tag == W + "p":
                rico, plano = parrafo(el)
                lineas_ricas.append(rico)
                lineas_planas.append(plano)
            elif el.tag == W + "tbl":
                filas = []
                for tr in el.findall("w:tr", NS):
                    # Rejilla lógica: una celda combinada (gridSpan) ocupa sus
                    # columnas, con su texto en la primera y vacías las demás;
                    # las columnas que la fila se salta (gridBefore) quedan
                    # vacías; y lo escrito en una celda que continúa una
                    # combinación vertical (vMerge) no se ve en Word, así que
                    # no cuenta. Así cada marca queda en la columna que se ve.
                    celdas = [("", "")] * _entero_ooxml(tr.find("w:trPr/w:gridBefore", NS))
                    for tc in tr.findall("w:tc", NS):
                        partes = [parrafo(p) for p in tc.findall(".//w:p", NS)]
                        celda = (" ".join(r for r, _ in partes), " ".join(pl for _, pl in partes))
                        vm = tc.find("w:tcPr/w:vMerge", NS)
                        if vm is not None and (_val(vm) or "continue").lower() != "restart":
                            celda = ("", "")
                        celdas.append(celda)
                        columnas = max(1, _entero_ooxml(tc.find("w:tcPr/w:gridSpan", NS)))
                        celdas.extend([("", "")] * max(0, min(columnas - 1, MAX_COLUMNAS_TABLA - len(celdas))))
                    filas.append(celdas)
                tablas.append([[pl for _, pl in f] for f in filas])
                lineas_ricas.append(_render_table([[r for r, _ in f] for f in filas]))
                lineas_planas.append("\n".join(" | ".join(pl for _, pl in f) for f in filas))
            elif el.tag in (W + "sdt", W + "sdtContent", W + "customXml"):
                bloque(el)

    cuerpo = doc.find("w:body", NS)
    if cuerpo is None:
        raise DocxInvalido("El documento de Word está vacío.")
    bloque(cuerpo)

    limpio = lambda ls: "\n".join(l for l in ls if l.strip())  # noqa: E731
    lineas = [Linea((i,), t) for i, t in enumerate(lineas_planas) if t.strip()]
    return DocxLeido(limpio(lineas_planas), limpio(lineas_ricas), tablas, Ubicaciones(lineas, imagenes))


def docx_tiene_imagenes(raw: bytes) -> bool:
    """Chequeo barato para el aviso de «casos especiales»."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            return any(n.startswith("word/media/") for n in z.namelist())
    except zipfile.BadZipFile:
        return False
