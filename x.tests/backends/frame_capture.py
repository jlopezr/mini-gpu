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

MASK = 0xFFFFFFFF
# Un frame son 16,7 ms: 200 ms de espera no se agotan salvo que el barrido esté
# detenido, y entonces seguir esperando tampoco arreglaría nada.
PENDING_WAIT_SECONDS = 0.2
ATTEMPTS = 3


class ImpreciseStop(RuntimeError):
    """La parada se pasó de largo y el frame pedido ya no existe."""


class Registers(NamedTuple):
    """Direcciones de byte de los registros de vídeo que usa la parada."""

    status: int
    swap_count: int
    fb_front: int
    fb_back: int


def swaps_since(read: Callable[[int], int], registers: Registers, base: int) -> int:
    return (read(registers.swap_count) - base) & MASK


def should_stop(read: Callable[[int], int], registers: Registers,
                  base: int, target: int) -> bool:
    return swaps_since(read, registers, base) >= target


def stop(client, timeout_seconds: float = 1.0):
    """Para el núcleo y espera a que lo esté; devuelve su estado.

    `halt_cpu` no es instantáneo en todas las versiones: leer el estado justo
    después puede dar «corriendo», y mientras el núcleo corre la depuración
    SIMT rechaza `select_context` con CommandRejected (visto en la 29, que
    tiene pipeline).
    """
    client.halt_cpu()
    limit = time.monotonic() + timeout_seconds
    while True:
        state = client.get_status()
        if state.halted or time.monotonic() >= limit:
            return state


def wait_no_pending(read: Callable[[int], int], registers: Registers) -> None:
    """Espera a que no quede un intercambio pendiente.

    Parar el núcleo no para el doble buffer: una petición de SWAP se atiende en
    la frontera de frame siguiente, que decide el barrido. Mientras siga
    pendiente, SWAP_COUNT y FB_FRONT pueden cambiar entre dos lecturas, y la
    cuenta y la base que se leen serían de instantes distintos.
    """
    limit = time.monotonic() + PENDING_WAIT_SECONDS
    while time.monotonic() < limit:
        if not read(registers.status) & 2:
            return


def frame_after_swap(client, read: Callable[[int], int], registers: Registers,
                    swaps: int, target: int | None, frame_bytes: int) -> bytes:
    """El frame completo que dejó el intercambio `objetivo`.

    Con `de_mas == 1` el buffer buscado ha pasado a ser el trasero, porque cada
    intercambio de más cambia de sitio el que quedó completo. La CPU/GPU está
    parada y su contenido ya no cambia, así que es una corrección de paridad,
    no una heurística. Con más no hay corrección posible.
    """
    extra = 0 if target is None else swaps - target
    if extra < 0 or extra > 1:
        raise ImpreciseStop(
            f"la parada pedía {target} intercambios y salieron {swaps}")
    address = registers.fb_back if extra else registers.fb_front
    return client.read_memory(read(address), frame_bytes)


def with_retries(execute: Callable[[], dict], attempts: int = ATTEMPTS) -> dict:
    """Repite un caso cuya parada salió imprecisa; el último intento propaga."""
    for attempt in range(attempts):
        try:
            return execute()
        except ImpreciseStop:
            if attempt == attempts - 1:
                raise
    raise AssertionError("inalcanzable")
