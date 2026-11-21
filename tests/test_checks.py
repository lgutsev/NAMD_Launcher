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


# --------------------------------------------------------------------------- #
# molecules, slab axis and geometry in the edge details
# --------------------------------------------------------------------------- #
from namd_launcher.checks import band_molecules, molecules, read_structure, slab_axis  # noqa: E402


def _slab_poscar(path: Path, n_stretch: float = 0.0) -> int:
    """Three 7x7 Pb layers (z 5, 11, 17; each one framework group) in a 22.4 x 22.4 x 40 cell, and a C-N-N-H
    molecule at z 8 between the first two layers. Returns the number of atoms."""
    pb = [(3.2 * i, 3.2 * j, z) for z in (5.0, 11.0, 17.0) for i in range(7) for j in range(7)]
    mol_c = [(1.6, 1.6, 8.0)]
    mol_n = [(2.95 + n_stretch, 1.6, 8.0), (0.25, 1.6, 8.0)]
    mol_h = [(1.6, 2.68, 8.0)]
    lines = ["slab", "1.0", "22.4 0 0", "0 22.4 0", "0 0 40", "Pb C N H",
             f"{len(pb)} 1 2 1", "Cartesian"]
    lines += [f"{x:.4f} {y:.4f} {z:.4f}" for x, y, z in pb + mol_c + mol_n + mol_h]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(pb) + 4


def test_molecules_slab_and_depth(tmp_path: Path) -> None:
    _slab_poscar(tmp_path / "POSCAR")
    struct = read_structure(tmp_path / "POSCAR")
    mols = molecules(*struct)
    sizes = sorted(len(g) for g in mols["groups"])
    assert sizes == [4, 49, 49, 49]
    slab = slab_axis(*struct)
    assert slab["axis"] == "c" and slab["slab_A"] == 12.0 and slab["gap_A"] == 28.0
    weights = {147: 0.5, 148: 0.2, 149: 0.2, 0: 0.1}  # C, N, N (0-based) and one Pb
    out = band_molecules(weights, struct, mols, slab, struct)
    mol = out[0]
    assert mol["kind"] == "molecule" and mol["formula"] == "CHN2" and mol["fraction"] == 0.9
    assert mol["depth_A"] == 3.0
    assert out[1]["kind"] == "framework"
    geo = mol["geometry"]
    assert geo["same_atoms_bonded_in_reference"] is True
    assert {b["bond"] for b in geo["heavy_bonds"]} == {"C148-N149", "C148-N150"}


def test_split_framework_pieces_count_as_framework(tmp_path: Path) -> None:
    """A Pb-I piece cut off from the lattice by a stretched bond, and a lone iodide, are framework, not molecules;
    all framework weight is one entry."""
    pb = [(3.2 * i, 3.2 * j, 5.0) for i in range(7) for j in range(7)]
    piece_pb = [(10.0, 10.0, 12.0)]
    piece_i = [(10.0, 10.0, 15.0), (13.0, 10.0, 12.0)]   # 3.0 A from the piece's Pb, 7 A from the layer
    lone_i = [(1.6, 1.6, 20.0)]
    mol_c, mol_n, mol_h = [(1.6, 1.6, 26.0)], [(2.95, 1.6, 26.0), (0.25, 1.6, 26.0)], [(1.6, 2.68, 26.0)]
    lines = ["split", "1.0", "22.4 0 0", "0 22.4 0", "0 0 40", "Pb I C N H", "50 3 1 2 1", "Cartesian"]
    lines += [f"{x:.4f} {y:.4f} {z:.4f}" for x, y, z in pb + piece_pb + piece_i + lone_i + mol_c + mol_n + mol_h]
    (tmp_path / "POSCAR").write_text("\n".join(lines) + "\n", encoding="utf-8")
    struct = read_structure(tmp_path / "POSCAR")
    mols = molecules(*struct)
    assert sorted(len(g) for g in mols["groups"]) == [1, 3, 4, 49]
    # 0-based: 0 layer Pb, 49 piece Pb, 50/51 piece I, 52 lone I, 53 C, 54/55 N
    weights = {0: 0.1, 49: 0.3, 50: 0.1, 51: 0.1, 52: 0.1, 53: 0.2, 54: 0.05, 55: 0.05}
    out = band_molecules(weights, struct, mols, None, struct)
    assert out[0]["kind"] == "framework" and out[0]["fraction"] == 0.7 and out[0]["atoms"] == 53
    assert out[1]["kind"] == "molecule" and out[1]["formula"] == "CHN2" and out[1]["fraction"] == 0.3
    assert len(out) == 2 and "geometry" in out[1]


def test_edges_details_report_molecule_geometry(campaign_dir: Path) -> None:
    n = 151
    for k, stretch in ((1, 0.0), (2, 0.0), (3, 0.2)):
        d = campaign_dir / "snapshots" / f"{k:03d}"
        d.mkdir(parents=True, exist_ok=True)
        _eigenval(d / "EIGENVAL", E0)
        _slab_poscar(d / "POSCAR", n_stretch=stretch)
        cbm = [0.0] * n
        if k == 3:
            cbm[147], cbm[148] = 0.6, 0.3  # C and N carry the CBM
            cbm[0] = 0.1
        else:
            cbm[0] = 1.0
        vbm = [0.0] * n
        vbm[50] = 1.0
        _procar(d / "PROCAR", {4: vbm, 5: cbm, 3: vbm, 6: cbm[:]}, nb=7)
    r = check_edges(load_campaign(campaign_dir / "namd_campaign.yaml"))
    assert r["changed_frames"] == [3]
    d3 = {d["frame"]: d for d in r["details"]}[3]
    mol = d3["5"]["molecules"][0]
    assert mol["formula"] == "CHN2" and mol["depth_A"] == 3.0
    bonds = {b["bond"]: b for b in mol["geometry"]["heavy_bonds"]}
    assert bonds["C148-N149"]["d_A"] == 1.55 and bonds["C148-N149"]["ref_A"] == 1.35
    md = Path(r["files"]["markdown"]).read_text(encoding="utf-8")
    assert "molecule CHN2" in md and "3.0 A below the nearer face" in md and "C148-N149 1.550 (frame 1 1.35)" in md
