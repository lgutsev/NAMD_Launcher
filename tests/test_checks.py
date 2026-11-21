"""Value checks: band edges across snapshots and NATXT/EIGTXT values."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from namd_launcher.checks import check_edges, check_nac, read_eigenval, read_procar
from namd_launcher.config import load_campaign
from namd_launcher.errors import SafetyError

from ._helpers import run_cli

# campaign_dir fixture: snapshots nsw 3, digits 3; bands vbm 4 / cbm 5; nac 4-5; namd nsw 1.
ELEMENTS = ["Pb", "I", "C"]


def _eigenval(path: Path, energies: list[float]) -> None:
    nb = len(energies)
    head = ["    3    3    1    1", "  0.1 0.1 0.1 0.1 0.5E-15", "  1.0E-004", "  CAR", " test",
            f"     8     1    {nb}", "", "  0.0 0.0 0.0 1.0"]
    body = [f"  {i + 1:4d}  {e: .6f}  {1.0 if i < 4 else 0.0:.6f}" for i, e in enumerate(energies)]
    path.write_text("\n".join(head + body) + "\n", encoding="utf-8")


def _poscar(path: Path) -> None:
    path.write_text("t\n1.0\n10 0 0\n0 10 0\n0 0 30\nPb I C\n1 1 1\nDirect\n0 0 0.1\n0.5 0.5 0.2\n0.5 0.5 0.8\n",
                    encoding="utf-8")


def _procar(path: Path, weights: dict[int, list[float]], nb: int = 7) -> None:
    out = ["PROCAR lm decomposed", "# of k-points:  1         # of bands:  7         # of ions:   3", "",
           " k-point     1 :    0.0 0.0 0.0     weight = 1.0", ""]
    for b in range(1, nb + 1):
        w = weights.get(b, [0.3, 0.3, 0.4])
        out += [f"band   {b} # energy   -1.000 # occ.  1.000", "", "ion      s     py     pz     px    tot"]
        out += [f"    {i + 1}  0.0 0.0 0.0 0.0  {x:.3f}" for i, x in enumerate(w)]
        out += [f"tot   0.0 0.0 0.0 0.0  {sum(w):.3f}", ""]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _snapshots(root: Path, frames: list[dict]) -> None:
    for k, f in enumerate(frames, start=1):
        d = root / "snapshots" / f"{k:03d}"
        d.mkdir(parents=True, exist_ok=True)
        _eigenval(d / "EIGENVAL", f["e"])
        _poscar(d / "POSCAR")
        if "w" in f:
            _procar(d / "PROCAR", f["w"])


CLEAN = {4: [0.0, 0.95, 0.05], 5: [0.8, 0.2, 0.0]}
E0 = [-3.0, -2.8, -2.6, -2.0, 0.0, 0.3, 0.6]


def test_readers(tmp_path: Path) -> None:
    _eigenval(tmp_path / "EIGENVAL", E0)
    assert read_eigenval(tmp_path / "EIGENVAL", [4, 5]) == {4: (-2.0, 1.0), 5: (0.0, 0.0)}
    _procar(tmp_path / "PROCAR", CLEAN)
    w = read_procar(tmp_path / "PROCAR", [4, 5])
    assert w[4] == {0: 0.0, 1: 0.95, 2: 0.05}
    assert w[5][0] == 0.8


def test_edges_clean_window_passes(campaign_dir: Path) -> None:
    _snapshots(campaign_dir, [{"e": E0, "w": CLEAN}] * 3)
    r = check_edges(load_campaign(campaign_dir / "namd_campaign.yaml"))
    assert r["status"] == "PASS"
    assert r["gap_eV"]["min"] == 2.0
    assert r["changed_frames"] == [] and r["near_degenerate_above"] == []
    assert Path(r["files"]["json"]).is_file() and Path(r["files"]["markdown"]).is_file()
    assert (campaign_dir / "checks" / "check_edges.json").is_file()


def test_edges_flags_neighbour_and_identity_change(campaign_dir: Path) -> None:
    near = list(E0)
    near[5] = 0.01  # band 6 within kT of the CBM
    organic = {4: CLEAN[4], 5: [0.02, 0.03, 0.95]}  # CBM taken over by C
    _snapshots(campaign_dir, [{"e": E0, "w": CLEAN}, {"e": near, "w": CLEAN}, {"e": E0, "w": organic}])
    r = check_edges(load_campaign(campaign_dir / "namd_campaign.yaml"), frames=[1])
    assert r["status"] == "WARN"
    assert r["near_degenerate_above"] == [2]
    assert r["changed_frames"] == [3]
    detail = {d["frame"]: d for d in r["details"]}
    assert set(detail) == {1, 3}
    top = detail[3]["5"]["top_atoms"][0]
    assert top["element"] == "C" and top["z"] == 24.0
    assert "C@24" in detail[3]["5"]["by_element_z"]
    md = Path(r["files"]["markdown"]).read_text(encoding="utf-8")
    assert "Make-up changed: 3" in md


def test_edges_without_procar_still_checks_energies(campaign_dir: Path) -> None:
    _snapshots(campaign_dir, [{"e": E0}] * 3)
    r = check_edges(load_campaign(campaign_dir / "namd_campaign.yaml"))
    assert r["status"] == "PASS"
    assert any(c["status"] == "PENDING" for c in r["checks"])


def test_edges_missing_frame_fails(campaign_dir: Path) -> None:
    _snapshots(campaign_dir, [{"e": E0}] * 2)
    assert check_edges(load_campaign(campaign_dir / "namd_campaign.yaml"))["status"] == "FAIL"


def _nac_files(root: Path, natxt: list[list[float]], eig: list[list[float]]) -> None:
    (root / "nac").mkdir(exist_ok=True)
    (root / "nac" / "NATXT").write_text("\n".join(" ".join(f"{x:.6e}" for x in r) for r in natxt) + "\n",
                                        encoding="utf-8")
    (root / "nac" / "EIGTXT").write_text("\n".join(" ".join(f"{x:.6f}" for x in r) for r in eig) + "\n",
                                         encoding="utf-8")


def test_nac_values_pass(campaign_dir: Path) -> None:
    _snapshots(campaign_dir, [{"e": E0}] * 3)
    _nac_files(campaign_dir, [[0, 1e-3, -1e-3, 0], [0, 2e-3, -2e-3, 0]], [[-2.0, 0.0], [-2.0, 0.0]])
    r = check_nac(load_campaign(campaign_dir / "namd_campaign.yaml"))
    assert r["status"] == "PASS", r["checks"]
    assert r["stats"]["energy_match"]["compared_rows"] == 2
    assert (campaign_dir / "nac" / "check_nac.json").is_file()


def test_nac_values_catch_bad_tables(campaign_dir: Path) -> None:
    _snapshots(campaign_dir, [{"e": E0}] * 3)
    # not antisymmetric, energies 0.2 eV off, one row short of nothing: rows 2 OK
    _nac_files(campaign_dir, [[0, 1e-3, 1e-3, 0], [0, 2e-3, 2e-3, 0]], [[-2.2, 0.0], [-2.2, 0.0]])
    r = check_nac(load_campaign(campaign_dir / "namd_campaign.yaml"))
    status = {c["check"]: c["status"] for c in r["checks"]}
    assert r["status"] == "FAIL"
    assert status["antisymmetric"] == "FAIL"
    assert status["energies match EIGENVAL"] == "FAIL"


def test_nac_rows_and_columns(campaign_dir: Path) -> None:
    _snapshots(campaign_dir, [{"e": E0}] * 3)
    _nac_files(campaign_dir, [[0, 1e-3, -1e-3, 0]] * 5, [[-2.0, 0.0]] * 4)
    r = check_nac(load_campaign(campaign_dir / "namd_campaign.yaml"))
    assert {c["check"]: c["status"] for c in r["checks"]}["rows"] == "FAIL"


def test_nac_needs_collect(campaign_dir: Path) -> None:
    with pytest.raises(SafetyError, match="nac collect"):
        check_nac(load_campaign(campaign_dir / "namd_campaign.yaml"))


def test_cli_exit_codes(campaign_dir: Path) -> None:
    _snapshots(campaign_dir, [{"e": E0, "w": CLEAN}] * 3)
    code, payload, _ = run_cli(["check", "edges", "--campaign", "namd_campaign.yaml"], cwd=campaign_dir)
    assert code == 0 and payload["status"] == "PASS"
    _nac_files(campaign_dir, [[0, 1e-3, 1e-3, 0]] * 2, [[-2.0, 0.0]] * 2)
    code, payload, _ = run_cli(["check", "nac", "--campaign", "namd_campaign.yaml"], cwd=campaign_dir)
    assert code == 3 and payload["status"] == "FAIL"
    saved = json.loads((campaign_dir / "nac" / "check_nac.json").read_text(encoding="utf-8"))
    assert saved["status"] == "FAIL"
