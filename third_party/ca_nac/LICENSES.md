# CA-NAC — license status

## `mod_hungarian.py` — GNU GPL v2.0 or later

The file header reads:

> Copyright (C) 2018 Alexey V. Akimov
> This file is distributed under the terms of the GNU General Public License
> as published by the Free Software Foundation, either version 2 of the
> License, or (at your option) any later version.

It is redistributed here **unmodified** under the GPL-2.0-or-later. Because it
is a separate, independently-usable module invoked only as an optional
state-reordering step (`nac.is_reorder: true`), it does not change the license
of NAMD Launcher's own code, but anyone redistributing this directory must
carry the GPL text and offer the corresponding source. The canonical source is
the Libra project: https://github.com/Quantum-Dynamics-Hub/libra-code

## `CAnac.py`, `aeolap.py`

The upstream CA-NAC repository (https://github.com/WeibinChu/CA-NAC) does not
include an explicit LICENSE file. These files are redistributed here in good
faith for research use, unmodified, with full attribution (see `PROVENANCE.md`)
and the citation the authors request. If you are the author and want a
different arrangement, please open an issue on NAMD Launcher.

Users must have their own legal access to VASP. The optional AE-NAC path
additionally needs a VASP source patch obtained directly from the CA-NAC
authors.
