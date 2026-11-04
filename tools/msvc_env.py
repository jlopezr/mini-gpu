"""Entorno x86 de MSVC (cl) en Windows, compartido por mini-lcc y mini-cc."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def ensure_msvc_environment() -> bool:
    """Carga el entorno x86 de MSVC cuando cl no esta ya en PATH."""
    if shutil.which("cl"):
        return True

    program_files_x86 = os.environ.get("ProgramFiles(x86)", "")
    program_files = os.environ.get("ProgramFiles", "")
    candidates: list[Path] = []
    vswhere = Path(program_files_x86) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if vswhere.exists():
        result = subprocess.run(
            [str(vswhere), "-all", "-products", "*", "-property", "installationPath"],
            capture_output=True, text=True, check=False
        )
        candidates.extend(Path(line.strip()) for line in result.stdout.splitlines() if line.strip())
    candidates.extend([
        Path(program_files) / "Microsoft Visual Studio" / "2022" / "Community",
        Path(program_files) / "Microsoft Visual Studio" / "2022" / "BuildTools",
        Path(program_files_x86) / "Microsoft Visual Studio" / "2019" / "BuildTools",
    ])

    vcvars = next((root / "VC" / "Auxiliary" / "Build" / "vcvars32.bat"
                   for root in candidates
                   if (root / "VC" / "Auxiliary" / "Build" / "vcvars32.bat").exists()), None)
    if vcvars is None:
        return False
    result = subprocess.run(
        f'call "{vcvars}" >nul 2>&1 && set',
        shell=True, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return False
    for line in result.stdout.splitlines():
        name, separator, value = line.partition("=")
        if separator:
            os.environ[name] = value
    return shutil.which("cl") is not None
