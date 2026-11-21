# Value checks (`inamd check`)

The stage audits check shapes: folders exist, files have the right columns. Two read-only checks look at the
numbers, at the two points where a wrong number would carry into NAMD unnoticed.

| When | Command | Writes | Asks |
|---|---|---|---|
| after the snapshot SCFs, before `inamd nac run` or NAMD | `inamd check edges` | `checks/check_edges.{json,md}` | Is the band window (`nac.bmin`–`nac.bmax`) an isolated pair of states that keeps its identity over the trajectory? |
| after `inamd nac collect` | `inamd check nac` | `nac/check_nac.{json,md}` | Are NATXT/EIGTXT complete, antisymmetric, free of isolated spikes, and do their energies match the snapshot EIGENVALs? |

Each writes a verdict: `PASS`, `WARN` (a person reads the report before the next stage) or `FAIL`. The exit code is 0
for PASS and WARN and 3 for FAIL; `--strict` makes WARN exit 3 too.

## `check edges`

Reads, for every snapshot folder:
- EIGENVAL: the gap between `bands.vbm` and `bands.cbm`, and the distance from the window's edges to the nearest band
  outside it (`nac.bmin - 1` below, `nac.bmax + 1` above);
- PROCAR (LORBIT 11), when present: each window band's make-up by element (fractions of the `tot` column).

It flags:
- **Neighbour within `--degenerate-ev`** (default kT at 300 K, 0.0259 eV). Population could reach a state the window
  leaves out.
- **Make-up drift > `--drift`** (default 0.25) from frame 1, as the total-variation distance between the element
  fractions (0 means the same make-up, 1 means disjoint). The band has changed identity, e.g. a molecular or surface
  state has taken over a band edge.

For the most changed frames (`--detail`, default 8) and any listed with `--frames`, it breaks bands
`bmin-1`…`bmax+1` down:
- by atom (index, element, height z), and by element and z to 1 Å;
- by molecule. Atoms are grouped by covalent bonds (radii × 1.15, minimum image). A group counts as the
  framework if it has over 40 atoms, holds a B-site metal (Pb, Sn, Ge, Bi), or is made only of halides: stretched
  Pb–I bonds (over 3.28 Å) fall outside the cutoff and would otherwise split the lattice into small "molecules".
  All framework weight is reported as one entry. Each group gets its formula, atom indices, share of the band, and depth below the nearer slab face. The
  slab normal is the lattice direction with the widest vacuum gap of 5 Å or more.
- For the leading molecule (≥ 10 % of the band): its heavy-atom bonds and angles and its largest X–H change, each
  against the same atoms in frame 1, and whether those atoms were the same molecule in frame 1. A band edge on a
  distorted or broken molecule shows up here.

It also inventories CA-NAC's `*.npy` overlap caches and the stored window. At CA-NAC a1e0e24 with `icor 1`, the
`tdolap_<stored window>` caches hold the phase-corrected overlaps for the whole stored window, so a wider NAC window
inside it can be recomputed from the caches without the WAVECARs. Keep the caches if that may be needed.

PROCAR parsing reads most of each file (the window bands sit deep in it). For hundreds of frames, run it as a batch
job, not on a login node.

## `check nac`

- **Columns:** nbasis² and nbasis.
- **Rows:** NATXT and EIGTXT agree, equal `snapshots.nsw - 1` or `snapshots.nsw`, and cover `namd.nsw`.
- **Values:** all finite.
- **Diagonal:** about 0 (WARN otherwise).
- **Antisymmetry:** max |d_ij + d_ji| ≤ 1 % of max |d_ij| passes, ≤ 10 % warns, above that fails.
- **Spikes:** max/median of |d_ij| ≤ 50, otherwise WARN with the rows; real crossings give spikes, so read them.
- **Energies:** each EIGTXT row is compared with frame i+1's EIGENVAL, and with the mean of frames i+1 and i+2. The
  better alignment is reported: ≤ `--energy-tol` (1 meV) passes, ≤ 50 meV warns, above that fails.
