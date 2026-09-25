# Pre-route timing estimate for one lane: predicts the routed WNS of
# flow/openroad/run.sh in ~6-25 min instead of ~3 h. Same platform, die rule
# and SDC as lane.tcl / flow.tcl. Driven by flow/openroad/estimate.sh via env:
#   OPENROAD_TEST, LANE, NETLIST, SDC, DIE_SIDE, EST_MODE (pre | place),
#   EST_CLOCK_LATENCY, TIMING_DRIVEN_GPL (as lane.tcl)
# Prints one "EST <tier> wns_ns= tns_ns= t_s= core_wns_ns= endpoint=" line per tier:
#   pre:   t1_sdc           synthesized netlist as is, P&R constraints
#   place: t3_placed        + flow.tcl's global placement (both passes, pin
#                           placement), placement parasitics, repair_design and
#                           detailed placement -- flow.tcl's "post resize" point
#          t3_placed_lat    + modelled clock insertion delay (see below)
#          t3_repaired_lat  + repair_timing -setup   <- the predictor
# All tiers are pre-CTS. No cheaper buffered tier exists: repair_design cannot
# buffer unplaced cells, and global placement's initial quadratic pass alone
# leaves them stacked (both give the same -132 ns as no placement).
#
# Calibration (2026-09-25, 10 routed runs: both lanes, default and
# timing-driven placement, 5 synthesis variants): routed WNS ~= t3_repaired_lat
# - 1.5 ns. 8 of 10 within +-0.3 ns of that; 12 of 17 routed-distinguishable
# pairs ranked right. Held out: Arch #14 + synth -noabc + timing-driven
# placement predicted -9.68, routed -9.404. Known misses: a design whose
# routed worst path is the icache RAM-enable reg-to-reg path (-0.3 instead of
# +1.5) and SV with synth -noabc under timing-driven placement (+2.9).
# t1_sdc (-414..-1379 ns) and t3_placed (errors spread 5 ns) do not predict.
cd $::env(OPENROAD_TEST)
source "helpers.tcl"
source "flow_helpers.tcl"
source "sky130hd/sky130hd.vars"
set synth_verilog $::env(NETLIST)
set sdc_file $::env(SDC)
set side $::env(DIE_SIDE)
set m 10
set die_area  [list 0 0 $side $side]
set core_area [list $m $m [expr $side - $m] [expr $side - $m]]
set slew_margin 30
set cap_margin 25
set global_place_density 0.5
set mode $::env(EST_MODE)
set t0 [clock seconds]
proc est { tier } {
  set w [sta::worst_slack -max]
  set t [sta::total_negative_slack -max]
  # worst data path (reg-to-reg and I/O group); find_timing_paths without a
  # group returns the first group's path, not the overall worst
  set c [lindex [find_timing_paths -path_group core_clock -path_delay max] 0]
  puts [format "EST %s wns_ns=%.3f tns_ns=%.1f t_s=%d core_wns_ns=%.3f endpoint=%s" \
    $tier $w $t [expr [clock seconds] - $::t0] \
    [get_property $c slack] [get_full_name [get_property $c endpoint]]]
}

read_libraries
read_verilog $synth_verilog
link_design ibex_top
read_sdc $sdc_file
set_thread_count [cpu_count]
sta::set_thread_count 1
source $layer_rc_file
set_wire_rc -signal -layer $wire_rc_layer
set_wire_rc -clock -layer $wire_rc_layer_clk
set_dont_use $dont_use
if { $mode == "pre" } { est t1_sdc; exit }

initialize_floorplan -site $site -die_area $die_area -core_area $core_area
source $tracks_file
remove_buffers
eval tapcell $tapcell_args ;# tclint-disable command-args

foreach layer_adjustment $global_routing_layer_adjustments {
  lassign $layer_adjustment layer adjustment
  set_global_routing_layer_adjustment $layer $adjustment
}
set_routing_layers -signal $global_routing_layers -clock $global_routing_clock_layers
set_macro_extension 2
# lane.tcl's TIMING_DRIVEN_GPL wrapper is honoured the same way here
if { [info exists ::env(TIMING_DRIVEN_GPL)] && $::env(TIMING_DRIVEN_GPL) == 1 } {
  set td_opt -timing_driven
} else {
  set td_opt ""
}
global_placement -density $global_place_density \
  -pad_left $global_place_pad -pad_right $global_place_pad -skip_io
place_pins -hor_layers $io_placer_hor_layer -ver_layers $io_placer_ver_layer
eval global_placement -routability_driven $td_opt -density $global_place_density \
  -pad_left $global_place_pad -pad_right $global_place_pad
estimate_parasitics -placement
repair_design -slew_margin $slew_margin -cap_margin $cap_margin
repair_tie_fanout -separation $tie_separation $tielo_port
repair_tie_fanout -separation $tie_separation $tiehi_port
set_placement_padding -global -left $detail_place_pad -right $detail_place_pad
detailed_placement
estimate_parasitics -placement
est t3_placed
# Pre-CTS clock insertion model: after CTS every flop's clock arrives
# EST_CLOCK_LATENCY late (3.8-4.4 ns measured on both lanes' routed reports)
# while I/O constraints stay referenced to the ideal edge, which costs the
# output-port paths that insertion delay. Ideal-clock estimates omit it.
# The latency goes on the flops' clock pins, not on the clock: latency set on
# the clock also moves the I/O delays' reference edge, so it cancels on I/O
# paths (measured: data_req_o slack unchanged; on the pins: -4.0 ns).
set_clock_latency $::env(EST_CLOCK_LATENCY) [all_registers -clock_pins]
est t3_placed_lat
repair_timing -setup -skip_gate_cloning
est t3_repaired_lat
exit
