# Hefei-NAMD

> **NAMD Launcher performs no non-adiabatic dynamics.** Every surface-hopping
> trajectory, every `SHPROP.*` file, is produced by Hefei-NAMD. Please cite the
> Hefei-NAMD papers and repository and acknowledge Qijing Zheng, Jin Zhao and
> the Hefei-NAMD group.
> Repository: <https://github.com/QijingZheng/Hefei-NAMD>
> Tutorials: <http://staff.ustc.edu.cn/~zqj/>

## Getting and building the engine

`third_party/fetch.sh` clones Hefei-NAMD (pinned) into `third_party/_src/`.

```bash
bash third_party/fetch.sh
cd third_party/_src/Hefei-NAMD/src/dish && make      # DISH   -> ./dish
cd ../namd && make                                   # FSSH   -> ./namd
```

Put the resulting binary on `PATH` (or point the `hefei_namd` profile job's
`command` at its full path).

### The DEV branch (`hfnamd`)

The reference workflow uses the **Hefei-NAMD-DEV** branch, whose MPI binary is
`hfnamd` and whose `&NAMDPARA` namelist takes `ALGO = "DISH" | "FSSH"`,
`ALGO_INT`, `LSHP`, `LCPTXT`, `DEBUGLEVEL` (see `src/namd_launcher/templates/
inp.dish`). If you have access to that branch, build it the same way and set
`namd.branch: dev` (the default). Otherwise use `namd.branch: master` and the
upstream `dish` / `namd` binaries — NAMD Launcher renders the correct namelist
for either.

## Inputs NAMD Launcher prepares

| file | produced by | notes |
|---|---|---|
| `EIGTXT` | `inamd nac collect` (`CAeig_*.txt`) | KS eigenvalues, `BMAX-BMIN+1` columns, one row per MD step |
| `NATXT` | `inamd nac collect` (`CAnac_*_re.txt`) | real NAC, `(BMAX-BMIN+1)²` columns |
| `DEPHTIME` | `inamd dephase` | Gaussian pure-dephasing matrix (fs), DISH only |
| `INICON` | `inamd inicon` | `NSAMPLE` rows of `<start step> <start band>` |
| `inp` | `inamd hefei prepare` | `&NAMDPARA` namelist |

`inamd hefei prepare` refuses to proceed unless `BMAX-BMIN+1` is consistent
across `inp`, `DEPHTIME`, `NATXT` and `EIGTXT`, and `NSW ≤` the number of NAC
frames.

## Parameter notes (from the reference workflow)

- **DISH** for recombination dynamics; **FSSH** for fast hot-carrier
  relaxation.
- `NSAMPLE` (initial conditions) and `NSW` (NAC frames) are the accuracy knobs.
  The reference runs used `NSAMPLE=10`, `NSW≈498` from a 25 ps trajectory and
  noted that `NSAMPLE=50`, `NSW≈1998` would be better (more VASP snapshots).
- The DEV branch's huge `NAMDTIME` (e.g. `1e7`) works because DISH replicates
  the NAC; do **not** do that with FSSH.
- `LHOLE=.FALSE.` follows the electron; `.TRUE.` follows the hole.
