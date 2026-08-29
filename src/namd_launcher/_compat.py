"""Shared helpers, sourced from InterfaceForge when it is installed.

NAMD Launcher is deliberately convention-compatible with InterfaceForge. When
the ``interfaceforge`` package is importable we use its exact implementations
(so scheduler scripts, INCAR edits and POTCAR assembly are identical across the
two tools); otherwise we fall back to the faithful copies in
``namd_launcher._vendor``.

``USING_INTERFACEFORGE`` records which path was taken (surfaced by
``inamd plan`` / ``inamd audit`` for provenance).
"""

from __future__ import annotations

USING_INTERFACEFORGE = False

try:  # pragma: no cover - exercised by installing interfaceforge
    from interfaceforge.scheduler import render_job, sanitize_job_name, write_job

    _sched_source = "interfaceforge"
    USING_INTERFACEFORGE = True
except ImportError:  # pragma: no cover - default in this repo's CI
    from ._vendor.scheduler import render_job, sanitize_job_name, write_job

    _sched_source = "namd_launcher._vendor"

try:  # pragma: no cover
    from interfaceforge.vasp import parse_incar, update_incar

    _incar_source = "interfaceforge"
    USING_INTERFACEFORGE = True
except ImportError:
    from ._vendor.incar import parse_incar, update_incar

    _incar_source = "namd_launcher._vendor"

try:  # pragma: no cover
    from interfaceforge.vasp import (
        assemble_potcar,
        ensure_run_potcar,
        resolve_launcher,
        resolve_potcar_root,
        submit_run,
    )

    _vasp_source = "interfaceforge"
    USING_INTERFACEFORGE = True
except ImportError:
    from ._vendor.vasp_helpers import (
        assemble_potcar,
        ensure_run_potcar,
        resolve_launcher,
        resolve_potcar_root,
        submit_run,
    )

    _vasp_source = "namd_launcher._vendor"


def compat_sources() -> dict[str, str]:
    """Where each shared helper group was imported from."""

    return {
        "scheduler": _sched_source,
        "incar": _incar_source,
        "vasp_helpers": _vasp_source,
        "using_interfaceforge": USING_INTERFACEFORGE,
    }


__all__ = [
    "USING_INTERFACEFORGE",
    "assemble_potcar",
    "compat_sources",
    "ensure_run_potcar",
    "parse_incar",
    "render_job",
    "resolve_launcher",
    "resolve_potcar_root",
    "sanitize_job_name",
    "submit_run",
    "update_incar",
    "write_job",
]
