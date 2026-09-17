#!/usr/bin/env python3
"""Ejecuta casos de conformidad sobre el simulador, la FPGA o ambos."""

from __future__ import annotations

import argparse
import importlib.util
import json
import struct
import sys
import time
from pathlib import Path
from types import ModuleType

from backends import board
from backends import fpga as fpga_backend
from backends import gpu_fpga as gpu_fpga_backend
from backends import simulator as simulator_backend
from backends import gpu_simulator as gpu_backend
from backends.gpu_simulator import GpuBackend
from backends.fpga import FpgaBackend
from backends.gpu_fpga import GpuFpgaBackend
from backends.simulator import SimulatorBackend

ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parent
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

from tools.rtl_facts import capability_architectures, load_capability_signals  # noqa: E402

# Límite común a todos los casos: que quepan en un espacio de 32 bits. Si el
# caso cabe en el mapa concreto de un backend lo decide `incompatibility()`.
ARCHITECTURAL_MEMORY_SIZE = 32 * 1024 * 1024
# Opciones de construcción que un caso GPU puede fijar sobre el simulador.
SIMULATOR_OPTIONS = ("simt_region_depth", "simt_path_depth")
# A partir de aquí se anota el tiempo junto al resultado del caso.
SLOW_CASE_SECONDS = 1.0
BACKEND_DEFINITIONS = {
    "gpu-simulator": {
        "class": GpuBackend,
        "module": gpu_backend,
        "architecture": GpuBackend.ARCHITECTURE,
        "versions": gpu_backend.VERSIONS,
        "default_version": gpu_backend.DEFAULT_VERSION,
    },
    "cpu-simulator": {
        "class": SimulatorBackend,
        "module": simulator_backend,
        "architecture": SimulatorBackend.ARCHITECTURE,
        "versions": simulator_backend.VERSIONS,
        "default_version": simulator_backend.DEFAULT_VERSION,
    },
    "cpu-fpga": {
        "class": FpgaBackend,
        "module": fpga_backend,
        "architecture": FpgaBackend.ARCHITECTURE,
        "versions": fpga_backend.VERSIONS,
        "default_version": fpga_backend.DEFAULT_VERSION,
    },
    "gpu-fpga": {
        "class": GpuFpgaBackend,
        "module": gpu_fpga_backend,
        "architecture": GpuFpgaBackend.ARCHITECTURE,
        "versions": gpu_fpga_backend.VERSIONS,
        "default_version": gpu_fpga_backend.DEFAULT_VERSION,
    },
}


def resolve_backend_versions(
    specifications: list[str], backend_names: tuple[str, ...]
) -> dict[str, str]:
    """Resolve repeatable VERSION or BACKEND=VERSION command-line values."""
    selected = {
        name: BACKEND_DEFINITIONS[name]["default_version"]
        for name in backend_names
    }
    for specification in specifications:
        if "=" in specification:
            backend_name, version = specification.split("=", 1)
            if backend_name not in backend_names:
                raise ValueError(
                    f"--version menciona el backend no seleccionado {backend_name!r}"
                )
        else:
            if len(backend_names) != 1:
                raise ValueError(
                    "Con varios backends usa --version BACKEND=VERSION"
                )
            backend_name = backend_names[0]
            version = specification

        versions = BACKEND_DEFINITIONS[backend_name]["versions"]
        if version not in versions:
            choices = ", ".join(sorted(versions))
            raise ValueError(
                f"Versión {version!r} no disponible para {backend_name}; "
                f"opciones: {choices}"
            )
        selected[backend_name] = version
    return selected


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se puede cargar el módulo {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def parse_integer(value: int | str, description: str) -> int:
    if type(value) is int:
        result = value
    elif isinstance(value, str):
        try:
            result = int(value, 0)
        except ValueError as error:
            raise ValueError(f"{description} inválido: {value}") from error
    else:
        raise TypeError(f"{description} debe ser un entero o una cadena")

    if not 0 <= result <= 0xFFFF_FFFF:
        raise ValueError(f"{description} fuera de 32 bits: {result}")
    return result


def load_program(path: Path) -> bytes:
    suffix = path.suffix.lower()
    if suffix == ".bin":
        data = path.read_bytes()
    elif suffix == ".hex":
        words = [
            int(line.strip(), 16)
            for line in path.read_text(encoding="ascii").splitlines()
            if line.strip()
        ]
        data = b"".join(struct.pack("<I", word) for word in words)
    elif suffix == ".asm":
        assembler = load_module(
            "miniisa_asm_for_tests",
            REPOSITORY / "1.isa" / "miniisa_asm.py",
        )
        words = assembler.assemble(path.read_text(encoding="utf-8"))
        data = b"".join(struct.pack("<I", word) for word in words)
    else:
        raise ValueError(f"Formato de programa no soportado: {path}")

    if not data or len(data) % 4:
        raise ValueError("El programa debe contener palabras completas de 32 bits")
    return data


def load_data_file(path: Path) -> bytes:
    """Load raw bytes, or little-endian 32-bit words from a textual .hex file."""
    if path.suffix.lower() != ".hex":
        return path.read_bytes()
    words = [
        int(line.split("#", 1)[0].strip(), 16)
        for line in path.read_text(encoding="ascii").splitlines()
        if line.split("#", 1)[0].strip()
    ]
    if any(not 0 <= word <= 0xFFFF_FFFF for word in words):
        raise ValueError(f"Palabra fuera de 32 bits en {path}")
    return b"".join(struct.pack("<I", word) for word in words)


def parse_register(name: str) -> int:
    if not isinstance(name, str) or not name.upper().startswith("R"):
        raise ValueError(f"Registro inválido: {name!r}")
    try:
        number = int(name[1:])
    except ValueError as error:
        raise ValueError(f"Registro inválido: {name!r}") from error
    if not 0 <= number < 32:
        raise ValueError(f"Registro fuera de rango: {name}")
    return number


def first_memory_difference(expected: bytes, actual: bytes) -> int | None:
    for offset, (expected_byte, actual_byte) in enumerate(zip(expected, actual)):
        if expected_byte != actual_byte:
            return offset
    return None if len(expected) == len(actual) else min(len(expected), len(actual))


def compare_result(case: dict, result: dict, backend_name: str) -> list[str]:
    expected = case["expected"]
    errors: list[str] = []

    for field in ("halted", "error"):
        if result[field] != expected[field]:
            errors.append(
                f"{backend_name}: {field}: esperado {expected[field]!r}, "
                f"obtenido {result[field]!r}"
            )

    for field in ("error_code", "pc"):
        if field not in expected:
            continue
        if result[field] != expected[field]:
            errors.append(
                f"{backend_name}: {field}: esperado 0x{expected[field]:08x}, "
                f"obtenido 0x{result[field]:08x}"
            )

    if expected.get("video") is not None:
        observado = result.get("video", {})
        esperado_under = expected["video"]["underflow"]
        if observado.get("underflow") != esperado_under:
            errors.append(
                f"{backend_name}: video.underflow: esperado {esperado_under!r}, "
                f"obtenido {observado.get('underflow')!r}"
            )

    if expected.get("frame") is not None:
        obtenido = result.get("video", {}).get("frame")
        if obtenido is None:
            errors.append(f"{backend_name}: el backend no devolvio ningun frame")
        elif obtenido != expected["frame"]:
            # Un recuento de pixeles distintos no orienta; DONDE estan si. El
            # detalle fino lo da tools/compare-frames.py sobre los volcados.
            distintos = sum(
                1 for a, b in zip(expected["frame"][::2], obtenido[::2])
            )
            offset = first_memory_difference(expected["frame"], obtenido)
            pixel = offset // 2 if offset is not None else 0
            errors.append(
                f"{backend_name}: frame distinto del esperado; primera "
                f"diferencia en el pixel {pixel} "
                f"(x={pixel % 320}, y={pixel // 320}) de {distintos}"
            )

    if expected.get("stdout") is not None:
        obtenido = result.get("stdout")
        if obtenido is None:
            errors.append(f"{backend_name}: el backend no devolvio stdout")
        elif obtenido != expected["stdout"]:
            # El flujo de bytes es corto y legible, asi que se ensena entero:
            # es mas util que decir en que posicion difiere.
            errors.append(
                f"{backend_name}: stdout: esperado "
                f"{expected['stdout'].decode('latin-1')!r}, obtenido "
                f"{obtenido.decode('latin-1')!r}"
            )

    for register, expected_value in expected["registers"].items():
        actual = result["registers"][register]
        if actual != expected_value:
            errors.append(
                f"{backend_name}: R{register}: esperado 0x{expected_value:08x}, "
                f"obtenido 0x{actual:08x}"
            )

    for memory_range, expected_data in expected["memory"].items():
        actual_data = result["memory"][memory_range]
        difference = first_memory_difference(expected_data, actual_data)
        if difference is not None:
            address, _ = memory_range
            expected_byte = expected_data[difference] if difference < len(expected_data) else None
            actual_byte = actual_data[difference] if difference < len(actual_data) else None
            errors.append(
                f"{backend_name}: memoria 0x{address + difference:08x}: "
                f"esperado {expected_byte!r}, obtenido {actual_byte!r} "
                f"(offset 0x{difference:x})"
            )

    for field, value in expected.get("observations", {}).items():
        actual = result.get("observations", {}).get(field, "<ausente>")
        if actual != value:
            errors.append(f"{backend_name}: {field}: esperado {value!r}, obtenido {actual!r}")
    return errors


def gpu_expectations(raw: dict, warp_size: int) -> dict:
    """Normaliza observaciones por warp/hilo sin inventar un PC global."""
    observations = {}
    if "fault" in raw:
        fault = raw["fault"]
        observations["fault.present"] = fault is not None
        if fault is not None:
            fields = {"pc", "warp_id", "core_id", "address"}
            if not isinstance(fault, dict) or fault.keys() != fields:
                raise ValueError("expect.fault requiere pc, warp_id, core_id y address")
            for field, value in fault.items():
                if value is None and field in ("core_id", "address"):
                    observations[f"fault.{field}"] = None
                else:
                    number = parse_integer(value, f"fault.{field}")
                    if field == "warp_id" and number >= 8:
                        raise ValueError("fault.warp_id fuera de rango")
                    if field == "core_id" and number >= warp_size:
                        raise ValueError("fault.core_id fuera de rango")
                    observations[f"fault.{field}"] = number
    if "instructions_executed" in raw:
        observations["instructions_executed"] = parse_integer(
            raw["instructions_executed"], "instructions_executed")
    warps = raw.get("warps", {})
    if not isinstance(warps, dict):
        raise ValueError("expect.warps debe ser un objeto indexado por ID")
    for warp_id, state in warps.items():
        if warp_id not in {str(i) for i in range(8)}:
            raise ValueError(f"ID de warp esperado inválido: {warp_id}")
        if not isinstance(state, dict) or state.keys() - {
            "pc", "active_mask", "instructions_executed", "registers"
        }:
            raise ValueError(f"Estado esperado inválido del warp {warp_id}")
        prefix = f"warp[{warp_id}]"
        for field in ("pc", "active_mask", "instructions_executed"):
            if field in state:
                observations[f"{prefix}.{field}"] = parse_integer(state[field], field)
        lanes = state.get("registers", {})
        if not isinstance(lanes, dict):
            raise ValueError("registers del warp debe estar indexado por hilo")
        for lane_id, registers in lanes.items():
            if lane_id not in {str(i) for i in range(warp_size)}:
                raise ValueError(f"ID de hilo esperado inválido: {lane_id}")
            if not isinstance(registers, dict):
                raise ValueError("Los registros del hilo deben ser un objeto")
            for name, value in registers.items():
                number = parse_register(name)
                observations[f"{prefix}.lane[{lane_id}].R{number}"] = parse_integer(value, name)
    return observations


def simulator_options(raw: dict, architecture: str) -> dict:
    """Opciones de construcción del simulador declaradas por el caso."""
    options = raw.get("simulator_options", {})
    if not options:
        return {}
    if architecture != "gpu":
        raise ValueError("simulator_options solo se admite en casos GPU")
    if not isinstance(options, dict):
        raise ValueError("simulator_options debe contener un objeto JSON")
    unknown = set(options) - set(SIMULATOR_OPTIONS)
    if unknown:
        raise ValueError(f"simulator_options desconocidas: {', '.join(sorted(unknown))}")
    for name, value in options.items():
        if type(value) is not int or value < 1:
            raise ValueError(f"simulator_options.{name} debe ser un entero positivo")
    return dict(options)


# ---------------------------------------------------------------------------
# Capacidades
#
# Un caso declara en `requires` lo que necesita del sistema, y cada backend
# publica `incompatibility(case, version)` diciendo si lo tiene. El runner
# imprime SKIP y lo cuenta aparte de los fallos: un caso omitido por no haber
# hardware no es un caso roto, y mezclarlos haria inutil el recuento.
#
# El mecanismo ya existia para `atomic_warp_faults`. Lo que se anade aqui es
# video, y con el la posibilidad de usar `requires` tambien en casos de CPU:
# hasta ahora estaba restringido a GPU porque no habia ninguna otra capacidad.
#
# Dos capacidades y no una, porque la diferencia es real:
#
#   video          hay scanout leyendo un framebuffer de memoria y ventana de
#                  registros en 0x80000000. La tienen 16 y 18.
#   frame_capture  ademas hay HALT_AT, SWAP_COUNT y borrado de underflow, o
#                  sea se puede parar en un intercambio concreto y leer el
#                  frame de forma repetible. Solo la 18.
#
# Con una sola capacidad, un caso de captura se omitiria en la 16 por el motivo
# equivocado: alli hay video, lo que no hay es con que capturar.
#
# Las otras dos son de ISA, no de periferico, y aparecen porque la 19 extiende
# el juego de instrucciones y las anteriores no:
#
#   subword_memory  LOADB/LOADUB/STOREB/LOADH/LOADUH/STOREH, opcodes 0x18..0x1D
#                   del mapa de propuesta-v0.2. En un bitstream sin ellas el
#                   programa no da un resultado distinto: para con error 0x01,
#                   que es justamente lo que un SKIP evita confundir con un bug.
#   calls           JAL/JALR/JR, opcodes 0x2C..0x2E del mismo mapa.
#
# Separadas porque son extensiones independientes: un backend futuro puede
# tener una sin la otra, y de hecho el backport a las versiones anteriores
# --si llega-- no tiene por que traer las dos a la vez.
#
# La 21 anade tres mas, y van SEPARADAS porque son tres extensiones
# independientes: se pueden implementar, portar y romper por separado, y un
# backend futuro puede tener una sin las otras.
#
#   shift_immediate  SHLI/SHRI/SARI. No son opcodes nuevos: SHL/SHR/SAR con el
#                    bit 10 del campo `extra` puesto (propuesta-v0.2.md §4.2,
#                    opcion B). Ojo con esto, porque es el unico caso del
#                    repositorio en el que la capacidad NO se puede detectar por
#                    un ERROR_INVALID_OPCODE: en un bitstream sin ella, el bit
#                    10 sigue siendo reservado y el programa para con
#                    ERROR_INVALID_ENCODING (0x05). El SKIP evita confundir esa
#                    parada con un bug del ensamblador.
#   alu_extended     MULHI (0x0B), DIVU (0x0D), REM (0x0E) y REMU (0x0F). En un
#                    bitstream sin ellas, ERROR_INVALID_OPCODE.
#
# `R0` CABLEADO A CERO NO ESTA EN ESTA LISTA, y estuvo. Fue la capacidad
# `zero_register` mientras solo la tenia la 21. Con el backport aplicado la
# tienen todas las implementaciones, asi que dejo de ser algo que un backend
# pueda o no tener y paso a ser una regla de la MiniISA: 1.isa/isa.md seccion 1.
#
# Fue ademas la unica capacidad NO ADITIVA que ha tenido este runner, y por eso
# no podia quedarse a medias mucho tiempo: las demas se detectan porque un
# bitstream que no las tiene para con ERROR_INVALID_OPCODE, mientras que un
# backend con R0 general no para, da otro resultado en silencio. Una capacidad
# sirve para omitir un caso con criterio; no sirve para proteger de una
# divergencia muda entre dos backends que el diferencial compararia.
#
# El camino rapido de MULHI/REM/REMU tampoco tiene capacidad, por el motivo
# contrario: es invisible para la arquitectura. Acierto y fallo dan el mismo
# numero y solo cambian los ciclos, que el diferencial ya excluye. Un caso no
# puede depender de el, asi que no hay nada que declarar.
#
# `mul_div` es la rara de la lista, y conviene leerla aparte de las demas:
# **no es una extension, es un hueco**. MUL, MULFX y DIV son instrucciones BASE
# de la MiniISA; todas las implementaciones las tienen menos `sdram`
# (10.fpga-cpu-ram), que se quedo sin ellas por temporizacion --el detalle esta
# en su `cpu.v`--. Las demas capacidades dicen «este backend tiene algo de mas»;
# esta dice «a este le falta algo de la base».
#
# Existe por la misma razon practica que el resto: sin ella, `cases/alu/multiply`
# falla en esa placa con ERROR_INVALID_OPCODE, que es lo mismo que produce un
# ensamblador roto. Con ella, el SKIP dice donde esta el problema. Pero conviene
# NO leer el SKIP como «aqui no hace falta»: ahi falta algo que la ISA exige, y
# el dia que la 10 implemente las tres, esta entrada desaparece.
# `CAPABILITIES` (arquitectura de cada una) y `CAPABILITY_IMPLIES` ya no se
# escriben aqui: se derivan de tools/capabilities.json, que es el mismo
# fichero de donde `backends/fpga.py` y `tools/prototype_report.py` leen que
# buscar en el RTL. Una tabla, no tres. `implies` alli documenta lo mismo que
# el parrafo anterior --`frame_capture` implica `video`, `alu_extended`
# implica `mul_div`-- pero como metadato, para que un caso pueda declarar solo
# la mas especifica sin repetir la base.
_CAPABILITY_SIGNALS = load_capability_signals(REPOSITORY)
# El valor es la TUPLA de arquitecturas que pueden declarar la capacidad, no
# una sola: `video` lo tienen CPU y GPU, y mientras fuese un unico valor un caso
# GPU no podia declarar `requires: ["video"]` aunque la placa tuviese el
# dispositivo -- que es justo lo que impide compartir un programa entre familias.
CAPABILITIES = {
    name: capability_architectures(spec) for name, spec in _CAPABILITY_SIGNALS.items()
}
CAPABILITY_IMPLIES = {
    name: tuple(spec["implies"])
    for name, spec in _CAPABILITY_SIGNALS.items()
    if "implies" in spec
}


# Campos que el diferencial `--backend both` NO compara.
#
# `cycles`, `instructions` y `clock_hz` son de rendimiento: el simulador no
# tiene ciclos ni reloj, y el numero de instrucciones se contrasta en
# `--measure`, no aqui.
#
# `video.frames` es el caso interesante, y se excluye por la misma razon por la
# que el simulador puede declarar `frame_capture` honestamente: aqui un frame
# son N instrucciones ejecutadas y en la placa son 16,7 ms de barrido. Los dos
# numeros son correctos y no pueden coincidir --medido: 1 contra 7068 en
# `video-registers`--, asi que compararlos hacia que los tres casos de video
# fallaran SIEMPRE el diferencial, pasando los dos backends por separado.
#
# Lo que si se compara de `video` es todo lo demas, que es lo que de verdad
# dice si las dos implementaciones hacen lo mismo: `swaps` esta anclado al
# intercambio y no al tiempo, `fb_front` y `frame` son el resultado visible, y
# `underflow` es la excepcion consciente --el simulador siempre da False, asi
# que coincidir ahi no demuestra nada; ver backends/simulator.py--.
#
# Y `pc` se excluye, pero solo en los casos con `run_until`: esa parada es
# asincrona y deja el PC donde pille a la CPU. Es exactamente el motivo por el
# que `parse_run_until` prohibe declarar `expect.pc` junto a `run_until`;
# compararlo entre backends tiene el mismo problema y no lo veia nadie --medido:
# 196 contra 192 en `video-bounce`, dos instrucciones del bucle de espera--.
# Sin `run_until` el PC si se compara, porque entonces es determinista.
PERF_FIELDS = ("cycles", "instructions", "clock_hz")
VIDEO_FIELDS_EXCLUDED = ("frames",)


def comparable(resultado: dict, case: dict) -> dict:
    """El estado observado sin lo que no puede coincidir entre backends.

    `stdout` se excluye en los casos que no piden `serial`, y esto arregla un
    fallo que estaba escondido: el simulador declara `serial` siempre, asi que
    devuelve `b''` para cualquier caso, mientras que un bitstream sin puerto
    serie devuelve `None`. Los dos quieren decir «aqui no hubo salida», pero no
    son iguales, asi que el diferencial fallaba en TODOS los casos contra los
    bitstreams `ebr`, `sdram`, `hdmi` y `bl8` --los cuatro sin serie-- mientras
    cada backend pasaba por separado. No se habia visto porque el README solo
    documentaba el diferencial contra `sdram`, que tampoco lo tiene, y nadie lo
    habia corrido.

    Para un caso que SI pide `serial`, los dos backends lo declaran y los dos
    devuelven bytes, asi que se compara y es lo que tiene que ser.
    """
    excluidos = set(PERF_FIELDS)
    if "serial" not in case.get("requires", ()):
        excluidos.add("stdout")
    if case.get("run_until"):
        excluidos.add("pc")
    recortado = {k: v for k, v in resultado.items() if k not in excluidos}
    if recortado.get("video"):
        video_excluidos = set(VIDEO_FIELDS_EXCLUDED)
        # `swaps` sale de SWAP_COUNT, que es parte de `frame_capture`. Un
        # bitstream con video pero sin esa capacidad --`hdmi`-- devuelve None
        # mientras el simulador devuelve el numero real, asi que comparar ahi
        # hacia fallar el diferencial de `video-registers` contra `hdmi`
        # pasando los dos backends por separado. Es el mismo fallo que tenia
        # `stdout`, y estaba escondido por el mismo motivo: nadie habia corrido
        # esa combinacion.
        if "frame_capture" not in case.get("requires", ()):
            video_excluidos.add("swaps")
        recortado["video"] = {
            k: v for k, v in recortado["video"].items()
            if k not in video_excluidos
        }
    return recortado


def expand_capabilities(names) -> frozenset:
    """Anade las capacidades implicadas por las declaradas."""
    resultado = set(names)
    for name in list(resultado):
        resultado.update(CAPABILITY_IMPLIES.get(name, ()))
    return frozenset(resultado)


def parse_requires(raw: dict, architecture: str) -> list:
    requires = raw.get("requires", [])
    if not isinstance(requires, list):
        raise ValueError("requires debe ser una lista")
    for item in requires:
        if item not in CAPABILITIES:
            opciones = ", ".join(sorted(CAPABILITIES))
            raise ValueError(f"capacidad desconocida {item!r}; opciones: {opciones}")
        if architecture not in CAPABILITIES[item]:
            raise ValueError(
                f"la capacidad {item!r} es de arquitectura "
                f"{'/'.join(CAPABILITIES[item])}, y el caso es {architecture}"
            )
    if len(set(requires)) != len(requires):
        raise ValueError("requires tiene capacidades repetidas")
    return sorted(requires)


def parse_run_until(raw: dict, requires: list) -> dict | None:
    """Condicion de parada distinta de «hasta que el programa haga HALT».

    Hoy solo `swap`: parar al completar el intercambio numero N. Se ancla al
    intercambio y no al contador de frames de video a proposito. Parar cuando
    el contador de frames llega a N para la CPU en un punto cualquiera de su
    dibujo, con el buffer trasero a medias, y lo que se capture depende de la
    velocidad relativa entre la CPU y el barrido: el caso saldria distinto cada
    vez. En el N-esimo intercambio completado el frame esta entero por
    construccion.
    """
    run_until = raw.get("run_until")
    if run_until is None:
        return None
    if not isinstance(run_until, dict) or set(run_until) != {"swap"}:
        raise ValueError("run_until solo admite {\"swap\": N}")
    swap = run_until["swap"]
    if not isinstance(swap, int) or swap < 1:
        raise ValueError("run_until.swap debe ser un entero positivo")
    if "frame_capture" not in requires:
        raise ValueError(
            "run_until.swap necesita requires: [\"frame_capture\"], que es "
            "quien declara que el sistema tiene el registro HALT_AT"
        )
    return {"swap": swap}


ARCHITECTURES = ("cpu", "gpu")


def case_architectures(raw: object) -> tuple[str, ...]:
    """Las arquitecturas en las que el caso puede correr.

    Casi siempre una. Un caso declara las DOS cuando su programa es el mismo
    binario en las dos familias, que exige un solo hilo: sin `GETTID` ni
    reparto de trabajo, porque un programa de GPU reparte entre 64 hilos y uno
    de CPU no. Desde que `SSY` y `BAR` son no-op en la MiniCPU, ese binario
    unico incluye los programas de video —escribir `FB_FRONT`/`FB_BACK`, pedir
    `SWAP`, sondear `STATUS`—, que es justo donde interesa: un caso que pase
    igual en la 21 y en la 22 es la prueba de que el contrato MMIO es uno solo,
    y no dos parecidos.

    `warp_config` se mira contra el conjunto, no contra una: un caso que pueda
    correr como GPU lo necesita aunque tambien pueda correr como CPU, y
    `load_case` lo ignora cuando se resuelve a CPU.
    """
    if not isinstance(raw, dict):
        raise ValueError("El caso requiere architecture: cpu o gpu")
    declared = raw.get("architecture")
    values = tuple(declared) if isinstance(declared, list) else (declared,)
    if not values or any(value not in ARCHITECTURES for value in values):
        raise ValueError("El caso requiere architecture: cpu o gpu")
    if len(set(values)) != len(values):
        raise ValueError("architecture repite una arquitectura")
    if ("warp_config" in raw) != ("gpu" in values):
        raise ValueError("warp_config es obligatorio para GPU y no se admite para CPU")
    return values


def case_architecture(raw: object) -> str:
    """La primera arquitectura declarada, para quien no elige backend."""
    return case_architectures(raw)[0]


def validate_compatibility(architecture, backend_names: tuple[str, ...]) -> None:
    supported_by_case = ((architecture,) if isinstance(architecture, str)
                         else tuple(architecture))
    for name in backend_names:
        supported = BACKEND_DEFINITIONS[name]["architecture"]
        if supported not in supported_by_case:
            raise ValueError(
                f"Caso {'/'.join(supported_by_case)} incompatible con backend "
                f"{name} ({supported})")


def resolve_architecture(architectures: tuple[str, ...],
                         backend_names: tuple[str, ...]) -> str:
    """Con que arquitectura cargar un caso para estos backends.

    Un caso de las dos familias no es ambiguo en el momento de ejecutarlo: lo
    decide el backend. Lo que no puede es correr en una sola pasada contra
    backends de familias distintas, porque el resultado esperado se valida
    contra una (`expect.warps` existe en GPU y no en CPU).
    """
    validate_compatibility(architectures, backend_names)
    supported = {BACKEND_DEFINITIONS[name]["architecture"]
                 for name in backend_names}
    if len(supported) != 1:
        raise ValueError(
            "los backends de una misma ejecucion han de compartir arquitectura, "
            f"y estos son {'/'.join(sorted(supported))}")
    return supported.pop()


def load_case(path: Path, architecture: str | None = None) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    directory = path.parent

    architectures = case_architectures(raw)
    if architecture is None:
        architecture = architectures[0]
    elif architecture not in architectures:
        raise ValueError(
            f"El caso es {'/'.join(architectures)}, no {architecture}")
    gpu = architecture == "gpu"
    warp_config = None
    if gpu:
        warp_config = json.loads((directory / raw["warp_config"]).read_text(encoding="utf-8-sig"))

    if not isinstance(raw.get("name"), str) or not raw["name"]:
        raise ValueError("El caso necesita un nombre")

    program_path = directory / raw["program"]
    program = load_program(program_path)
    if len(program) > ARCHITECTURAL_MEMORY_SIZE:
        raise ValueError(
            f"El programa ocupa {len(program)} bytes; el máximo es "
            f"{ARCHITECTURAL_MEMORY_SIZE}"
        )
    expected_raw = raw["expect"]
    if gpu and ("pc" in expected_raw or "registers" in expected_raw):
        raise ValueError("GPU: PC y registros deben estar dentro de expect.warps")
    if not gpu and any(field in expected_raw for field in ("warps", "instructions_executed", "fault")):
        raise ValueError("warps e instructions_executed requieren --backend gpu-simulator")
    registers = {
        parse_register(name): parse_integer(value, name)
        for name, value in expected_raw.get("registers", {}).items()
    }

    initial_memory = []
    for item in raw.get("initial_memory", []):
        address = parse_integer(item["address"], "dirección inicial")
        data = load_data_file(directory / item["file"])
        if not data:
            raise ValueError(f"El fichero inicial {item['file']} está vacío")
        if address + len(data) > ARCHITECTURAL_MEMORY_SIZE:
            raise ValueError(f"Inicialización fuera del mapa de memoria: {item['file']}")
        initial_memory.append((address, data))

    expected_memory = {}
    for item in expected_raw.get("memory_dumps", []):
        address = parse_integer(item["address"], "dirección de dump")
        data = load_data_file(directory / item["file"])
        if not data:
            raise ValueError(f"El dump esperado {item['file']} está vacío")
        if address + len(data) > ARCHITECTURAL_MEMORY_SIZE:
            raise ValueError(f"Dump fuera del mapa de memoria: {item['file']}")
        expected_memory[(address, len(data))] = data

    requires = parse_requires(raw, architecture)
    run_until = parse_run_until(raw, requires)
    # `frame_capture` implica `video`, asi que un caso que declare la captura
    # no tiene que declarar las dos.
    capacidades = expand_capabilities(requires)

    # --- expectativas de video -------------------------------------------
    #
    # `frame` no lleva direccion a proposito. Tras el intercambio N, FB_FRONT
    # alterna entre los dos buffers segun la paridad, asi que si el caso tuviera
    # que decir la direccion, la mitad de los casos apuntarian al buffer que no
    # es. El backend lee FB_FRONT y vuelca desde ahi.
    expected_video = None
    if "video" in expected_raw:
        video_raw = expected_raw["video"]
        if not isinstance(video_raw, dict) or set(video_raw) - {"underflow"}:
            raise ValueError("expect.video solo admite underflow")
        if not isinstance(video_raw.get("underflow", False), bool):
            raise ValueError("expect.video.underflow debe ser booleano")
        expected_video = {"underflow": video_raw.get("underflow", False)}

    expected_frame = None
    if "frame" in expected_raw:
        frame_raw = expected_raw["frame"]
        if not isinstance(frame_raw, dict) or set(frame_raw) != {"file"}:
            raise ValueError("expect.frame solo admite file")
        expected_frame = load_data_file(directory / frame_raw["file"])
        if not expected_frame:
            raise ValueError(f"El frame esperado {frame_raw['file']} esta vacio")

    if (expected_video or expected_frame is not None) and "video" not in capacidades:
        raise ValueError(
            "las expectativas de video necesitan requires: [\"video\"] o "
            "[\"frame_capture\"]"
        )

    # ------------------------------------------------------------------ serie
    #
    # `stdin` son los bytes que el PC mete en la cola de entrada ANTES de
    # arrancar, y `expect.stdout` lo que tiene que haber en la de salida al
    # parar. Se escriben como texto en el JSON, que es lo que hace legible un
    # caso de consola; para bytes que no son texto, `\xNN`.
    #
    # El limite de 64 bytes es la profundidad de la cola del hardware. Meter
    # mas exigiria ir alimentandola mientras el programa corre, y entonces el
    # caso dejaria de ser determinista: lo que se capture dependeria de lo
    # rapido que vaya la CPU. Un caso de consola tiene que ser
    # peticion-respuesta.
    SERIAL_FIFO_DEPTH = 64
    stdin_raw = raw.get("stdin", "")
    if not isinstance(stdin_raw, str):
        raise ValueError("stdin debe ser una cadena")
    stdin_bytes = stdin_raw.encode("latin-1", "backslashreplace").decode(
        "unicode_escape").encode("latin-1")
    if len(stdin_bytes) > SERIAL_FIFO_DEPTH:
        raise ValueError(
            f"stdin son {len(stdin_bytes)} bytes y la cola tiene "
            f"{SERIAL_FIFO_DEPTH}: un caso mas largo no seria determinista")

    expected_stdout = None
    if "stdout" in expected_raw:
        salida_raw = expected_raw["stdout"]
        if not isinstance(salida_raw, str):
            raise ValueError("expect.stdout debe ser una cadena")
        expected_stdout = salida_raw.encode(
            "latin-1", "backslashreplace").decode(
            "unicode_escape").encode("latin-1")

    if (stdin_bytes or expected_stdout is not None) and "serial" not in capacidades:
        raise ValueError(
            "stdin y expect.stdout necesitan requires: [\"serial\"]")

    max_instructions = raw.get("max_instructions", 1_000_000)
    timeout_seconds = raw.get("timeout_seconds", 5.0)
    if not isinstance(max_instructions, int) or max_instructions < 1:
        raise ValueError("max_instructions debe ser un entero positivo")
    if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds debe ser positivo")

    case = {
        "requires": requires,
        "run_until": run_until,
        "architecture": architecture,
        # Con cual se ha cargado (arriba) y en cuales podria correr (aqui).
        "architectures": architectures,
        "name": raw["name"],
        "program": program,
        "initial_memory": initial_memory,
        "max_instructions": max_instructions,
        "timeout_seconds": float(timeout_seconds),
        "simulator_options": simulator_options(raw, architecture),
        "stdin": stdin_bytes,
        "expected": {
            "stdout": expected_stdout,
            "halted": expected_raw.get("halted", True),
            "error": expected_raw.get("error", False),
            "error_code": parse_integer(
                expected_raw.get("error_code", 0), "error_code"
            ),
            "registers": registers,
            "memory": expected_memory,
            "video": expected_video,
            "frame": expected_frame,
        },
    }
    if gpu:
        if not isinstance(warp_config, dict):
            raise ValueError("warp_config debe contener un objeto JSON")
        size = parse_integer(warp_config.get("warp_size", 8), "warp_size")
        if size == 0:
            raise ValueError("warp_size debe ser positivo")
        case["warp_config"] = warp_config
        case["expected"]["observations"] = gpu_expectations(expected_raw, size)
    elif run_until is not None:
        # Con `run_until` la parada es ASINCRONA: llega cuando se completa el
        # intercambio, y el PC queda donde pillara a la CPU. Exigirlo aqui haria
        # el caso intermitente, asi que se admite no declararlo. Lo que si
        # sigue comprobandose es que paro y que no fue por error.
        if "pc" in expected_raw:
            raise ValueError(
                "con run_until el PC no es determinista: la parada es asincrona"
            )
    else:
        if "pc" in expected_raw:
            case["expected"]["pc"] = parse_integer(expected_raw["pc"], "PC")
    return case


def discover_cases(arguments: list[Path]) -> list[Path]:
    if arguments:
        # Un directorio vale por todos los casos que cuelgan de el, que es como
        # lo documenta el README (`cases/video`).
        encontrados = []
        for path in arguments:
            path = path.resolve()
            if path.is_dir():
                encontrados.extend(sorted(path.glob("**/test.json")))
            else:
                encontrados.append(path)
        return encontrados
    # `cases-shared` son los casos que declaran las DOS arquitecturas: el mismo
    # binario y las mismas expectativas en las dos familias. Tienen carpeta
    # propia porque ahi esta su valor -- si viven mezclados con los de CPU, el
    # dia que uno deje de correr como GPU nadie lo nota.
    return sorted(path for folder in ("cases", "cases-gpu", "cases-shared")
                  for path in (ROOT / folder).glob("**/test.json"))


# ---------------------------------------------------------------------------
# Modo medida
#
# Ejecuta los mismos casos en varias versiones y saca una tabla. Lo que se mide
# NO es el tiempo de pared: entre `run` y `halt` hay decenas de vueltas de USB a
# 1 Mbaud, y eso enmascara por completo un programa de milisegundos. Se mide el
# contador de ciclos de la placa, y el tiempo se deriva de el y del reloj.
#
# El numero de instrucciones es arquitectonico: tiene que salir igual en todas
# las versiones y en el simulador. Cuando no sale igual, la tabla lo dice en vez
# de elegir uno, porque una discrepancia ahi es un fallo de CPU, no una medida.
# ---------------------------------------------------------------------------

def _format_cpi(medida: dict | None) -> str:
    if medida is None:
        return "—"
    if medida.get("skipped"):
        return "n/a"
    cycles, instructions = medida.get("cycles"), medida.get("instructions")
    # `is None` y no verdad logica: 0 instrucciones es una medida real (el
    # caso trampea antes de retirar ninguna), y ahi el CPI esta indefinido,
    # no es que falte el contador.
    if cycles is None or instructions is None:
        return "sin contadores"
    if instructions == 0:
        return "n/d"
    return f"{cycles / instructions:.2f}"


def _format_ms(medida: dict | None) -> str:
    if medida is None:
        return "—"
    if medida.get("skipped"):
        return "n/a"
    cycles, clock_hz = medida.get("cycles"), medida.get("clock_hz")
    if cycles is None or clock_hz is None:
        return "sin contadores"
    return f"{1000.0 * cycles / clock_hz:.3f}"


def _markdown_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def measurement_table(medidas: dict, casos: list[str], versiones: list[str],
                      video_realtime: frozenset = frozenset(),
                      serial_realtime: frozenset = frozenset()) -> str:
    """Tabla en Markdown a partir de `medidas[(caso, version)] -> dict`.

    Cada `dict` lleva `instructions`, `cycles`, `clock_hz`, o `skipped`. Es
    funcion pura a proposito: la parte que da forma a la tabla se puede probar
    entera sin placa, que es la mitad del codigo y la que mas se toca.

    `video_realtime`/`serial_realtime`: nombres de casos que sincronizan con
    algo real (vsync o bytes de UART) en vez de con un numero fijo de
    instrucciones. Su numero de instrucciones VARIA por diseno segun el reloj
    o el baudrate de cada version — no es una discrepancia de CPU, así que se
    marcan con `*1`/`*2` en vez de disparar el aviso de "¡discrepan!".
    """
    lineas = ["## Ciclos por instruccion", ""]
    lineas.append(_markdown_row(["Caso", "Instr."] + versiones))
    lineas.append(_markdown_row(["---", "---:"] + ["---:"] * len(versiones)))

    discrepancias = []
    notas_usadas = set()
    for caso in casos:
        fila = [medidas.get((caso, v)) for v in versiones]
        # `is not None` y no verdad logica: cero instrucciones es una medida
        # real (el programa trampea en la primera), y un hueco no lo es.
        contadas = {
            m["instructions"] for m in fila
            if m and not m.get("skipped") and m.get("instructions") is not None
        }
        if len(contadas) > 1 and caso in video_realtime:
            instr, nota = "¡varía! *1", 1
        elif len(contadas) > 1 and caso in serial_realtime:
            instr, nota = "¡varía! *2", 2
        elif len(contadas) > 1:
            instr, nota = "¡discrepan!", None
            discrepancias.append((caso, sorted(contadas)))
        elif contadas:
            instr, nota = f"{contadas.pop():,}".replace(",", " "), None
        else:
            instr, nota = "—", None
        if nota is not None:
            notas_usadas.add(nota)
        lineas.append(_markdown_row(
            [caso, instr] + [_format_cpi(m) for m in fila]))

    lineas += ["", "## Tiempo de CPU (ms)", ""]
    lineas.append(_markdown_row(["Caso"] + versiones))
    lineas.append(_markdown_row(["---"] + ["---:"] * len(versiones)))
    for caso in casos:
        lineas.append(_markdown_row(
            [caso] + [_format_ms(medidas.get((caso, v))) for v in versiones]))

    lineas += [
        "",
        "`n/a`: la version no admite el caso (mapa de memoria o capacidades).",
        "`sin contadores`: la version no tiene los comandos 0x36/0x37, o es",
        "el simulador, que cuenta instrucciones pero no modela el tiempo.",
        "`n/d`: 0 instrucciones retiradas (el caso trampea desde el arranque);",
        "el CPI esta indefinido, no es que falte el contador.",
        "",
        "El tiempo sale de los ciclos y del reloj, no del reloj de pared: entre",
        "arrancar y parar la CPU hay decenas de vueltas de UART que no son parte",
        "del programa.",
    ]
    if discrepancias:
        lineas += ["", "> **Aviso**: el numero de instrucciones no coincide entre",
                   "> versiones. Eso no es una medida lenta, es una CPU que hace",
                   "> cosas distintas:"]
        for caso, valores in discrepancias:
            lineas.append(f"> - `{caso}`: {valores}")
    if 1 in notas_usadas:
        lineas += ["",
                  "*1: el numero de instrucciones varia por diseno, no es un fallo de",
                  "CPU: el caso espera un intercambio de framebuffer real (vsync), que",
                  "ocurre a un ritmo fijo en el tiempo; una version con reloj mas rapido",
                  "ejecuta mas vueltas de espera en el mismo tiempo real."]
    if 2 in notas_usadas:
        lineas += ["",
                  "*2: el numero de instrucciones varia por diseno, no es un fallo de",
                  "CPU: el caso espera bytes reales por UART, y el numero de vueltas de",
                  "espera depende del baudrate de cada version, no de su arquitectura."]
    return "\n".join(lineas) + "\n"


def run_measurements(case_paths, versiones, args, upload_policy) -> int:
    """Ejecuta cada caso en cada version y escribe la tabla.

    Cambiar de version recarga el bitstream, asi que el bucle exterior es la
    version y no el caso: al reves seria una carga por caso y por version.
    """
    casos = []
    for path in case_paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if "cpu" not in case_architectures(raw):
                continue
            # Explicito: un caso de las dos familias se mide como CPU, que es
            # lo unico que esta tabla compara.
            case = load_case(path, "cpu")
        except (OSError, ValueError, TypeError, KeyError) as error:
            print(f"ERROR {path}: {error}", file=sys.stderr)
            return 2
        casos.append(case)
    if not casos:
        print("No hay casos de CPU que medir", file=sys.stderr)
        return 2

    # Se detecta una sola vez, no en cada versión FPGA del bucle.
    port = args.port
    if port is None and any(version != "sim" for version in versiones):
        port = board.detect_port()

    medidas = {}
    for version in versiones:
        simulador = version == "sim"
        if simulador:
            backend = SimulatorBackend(REPOSITORY)
        else:
            try:
                backend = FpgaBackend(
                    REPOSITORY, port=port,
                    serial_timeout=args.serial_timeout, version=version,
                    upload_policy=upload_policy,
                )
            except (board.BoardNotConnected, board.MonitorSilent,
                    board.BitstreamMismatch) as error:
                print(f"ERROR [{version}]: {error}", file=sys.stderr)
                return 2

        for case in casos:
            clave = (case["name"], version)
            modulo = BACKEND_DEFINITIONS[
                "cpu-simulator" if simulador else "cpu-fpga"]["module"]
            comprueba = getattr(modulo, "incompatibility", None)
            motivo = None
            if comprueba:
                motivo = (comprueba(case) if simulador
                          else comprueba(case, version))
            if motivo:
                medidas[clave] = {"skipped": True, "reason": motivo}
                print(f"SKIP {case['name']} [{version}]: {motivo}")
                continue
            try:
                result = backend.run(
                    program=case["program"],
                    initial_memory=case["initial_memory"],
                    register_numbers=set(case["expected"]["registers"]),
                    memory_ranges=list(case["expected"]["memory"]),
                    max_instructions=case["max_instructions"],
                    timeout_seconds=case["timeout_seconds"],
                    stdin=case["stdin"],
                    **({"video": {
                        "run_until_swap": (case["run_until"] or {}).get("swap"),
                        "capture_frame": case["expected"]["frame"] is not None,
                    }} if (case["run_until"] or case["expected"]["video"]
                           or case["expected"]["frame"] is not None) else {}),
                )
            except Exception as error:
                medidas[clave] = {"skipped": True, "reason": str(error)}
                print(f"ERROR {case['name']} [{version}]: {error}",
                      file=sys.stderr)
                continue
            # Se compara con lo que el caso ESPERA, no con "sin error": los
            # casos de trampa terminan en error a proposito y su CPI es tan
            # valido como el de los demas. Lo que no mide nada es un programa
            # que hizo algo distinto de lo previsto.
            if (result["halted"] != case["expected"]["halted"]
                    or result["error"] != case["expected"]["error"]):
                medidas[clave] = {"skipped": True, "reason": "resultado inesperado"}
                print(f"ERROR {case['name']} [{version}]: resultado inesperado")
                continue
            medidas[clave] = {
                "instructions": result.get("instructions"),
                "cycles": result.get("cycles"),
                "clock_hz": result.get("clock_hz"),
            }
            print(f"PROFILED {case['name']} [{version}]: "
                  f"CPI {_format_cpi(medidas[clave])}")

    # Casos que sincronizan con algo real (vsync o UART) en vez de con un
    # numero fijo de instrucciones: su recuento varia por diseno entre
    # versiones con reloj o baudrate distintos, no es un fallo de CPU.
    video_realtime = frozenset(
        case["name"] for case in casos
        if {"video", "frame_capture"} & set(case["requires"]))
    serial_realtime = frozenset(case["name"] for case in casos if case["stdin"])

    tabla = measurement_table(
        medidas, [case["name"] for case in casos], list(versiones),
        video_realtime=video_realtime, serial_realtime=serial_realtime)
    args.measure.write_text(tabla, encoding="utf-8")
    print(f"\nTabla escrita en {args.measure}")
    print(tabla)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", nargs="*", type=Path, metavar="TEST_JSON")
    parser.add_argument(
        "--backend",
        choices=(
            "cpu-simulator", "cpu-fpga", "both",
            "gpu-simulator", "gpu-fpga", "gpu-both",
        ),
        default="gpu-simulator",
    )
    parser.add_argument("--port", default=None,
                        help="por defecto, detecta el primer adaptador FTDI conectado")
    parser.add_argument("--serial-timeout", type=float, default=1.0)
    parser.add_argument(
        "--version",
        action="append",
        default=[],
        metavar="[BACKEND=]VERSION",
        help="versión del backend; puede repetirse al usar varios backends",
    )
    parser.add_argument("--trace", action="store_true",
                        help="traza del scheduler GPU por instrucción de warp")
    parser.add_argument("--trace-detail", action="store_true",
                        help="incluye registros y memoria en la traza GPU")
    parser.add_argument("--trace-limit", type=int,
                        help="máximo de eventos mostrados; no limita la ejecución")
    parser.add_argument("--trace-file", type=Path,
                        help="guarda la traza GPU en este fichero")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="autoriza sin preguntar la carga del bitstream "
                             "si la placa tiene otra versión")
    parser.add_argument("--no-upload", action="store_true",
                        help="nunca cargar el bitstream: si la placa no tiene "
                             "la versión correcta, falla")
    parser.add_argument("--measure", type=Path, nargs="?",
                        const=Path("medidas.md"), default=None, metavar="FICHERO",
                        help="ejecuta cada caso en todas las versiones "
                             "aplicables y escribe una tabla Markdown con "
                             "instrucciones, tiempo y CPI "
                             "(medidas.md si se omite el nombre)")
    parser.add_argument("--durations", type=int, nargs="?", const=10, default=0,
                        metavar="N",
                        help="lista las N ejecuciones más lentas al terminar "
                             "(10 si se omite el valor)")
    args = parser.parse_args()
    if args.trace_limit is not None and args.trace_limit < 0:
        parser.error("--trace-limit no puede ser negativo")
    if (args.trace or args.trace_detail or args.trace_limit is not None or args.trace_file is not None) and args.backend != "gpu-simulator":
        parser.error("las opciones --trace solo están disponibles con --backend gpu-simulator")
    if args.yes and args.no_upload:
        parser.error("--yes y --no-upload se contradicen")
    if args.durations < 0:
        parser.error("--durations no puede ser negativo")

    case_paths = discover_cases(args.cases)
    if not case_paths:
        print("No se encontraron casos", file=sys.stderr)
        return 2

    if args.measure is not None:
        if args.backend.startswith("gpu"):
            parser.error("--measure es de los backends de CPU")
        # Las versiones a medir: las que se pidan con --version, o todas las
        # del backend FPGA mas el simulador, que aporta las instrucciones de
        # los casos que ninguna placa puede contar.
        pedidas = [v.split("=", 1)[-1] for v in args.version]
        if not pedidas:
            pedidas = list(fpga_backend.VERSIONS) + ["sim"]
        desconocidas = [v for v in pedidas
                        if v != "sim" and v not in fpga_backend.VERSIONS]
        if desconocidas:
            parser.error(f"versiones desconocidas: {', '.join(desconocidas)}")
        return run_measurements(
            case_paths, pedidas, args,
            board.UploadPolicy(allowed=not args.no_upload,
                               assume_yes=args.yes),
        )

    backend_groups = {
        "both": ("cpu-simulator", "cpu-fpga"),
        "gpu-both": ("gpu-simulator", "gpu-fpga"),
    }
    backend_names = backend_groups.get(args.backend, (args.backend,))
    try:
        backend_versions = resolve_backend_versions(args.version, backend_names)
    except ValueError as error:
        parser.error(str(error))

    # Valida todos los casos antes de construir backends o contactar hardware.
    cases = []
    skipped = 0
    try:
        for path in case_paths:
            raw = json.loads(path.read_text(encoding="utf-8"))
            architectures = case_architectures(raw)
            if not args.cases and any(
                BACKEND_DEFINITIONS[name]["architecture"] not in architectures
                for name in backend_names
            ):
                skipped += 1
                continue
            # La familia la elige el backend, no el caso: uno que declare las
            # dos se carga como CPU contra un backend de CPU y como GPU contra
            # uno de GPU, con el mismo binario.
            architecture = resolve_architecture(architectures, backend_names)
            # Las profundidades SIMT son parámetros del simulador: la FPGA las
            # tiene fijadas en el hardware y no puede reproducir el caso.
            if simulator_options(raw, architecture) and backend_names != ("gpu-simulator",):
                if not args.cases:
                    print(f"SKIP {raw.get('name', path)}: simulator_options requiere gpu-simulator")
                    skipped += 1
                    continue
                raise ValueError("simulator_options requiere --backend gpu-simulator")
            case = load_case(path, architecture)
            # Cada backend decide si el caso cabe en su mapa; los que no
            # publican `incompatibility` aceptan todo lo que valide load_case.
            reason = None
            for name in backend_names:
                check = getattr(BACKEND_DEFINITIONS[name]["module"],
                                "incompatibility", None)
                reason = check(case, backend_versions[name]) if check else None
                if reason:
                    reason = f"[{name}]: {reason}"
                    break
            if reason:
                if args.cases:
                    raise ValueError(reason)
                print(f"SKIP {case['name']} {reason}")
                skipped += 1
                continue
            cases.append((path, case))
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"ERROR {path}: {error}", file=sys.stderr)
        return 2
    if not cases:
        print("No se encontraron casos compatibles", file=sys.stderr)
        return 2

    backends = {}
    if "gpu-simulator" in backend_names:
        backends["gpu-simulator"] = GpuBackend(REPOSITORY, version=backend_versions["gpu-simulator"])
    if "cpu-simulator" in backend_names:
        backends["cpu-simulator"] = SimulatorBackend(
            REPOSITORY,
            version=backend_versions["cpu-simulator"],
        )
    upload_policy = board.UploadPolicy(
        allowed=not args.no_upload, assume_yes=args.yes
    )
    port = args.port
    if port is None and ("cpu-fpga" in backend_names or "gpu-fpga" in backend_names):
        port = board.detect_port()
    # Construir un backend FPGA comprueba la placa y, si hace falta y se
    # autoriza, carga el bitstream. Es el fallo más habitual del flujo con
    # hardware, así que merece un mensaje y no un volcado de pila.
    try:
        if "cpu-fpga" in backend_names:
            backends["cpu-fpga"] = FpgaBackend(
                REPOSITORY,
                port=port,
                serial_timeout=args.serial_timeout,
                version=backend_versions["cpu-fpga"],
                upload_policy=upload_policy,
            )
        if "gpu-fpga" in backend_names:
            backends["gpu-fpga"] = GpuFpgaBackend(
                REPOSITORY,
                port=port,
                serial_timeout=args.serial_timeout,
                version=backend_versions["gpu-fpga"],
                upload_policy=upload_policy,
            )
    except (board.BoardNotConnected, board.MonitorSilent,
            board.BitstreamMismatch) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    failures = 0
    durations: list[tuple[float, str, str]] = []
    started = time.monotonic()
    for path, case in cases:
        try:
            results = {}
            for backend_name, backend in backends.items():
                begun = time.monotonic()
                result = backend.run(
                    program=case["program"],
                    initial_memory=case["initial_memory"],
                    register_numbers=set(case["expected"]["registers"]),
                    memory_ranges=list(case["expected"]["memory"]),
                    max_instructions=case["max_instructions"],
                    timeout_seconds=case["timeout_seconds"],
                    # Solo los backends de CPU tienen puerto serie. La MiniGPU
                    # no lo ha recibido todavia, y pasarselo seria un
                    # TypeError.
                    **({"stdin": case["stdin"]}
                       if case["architecture"] == "cpu" else {}),
                    **({"warp_config": case["warp_config"]} if case["architecture"] == "gpu" else {}),
                    **({"observation_fields": set(case["expected"]["observations"])}
                       if backend_name == "gpu-fpga" else {}),
                    # Solo se pasa cuando el caso lo pide: asi un caso normal no
                    # paga las lecturas de registros ni el volcado del frame.
                    # `run_until_swap` solo significa algo donde hay HALT_AT, y
                    # la GPU no lo tiene -- ver VideoDevice en minigpu_sim.py-,
                    # pero llega igual y el backend de GPU lo rechaza, en vez de
                    # aceptarlo y no pararse.
                    **({"video": {
                        "run_until_swap": (case["run_until"] or {}).get("swap"),
                        "capture_frame": case["expected"]["frame"] is not None,
                    }} if backend_name in ("cpu-fpga", "cpu-simulator",
                                           "gpu-simulator", "gpu-fpga") and (
                        case["run_until"] or case["expected"]["video"]
                        or case["expected"]["frame"] is not None) else {}),
                    **({
                        "trace": args.trace,
                        "trace_detail": args.trace_detail,
                        "trace_limit": args.trace_limit,
                        "trace_file": args.trace_file,
                        "simulator_options": case["simulator_options"],
                    } if backend_name == "gpu-simulator" else {}),
                )
                elapsed = time.monotonic() - begun
                durations.append((elapsed, case["name"], backend_name))
                results[backend_name] = result
                errors = compare_result(case, result, backend_name)
                # El tiempo solo se anota junto al caso cuando es alto, para no
                # ensuciar la salida de los casos rápidos.
                slow = f" ({elapsed:.1f}s)" if elapsed >= SLOW_CASE_SECONDS else ""
                if errors:
                    failures += 1
                    print(f"FAIL {case['name']} [{backend_name}]{slow}")
                    for error in errors:
                        print(f"  {error}")
                else:
                    print(f"PASS {case['name']} [{backend_name}]{slow}")

            if args.backend == 'gpu-both':
                left, right = results['gpu-simulator'], results['gpu-fpga']
                fields = case['expected']['observations']
                mismatch = any(left[field] != right[field] for field in ('halted', 'error', 'error_code', 'memory'))
                mismatch |= any(left['observations'].get(key, '<ausente>') != right['observations'].get(key, '<ausente>') for key in fields)
                if mismatch:
                    failures += 1
                    print(f"FAIL {case['name']} [diferencial GPU]: los estados observados no coinciden")
            observado = {nombre: comparable(resultado, case)
                         for nombre, resultado in results.items()}
            if args.backend == 'both' and observado["cpu-simulator"] != observado["cpu-fpga"]:
                failures += 1
                print(f"FAIL {case['name']} [diferencial]")
                # Decir QUE campo difiere, y no solo que algo difiere. Sin esto
                # el fallo obligaba a reproducir el caso a mano en los dos
                # backends para averiguar por donde iba la diferencia.
                simulador, fpga = observado["cpu-simulator"], observado["cpu-fpga"]
                for clave in sorted(set(simulador) | set(fpga)):
                    izquierda = simulador.get(clave, "<ausente>")
                    derecha = fpga.get(clave, "<ausente>")
                    if izquierda != derecha:
                        print(f"  {clave}: simulador={izquierda!r} fpga={derecha!r}")
        except Exception as error:
            failures += 1
            print(f"ERROR {path}: {error}", file=sys.stderr)

    if args.durations and durations:
        print(f"\n{min(args.durations, len(durations))} ejecución(es) más lentas:")
        for elapsed, name, backend_name in sorted(durations, reverse=True)[:args.durations]:
            print(f"  {elapsed:7.2f}s  {name} [{backend_name}]")

    total = time.monotonic() - started
    print(f"{len(cases)} caso(s), {failures} fallo(s), "
          f"{skipped} omitido(s) por arquitectura o capacidades, {total:.1f}s")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
