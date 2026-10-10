"""Capturar el frame de un programa de vídeo: dónde está y cómo parar tras N intercambios.

**Dónde está.** Los programas de vídeo del repositorio ponen el framebuffer ellos
mismos al arrancar, con `STORE` a `FB_FRONT` y `FB_BACK`: las bases arrancan a
cero y el arnés ya no las prepara. Durante un tiempo lo hizo, solo por dos casos
(`band` y `bounce`), y tapaba un problema de verdad --solo el reset de la placa
reinicia las bases, así que un caso con un número impar de intercambios se las
pasaba cruzadas al siguiente--. Lo que queda son las dos direcciones que los
programas usan de hecho (`FB_FRONT` y `FB_BACK`, abajo), para que las pruebas que
necesitan mirar el framebuffer no dupliquen el número. Están separadas por
0x25800, justo un frame de 320x240 en RGB565, y alineadas a 16 como exige §9.2.
Si un programa elige otra dirección no pasa nada: los backends capturan el frame
leyendo `FB_FRONT` de la placa o del dispositivo, nunca una dirección fija.

**Cómo parar.** Es lo que comparten `fpga_cpu.py` y `fpga_gpu.py`. Antes lo hacía solo el de CPU y
la GPU esperaba a un HALT que un programa de vídeo no ejecuta nunca, así que
los casos `run_until: {swap: N}` se omitían en placa.

Hay dos formas de parar, según lo que declare el RTL (`tools/capabilities.json`):

  - `halt_on_swap`: `HALT_AT` cuenta intercambios (mmio.md §9.6), así que el
    backend lo arma y el núcleo se para solo, en el ciclo del intercambio N.
    Lo tienen las CPU con vídeo; esa rama vive en `fpga_cpu.py`.
  - sin ella, que es hoy el caso de las GPU --donde `HALT_AT` ni existe--: el
    host sondea SWAP_COUNT y manda parar al llegar a N. Es lo que hay en este
    módulo (`hay_que_parar`, `parar`).

El sondeo llega tarde por lo que tarda el viaje por el puerto serie, y en ese
hueco el programa puede pedir otro intercambio. Dos intercambios de más ya no
tienen arreglo --el buffer que se buscaba se ha vuelto a pintar-- así que
`frame_tras_swap` lo declara con `ParadaImprecisa` en lugar de devolver un
frame que falla en un píxel y parece ruido; `con_reintentos` repite el caso. La
comprobación sirve a los dos caminos: con la alarma de hardware el hueco es de
unos ciclos, pero no se da por hecho que sea cero.
"""

from __future__ import annotations

import time
from typing import Callable, NamedTuple

FB_FRONT = 0x0100_0000
FB_BACK = 0x0102_5800

MASCARA = 0xFFFFFFFF
# Un frame son 16,7 ms: 200 ms de espera no se agotan salvo que el barrido esté
# detenido, y entonces seguir esperando tampoco arreglaría nada.
ESPERA_PENDIENTE_SEGUNDOS = 0.2
INTENTOS = 3


class ParadaImprecisa(RuntimeError):
    """La parada se pasó de largo y el frame pedido ya no existe."""


class Registros(NamedTuple):
    """Direcciones de byte de los registros de vídeo que usa la parada."""

    status: int
    swap_count: int
    fb_front: int
    fb_back: int


def swaps_desde(leer: Callable[[int], int], registros: Registros, base: int) -> int:
    return (leer(registros.swap_count) - base) & MASCARA


def hay_que_parar(leer: Callable[[int], int], registros: Registros,
                  base: int, objetivo: int) -> bool:
    return swaps_desde(leer, registros, base) >= objetivo


def parar(client, timeout_seconds: float = 1.0):
    """Para el núcleo y espera a que lo esté; devuelve su estado.

    `halt_cpu` no es instantáneo en todas las versiones: leer el estado justo
    después puede dar «corriendo», y mientras el núcleo corre la depuración
    SIMT rechaza `select_context` con CommandRejected (visto en la 29, que
    tiene pipeline).
    """
    client.halt_cpu()
    limite = time.monotonic() + timeout_seconds
    while True:
        estado = client.get_status()
        if estado.halted or time.monotonic() >= limite:
            return estado


def esperar_sin_pendiente(leer: Callable[[int], int], registros: Registros) -> None:
    """Espera a que no quede un intercambio pendiente.

    Parar el núcleo no para el doble buffer: una petición de SWAP se atiende en
    la frontera de frame siguiente, que decide el barrido. Mientras siga
    pendiente, SWAP_COUNT y FB_FRONT pueden cambiar entre dos lecturas, y la
    cuenta y la base que se leen serían de instantes distintos.
    """
    limite = time.monotonic() + ESPERA_PENDIENTE_SEGUNDOS
    while time.monotonic() < limite:
        if not leer(registros.status) & 2:
            return


def frame_tras_swap(client, leer: Callable[[int], int], registros: Registros,
                    swaps: int, objetivo: int | None, frame_bytes: int) -> bytes:
    """El frame completo que dejó el intercambio `objetivo`.

    Con `de_mas == 1` el buffer buscado ha pasado a ser el trasero, porque cada
    intercambio de más cambia de sitio el que quedó completo. La CPU/GPU está
    parada y su contenido ya no cambia, así que es una corrección de paridad,
    no una heurística. Con más no hay corrección posible.
    """
    de_mas = 0 if objetivo is None else swaps - objetivo
    if de_mas < 0 or de_mas > 1:
        raise ParadaImprecisa(
            f"la parada pedía {objetivo} intercambios y salieron {swaps}")
    direccion = registros.fb_back if de_mas else registros.fb_front
    return client.read_memory(leer(direccion), frame_bytes)


def con_reintentos(ejecutar: Callable[[], dict], intentos: int = INTENTOS) -> dict:
    """Repite un caso cuya parada salió imprecisa; el último intento propaga."""
    for intento in range(intentos):
        try:
            return ejecutar()
        except ParadaImprecisa:
            if intento == intentos - 1:
                raise
    raise AssertionError("inalcanzable")
