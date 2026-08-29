"""Stage 5a -- pure-dephasing matrix (DEPHTIME) from energy.dat.

Port of ``Dephase.py`` (Jaeger, Fischer, Prezhdo, JCP 2012): for every pair of
adiabatic states, form the KS energy-gap fluctuation, its autocorrelation
function, the second cumulative integral G(t), the dephasing function
D(t)=exp(-G), and fit a Gaussian exp(-t^2 / 2c^2). ``c`` (fs) is written to
``DEPHTIME``; the diagonal is zero.

A perovskite sanity check follows: the mean off-diagonal dephasing time should
sit in a few-fs band (the user's own runs give ~7 fs; well under 20).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np

from ._stage import write_audit, write_manifest
from .cli import _json, register
from .config import Campaign, load_campaign
from .errors import DependencyError, SafetyError
from .state import StateStore

STAGE = "dephase"
_HBAR_EV_FS = 0.6582119513926019


def _cumtrapz(values: np.ndarray, dx: float) -> np.ndarray:
    try:
        from scipy.integrate import cumulative_trapezoid

        return cumulative_trapezoid(values, dx=dx, initial=0)
    except ImportError:
        out = np.zeros_like(values, dtype=float)
        out[1:] = np.cumsum((values[1:] + values[:-1]) * 0.5 * dx)
        return out


def dephasing_matrix(energy: np.ndarray, *, dt_fs: float = 1.0) -> np.ndarray:
    """(nbasis, nbasis) Gaussian dephasing times in fs; zero diagonal."""

    try:
        from scipy.optimize import curve_fit
    except ImportError as exc:  # pragma: no cover
        raise DependencyError("dephase needs scipy: pip install 'namdforge[report]'") from exc

    energy = np.asarray(energy, dtype=float)
    if energy.ndim != 2 or energy.shape[1] < 2:
        raise SafetyError("energy.dat must be a 2-D table with >= 2 state columns")
    nbasis = energy.shape[1]
    matrix = np.zeros((nbasis, nbasis), dtype=float)

    def gaussian(x: np.ndarray, c: float) -> np.ndarray:
        return np.exp(-(x**2) / (2.0 * c**2))

    for ii in range(nbasis):
        for jj in range(ii):
            et = energy[:, ii] - energy[:, jj]
            et = et - et.mean()
            if et.size < 4 or not np.any(et):
                continue
            acf = np.correlate(et, et, "full")[et.size - 1 :] / et.size
            gt = _cumtrapz(_cumtrapz(acf, dt_fs), dt_fs) / _HBAR_EV_FS**2
            dt_func = np.exp(-gt)
            t = np.arange(dt_func.size) * dt_fs
            try:
                popt, _ = curve_fit(gaussian, t, dt_func, p0=[10.0], maxfev=10000)
                c = abs(float(popt[0]))
            except (RuntimeError, ValueError):
                c = 0.0
            matrix[ii, jj] = matrix[jj, ii] = c
    return matrix


def run_dephase(campaign: Campaign, *, energy_file: str | None = None, force: bool = False) -> dict[str, Any]:
    nac_root = campaign.stage_dir("nac")
    energy_path = Path(energy_file) if energy_file else nac_root / "energy.dat"
    if not energy_path.is_file() or not energy_path.stat().st_size:
        raise SafetyError(f"{energy_path} missing. Run `inamd nac collect` first (or pass --energy-file).")

    energy = np.loadtxt(energy_path)
    dt_fs = float(campaign.dephasing["dt_fs"])
    matrix = dephasing_matrix(energy, dt_fs=dt_fs)

    dephtime = nac_root / "DEPHTIME"
    if dephtime.exists() and not force:
        raise SafetyError(f"{dephtime} already exists; re-run with --force.")
    np.savetxt(dephtime, matrix, fmt="%10.4f")

    off_diag = matrix[~np.eye(matrix.shape[0], dtype=bool)]
    nonzero = off_diag[off_diag > 0]
    mean_fs = float(nonzero.mean()) if nonzero.size else 0.0
    lo, hi = campaign.dephasing["expect_min_fs"], campaign.dephasing["expect_max_fs"]
    status = "PASS"
    note = f"mean off-diagonal dephasing = {mean_fs:.2f} fs (expected {lo}-{hi} fs)"
    if not nonzero.size:
        status, note = "FAIL", "all dephasing times are zero -- check energy.dat / the Gaussian fits"
    elif not (lo <= mean_fs <= hi):
        status, note = "WARN", note + " -- outside the expected band; inspect the energy gaps"

    payload = {
        "stage": STAGE,
        "energy_file": str(energy_path),
        "frames": int(energy.shape[0]),
        "nbasis": int(energy.shape[1]),
        "dephtime": str(dephtime),
        "mean_offdiag_fs": round(mean_fs, 4),
        "min_offdiag_fs": round(float(nonzero.min()), 4) if nonzero.size else 0.0,
        "max_offdiag_fs": round(float(nonzero.max()), 4) if nonzero.size else 0.0,
        "expected_fs": [lo, hi],
    }
    manifest = write_manifest(nac_root, STAGE, payload)
    audit = {"status": status, "summary": note, **payload}
    write_audit(nac_root, STAGE, audit)
    state = StateStore(campaign.root)
    state.event("dephase", **payload, status=status)
    state.artifact("DEPHTIME", dephtime)
    return {"mode": "written", "status": status, "note": note, **payload, "manifest": str(manifest)}


def audit_dephase(campaign: Campaign) -> dict[str, Any]:
    nac_root = campaign.stage_dir("nac")
    existing = None
    audit_path = nac_root / f"{STAGE}_audit.json"
    if audit_path.is_file():
        import json

        existing = json.loads(audit_path.read_text(encoding="utf-8"))
    if existing:
        return existing
    audit = {"status": "PENDING", "summary": "DEPHTIME not generated yet", "root": str(nac_root)}
    write_audit(nac_root, STAGE, audit)
    return audit


def _cmd(args: argparse.Namespace) -> int:
    campaign = load_campaign(args.campaign)
    if getattr(args, "dephase_audit", False):
        _json(audit_dephase(campaign))
        return 0
    _json(run_dephase(campaign, energy_file=args.energy_file, force=args.force))
    return 0


@register
def _register(commands: Any, add_campaign_option: Any) -> None:
    parser = commands.add_parser(STAGE, help="energy.dat -> DEPHTIME + perovskite sanity check")
    add_campaign_option(parser)
    parser.add_argument("--energy-file", help="override nac/energy.dat")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--audit", dest="dephase_audit", action="store_true", help="print the last audit and exit")
    parser.set_defaults(func=_cmd)
