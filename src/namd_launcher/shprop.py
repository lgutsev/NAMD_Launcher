"""Stage 7 -- average SHPROP.* and fit the population decay.

Ports ``SHPROP_avg.sh`` (row-wise mean of one column across every ``SHPROP.*``)
and ``plot_SHPROP_data.py`` (fit ``exp(-t/A)``, report A and R^2). A is the
non-radiative lifetime tau, reported in the campaign's ``analysis.fit_time_unit``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from ._stage import write_audit, write_manifest
from .cli import _json, register
from .config import Campaign, load_campaign
from .errors import DependencyError, SafetyError
from .state import StateStore

STAGE = "shprop"
_TO_FS = {"fs": 1.0, "ps": 1e3, "ns": 1e6}


def _time_factor(time_in: str, fit_unit: str) -> float:
    return _TO_FS[time_in] / _TO_FS[fit_unit]


def average_shprop(namd_root: Path, column: int) -> tuple[np.ndarray, list[str]]:
    files = sorted(namd_root.glob("SHPROP.*"), key=lambda p: p.name)
    if not files:
        raise SafetyError(f"No SHPROP.* files in {namd_root}. Has the Hefei-NAMD job finished?")
    arrays = [np.loadtxt(f) for f in files]
    shapes = {a.shape for a in arrays}
    if len(shapes) != 1:
        raise SafetyError(f"SHPROP.* files have mismatched shapes: {sorted(shapes)}")
    stacked = np.stack(arrays)
    if column - 1 >= stacked.shape[2]:
        raise SafetyError(f"analysis.shprop_column={column} but SHPROP files have {stacked.shape[2]} columns")
    averaged = arrays[0].copy()
    averaged[:, column - 1] = stacked[:, :, column - 1].mean(axis=0)
    return averaged, [f.name for f in files]


def fit_single_exp(
    time: np.ndarray, population: np.ndarray, *, normalize: bool = True
) -> dict[str, float]:
    try:
        from scipy.optimize import curve_fit
    except ImportError as exc:  # pragma: no cover
        raise DependencyError("shprop fit needs scipy: pip install 'namdforge[report]'") from exc

    y = np.asarray(population, dtype=float)
    if normalize and y.max() != 0:
        y = y / y.max()
    lo, hi = float(time.min()), float(time.max())
    span = hi - lo or 1.0

    def model(x: np.ndarray, a: float) -> np.ndarray:
        return np.exp(-x / a)

    popt, _ = curve_fit(model, time, y, p0=[span], bounds=(span * 1e-3, span * 1e3), maxfev=20000)
    a = float(popt[0])
    resid = y - model(time, a)
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1.0
    return {"tau": a, "r_squared": 1.0 - ss_res / ss_tot}


def _plot(time: np.ndarray, y: np.ndarray, fit: dict[str, float], unit: str, out: Path) -> str | None:
    try:
        import matplotlib

        matplotlib.use("agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    grid = np.linspace(time.min(), time.max(), 400)
    plt.figure(figsize=(7, 5))
    plt.scatter(time, y, s=10, color="green", label="population")
    plt.plot(grid, np.exp(-grid / fit["tau"]), color="red", label="exp(-t/A)")
    plt.xlabel(f"Time ({unit})")
    plt.ylabel("normalized target-state population")
    plt.legend()
    plt.grid(True, ls="--", lw=0.5)
    plt.text(0.05, 0.05, f"A = {fit['tau']:.3g} {unit}\nR2 = {fit['r_squared']:.4f}", transform=plt.gca().transAxes,
             bbox=dict(facecolor="white", alpha=0.8))
    plt.tight_layout()
    plt.savefig(out, dpi=200)
    plt.close()
    return str(out)


def run_shprop(campaign: Campaign, *, force: bool = False) -> dict[str, Any]:
    namd_root = campaign.stage_dir("namd")
    analysis = campaign.analysis
    column = int(analysis["shprop_column"])
    averaged, files = average_shprop(namd_root, column)

    data_path = namd_root / "data.txt"
    if data_path.exists() and not force:
        raise SafetyError(f"{data_path} already exists; re-run with --force.")
    np.savetxt(data_path, averaged, fmt="%.15g")

    factor = _time_factor(analysis["time_in"], analysis["fit_time_unit"])
    time = averaged[:, 0] * factor
    population = averaged[:, column - 1]
    fit = fit_single_exp(time, population, normalize=analysis["normalize"])

    unit = analysis["fit_time_unit"]
    plot = _plot(
        time,
        population / population.max() if analysis["normalize"] and population.max() else population,
        fit, unit, namd_root / "shprop_fit.png",
    )

    payload = {
        "stage": STAGE,
        "shprop_files": len(files),
        "column": column,
        "time_unit_in": analysis["time_in"],
        "fit_time_unit": unit,
        "tau": round(fit["tau"], 6),
        "tau_unit": unit,
        "r_squared": round(fit["r_squared"], 6),
        "data_file": str(data_path),
        "plot": plot,
        "n_points": int(time.size),
    }
    (namd_root / "shprop_fit.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = write_manifest(namd_root, STAGE, {**payload, "files": files})

    status = "PASS" if fit["r_squared"] >= 0.9 else "WARN"
    note = f"tau = {fit['tau']:.4g} {unit}, R^2 = {fit['r_squared']:.4f} over {len(files)} SHPROP files"
    if fit["r_squared"] < 0.9:
        note += " -- low R^2: the run may be too short, or the decay is not single-exponential"
    audit = {"status": status, "summary": note, **payload}
    write_audit(namd_root, STAGE, audit)
    state = StateStore(campaign.root)
    state.event("shprop", tau=payload["tau"], tau_unit=unit, r_squared=payload["r_squared"], files=len(files))
    state.artifact("shprop_fit", namd_root / "shprop_fit.json")
    return {"mode": "fitted", "status": status, "note": note, **payload, "manifest": str(manifest)}


def audit_shprop(campaign: Campaign) -> dict[str, Any]:
    namd_root = campaign.stage_dir("namd")
    path = namd_root / f"{STAGE}_audit.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    n = len(list(namd_root.glob("SHPROP.*")))
    audit = {
        "status": "PENDING",
        "summary": f"{n} SHPROP.* present; fit not run yet" if n else "no SHPROP.* yet",
        "root": str(namd_root),
    }
    write_audit(namd_root, STAGE, audit)
    return audit


def _cmd(args: argparse.Namespace) -> int:
    campaign = load_campaign(args.campaign)
    if getattr(args, "shprop_audit", False):
        _json(audit_shprop(campaign))
        return 0
    _json(run_shprop(campaign, force=args.force))
    return 0


@register
def _register(commands: Any, add_campaign_option: Any) -> None:
    parser = commands.add_parser(STAGE, help="Average SHPROP.* and fit exp(-t/A) -> tau")
    add_campaign_option(parser)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--audit", dest="shprop_audit", action="store_true")
    parser.set_defaults(func=_cmd)
