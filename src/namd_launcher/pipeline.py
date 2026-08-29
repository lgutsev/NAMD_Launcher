"""Campaign-level plan: the ordered stage DAG and where each stage writes.

``inamd plan`` prints this; ``inamd run`` (added later) walks it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import __version__
from ._compat import compat_sources
from ._stage import read_audit
from .config import Campaign, load_profile

# (stage key, output subdirectory, one-line description, upstream stage)
STAGES: tuple[tuple[str, str, str, str | None], ...] = (
    ("snapshots", "snapshots", "Slice the AIMD trajectory into 001..NSW WAVECAR folders", None),
    ("waverun", "snapshots", "Run one WAVECAR/eigenvalue SCF per snapshot", "snapshots"),
    ("ksplot", "snapshots", "Plot KS energies vs time and band-gap statistics", "waverun"),
    ("nac", "nac", "CA-NAC non-adiabatic couplings + eigenvalues", "waverun"),
    ("dephase", "nac", "energy.dat -> DEPHTIME (pure-dephasing matrix) + sanity check", "nac"),
    ("inicon", "nac", "Generate INICON initial conditions", "nac"),
    ("hefei", "namd", "Render `inp` and launch Hefei-NAMD surface hopping", "nac"),
    ("shprop", "namd", "Average SHPROP.* and fit exp(-t/A) -> tau", "hefei"),
)


def build_plan(campaign: Campaign) -> dict[str, Any]:
    """Deterministic, serialisable campaign plan."""

    profile = load_profile(campaign.profile_path)
    stages = []
    for key, subdir, description, upstream in STAGES:
        directory = campaign.root / subdir
        audit = read_audit(directory, key)
        stages.append(
            {
                "stage": key,
                "directory": str(directory),
                "description": description,
                "depends_on": upstream,
                "status": (audit or {}).get("status", "PENDING"),
            }
        )
    return {
        "schema_version": 1,
        "namdforge_version": __version__,
        "project": campaign.name,
        "campaign_file": str(campaign.path),
        "profile": str(campaign.profile_path),
        "scheduler": profile["scheduler"],
        "jobs": sorted(profile["jobs"]),
        "compat": compat_sources(),
        "source": campaign.source,
        "nac_engine": campaign.nac["engine"],
        "namd_branch": campaign.namd["branch"],
        "namd_algo": campaign.namd["algo"],
        "stages": stages,
    }


def scaffold_layout(root: Path) -> list[str]:
    """Directories a campaign uses; created by ``inamd init``/``prepare``."""

    created = []
    for name in ("profiles", "snapshots", "nac", "namd", "logs"):
        path = root / name
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(name)
    return created
