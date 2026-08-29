# CA-NAC

Non-adiabatic couplings and eigenvalues for the NAMD stage are computed by
**CA-NAC** (Concentric Approximation – Non-adiabatic Coupling).

> Weibin Chu and Oleg V. Prezhdo, *Concentric Approximation for Fast and
> Accurate Numerical Evaluation of Nonadiabatic Coupling with Projector
> Augmented-Wave Pseudopotentials*, **J. Phys. Chem. Lett.** 2021, 12 (12),
> 3082–3089.
> Repository: <https://github.com/WeibinChu/CA-NAC>

CA-NAC is used here (rather than Hefei-NAMD's own serial NAC) because it
parallelises the WAVECAR time-overlap step and produces a standard input that
is compatible with both Hefei-NAMD and PYXAID.

## Dependencies (installed, not vendored)

NAMD Launcher ships **no** CA-NAC code. Get it once:

```bash
bash third_party/fetch.sh          # clones CA-NAC + VaspBandUnfolding into third_party/_src/
pip install ase scipy numpy
```

or point at your own installs in the campaign:

```yaml
nac:
  canac_dir: ~/src/CA-NAC
  vaspwfc_dir: ~/src/VaspBandUnfolding
```

Resolution order: `nac.canac_dir` → `$NAMDFORGE_CANAC_DIR` →
`third_party/_src/CA-NAC` → importable `CAnac`. `inamd nac prepare` reports
what it found (`canac.found`, `canac.how`); `inamd nac run` refuses if nothing
is resolvable unless you pass `--allow-missing` (for when the compute node's
`canac` job sets it up itself). When a directory *is* resolved, `run_canac.sh`
prepends it to `PYTHONPATH`.

AE-NAC (`is_alle: true`) additionally needs a VASP source patch from the CA-NAC
authors and is **not** used by the default path.

## How NAMD Launcher drives it

`inamd nac prepare` renders **only** `snapshots/input.py` from the campaign
`nac:` block (nothing is copied in -- CA-NAC's `CAnac.py` etc. come from the
resolved install via `PYTHONPATH`):

| campaign key | `input.py` variable | meaning |
|---|---|---|
| `nac.bmin` / `nac.bmax` | `bmin` / `bmax` | NAMD band window (VASP indices) — must equal `namd.bmin/bmax` |
| `nac.bmin_stored` / `nac.bmax_stored` | `bmin_stored` / `bmax_stored` | wider time-overlap storage window (enclose the NAMD window) |
| `nac.gamma` | `is_gamma_version` | `true` for `vasp_gam` WAVECARs |
| `nac.nproc` | `nproc` | CA-NAC parallel workers (match the `canac` job's ntasks) |
| `nac.is_real` | `is_real` | keep `true` — Hefei-NAMD needs real NAC |
| `nac.is_reorder` | `is_reorder` | state reordering via `mod_hungarian.py` (use with care) |
| `snapshots.nsw` | `T_end` | number of snapshot folders |
| `snapshots.digits` | folder format | `./%03d/` etc. |

`inamd nac run` submits `python input.py`; `inamd nac collect` renames the
three output text files to the Hefei-NAMD names.

## Reference-workflow observations

- CA-NAC can band-fold multiple k-points, so momentum-resolved NAC is possible
  (unexplored here).
- Delete `*.npy` in the snapshot folders before a **re-run** — CA-NAC caches
  intermediate overlaps in those binaries and will not recompute them.
