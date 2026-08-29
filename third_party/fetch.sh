#!/usr/bin/env bash
# Fetch the external scientific codes NAMD Launcher orchestrates. None of them
# are redistributed in this repo -- this script clones them (pinned) into
# third_party/_src/, which is git-ignored.
#
#   * CA-NAC             -- non-adiabatic couplings (stage `nac`)
#   * VaspBandUnfolding  -- vaspwfc/paw/spinorb, imported by CA-NAC
#   * Hefei-NAMD         -- the surface-hopping engine (Fortran; build after)
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${HERE}/_src"
mkdir -p "${SRC}"

CANAC_URL="https://github.com/WeibinChu/CA-NAC.git"
CANAC_REF="a1e0e24ba755549e87e30d675b704de27a1dbeaa"          # 2026-03-09

VBU_URL="https://github.com/QijingZheng/VaspBandUnfolding.git"
VBU_REF="3f8a6285b538cdec1d896e803e3d0800147fda88"            # 2026-04-27

HEFEI_NAMD_URL="https://github.com/QijingZheng/Hefei-NAMD.git"
HEFEI_NAMD_REF="master"   # no tagged releases upstream; pin a SHA for a frozen study

clone_or_update () {
  local url="$1" ref="$2" dir="$3"
  if [ -d "${SRC}/${dir}/.git" ]; then
    git -C "${SRC}/${dir}" fetch --all --tags --quiet
    git -C "${SRC}/${dir}" checkout -q "${ref}" || git -C "${SRC}/${dir}" checkout -q FETCH_HEAD
  else
    git clone --quiet "${url}" "${SRC}/${dir}"
    git -C "${SRC}/${dir}" checkout -q "${ref}" || true
  fi
  echo "  ${dir}: $(git -C "${SRC}/${dir}" rev-parse HEAD)"
}

echo "Fetching into ${SRC}"
clone_or_update "${CANAC_URL}"       "${CANAC_REF}"       "CA-NAC"
clone_or_update "${VBU_URL}"         "${VBU_REF}"         "VaspBandUnfolding"
clone_or_update "${HEFEI_NAMD_URL}"  "${HEFEI_NAMD_REF}"  "Hefei-NAMD"

cat <<EOF

Done. NAMD Launcher auto-discovers these under third_party/_src/.
(You can also point at your own installs with nac.canac_dir / nac.vaspwfc_dir /
namd.binary_dir in the campaign, or \$NAMDFORGE_CANAC_DIR / \$NAMDFORGE_VASPWFC_DIR.)

Next:
  * Build the engine:
      cd ${SRC}/Hefei-NAMD/src/dish && make      # DISH  -> ./dish
      cd ../namd && make                          # FSSH  -> ./namd
    (the Hefei-NAMD-DEV 'hfnamd' binary is built the same way from its own
     checkout -- see docs/hefei-namd.md.)
  * CA-NAC also needs: pip install ase scipy numpy
EOF
