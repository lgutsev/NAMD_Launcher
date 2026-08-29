"""Stage 3 -- KS manifold diagnostics over the snapshot SCFs.

Two products, both optional sanity checks before committing to NAC:

* ``bandgap_stats.json`` -- mean / std band gap across the snapshot EIGENVALs
  (port of ``bandgap_stats.py``).
* ``ksen.png`` -- KS energy vs time, points coloured/sized by each
  ``bands.groups`` atom group's PROCAR projection (port of
  ``tdksen_hydrogen.py``). Skipped when matplotlib is absent or no PROCARs
  are present.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from ._stage import write_audit, write_manifest
from .cli import _json, register
from .config import Campaign, load_campaign
from .errors import SafetyError
from .state import StateStore

STAGE = "ksplot"


def _snapshot_folders(root: Path, digits: int) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        (p for p in root.iterdir() if p.is_dir() and p.name.isdigit() and len(p.name) == digits),
        key=lambda p: int(p.name),
    )


# --------------------------------------------------------------------------- #
# band gap
# --------------------------------------------------------------------------- #
def _gap_from_eigenval(path: Path) -> float | None:
    vbm = cbm = None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split()
        if len(parts) == 3:
            try:
                energy, occ = float(parts[1]), float(parts[2])
            except ValueError:
                continue
            if occ >= 0.5:
                vbm = energy
            elif vbm is not None and cbm is None:
                cbm = energy
    if vbm is None or cbm is None:
        return None
    return cbm - vbm


def band_gap_stats(campaign: Campaign) -> dict[str, Any]:
    root = campaign.stage_dir("snapshots")
    digits = int(campaign.snapshots["digits"])
    folders = _snapshot_folders(root, digits)
    gaps: list[tuple[str, float | None]] = []
    for folder in folders:
        eigenval = folder / "EIGENVAL"
        gaps.append((folder.name, _gap_from_eigenval(eigenval) if eigenval.is_file() else None))
    valid = [g for _, g in gaps if g is not None]
    return {
        "folders": len(folders),
        "with_eigenval": len(valid),
        "mean_gap_ev": round(float(np.mean(valid)), 4) if valid else None,
        "std_gap_ev": round(float(np.std(valid)), 4) if valid else None,
        "min_gap_ev": round(float(np.min(valid)), 4) if valid else None,
        "max_gap_ev": round(float(np.max(valid)), 4) if valid else None,
        "per_folder": [{"folder": name, "gap_ev": (round(g, 4) if g is not None else None)} for name, g in gaps],
    }


# --------------------------------------------------------------------------- #
# PROCAR projection (port of WeightFromPro / tdksen_hydrogen.py)
# --------------------------------------------------------------------------- #
def weight_from_procar(procar: Path, atom_idx0: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (energies[nspin,nkpts,nbands], weight[nspin,nkpts,nbands]) for the atoms."""

    lines = [ln for ln in procar.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
    nkpts, nbands, nions = (int(x) for x in re.sub("[^0-9]", " ", lines[1]).split())
    weights = np.asarray(
        [ln.split()[-1] for ln in lines if not re.search("[a-zA-Z]", ln)], dtype=float
    )
    nspin = weights.shape[0] // (nkpts * nbands * nions)
    weights = weights.reshape(nspin, nkpts, nbands, nions)
    energies = np.asarray([ln.split()[-4] for ln in lines if "occ." in ln], dtype=float)
    energies = energies.reshape(nspin, nkpts, nbands)
    return energies, np.sum(weights[:, :, :, atom_idx0], axis=-1)


def _group_indices(pairs: list[list[int]]) -> np.ndarray:
    idx: list[int] = []
    for start, stop in pairs:
        idx.extend(range(start - 1, stop))  # 1-based inclusive -> 0-based
    return np.array(sorted(set(idx)), dtype=int)


def ks_energy_plot(campaign: Campaign, *, spin: int = 0, kpt: int = 0, out: Path | None = None) -> dict[str, Any]:
    root = campaign.stage_dir("snapshots")
    digits = int(campaign.snapshots["digits"])
    folders = _snapshot_folders(root, digits)
    procar_folders = [f for f in folders if (f / "PROCAR").is_file()]
    groups = campaign.bands.get("groups", {})
    if not procar_folders:
        return {"status": "skipped", "reason": "no PROCAR files in snapshot folders"}
    if not groups:
        return {"status": "skipped", "reason": "campaign bands.groups is empty"}
    try:
        import matplotlib

        matplotlib.use("agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return {"status": "skipped", "reason": "matplotlib not installed (pip install 'namdforge[report]')"}

    group_idx = {label: _group_indices(pairs) for label, pairs in groups.items()}
    energies: list[np.ndarray] = []
    weights: dict[str, list[np.ndarray]] = {label: [] for label in groups}
    for folder in procar_folders:
        enr = None
        for label, idx in group_idx.items():
            e, w = weight_from_procar(folder / "PROCAR", idx)
            enr = e[spin, kpt, :]
            weights[label].append(w[spin, kpt, :])
        energies.append(enr)
    enr_arr = np.array(energies)
    times = np.arange(enr_arr.shape[0])

    fig, ax = plt.subplots(figsize=(7, 5))
    colors = ["blue", "red", "green", "black", "orange", "purple"]
    for (label, wlist), color in zip(weights.items(), colors, strict=False):
        w = np.array(wlist)
        wmax = w.max() or 1.0
        ax.scatter(
            np.repeat(times[:, None], enr_arr.shape[1], axis=1),
            enr_arr, s=w / wmax * 12.0, color=color, lw=0.0, label=label,
        )
    ax.set_xlabel("snapshot")
    ax.set_ylabel("KS energy (eV)")
    ax.legend(fontsize="small")
    ax.grid(color="lightgray", ls="--", lw=0.5)
    fig.tight_layout()
    out = out or (root / "ksen.png")
    fig.savefig(out, dpi=300)
    plt.close(fig)
    return {"status": "written", "plot": str(out), "procar_folders": len(procar_folders), "groups": list(groups)}


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def run_ksplot(campaign: Campaign, *, no_plot: bool = False, force: bool = False) -> dict[str, Any]:
    root = campaign.stage_dir("snapshots")
    if not (root / "snapshots_manifest.json").is_file():
        raise SafetyError("Run `inamd snapshots prepare` (and `inamd waverun`) first.")

    stats = band_gap_stats(campaign)
    stats_path = root / "bandgap_stats.json"
    if stats_path.exists() and not force:
        raise SafetyError(f"{stats_path} already exists; re-run with --force.")
    stats_path.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")

    plot = {"status": "skipped", "reason": "--no-plot"} if no_plot else ks_energy_plot(campaign)

    payload = {
        "stage": STAGE,
        "bandgap": {k: v for k, v in stats.items() if k != "per_folder"},
        "bandgap_stats_file": str(stats_path),
        "ks_plot": plot,
    }
    manifest = write_manifest(root, STAGE, payload)
    gap = stats["mean_gap_ev"]
    status = "PASS" if gap else "PENDING"
    summary = (
        f"mean band gap {gap} +/- {stats['std_gap_ev']} eV over {stats['with_eigenval']} snapshots"
        if gap
        else "no EIGENVAL files yet -- run `inamd waverun` first"
    )
    audit = {"status": status, "summary": summary, **payload}
    write_audit(root, STAGE, audit)
    state = StateStore(campaign.root)
    state.event("ksplot", mean_gap_ev=gap, ks_plot=plot.get("status"))
    state.artifact("bandgap_stats", stats_path)
    return {"mode": "done", "status": status, "summary": summary, **payload, "manifest": str(manifest)}


def audit_ksplot(campaign: Campaign) -> dict[str, Any]:
    root = campaign.stage_dir("snapshots")
    path = root / f"{STAGE}_audit.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    audit = {"status": "PENDING", "summary": "ksplot not run", "root": str(root)}
    write_audit(root, STAGE, audit)
    return audit


def _cmd(args: argparse.Namespace) -> int:
    campaign = load_campaign(args.campaign)
    if getattr(args, "ksplot_audit", False):
        _json(audit_ksplot(campaign))
        return 0
    _json(run_ksplot(campaign, no_plot=args.no_plot, force=args.force))
    return 0


@register
def _register(commands: Any, add_campaign_option: Any) -> None:
    parser = commands.add_parser(STAGE, help="Band-gap statistics + KS-energy-vs-time plot")
    add_campaign_option(parser)
    parser.add_argument("--no-plot", action="store_true", help="band-gap stats only, skip the PROCAR plot")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--audit", dest="ksplot_audit", action="store_true")
    parser.set_defaults(func=_cmd)
