# third_party/

NAMD Launcher **orchestrates** three external scientific codes; it does **not
redistribute any of them**. This directory holds only pointers + a fetch
script. `third_party/_src/` (git-ignored) is where `fetch.sh` clones them.

| code | upstream | role | how NAMD Launcher finds it |
|---|---|---|---|
| **CA-NAC** | [WeibinChu/CA-NAC](https://github.com/WeibinChu/CA-NAC) | non-adiabatic couplings + eigenvalues (`inamd nac`) | `nac.canac_dir` → `$NAMDFORGE_CANAC_DIR` → `_src/CA-NAC` → importable `CAnac` |
| **VaspBandUnfolding** | [QijingZheng/VaspBandUnfolding](https://github.com/QijingZheng/VaspBandUnfolding) | `vaspwfc` / `paw` / `spinorb`, imported by CA-NAC | `nac.vaspwfc_dir` → `$NAMDFORGE_VASPWFC_DIR` → `_src/VaspBandUnfolding` → importable |
| **Hefei-NAMD** | [QijingZheng/Hefei-NAMD](https://github.com/QijingZheng/Hefei-NAMD) | the surface-hopping engine (`inamd hefei`) | `namd.binary_dir` → `_src/Hefei-NAMD/src/{dish,namd}` → `hfnamd`/`dish`/`namd` on `$PATH` |

## Setup

```bash
bash third_party/fetch.sh                       # clone all three (pinned commits)
cd third_party/_src/Hefei-NAMD/src/dish && make # build the engine
pip install ase scipy numpy                     # CA-NAC's Python deps
```

Or skip `fetch.sh` entirely and point at your existing installs via the
campaign keys / environment variables above. The compute-side `canac` /
`hefei_namd` scheduler jobs can also set things up in their `preamble`
(`CANAC_ACTIVATE_SCRIPT` is wired in the LONI profile template).

## Why nothing is committed here

CA-NAC and Hefei-NAMD do not ship an explicit open-source license, and CA-NAC
pulls in `mod_hungarian.py` (GPL-2.0+, from Libra). Rather than redistribute
any of it, `fetch.sh` pins exact commits so a study stays reproducible.
`inamd nac prepare` / `inamd hefei audit` report which install was resolved and
how; a missing dependency becomes an error at `inamd nac run` /
`inamd hefei launch` (use `--allow-missing` if the compute node provides it).
