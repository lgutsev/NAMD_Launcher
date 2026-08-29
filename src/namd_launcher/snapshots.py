"""Stage 1 -- slice an AIMD trajectory into per-snapshot WAVECAR folders.

Ports ``FolderPrep.py`` (last ``NSW`` frames of ``XDATCAR_FINAL`` -> ``001/POSCAR``
.. ``NSW/POSCAR``) and ``create_links.sh`` (link ``INCAR/KPOINTS/POTCAR`` from the
stage root into every snapshot folder).

Source may be an ``XDATCAR_FINAL`` file *or* an InterfaceForge Step2 run
directory -- in the latter case its ``XDATCAR``, ``KPOINTS``, ``POTCAR`` and
launcher are picked up directly.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from importlib import resources
from pathlib import Path
from typing import Any

from ._compat import parse_incar, update_incar
from ._nbands import choose_nbands, reference_nbands
from ._stage import rollup_status, write_audit, write_manifest
from ._xdatcar import read_xdatcar, write_poscar
from .cli import _json, register
from .config import Campaign, load_campaign
from .errors import SafetyError
from .state import StateStore

STAGE = "snapshots"
_LAUNCHERS = ("runvasp.sh", "run.slurm")


# --------------------------------------------------------------------------- #
# source resolution
# --------------------------------------------------------------------------- #
def resolve_source(campaign: Campaign) -> dict[str, Any]:
    raw = campaign.source["trajectory"]
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (campaign.root / path).resolve()

    inputs: dict[str, Path] = {}
    if path.is_dir():
        kind = "step2_run"
        reference_dir = path
        xdatcar = next((path / name for name in ("XDATCAR_FINAL", "XDATCAR") if (path / name).is_file()), None)
        if xdatcar is None:
            raise SafetyError(f"No XDATCAR_FINAL or XDATCAR in {path}")
        for name in ("KPOINTS", "POTCAR"):
            if (path / name).is_file():
                inputs[name] = path / name
        for name in _LAUNCHERS:
            if (path / name).is_file():
                inputs["launcher"] = path / name
                break
    elif path.is_file():
        kind = "xdatcar"
        xdatcar = path
        # The reference MD calc most likely lives next to the trajectory file.
        def _has_ref(base: Path) -> bool:
            return (base / "OUTCAR").is_file() or (base / "OUTCAR.gz").is_file() or (base / "INCAR").is_file()

        reference_dir = next((b for b in (path.parent, campaign.root) if _has_ref(b)), path.parent)
        for name in ("KPOINTS", "POTCAR"):
            for base in (path.parent, campaign.root):
                if (base / name).is_file():
                    inputs[name] = base / name
                    break
    else:
        raise SafetyError(f"source.trajectory does not exist: {path}")

    return {
        "kind": kind,
        "xdatcar": xdatcar,
        "inputs": inputs,
        "label": str(path),
        "reference_dir": str(reference_dir),
    }


def _resolve_incar(campaign: Campaign) -> tuple[Path, str]:
    ref = campaign.snapshots.get("incar")
    if ref:
        candidate = Path(ref).expanduser()
        if not candidate.is_absolute():
            candidate = (campaign.root / candidate).resolve()
        if candidate.is_file():
            return candidate, str(candidate)
        raise SafetyError(f"snapshots.incar not found: {candidate}")
    if (campaign.root / "INCAR").is_file():
        return campaign.root / "INCAR", str(campaign.root / "INCAR")
    packaged = resources.files("namd_launcher").joinpath("templates/INCAR.nac")
    return Path(str(packaged)), "packaged templates/INCAR.nac"


def _link_or_copy(source: Path, target: Path) -> str:
    if target.exists() or target.is_symlink():
        target.unlink()
    try:
        os.symlink(os.path.relpath(source, target.parent), target)
        return "link"
    except (OSError, NotImplementedError):
        shutil.copy2(source, target)
        return "copy"


# --------------------------------------------------------------------------- #
# prepare
# --------------------------------------------------------------------------- #
def prepare_snapshots(campaign: Campaign, *, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
    root = campaign.stage_dir(STAGE)
    src = resolve_source(campaign)
    traj = read_xdatcar(src["xdatcar"])

    nsw = int(campaign.snapshots["nsw"])
    stride = int(campaign.snapshots["stride"])
    digits = int(campaign.snapshots["digits"])
    link_names = list(campaign.snapshots["link_inputs"])

    available = list(range(0, len(traj), stride))
    if len(available) < nsw:
        raise SafetyError(
            f"Trajectory has {len(traj)} frames ({len(available)} at stride {stride}); "
            f"snapshots.nsw={nsw} requires at least that many."
        )
    selected = available[-nsw:]  # last NSW retained frames, in order (matches FolderPrep.py)

    incar_source, incar_label = _resolve_incar(campaign)
    kpoints_source = src["inputs"].get("KPOINTS")
    potcar_source = src["inputs"].get("POTCAR")
    launcher_source = src["inputs"].get("launcher")

    ref_nbands, ref_source = reference_nbands(Path(src["reference_dir"]))
    nbands = choose_nbands(campaign.bands, campaign.nac, ref_nbands=ref_nbands, ref_source=ref_source)

    folder_names = [f"{i + 1:0{digits}d}" for i in range(nsw)]
    plan = {
        "stage": STAGE,
        "campaign": str(campaign.path),
        "root": str(root),
        "source": src["label"],
        "source_kind": src["kind"],
        "reference_dir": src["reference_dir"],
        "trajectory_frames": len(traj),
        "n_ions": traj.n_ions,
        "species": traj.species,
        "counts": traj.counts,
        "nsw": nsw,
        "stride": stride,
        "first_folder": folder_names[0],
        "last_folder": folder_names[-1],
        "selected_frame_indices": [selected[0], selected[-1]],
        "incar_source": incar_label,
        "nbands": nbands,
        "kpoints_source": str(kpoints_source) if kpoints_source else None,
        "potcar_source": str(potcar_source) if potcar_source else None,
        "launcher_source": str(launcher_source) if launcher_source else None,
        "link_inputs": link_names,
    }

    if dry_run:
        return {"mode": "dry-run", **plan}

    for name, resolved in (("KPOINTS", kpoints_source), ("POTCAR", potcar_source)):
        if resolved is None and name in link_names:
            raise SafetyError(
                f"No {name} found next to the trajectory or in the campaign root. "
                f"Place a {name} there, or drop it from snapshots.link_inputs."
            )

    if (root / folder_names[0]).exists() and not force:
        raise SafetyError(
            f"{root / folder_names[0]} already exists. Re-run with --force, or remove the "
            f"snapshot folders first."
        )

    root.mkdir(parents=True, exist_ok=True)

    # Stage the shared inputs at the snapshot root.
    staged: dict[str, str] = {}
    incar_target = root / "INCAR"
    shutil.copy2(incar_source, incar_target)
    if nbands["nbands"]:
        update_incar(incar_target, {"NBANDS": int(nbands["nbands"])})
    staged["INCAR"] = str(incar_target)
    for name, source in (("KPOINTS", kpoints_source), ("POTCAR", potcar_source)):
        if source is not None:
            shutil.copy2(source, root / name)
            staged[name] = str(root / name)
    if launcher_source is not None:
        shutil.copy2(launcher_source, root / launcher_source.name)
        staged["launcher"] = str(root / launcher_source.name)

    # Write POSCARs + create links.
    link_modes: set[str] = set()
    for folder, frame_index in zip(folder_names, selected, strict=True):
        folder_path = root / folder
        folder_path.mkdir(parents=True, exist_ok=True)
        write_poscar(traj, frame_index, folder_path / "POSCAR", comment=f"{campaign.name} snapshot {folder}")
        for name in link_names:
            shared = root / name
            if shared.is_file():
                link_modes.add(_link_or_copy(shared, folder_path / name))

    manifest = write_manifest(
        root,
        STAGE,
        {**plan, "staged_inputs": staged, "link_mode": sorted(link_modes), "folders": folder_names},
    )
    audit = audit_snapshots(campaign)
    state = StateStore(campaign.root)
    state.event(
        "snapshots.prepare",
        source=src["label"],
        nsw=nsw,
        folders=len(folder_names),
        nbands=nbands["nbands"],
        nbands_reason=nbands["reason"],
    )
    state.artifact("snapshots_manifest", manifest)
    return {
        "mode": "prepared",
        **plan,
        "staged_inputs": staged,
        "link_mode": sorted(link_modes),
        "manifest": str(manifest),
        "audit_status": audit["status"],
    }


# --------------------------------------------------------------------------- #
# audit
# --------------------------------------------------------------------------- #
def audit_snapshots(campaign: Campaign) -> dict[str, Any]:
    root = campaign.stage_dir(STAGE)
    manifest_path = root / f"{STAGE}_manifest.json"
    if not manifest_path.is_file():
        audit = {"status": "PENDING", "summary": "snapshots not prepared yet", "root": str(root)}
        write_audit(root, STAGE, audit)
        return audit

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    folders: list[str] = manifest.get("folders", [])
    link_names = manifest.get("link_inputs", [])
    rows: list[dict[str, Any]] = []
    for folder in folders:
        folder_path = root / folder
        poscar = folder_path / "POSCAR"
        missing_links = [n for n in link_names if not (folder_path / n).exists()]
        status = "PASS"
        detail = ""
        if not poscar.is_file() or not poscar.stat().st_size:
            status = "FAIL"
            detail = "missing/empty POSCAR"
        elif missing_links:
            status = "FAIL"
            detail = f"missing linked input(s): {', '.join(missing_links)}"
        elif (folder_path / "WAVECAR").is_file():
            status = "WARN"
            detail = "WAVECAR already present (previous run?)"
        rows.append({"status": status, "folder": folder, "detail": detail})

    for name in ("INCAR", *(n for n in ("KPOINTS", "POTCAR") if n in link_names)):
        if not (root / name).is_file():
            rows.append(
                {"status": "FAIL", "folder": f"<root>/{name}", "detail": "shared input missing at snapshot root"}
            )

    # NBANDS check: what was decided, what is actually in the staged INCAR, and
    # whether it still covers CA-NAC's stored window.
    nb = manifest.get("nbands", {})
    staged_nbands = None
    if (root / "INCAR").is_file():
        value = parse_incar(root / "INCAR").get("NBANDS", "")
        staged_nbands = int(value.split()[0]) if value[:1].isdigit() else None
    requirement = nb.get("requirement")
    nb_status, nb_detail = "PASS", (
        f"NBANDS={staged_nbands} ({nb.get('reason', 'n/a')}); reference NBANDS={nb.get('reference_nbands')}"
    )
    if staged_nbands is None:
        nb_status = "WARN"
        nb_detail = "no explicit NBANDS in the staged INCAR; VASP will auto-choose (usually too few for NAMD)"
    elif requirement and staged_nbands < requirement:
        nb_status = "FAIL"
        nb_detail = f"staged NBANDS={staged_nbands} < required {requirement} (CA-NAC bmax_stored window)"
    elif nb.get("notes"):
        nb_status = "WARN"
        nb_detail += " -- " + "; ".join(nb["notes"])
    rows.append({"status": nb_status, "folder": "<root>/INCAR NBANDS", "detail": nb_detail})

    status = rollup_status([r["status"] for r in rows]) if rows else "PENDING"
    ok_folders = sum(r["status"] == "PASS" for r in rows if r["folder"] in folders)
    audit = {
        "status": status,
        "root": str(root),
        "folders_total": len(folders),
        "folders_ok": ok_folders,
        "nbands": {"chosen": staged_nbands, **nb},
        "runs": rows,
        "summary": f"{ok_folders}/{len(folders)} folders ready; NBANDS {staged_nbands} [{nb_status}]",
    }
    write_audit(root, STAGE, audit, rows=rows)
    return audit


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _cmd(args: argparse.Namespace) -> int:
    campaign = load_campaign(args.campaign)
    if args.snapshots_command == "audit":
        _json(audit_snapshots(campaign))
        return 0
    _json(prepare_snapshots(campaign, dry_run=args.dry_run, force=args.force))
    return 0


@register
def _register(commands: Any, add_campaign_option: Any) -> None:
    parser = commands.add_parser(STAGE, help="Slice the AIMD trajectory into snapshot WAVECAR folders")
    sub = parser.add_subparsers(dest="snapshots_command", required=True)
    prepare = sub.add_parser("prepare", help="Write 001..NSW/POSCAR and link INCAR/KPOINTS/POTCAR")
    add_campaign_option(prepare)
    prepare.add_argument("--dry-run", action="store_true")
    prepare.add_argument("--force", action="store_true")
    prepare.set_defaults(func=_cmd)
    audit = sub.add_parser("audit", help="Re-check the prepared snapshot folders")
    add_campaign_option(audit)
    audit.set_defaults(func=_cmd)
