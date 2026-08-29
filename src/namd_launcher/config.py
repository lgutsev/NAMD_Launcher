"""Campaign and scheduler-profile loading with conservative validation.

The campaign file (``namd_campaign.yaml``) is intentionally small: it records
the source trajectory, the band window, and the parameters for each stage of
the VASP -> CA-NAC -> Hefei-NAMD pipeline. Validation checks *structure and
types* only -- it never guesses a physical value (band indices, NBANDS,
temperature, ...). Each stage asserts the fields it actually needs.

Schema and loader style mirror ``interfaceforge.config``.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigurationError

SCHEMA_VERSION = 1
NAC_ENGINES = ("ca-nac",)
NAMD_BRANCHES = ("dev", "master")
NAMD_ALGORITHMS = ("DISH", "FSSH")


@dataclass(frozen=True)
class Campaign:
    """Validated, path-resolved NAMD campaign configuration."""

    path: Path
    root: Path
    name: str
    description: str
    profile_path: Path
    source: dict[str, Any]
    snapshots: dict[str, Any]
    bands: dict[str, Any]
    nac: dict[str, Any]
    dephasing: dict[str, Any]
    inicon: dict[str, Any]
    namd: dict[str, Any]
    analysis: dict[str, Any]
    raw: dict[str, Any]

    def stage_dir(self, name: str) -> Path:
        return self.root / name


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{where} must be a mapping")
    return dict(value)


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def _int(value: Any, where: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{where} must be an integer") from exc


def _float(value: Any, where: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{where} must be a number") from exc


def _bool(value: Any, where: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ConfigurationError(f"{where} must be a boolean (true/false)")


def _band_group(value: Any, where: str) -> list[list[int]]:
    """Normalise an atom-index group to a list of inclusive [start, stop] pairs.

    Accepts ``[a, b]`` (one range) or ``[[a, b], [c, d], e]`` (several ranges,
    a bare integer meaning the single index). Indices are 1-based (VASP ion
    order), matching the user's ``tdksen`` / ``bandgap`` scripts.
    """

    if not isinstance(value, list) or not value:
        raise ConfigurationError(f"{where} must be a non-empty list")
    # single [start, stop]
    if len(value) == 2 and all(isinstance(item, int) for item in value):
        pairs = [[int(value[0]), int(value[1])]]
    else:
        pairs = []
        for item in value:
            if isinstance(item, int):
                pairs.append([item, item])
            elif isinstance(item, list) and len(item) == 2 and all(isinstance(x, int) for x in item):
                pairs.append([int(item[0]), int(item[1])])
            else:
                raise ConfigurationError(f"{where}: each entry must be an int or an [int, int] pair")
    for start, stop in pairs:
        if start < 1 or stop < start:
            raise ConfigurationError(f"{where}: ranges must satisfy 1 <= start <= stop (got {start}, {stop})")
    return pairs


def _validate_source(source: dict[str, Any]) -> dict[str, Any]:
    trajectory = source.get("trajectory")
    if not trajectory:
        raise ConfigurationError("source.trajectory is required (an XDATCAR_FINAL file or a Step2 run directory)")
    source["trajectory"] = str(trajectory)
    source["structure"] = str(source.get("structure", "CONTCAR"))
    return source


def _validate_snapshots(snapshots: dict[str, Any]) -> dict[str, Any]:
    snapshots["nsw"] = _int(snapshots.get("nsw", 500), "snapshots.nsw")
    if snapshots["nsw"] < 2:
        raise ConfigurationError("snapshots.nsw must be at least 2")
    snapshots["stride"] = _int(snapshots.get("stride", 1), "snapshots.stride")
    if snapshots["stride"] < 1:
        raise ConfigurationError("snapshots.stride must be positive")
    snapshots["potim"] = _float(snapshots.get("potim", 1.0), "snapshots.potim")
    links = snapshots.get("link_inputs", ["INCAR", "KPOINTS", "POTCAR"])
    if not isinstance(links, list) or any(not str(item).strip() for item in links):
        raise ConfigurationError("snapshots.link_inputs must be a list of file names")
    snapshots["link_inputs"] = [str(item) for item in links]
    if "incar" in snapshots and snapshots["incar"]:
        snapshots["incar"] = str(snapshots["incar"])
    snapshots["digits"] = _int(snapshots.get("digits", 3), "snapshots.digits")
    if snapshots["digits"] < 1:
        raise ConfigurationError("snapshots.digits must be positive")
    return snapshots


def _validate_bands(bands: dict[str, Any]) -> dict[str, Any]:
    for key in ("vbm", "cbm", "nbands"):
        if key in bands and bands[key] is not None:
            bands[key] = _int(bands[key], f"bands.{key}")
    bands["nbands_margin"] = _int(bands.get("nbands_margin", 64), "bands.nbands_margin")
    bands["nbands_round"] = _int(bands.get("nbands_round", 8), "bands.nbands_round")
    if bands["nbands_margin"] < 0:
        raise ConfigurationError("bands.nbands_margin cannot be negative")
    if bands["nbands_round"] < 1:
        raise ConfigurationError("bands.nbands_round must be positive")
    groups = _mapping(bands.get("groups"), "bands.groups")
    bands["groups"] = {str(label): _band_group(value, f"bands.groups.{label}") for label, value in groups.items()}
    return bands


def _validate_nac(nac: dict[str, Any]) -> dict[str, Any]:
    engine = str(nac.get("engine", "ca-nac")).lower()
    if engine not in NAC_ENGINES:
        raise ConfigurationError(f"nac.engine must be one of {NAC_ENGINES}")
    nac["engine"] = engine
    for key in ("bmin", "bmax", "bmin_stored", "bmax_stored", "nproc", "ispin", "ikpt", "icor"):
        if key in nac and nac[key] is not None:
            nac[key] = _int(nac[key], f"nac.{key}")
    nac.setdefault("ispin", 1)
    nac.setdefault("ikpt", 1)
    nac.setdefault("nproc", 48)
    nac["gamma"] = _bool(nac.get("gamma", True), "nac.gamma")
    nac["is_real"] = _bool(nac.get("is_real", True), "nac.is_real")
    nac["is_reorder"] = _bool(nac.get("is_reorder", False), "nac.is_reorder")
    nac["is_alle"] = _bool(nac.get("is_alle", False), "nac.is_alle")
    nac["iformat"] = str(nac.get("iformat", "HFNAMD")).upper()
    if nac["iformat"] not in {"HFNAMD", "PYXAID"}:
        raise ConfigurationError("nac.iformat must be HFNAMD or PYXAID")
    if "potim" in nac:
        nac["potim"] = _float(nac["potim"], "nac.potim")
    for key in ("canac_dir", "vaspwfc_dir"):
        if nac.get(key):
            nac[key] = str(Path(str(nac[key])).expanduser())
    if {"bmin", "bmax"} <= nac.keys() and nac["bmin"] > nac["bmax"]:
        raise ConfigurationError("nac.bmin must not exceed nac.bmax")
    if {"bmin_stored", "bmax_stored", "bmin", "bmax"} <= nac.keys():
        if nac["bmin_stored"] > nac["bmin"] or nac["bmax_stored"] < nac["bmax"]:
            raise ConfigurationError(
                "nac.[bmin_stored, bmax_stored] must enclose nac.[bmin, bmax]"
            )
    return nac


def _validate_dephasing(dephasing: dict[str, Any]) -> dict[str, Any]:
    dephasing["expect_min_fs"] = _float(dephasing.get("expect_min_fs", 2.0), "dephasing.expect_min_fs")
    dephasing["expect_max_fs"] = _float(dephasing.get("expect_max_fs", 20.0), "dephasing.expect_max_fs")
    if dephasing["expect_min_fs"] >= dephasing["expect_max_fs"]:
        raise ConfigurationError("dephasing.expect_min_fs must be below dephasing.expect_max_fs")
    dephasing["dt_fs"] = _float(dephasing.get("dt_fs", 1.0), "dephasing.dt_fs")
    return dephasing


def _validate_inicon(inicon: dict[str, Any]) -> dict[str, Any]:
    for key in ("nsample", "tmax", "band_min", "band_max", "seed"):
        if key in inicon and inicon[key] is not None:
            inicon[key] = _int(inicon[key], f"inicon.{key}")
    if {"band_min", "band_max"} <= inicon.keys() and inicon["band_min"] > inicon["band_max"]:
        raise ConfigurationError("inicon.band_min must not exceed inicon.band_max")
    return inicon


def _validate_namd(namd: dict[str, Any]) -> dict[str, Any]:
    branch = str(namd.get("branch", "dev")).lower()
    if branch not in NAMD_BRANCHES:
        raise ConfigurationError(f"namd.branch must be one of {NAMD_BRANCHES}")
    namd["branch"] = branch
    algo = str(namd.get("algo", "DISH")).upper()
    if algo not in NAMD_ALGORITHMS:
        raise ConfigurationError(f"namd.algo must be one of {NAMD_ALGORITHMS}")
    namd["algo"] = algo
    for key in ("bmin", "bmax", "nbands", "nsw", "nsample", "ntraj", "nelm", "namdtime", "algo_int"):
        if key in namd and namd[key] is not None:
            namd[key] = _int(namd[key], f"namd.{key}")
    for key in ("potim", "temp"):
        if key in namd and namd[key] is not None:
            namd[key] = _float(namd[key], f"namd.{key}")
    namd["lhole"] = _bool(namd.get("lhole", False), "namd.lhole")
    namd["lcptxt"] = _bool(namd.get("lcptxt", True), "namd.lcptxt")
    namd["lshp"] = _bool(namd.get("lshp", True), "namd.lshp")
    namd["debuglevel"] = str(namd.get("debuglevel", "I"))
    namd["rundir"] = str(namd.get("rundir", "."))
    if namd.get("binary_dir"):
        namd["binary_dir"] = str(Path(str(namd["binary_dir"])).expanduser())
    if {"bmin", "bmax"} <= namd.keys() and namd["bmin"] >= namd["bmax"]:
        raise ConfigurationError("namd.bmin must be below namd.bmax (Hefei-NAMD needs at least two states)")
    return namd


def _validate_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    analysis["shprop_column"] = _int(analysis.get("shprop_column", 4), "analysis.shprop_column")
    if analysis["shprop_column"] < 1:
        raise ConfigurationError("analysis.shprop_column must be positive (1-based)")
    analysis["time_in"] = str(analysis.get("time_in", "fs")).lower()
    analysis["fit_time_unit"] = str(analysis.get("fit_time_unit", "ns")).lower()
    for unit_key in ("time_in", "fit_time_unit"):
        if analysis[unit_key] not in {"fs", "ps", "ns"}:
            raise ConfigurationError(f"analysis.{unit_key} must be fs, ps or ns")
    analysis["model"] = str(analysis.get("model", "single_exp"))
    if analysis["model"] not in {"single_exp"}:
        raise ConfigurationError("analysis.model currently supports only 'single_exp'")
    analysis["normalize"] = _bool(analysis.get("normalize", True), "analysis.normalize")
    return analysis


def _validate_cross_fields(
    snapshots: dict[str, Any],
    nac: dict[str, Any],
    dephasing: dict[str, Any],
    inicon: dict[str, Any],
    namd: dict[str, Any],
) -> None:
    """Reject campaign combinations that Hefei-NAMD cannot safely execute."""

    for left, right, label in (
        (nac.get("bmin"), namd.get("bmin"), "bmin"),
        (nac.get("bmax"), namd.get("bmax"), "bmax"),
    ):
        if left is not None and right is not None and left != right:
            raise ConfigurationError(f"nac.{label} must equal namd.{label} ({left} != {right})")

    if namd.get("bmin") is not None and namd.get("bmax") is not None:
        band_min = inicon.get("band_min")
        band_max = inicon.get("band_max")
        if band_min is not None and band_max is not None:
            if band_min < namd["bmin"] or band_max > namd["bmax"]:
                raise ConfigurationError(
                    "inicon band range must lie inside the Hefei-NAMD active window: "
                    f"[{band_min}, {band_max}] is outside [{namd['bmin']}, {namd['bmax']}]"
                )

    if inicon.get("nsample") is not None and namd.get("nsample") is not None:
        if inicon["nsample"] != namd["nsample"]:
            raise ConfigurationError(
                "inicon.nsample must equal namd.nsample so every generated initial condition is used "
                f"({inicon['nsample']} != {namd['nsample']})"
            )

    if namd.get("nsw") is not None and namd["nsw"] > snapshots["nsw"] - 1:
        raise ConfigurationError(
            "namd.nsw cannot exceed snapshots.nsw - 1 because time-overlap NACs require adjacent frames "
            f"({namd['nsw']} > {snapshots['nsw'] - 1})"
        )

    nac_potim = float(nac.get("potim", snapshots["potim"]))
    if namd.get("potim") is not None and abs(float(namd["potim"]) - nac_potim) > 1e-12:
        raise ConfigurationError(
            f"namd.potim must match the retained-snapshot NAC timestep ({namd['potim']} != {nac_potim})"
        )
    if abs(float(dephasing["dt_fs"]) - nac_potim) > 1e-12:
        raise ConfigurationError(
            f"dephasing.dt_fs must match the retained-snapshot NAC timestep ({dephasing['dt_fs']} != {nac_potim})"
        )


def load_campaign(path: str | Path) -> Campaign:
    """Load and validate a NAMD campaign YAML file."""

    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ConfigurationError(f"Campaign file does not exist: {config_path}")
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML in {config_path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ConfigurationError("Campaign root must be a mapping")
    raw = copy.deepcopy(dict(data))

    if _int(data.get("schema_version", 0), "schema_version") != SCHEMA_VERSION:
        raise ConfigurationError(f"Only schema_version: {SCHEMA_VERSION} is supported")

    root = config_path.parent
    project = _mapping(data.get("project"), "project")
    name = str(project.get("name", "")).strip()
    if not name:
        raise ConfigurationError("project.name is required")
    description = str(project.get("description", "")).strip()

    profile_value = data.get("profile")
    if not profile_value:
        raise ConfigurationError("profile is required")
    profile_path = _resolve(root, str(profile_value)).resolve()

    source = _validate_source(_mapping(data.get("source"), "source"))
    snapshots = _validate_snapshots(_mapping(data.get("snapshots"), "snapshots"))
    bands = _validate_bands(_mapping(data.get("bands"), "bands"))
    nac = _validate_nac(_mapping(data.get("nac"), "nac"))
    dephasing = _validate_dephasing(_mapping(data.get("dephasing"), "dephasing"))
    inicon = _validate_inicon(_mapping(data.get("inicon"), "inicon"))
    namd = _validate_namd(_mapping(data.get("namd"), "namd"))
    analysis = _validate_analysis(_mapping(data.get("analysis"), "analysis"))
    _validate_cross_fields(snapshots, nac, dephasing, inicon, namd)

    return Campaign(
        path=config_path,
        root=root,
        name=name,
        description=description,
        profile_path=profile_path,
        source=source,
        snapshots=snapshots,
        bands=bands,
        nac=nac,
        dephasing=dephasing,
        inicon=inicon,
        namd=namd,
        analysis=analysis,
        raw=raw,
    )


def load_profile(path: str | Path) -> dict[str, Any]:
    """Load a scheduler profile without interpreting engine-specific commands.

    Same schema as an InterfaceForge scheduler profile.
    """

    profile_path = Path(path).expanduser().resolve()
    if not profile_path.is_file():
        raise ConfigurationError(f"Scheduler profile does not exist: {profile_path}")
    try:
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid profile YAML in {profile_path}: {exc}") from exc
    if not isinstance(profile, Mapping):
        raise ConfigurationError("Scheduler profile root must be a mapping")
    result = dict(profile)
    scheduler = str(result.get("scheduler", "")).lower()
    if scheduler not in {"slurm", "local"}:
        raise ConfigurationError("profile.scheduler must be slurm or local")
    jobs = result.get("jobs")
    if not isinstance(jobs, Mapping) or not jobs:
        raise ConfigurationError("profile.jobs must be a non-empty mapping")
    result["scheduler"] = scheduler
    result["jobs"] = {str(key): _mapping(value, f"profile.jobs.{key}") for key, value in jobs.items()}
    result["_path"] = str(profile_path)
    return result
