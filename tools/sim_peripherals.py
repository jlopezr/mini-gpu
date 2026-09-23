"""Configuración y salidas comunes de periféricos de los tres simuladores."""
import re
import sys
from pathlib import Path
from tools.sim_devices import VideoDevice, SerialDevice

FRAME_BYTES = 320 * 240 * 2
VIDEO_SYMBOL_RE = re.compile(r"\bMMIO_VIDEO_[A-Za-z0-9_]*\b")


def add_arguments(parser):
    group = parser.add_argument_group("periféricos funcionales compartidos")
    group.add_argument("--video", action="store_true", help="habilita registros MMIO de vídeo")
    group.add_argument("--frame-instructions", type=int, default=1000,
                       help="instrucciones CPU/de warp por frame sintético (1000)")
    group.add_argument("--halt-after-swaps", type=int,
                       help="habilita vídeo y para tras N intercambios")
    group.add_argument("--frame-output", type=Path, help="habilita vídeo y guarda FB_FRONT en RGB565 320x240")
    group.add_argument("--serial", action="store_true", help="habilita el puerto serie MMIO")
    group.add_argument("--serial-input", type=Path, help="habilita serie y carga bytes de entrada")
    group.add_argument("--serial-output", type=Path, help="habilita serie y guarda los bytes de salida")


def video_requested(args) -> bool:
    return bool(args.video or args.frame_output
                or args.halt_after_swaps is not None)


def missing_video_warning(program: Path, args) -> str | None:
    """Mensaje si un ASM parece usar vídeo pero no se creó el periférico."""
    program = Path(program)
    if video_requested(args) or program.suffix.lower() != ".asm":
        return None
    source = program.read_text(encoding="utf-8")
    if VIDEO_SYMBOL_RE.search(source) is None:
        return None
    return ("el programa usa símbolos MMIO_VIDEO_* pero el periférico de "
            "vídeo no está habilitado; vuelve a ejecutar con --video")


def warn_missing_video(program: Path, args) -> bool:
    """Imprime el aviso para las CLI que no tienen consola propia."""
    warning = missing_video_warning(program, args)
    if warning is None:
        return False
    print(f"AVISO: {warning}", file=sys.stderr)
    return True


def from_arguments(args):
    if args.frame_instructions <= 0:
        raise ValueError("frame-instructions debe ser positivo")
    if args.halt_after_swaps is not None and args.halt_after_swaps <= 0:
        raise ValueError("halt-after-swaps debe ser positivo")
    video = None
    if video_requested(args):
        video = VideoDevice(frame_instructions=args.frame_instructions)
        if args.halt_after_swaps:
            # Esta opción es una condición del host basada en SWAP_COUNT. No
            # se implementa con HALT_AT: en MMIO v2 ese registro cuenta frames
            # de vídeo y además necesita HALT_TARGET.
            video.stop_after_swaps = args.halt_after_swaps
    serial = None
    if args.serial or args.serial_input or args.serial_output:
        serial = SerialDevice(stdin=args.serial_input.read_bytes() if args.serial_input else b"")
        serial.attach_host()
    return {"video": video, "serial": serial}


def video_result(machine, capture=False):
    video = machine.video
    if video is None:
        return None
    frame = None
    if capture:
        base = video.fb_front
        if base < 0 or base + FRAME_BYTES > len(machine.memory):
            raise ValueError("framebuffer fuera de RAM")
        frame = bytes(machine.memory[base:base + FRAME_BYTES])
    return dict(underflow=False, frames=video.frame_count, swaps=video.swap_count,
                fb_front=video.fb_front, frame=frame)


def write_outputs(args, machine):
    if args.frame_output:
        args.frame_output.write_bytes(video_result(machine, True)["frame"])
    if args.serial_output:
        args.serial_output.write_bytes(machine.serial.output())
