"""Full local pipeline: snapshots -> (fake VASP) -> nac -> dephase -> inicon -> hefei -> shprop."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from namd_launcher.audit import campaign_audit
from namd_launcher.config import load_campaign
from namd_launcher.dephase import run_dephase
from namd_launcher.hefeinamd import prepare_hefei
from namd_launcher.inicon import generate_inicon
from namd_launcher.nac import collect_nac, prepare_nac
from namd_launcher.shprop import run_shprop
from namd_launcher.snapshots import prepare_snapshots

from ._helpers import make_xdatcar

OUTCAR = "reached required accuracy - stopping structural energy minimisation\n General timing and accounting\n"


def test_full_local_pipeline(campaign_dir: Path) -> None:
    # --- inputs ---
    make_xdatcar(campaign_dir / "traj" / "XDATCAR_FINAL", frames=8, n=2)
    (campaign_dir / "KPOINTS").write_text("k\n", encoding="utf-8")
    (campaign_dir / "POTCAR").write_text("p\n", encoding="utf-8")
    campaign = load_campaign(campaign_dir / "namd_campaign.yaml")
    snap = campaign_dir / "snapshots"

    # --- stage 1: snapshots ---
    prepare_snapshots(campaign)
    assert sorted(p.name for p in snap.iterdir() if p.is_dir()) == ["001", "002", "003"]

    # --- stage 2: pretend VASP ran ---
    for folder in ("001", "002", "003"):
        (snap / folder / "OUTCAR").write_text(OUTCAR, encoding="utf-8")
        (snap / folder / "WAVECAR").write_text("x" * 32, encoding="utf-8")

    # --- stage 4: nac (fake CA-NAC output; nbasis=2 -> 4 NAC cols, 2 eig cols) ---
    prepare_nac(campaign)
    rng = np.random.default_rng(0)
    frames = 150
    np.savetxt(snap / "CAnac_2_7_ispin1_k1_ps_real_re.txt", 1e-4 * rng.standard_normal((frames, 4)))
    gap = 1.0 + 0.06 * rng.standard_normal(frames)
    eig = np.column_stack([-1.5 + np.zeros(frames), -1.5 + gap])
    np.savetxt(snap / "CAeig_2_7_ispin1_k1_ps_real.txt", eig)
    collect_nac(campaign)
    assert (campaign_dir / "nac" / "NATXT").is_file()

    # --- stage 5: dephase + inicon ---
    run_dephase(campaign)
    generate_inicon(campaign)
    assert (campaign_dir / "nac" / "DEPHTIME").is_file()
    assert (campaign_dir / "nac" / "INICON").is_file()

    # --- stage 6: hefei prepare (validates cross-consistency) ---
    result = prepare_hefei(campaign)
    assert result["audit_status"] == "PASS"
    assert (campaign_dir / "namd" / "inp").read_text(encoding="utf-8").count("BMIN") == 1

    # --- stage 7: pretend Hefei-NAMD produced SHPROP.* ---
    namd = campaign_dir / "namd"
    t = np.linspace(0, 2.0e5, 60)
    for k in range(int(campaign.namd["nsample"])):
        pop = np.exp(-t / 8.0e4)
        np.savetxt(namd / f"SHPROP.{k + 1}", np.column_stack([t, np.ones_like(t), 1 - pop, pop]))
    fit = run_shprop(campaign)
    assert fit["tau"] > 0
    assert fit["r_squared"] > 0.99

    # --- rollup ---
    report = campaign_audit(campaign)
    by_stage = {s["stage"]: s["status"] for s in report["stages"]}
    for stage in ("snapshots", "waverun", "nac", "dephase", "inicon", "hefei", "shprop"):
        assert by_stage[stage] in {"PASS", "WARN"}, (stage, by_stage[stage])
