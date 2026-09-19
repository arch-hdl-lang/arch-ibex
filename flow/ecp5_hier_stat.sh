#!/usr/bin/env bash
# Hierarchical (unflattened) ECP5 synthesis, for per-module area attribution.
#
#   flow/ecp5_hier_stat.sh            -> flow/out/<lane>/ecp5/hier.stat
#
# Mirrors the flattened script the review package used
# (review-package/reports/<lane>_ecp5_synth.ys) EXCEPT for -noflatten, so the
# two are comparable. In particular it keeps:
#   - the ecp5_prim_clock_gating.v overwrite, and
#   - the full -chparam list; without it the design elaborates with default
#     parameters and the numbers describe a different core.
# TASK9's one-line form omits both; that would not be comparable to the
# flattened runs it is meant to break down.
#
# Unflattened totals are EXPECTED to differ from the flattened ones: cross-
# module optimisation is what flattening buys. The flattened numbers remain
# the headline; this is a breakdown.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for lane in sv arch; do
  out="$REPO_ROOT/flow/out/$lane/ecp5"; mkdir -p "$out"
  yosys -q -p "
    read_verilog -sv $REPO_ROOT/flow/out/$lane/ibex_top.v
    read_verilog -sv -overwrite $REPO_ROOT/flow/ecp5_prim_clock_gating.v
    hierarchy -check -top ibex_top -chparam ICache 1 -chparam PMPEnable 1 -chparam PMPNumRegions 4 -chparam PMPGranularity 0 -chparam DbgTriggerEn 1 -chparam DbgHwBreakNum 1 -chparam RV32E 0 -chparam RV32M 2 -chparam RV32B 0 -chparam RV32ZC 3 -chparam RegFile 0 -chparam BranchTargetALU 0 -chparam WritebackStage 0 -chparam BranchPredictor 0 -chparam SecureIbex 0 -chparam ICacheECC 0 -chparam ICacheScramble 0 -chparam MHPMCounterNum 0 -chparam MHPMCounterWidth 40 -chparam MemECC 0 -chparam DmBaseAddr 0 -chparam DmAddrMask 3 -chparam DmHaltAddr 0 -chparam DmExceptionAddr 0
    synth_ecp5 -top ibex_top -noflatten
    tee -o $out/hier.stat stat
  " 2>"$out/hier.log"
  echo "$lane -> $out/hier.stat"
done
