"""NAMD Launcher (namdforge).

A CLI-first orchestration layer for the ab-initio non-adiabatic molecular
dynamics workflow:

    VASP AIMD  ->  snapshot WAVECARs  ->  CA-NAC  ->  dephasing / INICON
               ->  Hefei-NAMD (surface hopping)  ->  SHPROP averaging + fit

It is a *launcher only*. All non-adiabatic dynamics is performed by
Hefei-NAMD (Q. Zheng, J. Zhao et al.); non-adiabatic couplings are evaluated
by CA-NAC (W. Chu & O. V. Prezhdo). See the README "Acknowledgements".

Conventions deliberately mirror InterfaceForge so the two interoperate: an
``iface vasp step2-*`` run directory is a first-class input here.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
