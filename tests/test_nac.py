"""Stage 4: CA-NAC input rendering + output collection."""

from __future__ import annotations

from pathlib import Path

import pytest

from namd_launcher.config import load_campaign
from namd_launcher.errors import SafetyError
from namd_launcher.nac import audit_nac, collect_nac, prepare_nac, render_input_py
from namd_launcher.snapshots import prepare_snapshots

from ._helpers import make_xdatcar


@pytest.fixture
def with_snapshots(campaign_dir: Path) -> Path:
    make_xdatcar(campaign_dir / "traj" / "XDATCAR_FINAL", frames=6, n=2)
    (campaign_dir / "KPOINTS").write_text("k\n", encoding="utf-8")
    (campaign_dir / "POTCAR").write_text("p\n", encoding="utf-8")
    prepare_snapshots(load_campaign(campaign_dir / "namd_campaign.yaml"))
    return campaign_dir


def test_render_input_py(with_snapshots: Path) -> None:
    campaign = load_campaign(with_snapshots / "namd_campaign.yaml")
    text = render_input_py(campaign)
    assert "bmin    = 4" in text
    assert "bmax    = 5" in text
    assert "is_gamma_version = True" in text
    assert "range(T_start - 1, T_end)" in text
    assert "T_end   = 3" in text
    assert "%03d" in text
    assert "@" not in text  # every placeholder filled


def test_prepare_renders_input_py(with_snapshots: Path) -> None:
    campaign = load_campaign(with_snapshots / "namd_campaign.yaml")
    dry = prepare_nac(campaign, dry_run=True)
    assert dry["mode"] == "dry-run"
    assert dry["nbasis_out"] == 2
    assert dry["canac"]["found"] in (True, False)  # resolution attempted, not vendored

    result = prepare_nac(campaign)
    snap = with_snapshots / "snapshots"
    assert (snap / "input.py").is_file()
    # nothing from CA-NAC is copied in -- it is a dependency, not vendored
    assert not (snap / "CAnac.py").exists()
    assert (with_snapshots / "nac" / "nac_manifest.json").is_file()
    assert result["audit_status"] == "PENDING"

    with pytest.raises(SafetyError, match="already exists"):
        prepare_nac(campaign)


def test_run_requires_canac_or_allow_missing(with_snapshots: Path, monkeypatch) -> None:
    monkeypatch.delenv("NAMDFORGE_CANAC_DIR", raising=False)
    campaign = load_campaign(with_snapshots / "namd_campaign.yaml")
    prepare_nac(campaign)
    from namd_launcher.nac import run_nac

    # CA-NAC not installed in the test env -> refuses without --allow-missing
    with pytest.raises(SafetyError, match="CA-NAC not found"):
        run_nac(campaign)
    out = run_nac(campaign, allow_missing=True)
    assert out["mode"] == "dry-run"
    body = Path(out["script"]).read_text(encoding="utf-8")
    assert "python input.py" in body


def test_run_uses_configured_canac_dir(with_snapshots: Path, tmp_path: Path) -> None:
    fake = tmp_path / "CA-NAC"
    fake.mkdir()
    (fake / "CAnac.py").write_text("# stub\n", encoding="utf-8")
    vbu = tmp_path / "VaspBandUnfolding"
    vbu.mkdir()
    (vbu / "vaspwfc.py").write_text("# stub\n", encoding="utf-8")

    campaign_file = with_snapshots / "namd_campaign.yaml"
    campaign_file.write_text(
        campaign_file.read_text(encoding="utf-8").replace(
            "  nproc: 2\n",
            f"  nproc: 2\n  canac_dir: {fake.as_posix()}\n  vaspwfc_dir: {vbu.as_posix()}\n",
        ),
        encoding="utf-8",
    )
    campaign = load_campaign(campaign_file)
    from namd_launcher.nac import run_nac

    prepare_nac(campaign)
    out = run_nac(campaign)
    assert out["canac"]["found"] is True
    body = Path(out["script"]).read_text(encoding="utf-8")
    assert fake.as_posix() in body


def test_collect_and_audit(with_snapshots: Path) -> None:
    campaign = load_campaign(with_snapshots / "namd_campaign.yaml")
    prepare_nac(campaign)
    snap = with_snapshots / "snapshots"
    # nbasis = 2 -> NAC has 4 columns, eig has 2 columns; 2 frames of data
    (snap / "CAnac_2_7_ispin1_k1_ps_real_re.txt").write_text(
        "0.0 1.0 -1.0 0.0\n0.0 2.0 -2.0 0.0\n", encoding="utf-8"
    )
    (snap / "CAeig_2_7_ispin1_k1_ps_real.txt").write_text("-3.0 -1.0\n-3.1 -0.9\n", encoding="utf-8")

    result = collect_nac(campaign)
    nac_dir = with_snapshots / "nac"
    assert (nac_dir / "NATXT").read_text(encoding="utf-8").split("\n")[0] == "0.0 1.0 -1.0 0.0"
    assert (nac_dir / "EIGTXT").is_file()
    assert (nac_dir / "energy.dat").is_file()
    assert result["natxt_columns"] == 4
    assert result["eigtxt_columns"] == 2
    assert audit_nac(campaign)["status"] == "PASS"


def test_audit_flags_wrong_columns(with_snapshots: Path) -> None:
    campaign = load_campaign(with_snapshots / "namd_campaign.yaml")
    prepare_nac(campaign)
    snap = with_snapshots / "snapshots"
    (snap / "CAnac_x_re.txt").write_text("0 1 2\n", encoding="utf-8")  # 3 cols, expected 4
    (snap / "CAeig_x.txt").write_text("-3 -1\n", encoding="utf-8")
    collect_nac(campaign)
    audit = audit_nac(campaign)
    assert audit["status"] == "FAIL"
