"""POTCAR assembly, launcher resolution, and job submission.

Vendored subset of ``interfaceforge.vasp`` used when InterfaceForge is not
importable. Behaviour matches InterfaceForge except that the environment
variable ``NAMDFORGE_POTCAR_ROOT`` is also honoured and the built-in POTCAR
mapping ships inside ``namd_launcher``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Iterable, Mapping
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from ..errors import SafetyError
from .incar import parse_incar  # noqa: F401  (re-exported for _compat)

__all__ = [
    "parse_incar",
    "assemble_potcar",
    "resolve_potcar_root",
    "ensure_run_potcar",
    "resolve_launcher",
    "submit_run",
    "require_files",
    "poscar_elements",
    "poscar_ion_count",
]


def require_files(folder: Path, names: Iterable[str]) -> None:
    missing = [name for name in names if not (folder / name).is_file()]
    if missing:
        raise SafetyError(f"{folder} is missing required file(s): {', '.join(missing)}")


def poscar_elements(poscar: Path) -> list[str]:
    """Read VASP 5+ species, with the legacy first-line convention as fallback."""

    lines = poscar.read_text(encoding="utf-8", errors="ignore").splitlines()
    if len(lines) < 7:
        raise SafetyError(f"POSCAR is too short: {poscar}")
    symbols = lines[5].split()
    if symbols and all(re.fullmatch(r"\d+", token) for token in symbols):
        counts = symbols
        symbols = lines[0].split()
    else:
        counts = lines[6].split()
    if not symbols or any(not re.fullmatch(r"[A-Z][a-z]?", token) for token in symbols):
        raise SafetyError(
            "POSCAR contains neither a valid VASP 5+ species line nor a legacy "
            "first-line element list"
        )
    if len(counts) != len(symbols) or not all(re.fullmatch(r"\d+", token) for token in counts):
        raise SafetyError(f"POSCAR element and count lines are inconsistent: {poscar}")
    return symbols


def poscar_ion_count(poscar: Path) -> int:
    lines = poscar.read_text(encoding="utf-8", errors="ignore").splitlines()
    if len(lines) < 7:
        raise SafetyError(f"POSCAR is too short: {poscar}")
    counts = lines[5].split()
    if not all(re.fullmatch(r"\d+", token) for token in counts):
        counts = lines[6].split()
    if not counts or not all(re.fullmatch(r"\d+", token) for token in counts):
        raise SafetyError(f"POSCAR has no valid ion-count line: {poscar}")
    return sum(int(token) for token in counts)


def assemble_potcar(
    poscar: str | Path,
    output: str | Path,
    *,
    pseudopotential_root: str | Path,
    mapping_file: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Assemble POTCAR from an explicit licensed local pseudopotential tree."""

    poscar_path = Path(poscar).resolve()
    output_path = Path(output).resolve()
    root = Path(pseudopotential_root).expanduser().resolve()
    if output_path.exists() and not force:
        raise SafetyError(f"Refusing to overwrite existing POTCAR: {output_path}")
    if mapping_file is None:
        mapping_label = "built-in POTCAR mapping"
        mapping_text = (
            resources.files("namd_launcher").joinpath("templates/potcar_pbe_54.yaml").read_text(encoding="utf-8")
        )
    else:
        mapping_path = Path(mapping_file).resolve()
        mapping_label = str(mapping_path)
        mapping_text = mapping_path.read_text(encoding="utf-8")
    mapping = yaml.safe_load(mapping_text)
    if not isinstance(mapping, Mapping):
        raise SafetyError(f"Invalid POTCAR map: {mapping_label}")
    elements = poscar_elements(poscar_path)
    source_files: list[Path] = []
    variants: list[str] = []
    for element in elements:
        variant = str(mapping.get(element, "")).strip()
        if not variant:
            raise SafetyError(f"No POTCAR mapping for element {element}")
        source = root / variant / "POTCAR"
        if not source.is_file() or not source.stat().st_size:
            raise SafetyError(f"Missing licensed POTCAR source: {source}")
        source_files.append(source)
        variants.append(variant)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".tmp")
    with temporary.open("wb") as destination:
        for source in source_files:
            with source.open("rb") as handle:
                shutil.copyfileobj(handle, destination)
    temporary.replace(output_path)
    return {
        "output": str(output_path),
        "elements": elements,
        "variants": variants,
        "sources": [str(path) for path in source_files],
        "mapping": mapping_label,
    }


def resolve_potcar_root(explicit: str | Path | None = None) -> Path:
    """Find the licensed local PBE PAW tree without bundling POTCAR data."""

    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit).expanduser())
    for env_name in ("NAMDFORGE_POTCAR_ROOT", "IFACE_POTCAR_ROOT"):
        if value := os.environ.get(env_name):
            candidates.append(Path(value).expanduser())
    if value := os.environ.get("VASP_PP_PATH"):
        base = Path(value).expanduser()
        candidates.extend((base / "potpaw_PBE", base))
    candidates.append(Path.home() / "pot" / "potpaw_PBE")
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_dir():
            return resolved
    searched = ", ".join(str(path) for path in candidates)
    raise SafetyError(
        "POTCAR is missing and no licensed PBE PAW tree was found. "
        "Pass --potcar-root, set NAMDFORGE_POTCAR_ROOT, or set VASP_PP_PATH. "
        f"Searched: {searched}"
    )


def ensure_run_potcar(
    folder: str | Path,
    *,
    pseudopotential_root: str | Path | None = None,
    mapping_file: str | Path | None = None,
) -> dict[str, Any]:
    """Generate a missing/empty run POTCAR from POSCAR before submission."""

    run = Path(folder).resolve()
    output = run / "POTCAR"
    if output.is_file() and output.stat().st_size:
        return {"status": "existing", "output": str(output)}
    require_files(run, ("POSCAR",))
    root = resolve_potcar_root(pseudopotential_root)
    payload = assemble_potcar(
        run / "POSCAR",
        output,
        pseudopotential_root=root,
        mapping_file=mapping_file,
        force=output.exists(),
    )
    payload["status"] = "generated"
    return payload


def resolve_launcher(folder: str | Path, launcher: str | None = None) -> Path:
    """Resolve an explicit launcher or prefer the standalone VASP launcher."""

    run = Path(folder).resolve()
    if launcher:
        script = run / launcher
        if not script.is_file():
            raise FileNotFoundError(script)
        return script
    for name in ("runvasp.sh", "run.slurm"):
        script = run / name
        if script.is_file():
            return script
    raise FileNotFoundError(f"No launcher found in {run}; expected runvasp.sh or run.slurm")


def submit_run(
    folder: str | Path,
    launcher: str | None = None,
    *,
    potcar_root: str | Path | None = None,
    potcar_mapping: str | Path | None = None,
) -> str:
    """Submit one prepared run and return the scheduler job id."""

    run = Path(folder).resolve()
    ensure_run_potcar(run, pseudopotential_root=potcar_root, mapping_file=potcar_mapping)
    script = resolve_launcher(run, launcher)
    result = subprocess.run(
        ["sbatch", script.name],
        cwd=run,
        check=True,
        capture_output=True,
        text=True,
    )
    match = re.search(r"Submitted batch job\s+(\d+)", result.stdout)
    return match.group(1) if match else result.stdout.strip()
