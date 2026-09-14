#!/usr/bin/env python3
"""Resolución compartida de prototipos y utilidades de repositorio."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


class PrototypeResolutionError(ValueError):
    """Error de resolución del prototipo."""


class ToolchainError(RuntimeError):
    """La herramienta externa (oss-cad-suite) no está disponible."""


def find_oss_cad_suite() -> Path:
    """Localiza la instalación de oss-cad-suite que gestiona apio."""
    suite = Path.home() / ".apio" / "packages" / "oss-cad-suite"
    if not suite.exists():
        raise ToolchainError(
            f"No se encontró oss-cad-suite en {suite}. Instala el paquete de apio "
            "correspondiente (apio packages install oss-cad-suite)."
        )
    return suite


def oss_cad_suite_env() -> dict[str, str]:
    """Entorno con el PATH de oss-cad-suite anteponiendo sus binarios."""
    suite = find_oss_cad_suite()
    env = dict(os.environ)
    parts = [str(suite / part) for part in ("bin", "lib", "py3bin") if (suite / part).exists()]
    env["PATH"] = os.pathsep.join(parts + [env.get("PATH", "")])
    return env


def find_toolchain_binary(name: str) -> Path:
    """Resuelve el ejecutable `name` dentro de oss-cad-suite, multiplataforma."""
    suite = find_oss_cad_suite()
    filename = f"{name}.exe" if os.name == "nt" else name
    exe = suite / "bin" / filename
    if not exe.exists():
        raise ToolchainError(f"No se encontró {filename} en {suite / 'bin'}.")
    return exe


def find_apio_binary(root: Path) -> str:
    """Resuelve el ejecutable de apio, multiplataforma: prueba `.venv` antes
    de confiar en el PATH, igual que hace x.tests/backends/board.py."""
    filename = "apio.exe" if os.name == "nt" else "apio"
    candidates = (root / ".venv" / "Scripts" / filename, root / ".venv" / "bin" / filename)
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return "apio"


def read_ecp5_params(scons_params_text: str) -> dict[str, str]:
    """Extrae type/package/speed de `ecp5_params` dentro de `scons.params`
    (lo que apio genera al sintetizar), para no asumir la placa a mano."""
    body_match = re.search(r"ecp5_params\s*\{([^}]*)\}", scons_params_text)
    if not body_match:
        raise ToolchainError("scons.params no tiene un bloque ecp5_params; ¿es un proyecto ECP5?")
    body = body_match.group(1)
    result = {}
    for key in ("type", "package", "speed"):
        match = re.search(rf'{key}:\s*"([^"]+)"', body)
        if not match:
            raise ToolchainError(f"scons.params: no se encontró '{key}' dentro de ecp5_params")
        result[key] = match.group(1)
    return result


def find_repo_root(start: Path | None = None) -> Path:
    """Busca la raíz del repositorio a partir de varias señales."""
    candidates: list[Path] = []
    env_root = os.environ.get("MINI_GPU_ROOT")
    if env_root:
        candidates.append(Path(env_root).resolve())

    if start is not None:
        current = start.resolve()
        candidates.append(current)
        candidates.extend(parent for parent in [current, *current.parents])

    here = Path(__file__).resolve()
    candidates.append(here.parent.parent)
    candidates.extend(parent for parent in here.parents)

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        marker_files = [candidate / "README.md", candidate / "x.tests", candidate / "tools"]
        if all(path.exists() for path in marker_files[:2]) and (candidate / "tools").exists():
            return candidate
        if (candidate / "README.md").exists() and (candidate / "tools").exists():
            return candidate

    raise PrototypeResolutionError(
        "No se pudo localizar la raíz del repositorio. Define MINI_GPU_ROOT o usa un lanzador dentro del repo."
    )


def _prototype_sort_key(path: Path) -> tuple[int, str]:
    number = re.match(r"(\d+)", path.name)
    return (int(number.group(1)) if number else 0, path.name)


def list_prototypes(root: Path) -> list[Path]:
    """Lista prototipos top-level del repositorio, en orden numérico (1, 2, ..., 10, 11)."""
    return sorted(
        [path for path in root.iterdir() if path.is_dir() and path.name[0].isdigit() and "." in path.name],
        key=_prototype_sort_key,
    )


def resolve_prototype(value: str, root: Path | None = None) -> Path:
    """Resuelve un nombre/numero/ruta relativo/absoluto de un prototipo."""
    repo_root = find_repo_root(root if root is not None else Path.cwd()) if root is None else root.resolve()
    if not root and not repo_root.exists():
        raise PrototypeResolutionError(f"Raíz del repositorio no encontrada: {repo_root}")

    candidate = Path(value)
    if candidate.exists():
        return candidate.resolve()

    if value.startswith("./") or value.startswith("../"):
        resolved = (repo_root / candidate).resolve()
        if resolved.exists():
            return resolved

    if not value.strip():
        raise PrototypeResolutionError("El prototipo no puede estar vacío")

    complete_name = value.strip()
    if (repo_root / complete_name).exists():
        return (repo_root / complete_name).resolve()

    if value.isdigit():
        matches = sorted(
            [path for path in repo_root.iterdir() if path.is_dir() and path.name.startswith(f"{value}.")],
            key=lambda p: p.name,
        )
        if not matches:
            available = ", ".join(sorted(p.name for p in repo_root.iterdir() if p.is_dir() and p.name[:1].isdigit())) or "ninguno"
            raise PrototypeResolutionError(
                f"No existe ningún prototipo para '{value}'. Disponibles: {available}"
            )
        if len(matches) > 1:
            names = ", ".join(path.name for path in matches)
            raise PrototypeResolutionError(
                f"El número '{value}' es ambiguo: {names}. Usa el nombre completo del prototipo."
            )
        return matches[0].resolve()

    matches = sorted(
        [path for path in repo_root.iterdir() if path.is_dir() and path.name.startswith(f"{value}")],
        key=lambda p: p.name,
    )
    if matches:
        if len(matches) > 1:
            names = ", ".join(path.name for path in matches)
            raise PrototypeResolutionError(
                f"El identificador '{value}' es ambiguo: {names}. Usa el nombre completo del prototipo."
            )
        return matches[0].resolve()

    raise PrototypeResolutionError(
        f"No se encontró el prototipo '{value}'. Disponibles: {', '.join(sorted(p.name for p in repo_root.iterdir() if p.is_dir() and p.name[:1].isdigit())) or 'ninguno'}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Resuelve un prototipo del repositorio.")
    parser.add_argument("prototype", nargs="?", help="Número, nombre o ruta del prototipo")
    parser.add_argument("--root", type=Path, default=None, help="Raíz del repositorio (opcional)")
    args = parser.parse_args()
    if not args.prototype:
        parser.error("falta el prototipo")
    try:
        path = resolve_prototype(args.prototype, args.root)
    except PrototypeResolutionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
