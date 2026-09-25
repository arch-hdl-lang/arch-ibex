#!/usr/bin/env bash
# Pre-route timing estimate of one lane's synthesised netlist: routed WNS of
# flow/openroad/run.sh ~= t3_repaired_lat - 1.5 ns (tiers, calibration and known
# misses in estimate.tcl). Same inputs, die rule and SDC as run.sh.
#   flow/openroad/estimate.sh <sv|arch> [synth_dir]
# synth_dir defaults to flow/out/<lane>/sky130 (netlist_sta.v + synth.stat).
# Outputs {pre,place}.log and est.txt (the EST lines) in EST_OUT
# (default flow/out/<lane>/estimate).
# Env: OPENROAD_EXE, OPENROAD_TEST, UTIL (default 25, as run.sh),
#      TIMING_DRIVEN_GPL (as lane.tcl), EST_MODES (default "pre place"),
#      EST_CLOCK_LATENCY (ns, default 4.0: modelled clock insertion delay).
set -uo pipefail
lane="${1:?lane (sv|arch)}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export OPENROAD_TEST="${OPENROAD_TEST:-$HOME/github/OpenROAD/test}"
OPENROAD_EXE="${OPENROAD_EXE:-$HOME/.local/bin/openroad}"
UTIL="${UTIL:-25}"
in="${2:-$REPO_ROOT/flow/out/$lane/sky130}"
[ -f "$in/netlist_sta.v" ] || { echo "[$lane] missing $in/netlist_sta.v (run flow/sky130_synth.sh)"; exit 2; }
area=$(grep -oE "Chip area for module '\\\\ibex_top': [0-9.]+" "$in/synth.stat" | grep -oE '[0-9.]+$')
# same die rule as run.sh
side=$(python3 -c "import math; print(math.ceil(math.sqrt($area/($UTIL/100.0))) + 20)")
out="${EST_OUT:-$REPO_ROOT/flow/out/$lane/estimate}"; mkdir -p "$out"
export EST_CLOCK_LATENCY="${EST_CLOCK_LATENCY:-4.0}"
export LANE="$lane" NETLIST="$in/netlist_sta.v" SDC="$REPO_ROOT/flow/openroad/constraint.sdc" DIE_SIDE="$side"
echo "[$lane] estimate: area ${area} um2 -> die ${side} um"
for mode in ${EST_MODES:-pre place}; do
  EST_MODE=$mode "$OPENROAD_EXE" -exit -no_init "$REPO_ROOT/flow/openroad/estimate.tcl" > "$out/$mode.log" 2>&1 &
done
wait
grep -h "^EST " "$out"/pre.log "$out"/place.log 2>/dev/null | sed "s/^/[$lane] /" | tee "$out/est.txt"
