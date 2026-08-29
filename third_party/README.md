# third_party/

Scientific code that NAMD Launcher *orchestrates* rather than reimplements.
It is **not** covered by the repository's MIT license; each subdirectory keeps
its own authors and terms (`PROVENANCE.md`, `LICENSES.md`).

| directory | upstream | role in the workflow |
|---|---|---|
| `ca_nac/` | [WeibinChu/CA-NAC](https://github.com/WeibinChu/CA-NAC) | Non-adiabatic couplings + eigenvalues from snapshot WAVECARs (stage `nac`). |
| `hefei_namd_scripts/` | [QijingZheng/Hefei-NAMD](https://github.com/QijingZheng/Hefei-NAMD) `scripts/` + this project's own copies | `Dephase.py` (DEPHTIME), `tdksen*.py` / `bandgap_stats.py` (KS-manifold plots). |
| `_src/` (git-ignored) | fetched by `fetch.sh` | Hefei-NAMD (Fortran; compiled on the cluster) and VaspBandUnfolding (import dependency of CA-NAC). |

## Getting the compiled/importable dependencies

```bash
bash third_party/fetch.sh          # clones Hefei-NAMD + VaspBandUnfolding into third_party/_src/
```

Then build Hefei-NAMD (`cd third_party/_src/Hefei-NAMD/src/dish && make`) and put
`vaspwfc.py` / `paw.py` / `spinorb.py` from VaspBandUnfolding on `PYTHONPATH`
for the `nac` stage. See `docs/hefei-namd.md` and `docs/ca-nac.md`.

## Why some things are fetched, not committed

Hefei-NAMD and VaspBandUnfolding do not carry an explicit open-source license
file. Rather than redistribute them here, `fetch.sh` pins the exact commits so
the workflow stays reproducible. CA-NAC's Python driver and the Hefei-NAMD
helper scripts *are* committed (with attribution) because the launcher renders
their configuration and needs them present to be useful offline; if you would
prefer they were fetched too, delete the directories and extend `fetch.sh`.
