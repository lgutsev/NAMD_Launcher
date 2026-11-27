"""Characterization tests for ``namd_launcher._run.submit`` and ``python -m``.

Pins current behaviour only; the Slurm path is mocked (no sbatch needed).
"""

from __future__ import annotations

import runpy
import subprocess
from pathlib import Path

import pytest

from namd_launcher import _run


def test_planned_when_not_executing(tmp_path: Path) -> None:
    script = tmp_path / "job.sh"
    script.write_text("echo hi\n", encoding="utf-8")
    out = _run.submit({"scheduler": "SLURM"}, script, execute=False)
    assert out == {"status": "planned", "script": str(script.resolve()), "scheduler": "slurm"}


def test_slurm_submit_parses_job_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "job.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="Submitted batch job 4242\n", stderr="")

    monkeypatch.setattr(_run.subprocess, "run", fake_run)
    out = _run.submit({"scheduler": "slurm"}, script, execute=True)
    assert out == {"status": "submitted", "script": str(script.resolve()), "job_id": "4242"}
    assert calls[0][0] == ["sbatch", "job.sh"]
    assert calls[0][1]["cwd"] == script.resolve().parent


def test_slurm_unparseable_output_falls_back_to_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "job.sh"
    script.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        _run.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=" weird \n", stderr=""),
    )
    assert _run.submit({"scheduler": "slurm"}, script, execute=True)["job_id"] == "weird"


def test_local_run_success_and_failure(tmp_path: Path) -> None:
    ok = tmp_path / "ok.sh"
    ok.write_text("echo done\n", encoding="utf-8")
    out = _run.submit({"scheduler": "local"}, ok, execute=True)
    assert out["status"] == "ran"
    assert out["returncode"] == 0
    assert out["stdout_tail"].strip() == "done"

    bad = tmp_path / "bad.sh"
    bad.write_text("echo oops >&2\nexit 3\n", encoding="utf-8")
    out = _run.submit({"scheduler": "local"}, bad, execute=True)
    assert out["status"] == "failed"
    assert out["returncode"] == 3
    assert "oops" in out["stderr_tail"]


def test_module_entry_point_exits_with_cli_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["namd_launcher", "--help"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("namd_launcher", run_name="__main__")
    assert exc.value.code == 0
    assert "usage" in capsys.readouterr().out.lower()
