# third_party/

NAMD Launcher **orchestrates** three external scientific codes; it does **not
redistribute any of them**. This directory holds only pointers + a fetch
script. `third_party/_src/` (git-ignored) is where `fetch.sh` clones them.

| code | upstream | role | how NAMD Launcher finds it |
|---|---|---|---|
| **CA-NAC** | [WeibinChu/CA-NAC](https://github.com/WeibinChu/CA-NAC) | non-adiabatic couplings + eigenvalues (`inamd nac`) | `nac.canac_dir` → `$NAMDFORGE_CANAC_DIR` → `_src/CA-NAC` → importable `CAnac` |
| **VaspBandUnfolding** | [QijingZheng/VaspBandUnfolding](https://github.com/QijingZheng/VaspBandUnfolding) | `vaspwfc` / `paw` / `spinorb`, imported by CA-NAC | `nac.vaspwfc_dir` → `$NAMDFORGE_VASPWFC_DIR` → `_src/VaspBandUnfolding` → importable |
| **Hefei-NAMD-DEV** | [zhang-changwei/Hefei-NAMD-DEV](https://github.com/zhang-changwei/Hefei-NAMD-DEV) | default unified `hfnamd` engine | `namd.binary_dir` → `_src/Hefei-NAMD-DEV` → `$PATH` |
| **Hefei-NAMD** | [QijingZheng/Hefei-NAMD](https://github.com/QijingZheng/Hefei-NAMD) | legacy master `dish` / `namd` engines | `namd.binary_dir` → `_src/Hefei-NAMD/src/{dish,namd}` → `$PATH` |

## Setup

```bash
bash third_party/fetch.sh                       # clone all four (pinned commits)
cd third_party/_src/Hefei-NAMD-DEV
make -f linux/Makefile tdm                       # build default hfnamd engine
pip install ase scipy numpy                     # CA-NAC's Python deps
```

Or skip `fetch.sh` entirely and point at your existing installs via the
campaign keys / environment variables above. The compute-side `canac` /
`hefei_namd` scheduler jobs can also set things up in their `preamble`
(`CANAC_ACTIVATE_SCRIPT` is wired in the LONI profile template).

## Why nothing is committed here

CA-NAC and the original Hefei-NAMD repository do not ship an explicit
open-source license; Hefei-NAMD-DEV is MIT-licensed. CA-NAC also pulls in
`mod_hungarian.py` (GPL-2.0+, from Libra). Rather than redistribute scientific
engine code, `fetch.sh` pins exact commits so a study stays reproducible.
`inamd nac prepare` / `inamd hefei audit` report which install was resolved and
how. A missing CA-NAC installation is an error at `inamd nac run` unless
`--allow-missing` is used for a compute-node-only environment. A Hefei launch
script may likewise rely on scheduler modules; its shell job fails normally if
the automatically selected binary is still unavailable at runtime.
