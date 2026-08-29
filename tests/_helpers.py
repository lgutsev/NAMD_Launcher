"""Plain helper functions shared across test modules (not fixtures)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def make_xdatcar(path: Path, *, frames: int, species: str = "H", n: int = 2) -> Path:
    """Write a tiny valid VASP-5 XDATCAR with ``frames`` Direct configurations."""

    path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "test cell",
        "1.0",
        "10.0 0.0 0.0",
        "0.0 10.0 0.0",
        "0.0 0.0 10.0",
        species,
        str(n),
    ]
    body: list[str] = []
    for f in range(frames):
        body.append(f"Direct configuration=  {f + 1}")
        for i in range(n):
            x = 0.1 + 0.01 * f + 0.001 * i
            body.append(f"  {x:.8f}  {x:.8f}  {x:.8f}")
    path.write_text("\n".join(header + body) + "\n", encoding="utf-8")
    return path


def run_cli(args: list[str], cwd: Path) -> tuple[int, dict, str]:
    """Invoke the installed ``inamd`` CLI and parse its JSON stdout."""

    proc = subprocess.run(
        [sys.executable, "-m", "namd_launcher", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    payload: dict = {}
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = {"_raw": proc.stdout}
    return proc.returncode, payload, proc.stderr
