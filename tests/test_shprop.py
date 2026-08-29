"""Stage 7: SHPROP averaging + exponential lifetime fit."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from namd_launcher.config import load_campaign
from namd_launcher.errors import SafetyError
from namd_launcher.shprop import average_shprop, fit_single_exp, run_shprop


def _write_shprop(namd_dir: Path, *, n_files: int, tau_fs: float, t_end_fs: float = 3.0e5, npts: int = 120) -> None:
    namd_dir.mkdir(parents=True, exist_ok=True)
    t = np.linspace(0.0, t_end_fs, npts)
    rng = np.random.default_rng(0)
    for k in range(n_files):
        pop = np.exp(-t / tau_fs) + 0.01 * rng.standard_normal(npts)
        block = np.column_stack([t, np.ones_like(t), 1.0 - pop, pop])
        np.savetxt(namd_dir / f"SHPROP.{k + 1}", block)


def test_fit_single_exp_recovers_tau() -> None:
    t = np.linspace(0, 5, 200)
    y = np.exp(-t / 1.7)
    fit = fit_single_exp(t, y, normalize=False)
    assert fit["tau"] == pytest.approx(1.7, rel=1e-3)
    assert fit["r_squared"] > 0.999


def test_average_shprop_shape(campaign_dir: Path) -> None:
    _write_shprop(campaign_dir / "namd", n_files=4, tau_fs=1.0e5)
    averaged, names = average_shprop(campaign_dir / "namd", column=4)
    assert averaged.shape == (120, 4)
    assert names == ["SHPROP.1", "SHPROP.2", "SHPROP.3", "SHPROP.4"]


def test_run_shprop_end_to_end(campaign_dir: Path) -> None:
    _write_shprop(campaign_dir / "namd", n_files=5, tau_fs=1.0e5)  # 0.1 ns
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    result = run_shprop(campaign)
    assert result["fit_time_unit"] == "ns"
    assert result["tau"] == pytest.approx(0.1, rel=0.05)
    assert result["r_squared"] > 0.95
    assert (campaign_dir / "namd" / "data.txt").is_file()
    assert (campaign_dir / "namd" / "shprop_fit.json").is_file()
    with pytest.raises(SafetyError, match="already exists"):
        run_shprop(campaign)


def test_run_shprop_needs_files(campaign_dir: Path) -> None:
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    with pytest.raises(SafetyError, match="No SHPROP"):
        run_shprop(campaign)
