"""Resolve the external scientific codes -- they are installed, never vendored.

NAMD Launcher ships **none** of CA-NAC, VaspBandUnfolding, or the Hefei-NAMD
engine (see ``third_party/README.md``). Each is resolved from, in order:

1. an explicit campaign key (``nac.canac_dir``, ``nac.vaspwfc_dir``, ``namd.binary_dir``);
2. an environment variable (``NAMDFORGE_CANAC_DIR``, ``NAMDFORGE_VASPWFC_DIR``, ``PATH``);
3. the ``third_party/_src/<name>`` checkout that ``third_party/fetch.sh`` makes;
4. (for importable packages) the active Python environment.

Resolution is best effort: ``prepare`` records what it found and WARNs;
``run`` / ``launch`` is where a missing dependency becomes an error.
"""

from __future__ import annotations

import os
import shutil
from importlib.util import find_spec
from pathlib import Path
from typing import Any

_REPO_SRC = Path(__file__).resolve().parents[2] / "third_party" / "_src"


def _dir_with(value: str | None, marker: str, label: str) -> dict[str, Any] | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if path.is_dir() and (path / marker).is_file():
        return {"path": str(path.resolve()), "found": True, "how": label}
    return None


def resolve_canac(nac: dict[str, Any]) -> dict[str, Any]:
    """Directory containing ``CAnac.py`` (Chu & Prezhdo's CA-NAC checkout)."""

    for value, label in (
        (nac.get("canac_dir"), "nac.canac_dir"),
        (os.environ.get("NAMDFORGE_CANAC_DIR"), "$NAMDFORGE_CANAC_DIR"),
        (str(_REPO_SRC / "CA-NAC"), "third_party/_src checkout"),
    ):
        hit = _dir_with(value, "CAnac.py", label)
        if hit:
            return {"name": "CA-NAC", **hit}
    if find_spec("CAnac") is not None:
        return {"name": "CA-NAC", "path": None, "found": True, "how": "importable (on PYTHONPATH)"}
    return {
        "name": "CA-NAC",
        "path": None,
        "found": False,
        "how": "not found",
        "hint": "clone it (bash third_party/fetch.sh), set nac.canac_dir or $NAMDFORGE_CANAC_DIR, "
        "or make it importable in the `canac` job. https://github.com/WeibinChu/CA-NAC",
    }


def resolve_vaspwfc(nac: dict[str, Any]) -> dict[str, Any]:
    """Directory (or install) providing ``vaspwfc`` / ``paw`` / ``spinorb``."""

    for value, label in (
        (nac.get("vaspwfc_dir"), "nac.vaspwfc_dir"),
        (os.environ.get("NAMDFORGE_VASPWFC_DIR"), "$NAMDFORGE_VASPWFC_DIR"),
        (os.environ.get("VBU_DIR"), "$VBU_DIR"),
        (str(_REPO_SRC / "VaspBandUnfolding"), "third_party/_src checkout"),
    ):
        hit = _dir_with(value, "vaspwfc.py", label)
        if hit:
            return {"name": "VaspBandUnfolding", **hit}
    if find_spec("vaspwfc") is not None:
        return {"name": "VaspBandUnfolding", "path": None, "found": True, "how": "importable"}
    return {
        "name": "VaspBandUnfolding",
        "path": None,
        "found": False,
        "how": "not found",
        "hint": "bash third_party/fetch.sh, or set nac.vaspwfc_dir / $NAMDFORGE_VASPWFC_DIR. "
        "https://github.com/QijingZheng/VaspBandUnfolding",
    }


def resolve_hefei_binary(binary: str, namd: dict[str, Any]) -> dict[str, Any]:
    """Locate the Hefei-NAMD executable (``hfnamd`` / ``dish`` / ``namd``)."""

    explicit = namd.get("binary_dir")
    if explicit:
        candidate = Path(explicit).expanduser() / binary
        if candidate.is_file():
            return {"name": binary, "path": str(candidate.resolve()), "found": True, "how": "namd.binary_dir"}
    for sub in ("dish", "namd", "namdK"):
        candidate = _REPO_SRC / "Hefei-NAMD" / "src" / sub / binary
        if candidate.is_file():
            return {"name": binary, "path": str(candidate.resolve()), "found": True, "how": "third_party/_src build"}
    which = shutil.which(binary)
    if which:
        return {"name": binary, "path": which, "found": True, "how": "PATH"}
    return {
        "name": binary,
        "path": None,
        "found": False,
        "how": "not found",
        "hint": f"build it (bash third_party/fetch.sh; make in src/dish|src/namd), put {binary} on PATH, "
        "or set namd.binary_dir / point the hefei_namd job's command at its full path.",
    }


def pythonpath_prefix(*deps: dict[str, Any]) -> list[str]:
    """The resolved directories, for prepending to PYTHONPATH in a job script."""

    return [d["path"] for d in deps if d.get("path")]
