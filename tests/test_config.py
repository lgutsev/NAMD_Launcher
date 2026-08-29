"""Campaign + profile validation."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from namd_launcher.config import load_campaign, load_profile
from namd_launcher.errors import ConfigurationError


def _write(path: Path, body: str) -> Path:
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_load_valid_campaign(campaign_dir: Path) -> None:
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    assert campaign.name == "test-namd"
    assert campaign.nac["bmin"] == 4
    assert campaign.namd["branch"] == "dev"
    assert campaign.bands["groups"] == {}


def test_band_group_normalisation(tmp_path: Path) -> None:
    camp = _write(
        tmp_path / "c.yaml",
        """
        schema_version: 1
        project: {name: g}
        profile: p.yaml
        source: {trajectory: x}
        bands:
          groups:
            Iodine: [177, 257]
            Mixed: [[1, 3], 9, [11, 12]]
        """,
    )
    (tmp_path / "p.yaml").write_text("scheduler: local\njobs: {a: {command: x}}\n", encoding="utf-8")
    campaign = load_campaign(camp)
    assert campaign.bands["groups"]["Iodine"] == [[177, 257]]
    assert campaign.bands["groups"]["Mixed"] == [[1, 3], [9, 9], [11, 12]]


def test_rejects_bad_schema_version(tmp_path: Path) -> None:
    camp = _write(tmp_path / "c.yaml", "schema_version: 2\nproject: {name: x}\nprofile: p\nsource: {trajectory: t}\n")
    with pytest.raises(ConfigurationError):
        load_campaign(camp)


def test_rejects_missing_trajectory(tmp_path: Path) -> None:
    camp = _write(tmp_path / "c.yaml", "schema_version: 1\nproject: {name: x}\nprofile: p\nsource: {}\n")
    with pytest.raises(ConfigurationError, match="source.trajectory"):
        load_campaign(camp)


def test_rejects_stored_window_not_enclosing(tmp_path: Path) -> None:
    camp = _write(
        tmp_path / "c.yaml",
        """
        schema_version: 1
        project: {name: x}
        profile: p
        source: {trajectory: t}
        nac: {bmin: 10, bmax: 20, bmin_stored: 12, bmax_stored: 25}
        """,
    )
    with pytest.raises(ConfigurationError, match="enclose"):
        load_campaign(camp)


def test_profile_requires_partition_account_only_for_slurm(tmp_path: Path) -> None:
    good = _write(tmp_path / "local.yaml", "scheduler: local\njobs: {a: {command: echo hi}}\n")
    profile = load_profile(good)
    assert profile["scheduler"] == "local"
    bad = _write(tmp_path / "bad.yaml", "scheduler: pbs\njobs: {a: {}}\n")
    with pytest.raises(ConfigurationError):
        load_profile(bad)
