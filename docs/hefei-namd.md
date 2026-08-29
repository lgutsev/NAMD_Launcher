# Hefei-NAMD

> **NAMD Launcher performs no non-adiabatic dynamics.** Every surface-hopping
> trajectory, every `SHPROP.*` file, is produced by Hefei-NAMD. Please cite the
> Hefei-NAMD papers and repository and acknowledge Qijing Zheng, Jin Zhao and
> the Hefei-NAMD group.
> Original repository: <https://github.com/QijingZheng/Hefei-NAMD>
> N²AMD/DEV repository: <https://github.com/zhang-changwei/Hefei-NAMD-DEV>
> Tutorials: <http://staff.ustc.edu.cn/~zqj/>

## Getting and building the engine

NAMD Launcher ships **no** Hefei-NAMD code. `third_party/fetch.sh` clones fixed
commits of both the public DEV engine and the original master implementation
into `third_party/_src/`; build the branch selected by the campaign:

```bash
bash third_party/fetch.sh
cd third_party/_src/Hefei-NAMD-DEV
make -f linux/Makefile tdm                           # DEV DISH/FSSH -> ./hfnamd

cd ../Hefei-NAMD/src/dish && make tdm                # master DISH -> ./dish
cd ../namd && make tdm                               # master FSSH -> ./namd
```

NAMD Launcher finds the binary via `namd.binary_dir` in the campaign, then the
matching pinned checkout under `third_party/_src/`, then `$PATH`. `inamd hefei
audit` reports which; if none resolves, the `hefei_namd` job's own `command`
(a full path is fine) still runs. You can also point that job's `command`
straight at the binary.

### The DEV branch (`hfnamd`)

The reference workflow and N²AMD paper use the public, MIT-licensed
**Hefei-NAMD-DEV** repository, whose MPI binary is `hfnamd` and whose
`&NAMDPARA` namelist takes `ALGO = "DISH" | "FSSH"`,
`ALGO_INT`, `LSHP`, `LCPTXT`, `DEBUGLEVEL` (see `src/namd_launcher/templates/
inp.dish`). Set `namd.branch: dev` (the default). The original master
repository remains supported through `namd.branch: master`; the launcher
renders its older namelist and selects `dish` or `namd`. Leave the profile's
`hefei_namd.command` unset to preserve automatic selection; a configured
command is an intentional site-specific override.

## Inputs NAMD Launcher prepares

| file | produced by | notes |
|---|---|---|
| `EIGTXT` | `inamd nac collect` (`CAeig_*.txt`) | KS eigenvalues, `BMAX-BMIN+1` columns, one row per MD step |
| `NATXT` | `inamd nac collect` (`CAnac_*_re.txt`) | real NAC, `(BMAX-BMIN+1)²` columns |
| `DEPHTIME` | `inamd dephase` | Gaussian pure-dephasing matrix (fs), DISH only |
| `INICON` | `inamd inicon` | `NSAMPLE` rows of `<start step> <start band>` |
| `inp` | `inamd hefei prepare` | `&NAMDPARA` namelist |

`inamd hefei prepare` refuses to proceed unless `BMAX-BMIN+1` is consistent
across `inp`, `DEPHTIME`, `NATXT` and `EIGTXT`, `NSW ≤` the number of NAC
frames, and every `INICON` band and start time is valid for the requested
algorithm.

## Parameter notes (from the reference workflow)

- **DISH** for recombination dynamics; **FSSH** for fast hot-carrier
  relaxation.
- `NSAMPLE` (initial conditions) and `NSW` (NAC frames) are the accuracy knobs.
  The reference runs used `NSAMPLE=10`, `NSW≈498` from a 25 ps trajectory and
  noted that `NSAMPLE=50`, `NSW≈1998` would be better (more VASP snapshots).
- The DEV branch's huge `NAMDTIME` (e.g. `1e7`) works because DISH replicates
  the NAC; do **not** do that with FSSH.
- `LHOLE=.FALSE.` follows the electron; `.TRUE.` follows the hole.
