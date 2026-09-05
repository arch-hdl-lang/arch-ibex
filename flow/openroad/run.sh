#!/usr/bin/env bash
# sky130hd place-and-route of one lane's synthesised ibex_top with OpenROAD's
# regression flow (no OpenROAD-flow-scripts needed).
#   flow/openroad/run.sh <sv|arch>
# Inputs : flow/out/<lane>/sky130/netlist.v (from flow/sky130_synth.sh) and its
#          synth.stat (the die is sized from the synthesised area at UTIL %).
# Outputs: flow/out/<lane>/openroad/{results/,openroad.log,final_*.rpt} and copies
#          review-package/reports/<lane>_openroad_final_{area,timing,power}.rpt,
#          <lane>_openroad_final_metrics.txt
# Env: OPENROAD_EXE, OPENROAD_TEST (default ~/github/OpenROAD/test), UTIL (default 50).
set -uo pipefail
lane="${1:?lane (sv|arch)}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export OPENROAD_TEST="${OPENROAD_TEST:-$HOME/github/OpenROAD/test}"
OPENROAD_EXE="${OPENROAD_EXE:-$HOME/.local/bin/openroad}"
UTIL="${UTIL:-50}"
in="$REPO_ROOT/flow/out/$lane/sky130"
[ -f "$in/netlist.v" ] || { echo "[$lane] missing $in/netlist.v (run flow/sky130_synth.sh)"; exit 2; }
area=$(grep -oE "Chip area for module '\\\\ibex_top': [0-9.]+" "$in/synth.stat" | grep -oE '[0-9.]+$')
# Square die holding the synthesised area at UTIL % core utilisation, plus a
# 10 um core margin on each side; the same rule on both lanes (ORFS's
# CORE_UTILIZATION semantics), rounded up to a whole micron.
side=$(python3 -c "import math; print(math.ceil(math.sqrt($area/($UTIL/100.0))) + 20)")
out="$REPO_ROOT/flow/out/$lane/openroad"; mkdir -p "$out/results"
export LANE="$lane" NETLIST="$in/netlist.v" SDC="$REPO_ROOT/flow/openroad/constraint.sdc" DIE_SIDE="$side" RESULTS_DIR="$out/results" OUT="$out"
echo "[$lane] synthesised area ${area} um2, UTIL=${UTIL}% -> die ${side}x${side} um"
start=$(date +%s)
"$OPENROAD_EXE" -exit -no_init "$REPO_ROOT/flow/openroad/lane.tcl" > "$out/openroad.log" 2>&1
rc=$?
echo "[$lane] openroad exit=$rc in $(( $(date +%s) - start )) s"
R="$REPO_ROOT/review-package/reports"
for f in final_area.rpt final_timing.rpt final_power.rpt final_metrics.txt; do
  [ -f "$out/$f" ] && cp "$out/$f" "$R/${lane}_openroad_$f"
done
exit $rc
