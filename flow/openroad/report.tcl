# Final reports for one lane, from the design the P&R flow saved (the filled,
# routed database + extracted parasitics). Runs after flow/openroad/lane.tcl;
# can be re-run alone. Env: OPENROAD_TEST, LANE, SDC, RESULTS_DIR, OUT.
cd $::env(OPENROAD_TEST)
source "helpers.tcl"
source "flow_helpers.tcl"
source "sky130hd/sky130hd.vars"
set lane $::env(LANE)
set design "ibex_top_$lane"
set results $::env(RESULTS_DIR)
set out $::env(OUT)

read_libraries
read_db [lindex [glob "$results/${design}_sky130hd_fill*.db"] 0]
read_sdc $::env(SDC)
set_propagated_clock [all_clocks]
read_spef [lindex [glob "$results/${design}_sky130hd*.spef"] 0]

# Everything below prints to stdout; run.sh splits it into final_*.rpt on
# the "##### <file>" marker lines (OpenROAD's logger bypasses OpenSTA's
# log_begin/log_end, so file redirection inside Tcl is not available).
puts "##### final_timing.rpt"
report_worst_slack -max -digits 3
report_worst_slack -min -digits 3
report_tns -digits 3
report_clock_skew -digits 3
# Per path group: the register-to-register / I/O group is "core_clock"; the
# "asynchronous" (reset recovery) and "gated clock" groups are listed once each.
report_checks -path_delay max -group_path_count 5 -path_group core_clock -digits 3
report_checks -path_delay max -group_path_count 1 -path_group asynchronous -digits 3
report_checks -path_delay min -group_path_count 1 -path_group core_clock -digits 3
report_check_types -max_slew -max_capacitance -max_fanout -violators -digits 3
puts "##### final_area.rpt"
report_design_area
report_cell_usage
puts "##### final_power.rpt"
report_power -corner $power_corner
puts "##### final_checks.rpt"
check_antennas
check_placement -verbose
puts "##### end"

set fh [open $out/final_metrics.txt w]
puts $fh "die_side_um $::env(DIE_SIDE)"
puts $fh "design_area_um2 [sta::format_area [rsz::design_area] 0]"
puts $fh "utilization_pct [format %.1f [expr [rsz::utilization] * 100]]"
puts $fh "wns_setup_ns [format %.3f [sta::worst_slack -max]]"
puts $fh "wns_hold_ns [format %.3f [sta::worst_slack -min]]"
puts $fh "tns_setup_ns [format %.1f [sta::total_negative_slack -max]]"
puts $fh "clock_skew_setup_ns [format %.3f [sta::worst_clock_skew -setup]]"
puts $fh "antenna_violations [ant::antenna_violation_count]"
close $fh
