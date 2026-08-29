"""Command-line interface for NAMD Launcher (``inamd``).

Ergonomics deliberately match InterfaceForge's ``iface``: every subcommand
prints a single JSON object to stdout, errors go to stderr as ``ERROR: ...``
with exit code 2, mutating operations refuse to overwrite an existing output
tree, and launches are a dry run unless ``--execute`` is given.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from importlib import resources
from pathlib import Path
from typing import Any

from . import __version__
from .config import load_campaign
from .errors import NamdLauncherError

# Stage modules append their subparser registrars here (via @register) as they
# are imported by _load_stage_modules().
_SUBCOMMAND_REGISTRARS: list[Any] = []


def register(fn: Any) -> Any:
    """Decorator: a stage module registers ``fn(subparsers, add_campaign_option)``."""

    _SUBCOMMAND_REGISTRARS.append(fn)
    return fn


def _json(value: Any) -> None:
    print(json.dumps(value, indent=2, default=str))


def _campaign(args: argparse.Namespace):
    return load_campaign(args.campaign)


def _copy_template(name: str, destination: Path, *, force: bool) -> bool:
    if destination.exists() and not force:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = resources.files("namd_launcher").joinpath(f"templates/{name}").read_text(encoding="utf-8")
    destination.write_text(text, encoding="utf-8")
    return True


# --------------------------------------------------------------------------- #
# init / plan
# --------------------------------------------------------------------------- #
def cmd_init(args: argparse.Namespace) -> int:
    from .errors import SafetyError
    from .pipeline import scaffold_layout

    root = Path(args.directory).expanduser().resolve()
    if root.exists() and any(root.iterdir()) and not args.force:
        allowed = {"profiles", "structures", "inputs"}
        unexpected = [item.name for item in root.iterdir() if item.name not in allowed]
        if unexpected:
            raise SafetyError(f"Init directory is not empty: {root}. Use --force intentionally.")
    root.mkdir(parents=True, exist_ok=True)
    created = scaffold_layout(root)
    files = []
    if _copy_template("namd_campaign.yaml", root / "namd_campaign.yaml", force=args.force):
        files.append("namd_campaign.yaml")
    for name, dest in (
        ("profile_loni.yaml", root / "profiles" / "loni.yaml"),
        ("profile_local.yaml", root / "profiles" / "local.yaml"),
        ("potcar_pbe_54.yaml", root / "profiles" / "potcar_pbe_54.yaml"),
        ("INCAR.nac", root / "templates" / "INCAR.nac"),
    ):
        if _copy_template(name, dest, force=args.force):
            files.append(str(dest.relative_to(root)))
    _json(
        {
            "campaign_root": str(root),
            "campaign": str(root / "namd_campaign.yaml"),
            "directories_created": created,
            "files_written": files,
            "next": "edit namd_campaign.yaml + profiles/loni.yaml, then `inamd plan`",
        }
    )
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    from .pipeline import build_plan

    _json(build_plan(_campaign(args)))
    return 0


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def _add_campaign_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-c", "--campaign", default="namd_campaign.yaml")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inamd",
        description="Orchestrate the VASP -> CA-NAC -> Hefei-NAMD non-adiabatic dynamics workflow.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="Create a campaign skeleton")
    init.add_argument("directory", nargs="?", default=".")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    plan = commands.add_parser("plan", help="Validate the campaign and print the stage DAG")
    _add_campaign_option(plan)
    plan.set_defaults(func=cmd_plan)

    for registrar in _SUBCOMMAND_REGISTRARS:
        registrar(commands, _add_campaign_option)

    return parser


def _load_stage_modules() -> None:
    """Import stage modules so their @register'd subparsers attach."""

    for name in (
        "snapshots",
        "waverun",
        "nac",
        "dephase",
        "inicon",
        "hefeinamd",
        "shprop",
        "ksplot",
        "n2amd",
        "audit",
    ):
        try:
            __import__(f"namd_launcher.{name}")
        except ImportError:
            # A stage not present in this build simply omits its subcommand.
            pass


def main(argv: Sequence[str] | None = None) -> int:
    _load_stage_modules()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (NamdLauncherError, FileNotFoundError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
