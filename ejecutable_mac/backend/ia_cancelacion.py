"""
ia_cancelacion.py — Cancelación de una conversión que usa la IA.

«Cancelar» en la pantalla de carga cierra la conexión del navegador, pero el
hilo que llama a la IA seguía trabajando (y ocupando uno de los 2 cupos de
conversión) hasta terminar la llamada y sus reintentos. Cada conversión
tiene ahora una Cancelacion: main.py la activa al desconectarse el cliente
y la capa de IA la revisa en cada línea del stream, en cada espera de
reintento y antes de cada llamada. Va por hilo (threading.local) para no
cambiar la firma de todas las funciones intermedias.

No depende de ningún proveedor: cualquiera (ia_gemini, uno local…) usa lo
mismo. formatter.py re-exporta estos nombres.
"""

import threading
import time
from typing import Optional


class ConversionCancelada(Exception):
    """El docente canceló (o cerró) la conversión: se abandona sin reintentos."""


class Cancelacion:
    def __init__(self) -> None:
        self._evento = threading.Event()
        self._lock = threading.Lock()
        self._cierres: list = []

    @property
    def cancelada(self) -> bool:
        return self._evento.is_set()

    def cancelar(self) -> None:
        """Activa la cancelación y corta cualquier conexión en curso."""
        self._evento.set()
        with self._lock:
            cierres, self._cierres = self._cierres, []
        for cierre in cierres:
            try:
                cierre()
            except Exception:  # noqa: BLE001
                pass

    def comprobar(self) -> None:
        if self._evento.is_set():
            raise ConversionCancelada()

    def esperar(self, segundos: float) -> None:
        """Como time.sleep, pero se interrumpe al cancelar."""
        if self._evento.wait(max(0.0, segundos)):
            raise ConversionCancelada()

    def registrar(self, cierre) -> None:
        """Función que corta una conexión abierta; si ya se canceló, se
        ejecuta de inmediato y se lanza ConversionCancelada."""
        with self._lock:
            if not self._evento.is_set():
                self._cierres.append(cierre)
                return
        try:
            cierre()
        except Exception:  # noqa: BLE001
            pass
        raise ConversionCancelada()

    def quitar(self, cierre) -> None:
        with self._lock:
            if cierre in self._cierres:
                self._cierres.remove(cierre)


_cancel_local = threading.local()


def usar_cancelacion(cancelacion: Optional[Cancelacion]) -> None:
    """Asocia una Cancelacion al hilo actual (None la quita)."""
    _cancel_local.actual = cancelacion


def cancelacion_actual() -> Optional[Cancelacion]:
    return getattr(_cancel_local, "actual", None)


def comprobar_cancelacion() -> None:
    """Lanza ConversionCancelada si la conversión de este hilo se canceló."""
    c = cancelacion_actual()
    if c is not None:
        c.comprobar()


def esperar(segundos: float) -> None:
    """Espera `segundos` (interrumpible si el hilo tiene una Cancelacion)."""
    c = cancelacion_actual()
    if c is not None:
        c.esperar(segundos)
    else:
        time.sleep(max(0.0, segundos))
