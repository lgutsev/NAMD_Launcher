"""Shared pytest fixtures for NAMD Launcher tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "namd_launcher" / "templates"


@pytest.fixture
def campaign_dir(tmp_path: Path) -> Path:
    """A minimal, valid campaign directory (profiles + namd_campaign.yaml)."""

    root = tmp_path / "camp"
    root.mkdir()
    (root / "profiles").mkdir()
    (root / "profiles" / "local.yaml").write_text(
        (TEMPLATES / "profile_local.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / "namd_campaign.yaml").write_text(
        textwrap.dedent(
            """\
            schema_version: 1
            project:
              name: test-namd
            profile: profiles/local.yaml
            source:
              trajectory: traj/XDATCAR_FINAL
            snapshots:
              nsw: 3
              digits: 3
            bands:
              vbm: 4
              cbm: 5
              nbands: 8
              nbands_margin: 2
            nac:
              bmin: 4
              bmax: 5
              bmin_stored: 2
              bmax_stored: 6
              gamma: true
              nproc: 2
            inicon:
              nsample: 5
              tmax: 3
              band_min: 5
              band_max: 6
              seed: 7
            namd:
              branch: dev
              algo: DISH
              bmin: 4
              bmax: 5
              nsw: 1
              nsample: 2
              ntraj: 10
              nelm: 5
              namdtime: 200
              potim: 1.0
              temp: 300
            """
        ),
        encoding="utf-8",
    )
    return root
