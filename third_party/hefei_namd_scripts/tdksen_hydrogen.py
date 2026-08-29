#!/usr/bin/env python
############################################################
import os, re
import numpy as np
from glob import glob

import matplotlib as mpl
mpl.use('agg')
mpl.rcParams['axes.unicode_minus'] = False

import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from mpl_toolkits.axes_grid1 import make_axes_locatable
############################################################
def WeightFromPro(infile='PROCAR', whichAtom=None, spd=None):
    """
    Contribution of selected atoms to the each KS orbital
    """

    print(infile) 
    assert os.path.isfile(infile), '%s cannot be found!' % infile
    FileContents = [line for line in open(infile) if line.strip()]

    # when the band number is too large, there will be no space between ";" and
    # the actual band number. A bug found by Homlee Guo.
    # Here, #kpts, #bands and #ions are all integers
    nkpts, nbands, nions = [int(xx) for xx in re.sub('[^0-9]', ' ', FileContents[1]).split()]

    if spd:
        Weights = np.asarray([line.split()[1:-1] for line in FileContents
                              if not re.search('[a-zA-Z]', line)], dtype=float)
        Weights = np.sum(Weights[:,spd], axis=1)
    else:
        Weights = np.asarray([line.split()[-1] for line in FileContents
                              if not re.search('[a-zA-Z]', line)], dtype=float)
    
    nspin = Weights.shape[0] // (nkpts * nbands * nions)
    Weights.resize(nspin, nkpts, nbands, nions)

    Energies = np.asarray([line.split()[-4] for line in FileContents
                            if 'occ.' in line], dtype=float)
    Energies.resize(nspin, nkpts, nbands)
    
    if whichAtom is None:
        return Energies, np.sum(Weights, axis=-1)
    else:
        # whichAtom = [xx - 1 for xx in whichAtom]
        return Energies, np.sum(Weights[:,:,:,whichAtom], axis=-1)

def parallel_wht(runDirs, whichAtoms, nproc=None):
    '''
    calculate localization of some designated in parallel.
    '''
    import multiprocessing
    nproc = multiprocessing.cpu_count() if nproc is None else nproc
    pool = multiprocessing.Pool(processes=nproc)

    results = []
    for rd in runDirs:
        res = pool.apply_async(WeightFromPro, (rd + '/PROCAR', whichAtoms, None,))
        results.append(res)

    enr = []
    wht = []
    for ii in range(len(results)):
        tmp_enr, tmp_wht = results[ii].get()
        enr.append(tmp_enr)
        wht.append(tmp_wht)

    return np.array(enr), np.array(wht)

############################################################
# Parameters and Atom Groups
############################################################
nsw = 500
dt = 1.0
nproc = 48
prefix = "."
run_dirs = [f"{prefix}/{i:03d}" for i in range(1, nsw + 1)]
whichS = 0  # Spin index (0-based)
whichK = 0  # k-point index (0-based)

# Atom groups (adjusted for 0-based indexing)
whichA = np.arange(177 - 1, 257)  # Iodine
whichB = np.arange(311 - 1, 337)  # Lead
whichH = np.arange(131 - 1, 140)  # Hydrogen

# Labels
Alabel = "Iodine"
Blabel = "Lead"
Hlabel = "Hydrogen"

############################################################
# Calculate Weights
############################################################
if os.path.isfile("all_wht.npy"):
    WhtA, WhtB, WhtH = np.load("all_wht.npy", allow_pickle=True)
    Enr = np.load("all_en.npy")
else:
    Enr, WhtA = parallel_wht(run_dirs, whichA, nproc=nproc)
    _, WhtB = parallel_wht(run_dirs, whichB, nproc=nproc)
    _, WhtH = parallel_wht(run_dirs, whichH, nproc=nproc)

    Enr = Enr[:, whichS, whichK, :]
    WhtA = WhtA[:, whichS, whichK, :]
    WhtB = WhtB[:, whichS, whichK, :]
    WhtH = WhtH[:, whichS, whichK, :]

    np.save("all_wht.npy", [WhtA, WhtB, WhtH])
    np.save("all_en.npy", Enr)

############################################################
# Plot Contributions
############################################################
fig, ax = plt.subplots(figsize=(8, 6))
nband = Enr.shape[1]
T, dump = np.mgrid[0:nsw:dt, 0:nband]

# Plot contributions
ax.scatter(T, Enr, s=WhtA / WhtA.max() * 10, color="blue", lw=0, label=Alabel)  # Iodine
ax.scatter(T, Enr, s=WhtB / WhtB.max() * 10, color="red", lw=0, label=Blabel)   # Lead
ax.scatter(T, Enr, s=WhtH / WhtH.max() * 30, color="black", lw=0, label=Hlabel) # Hydrogen (larger size)

# Customize plot appearance
ax.set_xlim(0, nsw)
ax.set_ylim(-3.2, -0.2)
ax.set_xlabel("Time [fs]")
ax.set_ylabel("Energy [eV]")
ax.legend(fontsize="small", loc="center right")
ax.grid(color="lightgray", linestyle="--", linewidth=0.5)

# Save the plot
plt.tight_layout()
plt.savefig("ksen_hydrogen_focus.png", dpi=360)

