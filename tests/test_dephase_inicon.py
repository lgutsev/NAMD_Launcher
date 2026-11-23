"""Stage 5: DEPHTIME + INICON."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from namd_launcher.config import load_campaign
from namd_launcher.dephase import dephasing_matrix, run_dephase
from namd_launcher.errors import SafetyError
from namd_launcher.inicon import generate_inicon


def _energy_dat(path: Path, *, frames: int, gap_noise: float, seed: int = 0) -> Path:
    rng = np.random.default_rng(seed)
    base = -1.5 + np.zeros(frames)
    gap = 1.0 + gap_noise * rng.standard_normal(frames)
    data = np.column_stack([base, base + gap])
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savetxt(path, data)
    return path


def test_dephasing_matrix_shape_and_diagonal() -> None:
    rng = np.random.default_rng(1)
    e = np.column_stack([np.zeros(200), 1.0 + 0.05 * rng.standard_normal(200)])
    m = dephasing_matrix(e, dt_fs=1.0)
    assert m.shape == (2, 2)
    assert m[0, 0] == 0.0 and m[1, 1] == 0.0
    assert m[0, 1] == m[1, 0] > 0.0


def test_dephasing_faster_for_larger_fluctuation() -> None:
    rng = np.random.default_rng(2)
    noise = rng.standard_normal(400)
    small = np.column_stack([np.zeros(400), 1.0 + 0.02 * noise])
    large = np.column_stack([np.zeros(400), 1.0 + 0.20 * noise])
    c_small = dephasing_matrix(small)[0, 1]
    c_large = dephasing_matrix(large)[0, 1]
    assert c_large < c_small


def test_run_dephase_writes_dephtime(campaign_dir: Path) -> None:
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    _energy_dat(campaign_dir / "nac" / "energy.dat", frames=300, gap_noise=0.05)
    result = run_dephase(campaign)
    deph = campaign_dir / "nac" / "DEPHTIME"
    assert deph.is_file()
    m = np.loadtxt(deph)
    assert m.shape == (2, 2)
    assert result["status"] in {"PASS", "WARN"}
    with pytest.raises(SafetyError, match="already exists"):
        run_dephase(campaign)


def test_run_dephase_requires_energy(campaign_dir: Path) -> None:
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    with pytest.raises(SafetyError, match="energy.dat"):
        run_dephase(campaign)


def test_inicon_deterministic(campaign_dir: Path) -> None:
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    first = generate_inicon(campaign)
    rows_1 = (campaign_dir / "nac" / "INICON").read_text(encoding="utf-8")
    generate_inicon(campaign, force=True)
    rows_2 = (campaign_dir / "nac" / "INICON").read_text(encoding="utf-8")
    assert rows_1 == rows_2
    lines = rows_1.strip().splitlines()
    assert len(lines) == campaign.inicon["nsample"]
    for line in lines:
        t, b = map(int, line.split())
        assert t == 2
        assert 5 <= b <= 6
    assert first["status"] in {"PASS", "WARN"}


def test_inicon_warns_when_tmax_exceeds_frames(campaign_dir: Path) -> None:
    # 2 NAC frames but tmax = 3
    (campaign_dir / "nac").mkdir()
    (campaign_dir / "nac" / "NATXT").write_text("0 0 0 0\n0 0 0 0\n", encoding="utf-8")
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    result = generate_inicon(campaign)
    assert result["status"] == "WARN"
    assert any("exceeds" in n for n in result["notes"])


def test_inicon_starts_distinct_and_at_least_two(campaign_dir: Path) -> None:
    """hfnamd reads the step before the start (start 1 aborts, PD031) and names output SHPROP.<start>."""
    text = (campaign_dir / "namd_campaign.yaml").read_text(encoding="utf-8")
    text = text.replace("nsw: 3\n", "nsw: 60\n").replace("tmax: 3\n", "tmax: 60\n").replace("nsw: 2\n", "nsw: 40\n")
    text = text.replace("nsample: 1\n", "nsample: 39\n")
    (campaign_dir / "namd_campaign.yaml").write_text(text, encoding="utf-8")
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    result = generate_inicon(campaign)
    starts = [int(line.split()[0]) for line in (campaign_dir / "nac" / "INICON").read_text(encoding="utf-8").splitlines()]
    assert sorted(starts) == list(range(2, 41))  # all 39 of [2, nsw=40]: DISH caps tmax at namd.nsw
    assert result["start_range"] == [2, 40]
    assert any("capped" in n for n in result["notes"])
    text = text.replace("nsample: 39\n", "nsample: 40\n")
    (campaign_dir / "namd_campaign.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(SafetyError, match="distinct start steps"):
        generate_inicon(load_campaign(campaign_dir / "namd_campaign.yaml"), force=True)
