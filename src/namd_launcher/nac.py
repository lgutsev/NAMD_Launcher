"""Stage 4 -- non-adiabatic couplings via CA-NAC.

CA-NAC (and VaspBandUnfolding) is a *dependency you install*, not vendored code
-- see ``third_party/README.md``. ``prepare`` renders ``input.py`` from the
campaign ``nac:`` block next to the snapshot folders (CA-NAC's
``Dirs = ['./001/', ...]`` resolve there) and resolves the CA-NAC / vaspwfc
locations. ``run`` submits ``python input.py`` under the ``canac`` job, with
those directories prepended to ``PYTHONPATH``. ``collect`` maps the text
outputs to the Hefei-NAMD input names:

    CAnac_*_re.txt  ->  nac/NATXT
    CAeig_*.txt     ->  nac/EIGTXT   and   nac/energy.dat   (dephasing input)
"""

from __future__ import annotations

import argparse
import shutil
from importlib import resources
from pathlib import Path
from typing import Any

from ._deps import pythonpath_prefix, resolve_canac, resolve_vaspwfc
from ._run import submit
from ._stage import rollup_status, write_audit, write_manifest
from ._template import python_bool, render
from .cli import _json, register
from .config import Campaign, load_campaign, load_profile
from .errors import SafetyError
from .state import StateStore

STAGE = "nac"


def _require(campaign: Campaign, *keys: str) -> dict[str, Any]:
    nac = campaign.nac
    missing = [k for k in keys if nac.get(k) is None]
    if missing:
        raise SafetyError(f"campaign nac: block needs {', '.join(missing)}")
    return nac


def render_input_py(campaign: Campaign) -> str:
    nac = _require(campaign, "bmin", "bmax", "bmin_stored", "bmax_stored")
    nsw = int(campaign.snapshots["nsw"])
    potim = float(nac.get("potim", campaign.snapshots["potim"]))
    tmpl = resources.files("namd_launcher").joinpath("templates/canac_input.py.tmpl").read_text(encoding="utf-8")
    return render(
        tmpl,
        {
            "T_START": 1,
            "T_END": nsw,
            "IFORMAT": nac["iformat"],
            "BMIN": nac["bmin"],
            "BMAX": nac["bmax"],
            "POTIM": potim,
            "BMIN_STORED": nac["bmin_stored"],
            "BMAX_STORED": nac["bmax_stored"],
            "NPROC": int(nac["nproc"]),
            "IS_GAMMA": python_bool(bool(nac["gamma"])),
            "IS_REORDER": python_bool(bool(nac["is_reorder"])),
            "IS_ALLE": python_bool(bool(nac["is_alle"])),
            "IS_REAL": python_bool(bool(nac["is_real"])),
            "IKPT": int(nac["ikpt"]),
            "ISPIN": int(nac["ispin"]),
            "DIGITS": int(campaign.snapshots["digits"]),
            "ICOR": int(nac.get("icor", 1)),
        },
    )


def prepare_nac(campaign: Campaign, *, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
    if campaign.nac["engine"] != "ca-nac":
        raise SafetyError(f"nac.engine is {campaign.nac['engine']!r}; the supported production engine is ca-nac.")
    snap_root = campaign.stage_dir("snapshots")
    nac_root = campaign.stage_dir(STAGE)
    if not (snap_root / "snapshots_manifest.json").is_file():
        raise SafetyError("Run `inamd snapshots prepare` (and `inamd waverun`) first.")

    input_py = render_input_py(campaign)
    canac = resolve_canac(campaign.nac)
    vaspwfc = resolve_vaspwfc(campaign.nac)
    plan = {
        "stage": STAGE,
        "campaign": str(campaign.path),
        "run_dir": str(snap_root),
        "collect_dir": str(nac_root),
        "canac": canac,
        "vaspwfc": vaspwfc,
        "bmin": campaign.nac["bmin"],
        "bmax": campaign.nac["bmax"],
        "nbasis_out": campaign.nac["bmax"] - campaign.nac["bmin"] + 1,
        "nsw": int(campaign.snapshots["nsw"]),
        "iformat": campaign.nac["iformat"],
    }
    if dry_run:
        return {"mode": "dry-run", **plan, "input_py_preview": input_py}

    if (snap_root / "input.py").exists() and not force:
        raise SafetyError(f"{snap_root / 'input.py'} already exists; re-run with --force.")

    (snap_root / "input.py").write_text(input_py, encoding="utf-8")

    nac_root.mkdir(parents=True, exist_ok=True)
    manifest = write_manifest(nac_root, STAGE, plan)
    audit = audit_nac(campaign)
    state = StateStore(campaign.root)
    state.event("nac.prepare", run_dir=str(snap_root), nsw=plan["nsw"], canac_found=canac["found"])
    state.artifact("nac_manifest", manifest)
    return {"mode": "prepared", **plan, "manifest": str(manifest), "audit_status": audit["status"]}


def run_nac(campaign: Campaign, *, execute: bool = False, allow_missing: bool = False) -> dict[str, Any]:
    snap_root = campaign.stage_dir("snapshots")
    if not (snap_root / "input.py").is_file():
        raise SafetyError("Run `inamd nac prepare` first.")
    profile = load_profile(campaign.profile_path)
    if "canac" not in profile["jobs"]:
        raise SafetyError("Scheduler profile has no 'canac' job")
    from ._compat import render_job, write_job

    canac = resolve_canac(campaign.nac)
    vaspwfc = resolve_vaspwfc(campaign.nac)
    if not canac["found"] and not allow_missing:
        raise SafetyError(
            f"CA-NAC not found ({canac['hint']}). The `canac` job may still provide it "
            "at runtime -- pass --allow-missing to build the script anyway."
        )

    base_command = str(profile["jobs"]["canac"].get("command", "")).strip() or "python input.py"
    prefix = [Path(p).as_posix() for p in pythonpath_prefix(canac, vaspwfc)]
    if prefix:
        joined = ":".join(prefix)
        command = f'export PYTHONPATH="{joined}:${{PYTHONPATH:-}}"\n{base_command}'
    else:
        command = (
            "# CA-NAC / VaspBandUnfolding must be importable here -- set PYTHONPATH\n"
            "# or CANAC_ACTIVATE_SCRIPT in the `canac` job.\n"
            f"{base_command}"
        )
    script = render_job(
        profile, "canac", command=command,
        job_name=f"{campaign.name}_canac", working_directory=snap_root.as_posix(),
    )
    script_path = snap_root / "run_canac.sh"
    write_job(script_path, script, force=True)
    outcome = submit(profile, script_path, execute=execute)
    logged = {k: v for k, v in outcome.items() if k not in ("stdout_tail", "stderr_tail")}
    StateStore(campaign.root).event("nac.run", execute=execute, canac=canac["how"], **logged)
    return {
        "mode": "submitted" if execute else "dry-run",
        "script": str(script_path),
        "canac": canac,
        "vaspwfc": vaspwfc,
        **outcome,
    }


def _newest(root: Path, pattern: str) -> Path | None:
    hits = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


def _count_columns(path: Path) -> int:
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip():
            return len(line.split())
    return 0


def collect_nac(campaign: Campaign, *, force: bool = False) -> dict[str, Any]:
    snap_root = campaign.stage_dir("snapshots")
    nac_root = campaign.stage_dir(STAGE)
    nac_re = _newest(snap_root, "CAnac_*_re.txt")
    caeig = _newest(snap_root, "CAeig_*.txt")
    if nac_re is None or caeig is None:
        raise SafetyError(
            f"No CA-NAC outputs in {snap_root} (need CAnac_*_re.txt and CAeig_*.txt). "
            "Has the `canac` job finished?"
        )
    nac_root.mkdir(parents=True, exist_ok=True)
    targets = {"NATXT": nac_re, "EIGTXT": caeig, "energy.dat": caeig}
    for name, source in targets.items():
        dest = nac_root / name
        if dest.exists() and not force:
            raise SafetyError(f"{dest} already exists; re-run with --force.")
        shutil.copy2(source, dest)

    nbasis = campaign.nac["bmax"] - campaign.nac["bmin"] + 1
    nat_cols = _count_columns(nac_root / "NATXT")
    eig_cols = _count_columns(nac_root / "EIGTXT")
    payload = {
        "stage": STAGE,
        "sources": {"NATXT": str(nac_re), "EIGTXT": str(caeig)},
        "expected_nbasis": nbasis,
        "natxt_columns": nat_cols,
        "eigtxt_columns": eig_cols,
        "natxt_rows": sum(1 for _ in (nac_root / "NATXT").open()),
        "eigtxt_rows": sum(1 for _ in (nac_root / "EIGTXT").open()),
    }
    manifest = write_manifest(nac_root, STAGE, {**payload, "collected": True})
    audit = audit_nac(campaign)
    state = StateStore(campaign.root)
    state.event("nac.collect", **payload)
    for name in ("NATXT", "EIGTXT"):
        state.artifact(f"nac_{name}", nac_root / name)
    state.artifact("nac_manifest", manifest)
    return {"mode": "collected", **payload, "manifest": str(manifest), "audit_status": audit["status"]}


def audit_nac(campaign: Campaign) -> dict[str, Any]:
    nac_root = campaign.stage_dir(STAGE)
    nbasis = None
    if campaign.nac.get("bmin") is not None and campaign.nac.get("bmax") is not None:
        nbasis = campaign.nac["bmax"] - campaign.nac["bmin"] + 1

    rows: list[dict[str, Any]] = []
    prepared = (nac_root / "nac_manifest.json").is_file()
    canac = resolve_canac(campaign.nac) if prepared else None

    for name in ("NATXT", "EIGTXT", "energy.dat"):
        path = nac_root / name
        if not path.is_file() or not path.stat().st_size:
            rows.append({"status": "PENDING", "file": name, "detail": "not collected yet"})
            continue
        cols = _count_columns(path)
        status, detail = "PASS", f"{cols} columns"
        if nbasis is not None:
            expect = nbasis * nbasis if name == "NATXT" else nbasis
            if cols != expect:
                status, detail = "FAIL", f"{cols} columns, expected {expect} for nbasis={nbasis}"
        rows.append({"status": status, "file": name, "detail": detail})

    present = [r for r in rows if r["status"] != "PENDING"]
    if present:
        nat = next((r for r in rows if r["file"] == "NATXT"), None)
        eig = next((r for r in rows if r["file"] == "EIGTXT"), None)
        if nat and eig and nat["status"] != "PENDING" and eig["status"] != "PENDING":
            nrows = sum(1 for _ in (nac_root / "NATXT").open())
            erows = sum(1 for _ in (nac_root / "EIGTXT").open())
            if nrows != erows:
                rows.append(
                    {"status": "FAIL", "file": "<consistency>", "detail": f"NATXT {nrows} rows vs EIGTXT {erows} rows"}
                )

    status = rollup_status([r["status"] for r in rows]) if rows else "PENDING"
    summary = "NATXT / EIGTXT / energy.dat " + (
        "ready" if status == "PASS" else "not ready" if status != "FAIL" else "inconsistent"
    )
    if canac is not None and not canac["found"] and status in {"PENDING", "PASS"}:
        summary += f"  (note: CA-NAC install not resolved -- {canac['how']}; needed for `inamd nac run`)"
    audit = {
        "status": status,
        "root": str(nac_root),
        "expected_nbasis": nbasis,
        "canac_install": canac,
        "runs": rows,
        "summary": summary,
    }
    write_audit(nac_root, STAGE, audit, rows=rows)
    return audit


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _cmd(args: argparse.Namespace) -> int:
    campaign = load_campaign(args.campaign)
    cmd = args.nac_command
    if cmd == "prepare":
        _json(prepare_nac(campaign, dry_run=args.dry_run, force=args.force))
    elif cmd == "run":
        _json(run_nac(campaign, execute=args.execute, allow_missing=args.allow_missing))
    elif cmd == "collect":
        _json(collect_nac(campaign, force=args.force))
    else:
        _json(audit_nac(campaign))
    return 0


@register
def _register(commands: Any, add_campaign_option: Any) -> None:
    parser = commands.add_parser(STAGE, help="CA-NAC non-adiabatic couplings + eigenvalues")
    sub = parser.add_subparsers(dest="nac_command", required=True)
    prepare = sub.add_parser("prepare", help="Render input.py; resolve the CA-NAC / vaspwfc install")
    add_campaign_option(prepare)
    prepare.add_argument("--dry-run", action="store_true")
    prepare.add_argument("--force", action="store_true")
    prepare.set_defaults(func=_cmd)
    run = sub.add_parser("run", help="Submit `python input.py` under the canac job")
    add_campaign_option(run)
    run.add_argument("--execute", action="store_true")
    run.add_argument(
        "--allow-missing",
        action="store_true",
        help="build the job script even if CA-NAC is not resolvable here (the compute env may provide it)",
    )
    run.set_defaults(func=_cmd)
    collect = sub.add_parser("collect", help="Map CAnac_*/CAeig_* to NATXT / EIGTXT / energy.dat")
    add_campaign_option(collect)
    collect.add_argument("--force", action="store_true")
    collect.set_defaults(func=_cmd)
    audit = sub.add_parser("audit", help="Check collected NAC inputs")
    add_campaign_option(audit)
    audit.set_defaults(func=_cmd)
