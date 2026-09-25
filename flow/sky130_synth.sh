#!/usr/bin/env bash
# sky130 logic synthesis + STA for ibex_top, both lanes, each with its own recipe
# (flow/recipes/<lane>.env; FLOW_RECIPE=none = identical plain settings).
#
#   flow/sky130_synth.sh [sv|arch ...]      (default: both lanes)
#
# Inputs : flow/out/<lane>/ibex_top.v            (from flow/sv2v.sh)
# Outputs: flow/out/<lane>/sky130/{synth.log,synth.stat,netlist.v,sta.log,
#          sta_checks.rpt,sta_wns_tns.rpt} and copies in $REPORT_DIR
#          as <lane>_sky130_synth_area.rpt / <lane>_sky130_sta_*.rpt
#
# Env: SKY130_LIB (liberty), STA_BIN (OpenSTA), CLOCK_NS (default 10.0),
#      REPORT_DIR (default flow/out/reports),
#      SYNTH_NOABC (default 0, or the lane's recipe; see below),
#      SYNTH_ADDER, SYNTH_ADDR_ADDER (default bk, or the lane's recipe; see
#      below), FLOW_RECIPE.
#
# Recipe (same as the 2026-05 notes in changes/2026-05-07-icache-area-restructure):
# proc; per-module `memory -nomap` BEFORE flatten so parallel write ports on the
# inferred icache RAMs are not dead-code-eliminated; flatten; memory_map; synth;
# dfflibmap + abc against sky130_fd_sc_hd tt; stat -liberty. Memories are
# inferred (prim_generic_* models), never black-boxed.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Reports are copied to REPORT_DIR (default flow/out/reports/, untracked), never into
# review-package/ unless asked: that directory is the submitted paper's evidence and
# is regenerated only deliberately, with REPORT_DIR="$REPO_ROOT/review-package/reports".
REPORT_DIR="${REPORT_DIR:-$REPO_ROOT/flow/out/reports}"
mkdir -p "$REPORT_DIR"
SKY130_LIB="${SKY130_LIB:-$HOME/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib}"
STA_BIN="${STA_BIN:-$HOME/OpenSTA/build/sta}"
CLOCK_NS="${CLOCK_NS:-10.0}"
# SYNTH_NOABC=1: run `synth` with -noabc, so the logic is restructured once, by
# the liberty `abc` below, instead of first by synth's generic ABC pass.
# Measured depth flop->data_addr_o[31]: arch 39->36, sv 30->32. (`abc -D <ps>`
# on top of this changed neither depth, so it is not offered.) Resolved per
# lane: environment, then flow/recipes/<lane>.env, then 0.
# SYNTH_ADDER=bk|ks|hc|sklansky: carry network for every $alu adder. bk is
# Yosys's default Brent-Kung $lcu; the others are Yosys's +/choices/ maps
# (Kogge-Stone, Han-Carlson, Sklansky), injected with `synth -extra-map`.
# Standalone 32-bit add, sky130 mapped: bk 24 levels / 6.35 ns, ks 19 / 4.23,
# hc 18 / 4.69, sklansky 25 / 6.37. Resolved per lane like SYNTH_NOABC.
# SYNTH_ADDR_ADDER=bk|ks|hc|sklansky: the same choice for ONE adder only, the
# ALU adder (the $alu cell driving ibex_alu's adder_result_ext_o: load/store
# addresses, and branch targets under BranchTargetALU = 0). synth stops before
# its fine stage, that cell alone is techmapped with the chosen $lcu, and synth
# resumes; the flow fails unless the selection matches exactly one cell.
# Measured (Arch recipe, pre-route estimate, ks): ALU adder alone -7.335 ns;
# plus the 4 data-side PMP TOR compares after it -7.675 (no better); all 68
# adders -6.216; none -8.176.
source "$REPO_ROOT/flow/recipes/recipe.sh"
[ -f "$SKY130_LIB" ] || { echo "liberty not found: $SKY130_LIB" >&2; exit 2; }
[ -x "$STA_BIN" ] || { echo "OpenSTA not found: $STA_BIN" >&2; exit 2; }
lanes=("$@"); [ ${#lanes[@]} -eq 0 ] && lanes=(sv arch)
rc=0
for lane in "${lanes[@]}"; do
  in="$REPO_ROOT/flow/out/$lane/ibex_top.v"
  out="$REPO_ROOT/flow/out/$lane/sky130"; mkdir -p "$out"
  [ -f "$in" ] || { echo "[$lane] missing $in (run flow/sv2v.sh)"; rc=1; continue; }
  SYNTH_OPTS=""
  [ "$(recipe_value "$lane" SYNTH_NOABC 0)" = "1" ] && SYNTH_OPTS=" -noabc"
  case "$(recipe_value "$lane" SYNTH_ADDER bk)" in
    bk) ;;
    ks) SYNTH_OPTS="$SYNTH_OPTS -extra-map +/choices/kogge-stone.v" ;;
    hc) SYNTH_OPTS="$SYNTH_OPTS -extra-map +/choices/han-carlson.v" ;;
    sklansky) SYNTH_OPTS="$SYNTH_OPTS -extra-map +/choices/sklansky.v" ;;
    *) echo "[$lane] unknown SYNTH_ADDER '$(recipe_value "$lane" SYNTH_ADDER bk)' (bk|ks|hc|sklansky)"; rc=1; continue ;;
  esac
  ADDR_SEL='w:*alu_i.adder_result_ext_o %ci1 t:$alu %i'
  case "$(recipe_value "$lane" SYNTH_ADDR_ADDER bk)" in
    bk) SYNTH_CMDS="synth -top ibex_top${SYNTH_OPTS}" ;;
    ks|hc|sklansky)
      case "$(recipe_value "$lane" SYNTH_ADDR_ADDER bk)" in
        ks) m=kogge-stone ;; hc) m=han-carlson ;; sklansky) m=sklansky ;;
      esac
      SYNTH_CMDS="synth -top ibex_top -run begin:fine
select -assert-count 1 $ADDR_SEL
techmap -map +/techmap.v -map +/choices/$m.v $ADDR_SEL
select -assert-none t:\$lcu
synth -top ibex_top -run fine:${SYNTH_OPTS}" ;;
    *) echo "[$lane] unknown SYNTH_ADDR_ADDER '$(recipe_value "$lane" SYNTH_ADDR_ADDER bk)' (bk|ks|hc|sklansky)"; rc=1; continue ;;
  esac
  recipe_describe "$lane" SYNTH_NOABC SYNTH_ADDER=bk SYNTH_ADDR_ADDER=bk > "$out/recipe_synth.txt"
  echo "[$lane] recipe: $(tr '\n' ' ' < "$out/recipe_synth.txt")"
  # The port's configuration (01-inventory.md §1), forced identically on both
  # lanes. Enum-typed parameters are integers after sv2v (ibex_pkg encodings:
  # RV32M: 2 = RV32MFast; RV32B: 0 = RV32BNone; RV32ZC: 3 = RV32ZcaZcbZcmp;
  # RegFile: 0 = RegFileFF). Without this a standalone ibex_top elaborates
  # with upstream's defaults (no icache, no PMP, RV32MNone).
  CHPARAM="-set ICache 1 -set PMPEnable 1 -set PMPNumRegions 4 -set PMPGranularity 0 \
    -set DbgTriggerEn 1 -set DbgHwBreakNum 1 -set RV32E 0 -set RV32M 2 -set RV32B 0 -set RV32ZC 3 \
    -set RegFile 0 -set BranchTargetALU 0 -set WritebackStage 0 -set BranchPredictor 0 \
    -set SecureIbex 0 -set ICacheECC 0 -set ICacheScramble 0 -set MHPMCounterNum 0 -set MHPMCounterWidth 40 \
    -set MemECC 0 \
    -set DmBaseAddr 0 -set DmAddrMask 3 -set DmHaltAddr 0 -set DmExceptionAddr 0"
  # DummyInstructions / RegFileECC are NOT overridden: both already default to 0 on
  # both lanes, and overriding either makes Yosys fail with "Module name in defparam
  # contains non-constant expressions" on the upstream ibex_top. Overrides go through
  # `hierarchy -chparam` (a plain `chparam` pass fails the same way).
  HCHPARAM="${CHPARAM//-set /-chparam }"
  cat > "$out/synth.ys" <<YS
read_liberty -lib $SKY130_LIB
read_verilog -sv $in
hierarchy -check -top ibex_top $HCHPARAM
proc
opt_clean
# keep inferred RAM write ports intact across flatten (see header)
memory -nomap
flatten
memory_map
opt
${SYNTH_CMDS}
dfflibmap -liberty $SKY130_LIB
techmap -map $REPO_ROOT/flow/sky130_latch_map.v
abc -liberty $SKY130_LIB
# Undefined bits ('x, e.g. unused multiplier intermediate bits) become 0, and
# constant drivers become conb_1 tie cells (one HI, one LO); OpenROAD's reader
# otherwise turns them into unroutable zero_/one_ power nets (TritonRoute
# DRT-0305) and the P&R flow's repair_tie_fanout expects tie cells.
setundef -zero
hilomap -singleton -hicell sky130_fd_sc_hd__conb_1 HI -locell sky130_fd_sc_hd__conb_1 LO
opt_clean -purge
tee -o $out/synth.stat stat -liberty $SKY130_LIB
write_verilog -noattr -noexpr -nohex -nodec $out/netlist.v
YS
  echo "[$lane] yosys ..."; start=$(date +%s)
  if yosys -q -l "$out/synth.log" -s "$out/synth.ys" > /dev/null 2>&1; then
    echo "[$lane] yosys ok in $(( $(date +%s) - start )) s"
  else
    echo "[$lane] yosys FAILED (see $out/synth.log)"; tail -5 "$out/synth.log"; rc=1; continue
  fi
  # OpenSTA's Verilog reader rejects `wire signed [..]` declarations, which
  # Yosys emits for signed nets; signedness carries no timing meaning, so STA
  # reads a copy with the keyword removed (identical treatment on both lanes).
  sed -E 's/^([[:space:]]*(wire|reg|input|output|inout)) signed /\1 /' "$out/netlist.v" > "$out/netlist_sta.v"
  cat > "$out/sta.tcl" <<TCL
read_liberty $SKY130_LIB
read_verilog $out/netlist_sta.v
link_design ibex_top
create_clock -name clk_i -period $CLOCK_NS [get_ports clk_i]
set_input_delay 0 -clock clk_i [delete_from_list [all_inputs] [get_ports clk_i]]
set_output_delay 0 -clock clk_i [all_outputs]
report_checks -path_delay max -group_path_count 5 > $out/sta_checks.rpt
report_wns > $out/sta_wns_tns.rpt
report_tns >> $out/sta_wns_tns.rpt
report_checks -path_delay max -format summary >> $out/sta_wns_tns.rpt
exit
TCL
  echo "[$lane] OpenSTA ..."
  "$STA_BIN" -no_init -exit "$out/sta.tcl" > "$out/sta.log" 2>&1 || { echo "[$lane] OpenSTA FAILED (see $out/sta.log)"; tail -5 "$out/sta.log"; rc=1; }
  bb=$(grep -cE 'not found\. Creating black box|black box' "$out/sta.log" || true)
  echo "[$lane] black-boxed cells in STA: ${bb:-0}"
  R="$REPORT_DIR"
  cp "$out/synth.stat" "$R/${lane}_sky130_synth_area.rpt"
  cp "$out/sta_checks.rpt" "$R/${lane}_sky130_sta_checks.rpt"
  cp "$out/sta_wns_tns.rpt" "$R/${lane}_sky130_sta_wns_tns.rpt"
  sed "s|$REPO_ROOT|\${REPO_ROOT}|g; s|$HOME|~|g" "$out/synth.ys" > "$R/${lane}_sky130_synth.ys"
  sed "s|$REPO_ROOT|\${REPO_ROOT}|g; s|$HOME|~|g" "$out/sta.tcl" > "$R/${lane}_sky130_sta.tcl"
done
exit $rc
