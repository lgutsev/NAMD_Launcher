# Hefei-NAMD helper scripts — provenance

**Upstream:** https://github.com/QijingZheng/Hefei-NAMD

**Authors:** Qijing Zheng, Jin Zhao, and the Hefei-NAMD contributors (USTC / Hefei).

These are *analysis* helpers, not the NAMD engine. The engine itself
(`src/dish`, `src/namd`, `src/namdK` Fortran) is fetched and compiled
separately — see `../fetch.sh` and `docs/hefei-namd.md`.

| file | purpose |
|---|---|
| `Dephase.py` | Autocorrelation → pure-dephasing (Gaussian) → `DEPHTIME` matrix. Copied from the working NAMD package for this project; equivalent to upstream `scripts/Dephase.py`. |
| `tdksen.py`, `tdksen_hydrogen.py`, `tdksen_custom.py`, `tdksen_pass.py` | KS energy-vs-time plots coloured by atom-group projection (PROCAR). Project-specific variants layered on upstream `spatial_localization_fssh.py`. |
| `bandgap_stats.py` | Mean / std band gap across the snapshot EIGENVALs. Project-authored. |

`inamd dephase` calls a parametrised port of `Dephase.py`;
`inamd ksplot` calls a parametrised port of `tdksen_hydrogen.py` +
`bandgap_stats.py` (atom groups come from the campaign `bands.groups` block).
The originals are kept here for reference and manual use.

## Citation / acknowledgement

All non-adiabatic dynamics in this workflow is performed by **Hefei-NAMD**.
Please cite the Hefei-NAMD papers and repository and thank the authors — see
the NAMD Launcher `README.md` "Acknowledgements" and `docs/hefei-namd.md`.
