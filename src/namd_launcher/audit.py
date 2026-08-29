"""``inamd audit`` / ``inamd status`` / ``inamd run`` -- whole-campaign views.

Each stage already writes its own ``*_audit.json``; this module just calls the
stage audit functions in dependency order and rolls the results up, the way
``iface status`` does for an InterfaceForge campaign.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from .cli import _json, register
from .config import Campaign, load_campaign

# stage key -> (audit callable, next-step hint)
_STAGE_AUDITS: dict[str, tuple[str, str]] = {
    "snapshots": ("namd_launcher.snapshots:audit_snapshots", "inamd snapshots prepare"),
    "waverun": ("namd_launcher.waverun:audit_waverun", "inamd waverun launch --execute"),
    "ksplot": ("namd_launcher.ksplot:audit_ksplot", "inamd ksplot"),
    "nac": ("namd_launcher.nac:audit_nac", "inamd nac prepare / run --execute / collect"),
    "dephase": ("namd_launcher.dephase:audit_dephase", "inamd dephase"),
    "inicon": ("namd_launcher.inicon:audit_inicon", "inamd inicon"),
    "hefei": ("namd_launcher.hefeinamd:audit_hefei", "inamd hefei prepare / launch --execute"),
    "shprop": ("namd_launcher.shprop:audit_shprop", "inamd shprop"),
}


def _resolve(dotted: str) -> Callable[[Campaign], dict[str, Any]]:
    module_name, func_name = dotted.split(":")
    module = __import__(module_name, fromlist=[func_name])
    return getattr(module, func_name)


def _overall(statuses) -> str:
    """Whole-campaign verdict -- not a simple max: PASS only when every stage does."""

    seen = list(statuses)
    if "ERROR" in seen:
        return "ERROR"
    if "FAIL" in seen:
        return "FAIL"
    if "WARN" in seen:
        return "WARN"
    if all(s == "PASS" for s in seen):
        return "PASS"
    if any(s == "PASS" for s in seen):
        return "IN_PROGRESS"
    return "PENDING"


def campaign_audit(campaign: Campaign) -> dict[str, Any]:
    stages: list[dict[str, Any]] = []
    for key, (dotted, hint) in _STAGE_AUDITS.items():
        try:
            result = _resolve(dotted)(campaign)
        except Exception as exc:  # noqa: BLE001 -- a broken stage should not hide the rest
            result = {"status": "ERROR", "summary": f"{type(exc).__name__}: {exc}"}
        stages.append(
            {
                "stage": key,
                "status": result.get("status", "PENDING"),
                "summary": result.get("summary", ""),
                "next": hint,
            }
        )
    overall = _overall(s["status"] for s in stages)
    return {
        "schema_version": 1,
        "project": campaign.name,
        "campaign_file": str(campaign.path),
        "status": overall,
        "stages": stages,
    }


def _cmd_audit(args: argparse.Namespace) -> int:
    _json(campaign_audit(load_campaign(args.campaign)))
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    report = campaign_audit(load_campaign(args.campaign))
    print(f"{report['project']}  [{report['status']}]")
    for stage in report["stages"]:
        print(f"  {stage['stage']:<10} {stage['status']:<8} {stage['summary']}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    """Advance every ready *local* stage; never submit a cluster job."""

    campaign = load_campaign(args.campaign)
    from .dephase import run_dephase
    from .hefeinamd import prepare_hefei
    from .inicon import generate_inicon
    from .ksplot import run_ksplot
    from .nac import prepare_nac
    from .shprop import run_shprop
    from .snapshots import prepare_snapshots

    local_steps: list[tuple[str, Callable[[], dict[str, Any]]]] = [
        ("snapshots", lambda: prepare_snapshots(campaign, force=args.force)),
        ("nac.prepare", lambda: prepare_nac(campaign, force=args.force)),
        ("dephase", lambda: run_dephase(campaign, force=args.force)),
        ("inicon", lambda: generate_inicon(campaign, force=args.force)),
        ("hefei.prepare", lambda: prepare_hefei(campaign, force=args.force)),
        ("shprop", lambda: run_shprop(campaign, force=args.force)),
        ("ksplot", lambda: run_ksplot(campaign, no_plot=args.no_plot, force=args.force)),
    ]
    done: list[dict[str, Any]] = []
    for name, fn in local_steps:
        if not args.execute:
            done.append({"step": name, "status": "would-run"})
            continue
        try:
            result = fn()
            done.append({"step": name, "status": result.get("status", result.get("mode", "ok"))})
        except Exception as exc:  # noqa: BLE001
            done.append({"step": name, "status": "blocked", "reason": str(exc)})
    _json(
        {
            "mode": "executed-local" if args.execute else "dry-run",
            "note": "cluster jobs (waverun, nac run, hefei launch) are never submitted by `run`; "
            "do those explicitly with --execute on the stage command",
            "steps": done,
            "audit": campaign_audit(campaign),
        }
    )
    return 0


@register
def _register(commands: Any, add_campaign_option: Any) -> None:
    audit = commands.add_parser("audit", help="Roll up every stage audit for the campaign")
    add_campaign_option(audit)
    audit.set_defaults(func=_cmd_audit)

    status = commands.add_parser("status", help="One-line-per-stage campaign status")
    add_campaign_option(status)
    status.set_defaults(func=_cmd_status)

    run = commands.add_parser(
        "run", help="Advance every ready local stage (never submits cluster jobs)"
    )
    add_campaign_option(run)
    run.add_argument("--execute", action="store_true", help="actually run the local stages")
    run.add_argument("--force", action="store_true")
    run.add_argument("--no-plot", action="store_true")
    run.set_defaults(func=_cmd_run)
