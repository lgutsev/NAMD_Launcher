"""init / plan and the argparse tree."""

from __future__ import annotations

from pathlib import Path

from namd_launcher.cli import build_parser, main
from namd_launcher.config import load_campaign
from namd_launcher.pipeline import build_plan


def test_init_creates_campaign(tmp_path: Path, capsys) -> None:
    rc = main(["init", str(tmp_path / "demo")])
    assert rc == 0
    root = tmp_path / "demo"
    assert (root / "namd_campaign.yaml").is_file()
    assert (root / "profiles" / "loni.yaml").is_file()
    assert (root / "profiles" / "local.yaml").is_file()
    # emitted JSON is parseable
    out = capsys.readouterr().out
    assert "campaign_root" in out


def test_init_refuses_dirty_dir(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    target.mkdir()
    (target / "important.txt").write_text("keep me", encoding="utf-8")
    rc = main(["init", str(target)])
    assert rc == 2


def test_plan_on_campaign(campaign_dir: Path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(campaign_dir)
    rc = main(["plan"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"namd_algo": "DISH"' in out
    assert '"stages"' in out


def test_build_plan_stage_order(campaign_dir: Path) -> None:
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    plan = build_plan(campaign)
    stages = [s["stage"] for s in plan["stages"]]
    assert stages[0] == "snapshots"
    assert stages.index("nac") < stages.index("hefei") < stages.index("shprop")
    assert all(s["status"] == "PENDING" for s in plan["stages"])


def test_parser_has_core_commands() -> None:
    parser = build_parser()
    # argparse stores subparser choices on the _SubParsersAction
    sub = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    for name in ("init", "plan"):
        assert name in sub.choices
