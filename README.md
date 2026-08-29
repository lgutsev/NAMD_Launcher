# NAMD Launcher (`namdforge`)

A CLI-first orchestration layer for ab-initio non-adiabatic molecular dynamics
of the kind used for perovskite carrier relaxation and non-radiative
recombination:

```
VASP AIMD   ─▶  snapshot WAVECARs  ─▶  CA-NAC  ─▶  dephasing / INICON
            ─▶  Hefei-NAMD (surface hopping)  ─▶  SHPROP averaging + exp fit  ─▶  τ
```

It is a **launcher only**. It does not implement any non-adiabatic dynamics:
that is done by [**Hefei-NAMD**](https://github.com/QijingZheng/Hefei-NAMD).
Non-adiabatic couplings are evaluated by
[**CA-NAC**](https://github.com/WeibinChu/CA-NAC). NAMD Launcher turns a pile of
per-machine shell scripts into one reproducible, auditable `inamd` command tree
that is convention-compatible with
[InterfaceForge](https://github.com/lgutsev/InterfaceForge) — an `iface vasp
step2-*` run directory is a first-class input here.

## Acknowledgements

**This project stands entirely on the work of others. Please cite and thank them.**

- **Hefei-NAMD** — Qijing Zheng, Jin Zhao, and the Hefei-NAMD contributors
  (University of Science and Technology of China). *All surface-hopping
  dynamics in this workflow is performed by Hefei-NAMD.* This launcher only
  prepares its inputs (`EIGTXT`, `NATXT`, `INICON`, `DEPHTIME`, `inp`) and
  submits it. Repository: <https://github.com/QijingZheng/Hefei-NAMD>. The MD
  and NAMD recipe closely follows Q.-J. Zheng's tutorials at
  <http://staff.ustc.edu.cn/~zqj/>. Thank you.
- **CA-NAC** — Weibin Chu and Oleg V. Prezhdo. *Concentric Approximation for
  Fast and Accurate Numerical Evaluation of Nonadiabatic Coupling with
  Projector Augmented-Wave Pseudopotentials*, **J. Phys. Chem. Lett.** 2021,
  12 (12), 3082–3089. Repository: <https://github.com/WeibinChu/CA-NAC>.
- **VaspBandUnfolding** (`vaspwfc`, `paw`, `spinorb`) — Qijing Zheng.
  <https://github.com/QijingZheng/VaspBandUnfolding>.
- **`mod_hungarian.py`** (used by CA-NAC's state reordering) — Alexey V.
  Akimov, from the Libra project (GPL-2.0+).
- **N2AMD** — Zhang et al., *Nat. Commun.* **16** (2025); arXiv:2408.06654
  (see [`docs/n2amd.md`](docs/n2amd.md) for the optional step-3 integration).

If NAMD Launcher contributes to published work, cite the packages above; a
citation of this launcher itself is optional (see `CITATION.cff`).

## Install

```bash
git clone https://github.com/lgutsev/NAMD_Launcher.git
cd NAMD_Launcher
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # or ".[report]" for just the plotting/fit deps
bash third_party/fetch.sh        # clones CA-NAC + VaspBandUnfolding + Hefei-NAMD
```

**NAMD Launcher redistributes none of the scientific engines.** CA-NAC,
VaspBandUnfolding and Hefei-NAMD are dependencies you install — `fetch.sh`
clones them at pinned commits into `third_party/_src/` (git-ignored), or point
at your own installs with `nac.canac_dir` / `nac.vaspwfc_dir` / `namd.binary_dir`
(or `$NAMDFORGE_CANAC_DIR` / `$NAMDFORGE_VASPWFC_DIR`). See
[`third_party/README.md`](third_party/README.md).

`pip install -e ".[interfaceforge]"` additionally reuses InterfaceForge's exact
scheduler / INCAR / POTCAR helpers; without it, faithful vendored copies are
used (`inamd plan` reports which).

## Ten-minute start

```bash
inamd init my-namd && cd my-namd
# edit namd_campaign.yaml (band window, source trajectory) and profiles/loni.yaml
inamd plan                                    # validate + print the stage DAG

inamd snapshots prepare                       # XDATCAR_FINAL / Step2 run  ->  001..NSW/
inamd waverun launch --chunk 100              # dry run: writes chunk job scripts
inamd waverun launch --chunk 100 --execute    # submit them
inamd waverun audit                           # per-snapshot convergence

inamd nac prepare                             # render input.py + stage CA-NAC
inamd nac run --execute                       # submit `python input.py`
inamd nac collect                             # CAnac_*/CAeig_*  ->  NATXT/EIGTXT/energy.dat

inamd dephase                                 # energy.dat -> DEPHTIME (+ few-fs sanity check)
inamd inicon                                  # INICON initial conditions

inamd hefei prepare                           # render `inp`, cross-check nbasis / frames
inamd hefei launch --execute                  # submit hfnamd / dish / namd

inamd shprop                                  # average SHPROP.* + fit exp(-t/A) -> tau
inamd audit                                   # roll every stage up
```

`inamd run` advances every ready **local** stage in one go (it never submits a
cluster job).

## Conventions (shared with InterfaceForge)

- Every subcommand prints one JSON object to stdout; errors go to stderr as
  `ERROR: …` with exit code 2.
- Every stage writes `<stage>_manifest.json` + `<stage>_audit.{json,tsv,md}`
  and appends to `.namdforge/state.json` (events + hashed artifacts).
- Mutating commands refuse to overwrite an existing output tree (`--force` to
  override). Cluster launches are a dry run unless `--execute` is given.
- Scheduler profiles use the **identical YAML schema** as an InterfaceForge
  profile, so one file drives both tools.

## Layout

| path | what |
|---|---|
| `src/namd_launcher/` | the launcher (MIT) |
| `src/namd_launcher/templates/` | `namd_campaign.yaml`, profiles, `INCAR.nac`, `inp.{dish,fssh}`, CA-NAC input template |
| `third_party/` | pointers + `fetch.sh` only — no engine code is redistributed |
| `docs/` | [workflow](docs/workflow.md), [Hefei-NAMD](docs/hefei-namd.md), [CA-NAC](docs/ca-nac.md), [N2AMD](docs/n2amd.md), [InterfaceForge integration](docs/interfaceforge-integration.md) |

## Status

Early research tool. The per-stage logic is unit-tested (`pytest`) and a full
synthetic pipeline is exercised end to end, but **no real multi-stage LONI
campaign has been run through it yet**. Inspect every generated `inp`,
`input.py`, and job script, and do a small `BMIN/BMAX` smoke run before
committing an allocation.
