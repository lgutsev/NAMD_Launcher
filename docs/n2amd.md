# N²AMD research preview

> **Support level: research preview, not part of the production pipeline.**
> `inamd n2amd {status,plan,export}` only scopes a possible future study. It
> does not train HamGNN, predict Hamiltonians, calculate NACs, or submit jobs.

The supported workflow is:

```text
InterfaceForge trajectory
  -> VASP snapshot SCFs
  -> CA-NAC
  -> dephasing / INICON
  -> Hefei-NAMD
  -> SHPROP analysis
```

## Why N²AMD is de-emphasized

N²AMD uses an E(3)-equivariant HamGNN model to predict electronic
Hamiltonians in a numerical atomic-orbital (NAO) basis. The 2025 work
demonstrated efficient classical-path NAMD with Hefei-NAMD, including
hybrid-functional calculations:

- Zhang et al., *Advancing nonadiabatic molecular dynamics simulations in
  solids with E(3) equivariant deep neural Hamiltonians*, **Nature
  Communications 16** (2025), DOI: 10.1038/s41467-025-57328-1.
- HamGNN: <https://github.com/QuantumLab-ZY/HamGNN>
- N²AMD code and tutorial: <https://doi.org/10.6084/m9.figshare.26629405>

For a passivated Pb/I perovskite slab, however, this is a separate research
project rather than an easy launcher stage. A useful model would have to cover
the heavy-element/SOC treatment, surface and vacuum geometries, organic
passivants, defects, distortions, and interfacial electronic states. Its
electronic labels must come from a compatible NAO code and be cross-validated
against the intended VASP reference.

## Correct feasibility assessment

| item | assessment |
|---|---|
| Reusing an InterfaceForge trajectory | feasible for geometries |
| VASP as HamGNN label source | not direct; VASP does not emit the compatible NAO Hamiltonian/overlap representation |
| Label backends | OpenMX, ABACUS, or SIESTA/HONPAS |
| Training-set size | system dependent; published examples used 300–2000 structures, not a universal requirement |
| PBE usefulness | possible for large, long, or repeated calculations; HSE06 is an important motivation, not the only one |
| Pb/I systems | SOC treatment and parity against direct calculations are mandatory decisions |
| Current launcher support | scoping commands only |

Current HamGNN uses `graph_data.npz` and optionally LMDB. Prediction also
requires backend-specific graph construction and overlap/H0 preprocessing; the
operational input is therefore more than an `XDATCAR` alone.

## Safest future integration

Do not write a new direct `NATXT` converter. Current CA-NAC already supports
`software='HAMGNNHUGE'` and reads per-frame eigenvector, eigenvalue, and sparse
overlap arrays. A future production implementation should be:

```text
NAO reference data
  -> graph_data.npz / LMDB
  -> HamGNN training and prediction
  -> per-frame wfc.npy + eigen.npy + SKS*.npy
  -> CA-NAC HAMGNNHUGE backend
  -> EIGTXT + NATXT
  -> existing dephase / INICON / Hefei-NAMD stages
```

This matters because Hefei-NAMD expects CA-NAC's phase-corrected,
antisymmetrized overlap numerator in `NATXT` and applies its own
`1/(2*POTIM)` scaling. A file containing already differentiated couplings can
have the right dimensions while being physically mis-scaled.

Before enabling such a path, require held-out parity tests for:

1. Hamiltonian and band-edge errors;
2. generalized eigenvectors and overlap convention;
3. state ordering, phase continuity, and trivial crossings;
4. `EIGTXT` energy units and `NATXT` normalization;
5. direct-DFT versus predicted NAC time series;
6. final population dynamics and lifetime sensitivity.

## Newer on-the-fly work

The August 2026 on-the-fly N²AMD work adds excited-state forces and NAC vectors
beyond a fixed classical trajectory (arXiv:2608.08095). That is scientifically
distinct from this launcher's classical-path workflow and is not presented as
a drop-in step here.
