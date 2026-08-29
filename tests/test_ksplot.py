"""Stage 3: band-gap statistics + PROCAR projection."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from namd_launcher.config import load_campaign
from namd_launcher.ksplot import band_gap_stats, ks_energy_plot, run_ksplot, weight_from_procar
from namd_launcher.snapshots import prepare_snapshots

from ._helpers import make_xdatcar

EIGENVAL = """\
  header line
  more
  more
  more
  more
   1  -2.0000  1.000000
   2  -1.5000  1.000000
   3  -1.0000  1.000000
   4   0.5000  0.000000
   5   1.0000  0.000000
"""

PROCAR = """\
PROCAR lm decomposed
# of k-points:  1   # of bands:  2   # of ions:  2

band   1 # energy   -1.00000000 # occ.  1.00000000
  1  0.10 0.00 0.00 0.00  0.30
  2  0.20 0.00 0.00 0.00  0.40

band   2 # energy    0.50000000 # occ.  0.00000000
  1  0.05 0.00 0.00 0.00  0.10
  2  0.25 0.00 0.00 0.00  0.60
"""


def _prepare(campaign_dir: Path):
    make_xdatcar(campaign_dir / "traj" / "XDATCAR_FINAL", frames=5, n=2)
    (campaign_dir / "KPOINTS").write_text("k\n", encoding="utf-8")
    (campaign_dir / "POTCAR").write_text("p\n", encoding="utf-8")
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    prepare_snapshots(campaign)
    return campaign


def test_weight_from_procar() -> None:
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix="PROCAR", delete=False) as fh:
        fh.write(PROCAR)
        path = Path(fh.name)
    energies, weights = weight_from_procar(path, np.array([0, 1]))
    assert energies.shape == (1, 1, 2)
    assert energies[0, 0].tolist() == [-1.0, 0.5]
    # band 2: ion tot weights 0.10 + 0.60
    assert weights[0, 0, 1] == 0.70


def test_band_gap_stats(campaign_dir: Path) -> None:
    campaign = _prepare(campaign_dir)
    for folder in ("001", "002", "003"):
        (campaign_dir / "snapshots" / folder / "EIGENVAL").write_text(EIGENVAL, encoding="utf-8")
    stats = band_gap_stats(campaign)
    assert stats["with_eigenval"] == 3
    assert stats["mean_gap_ev"] == 1.5   # 0.5 - (-1.0)


def test_run_ksplot_stats_only(campaign_dir: Path) -> None:
    campaign = _prepare(campaign_dir)
    for folder in ("001", "002", "003"):
        (campaign_dir / "snapshots" / folder / "EIGENVAL").write_text(EIGENVAL, encoding="utf-8")
    result = run_ksplot(campaign, no_plot=True)
    assert result["status"] == "PASS"
    assert result["ks_plot"]["status"] == "skipped"
    assert (campaign_dir / "snapshots" / "bandgap_stats.json").is_file()


def test_ks_plot_skipped_without_procar(campaign_dir: Path) -> None:
    campaign = _prepare(campaign_dir)
    out = ks_energy_plot(campaign)
    assert out["status"] == "skipped"
