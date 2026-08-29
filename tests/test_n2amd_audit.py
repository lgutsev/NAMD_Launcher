"""N2AMD stub + whole-campaign audit/status/run."""

from __future__ import annotations

from pathlib import Path

from namd_launcher.audit import campaign_audit
from namd_launcher.cli import main
from namd_launcher.config import load_campaign
from namd_launcher.n2amd import export, plan, status

from ._helpers import make_xdatcar


def test_n2amd_status_reports_not_implemented() -> None:
    s = status()
    assert s["implemented"] is False
    assert s["replaces_stages"] == ["waverun", "nac"]
    assert "torch" in s["dependencies_present"]


def test_n2amd_plan_with_campaign(campaign_dir: Path) -> None:
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    p = plan(campaign)
    assert len(p["workflow"]) == 5
    assert p["namd_algo"] == "DISH"


def test_n2amd_export_writes_manifest_and_checklist(campaign_dir: Path) -> None:
    make_xdatcar(campaign_dir / "traj" / "XDATCAR_FINAL", frames=6, n=2)
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    result = export(campaign)
    assert result["implemented"] is False
    assert (campaign_dir / "n2amd" / "frames_manifest.json").is_file()
    assert (campaign_dir / "n2amd" / "TRAINING_CHECKLIST.md").is_file()


def test_campaign_audit_all_pending(campaign_dir: Path) -> None:
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    report = campaign_audit(campaign)
    assert {s["stage"] for s in report["stages"]} == {
        "snapshots", "waverun", "ksplot", "nac", "dephase", "inicon", "hefei", "shprop"
    }
    assert report["status"] in {"PENDING", "ERROR"}


def test_status_command_prints_table(campaign_dir: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(campaign_dir)
    rc = main(["status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "snapshots" in out and "shprop" in out


def test_run_dry_run(campaign_dir: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(campaign_dir)
    rc = main(["run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "would-run" in out
    assert "never submits" not in out or "cluster jobs" in out
