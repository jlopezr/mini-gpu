"""Configuración y salidas comunes de periféricos de los tres simuladores."""
import re
import sys
from pathlib import Path
from tools.sim_devices import VideoDevice, SerialDevice, InputDevice

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
    group.add_argument("--console", action="store_true",
                       help="habilita vídeo con la consola de texto 80x30 (CONFIG, paleta, texto)")
    group.add_argument("--console-output", type=Path,
                       help="habilita --console y guarda la pantalla de texto al terminar (UTF-8)")
    group.add_argument("--console-image", type=Path,
                       help="habilita --console y guarda la pantalla como PNG 640x480, "
                            "dibujada con --console-font y sobre el framebuffer si se usa")
    group.add_argument("--console-font", default="cpc464",
                       help="fuente de --console-image: nombre en "
                            "30.fpga-cpu-console/fonts (pc, cpc464, tamzen) o ruta a un .hex")
    group.add_argument("--serial", action="store_true", help="habilita el puerto serie MMIO")
    group.add_argument("--serial-input", type=Path, help="habilita serie y carga bytes de entrada")
    group.add_argument("--serial-output", type=Path, help="habilita serie y guarda los bytes de salida")
    group.add_argument("--window", action="store_true",
                       help="abre una ventana con la pantalla (framebuffer, consola o ambos) y "
                            "conecta su teclado y ratón a INPUT; implica vídeo. F12 para el simulador")
    group.add_argument("--keyboard", action="store_true",
                       help="habilita INPUT (mmio.md §25) con un teclado presente desde el principio")
    group.add_argument("--mouse", action="store_true",
                       help="habilita INPUT con un ratón presente desde el principio")
    group.add_argument("--input-script", type=Path,
                       help="habilita INPUT y carga un guion de entrada (tools/input_script.py); "
                            "el guion conecta lo que no pidan --keyboard/--mouse")


def video_requested(args) -> bool:
    return bool(args.video or args.frame_output or console_requested(args)
                or args.halt_after_swaps is not None or getattr(args, "window", False))


def console_requested(args) -> bool:
    return bool(getattr(args, "console", False)
                or getattr(args, "console_output", None)
                or getattr(args, "console_image", None))


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
        video = VideoDevice(frame_instructions=args.frame_instructions,
                            console=console_requested(args))
        if args.halt_after_swaps:
            # Esta opción es una condición del host basada en SWAP_COUNT. No
            # se implementa con HALT_AT: es un registro del contrato, que el
            # programa ve, y además necesita HALT_TARGET.
            video.stop_after_swaps = args.halt_after_swaps
    serial = None
    if args.serial or args.serial_input or args.serial_output:
        serial = SerialDevice(stdin=args.serial_input.read_bytes() if args.serial_input else b"")
        serial.attach_host()
    return {"video": video, "serial": serial, "input_device": input_from_arguments(args)}


def input_from_arguments(args):
    """El INPUT que piden `--keyboard`, `--mouse` e `--input-script`, o None."""
    keyboard = getattr(args, "keyboard", False)
    mouse = getattr(args, "mouse", False)
    script = getattr(args, "input_script", None)
    window = getattr(args, "window", False)
    if not (keyboard or mouse or script or window):
        return None
    from tools import input_script
    # Con ventana, teclado y ratón los conecta la propia ventana al abrirse.
    actions = input_script.load(script, keyboard or window, mouse or window) if script else []
    device = InputDevice()
    if keyboard:
        device.connect_keyboard()
    if mouse:
        device.connect_mouse()
    device.attach_script(actions)
    if window:
        from tools.sim_display import SimDisplay
        device.attach_host(SimDisplay(resolve_font(args.console_font)))
    return device


def start_display(machine):
    """Abre la ventana de `--window`, si se pidió. Llamar con el simulador ya
    construido y antes de ejecutarlo."""
    device = getattr(machine, "input", None)
    host = getattr(device, "host", None)
    if host is not None:
        host.bind(machine)
        host.start(device)
    return host


def finish_display(machine) -> None:
    """Al acabar el programa, deja la última imagen hasta que se cierre la ventana."""
    device = getattr(machine, "input", None)
    host = getattr(device, "host", None)
    if host is not None:
        host.finish(device)


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


def resolve_font(spec: str) -> Path:
    """`spec` es una ruta a un .hex o el nombre de una fuente de la 30."""
    if Path(spec).is_file():
        return Path(spec)
    fonts = Path(__file__).resolve().parents[1] / "30.fpga-cpu-console" / "fonts"
    named = fonts / f"font8x16_{spec}.hex"
    if not named.is_file():
        known = ", ".join(p.stem.removeprefix("font8x16_") for p in sorted(fonts.glob("*.hex")))
        raise ValueError(f"fuente desconocida: {spec}. Disponibles: {known}")
    return named


def write_console_image(args, machine):
    from tools import console_render
    video = machine.video
    framebuffer = None
    if video.video_mode == video.MODE_SCANOUT:
        base = video.fb_front
        if 0 <= base and base + FRAME_BYTES <= len(machine.memory):
            framebuffer = bytes(machine.memory[base:base + FRAME_BYTES])
    font = console_render.load_font(resolve_font(args.console_font))
    console_render.write_png(
        args.console_image,
        console_render.render_rgb(video.text_ram, video.palette, font, framebuffer))


def write_outputs(args, machine):
    if args.frame_output:
        args.frame_output.write_bytes(video_result(machine, True)["frame"])
    if getattr(args, "console_output", None):
        args.console_output.write_text("\n".join(machine.video.text_lines()) + "\n",
                                       encoding="utf-8")
    if getattr(args, "console_image", None):
        write_console_image(args, machine)
    if args.serial_output:
        args.serial_output.write_bytes(machine.serial.output())
