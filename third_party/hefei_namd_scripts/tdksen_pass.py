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
# calculate spatial localization
############################################################
nsw     = 500
dt      = 1.0
nproc   = 48
prefix  = '.'
runDirs = [prefix + '/{:03d}'.format(ii + 1) for ii in range(nsw)]
# which spin, index starting from 0
whichS  = 0
# which k-point, index starting from 0
whichK  = 0
# which atoms, index starting from 0
whichA = np.arange(177 - 1, 257)  # Iodine (adjusted for 0-based indexing)
whichB = np.arange(311 - 1, 337)  # Lead (adjusted for 0-based indexing)
whichC = np.concatenate([
    np.arange(165 - 1, 176),  # H atoms (adjusted for 0-based indexing)
    np.arange(27 - 1, 34),    # C atoms (adjusted for 0-based indexing)
    [310 - 1]                 # Single N atom (adjusted for 0-based indexing)
])
Alabel  = r'Iodine'
Blabel  = r'Lead'
Clabel  = r'Passivant'

if os.path.isfile('all_wht.npy'):
    Wht = np.load('all_wht.npy')
    Enr = np.load('all_en.npy')
else:
    # Calculate localization for Iodine, Lead, and Passivant
    Enr, WhtA = parallel_wht(runDirs, whichA, nproc=nproc)
    _, WhtB = parallel_wht(runDirs, whichB, nproc=nproc)
    _, WhtC = parallel_wht(runDirs, whichC, nproc=nproc)

    Enr = Enr[:, whichS, whichK, :]
    WhtA = WhtA[:, whichS, whichK, :]
    WhtB = WhtB[:, whichS, whichK, :]
    WhtC = WhtC[:, whichS, whichK, :]

    np.save('all_wht.npy', [WhtA, WhtB, WhtC])
    np.save('all_en.npy', Enr)

############################################################
# Plot data for all three groups
############################################################
fig = plt.figure()
fig.set_size_inches(4.8, 3.0)

ax = plt.subplot()
nband = Enr.shape[1]
T, dump = np.mgrid[0:nsw:dt, 0:nband]

# Plot Iodine
img1 = ax.scatter(
    T, Enr,
    s=WhtA / WhtA.max() * 10,  # Scale by maximum weight
    color='blue', lw=0.0, zorder=1, label=Alabel
)

# Plot Lead
img2 = ax.scatter(
    T, Enr,
    s=WhtB / WhtB.max() * 10,  # Scale by maximum weight
    color='red', lw=0.0, zorder=2, label=Blabel
)

# Plot Passivant
img3 = ax.scatter(
    T, Enr,
    s=WhtC / WhtC.max() * 10,  # Scale by maximum weight
    color='green', lw=0.0, zorder=3, label=Clabel
)

# Customize the plot
ax.set_xlim(0, nsw)
ax.set_ylim(-3, 1)
ax.set_xlabel('Time [fs]', fontsize=None, labelpad=5)
ax.set_ylabel('Energy [eV]', fontsize=None, labelpad=8)
ax.tick_params(which='both', labelsize='x-small')
ax.legend(fontsize="small", loc="upper right")

plt.tight_layout(pad=0.2)
plt.savefig('ksen_wht_three_groups.png', dpi=360)

