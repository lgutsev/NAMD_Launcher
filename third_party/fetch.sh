#!/usr/bin/env bash
# Fetch the external scientific codes NAMD Launcher orchestrates. None of them
# are redistributed in this repo -- this script clones them (pinned) into
# third_party/_src/, which is git-ignored.
#
#   * CA-NAC             -- non-adiabatic couplings (stage `nac`)
#   * VaspBandUnfolding  -- vaspwfc/paw/spinorb, imported by CA-NAC
#   * Hefei-NAMD-DEV     -- default unified hfnamd engine (Fortran; build after)
#   * Hefei-NAMD         -- legacy master dish/namd engines (Fortran; build after)
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
HEFEI_NAMD_REF="b7c8fc5a27e89b85fbcd7ba67c41b38a99085d4e"

HEFEI_NAMD_DEV_URL="https://github.com/zhang-changwei/Hefei-NAMD-DEV.git"
HEFEI_NAMD_DEV_REF="b077863c9d7679b5d36df3f9af765b3d33f6ff45"  # v2025.01

clone_or_update () {
  local url="$1" ref="$2" dir="$3"
  if [ -d "${SRC}/${dir}/.git" ]; then
    git -C "${SRC}/${dir}" fetch origin --tags --quiet
  else
    git clone --quiet "${url}" "${SRC}/${dir}"
  fi
  # Every REF above is a full commit SHA. Fail instead of silently using a
  # moving branch tip when a pin is mistyped or no longer fetchable.
  git -C "${SRC}/${dir}" checkout --detach -q "${ref}"
  test "$(git -C "${SRC}/${dir}" rev-parse HEAD)" = "${ref}"
  echo "  ${dir}: $(git -C "${SRC}/${dir}" rev-parse HEAD)"
}

echo "Fetching into ${SRC}"
clone_or_update "${CANAC_URL}"       "${CANAC_REF}"       "CA-NAC"
clone_or_update "${VBU_URL}"         "${VBU_REF}"         "VaspBandUnfolding"
clone_or_update "${HEFEI_NAMD_DEV_URL}" "${HEFEI_NAMD_DEV_REF}" "Hefei-NAMD-DEV"
clone_or_update "${HEFEI_NAMD_URL}"  "${HEFEI_NAMD_REF}"  "Hefei-NAMD"

cat <<EOF

Done. NAMD Launcher auto-discovers these under third_party/_src/.
(You can also point at your own installs with nac.canac_dir / nac.vaspwfc_dir /
namd.binary_dir in the campaign, or \$NAMDFORGE_CANAC_DIR / \$NAMDFORGE_VASPWFC_DIR.)

Next:
  * Build the engine:
      cd ${SRC}/Hefei-NAMD-DEV && make -f linux/Makefile tdm  # default -> ./hfnamd
      cd ${SRC}/Hefei-NAMD/src/dish && make tdm                # master DISH -> ./dish
      cd ../namd && make tdm                                   # master FSSH -> ./namd
  * CA-NAC also needs: pip install ase scipy numpy
EOF
