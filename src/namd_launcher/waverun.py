"""Stage 2 -- one WAVECAR/eigenvalue SCF per snapshot folder.

Ports ``runvasp_range.sh``: a chunk job cd's into ``001/`` .. ``NNN/`` in turn
and runs VASP (the profile's ``vasp_nac`` command) in each, checking OUTCAR for
convergence. Chunking ("1 100", "101 200", ...) lets different nodes own
different snapshot ranges, exactly as the original workflow does.

``--array`` instead emits a single Slurm array job, one task per folder.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ._compat import render_job, write_job
from ._run import submit
from ._stage import rollup_status, write_audit, write_manifest
from .cli import _json, register
from .config import Campaign, load_campaign, load_profile
from .errors import SafetyError
from .state import StateStore

STAGE = "waverun"


def _snapshot_folders(root: Path, digits: int) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and p.name.isdigit() and len(p.name) == digits)


def _converged(folder: Path) -> bool:
    outcar = folder / "OUTCAR"
    if not outcar.is_file() or not outcar.stat().st_size:
        return False
    tail = outcar.read_bytes()[-8192:].decode("utf-8", errors="ignore")
    return "reached required accuracy" in tail or "General timing and accounting" in tail


def _chunks(folders: list[str], size: int) -> list[list[str]]:
    return [folders[i : i + size] for i in range(0, len(folders), size)]


def _loop_command(root: Path, first: str, last: str, digits: int, vasp_command: str) -> str:
    return "\n".join(
        [
            f'ROOT="{root.as_posix()}"',
            f'for i in $(seq -f "%0{digits}g" {int(first)} {int(last)}); do',
            '  cd "$ROOT/$i" || { echo "missing snapshot $i"; continue; }',
            "  if [ -s OUTCAR ] && grep -q 'reached required accuracy' OUTCAR; then",
            '    echo "snapshot $i already converged, skipping"; cd "$ROOT"; continue',
            "  fi",
            f"  {vasp_command}",
            "  if grep -q 'reached required accuracy' OUTCAR 2>/dev/null; then",
            '    echo "snapshot $i OK"',
            "  else",
            '    echo "snapshot $i CHECK"',
            "  fi",
            '  cd "$ROOT"',
            "done",
        ]
    )


def _array_command(root: Path, digits: int, vasp_command: str) -> str:
    return "\n".join(
        [
            f'ROOT="{root.as_posix()}"',
            f'i=$(printf "%0{digits}d" "${{SLURM_ARRAY_TASK_ID:?set --array}}")',
            'cd "$ROOT/$i" || { echo "missing snapshot $i"; exit 1; }',
            f"{vasp_command}",
            "if grep -q 'reached required accuracy' OUTCAR 2>/dev/null; then",
            '  echo "snapshot $i OK"',
            "else",
            '  echo "snapshot $i CHECK"',
            "fi",
        ]
    )


def plan_waverun(
    campaign: Campaign,
    *,
    chunk: int | None = None,
    span: tuple[int, int] | None = None,
    array: bool = False,
    array_throttle: int = 20,
) -> dict[str, Any]:
    root = campaign.stage_dir("snapshots")
    digits = int(campaign.snapshots["digits"])
    if not (root / "snapshots_manifest.json").is_file():
        raise SafetyError("Run `inamd snapshots prepare` first.")
    folders = _snapshot_folders(root, digits)
    if not folders:
        raise SafetyError(f"No snapshot folders under {root}")

    if span is not None:
        lo, hi = span
        folders = [f for f in folders if lo <= int(f) <= hi]
        if not folders:
            raise SafetyError(f"No snapshot folders in range {span}")

    profile = load_profile(campaign.profile_path)
    if "vasp_nac" not in profile["jobs"]:
        raise SafetyError("Scheduler profile has no 'vasp_nac' job")
    vasp_command = str(profile["jobs"]["vasp_nac"].get("command", "")).strip() or "vasp_gam"

    done = [f for f in folders if _converged(root / f)]
    todo = [f for f in folders if f not in set(done)]

    if array:
        jobs = [
            {
                "kind": "array",
                "name": f"{campaign.name}_waverun_array",
                "array": f"{int(folders[0])}-{int(folders[-1])}%{array_throttle}",
                "folders": [folders[0], folders[-1]],
            }
        ]
    else:
        size = chunk or len(folders)
        jobs = [
            {
                "kind": "chunk",
                "name": f"{campaign.name}_waverun_{c[0]}-{c[-1]}",
                "first": c[0],
                "last": c[-1],
                "folders": [c[0], c[-1]],
                "count": len(c),
            }
            for c in _chunks(folders, size)
        ]

    return {
        "stage": STAGE,
        "root": str(root),
        "vasp_command": vasp_command,
        "scheduler": profile["scheduler"],
        "folders_total": len(folders),
        "converged": len(done),
        "pending": len(todo),
        "mode": "array" if array else "chunk",
        "jobs": jobs,
    }


def launch_waverun(
    campaign: Campaign,
    *,
    chunk: int | None = None,
    span: tuple[int, int] | None = None,
    array: bool = False,
    array_throttle: int = 20,
    execute: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    root = campaign.stage_dir("snapshots")
    digits = int(campaign.snapshots["digits"])
    profile = load_profile(campaign.profile_path)
    planned = plan_waverun(campaign, chunk=chunk, span=span, array=array, array_throttle=array_throttle)
    vasp_command = planned["vasp_command"]

    rows: list[dict[str, Any]] = []
    scripts: list[str] = []
    for job in planned["jobs"]:
        if job["kind"] == "array":
            command = _array_command(root, digits, vasp_command)
            script = render_job(
                profile, "vasp_nac", command=command, job_name=job["name"],
                array=job["array"], working_directory=root.as_posix(),
            )
        else:
            command = _loop_command(root, job["first"], job["last"], digits, vasp_command)
            script = render_job(
                profile, "vasp_nac", command=command, job_name=job["name"],
                working_directory=root.as_posix(),
            )
        script_path = root / f"{job['name']}.sh"
        write_job(script_path, script, force=True)
        scripts.append(str(script_path))
        outcome = submit(profile, script_path, execute=execute)
        rows.append({"job": job["name"], "range": f"{job['folders'][0]}-{job['folders'][1]}", **outcome})

    manifest = write_manifest(
        root, STAGE,
        {
            "campaign": str(campaign.path), "root": str(root), "mode": planned["mode"],
            "vasp_command": vasp_command, "scripts": scripts, "jobs": rows,
        },
    )
    audit = audit_waverun(campaign)
    state = StateStore(campaign.root)
    state.event("waverun.launch", execute=execute, mode=planned["mode"], jobs=len(rows))
    state.artifact("waverun_manifest", manifest)
    return {
        "mode": "submitted" if execute else "dry-run",
        "root": str(root),
        "jobs": rows,
        "scripts": scripts,
        "manifest": str(manifest),
        "audit_status": audit["status"],
        "hint": None if execute else "review the generated *.sh, then re-run with --execute",
    }


def audit_waverun(campaign: Campaign) -> dict[str, Any]:
    root = campaign.stage_dir("snapshots")
    digits = int(campaign.snapshots["digits"])
    folders = _snapshot_folders(root, digits)
    rows: list[dict[str, Any]] = []
    for folder in folders:
        path = root / folder
        has_wavecar = (path / "WAVECAR").is_file() and (path / "WAVECAR").stat().st_size > 0
        if _converged(path):
            status, detail = ("PASS", "converged") if has_wavecar else ("WARN", "converged; WAVECAR missing (LWAVE?)")
        elif (path / "OUTCAR").is_file():
            status, detail = "WARN", "OUTCAR present; not converged / running"
        else:
            status, detail = "PENDING", "not started"
        rows.append({"status": status, "folder": folder, "detail": detail})

    status = rollup_status([r["status"] for r in rows]) if rows else "PENDING"
    audit = {
        "status": status,
        "root": str(root),
        "folders_total": len(folders),
        "converged": sum(r["status"] == "PASS" for r in rows),
        "running_or_incomplete": sum(r["status"] == "WARN" for r in rows),
        "not_started": sum(r["status"] == "PENDING" for r in rows),
        "runs": rows,
        "summary": f"{sum(r['status'] == 'PASS' for r in rows)}/{len(folders)} snapshots converged with WAVECAR",
    }
    write_audit(root, STAGE, audit, rows=rows)
    return audit


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _span(value: list[int] | None) -> tuple[int, int] | None:
    if not value:
        return None
    return int(value[0]), int(value[1])


def _cmd(args: argparse.Namespace) -> int:
    campaign = load_campaign(args.campaign)
    if args.waverun_command == "audit":
        _json(audit_waverun(campaign))
        return 0
    kwargs = dict(
        chunk=args.chunk,
        span=_span(args.range),
        array=args.array,
        array_throttle=args.throttle,
    )
    if args.waverun_command == "plan":
        _json(plan_waverun(campaign, **kwargs))
        return 0
    _json(launch_waverun(campaign, **kwargs, execute=args.execute, force=args.force))
    return 0


@register
def _register(commands: Any, add_campaign_option: Any) -> None:
    parser = commands.add_parser(STAGE, help="Run one WAVECAR/eigenvalue SCF per snapshot")
    sub = parser.add_subparsers(dest="waverun_command", required=True)
    for name, help_text in (
        ("plan", "Show the chunk/array job plan"),
        ("launch", "Render job scripts; submit only with --execute"),
        ("audit", "Re-check per-snapshot convergence"),
    ):
        p = sub.add_parser(name, help=help_text)
        add_campaign_option(p)
        if name != "audit":
            p.add_argument("--chunk", type=int, help="Folders per chunk job (default: one job over all)")
            p.add_argument("--range", nargs=2, type=int, metavar=("FIRST", "LAST"), help="Restrict to a folder range")
            p.add_argument("--array", action="store_true", help="Emit a Slurm array (one task per folder) instead")
            p.add_argument("--throttle", type=int, default=20, help="Slurm array concurrency (%%N)")
        if name == "launch":
            p.add_argument("--execute", action="store_true")
            p.add_argument("--force", action="store_true")
        p.set_defaults(func=_cmd)
