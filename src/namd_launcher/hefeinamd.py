"""Stage 6 -- render ``inp`` and launch Hefei-NAMD surface hopping.

Two input dialects are supported:

* ``--branch dev``  -> the Hefei-NAMD-DEV binary ``hfnamd``; ``&NAMDPARA`` uses
  ``ALGO = "DISH"|"FSSH"``, ``ALGO_INT``, ``LSHP``, ``LCPTXT``, ``DEBUGLEVEL``
  (this is what the source workflow uses; templates ``inp.dish`` / ``inp.fssh``).
* ``--branch master`` -> the upstream ``dish`` / ``namd`` binaries; ``&NAMDPARA``
  uses ``LDISH`` + ``DIINIT`` (DISH) or ``LSHP`` (FSSH), and needs ``NBANDS``.

Hefei-NAMD reads ``EIGTXT`` (eigenvalues), ``NATXT`` (NAC), ``INICON`` (initial
conditions) and -- for DISH -- ``DEPHTIME``. These are staged into ``namd/``
from the ``nac/`` stage and cross-checked against the band window.
"""

from __future__ import annotations

import argparse
import shlex
import shutil
from importlib import resources
from pathlib import Path
from typing import Any

from ._compat import render_job, write_job
from ._deps import resolve_hefei_binary
from ._run import submit
from ._stage import rollup_status, write_audit, write_manifest
from ._template import fortran_bool, render
from .cli import _json, register
from .config import Campaign, load_campaign, load_profile
from .errors import SafetyError
from .state import StateStore

STAGE = "hefei"
_BINARY = {"dev": "hfnamd", "master": {"DISH": "dish", "FSSH": "namd"}}


def _count_rows(path: Path) -> int:
    return sum(1 for line in path.open() if line.strip())


def _table_shape(path: Path) -> tuple[int, int] | None:
    rows = [line.split() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
    if not rows:
        return (0, 0)
    widths = {len(row) for row in rows}
    if len(widths) != 1:
        return None
    return len(rows), widths.pop()


def _validate_inicon_rows(campaign: Campaign, path: Path, frames: int) -> list[str]:
    issues: list[str] = []
    parsed: list[tuple[int, int]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split()
        try:
            if len(fields) != 2:
                raise ValueError
            parsed.append((int(fields[0]), int(fields[1])))
        except ValueError:
            issues.append(f"INICON line {lineno} must contain exactly two integers: <start step> <start band>")

    nsample = int(campaign.namd["nsample"])
    if len(parsed) != nsample:
        issues.append(f"INICON has {len(parsed)} rows, expected exactly namd.nsample={nsample}")

    bmin, bmax = int(campaign.namd["bmin"]), int(campaign.namd["bmax"])
    algo = campaign.namd["algo"]
    namdtime = int(campaign.namd["namdtime"])
    for index, (start, band) in enumerate(parsed, start=1):
        if not bmin <= band <= bmax:
            issues.append(f"INICON row {index}: band {band} is outside active window [{bmin}, {bmax}]")
        if not 1 <= start <= frames:
            issues.append(f"INICON row {index}: start step {start} is outside available frames [1, {frames}]")
        if algo == "FSSH":
            if start <= 1:
                issues.append(f"INICON row {index}: FSSH start step must be greater than 1")
            if start + namdtime - 1 > int(campaign.namd["nsw"]):
                issues.append(
                    f"INICON row {index}: FSSH start {start} + NAMDTIME {namdtime} exceeds NSW "
                    f"{campaign.namd['nsw']}"
                )
    return issues


def render_inp(campaign: Campaign) -> tuple[str, dict[str, Any]]:
    namd = campaign.namd
    for key in ("bmin", "bmax", "nsw", "nsample", "ntraj", "nelm", "namdtime"):
        if namd.get(key) is None:
            raise SafetyError(f"campaign namd: block needs {key}")
    bmin, bmax = int(namd["bmin"]), int(namd["bmax"])
    nbasis = bmax - bmin + 1
    potim = float(namd.get("potim", campaign.nac.get("potim", campaign.snapshots["potim"])))
    temp = float(namd.get("temp", 300.0))
    algo = namd["algo"]
    branch = namd["branch"]
    meta = {"branch": branch, "algo": algo, "nbasis": nbasis}

    if branch == "dev":
        tmpl_name = "inp.dish" if algo == "DISH" else "inp.fssh"
        tmpl = resources.files("namd_launcher").joinpath(f"templates/{tmpl_name}").read_text(encoding="utf-8")
        text = render(
            tmpl,
            {
                "BMIN": bmin,
                "BMAX": bmax,
                "NSAMPLE": int(namd["nsample"]),
                "NTRAJ": int(namd["ntraj"]),
                "NSW": int(namd["nsw"]),
                "NELM": int(namd["nelm"]),
                "TEMP": f"{temp:g}",
                "NAMDTIME": int(namd["namdtime"]),
                "POTIM": f"{potim:g}",
                "ALGO_INT": int(namd.get("algo_int", 0)),
                "LHOLE": fortran_bool(bool(namd["lhole"])),
                "LSHP": fortran_bool(bool(namd["lshp"])),
                "LCPTXT": fortran_bool(bool(namd["lcptxt"])),
                "DEBUGLEVEL": str(namd.get("debuglevel", "I")),
            },
        )
        meta["binary"] = _BINARY["dev"]
        return text, meta

    # master branch: build the namelist explicitly
    nbands = namd.get("nbands") or campaign.bands.get("nbands")
    if nbands is None:
        raise SafetyError("master branch needs NBANDS (set namd.nbands or bands.nbands)")
    lines = [
        "&NAMDPARA",
        f"  BMIN     = {bmin}",
        f"  BMAX     = {bmax}",
        f"  NBANDS   = {int(nbands)}",
        f"  NSW      = {int(namd['nsw'])}",
        f"  POTIM    = {potim:g}",
        f"  NTRAJ    = {int(namd['ntraj'])}",
        f"  NELM     = {int(namd['nelm'])}",
        f"  TEMP     = {temp:g}",
        f"  NAMDTIME = {int(namd['namdtime'])}",
        f"  NSAMPLE  = {int(namd['nsample'])}",
        f"  LHOLE    = {fortran_bool(bool(namd['lhole']))}",
        f"  LCPEXT   = {fortran_bool(bool(namd['lcptxt']))}",
        f'  RUNDIR   = "{namd.get("rundir", ".")}"',
        '  TBINIT   = "INICON"',
    ]
    if algo == "DISH":
        lines += ["  LDISH    = .TRUE.", '  DIINIT   = "DEPHTIME"', f"  REALTIME = {int(namd['namdtime'])}"]
    else:
        lines += [f"  LSHP     = {fortran_bool(bool(namd['lshp']))}"]
    lines.append("/")
    meta["binary"] = _BINARY["master"][algo]
    meta["nbands"] = int(nbands)
    return "\n".join(lines) + "\n", meta


def _validate_inputs(campaign: Campaign, namd_root: Path, nac_root: Path, meta: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    nbasis = meta["nbasis"]
    natxt, eigtxt = nac_root / "NATXT", nac_root / "EIGTXT"
    for name, path in (("NATXT", natxt), ("EIGTXT", eigtxt), ("INICON", nac_root / "INICON")):
        if not path.is_file() or not path.stat().st_size:
            issues.append(f"{name} missing in {nac_root}")
    if meta["algo"] == "DISH" and not (nac_root / "DEPHTIME").is_file():
        issues.append("DISH needs DEPHTIME (run `inamd dephase`)")

    if not issues:
        nat_shape = _table_shape(natxt)
        eig_shape = _table_shape(eigtxt)
        if nat_shape is None:
            issues.append("NATXT has inconsistent row widths")
        elif nat_shape[1] != nbasis * nbasis:
            issues.append(f"NATXT has {nat_shape[1]} columns, expected nbasis^2 = {nbasis * nbasis}")
        if eig_shape is None:
            issues.append("EIGTXT has inconsistent row widths")
        elif eig_shape[1] != nbasis:
            issues.append(f"EIGTXT has {eig_shape[1]} columns, expected nbasis = {nbasis}")
        frames = eig_shape[0] if eig_shape is not None else _count_rows(eigtxt)
        if nat_shape is not None and eig_shape is not None and nat_shape[0] != eig_shape[0]:
            issues.append(f"NATXT has {nat_shape[0]} rows but EIGTXT has {eig_shape[0]} rows")
        if int(campaign.namd["nsw"]) > frames:
            issues.append(f"namd.nsw={campaign.namd['nsw']} exceeds {frames} NAC frames (EIGTXT rows)")
        issues.extend(_validate_inicon_rows(campaign, nac_root / "INICON", frames))
        if meta["algo"] == "DISH":
            shape = _table_shape(nac_root / "DEPHTIME")
            if shape is None:
                issues.append("DEPHTIME has inconsistent row widths")
            elif shape != (nbasis, nbasis):
                issues.append(f"DEPHTIME is {shape[0]}x{shape[1]}, expected {nbasis}x{nbasis}")
    return issues


def prepare_hefei(campaign: Campaign, *, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
    nac_root = campaign.stage_dir("nac")
    namd_root = campaign.stage_dir("namd")
    inp_text, meta = render_inp(campaign)

    plan = {
        "stage": STAGE,
        "campaign": str(campaign.path),
        "root": str(namd_root),
        "branch": meta["branch"],
        "algo": meta["algo"],
        "binary": meta["binary"],
        "nbasis": meta["nbasis"],
        "bmin": campaign.namd["bmin"],
        "bmax": campaign.namd["bmax"],
        "nsw": int(campaign.namd["nsw"]),
        "nsample": int(campaign.namd["nsample"]),
    }
    if dry_run:
        issues = _validate_inputs(campaign, namd_root, nac_root, meta) if nac_root.exists() else ["nac/ not prepared"]
        return {"mode": "dry-run", **plan, "inp_preview": inp_text, "input_issues": issues}

    issues = _validate_inputs(campaign, namd_root, nac_root, meta)
    if issues:
        raise SafetyError("Cannot prepare Hefei-NAMD inputs:\n  - " + "\n  - ".join(issues))
    if (namd_root / "inp").exists() and not force:
        raise SafetyError(f"{namd_root / 'inp'} already exists; re-run with --force.")

    namd_root.mkdir(parents=True, exist_ok=True)
    (namd_root / "inp").write_text(inp_text, encoding="utf-8")
    staged = ["inp"]
    wanted = ["NATXT", "EIGTXT", "INICON"] + (["DEPHTIME"] if meta["algo"] == "DISH" else [])
    for name in wanted:
        shutil.copy2(nac_root / name, namd_root / name)
        staged.append(name)

    manifest = write_manifest(namd_root, STAGE, {**plan, "staged": staged})
    audit = audit_hefei(campaign)
    state = StateStore(campaign.root)
    state.event("hefei.prepare", branch=meta["branch"], algo=meta["algo"], nbasis=meta["nbasis"])
    state.artifact("hefei_manifest", manifest)
    state.artifact("hefei_inp", namd_root / "inp")
    return {"mode": "prepared", **plan, "staged": staged, "manifest": str(manifest), "audit_status": audit["status"]}


def launch_hefei(campaign: Campaign, *, execute: bool = False) -> dict[str, Any]:
    namd_root = campaign.stage_dir("namd")
    if not (namd_root / "inp").is_file():
        raise SafetyError("Run `inamd hefei prepare` first.")
    profile = load_profile(campaign.profile_path)
    if "hefei_namd" not in profile["jobs"]:
        raise SafetyError("Scheduler profile has no 'hefei_namd' job")
    _, meta = render_inp(campaign)
    resolved = resolve_hefei_binary(meta["binary"], campaign.namd)
    default_command = str(profile["jobs"]["hefei_namd"].get("command", "")).strip()
    exe = resolved["path"] if (resolved["found"] and resolved["how"] != "PATH") else meta["binary"]
    exe = shlex.quote(str(exe))
    if default_command:
        command = default_command
    elif profile["scheduler"] == "local":
        command = exe
    else:
        command = f"mpirun -np {{ntasks}} {exe}"
    script = render_job(
        profile, "hefei_namd", command=command,
        job_name=f"{campaign.name}_namd", working_directory=namd_root.as_posix(),
    )
    script_path = namd_root / "run_namd.sh"
    write_job(script_path, script, force=True)
    outcome = submit(profile, script_path, execute=execute)
    logged = {k: v for k, v in outcome.items() if k not in ("stdout_tail", "stderr_tail")}
    StateStore(campaign.root).event("hefei.launch", execute=execute, binary=meta["binary"], **logged)
    return {
        "mode": "submitted" if execute else "dry-run",
        "binary": resolved,
        "script": str(script_path),
        **outcome,
    }


def audit_hefei(campaign: Campaign) -> dict[str, Any]:
    namd_root = campaign.stage_dir("namd")
    nac_root = campaign.stage_dir("nac")
    if not (namd_root / "inp").is_file():
        audit = {"status": "PENDING", "summary": "Hefei-NAMD inputs not prepared", "root": str(namd_root)}
        write_audit(namd_root, STAGE, audit)
        return audit

    _, meta = render_inp(campaign)
    rows: list[dict[str, Any]] = []
    wanted = ["inp", "NATXT", "EIGTXT", "INICON"] + (["DEPHTIME"] if meta["algo"] == "DISH" else [])
    for name in wanted:
        path = namd_root / name
        rows.append(
            {
                "status": "PASS" if path.is_file() and path.stat().st_size else "FAIL",
                "file": name,
                "detail": "" if path.is_file() else "missing",
            }
        )
    issues = _validate_inputs(campaign, namd_root, nac_root, meta) if nac_root.exists() else []
    for issue in issues:
        rows.append({"status": "FAIL", "file": "<consistency>", "detail": issue})

    shprop = sorted(namd_root.glob("SHPROP.*"))
    if shprop or (namd_root / "namd.out").is_file():
        nsample = int(campaign.namd["nsample"])
        rows.append(
            {
                "status": "PASS" if len(shprop) >= nsample else "WARN",
                "file": "SHPROP.*",
                "detail": f"{len(shprop)} of {nsample} present",
            }
        )

    binary = resolve_hefei_binary(meta["binary"], campaign.namd)
    status = rollup_status([r["status"] for r in rows]) if rows else "PENDING"
    summary = f"{sum(r['status'] == 'PASS' for r in rows)}/{len(rows)} checks pass; {len(shprop)} SHPROP files"
    if not binary["found"]:
        summary += f"  (note: {meta['binary']} not found -- {binary['hint']})"
    audit = {
        "status": status,
        "root": str(namd_root),
        "branch": meta["branch"],
        "algo": meta["algo"],
        "binary_install": binary,
        "shprop_files": len(shprop),
        "runs": rows,
        "summary": summary,
    }
    write_audit(namd_root, STAGE, audit, rows=rows)
    return audit


def _cmd(args: argparse.Namespace) -> int:
    campaign = load_campaign(args.campaign)
    cmd = args.hefei_command
    if cmd == "prepare":
        _json(prepare_hefei(campaign, dry_run=args.dry_run, force=args.force))
    elif cmd == "launch":
        _json(launch_hefei(campaign, execute=args.execute))
    else:
        _json(audit_hefei(campaign))
    return 0


@register
def _register(commands: Any, add_campaign_option: Any) -> None:
    parser = commands.add_parser(STAGE, help="Render `inp` and launch Hefei-NAMD surface hopping")
    sub = parser.add_subparsers(dest="hefei_command", required=True)
    prepare = sub.add_parser("prepare", help="Render inp and stage NATXT/EIGTXT/INICON/DEPHTIME")
    add_campaign_option(prepare)
    prepare.add_argument("--dry-run", action="store_true")
    prepare.add_argument("--force", action="store_true")
    prepare.set_defaults(func=_cmd)
    launch = sub.add_parser("launch", help="Submit the Hefei-NAMD job")
    add_campaign_option(launch)
    launch.add_argument("--execute", action="store_true")
    launch.set_defaults(func=_cmd)
    audit = sub.add_parser("audit", help="Check the prepared Hefei-NAMD inputs / SHPROP progress")
    add_campaign_option(audit)
    audit.set_defaults(func=_cmd)
