"""Stage 4 -- non-adiabatic couplings via CA-NAC.

``prepare`` renders ``input.py`` (from the campaign ``nac:`` block) and drops
the CA-NAC driver next to the snapshot folders -- CA-NAC's ``Dirs = ['./001/',
...]`` are resolved relative to that directory, exactly as in the original
workflow. ``run`` submits ``python input.py`` under the ``canac`` job.
``collect`` maps CA-NAC's text outputs to the Hefei-NAMD input names:

    CAnac_*_re.txt  ->  nac/NATXT
    CAeig_*.txt     ->  nac/EIGTXT   and   nac/energy.dat   (dephasing input)
"""

from __future__ import annotations

import argparse
import shutil
from importlib import resources
from pathlib import Path
from typing import Any

from ._run import submit
from ._stage import rollup_status, write_audit, write_manifest
from ._template import python_bool, render
from .cli import _json, register
from .config import Campaign, load_campaign, load_profile
from .errors import SafetyError
from .state import StateStore

STAGE = "nac"
_CANAC_LIBS = ("CAnac.py", "aeolap.py", "mod_hungarian.py")
_THIRD_PARTY = Path(__file__).resolve().parents[2] / "third_party" / "ca_nac"


def _require(campaign: Campaign, *keys: str) -> dict[str, Any]:
    nac = campaign.nac
    missing = [k for k in keys if nac.get(k) is None]
    if missing:
        raise SafetyError(f"campaign nac: block needs {', '.join(missing)}")
    return nac


def _canac_lib_dir() -> Path:
    """Where CAnac.py etc. live (repo checkout, or fall back to packaged copy)."""

    if (_THIRD_PARTY / "CAnac.py").is_file():
        return _THIRD_PARTY
    raise SafetyError(
        "CA-NAC driver not found under third_party/ca_nac/. This is a source "
        "checkout requirement; see third_party/README.md."
    )


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
        raise SafetyError(f"nac.engine is {campaign.nac['engine']!r}; `inamd nac` handles ca-nac (see `inamd n2amd`).")
    snap_root = campaign.stage_dir("snapshots")
    nac_root = campaign.stage_dir(STAGE)
    if not (snap_root / "snapshots_manifest.json").is_file():
        raise SafetyError("Run `inamd snapshots prepare` (and `inamd waverun`) first.")

    input_py = render_input_py(campaign)
    lib_dir = _canac_lib_dir()
    plan = {
        "stage": STAGE,
        "campaign": str(campaign.path),
        "run_dir": str(snap_root),
        "collect_dir": str(nac_root),
        "driver_source": str(lib_dir),
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
    copied = []
    for name in _CANAC_LIBS:
        shutil.copy2(lib_dir / name, snap_root / name)
        copied.append(name)

    nac_root.mkdir(parents=True, exist_ok=True)
    manifest = write_manifest(nac_root, STAGE, {**plan, "canac_libs": copied})
    audit = audit_nac(campaign)
    state = StateStore(campaign.root)
    state.event("nac.prepare", run_dir=str(snap_root), nsw=plan["nsw"])
    state.artifact("nac_manifest", manifest)
    return {
        "mode": "prepared",
        **plan,
        "canac_libs": copied,
        "manifest": str(manifest),
        "audit_status": audit["status"],
    }


def run_nac(campaign: Campaign, *, execute: bool = False) -> dict[str, Any]:
    snap_root = campaign.stage_dir("snapshots")
    if not (snap_root / "input.py").is_file():
        raise SafetyError("Run `inamd nac prepare` first.")
    profile = load_profile(campaign.profile_path)
    if "canac" not in profile["jobs"]:
        raise SafetyError("Scheduler profile has no 'canac' job")
    from ._compat import render_job, write_job

    script = render_job(
        profile, "canac",
        command=str(profile["jobs"]["canac"].get("command", "")).strip() or "python input.py",
        job_name=f"{campaign.name}_canac", working_directory=snap_root.as_posix(),
    )
    script_path = snap_root / "run_canac.sh"
    write_job(script_path, script, force=True)
    outcome = submit(profile, script_path, execute=execute)
    logged = {k: v for k, v in outcome.items() if k not in ("stdout_tail", "stderr_tail")}
    StateStore(campaign.root).event("nac.run", execute=execute, **logged)
    return {"mode": "submitted" if execute else "dry-run", "script": str(script_path), **outcome}


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
    audit = {
        "status": status,
        "root": str(nac_root),
        "expected_nbasis": nbasis,
        "runs": rows,
        "summary": "NATXT / EIGTXT / energy.dat "
        + ("ready" if status == "PASS" else "not ready" if status != "FAIL" else "inconsistent"),
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
        _json(run_nac(campaign, execute=args.execute))
    elif cmd == "collect":
        _json(collect_nac(campaign, force=args.force))
    else:
        _json(audit_nac(campaign))
    return 0


@register
def _register(commands: Any, add_campaign_option: Any) -> None:
    parser = commands.add_parser(STAGE, help="CA-NAC non-adiabatic couplings + eigenvalues")
    sub = parser.add_subparsers(dest="nac_command", required=True)
    prepare = sub.add_parser("prepare", help="Render input.py and stage the CA-NAC driver")
    add_campaign_option(prepare)
    prepare.add_argument("--dry-run", action="store_true")
    prepare.add_argument("--force", action="store_true")
    prepare.set_defaults(func=_cmd)
    run = sub.add_parser("run", help="Submit `python input.py` under the canac job")
    add_campaign_option(run)
    run.add_argument("--execute", action="store_true")
    run.set_defaults(func=_cmd)
    collect = sub.add_parser("collect", help="Map CAnac_*/CAeig_* to NATXT / EIGTXT / energy.dat")
    add_campaign_option(collect)
    collect.add_argument("--force", action="store_true")
    collect.set_defaults(func=_cmd)
    audit = sub.add_parser("audit", help="Check collected NAC inputs")
    add_campaign_option(audit)
    audit.set_defaults(func=_cmd)
