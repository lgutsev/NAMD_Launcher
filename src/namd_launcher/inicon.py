"""Stage 5b -- INICON initial conditions for Hefei-NAMD.

Port of ``INICON_gen.sh``: NSAMPLE rows of ``<start_step> <start_band>`` with
the start step drawn uniformly from ``[1, tmax]`` and the start band from
``[band_min, band_max]``. Deterministic given ``inicon.seed``.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Any

from ._stage import write_audit, write_manifest
from .cli import _json, register
from .config import Campaign, load_campaign
from .errors import SafetyError
from .state import StateStore

STAGE = "inicon"


def _nac_frames(nac_root: Path) -> int | None:
    natxt = nac_root / "NATXT"
    if natxt.is_file() and natxt.stat().st_size:
        return sum(1 for line in natxt.open() if line.strip())
    return None


def generate_inicon(campaign: Campaign, *, force: bool = False) -> dict[str, Any]:
    cfg = campaign.inicon
    for key in ("nsample", "tmax", "band_min", "band_max"):
        if cfg.get(key) is None:
            raise SafetyError(f"campaign inicon: block needs {key}")
    nsample = int(cfg["nsample"])
    tmax = int(cfg["tmax"])
    b_lo, b_hi = int(cfg["band_min"]), int(cfg["band_max"])
    seed = int(cfg.get("seed", 0))
    if tmax < 1 or nsample < 1:
        raise SafetyError("inicon.tmax and inicon.nsample must be positive")

    nac_root = campaign.stage_dir("nac")
    nac_root.mkdir(parents=True, exist_ok=True)
    target = nac_root / "INICON"
    if target.exists() and not force:
        raise SafetyError(f"{target} already exists; re-run with --force.")

    rng = random.Random(seed)
    rows = [(rng.randint(1, tmax), rng.randint(b_lo, b_hi)) for _ in range(nsample)]
    target.write_text("".join(f"{t} {b}\n" for t, b in rows), encoding="utf-8")

    notes: list[str] = []
    status = "PASS"
    frames = _nac_frames(nac_root)
    namdtime = campaign.namd.get("namdtime")
    if frames is not None:
        if tmax > frames:
            status = "WARN"
            notes.append(f"inicon.tmax={tmax} exceeds the {frames} NAC frames available")
        if campaign.namd["algo"] == "FSSH" and namdtime and tmax + int(namdtime) - 1 > frames:
            status = "WARN"
            notes.append(
                f"FSSH: start step up to {tmax} + NAMDTIME {namdtime} can exceed {frames} frames "
                "(fine for DISH's replicated NAC, risky for FSSH)"
            )
    bands = campaign.bands
    if bands.get("cbm") is not None and not (b_lo <= bands["cbm"] <= b_hi or b_lo >= bands["cbm"]):
        notes.append(f"initial band window [{b_lo}, {b_hi}] does not include the CBM ({bands['cbm']})")

    payload = {
        "stage": STAGE,
        "inicon": str(target),
        "nsample": nsample,
        "tmax": tmax,
        "band_range": [b_lo, b_hi],
        "seed": seed,
        "nac_frames": frames,
        "first_rows": rows[: min(5, len(rows))],
    }
    manifest = write_manifest(nac_root, STAGE, payload)
    audit = {"status": status, "summary": "; ".join(notes) or "INICON generated", **payload}
    write_audit(nac_root, STAGE, audit)
    state = StateStore(campaign.root)
    state.event("inicon", nsample=nsample, seed=seed, status=status)
    state.artifact("INICON", target)
    return {"mode": "written", "status": status, "notes": notes, **payload, "manifest": str(manifest)}


def audit_inicon(campaign: Campaign) -> dict[str, Any]:
    nac_root = campaign.stage_dir("nac")
    path = nac_root / f"{STAGE}_audit.json"
    if path.is_file():
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    audit = {"status": "PENDING", "summary": "INICON not generated yet", "root": str(nac_root)}
    write_audit(nac_root, STAGE, audit)
    return audit


def _cmd(args: argparse.Namespace) -> int:
    campaign = load_campaign(args.campaign)
    if getattr(args, "inicon_audit", False):
        _json(audit_inicon(campaign))
        return 0
    _json(generate_inicon(campaign, force=args.force))
    return 0


@register
def _register(commands: Any, add_campaign_option: Any) -> None:
    parser = commands.add_parser(STAGE, help="Generate INICON initial conditions")
    add_campaign_option(parser)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--audit", dest="inicon_audit", action="store_true")
    parser.set_defaults(func=_cmd)
