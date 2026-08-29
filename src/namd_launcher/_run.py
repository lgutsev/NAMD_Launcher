"""Submit a rendered job script under the campaign's scheduler.

Kept separate from ``_compat.submit_run`` (which also assembles a per-run
POTCAR): NAMD Launcher's job scripts loop over already-staged snapshot folders,
so there is nothing to assemble at submit time.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any


def submit(profile: dict[str, Any], script: str | Path, *, execute: bool) -> dict[str, Any]:
    """Submit (or, for ``execute=False``, describe) one job script."""

    script_path = Path(script).resolve()
    scheduler = str(profile.get("scheduler", "")).lower()
    if not execute:
        return {"status": "planned", "script": str(script_path), "scheduler": scheduler}

    if scheduler == "slurm":
        result = subprocess.run(
            ["sbatch", script_path.name],
            cwd=script_path.parent,
            check=True,
            capture_output=True,
            text=True,
        )
        match = re.search(r"Submitted batch job\s+(\d+)", result.stdout)
        job_id = match.group(1) if match else result.stdout.strip()
        return {"status": "submitted", "script": str(script_path), "job_id": job_id}

    # local scheduler: run it now, block until done.
    result = subprocess.run(
        ["bash", script_path.name],
        cwd=script_path.parent,
        capture_output=True,
        text=True,
    )
    return {
        "status": "ran" if result.returncode == 0 else "failed",
        "script": str(script_path),
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
    }
