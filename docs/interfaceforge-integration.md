# Using NAMD Launcher with InterfaceForge

NAMD Launcher (`inamd`) picks up where InterfaceForge (`iface`) leaves off. The
two are deliberately convention-compatible.

## The hand-off point

InterfaceForge's `iface vasp step1-prepare` → `step2-prepare` → `step2-launch`
produces a `Step2_<T>K/<run>/` tree of finished DFT-MD, each run with an
`XDATCAR`, `KPOINTS`, `POTCAR`, `runvasp.sh`/`run.slurm`, and a
`step2_manifest.json`.

Point a NAMD campaign straight at one of those run directories:

```yaml
# namd_campaign.yaml
source:
  trajectory: ../MD/Step2_300K/run1     # an iface step2 run directory
  structure: CONTCAR
```

`inamd snapshots prepare` then:

- reads `XDATCAR_FINAL` if present, else `XDATCAR`, from that directory;
- copies its `KPOINTS`, `POTCAR`, and launcher to the `snapshots/` root;
- takes `INCAR` from `snapshots.incar` (the packaged `INCAR.nac` — a
  WAVECAR/eigenvalue SCF, **not** the MD INCAR);
- sets `NBANDS` from that Step2 run's `OUTCAR`/`INCAR` (raised if it does not
  cover `nac.bmax_stored + bands.nbands_margin`), so the snapshot electronic
  structure matches the trajectory it came from.

An `XDATCAR_FINAL` file produced by the older `Restart_MD` / `PackageOutputsMD`
scripts works identically — just give its path.

## Shared machinery

| concern | InterfaceForge | NAMD Launcher |
|---|---|---|
| scheduler profile | `profiles/loni.yaml` (`scheduler`, `jobs.<name>.{partition,account,nodes,ntasks,command,modules,environment}`) | **same file, same schema** — jobs `vasp_nac`, `canac`, `hefei_namd`, `analysis` |
| INCAR editing | `interfaceforge.vasp.update_incar` | same function (imported when `interfaceforge` is installed; identical vendored copy otherwise) |
| POTCAR assembly | `iface vasp potcar` / built-in `POTCAR_DEFS` | same helper + `templates/potcar_pbe_54.yaml` |
| provenance | `.interfaceforge/state.json` + `*_manifest.json` + `*_audit.{json,tsv,md}` | `.namdforge/state.json` + the same file shapes |
| safety | dry-run default, refuse-overwrite, `--execute` to submit | identical |

`pip install -e ".[interfaceforge]"` makes `inamd` import InterfaceForge's exact
implementations; `inamd plan` reports `compat.using_interfaceforge`.

## Typical combined run

```bash
# --- InterfaceForge: DFT-MD ---
iface vasp step1-prepare OPT
iface vasp step2-prepare Step1 --temperatures 300
iface vasp step2-launch Step2_300K --execute
#   ... wait for the trajectory ...

# --- NAMD Launcher: non-adiabatic dynamics ---
inamd init FAPI_namd && cd FAPI_namd
#   set source.trajectory: ../Step2_300K/<run>
inamd snapshots prepare
inamd waverun launch --chunk 100 --execute
inamd nac prepare && inamd nac run --execute && inamd nac collect
inamd dephase && inamd inicon
inamd hefei prepare && inamd hefei launch --execute
inamd shprop
```
