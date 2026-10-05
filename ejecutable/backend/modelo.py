"""
modelo.py — Modelo tipado de una pregunta.

Hasta ahora una pregunta viajaba como diccionario entre schema_adapter.adapt,
validator y xml_builder (y el editor la serializa a JSON). Los dicts siguen
siendo el formato de ENTRADA y SALIDA de esas funciones públicas (no cambia
ninguna firma ni el JSON que ve el navegador), pero por dentro cada módulo
los convierte a este modelo al entrar y trabaja con atributos tipados:

    p = Pregunta.desde_dict({"num": 3, "type": "multichoice", "data": {...}})
    p.options, p.respuesta_texto, p.resolver_correctas() ...
    p.a_dict()    # el mismo dict de antes

Garantías
---------
* Ida y vuelta EXACTA: `Pregunta.desde_dict(d).a_dict() == d` para cualquier
  dict (también el mismo orden de claves). Un campo que no se reconoce, o cuyo
  valor no tiene el tipo esperado, NO se pierde ni se corrige: se guarda tal
  cual en `extra` (nivel pregunta) o `extra_data` (dentro de "data").
* Un campo con valor None no se serializa: el JSON y el XML no cambian
  mientras nadie lo llene.
* Nunca lanza excepción por datos raros: la validación de la forma es
  trabajo del validador, que corre sobre lo que llega del navegador.

Dónde viaja cada campo (dict ↔ atributo)
-----------------------------------------
    pregunta:  num, type→tipo, data, error, points, raw_text
    data:      stem, text, options*, col_a*, col_b*, from_table*, feedback,
               images, low_confidence, answer_from_marks, color_review_hint,
               page→pagina, _comparte_imagen→comparte_imagen,
               origen_respuesta, confianza, recuadro
               (* solo en su tipo: options en multichoice; col_a, col_b y
                from_table en matching. En otro tipo van a `extra_data`.)
    clave:     type→tipo, answer, pairs, from_key, correct_idx*, huecos*   (answer_key[num])
               (* ver «Respuestas por índice»)

Respuestas por índice (opcionales; ausentes = el comportamiento de siempre)
---------------------------------------------------------------------------
La respuesta correcta viaja como TEXTO (clave.answer: «B | D», «A. x; B. y») y
una opción cuyo propio texto contiene « | » o « / » ("x | y", "10 / 2") se
partía mal. Por eso viaja además como ÍNDICES, sin nada que partir:

    clave.correct_idx   multichoice: lista de enteros base 0 = posiciones de las
                        opciones correctas en las letras ORDENADAS de
                        data["options"] (A→0, B→1…). Ej.: [1, 3].
    clave.huecos        cloze: lista, una entrada por hueco del enunciado:
                        {"letra": "A", "options": ["10 / 2", "5"], "correct_idx": [1]}
                        `options` son las opciones del hueco como lista de
                        textos (en el enunciado van unidas con « / ») y
                        `correct_idx` las posiciones (base 0) de las correctas
                        ([] = sin respuesta marcada).

Quién los produce: schema_adapter.adapt (de la salida estructurada de la IA),
mark_resolver (respuesta por marcas) y el editor (tarjetas.js / cloze.js).
Quién los usa: PreguntaMultichoice.resolver_correctas y Hueco.resolver, o sea
el validador, xml_builder y confianza. Solo valen si son válidos (enteros dentro
de rango) Y coinciden con el texto de la clave / del enunciado; si no, o si
faltan (historiales viejos, claves del documento en texto), se analiza el texto
como siempre (answer_matching.resolver_correctas_*).

Campos informativos (None por defecto, no se serializan mientras sean None; no
cambian ni bloquean ninguna respuesta ni el XML). Los llena pipeline.py:
    origen_respuesta  "documento" | "marca" | "ia" (confianza.py); el editor
                      añade "docente" cuando el profesor edita la respuesta y
                      "sugerida" cuando acepta la que propuso la IA (2.0).
                      Ausente en essay y en preguntas sin respuesta.
    confianza         "alta" | "media" | "baja" (confianza.py; no es lo mismo
                      que low_confidence, que sigue siendo la señal de la IA)
    pagina            int ≥ 1 (en el dict es data["page"], como siempre): la
                      verificada en el PDF por origen_pdf.py si se pudo ubicar
                      la pregunta; si no, la que dijo la IA
    recuadro          (x0, y0, x1, y1) como FRACCIONES 0–1 del ancho y del alto
                      de la página, origen arriba a la izquierda (origen_pdf.py);
                      ausente si la pregunta no se ubicó en el PDF. En el dict,
                      lista de 4.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Dict, List, NamedTuple, Optional, Tuple

from answer_matching import (
    TRUEFALSE_ALIAS, clave_de_columna, clave_de_huecos, find_cloze_brackets,
    indices_utilizables, normalizar_numero, resolver_correctas_cloze,
    resolver_correctas_multichoice, split_options,
)

SIN_RESPUESTA = "SIN_RESPUESTA"

ORIGENES = ("documento", "marca", "ia", "docente", "sugerida")
CONFIANZAS = ("alta", "media", "baja")


# ── Campos: cómo se lee y se escribe cada clave del dict ────────────────────

def _id(v: Any) -> Any:
    return v


def _es_str(v: Any) -> bool:
    return isinstance(v, str)


def _es_bool(v: Any) -> bool:
    return isinstance(v, bool)


def _es_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _es_numero(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _es_dict(v: Any) -> bool:
    return isinstance(v, dict)


def _es_origen(v: Any) -> bool:
    return isinstance(v, str) and v in ORIGENES


def _es_confianza(v: Any) -> bool:
    return isinstance(v, str) and v in CONFIANZAS


def _es_recuadro(v: Any) -> bool:
    return isinstance(v, (list, tuple)) and len(v) == 4 and all(_es_numero(x) for x in v)


def _es_lista_de_dicts(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(x, dict) for x in v)


def _es_lista_de_enteros(v: Any) -> bool:
    return isinstance(v, list) and all(_es_int(x) for x in v)


def _es_lista_de_textos(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


class Campo(NamedTuple):
    atributo: str
    clave: str
    valida: Callable[[Any], bool]
    entra: Callable[[Any], Any] = _id      # valor del dict → valor del atributo
    sale: Callable[[Any], Any] = _id       # valor del atributo → valor del dict
    solo: Optional[str] = None             # solo para ese tipo de pregunta


def _copia(v: Any) -> Any:
    return copy.deepcopy(v)


def _ordenar(d: Dict[str, Any], orden: List[str]) -> Dict[str, Any]:
    """Mismo orden de claves que tenía el dict original; las nuevas, al final."""
    out = {k: d[k] for k in orden if k in d}
    for k, v in d.items():
        if k not in out:
            out[k] = v
    return out


def _cargar(obj: Any, campos: Dict[str, Campo], d: Dict[str, Any], extra: Dict[str, Any],
            saltar: Tuple[str, ...] = ()) -> None:
    for k, v in d.items():
        if k in saltar:
            continue
        c = campos.get(k)
        if c is not None and c.valida(v):
            setattr(obj, c.atributo, c.entra(v))
        else:
            extra[k] = _copia(v)


def _volcar(obj: Any, campos: Tuple[Campo, ...], extra: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for c in campos:
        v = getattr(obj, c.atributo, None)
        if v is not None:
            out[c.clave] = c.sale(v)
    for k, v in extra.items():
        out.setdefault(k, _copia(v))   # lo tipado manda sobre un sobrante con la misma clave
    return out


# ── Imagen ──────────────────────────────────────────────────────────────────

_CAMPOS_IMAGEN = (
    Campo("name", "name", _es_str),
    Campo("mime", "mime", _es_str),
    Campo("b64", "b64", _es_str),
)
_IMAGEN_POR_CLAVE = {c.clave: c for c in _CAMPOS_IMAGEN}


@dataclass
class Imagen:
    """Imagen de una pregunta (data["images"]): nombre, tipo y contenido base64."""
    name: Optional[str] = None
    mime: Optional[str] = None
    b64: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    _orden: List[str] = field(default_factory=list, repr=False, compare=False)

    @classmethod
    def desde_dict(cls, d: Dict[str, Any]) -> "Imagen":
        im = cls(_orden=list(d.keys()))
        _cargar(im, _IMAGEN_POR_CLAVE, d, im.extra)
        return im

    def a_dict(self) -> Dict[str, Any]:
        return _ordenar(_volcar(self, _CAMPOS_IMAGEN, self.extra), self._orden)


def _imagenes_entra(v: List[Dict[str, Any]]) -> List[Imagen]:
    return [Imagen.desde_dict(x) for x in v]


def _imagenes_sale(v: List[Imagen]) -> List[Dict[str, Any]]:
    return [im.a_dict() for im in v]


# ── Hueco de un Cloze tal como lo guarda la clave ───────────────────────────

_CAMPOS_HUECO_CLAVE = (
    Campo("letra", "letra", _es_str),
    Campo("options", "options", _es_lista_de_textos, _copia),
    Campo("correct_idx", "correct_idx", _es_lista_de_enteros, _copia),
)
_HUECO_CLAVE_POR_CLAVE = {c.clave: c for c in _CAMPOS_HUECO_CLAVE}


@dataclass
class HuecoClave:
    """Un hueco en answer_key[num]["huecos"]: {"letra", "options", "correct_idx"}.
    `options` son las opciones como LISTA de textos (sin partir nada) y
    `correct_idx` las posiciones (base 0) de las correctas."""
    letra: Optional[str] = None
    options: Optional[List[str]] = None
    correct_idx: Optional[List[int]] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    _orden: List[str] = field(default_factory=list, repr=False, compare=False)

    @classmethod
    def desde_dict(cls, d: Dict[str, Any]) -> "HuecoClave":
        h = cls(_orden=list(d.keys()))
        _cargar(h, _HUECO_CLAVE_POR_CLAVE, d, h.extra)
        return h

    def a_dict(self) -> Dict[str, Any]:
        return _ordenar(_volcar(self, _CAMPOS_HUECO_CLAVE, self.extra), self._orden)


def _huecos_entra(v: List[Dict[str, Any]]) -> List[HuecoClave]:
    return [HuecoClave.desde_dict(x) for x in v]


def _huecos_sale(v: List[HuecoClave]) -> List[Dict[str, Any]]:
    return [h.a_dict() for h in v]


# ── Clave (entrada de answer_key) ───────────────────────────────────────────

_CAMPOS_CLAVE = (
    Campo("tipo", "type", _es_str),
    Campo("answer", "answer", _es_str),
    Campo("pairs", "pairs", _es_dict, _copia),
    Campo("from_key", "from_key", _es_bool),
    Campo("correct_idx", "correct_idx", _es_lista_de_enteros, _copia),
    Campo("huecos", "huecos", _es_lista_de_dicts, _huecos_entra, _huecos_sale),
)
_CLAVE_POR_CLAVE = {c.clave: c for c in _CAMPOS_CLAVE}


@dataclass
class Clave:
    """La respuesta correcta de una pregunta: answer_key[num].

    answer     texto de la respuesta, con las convenciones de siempre ("B | D",
               "1-a; 2-b", "A. x; B. y", SIN_RESPUESTA…)
    pairs      {"1": "a"} en emparejamiento
    from_key   True si salió de una clave explícita del documento
    correct_idx  multichoice: posiciones (base 0) de las opciones correctas
               (ver «Respuestas por índice» arriba)
    huecos     cloze: [HuecoClave], opciones y correctas de cada hueco por índice
    """
    tipo: Optional[str] = None
    answer: Optional[str] = None
    pairs: Optional[Dict[str, str]] = None
    from_key: Optional[bool] = None
    correct_idx: Optional[List[int]] = None
    huecos: Optional[List[HuecoClave]] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    _orden: List[str] = field(default_factory=list, repr=False, compare=False)

    @classmethod
    def desde_dict(cls, d: Dict[str, Any]) -> "Clave":
        c = cls(_orden=list(d.keys()))
        _cargar(c, _CLAVE_POR_CLAVE, d, c.extra)
        return c

    def a_dict(self) -> Dict[str, Any]:
        return _ordenar(_volcar(self, _CAMPOS_CLAVE, self.extra), self._orden)

    def __bool__(self) -> bool:
        """Una clave sin ningún dato equivale a «no hay clave» (el {} de antes)."""
        return bool(self.extra) or any(getattr(self, c.atributo) is not None for c in _CAMPOS_CLAVE)

    @property
    def texto(self) -> str:
        return self.answer if isinstance(self.answer, str) else ""


# ── Vistas tipadas (derivadas, no se guardan) ───────────────────────────────

@dataclass
class Opcion:
    letra: str
    texto: str
    correcta: bool


@dataclass
class Pareja:
    num: str            # elemento de la Columna A ("1")
    izquierda: str
    letra: str          # elemento de la Columna B ("a")
    derecha: str


@dataclass
class Hueco:
    """Un espacio «[A: correcta / otra]» de un Cloze con su respuesta de la clave."""
    letra: str
    inicio: int
    fin: int
    crudo: str                  # texto entre «Letra:» y «]», sin partir
    opciones: List[str]
    respuestas: List[str]       # lo que dice la clave para este hueco ([] si nada)
    # Posiciones (base 0) de las correctas cuando la clave las trae por índice
    # (y son válidas y coinciden con el texto); None = analizar `respuestas`.
    indices_clave: Optional[List[int]] = None

    def resolver(self) -> Tuple[List[int], List[Tuple[str, str]]]:
        """(índices de las opciones correctas sin repetir, fallos). Con índices
        en la clave se usan tal cual; si no, cada respuesta de la clave debe
        identificar UNA opción (la misma función que usaba el validador y el
        constructor); un fallo es (respuesta, motivo) con motivo «ninguna» o
        «ambigua». Nunca se adivina."""
        return resolver_correctas_cloze(self.opciones, self.respuestas, self.indices_clave)


def _colapsar(texto: str) -> str:
    return " ".join(str(texto or "").split())


def _hueco_de_estructura(
    estructura: Optional[List[HuecoClave]], letra: str, crudo: str, clave: str,
) -> Tuple[Optional[List[str]], Optional[List[int]]]:
    """(opciones, índices correctas) que da la estructura de la clave para el
    hueco `letra`, o (None, None) si no hay o no concuerda con el enunciado.
    Las opciones valen si, unidas con « / », son EXACTAMENTE lo que hay entre
    corchetes (si el enunciado se editó por otro lado, manda el enunciado). Los
    índices valen además si son válidos y la clave dice lo mismo en texto."""
    for h in estructura or []:
        if not isinstance(h.letra, str) or h.letra.upper() != letra.upper() or h.options is None:
            continue
        if crudo.strip() != " / ".join(h.options):
            return None, None
        usables = indices_utilizables(h.correct_idx, len(h.options))
        if usables is not None:
            dicho = f"{h.letra.upper()}. " + " | ".join(h.options[i] for i in usables)
            if _colapsar(dicho) not in _colapsar(clave):
                usables = None
        return list(h.options), usables
    return None, None


def huecos_de_cloze(texto: str, clave: str, estructura: Optional[List[HuecoClave]] = None) -> List[Hueco]:
    """Los huecos de un texto Cloze, cada uno con sus respuestas de `clave`
    («A. respuesta; B. resp1 | resp2»). Única fuente para validator y
    xml_builder. `estructura` (clave.huecos) trae las opciones de cada hueco
    como lista y sus correctas por índice: con ella una opción que contiene
    « / » o « | » no se parte. Sin ella (o si no concuerda con el enunciado),
    se parte el texto como siempre."""
    brackets = find_cloze_brackets(texto or "")
    por_hueco = clave_de_huecos(clave or "", len(brackets), brackets[0][2] if brackets else "")
    out: List[Hueco] = []
    for inicio, fin, letra, crudo in brackets:
        opciones, indices = _hueco_de_estructura(estructura, letra, crudo, clave or "")
        if opciones is None:
            out.append(Hueco(letra, inicio, fin, crudo, split_options(crudo),
                             list(por_hueco.get(letra.upper(), []))))
        elif indices is None:
            out.append(Hueco(letra, inicio, fin, crudo, opciones, list(por_hueco.get(letra.upper(), []))))
        else:
            out.append(Hueco(letra, inicio, fin, crudo, opciones, [opciones[i] for i in indices], indices))
    return out


# ── Pregunta ────────────────────────────────────────────────────────────────

_CAMPOS_PREGUNTA = (
    Campo("num", "num", _es_int),
    Campo("tipo", "type", _es_str),
    Campo("error", "error", _es_str),
    Campo("points", "points", _es_numero),
    Campo("raw_text", "raw_text", _es_str),
)
_PREGUNTA_POR_CLAVE = {c.clave: c for c in _CAMPOS_PREGUNTA}

# Orden canónico de "data" (el mismo en que schema_adapter los armaba).
_CAMPOS_DATA = (
    Campo("stem", "stem", _es_str),
    Campo("options", "options", _es_dict, _copia, solo="multichoice"),
    Campo("col_a", "col_a", _es_dict, _copia, solo="matching"),
    Campo("col_b", "col_b", _es_dict, _copia, solo="matching"),
    Campo("from_table", "from_table", _es_bool, solo="matching"),
    Campo("text", "text", _es_str),
    Campo("low_confidence", "low_confidence", _es_bool),
    Campo("pagina", "page", _es_int),
    Campo("comparte_imagen", "_comparte_imagen", _es_bool),
    Campo("feedback", "feedback", _es_str),
    Campo("images", "images", _es_lista_de_dicts, _imagenes_entra, _imagenes_sale),
    Campo("answer_from_marks", "answer_from_marks", _es_bool),
    Campo("color_review_hint", "color_review_hint", _es_bool),
    Campo("origen_respuesta", "origen_respuesta", _es_origen),
    Campo("confianza", "confianza", _es_confianza),
    Campo("recuadro", "recuadro", _es_recuadro, tuple, list),
)


def _campos_de(tipo: Optional[str]) -> Tuple[Campo, ...]:
    return tuple(c for c in _CAMPOS_DATA if c.solo in (None, tipo))


@dataclass
class Pregunta:
    """Una pregunta del examen. La clase base sirve para los tipos que no
    añaden campos propios (truefalse, essay, shortanswer, numerical y
    cualquier tipo desconocido); multichoice, matching y cloze tienen subclase.
    `Pregunta.desde_dict(d)` elige la clase según d["type"]."""

    TIPO: ClassVar[Optional[str]] = None

    num: Optional[int] = None
    tipo: Optional[str] = None
    stem: Optional[str] = None                 # enunciado (todos menos cloze)
    text: Optional[str] = None                 # enunciado con huecos (cloze)
    feedback: Optional[str] = None             # retroalimentación opcional
    images: Optional[List[Imagen]] = None
    points: Optional[float] = None             # puntaje que fijó el docente
    error: Optional[str] = None                # pregunta que el parser marcó como omitida
    raw_text: Optional[str] = None
    low_confidence: Optional[bool] = None
    answer_from_marks: Optional[bool] = None   # la respuesta salió de una marca (color…) en código
    color_review_hint: Optional[bool] = None   # conviene revisar la marca de color
    comparte_imagen: Optional[bool] = None     # marca interna de la IA (imagenes.asignar_imagenes)
    # Reservados (None = sin dato; no se serializan):
    origen_respuesta: Optional[str] = None
    confianza: Optional[str] = None
    pagina: Optional[int] = None               # data["page"]
    recuadro: Optional[Tuple[float, float, float, float]] = None

    respuesta: Optional[Clave] = None          # answer_key[num]; no forma parte del dict de la pregunta
    extra: Dict[str, Any] = field(default_factory=dict)         # claves desconocidas de la pregunta
    extra_data: Dict[str, Any] = field(default_factory=dict)    # claves desconocidas dentro de "data"
    tiene_data: bool = True
    data_invalida: bool = False                # "data" venía y no era un dict
    data_cruda: Any = None
    _orden: List[str] = field(default_factory=list, repr=False, compare=False)
    _orden_data: List[str] = field(default_factory=list, repr=False, compare=False)

    # ── dict ↔ modelo ──
    @classmethod
    def desde_dict(cls, d: Dict[str, Any]) -> "Pregunta":
        if not isinstance(d, dict):
            raise TypeError("Pregunta.desde_dict espera un dict")
        if cls is Pregunta:
            t = d.get("type")
            cls = _CLASES.get(t, Pregunta) if isinstance(t, str) else Pregunta
        p = cls()
        p._orden = list(d.keys())
        _cargar(p, _PREGUNTA_POR_CLAVE, d, p.extra, saltar=("data",))
        if "data" in d:
            datos = d["data"]
            if isinstance(datos, dict):
                p._orden_data = list(datos.keys())
                _cargar(p, {c.clave: c for c in cls._campos()}, datos, p.extra_data)
            else:
                p.data_invalida = True
                p.data_cruda = _copia(datos)
        else:
            p.tiene_data = False
        return p

    @classmethod
    def _campos(cls) -> Tuple[Campo, ...]:
        return _campos_de(cls.TIPO)

    def datos_a_dict(self) -> Dict[str, Any]:
        return _ordenar(_volcar(self, self._campos(), self.extra_data), self._orden_data)

    def a_dict(self) -> Dict[str, Any]:
        out = _volcar(self, _CAMPOS_PREGUNTA, self.extra)
        if self.data_invalida:
            out["data"] = _copia(self.data_cruda)
        else:
            datos = self.datos_a_dict()
            if self.tiene_data or datos:
                out["data"] = datos
        return _ordenar(out, self._orden)

    def clave_a_dict(self) -> Optional[Dict[str, Any]]:
        return self.respuesta.a_dict() if self.respuesta is not None else None

    # ── lectura cómoda ──
    @property
    def enunciado(self) -> str:
        return self.stem or self.text or ""

    @property
    def tiene_error(self) -> bool:
        """El parser la marcó como omitida (clave "error", con cualquier valor)."""
        return self.error is not None or "error" in self.extra

    @property
    def respuesta_texto(self) -> str:
        """Lo que dice answer_key[num]["answer"] ("" si no hay clave o no es texto)."""
        return self.respuesta.texto if self.respuesta is not None else ""

    @property
    def sin_respuesta(self) -> bool:
        r = self.respuesta_texto.strip()
        return not r or r.upper() == SIN_RESPUESTA

    @property
    def puntos_validos(self) -> Optional[float]:
        """El puntaje propio del editor si es un número usable (finito y ≥ 0);
        None si no llegó o no sirve (entonces rige el reparto por tipo)."""
        p = self.points
        if p is None or p != p or p in (float("inf"), float("-inf")) or p < 0:
            return None
        return p


@dataclass
class PreguntaMultichoice(Pregunta):
    TIPO: ClassVar[Optional[str]] = "multichoice"
    options: Optional[Dict[str, str]] = None   # {"A": "texto", "B": …}

    def resolver_correctas(self) -> Tuple[List[str], List[Tuple[str, str]]]:
        """(letras correctas sin repetir, fallos). La clave puede listar varias
        respuestas unidas con « | ». Cada una debe identificar UNA opción
        (answer_matching.resolver_opcion, la única fuente); un fallo es
        (respuesta, motivo) con motivo «ninguna» o «ambigua». Si la clave trae
        `correct_idx` (válido y de acuerdo con el texto de la clave) se usan
        esos índices y no se parte nada: así una opción como «x | y» sobrevive."""
        indices = self.respuesta.correct_idx if self.respuesta is not None else None
        return resolver_correctas_multichoice(self.options or {}, self.respuesta_texto, indices)

    def lista_opciones(self) -> List[Opcion]:
        letras, _ = self.resolver_correctas()
        return [Opcion(k, v, k in letras) for k, v in sorted((self.options or {}).items())]


@dataclass
class PreguntaTruefalse(Pregunta):
    TIPO: ClassVar[Optional[str]] = "truefalse"

    def es_verdadero(self) -> Optional[bool]:
        """True/False según la respuesta (con los alias de answer_matching.
        TRUEFALSE_ALIAS: «V», «true», «Falso»…); None si no es ninguna."""
        return TRUEFALSE_ALIAS.get(self.respuesta_texto.strip().lower())


@dataclass
class PreguntaMatching(Pregunta):
    TIPO: ClassVar[Optional[str]] = "matching"
    col_a: Optional[Dict[str, str]] = None     # {"1": "elemento"}
    col_b: Optional[Dict[str, str]] = None     # {"a": "elemento"}
    from_table: Optional[bool] = None          # la IA la armó desde una tabla

    @property
    def parejas(self) -> Dict[str, str]:
        """{"1": "a"} de la clave."""
        p = self.respuesta.pairs if self.respuesta is not None else None
        return p if isinstance(p, dict) else {}

    def letra_de(self, num_a: Any) -> Optional[str]:
        """La clave real de la Columna B que es pareja del elemento `num_a` de
        la A, sin distinguir mayúsculas; None si la clave no la resuelve."""
        return clave_de_columna(self.col_b or {}, self.parejas.get(str(num_a), ""))

    def lista_parejas(self) -> List[Pareja]:
        out: List[Pareja] = []
        col_a, col_b = self.col_a or {}, self.col_b or {}
        for a in sorted(col_a, key=lambda x: int(x) if str(x).isdigit() else str(x)):
            letra = self.letra_de(a)
            if letra is not None:
                out.append(Pareja(str(a), col_a[a], letra, col_b[letra]))
        return out


@dataclass
class PreguntaCloze(Pregunta):
    TIPO: ClassVar[Optional[str]] = "cloze"

    def huecos(self) -> List[Hueco]:
        estructura = self.respuesta.huecos if self.respuesta is not None else None
        return huecos_de_cloze(self.text or "", self.respuesta_texto, estructura)


@dataclass
class PreguntaEssay(Pregunta):
    TIPO: ClassVar[Optional[str]] = "essay"


@dataclass
class PreguntaShortanswer(Pregunta):
    TIPO: ClassVar[Optional[str]] = "shortanswer"


@dataclass
class PreguntaNumerical(Pregunta):
    TIPO: ClassVar[Optional[str]] = "numerical"

    def valor_numerico(self) -> Optional[str]:
        """La respuesta como número que entiende Moodle («3,5» → «3.5»); None si no lo es."""
        return normalizar_numero(self.respuesta_texto)


_CLASES: Dict[str, type] = {
    c.TIPO: c for c in (
        PreguntaMultichoice, PreguntaTruefalse, PreguntaMatching, PreguntaCloze,
        PreguntaEssay, PreguntaShortanswer, PreguntaNumerical,
    )
}


# ── Listas de preguntas ↔ (questions, answer_key) ───────────────────────────

def preguntas_desde_dicts(questions: List[Dict[str, Any]],
                          answer_key: Optional[Dict[Any, Any]] = None) -> List[Pregunta]:
    """Convierte la lista de dicts de siempre al modelo, con su `respuesta`
    tomada de `answer_key[num]` (una entrada que no es dict se trata como ausente)."""
    out: List[Pregunta] = []
    for q in questions:
        p = Pregunta.desde_dict(q)
        if answer_key is not None and p.num is not None:
            entrada = answer_key.get(p.num)
            if isinstance(entrada, dict):
                p.respuesta = Clave.desde_dict(entrada)
        out.append(p)
    return out


def preguntas_a_dicts(preguntas: List[Pregunta]) -> Tuple[List[Dict[str, Any]], Dict[int, Dict[str, Any]]]:
    """Lo inverso: (questions, answer_key) como los entrega adapt()."""
    questions = [p.a_dict() for p in preguntas]
    answer_key = {p.num: p.respuesta.a_dict() for p in preguntas
                  if p.num is not None and p.respuesta is not None}
    return questions, answer_key
