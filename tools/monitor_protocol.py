#!/usr/bin/env python3
"""El protocolo del monitor UART, una sola vez.

Por qué existe
--------------
Los diez `monitor.py` con juego de comandos tenían **20 de los 21 métodos de
`MonitorClient` byte a byte idénticos**. El único que difería, `read_word`,
difería sólo en el docstring. O sea que no eran diez clientes: era uno, copiado
diez veces, y cada arreglo del protocolo había que hacerlo diez veces y
acordarse de las diez.

El precedente es `tools/serial_ports.py`, que se extrajo de los trece monitores
exactamente por esto. La detección de puerto estaba copiada palabra por palabra
y falló de la peor manera posible —cogía el primer puerto del sistema, que con
la placa desenchufada es un enlace Bluetooth— en todas a la vez.

Ojo: esto NO es lo que se decidió para `monitor.v`. Allí se eligió copia y no
fichero compartido, para que cada carpeta siga siendo un prototipo que se lee
entero sin salir de él. La diferencia es que el RTL de una carpeta *es* la
lección de esa carpeta, y este cliente es herramienta de PC: nadie estudia la
progresión leyendo diez veces el mismo `_read_exact`.

Qué se queda fuera, y por qué
-----------------------------
Aquí vive lo que es el PROTOCOLO. Lo que describe a un prototipo concreto
—baudrate, `MAX_ADDRESS`, las regiones de memoria, qué comandos opcionales
tiene su hardware— se queda en su `monitor.py`, porque es justamente lo que lo
distingue. Los mixins de abajo existen para que eso siga siendo verdad: una
carpeta compone su cliente con lo que su hardware sabe hacer, y no hereda
métodos que la placa va a rechazar.

`ARCHITECTURAL_REGIONS` y `MONITOR_REGIONS` además tienen que seguir siendo
asignaciones literales en cada `monitor.py`: `tools/prototype_report.py` las
lee del TEXTO sin importar el módulo.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import serial

MAX_BLOCK_SIZE = 256

CMD_PING = b"\x01"
CMD_GET_VERSION = b"\x02"
CMD_WRITE_BYTE = 0x10
CMD_READ_BYTE = 0x11
CMD_READ_WORD = 0x12
CMD_WRITE_BLOCK = 0x20
CMD_READ_BLOCK = 0x21
CMD_RUN = 0x30
CMD_HALT = 0x31
CMD_STEP = 0x32
CMD_GET_STATUS = 0x33
CMD_READ_REGISTER = 0x34
CMD_RESET_CPU = 0x35
# Opcionales: sólo los tiene el hardware que declara el dispositivo. Ver los
# mixins.
CMD_SEND_BYTES = 0x38
CMD_RECV_BYTES = 0x39
CMD_SELECT_CONTEXT = 0x3A

RSP_PONG = b"\x81"
RSP_VERSION = 0x82
RSP_WRITE_BYTE = b"\x90"
RSP_READ_BYTE = 0x91
RSP_READ_WORD = 0x92
RSP_WRITE_BLOCK = b"\xa0"
RSP_READ_BLOCK = 0xA1
RSP_RUN = b"\xb0"
RSP_HALT = b"\xb1"
RSP_STEP = b"\xb2"
RSP_STATUS = 0xB3
RSP_READ_REGISTER = 0xB4
RSP_RESET_CPU = b"\xb5"
RSP_SEND_BYTES = 0xB8
RSP_RECV_BYTES = 0xB9
RSP_SELECT_CONTEXT = 0xBA
RSP_ERROR = 0xFF

# Contadores de rendimiento, en el MMIO y no en un comando propio. Los MISMOS
# offsets en las dos familias: el bloque de CPU es un prefijo del de GPU.
PERF_CYCLES = 0x8000_0300
PERF_RETIRED = 0x8000_0304


class MonitorError(Exception):
    """Raised when communication with the FPGA monitor fails."""


@dataclass(frozen=True)
class Version:
    major: int
    minor: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


@dataclass(frozen=True)
class CpuStatus:
    halted: bool
    error: bool
    error_code: int
    pc: int


def validate_block(address: int, length: int, regions) -> None:
    if not 1 <= length <= MAX_BLOCK_SIZE:
        raise MonitorError(f"Block length must be between 1 and {MAX_BLOCK_SIZE}")
    if not any(start <= address and address + length <= end
               for start, end in regions):
        raise MonitorError("Block is outside the currently implemented memory regions")


def validate_transfer(address: int, length: int, regions) -> None:
    if length < 1:
        raise MonitorError("Transfer must contain at least one byte")
    if not any(start <= address and address + length <= end
               for start, end in regions):
        raise MonitorError("Transfer is outside the currently implemented memory regions")


def parse_integer(value: str, maximum: int, description: str) -> int:
    try:
        result = int(value, 0)
    except ValueError as error:
        raise MonitorError(f"Invalid {description}: {value}") from error

    if not 0 <= result <= maximum:
        raise MonitorError(
            f"{description.capitalize()} must be between 0 and 0x{maximum:x}"
        )
    return result


class MonitorClient:
    """El juego de comandos BASE, el que tiene todo hardware con monitor.

    Las regiones son un atributo de clase y no un argumento porque
    `backends/board.py` construye el cliente con la conexión y nada más. Cada
    prototipo declara las suyas al heredar.
    """

    # Lo pone cada prototipo. Vacío significa que ningún bloque valida, que es
    # un fallo ruidoso y no uno silencioso.
    MEMORY_REGIONS: tuple = ()
    MAX_BLOCK_SIZE = MAX_BLOCK_SIZE

    def __init__(self, connection: serial.Serial) -> None:
        self.connection = connection

    def _send(self, command: bytes) -> None:
        self.connection.reset_input_buffer()
        self.connection.write(command)
        self.connection.flush()

    def _read_exact(self, response_size: int) -> bytes:
        response = self.connection.read(response_size)
        if len(response) != response_size:
            raise MonitorError(
                f"Timeout: expected {response_size} response byte(s), "
                f"received {len(response)}"
            )
        return response

    def _request(self, command: bytes, response_size: int) -> bytes:
        self._send(command)
        response = self._read_exact(response_size)
        if response[0] == RSP_ERROR:
            raise MonitorError("The FPGA rejected the command")
        return response

    @staticmethod
    def _address_bytes(address: int) -> bytes:
        return address.to_bytes(4, byteorder="big")

    def ping(self) -> None:
        response = self._request(CMD_PING, len(RSP_PONG))
        if response != RSP_PONG:
            raise MonitorError(f"Invalid PING response: {response.hex(' ')}")

    def get_version(self) -> Version:
        response = self._request(CMD_GET_VERSION, 3)
        if response[0] != RSP_VERSION:
            raise MonitorError(f"Invalid GET_VERSION response: {response.hex(' ')}")

        return Version(major=response[1], minor=response[2])

    def write_byte(self, address: int, value: int) -> None:
        request = (bytes((CMD_WRITE_BYTE,)) + self._address_bytes(address)
                   + bytes((value,)))
        response = self._request(request, len(RSP_WRITE_BYTE))
        if response != RSP_WRITE_BYTE:
            raise MonitorError(f"Invalid WRITE_BYTE response: {response.hex(' ')}")

    def read_byte(self, address: int) -> int:
        request = bytes((CMD_READ_BYTE,)) + self._address_bytes(address)
        self._send(request)
        header = self._read_exact(1)
        if header[0] == RSP_ERROR:
            raise MonitorError("The FPGA rejected the command")
        if header[0] != RSP_READ_BYTE:
            raise MonitorError(f"Invalid READ_BYTE response: {header.hex(' ')}")

        return self._read_exact(1)[0]

    def read_word(self, address: int) -> int:
        """Lee 32 bits en UNA transaccion de bus, y por tanto sin desgarro.

        Cuatro read_byte tardan cerca de un milisegundo entre el primero y el
        cuarto, y hay registros que siguen vivos con el nucleo parado: en la
        22, `frame_count` avanza con el scanout, que cuelga de `reset` y no de
        `core_reset`. Leido a trozos puede salir un valor que nunca existio.
        """
        if address % 4:
            raise MonitorError(
                f"READ_WORD requiere direccion alineada a 4: {address:#x}")
        request = bytes((CMD_READ_WORD,)) + self._address_bytes(address)
        self._send(request)
        header = self._read_exact(1)
        if header[0] == RSP_ERROR:
            raise MonitorError("The FPGA rejected the command")
        if header[0] != RSP_READ_WORD:
            raise MonitorError(f"Invalid READ_WORD response: {header.hex(' ')}")

        return int.from_bytes(self._read_exact(4), byteorder="little")

    def write_block(self, address: int, data: bytes) -> None:
        validate_block(address, len(data), self.MEMORY_REGIONS)
        request = (
            bytes((CMD_WRITE_BLOCK,))
            + self._address_bytes(address)
            + len(data).to_bytes(2, byteorder="big")
            + data
        )
        response = self._request(request, len(RSP_WRITE_BLOCK))
        if response != RSP_WRITE_BLOCK:
            raise MonitorError(f"Invalid WRITE_BLOCK response: {response.hex(' ')}")

    def read_block(self, address: int, length: int) -> bytes:
        validate_block(address, length, self.MEMORY_REGIONS)
        request = (
            bytes((CMD_READ_BLOCK,))
            + self._address_bytes(address)
            + length.to_bytes(2, byteorder="big")
        )
        self._send(request)
        header = self._read_exact(1)
        if header[0] == RSP_ERROR:
            raise MonitorError("The FPGA rejected the command")
        if header[0] != RSP_READ_BLOCK:
            raise MonitorError(f"Invalid READ_BLOCK response: {header.hex(' ')}")

        return self._read_exact(length)

    def write_memory(self, address: int, data: bytes) -> None:
        validate_transfer(address, len(data), self.MEMORY_REGIONS)
        for offset in range(0, len(data), self.MAX_BLOCK_SIZE):
            chunk = data[offset:offset + self.MAX_BLOCK_SIZE]
            self.write_block(address + offset, chunk)

    def read_memory(self, address: int, length: int) -> bytes:
        validate_transfer(address, length, self.MEMORY_REGIONS)
        result = bytearray()
        for offset in range(0, length, self.MAX_BLOCK_SIZE):
            chunk_length = min(self.MAX_BLOCK_SIZE, length - offset)
            result.extend(self.read_block(address + offset, chunk_length))
        return bytes(result)

    def run_cpu(self) -> None:
        response = self._request(bytes((CMD_RUN,)), 1)
        if response != RSP_RUN:
            raise MonitorError(f"Invalid RUN response: {response.hex(' ')}")

    def halt_cpu(self) -> None:
        response = self._request(bytes((CMD_HALT,)), 1)
        if response != RSP_HALT:
            raise MonitorError(f"Invalid HALT response: {response.hex(' ')}")

    def step_cpu(self) -> None:
        response = self._request(bytes((CMD_STEP,)), 1)
        if response != RSP_STEP:
            raise MonitorError(f"Invalid STEP response: {response.hex(' ')}")

    def get_status(self) -> CpuStatus:
        response = self._request(bytes((CMD_GET_STATUS,)), 7)
        if response[0] != RSP_STATUS:
            raise MonitorError(f"Invalid STATUS response: {response.hex(' ')}")

        return CpuStatus(
            halted=bool(response[1] & 0x01),
            error=bool(response[1] & 0x02),
            error_code=response[2],
            pc=int.from_bytes(response[3:7], byteorder="big"),
        )

    def read_register(self, register: int) -> int:
        if not 0 <= register < 32:
            raise MonitorError("Register number must be between 0 and 31")

        self._send(bytes((CMD_READ_REGISTER, register)))
        header = self._read_exact(1)
        if header[0] == RSP_ERROR:
            raise MonitorError("The FPGA rejected the command")
        if header[0] != RSP_READ_REGISTER:
            raise MonitorError(f"Invalid READ_REG response: {header.hex(' ')}")
        return int.from_bytes(self._read_exact(4), byteorder="big")

    def reset_cpu(self) -> None:
        response = self._request(bytes((CMD_RESET_CPU,)), 1)
        if response != RSP_RESET_CPU:
            raise MonitorError(f"Invalid RESET_CPU response: {response.hex(' ')}")


class PerfMixin:
    """Contadores de rendimiento, para el hardware que trae el dispositivo 3.

    Se leen del MMIO y no de un comando propio. `GET_CYCLES` (`0x36`) y
    `GET_INSTRUCTIONS` (`0x37`) existieron y se retiraron al pasar los
    contadores a MMIO: con eso, un PROGRAMA puede medirse a sí mismo en marcha,
    que es lo que nunca pudo hacer mientras la única vía era preguntar por
    serie con el núcleo parado.
    """

    def get_cycles(self) -> int:
        """Ciclos que el núcleo ha estado corriendo desde el último RUN.

        Se lee por separado de `get_instructions`, así que no son del mismo
        instante; se leen con el núcleo ya parado, así que ninguno de los dos
        se mueve entre una lectura y otra.
        """
        return self.read_word(PERF_CYCLES)

    def get_instructions(self) -> int:
        return self.read_word(PERF_RETIRED)


class WarpMixin:
    """Configuración de warps y depuración por carril, sólo en la MiniGPU.

    Las tres direcciones son atributos de clase porque han cambiado de sitio:
    la ventana de warps se movió de `0x80000000` a `0x80001000` en la fase 1
    para dejar la página compartida libre, y las carpetas sin migrar
    declaraban la vieja. Tenerlas aquí como constantes cableadas habría sido
    volver a poner la dirección en un sitio del que hay que acordarse.
    """

    # Lo declara cada prototipo.
    WARP_CONFIG_BASE = 0x8000_1000
    # Dispositivo 1 de la página MMIO: depuración.
    DEBUG_BASE = 0x8000_0100
    # La memoria del MODELO con el que se valida el JSON antes de tocar el
    # hardware. No es la de la placa: la 12 tiene 128 KiB de EBR y la 22 SDRAM.
    MODEL_MEMORY_SIZE = 32 * 1024 * 1024

    def select_context(self, warp: int, lane: int) -> None:
        if not 0 <= warp < 8 or not 0 <= lane < 8:
            raise MonitorError("Warp and lane must be in 0..7")
        self.write_byte(self.DEBUG_BASE, warp * 8 + lane)

    def read_registers(self, warp: int, lane: int) -> list[int]:
        """Read the complete register file for one halted GPU lane."""
        self.select_context(warp, lane)
        return [self.read_register(register) for register in range(32)]

    def configure_warps(self, config: object) -> None:
        # La validación del JSON se comparte con el simulador, y se hace ANTES
        # de tocar el hardware: un config malo no debe dejar la placa a medio
        # configurar.
        import sys
        from pathlib import Path

        sys.path.insert(
            0, str(Path(__file__).resolve().parent.parent / '11.gpu-sim-func'))
        from minigpu_sim import System
        model = System(self.MODEL_MEMORY_SIZE, 8, 8)
        try:
            model.configure_warps(config)
        except (ValueError, TypeError) as exc:
            raise MonitorError(str(exc)) from exc
        warps = model.streaming_multiprocessor.warps
        if any(w.workgroup_id > 0xffffffff for w in warps):
            raise MonitorError("Hardware workgroup IDs must fit in 32 bits")
        if not self.get_status().halted:
            raise MonitorError("Halt the GPU before configuring warps")
        self.reset_cpu()
        deadline = time.monotonic() + 2
        while not self.get_status().halted:
            if time.monotonic() > deadline:
                raise MonitorError("GPU did not finish register initialization")
        for w in warps:
            base = self.WARP_CONFIG_BASE + w.warp_id * 16
            self.write_memory(base, w.pc.to_bytes(4, 'little'))
            self.write_memory(base + 4, w.active_mask.to_bytes(4, 'little'))
            self.write_memory(base + 8, w.workgroup_id.to_bytes(4, 'little'))


class SerialMixin:
    """El puerto serie de la CPU, encapsulado en este mismo enlace.

    Estos dos métodos son el CODEC: convierten bytes en paquetes y nada más. El
    terminal interactivo vive fuera, en el `monitor.py` de cada carpeta, y esa
    separación es lo que permite probar el codec sin consola y sin placa.
    """

    def send_bytes(self, data: bytes) -> int:
        """Mete lo que quepa en la cola de entrada y dice cuántos entraron.

        El valor devuelto puede ser MENOR que `len(data)`, y no es un error: es
        el control de flujo. La cola de la FPGA tiene 64 bytes y quien decide
        cuántos caben es ella. Ver `send_all()` para el bucle de reenvío.
        """
        if not 0 <= len(data) <= 255:
            raise ValueError("un paquete SEND_BYTES son entre 0 y 255 bytes")
        request = bytes((CMD_SEND_BYTES, len(data))) + data
        response = self._request(request, 2)
        if response[0] != RSP_SEND_BYTES:
            raise MonitorError(f"Invalid SEND_BYTES response: {response.hex(' ')}")
        accepted = response[1]
        if accepted > len(data):
            raise MonitorError(
                f"SEND_BYTES acepto {accepted} de {len(data)} bytes")
        return accepted

    def send_all(self, data: bytes, timeout: float = 5.0) -> None:
        """Reenvía hasta colocarlo todo, respetando el control de flujo."""
        pending = memoryview(data)
        deadline = time.monotonic() + timeout
        while pending:
            accepted = self.send_bytes(bytes(pending[:255]))
            pending = pending[accepted:]
            if accepted == 0:
                # La CPU no esta consumiendo. Sin este limite, un programa
                # parado deja al PC girando para siempre.
                if time.monotonic() >= deadline:
                    raise MonitorError(
                        f"la cola de entrada sigue llena tras {timeout:g} s; "
                        f"quedan {len(pending)} bytes. ¿Esta corriendo la CPU?")
                time.sleep(0.005)
            else:
                deadline = time.monotonic() + timeout

    def recv_bytes(self, maximum: int = 255) -> bytes:
        """Saca hasta `maximum` bytes de la cola de salida; puede devolver b''."""
        if not 1 <= maximum <= 255:
            raise ValueError("RECV_BYTES admite entre 1 y 255 bytes")
        self._send(bytes((CMD_RECV_BYTES, maximum)))
        header = self._read_exact(2)
        if header[0] == RSP_ERROR:
            raise MonitorError("The FPGA rejected the command")
        if header[0] != RSP_RECV_BYTES:
            raise MonitorError(f"Invalid RECV_BYTES response: {header.hex(' ')}")
        count = header[1]
        if count > maximum:
            raise MonitorError(f"RECV_BYTES devolvio {count} de {maximum}")
        return self._read_exact(count) if count else b""
