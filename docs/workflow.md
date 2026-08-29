# The NAMD Launcher workflow

Each stage reads the previous stage's output, writes into a fixed directory,
and drops a manifest + audit. Nothing is overwritten without `--force`; nothing
is submitted without `--execute`.

```
campaign root/
├─ namd_campaign.yaml
├─ profiles/loni.yaml
├─ snapshots/          stage 1-3   (POSCARs, WAVECAR SCFs, KS diagnostics)
│  ├─ INCAR KPOINTS POTCAR
│  ├─ 001/ 002/ ... NSW/           POSCAR + linked inputs + (later) WAVECAR/EIGENVAL/PROCAR
│  ├─ input.py run_canac.sh                             (written by `nac prepare` / `nac run`)
│  └─ CAnac_*_re.txt CAeig_*.txt                        (written by the CA-NAC job)
├─ nac/               stage 4-5b  (NATXT EIGTXT energy.dat DEPHTIME INICON)
└─ namd/              stage 6-7   (inp + staged inputs, SHPROP.*, data.txt, shprop_fit.json)
```

## 1 · `inamd snapshots prepare`

Port of `FolderPrep.py` + `create_links.sh`.

- **Source** (`source.trajectory`): an `XDATCAR_FINAL` file, or an
  InterfaceForge Step2 run directory (its `XDATCAR`, `KPOINTS`, `POTCAR`,
  launcher are picked up automatically).
- Writes the **last `snapshots.nsw` frames** (at `snapshots.stride`) to
  `001/POSCAR` … `NSW/POSCAR` (VASP-5 Direct).
- Stages `INCAR` (from `snapshots.incar`, default the packaged `INCAR.nac`),
  `KPOINTS`, `POTCAR` at the `snapshots/` root and symlinks (or copies) them
  into every folder.
- **NBANDS** is chosen from the *reference* MD run, not guessed:
  1. explicit `bands.nbands` wins (but the audit WARNs if it is below the
     reference or below CA-NAC's stored window);
  2. otherwise the value the reference run actually used — read from its
     `OUTCAR`/`OUTCAR.gz` header, then its `INCAR` — is inherited (this is why
     the reference workflow's hand-written INCAR carried `NBANDS = 960`);
  3. raised to `nac.bmax_stored + bands.nbands_margin` (rounded up to
     `bands.nbands_round`) if the reference is short;
  4. if no reference NBANDS can be found, the `bmax_stored + margin` floor is
     used and the audit WARNs.
  `inamd snapshots prepare --dry-run` prints the full decision under `nbands`.

## 2 · `inamd waverun launch [--chunk N | --array]`

Port of `runvasp_range.sh`. One WAVECAR/eigenvalue SCF per folder.

- `--chunk N` writes one job per contiguous block of `N` folders (`001-100`,
  `101-200`, …) — "different nodes own different snapshot ranges", exactly the
  original pattern. Omit `--chunk` for one job over all folders. `--range A B`
  restricts the set.
- `--array` instead writes a single Slurm array job (`--array=1-NSW%throttle`),
  one task per folder.
- The VASP command comes from the profile's `vasp_nac` job.
- Dry run by default (writes the `*.sh`); `--execute` submits. Already-converged
  folders are skipped.
- `inamd waverun audit` classifies each folder PASS / WARN / PENDING.

## 3 · `inamd ksplot`

Optional KS-manifold sanity check before committing to NAC.

- Always: `bandgap_stats.json` — mean/std gap across the snapshot `EIGENVAL`s
  (port of `bandgap_stats.py`).
- If matplotlib is present and `bands.groups` is set: `ksen.png` — KS energy vs
  snapshot, points sized by each atom group's PROCAR projection (port of
  `tdksen_hydrogen.py`). `--no-plot` skips it.

## 4 · `inamd nac {prepare,run,collect}`

CA-NAC, driven by a generated `input.py`. CA-NAC is a **dependency you
install** (`third_party/fetch.sh`, or `nac.canac_dir` / `nac.vaspwfc_dir`), not
vendored code — see [ca-nac.md](ca-nac.md).

- `prepare` renders **only** `snapshots/input.py` from the campaign `nac:`
  block (CA-NAC's `./001/` paths resolve because the job `cd`s there) and
  reports which CA-NAC / vaspwfc install it resolved.
- `run` submits `python input.py` under the `canac` job, prepending the
  resolved directories to `PYTHONPATH`. Refuses if CA-NAC is unresolvable
  unless `--allow-missing`.
- `collect` maps the outputs:
  `CAnac_*_re.txt → nac/NATXT`, `CAeig_*.txt → nac/EIGTXT` and `nac/energy.dat`.
  The audit checks `NATXT` has `(BMAX-BMIN+1)²` columns, `EIGTXT` has
  `BMAX-BMIN+1`, and the two row counts agree.

## 5a · `inamd dephase`

Port of `Dephase.py`. `nac/energy.dat → nac/DEPHTIME` (Gaussian pure-dephasing
time per state pair, fs). Reports the **mean off-diagonal** and WARNs outside
`dephasing.expect_min_fs … expect_max_fs` (perovskites: a few fs, well under 20;
the reference workflow gets ≈ 7 fs).

## 5b · `inamd inicon`

Port of `INICON_gen.sh`. `nac/INICON` with `inicon.nsample` rows of
`<start_step> <start_band>`, drawn from `[1, tmax]` × `[band_min, band_max]`,
**deterministic** given `inicon.seed`. WARNs if `tmax` exceeds the NAC frame
count.

## 6 · `inamd hefei {prepare,launch}`

- `prepare` renders `namd/inp`:
  - `namd.branch: dev` → `inp.dish` / `inp.fssh` templates, binary `hfnamd`,
    `ALGO="DISH"|"FSSH"`, `ALGO_INT`, `LSHP`, `LCPTXT`, `DEBUGLEVEL` — matches
    the source workflow.
  - `namd.branch: master` → explicit `&NAMDPARA` with `LDISH`+`DIINIT` (DISH,
    binary `dish`) or `LSHP` (FSSH, binary `namd`); needs `NBANDS`.
  - Cross-checks `nbasis = BMAX-BMIN+1` against `DEPHTIME` dimensions,
    `NATXT`/`EIGTXT` column counts, `NSW ≤ NAC frames`, `NSAMPLE ≤ INICON rows`
    — and **refuses** to prepare if any fails.
  - Stages `NATXT`, `EIGTXT`, `INICON` (+ `DEPHTIME` for DISH) into `namd/`.
- `launch` renders `namd/run_namd.sh` from the `hefei_namd` job and submits.

## 7 · `inamd shprop`

Ports `SHPROP_avg.sh` + `plot_SHPROP_data.py`.

- Row-wise mean of `analysis.shprop_column` across every `namd/SHPROP.*` →
  `namd/data.txt`.
- Fits `p(t) = exp(-t / A)` (time converted from `analysis.time_in` to
  `analysis.fit_time_unit`). `A` is τ. Writes `shprop_fit.json` (τ, unit, R²)
  and `shprop_fit.png`. WARNs if R² < 0.9.

## Whole-campaign

- `inamd audit` — every stage audit, rolled up.
- `inamd status` — one compact line per stage.
- `inamd run [--execute]` — advance every ready local stage; never submits a
  cluster job.
