#!/bin/bash
# formal_suites.sh <cfg> -- run formal/icache_fbsel (7 tasks) and formal/icache_liveness (Arch tasks)
# against the current build/. Prints "GEN DONE" once both inputs are generated
# (after that build/ may change).
source ${STUDY_SCRATCH:?}/env.sh
cfg="$1"; L="$S/logs/$cfg"; mkdir -p "$L"
cd "$W" || exit 1
# Separate output dirs per cfg so runs can overlap with later builds.
FB="$W/flow/out/formal_fbsel_$cfg"; LV="$W/flow/out/formal_live_$cfg"
python3 formal/icache_fbsel/make.py "$FB" > "$L/fbsel_gen.log" 2>&1 || { echo "fbsel make.py FAILED"; cat "$L/fbsel_gen.log"; }
cp formal/icache_fbsel/fbsel.sby "$FB/"
python3 formal/icache_liveness/make_variants.py "$LV" > "$L/live_gen.log" 2>&1 || { echo "live make_variants FAILED"; cat "$L/live_gen.log"; }
cp formal/icache_liveness/live.sby "$LV/"
echo "GEN DONE $(date +%T)"
(
  cd "$FB"
  for t in kstrong equiv lcover nocoalbmc nocoalprop noopen nogate; do
    echo "== fbsel $t"
    { sby -f fbsel.sby "$t" 2>&1 || true; } | grep -E "returned|failed assertion|reached cover|unreached|DONE" || true
  done
) > "$L/fbsel.log" 2>&1 &
(
  cd "$LV"
  for t in nothrottle exact branchyield exact_fair branchyield_fair tight17 tight14 cover prove17; do
    echo "== live $t"
    { sby -f live.sby "$t" 2>&1 || true; } | grep -E "returned|failed assertion|reached cover|DONE" || true
  done
) > "$L/live.log" 2>&1 &
wait
echo "FORMAL DONE $(date +%T)"
grep -E "^== |DONE" "$L/fbsel.log" "$L/live.log"
