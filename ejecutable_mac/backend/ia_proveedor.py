"""
ia_proveedor.py — La capa de proveedor de IA: lo único que el resto de la app
sabe de «con quién hablamos».

Hasta la 1.8 Gemini estaba cableado en formatter.py y ayuda_ia.py. Ahora todo
el código de conversión (reintentos, elección entre intentos, botones de IA
del editor) habla con un ProveedorIA; cambiar de servicio (uno local, otro
proveedor) es agregar un módulo ia_<nombre>.py con una clase que implemente
`generar` y registrarlo en `_REGISTRO` (o con `registrar_proveedor`).

Qué contiene
  · Los datos que viajan: ParteIA (texto o imagen), SolicitudIA, RespuestaIA.
  · Los errores NORMALIZADOS (ErrorIA y subclases). Cada proveedor traduce
    sus fallos a estas clases; el bucle de reintentos (ia_reintentos.py) solo
    conoce estas, nunca un HTTP 429 ni una excepción de requests.
  · Los mensajes en español que ve el docente (MENSAJES_ES), que un proveedor
    puede sobrescribir.
  · `proveedor_actual()`: la factoría. Elige por la variable de entorno
    CONVERSOR_PROVEEDOR_IA (por defecto, config.IA_PROVEEDOR_POR_DEFECTO =
    «gemini»); un valor desconocido falla con un mensaje claro.

La cancelación (ia_cancelacion.py) no pasa por la interfaz: cada proveedor
consulta `cancelacion_actual()` del hilo, igual que antes.
"""

import base64
import io
import os
import threading
import weakref
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from config import IA_PROVEEDOR_POR_DEFECTO, IA_PROVEEDOR_VARIABLE

# Recibe el texto acumulado de la respuesta cada vez que llega un fragmento.
OnTexto = Optional[Callable[[str], None]]


# ══════════════════════════════════════════════════════════════════════════
# Errores normalizados
# ══════════════════════════════════════════════════════════════════════════
# Cada familia pide una reacción distinta al bucle de reintentos (ver
# ia_reintentos.generar_con_reintentos):
#   cuota / saturada / rechazada  → HTTP traducido por el proveedor
#   timeout / sin conexión        → fallos de red
#   vacía / cortada / interrumpida → respuestas técnicamente recibidas pero
#                                    inservibles
#   sin clave / configuración     → no se puede ni empezar

class ErrorIA(Exception):
    """Base de todos los fallos que un proveedor puede informar."""


class IASinClaveError(ErrorIA):
    """Falta la credencial del proveedor. `mensaje` es lo que lee el docente."""

    def __init__(self, mensaje: str):
        self.mensaje = mensaje
        super().__init__(mensaje)


class ErrorConfiguracionIA(ErrorIA):
    """La configuración del proveedor no sirve (p. ej. nombre desconocido)."""


class IAErrorHTTP(ErrorIA):
    """Respuesta de error del servicio. El texto lleva el código y el cuerpo
    completo de la respuesta, para el registro."""

    def __init__(self, code: int, body: str):
        self.code = code
        super().__init__(f"{code} {body}")


class IACuotaError(IAErrorHTTP):
    """Cuota agotada (429 en Gemini). El proveedor, que entiende el cuerpo de
    la respuesta, rellena: `diaria` (esperar no sirve de nada: se restablece
    otro día) y `espera_segundos` (cuánto pide esperar el servicio)."""

    def __init__(self, code: int, body: str, *, diaria: bool = False, espera_segundos: float = 30.0):
        super().__init__(code, body)
        self.diaria = diaria
        self.espera_segundos = espera_segundos


class IASaturadaError(IAErrorHTTP):
    """Servicio saturado o con un error interno (500/502/503/504 en Gemini)."""


class IARechazadaError(IAErrorHTTP):
    """Modelo inexistente, credencial inválida o petición mal formada
    (400/401/403/404 en Gemini). No se arregla reintentando."""


class IATimeoutError(ErrorIA, TimeoutError):
    """La respuesta no llegó a tiempo (tope total o silencio entre fragmentos)."""


class IASinConexionError(ErrorIA, ConnectionError):
    """No se pudo conectar con el servicio (sin internet, DNS, conexión caída)."""


class RespuestaVacia(ErrorIA, RuntimeError):
    """Sin texto: bloqueo de seguridad u otra respuesta vacía."""

    def __init__(self, finish: str, block: str):
        self.motivo = block or finish or "desconocido"
        super().__init__(f"Respuesta vacía de la IA (finish={finish or '-'}, block={block or '-'})")


class RespuestaCortada(ErrorIA, RuntimeError):
    """El stream terminó sin motivo de fin: la conexión se cortó a mitad."""


class RespuestaInterrumpida(ErrorIA, RuntimeError):
    """La IA terminó por un motivo distinto de STOP (SAFETY, RECITATION…)."""

    def __init__(self, motivo: str):
        self.motivo = motivo
        super().__init__(f"La IA interrumpió la respuesta (finish={motivo})")


# ══════════════════════════════════════════════════════════════════════════
# Mensajes que lee el docente
# ══════════════════════════════════════════════════════════════════════════
# Los de hoy, palabra por palabra. Un proveedor puede sobrescribir cualquiera
# poniendo la clave en su atributo `mensajes`.

MENSAJES_ES: Dict[str, str] = {
    "cuota_diaria": (
        "Se alcanzó el límite diario de uso del servicio de IA. "
        "Se restablece automáticamente cada día (medianoche, hora del Pacífico). "
        "Si esto ocurre seguido, conviene usar una API key con facturación activada."
    ),
    "cuota_persistente": "Se alcanzó el límite de uso del servicio de IA. Espera un minuto e intenta de nuevo.",
    "saturada": (
        "El servicio de IA de Google está saturado en este momento (no es un "
        "problema del documento). Intenta de nuevo en unos minutos."
    ),
    # 401/403: la clave no es válida o Google se la revocó. En esta app el
    # docente ES quien administra su propia clave.
    "clave_rechazada": (
        "Google rechazó tu clave de la API de Gemini (no es válida o fue "
        "revocada). Ábrela desde «Acerca de → API de Gemini» y pega una "
        "clave nueva de https://aistudio.google.com/apikey."
    ),
    "rechazada": (
        "El servicio de IA rechazó la solicitud (posible configuración "
        "inválida del modelo o del documento). Detalle técnico: error HTTP {code}."
    ),
    "sin_conexion": "No se pudo conectar con el servicio de IA de Google. Revisa tu conexión a internet e inténtalo de nuevo.",
}


# ══════════════════════════════════════════════════════════════════════════
# Datos de la conversación con la IA
# ══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ParteIA:
    """Un trozo de la entrada: texto, o una imagen (mime + base64)."""
    texto: Optional[str] = None
    mime: Optional[str] = None
    datos_b64: Optional[str] = None

    @property
    def es_imagen(self) -> bool:
        return self.datos_b64 is not None


def parte_texto(texto: str) -> ParteIA:
    return ParteIA(texto=texto)


def parte_imagen_b64(mime: str, datos_b64: str) -> ParteIA:
    return ParteIA(mime=mime, datos_b64=datos_b64)


# Partes de imagen ya codificadas, por imagen (mientras la imagen exista):
# codificar una página en WebP sin pérdida es lento, y la misma lista de
# páginas se enviaba de nuevo en cada reintento de calidad y en la llamada de
# preguntas omitidas. La entrada se borra sola cuando la imagen se libera.
_partes_imagen: dict = {}


def parte_imagen(img) -> ParteIA:
    """Una imagen PIL como ParteIA (WebP sin pérdida, en caché por imagen)."""
    clave = id(img)
    hit = _partes_imagen.get(clave)
    if hit is not None and hit[0]() is img:
        return hit[1]
    # WebP sin pérdida: el mismo formato que usaba el SDK de Gemini, para que
    # las páginas con imágenes (código en captura, marcas de color) lleguen
    # con la misma calidad que antes de dejar el SDK.
    buf = io.BytesIO()
    img.save(buf, format="webp", lossless=True)
    parte = ParteIA(mime="image/webp", datos_b64=base64.b64encode(buf.getvalue()).decode())
    try:
        def _olvidar(ref, clave=clave):
            actual = _partes_imagen.get(clave)
            if actual is not None and actual[0] is ref:
                _partes_imagen.pop(clave, None)
        _partes_imagen[clave] = (weakref.ref(img, _olvidar), parte)
    except TypeError:  # objeto sin soporte de weakref: simplemente no se guarda
        pass
    return parte


@dataclass
class SolicitudIA:
    """Todo lo que define UNA llamada lógica, para poder repetirla tal cual
    en cada reintento. `esquema` (un JSON Schema) pide salida JSON restringida;
    sin él, la salida es texto libre."""
    instruccion: str
    partes: List[ParteIA]
    temperatura: float = 0.0
    esquema: Optional[dict] = None
    max_tokens: Optional[int] = None


# Motivos de fin normalizados. Cualquier otro (SAFETY, RECITATION, OTHER…) se
# deja tal cual, en mayúsculas: es el «motivo» que se le muestra al docente.
FIN_STOP = "STOP"
FIN_MAX_TOKENS = "MAX_TOKENS"

_FIN_SINONIMOS = {
    "STOP": FIN_STOP, "END_TURN": FIN_STOP, "EOS": FIN_STOP, "COMPLETE": FIN_STOP, "COMPLETED": FIN_STOP,
    "MAX_TOKENS": FIN_MAX_TOKENS, "LENGTH": FIN_MAX_TOKENS, "MAX_OUTPUT_TOKENS": FIN_MAX_TOKENS,
    "MAX_LENGTH": FIN_MAX_TOKENS,
}


def normalizar_finish(motivo: Any) -> str:
    """Motivo de fin del proveedor → vocabulario común. «» (sin motivo) se
    conserva: significa que el proveedor no informó ninguno."""
    texto = str(motivo or "").strip().upper()
    return _FIN_SINONIMOS.get(texto, texto)


@dataclass
class RespuestaIA:
    """Lo que devuelve `generar`. finish_reason ya viene normalizado
    (ver normalizar_finish)."""
    text: str
    finish_reason: str
    prompt_tokens: int = 0
    output_tokens: int = 0

    @property
    def texto(self) -> str:
        return self.text

    @property
    def uso(self) -> Dict[str, int]:
        return {"prompt_tokens": self.prompt_tokens, "output_tokens": self.output_tokens}


# ══════════════════════════════════════════════════════════════════════════
# La interfaz
# ══════════════════════════════════════════════════════════════════════════

class ProveedorIA:
    """Contrato que implementa cada proveedor.

    `generar` hace UNA llamada (sin reintentos: eso lo hace ia_reintentos) y
    devuelve la respuesta completa, avisando con `on_texto(texto_acumulado)`
    de cada fragmento si el proveedor transmite en streaming. Debe:
      · lanzar solo errores de este módulo (ErrorIA y subclases) o
        ConversionCancelada; nunca excepciones de su librería de red;
      · consultar `ia_cancelacion.cancelacion_actual()`: comprobarla al
        empezar, cada fragmento, y registrar el cierre de su conexión para que
        Cancelacion.cancelar() la corte;
      · lanzar RespuestaVacia (sin texto), RespuestaCortada (sin motivo de fin)
        y devolver finish_reason normalizado.
    """

    #: nombre con el que se registra (el de CONVERSOR_PROVEEDOR_IA)
    nombre: str = "?"
    #: sobrescribe entradas de MENSAJES_ES
    mensajes: Dict[str, str] = {}

    def comprobar_listo(self) -> None:
        """Lanza IASinClaveError si falta la credencial. Por defecto, nada."""

    def generar(self, partes: List[ParteIA], *, instruccion: str = "", esquema: Optional[dict] = None,
                temperatura: float = 0.0, max_tokens: Optional[int] = None, stream: bool = True,
                on_texto: OnTexto = None, timeout: int = 180) -> RespuestaIA:
        raise NotImplementedError

    def mensaje(self, clave: str, **datos: Any) -> str:
        texto = self.mensajes.get(clave) or MENSAJES_ES[clave]
        return texto.format(**datos) if datos else texto


# ══════════════════════════════════════════════════════════════════════════
# Selección del proveedor
# ══════════════════════════════════════════════════════════════════════════

def _crear_gemini() -> ProveedorIA:
    # Import dentro de la función (y explícito, no por nombre en un texto):
    # así PyInstaller ve el módulo y lo empaqueta.
    from ia_gemini import GeminiProveedor
    return GeminiProveedor()


# nombre → función sin argumentos que crea el proveedor. Para agregar uno:
# módulo ia_<nombre>.py + una línea aquí.
_REGISTRO: Dict[str, Callable[[], ProveedorIA]] = {"gemini": _crear_gemini}
_instancias: Dict[str, ProveedorIA] = {}
_lock = threading.Lock()


def registrar_proveedor(nombre: str, fabrica: Callable[[], ProveedorIA]) -> None:
    """Agrega (o reemplaza) un proveedor. Lo usan las pruebas para enchufar uno falso."""
    nombre = nombre.strip().lower()
    with _lock:
        _REGISTRO[nombre] = fabrica
        _instancias.pop(nombre, None)


def quitar_proveedor(nombre: str) -> None:
    nombre = nombre.strip().lower()
    with _lock:
        _REGISTRO.pop(nombre, None)
        _instancias.pop(nombre, None)


def proveedores_disponibles() -> List[str]:
    with _lock:
        return sorted(_REGISTRO)


def nombre_configurado() -> str:
    """El proveedor pedido: la variable de entorno, o el de config."""
    valor = os.environ.get(IA_PROVEEDOR_VARIABLE, "").strip()
    return (valor or IA_PROVEEDOR_POR_DEFECTO).strip().lower()


def proveedor_actual() -> ProveedorIA:
    """El proveedor de IA que usa la app ahora mismo (por defecto, Gemini).
    Lanza ErrorConfiguracionIA si el nombre configurado no existe."""
    nombre = nombre_configurado()
    with _lock:
        inst = _instancias.get(nombre)
        if inst is not None:
            return inst
        fabrica = _REGISTRO.get(nombre)
        if fabrica is None:
            raise ErrorConfiguracionIA(
                f"Proveedor de IA desconocido: «{nombre}» (variable {IA_PROVEEDOR_VARIABLE}). "
                f"Los disponibles son: {', '.join(sorted(_REGISTRO))}."
            )
        inst = _instancias[nombre] = fabrica()
        return inst
