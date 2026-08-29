"""INCAR read/update helpers.

Vendored copies of ``interfaceforge.vasp.parse_incar`` and
``interfaceforge.vasp.update_incar`` (byte-for-byte behaviour) for the rare
case where InterfaceForge is not installed next to namdforge.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

_INCAR_LINE = re.compile(r"^(\s*)([A-Za-z][A-Za-z0-9_]*)(\s*=\s*)(.*?)(\r?\n)?$")


def parse_incar(path: str | Path) -> dict[str, str]:
    """Parse the last active value of each INCAR tag (upper-cased keys)."""

    parsed: dict[str, str] = {}
    incar = Path(path)
    if not incar.is_file():
        return parsed
    for raw in incar.read_text(encoding="utf-8", errors="ignore").splitlines():
        active = re.split(r"[!#]", raw, maxsplit=1)[0]
        match = re.match(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", active)
        if match:
            parsed[match.group(1).upper()] = match.group(2).strip()
    return parsed


def update_incar(
    path: str | Path,
    changes: Mapping[str, Any],
    *,
    delete: Iterable[str] = (),
    create: bool = False,
) -> Path:
    """Update tags while preserving unrelated comments and ordering."""

    incar = Path(path)
    if not incar.exists() and not create:
        raise FileNotFoundError(incar)
    original = incar.read_text(encoding="utf-8", errors="ignore") if incar.exists() else ""
    normalized = {str(key).upper(): str(value) for key, value in changes.items()}
    deleted = {str(key).upper() for key in delete}
    found: set[str] = set()
    output: list[str] = []

    for line in original.splitlines(keepends=True):
        match = _INCAR_LINE.match(line)
        if not match:
            output.append(line)
            continue
        key = match.group(2).upper()
        if key in deleted:
            continue
        if key in normalized:
            ending = match.group(5) or "\n"
            output.append(f"{match.group(1)}{key}{match.group(3)}{normalized[key]}{ending}")
            found.add(key)
        else:
            output.append(line)

    missing = [key for key in normalized if key not in found]
    if missing:
        if output and not output[-1].endswith("\n"):
            output[-1] += "\n"
        if output and output[-1].strip():
            output.append("\n")
        output.extend(f"{key} = {normalized[key]}\n" for key in missing)

    temporary = incar.with_suffix(incar.suffix + ".tmp")
    temporary.write_text("".join(output), encoding="utf-8")
    temporary.replace(incar)
    return incar
