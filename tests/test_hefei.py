"""Stage 6: Hefei-NAMD `inp` rendering + input staging."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from namd_launcher.config import load_campaign
from namd_launcher.errors import SafetyError
from namd_launcher.hefeinamd import audit_hefei, launch_hefei, prepare_hefei, render_inp


def _seed_nac(nac_dir: Path, *, frames: int = 3, nbasis: int = 2, inicon_rows: int = 2) -> None:
    nac_dir.mkdir(parents=True, exist_ok=True)
    nac_row = " ".join("0.001" for _ in range(nbasis * nbasis))
    eig_row = " ".join(f"-{1.0 + 0.1 * k:.3f}" for k in range(nbasis))
    (nac_dir / "NATXT").write_text("\n".join(nac_row for _ in range(frames)) + "\n", encoding="utf-8")
    (nac_dir / "EIGTXT").write_text("\n".join(eig_row for _ in range(frames)) + "\n", encoding="utf-8")
    (nac_dir / "INICON").write_text("\n".join("1 5" for _ in range(inicon_rows)) + "\n", encoding="utf-8")
    (nac_dir / "DEPHTIME").write_text("    0.0000    7.0000\n    7.0000    0.0000\n", encoding="utf-8")


def test_render_inp_dev_dish(campaign_dir: Path) -> None:
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    text, meta = render_inp(campaign)
    assert meta["binary"] == "hfnamd"
    assert meta["nbasis"] == 2
    assert 'ALGO       = "DISH"' in text
    assert "BMIN       = 4" in text
    assert "@" not in text


def test_render_inp_inherits_snapshot_timestep(campaign_dir: Path) -> None:
    config_path = campaign_dir / "namd_campaign.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["snapshots"]["potim"] = 2.5
    data["dephasing"] = {"dt_fs": 2.5}
    del data["namd"]["potim"]
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    campaign = load_campaign(config_path)
    inp, _ = render_inp(campaign)
    assert "POTIM      = 2.5" in inp


def test_render_inp_master_dish_needs_nbands(campaign_dir: Path) -> None:
    text = (campaign_dir / "namd_campaign.yaml").read_text(encoding="utf-8").replace("branch: dev", "branch: master")
    (campaign_dir / "namd_campaign.yaml").write_text(text, encoding="utf-8")
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    inp, meta = render_inp(campaign)
    assert meta["binary"] == "dish"
    assert "NBANDS   = 8" in inp        # inherited from bands.nbands
    assert 'DIINIT   = "DEPHTIME"' in inp
    assert "LDISH    = .TRUE." in inp


def test_launch_uses_branch_binary_without_mpi_placeholder_locally(campaign_dir: Path) -> None:
    _seed_nac(campaign_dir / "nac")
    config_path = campaign_dir / "namd_campaign.yaml"
    text = config_path.read_text(encoding="utf-8").replace("branch: dev", "branch: master")
    config_path.write_text(text, encoding="utf-8")
    campaign = load_campaign(config_path)
    prepare_hefei(campaign)

    result = launch_hefei(campaign)
    script = Path(result["script"]).read_text(encoding="utf-8")
    assert "dish" in script
    assert "hfnamd" not in script
    assert "{ntasks}" not in script


def test_prepare_stages_inputs(campaign_dir: Path) -> None:
    _seed_nac(campaign_dir / "nac")
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    result = prepare_hefei(campaign)
    namd = campaign_dir / "namd"
    for name in ("inp", "NATXT", "EIGTXT", "INICON", "DEPHTIME"):
        assert (namd / name).is_file()
    assert result["audit_status"] == "PASS"
    with pytest.raises(SafetyError, match="already exists"):
        prepare_hefei(campaign)


def test_prepare_rejects_inconsistent_natxt(campaign_dir: Path) -> None:
    _seed_nac(campaign_dir / "nac")
    (campaign_dir / "nac" / "NATXT").write_text("0.1 0.2 0.3\n", encoding="utf-8")  # 3 cols, need 4
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    with pytest.raises(SafetyError, match="NATXT has 3 columns"):
        prepare_hefei(campaign)


def test_prepare_rejects_inicon_band_outside_active_window(campaign_dir: Path) -> None:
    _seed_nac(campaign_dir / "nac", inicon_rows=2)
    (campaign_dir / "nac" / "INICON").write_text("1 5\n2 6\n", encoding="utf-8")
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    with pytest.raises(SafetyError, match="outside active window"):
        prepare_hefei(campaign)


def test_prepare_rejects_rectangular_dephtime(campaign_dir: Path) -> None:
    _seed_nac(campaign_dir / "nac", inicon_rows=2)
    (campaign_dir / "nac" / "DEPHTIME").write_text("0 7\n7 0\n0 7\n", encoding="utf-8")
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    with pytest.raises(SafetyError, match="DEPHTIME is 3x2"):
        prepare_hefei(campaign)


def test_prepare_rejects_nsw_over_frames(campaign_dir: Path) -> None:
    _seed_nac(campaign_dir / "nac", frames=1)
    text = (campaign_dir / "namd_campaign.yaml").read_text(encoding="utf-8").replace("nsw: 1", "nsw: 2")
    (campaign_dir / "namd_campaign.yaml").write_text(text, encoding="utf-8")
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    with pytest.raises(SafetyError, match="exceeds"):
        prepare_hefei(campaign)


def test_audit_pending_before_prepare(campaign_dir: Path) -> None:
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    assert audit_hefei(campaign)["status"] == "PENDING"


def test_dev_fssh_template(campaign_dir: Path) -> None:
    text = (campaign_dir / "namd_campaign.yaml").read_text(encoding="utf-8").replace("algo: DISH", "algo: FSSH")
    (campaign_dir / "namd_campaign.yaml").write_text(text, encoding="utf-8")
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    inp, meta = render_inp(campaign)
    assert 'ALGO       = "FSSH"' in inp
    assert meta["binary"] == "hfnamd"
