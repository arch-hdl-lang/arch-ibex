#!/bin/bash
# hier.sh <cfg> -- hierarchical (unflattened) ECP5 + sky130 stats on the saved res/<cfg>/ibex_top.v,
# same commands as flow/ecp5_hier_stat.sh and flow/sky130_hier_stat.sh but reading the saved copy.
S=${STUDY_SCRATCH:?}
W=${REPO_ROOT:?}
cfg="$1"; R="$S/res/$cfg"; in="$R/ibex_top.v"
CH="-chparam ICache 1 -chparam PMPEnable 1 -chparam PMPNumRegions 4 -chparam PMPGranularity 0 -chparam DbgTriggerEn 1 -chparam DbgHwBreakNum 1 -chparam RV32E 0 -chparam RV32M 2 -chparam RV32B 0 -chparam RV32ZC 3 -chparam RegFile 0 -chparam BranchTargetALU 0 -chparam WritebackStage 0 -chparam BranchPredictor 0 -chparam SecureIbex 0 -chparam ICacheECC 0 -chparam ICacheScramble 0 -chparam MHPMCounterNum 0 -chparam MHPMCounterWidth 40 -chparam MemECC 0 -chparam DmBaseAddr 0 -chparam DmAddrMask 3 -chparam DmHaltAddr 0 -chparam DmExceptionAddr 0"
yosys -q -p "
  read_verilog -sv $in
  read_verilog -sv -overwrite $W/flow/ecp5_prim_clock_gating.v
  hierarchy -check -top ibex_top $CH
  synth_ecp5 -top ibex_top -noflatten
  tee -o $R/ecp5_hier.stat stat
" 2> "$R/ecp5_hier.log" &
sed -e "s|\${REPO_ROOT}|$W|g" -e "s|$W/flow/out/sv/ibex_top.v|$in|g" "$W/flow/sky130_hier.ys.in" > "$R/sky130_hier.ys"
echo "tee -o $R/sky130_hier_area.rpt stat -liberty $HOME/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib" >> "$R/sky130_hier.ys"
yosys -q -s "$R/sky130_hier.ys" 2> "$R/sky130_hier.log" &
wait
echo "hier $cfg done"
