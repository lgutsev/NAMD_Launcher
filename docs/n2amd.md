# N2AMD as an optional step 3 — feasibility

> **Status: not implemented.** `inamd n2amd {status,plan,export}` are scoping
> aids only. This document is the assessment the user asked for.

## What N2AMD is

**N²AMD** (Neural-Network Non-Adiabatic Molecular Dynamics) replaces the
DFT/CA-NAC evaluation of the electronic structure along an AIMD path with an
**E(3)-equivariant deep Hamiltonian** (HamGNN). The model maps each instantaneous
geometry directly to a Kohn–Sham Hamiltonian matrix — no SCF — from which
eigenvalues, wavefunction overlaps and non-adiabatic couplings are obtained.
Those feed **Hefei-NAMD** with DISH under the classical-path approximation,
i.e. exactly the same downstream path this launcher already drives.

- Zhang et al., *Advancing nonadiabatic molecular dynamics simulations in
  solids with E(3) equivariant deep neural Hamiltonians*, **Nat. Commun.**
  **16** (2025); arXiv:2408.06654.
- HamGNN: <https://github.com/QuantumLab-ZY/HamGNN>
- N2AMD code: Figshare (linked from the paper); interfaces to HamGNN and
  Hefei-NAMD.
- Validated on TiO₂ and GaAs at HSE06; corrects order-of-magnitude carrier-
  dynamics errors from the standard procedure in a MoS₂/WS₂ heterostructure.

## Where it slots into this workflow

It **replaces stages 2 + 4** (`waverun` + `nac`):

```
                     ┌─ CA-NAC path:  snapshots ─▶ waverun (500 VASP SCF) ─▶ nac ─┐
Step2 XDATCAR  ──────┤                                                            ├─▶ EIGTXT / NATXT ─▶ dephase ─▶ inicon ─▶ hefei ─▶ shprop
                     └─ N2AMD path:   train HamGNN ─▶ predict H(t) ─▶ eig + NAC ──┘
```

Everything from `inamd dephase` onward is **unchanged** — N2AMD just has to
write `nac/EIGTXT` and `nac/NATXT` in the same format `inamd nac collect` does.

## Integration cost (honest)

| item | difficulty | note |
|---|---|---|
| Downstream hand-off | **easy** | same two text files; `dephase`/`inicon`/`hefei`/`shprop` already consume them |
| HamGNN install | easy–moderate | torch + e3nn + GPU; `inamd n2amd status` probes for these |
| **Training data** | **hard — the real blocker** | needs 500–2000 DFT Hamiltonians *in an LCAO basis*. **VASP cannot export one.** You must generate them with openmx / ABACUS / HONPAS (or the N2AMD pipeline), which means a second DFT stack and a basis-set convergence study for the target chemistry |
| HSE06 references | expensive | the *reason* to use N2AMD is hybrid-functional NAC; HSE06 on a 3×3×3 FAPI cell is ~10–50× a PBE SCF, ×(500–2000 structures) |
| Transferability | study required | the model must hold across the thermal ensemble and any strain/defect configs of interest; needs a held-out eigenvalue + NAC parity check vs direct DFT |

## Recommendation

For the current PBE-level perovskite runs, N2AMD offers **no advantage** — the
CA-NAC path is already parallel and cheap enough. N2AMD becomes worth the
integration effort when you want **hybrid-functional (HSE06) NAC**, **much
larger cells**, or **ns-scale trajectories** where re-running 10³–10⁴ VASP SCFs
is the bottleneck. At that point the plan is:

1. `inamd n2amd export` — freeze the trajectory + band window, get the checklist.
2. Stand up the LCAO-DFT reference stack; generate the training set.
3. Train HamGNN; validate eigenvalue + NAC parity on held-out frames.
4. Predict `H(t)` over the Step2 `XDATCAR`; emit `nac/EIGTXT` + `nac/NATXT`.
5. `inamd dephase && inamd inicon && inamd hefei prepare && inamd hefei launch --execute`.

A future `namdforge` release could add `inamd n2amd train` / `inamd n2amd
predict` around steps 2–4 once the reference-data path is settled.
