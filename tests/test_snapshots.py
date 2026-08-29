"""Stage 1: snapshot folder preparation."""

from __future__ import annotations

from pathlib import Path

import pytest

from namd_launcher._xdatcar import read_xdatcar
from namd_launcher.config import load_campaign
from namd_launcher.errors import SafetyError
from namd_launcher.snapshots import audit_snapshots, prepare_snapshots, resolve_source

from ._helpers import make_xdatcar


def test_read_xdatcar_frames(tmp_path: Path) -> None:
    xd = make_xdatcar(tmp_path / "XDATCAR_FINAL", frames=6, n=3)
    traj = read_xdatcar(xd)
    assert len(traj) == 6
    assert traj.n_ions == 3
    assert traj.species == ["H"]


def test_prepare_from_xdatcar_file(campaign_dir: Path) -> None:
    make_xdatcar(campaign_dir / "traj" / "XDATCAR_FINAL", frames=5, n=2)
    (campaign_dir / "KPOINTS").write_text("auto\n0\nG\n1 1 1\n", encoding="utf-8")
    (campaign_dir / "POTCAR").write_text("  PAW_PBE H\n", encoding="utf-8")
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")

    result = prepare_snapshots(campaign, dry_run=True)
    assert result["mode"] == "dry-run"
    assert result["nsw"] == 3
    assert result["last_folder"] == "003"

    result = prepare_snapshots(campaign)
    root = campaign_dir / "snapshots"
    for folder in ("001", "002", "003"):
        assert (root / folder / "POSCAR").is_file()
        assert (root / folder / "INCAR").exists()
    assert (root / "INCAR").is_file()
    # NBANDS injected from bands.nbands
    assert "NBANDS = 8" in (root / "INCAR").read_text(encoding="utf-8")
    assert result["audit_status"] == "PASS"

    audit = audit_snapshots(campaign)
    assert audit["status"] == "PASS"
    assert audit["folders_total"] == 3


def test_prepare_uses_last_frames(campaign_dir: Path) -> None:
    make_xdatcar(campaign_dir / "traj" / "XDATCAR_FINAL", frames=10, n=2)
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    result = prepare_snapshots(campaign, dry_run=True)
    # last 3 of 10 frames (0-indexed 7, 8, 9)
    assert result["selected_frame_indices"] == [7, 9]


def test_prepare_refuses_short_trajectory(campaign_dir: Path) -> None:
    make_xdatcar(campaign_dir / "traj" / "XDATCAR_FINAL", frames=2, n=2)
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    with pytest.raises(SafetyError, match="requires at least"):
        prepare_snapshots(campaign)


def test_prepare_refuses_existing_without_force(campaign_dir: Path) -> None:
    make_xdatcar(campaign_dir / "traj" / "XDATCAR_FINAL", frames=5, n=2)
    (campaign_dir / "KPOINTS").write_text("k\n", encoding="utf-8")
    (campaign_dir / "POTCAR").write_text("p\n", encoding="utf-8")
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    prepare_snapshots(campaign)
    with pytest.raises(SafetyError, match="already exists"):
        prepare_snapshots(campaign)
    # force succeeds
    prepare_snapshots(campaign, force=True)


def test_resolve_source_step2_run(campaign_dir: Path, tmp_path: Path) -> None:
    step2 = tmp_path / "Step2_300K" / "run1"
    make_xdatcar(step2 / "XDATCAR", frames=5, n=2)
    (step2 / "KPOINTS").write_text("k\n", encoding="utf-8")
    (step2 / "POTCAR").write_text("pot\n", encoding="utf-8")
    (step2 / "runvasp.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (campaign_dir / "namd_campaign.yaml").write_text(
        (campaign_dir / "namd_campaign.yaml").read_text(encoding="utf-8").replace(
            "trajectory: traj/XDATCAR_FINAL", f"trajectory: {step2.as_posix()}"
        ),
        encoding="utf-8",
    )
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    src = resolve_source(campaign)
    assert src["kind"] == "step2_run"
    assert src["inputs"]["KPOINTS"].name == "KPOINTS"
    assert src["inputs"]["launcher"].name == "runvasp.sh"
