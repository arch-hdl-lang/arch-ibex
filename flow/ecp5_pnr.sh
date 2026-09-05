#!/usr/bin/env bash
# ECP5 (LFE5U-85F, CABGA381, speed 6) synthesis + place-and-route, both lanes.
#   flow/ecp5_pnr.sh [synth|pnr|all] [sv|arch ...]      (default: all, both lanes)
# Inputs : flow/out/<lane>/ibex_top.v (sv2v output)
# Outputs: flow/out/<lane>/ecp5/{synth.log,ibex_top.json,nextpnr_seed<N>.log,report_seed<N>.json}
#          and copies under review-package/reports/<lane>_ecp5_*.
# Env: NEXTPNR (default ~/github/nextpnr/build/nextpnr-ecp5), YOSYS (default yosys), FREQ (50 MHz), SEEDS (1 2 3).
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NEXTPNR="${NEXTPNR:-$HOME/github/nextpnr/build/nextpnr-ecp5}"
YOSYS="${YOSYS:-yosys}"
FREQ="${FREQ:-50}"
SEEDS="${SEEDS:-1 2 3}"
stage="${1:-all}"; shift || true
lanes=("$@"); [ ${#lanes[@]} -eq 0 ] && lanes=(sv arch)
R="$REPO_ROOT/review-package/reports"
rc=0
for lane in "${lanes[@]}"; do
  in="$REPO_ROOT/flow/out/$lane/ibex_top.v"
  out="$REPO_ROOT/flow/out/$lane/ecp5"; mkdir -p "$out"
  [ -f "$in" ] || { echo "[$lane] missing $in (run flow/sv2v.sh)"; rc=1; continue; }
  if [ "$stage" = synth ] || [ "$stage" = all ]; then
    # Same parameter overrides as the sky130 flow (the port's configuration).
    # FPGA model of prim_clock_gating (no latch), identical on both lanes; see the file header.
    cat > "$out/synth.ys" <<YS
read_verilog -sv $in
read_verilog -sv -overwrite $REPO_ROOT/flow/ecp5_prim_clock_gating.v
hierarchy -check -top ibex_top -chparam ICache 1 -chparam PMPEnable 1 -chparam PMPNumRegions 4 -chparam PMPGranularity 0 -chparam DbgTriggerEn 1 -chparam DbgHwBreakNum 1 -chparam RV32E 0 -chparam RV32M 2 -chparam RV32B 0 -chparam RV32ZC 3 -chparam RegFile 0 -chparam BranchTargetALU 0 -chparam WritebackStage 0 -chparam BranchPredictor 0 -chparam SecureIbex 0 -chparam ICacheECC 0 -chparam ICacheScramble 0 -chparam MHPMCounterNum 0 -chparam MHPMCounterWidth 40 -chparam MemECC 0 -chparam DmBaseAddr 0 -chparam DmAddrMask 3 -chparam DmHaltAddr 0 -chparam DmExceptionAddr 0
synth_ecp5 -top ibex_top -json $out/ibex_top.json
tee -o $out/synth.stat stat
YS
    echo "[$lane] yosys synth_ecp5 ..."; start=$(date +%s)
    if "$YOSYS" -q -l "$out/synth.log" -s "$out/synth.ys" > /dev/null 2>&1; then
      echo "[$lane] synth ok in $(( $(date +%s) - start )) s"
    else
      echo "[$lane] synth FAILED (see $out/synth.log)"; tail -3 "$out/synth.log"; rc=1; continue
    fi
    # Memory mapping check: every inferred $mem must have become block RAM
    # (DP16KD / PDPW16KD); anything left as $mem / distributed logic is flagged.
    echo "[$lane] block RAMs: $(grep -cE 'DP16KD|PDPW16KD' "$out/synth.stat" | tr -d ' ') cell rows; $(grep -E '^\s+[0-9]+ +(DP16KD|PDPW16KD)' "$out/synth.stat" | awk '{s+=$1} END{print s+0}') instances; leftover \$mem: $(grep -cE '^\s+[0-9]+ +\$mem' "$out/synth.stat" | tr -d ' ')"
    cp "$out/synth.stat" "$R/${lane}_ecp5_synth.stat"; cp "$out/synth.ys" "$R/${lane}_ecp5_synth.ys"
  fi
  if [ "$stage" = pnr ] || [ "$stage" = all ]; then
    [ -f "$out/ibex_top.json" ] || { echo "[$lane] missing $out/ibex_top.json"; rc=1; continue; }
    # ibex_top has 787 (SV) / 2000 (Arch, RVFI ports always present) top-level IO
    # bits; no ECP5 package has that many pins, so the core is placed
    # out-of-context (--out-of-context: no IO buffers are inserted, ports become
    # internal nets). The LPF therefore only carries the clock constraint.
    printf 'FREQUENCY NET "clk_i" %s MHZ;\n' "$FREQ" > "$out/ibex_top.lpf"
    for seed in $SEEDS; do
      echo "[$lane] nextpnr seed $seed ..."; start=$(date +%s)
      "$NEXTPNR" --85k --package CABGA381 --speed 6 --json "$out/ibex_top.json" --lpf "$out/ibex_top.lpf" \
        --out-of-context --lpf-allow-unconstrained --freq "$FREQ" --timing-allow-fail --report "$out/report_seed${seed}.json" --seed "$seed" \
        > "$out/nextpnr_seed${seed}.log" 2>&1   # no --textcfg: bitstreams are not produced out-of-context
      st=$?
      echo "[$lane] nextpnr seed $seed exit=$st in $(( $(date +%s) - start )) s; $(grep -oE 'Max frequency for clock[^:]*: [0-9.]+ MHz \(PASS|FAIL[^)]*\)' "$out/nextpnr_seed${seed}.log" | tail -1)"
      [ $st -eq 0 ] || rc=1
      cp "$out/report_seed${seed}.json" "$R/${lane}_ecp5_report_seed${seed}.json" 2>/dev/null
      cp "$out/nextpnr_seed${seed}.log" "$R/${lane}_ecp5_nextpnr_seed${seed}.log" 2>/dev/null
    done
    cp "$out/ibex_top.lpf" "$R/${lane}_ecp5_ibex_top.lpf"
  fi
done
exit $rc
