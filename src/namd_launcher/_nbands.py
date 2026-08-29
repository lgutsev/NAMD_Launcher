"""Choose NBANDS for the snapshot SCF from the reference MD calculation.

The snapshot WAVECAR SCF must carry at least as many bands as CA-NAC's widest
stored window (``nac.bmax_stored``), and it is cleanest to reproduce the band
count the *reference* AIMD run actually used -- that is why the reference
workflow's hand-written INCAR carried ``NBANDS = 960`` for a 3x3x3 FAPI slab.

This module reads that number back (OUTCAR header, then INCAR), compares it to
the NAMD requirement, and picks a value -- explaining every choice.
"""

from __future__ import annotations

import gzip
import re
from pathlib import Path
from typing import Any

from ._compat import parse_incar

# "   number of bands    NBANDS= 960"  /  "NBANDS =    960"  /  "NBANDS= 960 "
_OUTCAR_NBANDS = re.compile(r"NBANDS\s*=\s*(\d+)")


def reference_nbands(reference_dir: Path | None) -> tuple[int | None, str]:
    """(nbands, source-description). Prefers the executed value in OUTCAR."""

    if reference_dir is None or not reference_dir.is_dir():
        return None, "no reference directory"

    for name in ("OUTCAR", "OUTCAR.gz"):
        outcar = reference_dir / name
        if not outcar.is_file():
            continue
        try:
            opener = gzip.open if name.endswith(".gz") else open
            with opener(outcar, "rt", encoding="utf-8", errors="ignore") as handle:  # type: ignore[operator]
                head = handle.read(200_000)
        except OSError:
            continue
        match = _OUTCAR_NBANDS.search(head)
        if match:
            return int(match.group(1)), f"{name} (executed value)"

    incar = reference_dir / "INCAR"
    if incar.is_file():
        value = parse_incar(incar).get("NBANDS")
        if value and value.split()[0].isdigit():
            return int(value.split()[0]), "reference INCAR NBANDS"
        return None, "reference INCAR has no explicit NBANDS (VASP auto-chose it)"

    return None, "no OUTCAR or INCAR in the reference directory"


def _round_up(value: int, multiple: int) -> int:
    if multiple <= 1:
        return value
    return -(-value // multiple) * multiple


def choose_nbands(
    campaign_bands: dict[str, Any],
    campaign_nac: dict[str, Any],
    *,
    ref_nbands: int | None,
    ref_source: str,
) -> dict[str, Any]:
    """Decide the snapshot INCAR's NBANDS and record why.

    Precedence:
      1. explicit ``bands.nbands``          -> use it (warn if below ref / requirement)
      2. reference run's NBANDS             -> use it (raise to the requirement if short)
      3. ``bmax_stored`` + ``nbands_margin`` -> compute a floor
      4. nothing usable                     -> leave unset, let VASP auto-choose (warn)
    """

    explicit = campaign_bands.get("nbands")
    margin = int(campaign_bands.get("nbands_margin", 64))
    round_to = int(campaign_bands.get("nbands_round", 8))

    stored = (
        campaign_nac.get("bmax_stored")
        or campaign_nac.get("bmax")
        or campaign_bands.get("cbm")
    )
    requirement = int(stored) + margin if stored else None

    notes: list[str] = []
    if explicit:
        chosen: int | None = int(explicit)
        reason = "explicit bands.nbands"
        if ref_nbands and chosen < ref_nbands:
            notes.append(
                f"bands.nbands={chosen} is below the reference run's NBANDS={ref_nbands} "
                f"({ref_source}); the snapshot electronic structure will differ from the MD run"
            )
        if requirement and chosen < requirement:
            notes.append(
                f"bands.nbands={chosen} < bmax_stored+margin ({requirement}); "
                f"CA-NAC's stored window (up to band {stored}) may not fit"
            )
    elif ref_nbands:
        chosen = ref_nbands
        reason = f"matched the reference run ({ref_source})"
        if requirement and chosen < requirement:
            raised = _round_up(requirement, round_to)
            notes.append(
                f"reference NBANDS={ref_nbands} < bmax_stored+margin ({requirement}); "
                f"raised to {raised}"
            )
            chosen = raised
            reason = f"reference run ({ref_source}), raised to bmax_stored+margin"
    elif requirement:
        chosen = _round_up(requirement, round_to)
        reason = "bmax_stored + nbands_margin (no reference NBANDS found)"
        notes.append(
            f"could not read NBANDS from the reference run ({ref_source}); "
            f"using {chosen}. Set bands.nbands explicitly for a production run."
        )
    else:
        chosen = None
        reason = "unset -- VASP will auto-choose"
        notes.append(
            "no reference NBANDS and no bmax_stored/cbm to size from; VASP's automatic "
            "NBANDS is usually too small for NAMD. Set bands.nbands or nac.bmax_stored."
        )

    return {
        "nbands": chosen,
        "reason": reason,
        "reference_nbands": ref_nbands,
        "reference_source": ref_source,
        "requirement": requirement,
        "requirement_basis": (
            f"bmax_stored({campaign_nac.get('bmax_stored')}) + margin({margin})"
            if campaign_nac.get("bmax_stored")
            else f"~band {stored} + margin({margin})"
            if stored
            else None
        ),
        "notes": notes,
    }
