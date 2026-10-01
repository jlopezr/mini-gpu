"""Carga común de un framebuffer en una placa, sin ejecutar CPU ni GPU."""

from __future__ import annotations

from pathlib import Path

from tools.mmio_map import (
    MMIO_VIDEO_BASE,
    MMIO_VIDEO_CTRL_OFF,
    MMIO_VIDEO_FB_BACK_OFF,
    MMIO_VIDEO_FB_FRONT_OFF,
    MMIO_VIDEO_MODE_SCANOUT,
)

FB_FRONT = MMIO_VIDEO_BASE + MMIO_VIDEO_FB_FRONT_OFF
FB_BACK = MMIO_VIDEO_BASE + MMIO_VIDEO_FB_BACK_OFF
VIDEO_CTRL = MMIO_VIDEO_BASE + MMIO_VIDEO_CTRL_OFF


def _write_register(prototype_dir: Path, port: str, address: int, value: int) -> None:
    # Una palabra atómica: el scanout sigue activo mientras el núcleo está en reset.
    from tools.run_board import run_monitor_cli

    run_monitor_cli(prototype_dir, port, "write-word",
                    f"0x{address:08x}", f"0x{value:08x}")


def upload_framebuffer(prototype: str, port: str | None, framebuffer: Path,
                       address: int) -> int:
    from tools.run_board import detect_port, resolve_target, run_monitor_cli

    target = resolve_target(prototype)
    selected_port = port if port is not None else detect_port()
    prototype_dir = target.prototype_dir

    if "video" not in target.capability.get("capabilities", ()):
        raise SystemExit(f"error: {prototype_dir.name} no tiene vídeo; "
                         "nada que mostrar en el monitor")
    if address % 16:
        raise SystemExit("error: la dirección del framebuffer debe estar alineada a 16 bytes")

    run_monitor_cli(prototype_dir, selected_port, "reset")
    print(f"Escribiendo {framebuffer.stat().st_size} bytes en 0x{address:08x}...")
    run_monitor_cli(prototype_dir, selected_port, "write-block",
                    f"0x{address:08x}", str(framebuffer.resolve()))
    _write_register(prototype_dir, selected_port, FB_FRONT, address)
    _write_register(prototype_dir, selected_port, FB_BACK, address)
    _write_register(prototype_dir, selected_port, VIDEO_CTRL, MMIO_VIDEO_MODE_SCANOUT)
    print("Framebuffer cargado; la imagen debería estar en el monitor.")
    return 0
