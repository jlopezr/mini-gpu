#!/usr/bin/env python3
"""Compatibility entry point for the current MiniISA assembler.

The original implementation lives in asm1/mini_asm.py. New code lives in
asm2/mini-asm.py, but a lot of tools still import or execute 1.isa/mini_asm.py.
Keep this small bridge until those callers move to asm2 explicitly.
"""

from __future__ import annotations

import importlib.util
import runpy
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ASM2 = HERE / "asm2"
ASM2_MAIN = ASM2 / "mini-asm.py"


def _prepend_asm2() -> None:
    path = str(ASM2)
    if path not in sys.path:
        sys.path.insert(0, path)


def _load_impl():
    _prepend_asm2()
    spec = importlib.util.spec_from_file_location("_mini_asm2_impl", ASM2_MAIN)
    if spec is None or spec.loader is None:
        raise ImportError(f"no se puede cargar {ASM2_MAIN}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    _prepend_asm2()
    runpy.run_path(str(ASM2_MAIN), run_name="__main__")
else:
    _impl = _load_impl()
    for _name, _value in vars(_impl).items():
        if _name not in {"__name__", "__package__", "__loader__", "__spec__"}:
            globals()[_name] = _value
