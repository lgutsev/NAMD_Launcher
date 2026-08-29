"""NBANDS chosen from the reference MD calculation."""

from __future__ import annotations

import gzip
from pathlib import Path

from namd_launcher._nbands import choose_nbands, reference_nbands
from namd_launcher.config import load_campaign
from namd_launcher.snapshots import audit_snapshots, prepare_snapshots

from ._helpers import make_xdatcar

BANDS = {"nbands_margin": 64, "nbands_round": 8}
NAC = {"bmin": 744, "bmax": 745, "bmin_stored": 734, "bmax_stored": 755}


def test_reference_nbands_from_outcar(tmp_path: Path) -> None:
    (tmp_path / "OUTCAR").write_text("  k-points NKPTS =  1   number of bands    NBANDS=  960\n", encoding="utf-8")
    n, src = reference_nbands(tmp_path)
    assert n == 960
    assert "OUTCAR" in src


def test_reference_nbands_from_gz_and_incar(tmp_path: Path) -> None:
    with gzip.open(tmp_path / "OUTCAR.gz", "wt", encoding="utf-8") as fh:
        fh.write("junk\n NBANDS=  844 \n")
    assert reference_nbands(tmp_path)[0] == 844

    other = tmp_path / "b"
    other.mkdir()
    (other / "INCAR").write_text("ENCUT = 400\nNBANDS = 700\n", encoding="utf-8")
    assert reference_nbands(other) == (700, "reference INCAR NBANDS")


def test_reference_nbands_missing(tmp_path: Path) -> None:
    assert reference_nbands(tmp_path)[0] is None
    assert reference_nbands(None)[0] is None


def test_choose_prefers_explicit_but_warns_when_below_reference() -> None:
    out = choose_nbands({**BANDS, "nbands": 500}, NAC, ref_nbands=960, ref_source="OUTCAR")
    assert out["nbands"] == 500
    assert any("below the reference" in n for n in out["notes"])
    assert any("stored window" in n for n in out["notes"])


def test_choose_matches_reference_when_sufficient() -> None:
    out = choose_nbands(BANDS, NAC, ref_nbands=960, ref_source="OUTCAR (executed value)")
    assert out["nbands"] == 960
    assert out["reason"].startswith("matched the reference")
    assert out["notes"] == []


def test_choose_raises_reference_to_requirement() -> None:
    # reference used only 760 bands; CA-NAC stores up to 755 + margin 64 = 819
    out = choose_nbands(BANDS, NAC, ref_nbands=760, ref_source="OUTCAR")
    assert out["nbands"] == 824      # 819 rounded up to a multiple of 8
    assert "raised to" in out["reason"]


def test_choose_falls_back_to_requirement_without_reference() -> None:
    out = choose_nbands(BANDS, NAC, ref_nbands=None, ref_source="no reference directory")
    assert out["nbands"] == 824
    assert any("Set bands.nbands explicitly" in n for n in out["notes"])


def test_choose_unset_when_nothing_to_size_from() -> None:
    out = choose_nbands(BANDS, {}, ref_nbands=None, ref_source="x")
    assert out["nbands"] is None
    assert out["notes"]


def test_prepare_uses_reference_outcar(campaign_dir: Path) -> None:
    step2 = campaign_dir / "MD" / "Step2_300K" / "run1"
    make_xdatcar(step2 / "XDATCAR", frames=5, n=2)
    (step2 / "KPOINTS").write_text("k\n", encoding="utf-8")
    (step2 / "POTCAR").write_text("p\n", encoding="utf-8")
    (step2 / "OUTCAR").write_text("number of bands    NBANDS=  20\n", encoding="utf-8")
    lines = (campaign_dir / "namd_campaign.yaml").read_text(encoding="utf-8").splitlines()
    lines = [ln for ln in lines if ln.strip() != "nbands: 8"]  # drop the explicit override
    text = "\n".join(lines).replace("trajectory: traj/XDATCAR_FINAL", f"trajectory: {step2.as_posix()}")
    (campaign_dir / "namd_campaign.yaml").write_text(text, encoding="utf-8")

    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    result = prepare_snapshots(campaign)
    # bmax_stored 6 + margin 2 = 8; reference 20 already covers it
    assert result["nbands"]["nbands"] == 20
    assert "reference" in result["nbands"]["reason"]
    assert "NBANDS = 20" in (campaign_dir / "snapshots" / "INCAR").read_text(encoding="utf-8")
    assert audit_snapshots(campaign)["status"] == "PASS"
