#!/bin/bash
# Random differential co-simulation of two ibex_icache builds (icache output-path study).
#
#   experiments/icache_out_study/run_cosim.sh <ref_build_dir> <dut_build_dir> <out_dir> \
#       <equiv 0|1> <cycles> <flags> <seed>...
#
# <*_build_dir>: a copy of build/*.sv after `make build` on the commit to test.
# Each seed runs twice (bus errors off / on); profile = seed % 4 (bus grant %,
# latency, ready %, branch rate). flags (bitmask, see tb.cpp):
#   1  no icache_inval_i pulses   (main bug: IC1 hit not qualified during inval)
#   2  no icache_enable_i toggles
#   4  no far-tag (way-conflict) branch targets
#   8  rare branches (1 per 20000 cycles) -- exposes stalls that a branch would hide
#   16 all instructions 32-bit and 4-byte aligned (CoreMark-like, rv32im)
# Checks per design: golden instruction stream (addr_o / rdata_o vs. program
# memory), R-OUT-2 stability, progress (<400 cycles without an accept while
# ready); with equiv=1 also cycle-exact equality of all outputs.
# Repros found on main (adbe54d), all with this harness:
#   * intra-line skid bridge takes beat 0 again (32-bit instr at line offset 2,
#     beat 1 not yet live): counted as "skidbug" (any seed, flags 1)
#   * premature out_done on a cross-line skid-bridge accept -> stall until branch:
#     seed 4, flags 9, onset ~cycle 3512 (pc 0x10000614)
#   * IC1 hit not qualified while the invalidation walk owns the RAM port:
#     seed 4, flags 2 (inval on), first wrong data cycle 3194 after the pulse at 3134
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ref="$1"; dut="$2"; out="$3"; eq="$4"; cyc="$5"; fl="$6"; shift 6
python3 "$here/mk.py" "$ref" "$dut" "$out"
for s in "$@"; do
  for em in 0 1; do
    "$out/obj_dir/cosim" "$s" "$cyc" "$eq" "$em" $((s % 4)) "$fl" > "$out/run_${s}_${eq}${em}${fl}.log" || true
    grep -v "known intra\|INVAL pulse" "$out/run_${s}_${eq}${em}${fl}.log" | head -3
    tail -1 "$out/run_${s}_${eq}${em}${fl}.log"
  done
done
