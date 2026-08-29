#!/usr/bin/env bash
# Fetch the compiled / importable third-party dependencies of NAMD Launcher.
#
#   * Hefei-NAMD     -- the surface-hopping engine (Fortran; build it after).
#   * VaspBandUnfolding -- provides vaspwfc/paw/spinorb imported by CA-NAC.
#
# Pinned to exact commits for reproducibility. Re-run to update the pins here.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${HERE}/_src"
mkdir -p "${SRC}"

HEFEI_NAMD_URL="https://github.com/QijingZheng/Hefei-NAMD.git"
HEFEI_NAMD_REF="master"          # no tagged releases upstream; pin a SHA for a frozen study

VBU_URL="https://github.com/QijingZheng/VaspBandUnfolding.git"
VBU_REF="3f8a6285b538cdec1d896e803e3d0800147fda88"   # 2026-04-27

clone_or_update () {
  local url="$1" ref="$2" dir="$3"
  if [ -d "${SRC}/${dir}/.git" ]; then
    git -C "${SRC}/${dir}" fetch --depth 1 origin "${ref}"
    git -C "${SRC}/${dir}" checkout -q "${ref}" || git -C "${SRC}/${dir}" checkout -q FETCH_HEAD
  else
    git clone "${url}" "${SRC}/${dir}"
    git -C "${SRC}/${dir}" checkout -q "${ref}" || true
  fi
  echo "  ${dir}: $(git -C "${SRC}/${dir}" rev-parse HEAD)"
}

echo "Fetching into ${SRC}"
clone_or_update "${HEFEI_NAMD_URL}" "${HEFEI_NAMD_REF}" "Hefei-NAMD"
clone_or_update "${VBU_URL}" "${VBU_REF}" "VaspBandUnfolding"

cat <<'EOF'

Next steps:
  * Build the engine:
      cd third_party/_src/Hefei-NAMD/src/dish && make      # DISH  -> ./dish
      cd ../namd && make                                    # FSSH  -> ./namd
    (the Hefei-NAMD-DEV `hfnamd` binary, if you use it, is built the same way
     from its own checkout -- see docs/hefei-namd.md.)
  * Expose the CA-NAC imports:
      export PYTHONPATH="$PWD/third_party/_src/VaspBandUnfolding:$PYTHONPATH"
EOF
