#!/usr/bin/env bash
# Run OpenROAD-flow-scripts for one lane with the shared config, then write reports.
#   flow/orfs/run.sh <sv|arch> [make-target]      (default target: finish)
# Env: ORFS_ROOT (checkout of OpenROAD-flow-scripts), OPENROAD_EXE, YOSYS_EXE.
# Results land in $ORFS_ROOT/flow/{results,logs,reports}/sky130hd/ibex_top_<lane>/.
set -uo pipefail
lane="${1:?lane}"; target="${2:-finish}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ORFS_ROOT="${ORFS_ROOT:-$HOME/github/OpenROAD-flow-scripts}"
export OPENROAD_EXE="${OPENROAD_EXE:-$HOME/.local/bin/openroad}"
export YOSYS_EXE="${YOSYS_EXE:-/opt/homebrew/bin/yosys}"
export ARCH_IBEX_ROOT="$REPO_ROOT"
[ -d "$ORFS_ROOT/flow" ] || { echo "ORFS_ROOT=$ORFS_ROOT has no flow/ directory" >&2; exit 2; }
cd "$ORFS_ROOT/flow"
start=$(date +%s)
make DESIGN_CONFIG="$REPO_ROOT/flow/orfs/$lane/config.mk" "$target" 2>&1 | tee "$REPO_ROOT/flow/out/$lane/orfs_${target}.log"
rc=${PIPESTATUS[0]}
echo "[$lane] make $target exit=$rc in $(( $(date +%s) - start )) s"
exit $rc
