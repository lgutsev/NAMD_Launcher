"""Step 3 (experimental) -- N2AMD: a deep-Hamiltonian shortcut for the NAC stage.

N2AMD (Zhang et al., Nat. Commun. 2025 / arXiv:2408.06654) trains an
E(3)-equivariant deep Hamiltonian (HamGNN) on DFT Hamiltonians, then predicts
H(t) along an AIMD trajectory, diagonalises it for eigenvalues, and computes
NACs -- feeding Hefei-NAMD through the classical-path approximation exactly
like CA-NAC does. In this launcher it would **replace stages `waverun` + `nac`**:
same Step2 `XDATCAR` in, ``EIGTXT`` / ``NATXT`` out for the unchanged `hefei`
stage.

Nothing here trains or runs a model. ``status`` probes dependencies, ``plan``
prints the workflow, and ``export`` writes a frame manifest + a training-data
checklist so the real work can be scoped. See ``docs/n2amd.md``.
"""

from __future__ import annotations

import argparse
import json
from importlib.util import find_spec
from typing import Any

from .cli import _json, register
from .config import Campaign, load_campaign
from .errors import SafetyError
from .snapshots import resolve_source
from .state import StateStore

STAGE = "n2amd"

WORKFLOW = [
    {
        "step": 1,
        "name": "training set",
        "detail": "500-2000 small-supercell DFT Hamiltonians (ideally HSE06) for the target chemistry. "
        "VASP does not emit an LCAO Hamiltonian: generate with openmx / ABACUS / HONPAS, or the "
        "N2AMD-provided pipeline. This is the main cost and the main integration gap.",
        "artifact": "n2amd/train/*.h5 (HamGNN format)",
    },
    {
        "step": 2,
        "name": "train HamGNN",
        "detail": "E(3)-equivariant deep Hamiltonian. github.com/QuantumLab-ZY/HamGNN. GPU.",
        "artifact": "n2amd/model/hamgnn.ckpt",
    },
    {
        "step": 3,
        "name": "predict H(t)",
        "detail": "Apply the model to every frame of the Step2 XDATCAR (larger cells / longer "
        "trajectories than the training supercell are the point).",
        "artifact": "n2amd/pred/H_*.npy",
    },
    {
        "step": 4,
        "name": "eigen-decompose + NAC",
        "detail": "Diagonalise H(t); finite-difference wavefunction overlaps -> NAC. "
        "N2AMD codes (Figshare) do this and interface to Hefei-NAMD.",
        "artifact": "nac/EIGTXT, nac/NATXT (same names the `hefei` stage consumes)",
    },
    {
        "step": 5,
        "name": "hand off",
        "detail": "Run `inamd dephase` / `inamd inicon` / `inamd hefei` on the generated "
        "EIGTXT/NATXT exactly as for the CA-NAC path.",
        "artifact": "SHPROP.* -> `inamd shprop`",
    },
]


def status() -> dict[str, Any]:
    probes = {name: find_spec(name) is not None for name in ("torch", "e3nn", "pytorch_lightning", "HamGNN")}
    return {
        "stage": STAGE,
        "implemented": False,
        "note": "EXPERIMENTAL scaffold. N2AMD is not wired into the pipeline yet; see docs/n2amd.md.",
        "dependencies_present": probes,
        "references": {
            "paper": "Zhang et al., Nat. Commun. 16 (2025); arXiv:2408.06654",
            "hamgnn": "https://github.com/QuantumLab-ZY/HamGNN",
            "n2amd_code": "Figshare (linked from the paper)",
        },
        "replaces_stages": ["waverun", "nac"],
    }


def plan(campaign: Campaign | None) -> dict[str, Any]:
    payload = {"stage": STAGE, "implemented": False, "workflow": WORKFLOW}
    if campaign is not None:
        payload["source_trajectory"] = campaign.source["trajectory"]
        payload["band_window"] = {k: campaign.bands.get(k) for k in ("vbm", "cbm", "nbands")}
        payload["namd_algo"] = campaign.namd["algo"]
    return payload


def export(campaign: Campaign, *, force: bool = False) -> dict[str, Any]:
    from ._xdatcar import read_xdatcar

    src = resolve_source(campaign)
    traj = read_xdatcar(src["xdatcar"])
    out_root = campaign.stage_dir(STAGE)
    out_root.mkdir(parents=True, exist_ok=True)

    manifest_path = out_root / "frames_manifest.json"
    checklist_path = out_root / "TRAINING_CHECKLIST.md"
    for path in (manifest_path, checklist_path):
        if path.exists() and not force:
            raise SafetyError(f"{path} already exists; re-run with --force.")

    nsw = int(campaign.snapshots["nsw"])
    manifest = {
        "format": "namdforge-n2amd-frames",
        "schema_version": 1,
        "implemented": False,
        "source": src["label"],
        "trajectory_frames": len(traj),
        "n_ions": traj.n_ions,
        "species": traj.species,
        "counts": traj.counts,
        "frames_for_namd": {"count": nsw, "indices": [len(traj) - nsw, len(traj) - 1]},
        "band_window": {k: campaign.bands.get(k) for k in ("vbm", "cbm", "nbands")},
        "workflow": WORKFLOW,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    bands = campaign.bands
    window = f"VBM {bands.get('vbm')}, CBM {bands.get('cbm')}, NBANDS {bands.get('nbands')}"
    checklist = f"""# N2AMD training-data checklist for {campaign.name}

> EXPERIMENTAL. This checklist scopes the work; nothing is trained or run here.

## Target
- chemistry / structure: {src['label']}
- NAMD band window: {window}
- trajectory frames available: {len(traj)} (use last {nsw} for NAMD)

## To collect
- [ ] 500-2000 DFT Hamiltonians on a small supercell of this chemistry
      (openmx / ABACUS / HONPAS -- VASP cannot export the LCAO H).
- [ ] functional decision: PBE (cheap, matches current CA-NAC path) vs HSE06
      (the reason to use N2AMD; ~10-50x costlier per reference).
- [ ] sampling: decorrelated frames from a short AIMD at the target T, plus
      strained / defected configs for transferability.
- [ ] hold-out set for eigenvalue + NAC parity vs direct DFT.

## To install
- [ ] HamGNN (https://github.com/QuantumLab-ZY/HamGNN) + torch + e3nn (GPU).
- [ ] N2AMD codes (Figshare, linked from the paper) for the H(t) -> NAC step.

## Hand-off
Once `nac/EIGTXT` and `nac/NATXT` exist, `inamd dephase`, `inamd inicon`,
`inamd hefei` and `inamd shprop` run unchanged.
"""
    checklist_path.write_text(checklist, encoding="utf-8")
    StateStore(campaign.root).event("n2amd.export", frames=len(traj), nsw=nsw)
    return {
        "mode": "exported",
        "implemented": False,
        "manifest": str(manifest_path),
        "checklist": str(checklist_path),
        "trajectory_frames": len(traj),
    }


def _cmd(args: argparse.Namespace) -> int:
    cmd = args.n2amd_command
    if cmd == "status":
        _json(status())
        return 0
    campaign = None
    try:
        campaign = load_campaign(args.campaign)
    except Exception:  # noqa: BLE001 -- status/plan work without a campaign
        if cmd == "export":
            raise
    if cmd == "plan":
        _json(plan(campaign))
        return 0
    _json(export(campaign, force=args.force))
    return 0


@register
def _register(commands: Any, add_campaign_option: Any) -> None:
    parser = commands.add_parser(STAGE, help="(experimental) deep-Hamiltonian NAC shortcut -- feasibility only")
    sub = parser.add_subparsers(dest="n2amd_command", required=True)
    st = sub.add_parser("status", help="Probe dependencies; report implementation state")
    st.set_defaults(func=_cmd)
    pl = sub.add_parser("plan", help="Print the 5-step N2AMD workflow scaffold")
    add_campaign_option(pl)
    pl.set_defaults(func=_cmd)
    ex = sub.add_parser("export", help="Write a frame manifest + training-data checklist")
    add_campaign_option(ex)
    ex.add_argument("--force", action="store_true")
    ex.set_defaults(func=_cmd)
