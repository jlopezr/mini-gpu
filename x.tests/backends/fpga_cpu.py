"""Backend de FPGA basado en el cliente del monitor UART."""

from __future__ import annotations

import time
from pathlib import Path

from . import board, frame_capture
from .common import capabilities_of
from .fpga_common import (
    REPOSITORY as _REPOSITORY, MonitorBackend, build_versions, missing_with_hint,
    region_reason, write_register as _write_register,
)

from tools.rtl_facts import (  # noqa: E402 (fpga_common ya puso REPOSITORY en sys.path)
    backend_from_rtl,
    capabilities_from_rtl,
    monitor_cycle_counters_from_rtl,
)


# La lista de versiones no se declara aquí: sale de los `version.json` de las
# carpetas (ver `fpga_common.build_versions`). Registrar una versión nueva es
# soltar `version.json` en su carpeta; no hace falta tocar este fichero.
#
# `R0` CABLEADO A CERO NO ES UNA CAPACIDAD. Lo fue mientras solo lo tenia la 21;
# con el backport hecho lo tienen las seis versiones, asi que paso a ser una
# regla de la MiniISA --1.isa/isa.md seccion 1-- y dejo de ser algo que un
# backend pueda o no tener. La capacidad `zero_register` ya no existe.
def _capabilities(directory: Path, signals: dict) -> tuple:
    capabilities = capabilities_from_rtl(directory, signals)
    # `input_device` (el RTL tiene INPUT) implica `input` (el arnes sabe
    # alimentarlo): el guion se reproduce por el monitor, conservando el
    # orden de los eventos y no su instante. Ver `play_on_board`.
    if "input_device" in capabilities and "input" not in capabilities:
        capabilities = capabilities + ("input",)
    return capabilities


def _extra(directory: Path, entry: dict) -> None:
    if monitor_cycle_counters_from_rtl(directory):
        entry["monitor_cycle_counters"] = True

VERSIONS = build_versions(
    lambda directory: backend_from_rtl(directory) == "cpu", _capabilities, _extra)
DEFAULT_VERSION = "alu"

# Registros de video, en direcciones de byte. Solo los usan las versiones que
# declaran `video`; estan aqui y no en el monitor porque son del sistema, no
# del protocolo.
# Las direcciones salen del mapa generado (`1.isa/mmio.md` §20), no escritas a
# mano: eran una cuarta copia junto al decodificador Verilog, `monitor.py` y
# cada `.asm`. De momento es el mapa de TRANSICION --bases de v2, offsets de
# v1-- porque `video_registers.v` aun no ha movido sus registros.
#
# AVISO PARA LAS OTRAS NUEVE CARPETAS: este fichero lo comparten todos los
# prototipos con placa. Al cambiarlo, los bitstreams de 6, 10, 16, 18 y 19
# --que siguen en v1-- dejan de responder donde el arnes los busca, hasta que
# se migren. Es sabido y aceptado, no una regresion.
from tools.mmio_map import (  # noqa: E402
    MMIO_VIDEO_BASE, MMIO_VIDEO_FB_FRONT_OFF, MMIO_VIDEO_FB_BACK_OFF,
    MMIO_VIDEO_STATUS_OFF, MMIO_VIDEO_SWAP_COUNT_OFF, MMIO_VIDEO_HALT_AT_OFF,
    MMIO_VIDEO_CTRL_OFF, MMIO_CPU_PERF_BASE, MMIO_PERF_CYCLES_OFF,
    MMIO_PERF_RETIRED_OFF, MMIO_VIDEO_FRAME_COUNT_OFF,
    MMIO_VIDEO_HALT_TARGET_OFF,
    MMIO_PERF_IMEM_HITS_OFF, MMIO_PERF_IMEM_MISSES_OFF, MMIO_PERF_MEM_TX_OFF,
    MMIO_PERF_STALL_MEM_OFF, MMIO_PERF_STALL_FETCH_OFF, MMIO_PERF_STALL_MMIO_OFF,
)

VIDEO_FB_FRONT = MMIO_VIDEO_BASE + MMIO_VIDEO_FB_FRONT_OFF
VIDEO_FB_BACK = MMIO_VIDEO_BASE + MMIO_VIDEO_FB_BACK_OFF
VIDEO_STATUS = MMIO_VIDEO_BASE + MMIO_VIDEO_STATUS_OFF
VIDEO_SWAP_COUNT = MMIO_VIDEO_BASE + MMIO_VIDEO_SWAP_COUNT_OFF
VIDEO_HALT_AT = MMIO_VIDEO_BASE + MMIO_VIDEO_HALT_AT_OFF
# En v2 los frames tienen registro propio de 32 bits. Ya NO estan en STATUS[31:16]:
# leerlos de ahi da cero siempre, que es lo que este fichero hacia hasta hoy.
VIDEO_FRAME_COUNT = MMIO_VIDEO_BASE + MMIO_VIDEO_FRAME_COUNT_OFF
# Quien se para cuando salta la alarma. Arranca a CERO, o sea que armar HALT_AT
# y no escribir esto --que era suficiente en v1-- no detiene a nadie.
VIDEO_HALT_TARGET = MMIO_VIDEO_BASE + MMIO_VIDEO_HALT_TARGET_OFF
VIDEO_HALT_TARGET_CPU = 1 << 0
VIDEO_CTRL = MMIO_VIDEO_BASE + MMIO_VIDEO_CTRL_OFF
# Modos de salida. Tras el reset la placa arranca en PATTERN --ver
# video_registers.v-- y el arnes enciende SCANOUT antes de cada caso de video.
MODE_BLANK = 0
MODE_PATTERN = 1
MODE_SCANOUT = 2
# Contadores de rendimiento. Los MISMOS offsets que en la MiniGPU: el bloque de
# CPU es un prefijo del de GPU, con CYCLES en +0x00 y RETIRED en +0x04.
PERF_CYCLES = MMIO_CPU_PERF_BASE + MMIO_PERF_CYCLES_OFF
PERF_RETIRED = MMIO_CPU_PERF_BASE + MMIO_PERF_RETIRED_OFF
# Los contadores de espera (capacidad `perf_stalls`, mmio.md §13.2). Con
# CYCLES se reparte el tiempo: CYCLES = calculo + STALL_MEM + STALL_MMIO, y de
# STALL_MEM se separan la busqueda (STALL_FETCH) y los datos (el resto).
PERF_STALL_COUNTERS = {
    "imem_hits": MMIO_CPU_PERF_BASE + MMIO_PERF_IMEM_HITS_OFF,
    "imem_misses": MMIO_CPU_PERF_BASE + MMIO_PERF_IMEM_MISSES_OFF,
    "mem_tx": MMIO_CPU_PERF_BASE + MMIO_PERF_MEM_TX_OFF,
    "stall_mem": MMIO_CPU_PERF_BASE + MMIO_PERF_STALL_MEM_OFF,
    "stall_fetch": MMIO_CPU_PERF_BASE + MMIO_PERF_STALL_FETCH_OFF,
    "stall_mmio": MMIO_CPU_PERF_BASE + MMIO_PERF_STALL_MMIO_OFF,
}
VIDEO_REGISTERS = frame_capture.Registers(
    status=VIDEO_STATUS, swap_count=VIDEO_SWAP_COUNT,
    fb_front=VIDEO_FB_FRONT, fb_back=VIDEO_FB_BACK)
# RGB565 de 320x240.
FRAME_BYTES = 320 * 240 * 2


# Los registros de video son de 32 bits, pero el monitor accede byte a byte:
# una palabra son cuatro comandos (`write_register`, en fpga_common).
def _read_register(client, address: int, word: bool = False) -> int:
    """Con READ_WORD cuando el monitor lo tiene; si no, cuatro READ_BYTE.

    La diferencia no es de velocidad sino de coherencia: hay registros que
    siguen vivos con el nucleo parado -STATUS lleva el contador de frames en
    los bits altos, y el scanout cuelga de `reset`, no de `core_reset`-, asi
    que entre el primer byte y el cuarto pasa cerca de un milisegundo y el
    valor montado puede no haber existido nunca. READ_WORD es una sola
    transaccion de bus, y por tanto atomico por construccion.

    El camino de bytes se queda porque no todos los prototipos tienen el
    comando: la capacidad se detecta del RTL, no se supone.
    """
    if word:
        return client.read_word(address)
    return int.from_bytes(
        bytes(client.read_byte(address + offset) for offset in range(4)),
        "little")


def capabilities(version: str = DEFAULT_VERSION) -> frozenset:
    """Lo que tiene esta versión, con las implicaciones ya expandidas."""
    return capabilities_of(VERSIONS, version)


def incompatibility(case: dict, version: str = DEFAULT_VERSION) -> str | None:
    """Rechaza un caso que no cabe en el mapa, antes de tocar la placa.

    El mapa lo declara el `monitor.py` de cada versión, que es quien lo
    implementa; aquí solo se lee su constante, sin abrir el puerto.
    """
    return (missing_with_hint(case, VERSIONS, version)
            or region_reason(case, VERSIONS, version, "fpga-cpu"))


class FpgaCpuBackend(MonitorBackend):
    """Carga, ejecuta e inspecciona un caso en la FPGA real."""

    ARCHITECTURE = "cpu"
    NAME = "fpga-cpu"
    VERSIONS = VERSIONS
    DEFAULT_VERSION = DEFAULT_VERSION

    def _run_once(
        self,
        program: bytes,
        initial_memory: list[tuple[int, bytes]],
        register_numbers: set[int],
        memory_ranges: list[tuple[int, int]],
        max_instructions: int,
        timeout_seconds: float,
        video: dict | None = None,
        stdin: bytes = b"",
        input_script: str | None = None,
    ) -> dict:
        del max_instructions  # La FPGA se limita mediante timeout de pared.
        device_caps = capabilities(self.version)
        has_capture = "frame_capture" in device_caps
        has_video = "video" in device_caps
        # Los registros de video se leen de una pieza donde se pueda: STATUS
        # lleva el contador de frames, que avanza aunque el nucleo este parado.
        has_word = "read_word" in device_caps

        with self.connect() as client:
            def read_register(address: int) -> int:
                return _read_register(client, address, has_word)

            client.reset_cpu()

            # Las regiones que el caso va a volcar se ponen a CERO antes de
            # nada. El simulador construye su memoria con `bytearray(tamano)`,
            # o sea toda a cero, y los `expected.hex` lo dan por hecho: el de
            # `bresenham-circles-core` tiene 673 de sus 896 palabras a cero, que
            # son las que el programa NO escribe. En la placa esas palabras
            # llevan lo que dejara el caso anterior, porque `reset_cpu` no toca
            # la SDRAM.
            #
            # Medido: `bresenham-lines-core` a solas daba 47 en 0x00100008, y
            # despues de `bresenham-circles-core` daba 32. Poniendo la region a
            # cero a mano, los dos pasan. El sintoma era un valor que cambiaba
            # en cada ejecucion y que no se parecia a su causa.
            #
            # Es propiedad del ARNES, igual que encender SCANOUT o borrar el
            # underflow: el caso declara lo que espera, no como dejar la placa
            # preparada. Y afecta a los 31 casos con `memory_dumps`, no solo a
            # los dos que fallaban: a los otros el residuo les cuadraba por
            # suerte, que es peor que fallar.
            #
            # Va ANTES del programa y de `initial_memory` para que los dos
            # ganen si alguna region los solapa.
            for address, size in memory_ranges:
                if size:
                    client.write_memory(address, bytes(size))

            client.write_memory(0, program)

            for address, data in initial_memory:
                client.write_memory(address, data)

            # Parada del ARNES tras N intercambios. Cero = no se usa. Se arma
            # mas abajo solo si el caso pide `run_until: {swap: N}` y la carpeta
            # tiene `frame_capture`.
            stop_after_swaps = 0
            by_hardware = False
            # SWAP_COUNT y FRAME_COUNT son del DISPOSITIVO DE VIDEO, no de la
            # CPU: `reset_cpu` no los toca y solo el reset de la placa los pone a
            # cero. Asi que llevan la cuenta acumulada de toda la sesion --se han
            # visto valores de cinco cifras-- y hay que medir contra la linea
            # base de ESTE caso. El simulador no tiene el problema porque
            # construye un dispositivo nuevo por caso, y por eso sus contadores
            # son per-caso; estos hay que restarlos para que sean comparables.
            swaps_base = 0
            frames_base = 0

            if video:
                # Borrar el underflow de la ejecucion anterior ANTES de
                # arrancar. Es pegajoso, asi que sin esto el primer caso que lo
                # provoque hace fallar a todos los demas de la sesion y no se
                # sabe cual fue. En las versiones sin `frame_capture` STATUS es
                # de solo lectura y la escritura se ignora, que es inofensivo.
                _write_register(client, VIDEO_STATUS, 1)
                # Las bases vuelven a CERO, que es su valor de reset, y no a
                # una direccion util: el framebuffer lo elige el programa. Antes
                # las ponia en las del arnes, por `band` y `bounce`, los dos
                # unicos que las heredaban, y eso tapaba que los programas
                # dependian de ellas. Cero no tapa nada. Hace falta porque solo
                # el reset de la placa las reinicia --un caso que dejara un
                # numero IMPAR de intercambios se las pasaba cruzadas al
                # siguiente-- y el simulador, que construye un dispositivo nuevo
                # por caso, siempre arranca en cero. Los casos que no escriben
                # las bases (`double-buffer`, `fb-desalineada`) las leen y
                # acaban con `fb_front` heredado: sin esto el diferencial lo
                # comparaba contra 0 y fallaba aunque cada backend pasara solo.
                # Va antes de encender el scanout, para que el barrido no lea de
                # una base a medio escribir.
                _write_register(client, VIDEO_FB_FRONT, 0)
                _write_register(client, VIDEO_FB_BACK, 0)
                # Y encender el scanout, porque tras el reset el modo es
                # PATTERN. No es cosmetica: en PATTERN el barrido NO lee la
                # memoria, asi que no puede haber underflow y un
                # `expect.video.underflow: false` pasaria sin comprobar nada.
                # Lo que este arnes mide --si el camino de datos alimenta al
                # barrido a tiempo-- solo existe en SCANOUT.
                #
                # Se escribe aqui y no se le pide al programa porque es
                # propiedad del ARNES: el caso declara lo que espera, no como
                # dejar la placa preparada. Un programa puede cambiarlo despues
                # si lo que prueba es el propio cambio de modo.
                _write_register(client, VIDEO_CTRL, MODE_SCANOUT)
                # HALT_AT y SWAP_COUNT solo existen donde hay `frame_capture`.
                # Ya no es un problema de ALCANCE --desde la fase 3.5 las cuatro
                # decodifican la pagina MMIO entera y un registro que no existe
                # lee cero y se traga la escritura-- pero armar una parada que
                # nadie va a atender seria mentirle al caso.
                if has_capture:
                    # `run_until: {swap: N}` es una condicion de OBSERVACION del
                    # arnes --«captura el frame tras el intercambio N»-- y hay
                    # dos formas de pararla, segun lo que declare el RTL:
                    #
                    #   halt_on_swap  HALT_AT cuenta intercambios (§9.6): se
                    #                 arma y la CPU se para sola, en el ciclo
                    #                 del intercambio N. Es exacto.
                    #   sin ella      HALT_AT cuenta FRAMES --asi lo dejo la
                    #                 v2--, que no es lo mismo: el numero de
                    #                 swaps al disparar depende de lo rapido
                    #                 que dibuje el programa. Se sondea
                    #                 SWAP_COUNT desde el host (frame_capture.py).
                    #
                    # Por el segundo camino escribir los swaps en HALT_AT era
                    # ademas incorrecto por partida doble: contaba frames, y
                    # HALT_TARGET arranca a cero, asi que no paraba a nadie. El
                    # sintoma era un timeout de 20-30 s por caso de video, que
                    # no se parece a la causa.
                    stop_after_swaps = video.get("run_until_swap") or 0
                    by_hardware = bool(
                        stop_after_swaps and "halt_on_swap" in device_caps)
                    # Los dos a cero, siempre, tambien cuando el caso no usa la
                    # alarma: solo el reset de la placa los reinicia y un caso
                    # heredaria la alarma del anterior.
                    _write_register(client, VIDEO_HALT_AT, 0)
                    _write_register(client, VIDEO_HALT_TARGET, 0)
                    # La linea base, despues de desarmar y justo antes de
                    # arrancar. Sin esto la condicion `swaps >= N` es cierta en
                    # el primer sondeo --el contador ya vale miles-- y el caso
                    # para sin haber dibujado nada: nueve frames en blanco que
                    # fallan en el pixel 0. Con la alarma de hardware sirve
                    # para el informe: armar no toca SWAP_COUNT.
                    swaps_base = _read_register(client, VIDEO_SWAP_COUNT,
                                                has_word)
                    frames_base = _read_register(client, VIDEO_FRAME_COUNT,
                                                 has_word)
                    if by_hardware:
                        # HALT_TARGET primero: arranca a cero y sin el bit de
                        # CPU la alarma se consume sin parar a nadie. Y lo
                        # ultimo antes de arrancar, porque armar pone a cero la
                        # cuenta de la alarma.
                        _write_register(client, VIDEO_HALT_TARGET,
                                        VIDEO_HALT_TARGET_CPU)
                        _write_register(client, VIDEO_HALT_AT, stop_after_swaps)

            # Un caso que NO usa video no puede heredar el scanout encendido de
            # uno que si. El modo de VIDEO_CTRL sobrevive a `reset_cpu` --solo
            # lo reinicia el reset de la placa-- y con SCANOUT el barrido lee la
            # SDRAM y compite con la CPU: un programa de 13 instrucciones tardaba
            # a veces 250-279 ciclos en vez de 210, de forma intermitente (3 de
            # cada 40 ejecuciones), y las medidas de CPI de los casos cortos
            # saltaban hasta un 35 % entre pasadas con el mismo RTL. Se vuelve al
            # estado de reset: modo PATTERN, que no lee memoria, y underflow
            # limpio. Va aqui y no en cada caso de video porque lo que hay que
            # garantizar es el punto de partida del SIGUIENTE, sea cual sea.
            if has_video and not video:
                _write_register(client, VIDEO_STATUS, 1)
                _write_register(client, VIDEO_CTRL, MODE_PATTERN)

            # El puerto serie se llena ANTES de arrancar, no mientras corre.
            # Asi el caso es determinista: la CPU encuentra su entrada entera
            # desde el primer ciclo, igual que el simulador, y lo que salga no
            # depende de cuando haya sondeado el PC. Por eso `load_case` limita
            # `stdin` a la profundidad de la cola.
            #
            # Vaciar antes es necesario: las colas sobreviven a RESET_CPU --son
            # del sistema, no de la CPU-- y un caso heredaria lo que dejara el
            # anterior.
            if hasattr(client, "recv_bytes"):
                while client.recv_bytes(255):
                    pass
                if stdin:
                    client.send_all(stdin)

            has_serial = hasattr(client, "recv_bytes")
            serial_output = b"" if has_serial else None

            client.run_cpu()
            deadline = time.monotonic() + timeout_seconds

            # El guion de INPUT se reproduce con la CPU YA en marcha: la FIFO de
            # la placa solo tiene 16 huecos y solo la CPU los libera, asi que un
            # guion largo no cabe antes de arrancar. Se conserva el ORDEN de los
            # eventos y no su instante (los `@N` son instrucciones del simulador);
            # ver `tools.input_script.play_on_board`.
            if input_script is not None:
                if not hasattr(client, "send_input_events"):
                    raise RuntimeError(
                        "este monitor no tiene INPUT_EVENTS: no puede reproducir "
                        "un guion de entrada")
                from tools import input_script as guion

                guion.play_on_board(
                    client, guion.parse(input_script), timeout=timeout_seconds)

            while True:
                status = client.get_status()
                if status.halted:
                    break
                # La parada del arnes: sondear SWAP_COUNT mientras la CPU corre
                # y pararla al llegar. Los registros MMIO responden con el nucleo
                # en marcha --el que no responde es la MEMORIA, que el monitor
                # solo posee con la CPU parada-- asi que esto es leer un contador,
                # no tocar el programa.
                if stop_after_swaps and not by_hardware:
                    if frame_capture.should_stop(read_register, VIDEO_REGISTERS,
                                                swaps_base, stop_after_swaps):
                        status = frame_capture.stop(client)
                        break
                if time.monotonic() >= deadline:
                    client.halt_cpu()
                    raise TimeoutError(
                        f"La CPU no terminó en {timeout_seconds:g} segundos"
                    )
                # Hay que vaciar MIENTRAS corre. La cola de salida son 64
                # bytes y un programa interactivo escribe mucho mas que eso;
                # si se deja llenar, el programa se queda esperando hueco y el
                # caso muere por timeout en vez de por lo que estuviera
                # probando. Esto no cambia el flujo de bytes, solo cuando se
                # recogen, asi que sigue siendo comparable con el simulador.
                if has_serial:
                    serial_output += client.recv_bytes(255)
                else:
                    time.sleep(0.01)

            # Se vacia lo que quede: lo que la CPU escribiera al final esta ahi
            # desde que paro, y un solo RECV_BYTES se queda en 255.
            if has_serial:
                while True:
                    chunk = client.recv_bytes(255)
                    if not chunk:
                        break
                    serial_output += chunk

            registers = {
                number: client.read_register(number)
                for number in sorted(register_numbers)
            }
            memory = {
                (address, size): client.read_memory(address, size)
                for address, size in memory_ranges
            }

            # Ya con la CPU parada y los registros leidos (el caso puede esperar
            # ver la presencia en STATUS): que el siguiente no herede teclas ni
            # presencia.
            if input_script is not None:
                client.set_input_presence(False, False)

            # Los contadores, antes que nada lo demas que toque la memoria: la
            # CPU ya esta parada, asi que no se mueven, pero leerlos aqui deja
            # claro que miden el programa y no lo que haga el monitor despues.
            #
            # Salen del MMIO, no de los comandos 0x36/0x37, que ya no existen:
            # son un dispositivo como los demas --ver cpu_perf_counters.v-- y la
            # capacidad se detecta del RTL igual que el resto.
            cycles = instructions = None
            waits = None
            if "perf_counters" in device_caps:
                cycles = _read_register(client, PERF_CYCLES, has_word)
                instructions = _read_register(client, PERF_RETIRED, has_word)
            # Los de espera solo donde el RTL los tiene: leer una ranura sin
            # contador da error de MMIO, no un cero.
            if "perf_stalls" in device_caps:
                waits = {
                    name: _read_register(client, address, has_word)
                    for name, address in PERF_STALL_COUNTERS.items()
                }

            video_result = None
            if video:
                # ANTES de leer nada, esperar a que no quede intercambio
                # pendiente. Parar la CPU no para el doble buffer: una peticion
                # de SWAP se atiende en la frontera de frame siguiente, que la
                # decide el barrido. Mientras siga pendiente, SWAP_COUNT y
                # FB_FRONT pueden cambiar entre dos lecturas nuestras, y
                # entonces la cuenta y la base que leemos son de instantes
                # distintos: el contador dice que no hubo intercambio de mas y
                # la base ya esta volteada.
                #
                # Eso hacia que `video-swap-demo-fast` fallara UNA DE CADA DOS
                # veces despues de corregir la paridad, que es peor que el
                # fallo original porque parece ruido.
                #
                # Con la CPU parada y sin nada pendiente, el dispositivo de
                # video esta quieto y todo lo que se lea es coherente. Un frame
                # son 16,7 ms; 200 ms es margen de sobra y no se agota nunca
                # salvo que el barrido este detenido, en cuyo caso seguir
                # esperando tampoco arreglaria nada.
                if has_capture:
                    frame_capture.wait_no_pending(read_register,
                                                     VIDEO_REGISTERS)

                # Se lee DESPUES de que la CPU haya parado. Los registros
                # responden tambien con la CPU en marcha, pero el frame no: el
                # monitor solo posee la memoria con la CPU parada.
                state = _read_register(client, VIDEO_STATUS, has_word)
                video_result = {
                    "underflow": bool(state & 1),
                    # De FRAME_COUNT, no de STATUS[31:16]. En v1 los frames
                    # vivian en la mitad alta de STATUS y daban la vuelta a los
                    # 65536 --unos 18 minutos--; en v2 tienen registro propio de
                    # 32 bits. Leerlos del sitio viejo devuelve cero SIEMPRE, sin
                    # error y sin ruido, que es el peor modo de fallo posible.
                    # Los dos contra la linea base del caso, por lo que dice el
                    # comentario de `swaps_base`: son contadores del dispositivo
                    # de video y sobreviven a `reset_cpu`.
                    "frames": ((_read_register(client, VIDEO_FRAME_COUNT,
                                               has_word)
                                - frames_base) & 0xFFFFFFFF
                               if has_capture else state >> 16),
                    "swaps": ((_read_register(client, VIDEO_SWAP_COUNT,
                                              has_word)
                               - swaps_base) & 0xFFFFFFFF
                              if has_capture else None),
                    "fb_front": _read_register(client, VIDEO_FB_FRONT, has_word),
                    "frame": None,
                }
                if video.get("capture_frame"):
                    # Desde FB_FRONT, no desde una direccion fija: tras el
                    # intercambio N el buffer visible alterna segun la paridad.
                    #
                    # Y con una correccion, porque parar la CPU NO para el
                    # doble buffer. Una peticion de intercambio se atiende en la
                    # frontera de frame siguiente, que la decide el BARRIDO; si
                    # el programa escribio SWAP justo antes de que llegara el
                    # `halt_cpu` del arnes, el intercambio se completa con la
                    # CPU ya parada y FB_FRONT acaba apuntando al buffer que el
                    # programa estaba pintando a medias.
                    #
                    # Solo muerde a los programas rapidos, y por eso tardo en
                    # verse: `swap_demo` repinta 240 lineas y tarda 96 ms en
                    # volver a pedir intercambio, asi que la parada siempre cae
                    # dentro de esa ventana. `swap_demo_fast` repinta 32 y
                    # vuelve a pedirlo en 13 ms, que es el orden del viaje de
                    # ida y vuelta por el puerto serie. Medido: la lenta para
                    # con `swaps=24` y la rapida con `swaps=25`, y el frame
                    # capturado salia con la banda dos filas mas abajo.
                    #
                    # La correccion es de paridad y no una heuristica: cada
                    # intercambio de mas cambia de sitio el buffer que buscamos,
                    # que es el que quedo completo tras el intercambio N. La CPU
                    # esta parada, asi que su contenido ya no cambia.
                    #
                    # La corrección vive en `frame_capture.frame_tras_swap`, que
                    # además falla con `ParadaImprecisa` si se pasó de largo en
                    # dos o más: antes se corregía por paridad sin mirar cuánto.
                    requested = stop_after_swaps if (
                        stop_after_swaps
                        and video_result["swaps"] is not None) else None
                    video_result["frame"] = frame_capture.frame_after_swap(
                        client, read_register, VIDEO_REGISTERS,
                        video_result["swaps"], requested, FRAME_BYTES)

        return {
            "halted": status.halted,
            "error": status.error,
            "error_code": status.error_code,
            "pc": status.pc,
            "registers": registers,
            "memory": memory,
            "video": video_result,
            "stdout": serial_output,
            "cycles": cycles,
            "instructions": instructions,
            # `None` en las versiones sin contadores de espera.
            "stalls": waits,
            "clock_hz": self.configuration.get("clock_hz"),
        }
