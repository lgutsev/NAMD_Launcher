"""Vendored scheduler + state store behaviour (InterfaceForge parity)."""

from __future__ import annotations

from pathlib import Path

import pytest

from namd_launcher._vendor.scheduler import render_job, write_job
from namd_launcher.errors import ConfigurationError, SafetyError
from namd_launcher.state import StateStore


def test_render_local_job() -> None:
    profile = {"scheduler": "local", "jobs": {"canac": {"command": "python input.py"}}}
    script = render_job(profile, "canac", job_name="nac")
    assert script.startswith("#!/usr/bin/env bash")
    assert "python input.py" in script


def test_render_slurm_job_tokens() -> None:
    profile = {
        "scheduler": "slurm",
        "jobs": {
            "hefei_namd": {
                "partition": "workq",
                "account": "acct",
                "nodes": 1,
                "ntasks": 48,
                "time": "72:00:00",
                "command": "mpirun -np {ntasks} hfnamd",
            }
        },
    }
    script = render_job(profile, "hefei_namd", job_name="fapi")
    assert "#SBATCH --partition=workq" in script
    assert "mpirun -np 48 hfnamd" in script


def test_render_slurm_missing_account() -> None:
    profile = {"scheduler": "slurm", "jobs": {"x": {"partition": "p", "command": "c"}}}
    with pytest.raises(ConfigurationError):
        render_job(profile, "x")


def test_write_job_refuses_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "run.slurm"
    write_job(target, "#!/bin/bash\n")
    with pytest.raises(SafetyError):
        write_job(target, "#!/bin/bash\n")
    write_job(target, "#!/bin/bash\n# v2\n", force=True)
    assert "v2" in target.read_text(encoding="utf-8")


def test_state_store_events_and_artifacts(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.event("prepare", stage="snapshots", runs=3)
    art = tmp_path / "snapshots_manifest.json"
    art.write_text("{}", encoding="utf-8")
    store.artifact("snapshots_manifest", art)
    state = store.load()
    assert state["events"][0]["action"] == "prepare"
    assert "sha256" in state["artifacts"]["snapshots_manifest"]
    assert (tmp_path / ".namdforge" / "state.json").is_file()
