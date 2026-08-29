# CA-NAC — provenance

**Upstream:** https://github.com/WeibinChu/CA-NAC (default branch `main`,
current commit `a1e0e24ba755549e87e30d675b704de27a1dbeaa`, 2026-03-09).

**Author:** Weibin Chu (wc_086@usc.edu), with Oleg V. Prezhdo.

## Files here

| file | origin |
|---|---|
| `CAnac.py` | CA-NAC driver library (`nac_calc`, TD-overlap, phase correction, combine). Copied from the working NAMD package supplied for this project; equivalent to upstream `CAnac.py`. |
| `aeolap.py` | All-electron augmentation-overlap helper. Same origin. |
| `mod_hungarian.py` | Munkres/Kuhn assignment for state reordering. **Originates from Libra / PYXAID** (Alexey V. Akimov) — see `LICENSES.md`. |
| `input.py.example` | Reference CA-NAC input; NAMD Launcher generates `input.py` from the campaign `nac:` block (see `src/namd_launcher/templates/canac_input.py.tmpl`). |

## Runtime dependencies not vendored here

`CAnac.py` / `aeolap.py` import `vaspwfc`, `paw`, `spinorb` from
**VaspBandUnfolding** (https://github.com/QijingZheng/VaspBandUnfolding,
pinned in `../fetch.sh`), plus `numpy`, `scipy`, `ase`.

## How NAMD Launcher uses it

`inamd nac prepare` writes `input.py` (from the campaign) and copies
`CAnac.py`, `aeolap.py`, `mod_hungarian.py` into the `nac/` stage directory.
`inamd nac run` submits `python input.py` under the `canac` scheduler job.
`inamd nac collect` maps the `CAnac_*_re.txt` / `CAeig_*.txt` outputs to
`NATXT` / `EIGTXT` / `energy.dat` for the Hefei-NAMD stage.

## Citation

Weibin Chu and Oleg V. Prezhdo, *Concentric Approximation for Fast and
Accurate Numerical Evaluation of Nonadiabatic Coupling with Projector
Augmented-Wave Pseudopotentials*, **J. Phys. Chem. Lett.** 2021, 12 (12),
3082–3089.
