"""Stage 2: WAVECAR SCF orchestration (chunk + array job rendering)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from namd_launcher.config import load_campaign
from namd_launcher.errors import SafetyError
from namd_launcher.snapshots import prepare_snapshots
from namd_launcher.waverun import audit_waverun, launch_waverun, plan_waverun

from ._helpers import make_xdatcar

SLURM_PROFILE = textwrap.dedent(
    """\
    name: t
    scheduler: slurm
    jobs:
      vasp_nac:
        partition: checkpt
        account: acct
        nodes: 2
        ntasks: 128
        time: "72:00:00"
        command: "srun -n {ntasks} vasp_gam"
    """
)


@pytest.fixture
def prepared(campaign_dir: Path) -> Path:
    make_xdatcar(campaign_dir / "traj" / "XDATCAR_FINAL", frames=8, n=2)
    (campaign_dir / "KPOINTS").write_text("k\n", encoding="utf-8")
    (campaign_dir / "POTCAR").write_text("p\n", encoding="utf-8")
    (campaign_dir / "profiles" / "loni.yaml").write_text(SLURM_PROFILE, encoding="utf-8")
    text = (campaign_dir / "namd_campaign.yaml").read_text(encoding="utf-8")
    (campaign_dir / "namd_campaign.yaml").write_text(text.replace("profiles/local.yaml", "profiles/loni.yaml"), "utf-8")
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    prepare_snapshots(campaign)
    return campaign_dir


def test_plan_chunks(prepared: Path) -> None:
    campaign = load_campaign(prepared / "namd_campaign.yaml")
    plan = plan_waverun(campaign, chunk=2)
    assert plan["folders_total"] == 3
    assert plan["mode"] == "chunk"
    spans = [(j["first"], j["last"]) for j in plan["jobs"]]
    assert spans == [("001", "002"), ("003", "003")]


def test_launch_dry_run_writes_scripts(prepared: Path) -> None:
    campaign = load_campaign(prepared / "namd_campaign.yaml")
    result = launch_waverun(campaign, chunk=2)
    assert result["mode"] == "dry-run"
    scripts = sorted((prepared / "snapshots").glob("*waverun*.sh"))
    assert len(scripts) == 2
    body = scripts[0].read_text(encoding="utf-8")
    assert "srun -n 128 vasp_gam" in body
    assert 'for i in $(seq -f "%03g" 1 2); do' in body
    assert "General timing and accounting" in body
    assert "[ -s WAVECAR ]" in body
    assert all(row["status"] == "planned" for row in result["jobs"])


def test_launch_array(prepared: Path) -> None:
    campaign = load_campaign(prepared / "namd_campaign.yaml")
    result = launch_waverun(campaign, array=True, array_throttle=5)
    body = Path(result["scripts"][0]).read_text(encoding="utf-8")
    assert "#SBATCH --array=1-3%5" in body
    assert "SLURM_ARRAY_TASK_ID" in body
    assert "already complete, skipping" in body


def test_audit_reports_convergence(prepared: Path) -> None:
    campaign = load_campaign(prepared / "namd_campaign.yaml")
    snap = prepared / "snapshots"
    (snap / "001" / "OUTCAR").write_text("...\n reached required accuracy - stopping\n", encoding="utf-8")
    (snap / "001" / "WAVECAR").write_text("x" * 10, encoding="utf-8")
    (snap / "002" / "OUTCAR").write_text("still going\n", encoding="utf-8")
    audit = audit_waverun(campaign)
    assert audit["converged"] == 1
    assert audit["status"] in {"WARN", "PASS"}
    by_folder = {r["folder"]: r["status"] for r in audit["runs"]}
    assert by_folder["001"] == "PASS"
    assert by_folder["002"] == "WARN"
    assert by_folder["003"] == "PENDING"


def test_plan_requires_snapshots(campaign_dir: Path) -> None:
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    with pytest.raises(SafetyError, match="snapshots prepare"):
        plan_waverun(campaign)
