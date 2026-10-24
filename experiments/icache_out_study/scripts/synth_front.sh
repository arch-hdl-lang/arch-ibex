#!/bin/bash
# synth_front.sh <cfg> -- (after make build-synth) sv2v, standalone icache stat, ECP5 synth (tagged), sky130 synth + estimate.
source ${STUDY_SCRATCH:?}/env.sh
cfg="$1"; R="$S/res/$cfg"; mkdir -p "$R"
cd "$W" || exit 1
{ git rev-parse HEAD; git status --short; $ARCH_BIN --version; } > "$R/head.txt"
echo "== sv2v $(date +%T)"; bash flow/sv2v.sh > "$R/sv2v.log" 2>&1; echo "sv2v rc=$?"
cp flow/out/arch/ibex_top.v "$R/ibex_top.v"
echo "== standalone icache $(date +%T)"
yosys -q -l "$R/icache_standalone.log" -p "read_verilog -sv $R/ibex_top.v; hierarchy -check -top ibex_icache; synth_ecp5 -top ibex_icache; tee -o $R/icache_standalone.stat stat" > /dev/null 2>&1; echo "standalone rc=$?"
echo "== ecp5 synth $(date +%T)"; ECP5_TAG="$cfg" bash flow/ecp5_pnr.sh synth arch > "$R/ecp5_synth.out" 2>&1; echo "ecp5 synth rc=$?"
cp flow/out/arch/ecp5_$cfg/synth.stat "$R/ecp5_synth.stat"
echo "== sky130 synth $(date +%T)"; bash flow/sky130_synth.sh arch > "$R/sky130_synth.out" 2>&1; echo "sky130 rc=$?"
cp -r flow/out/arch/sky130 "$R/sky130"
echo "== estimate $(date +%T)"; bash flow/openroad/estimate.sh arch > "$R/estimate.out" 2>&1; echo "estimate rc=$?"
cp -r flow/out/arch/estimate "$R/estimate"
echo "== done $(date +%T)"
