# One lane through OpenROAD's regression P&R flow (test/flow.tcl) on sky130hd.
# Driven by flow/openroad/run.sh through environment variables:
#   OPENROAD_TEST  path to <OpenROAD>/test (platform files, helpers, flow.tcl)
#   LANE           sv | arch
#   NETLIST        synthesised netlist (flow/out/<lane>/sky130/netlist.v)
#   SDC            constraint file (flow/openroad/constraint.sdc)
#   DIE_SIDE       die side in um (square die; core inset by CORE_MARGIN)
#   RESULTS_DIR    where flow.tcl writes its checkpoints and reports
#   OUT            where the final reports go
cd $::env(OPENROAD_TEST)
source "helpers.tcl"
source "flow_helpers.tcl"
source "sky130hd/sky130hd.vars"

set design "ibex_top_$::env(LANE)"
set top_module "ibex_top"
set synth_verilog $::env(NETLIST)
set sdc_file $::env(SDC)
set side $::env(DIE_SIDE)
set m 10
set die_area  [list 0 0 $side $side]
set core_area [list $m $m [expr $side - $m] [expr $side - $m]]

# Same knobs as OpenROAD's own ibex_sky130hd.tcl, identical on both lanes.
set slew_margin 30
set cap_margin 25
set global_place_density 0.5

include -echo "flow.tcl"

# ── Final reports on the routed, parasitic-extracted design ──────────────
set out $::env(OUT)
report_design_area                                       > $out/final_area.rpt
report_cell_usage                                       >> $out/final_area.rpt
report_wns                                               > $out/final_timing.rpt
report_tns                                              >> $out/final_timing.rpt
report_worst_slack -max -digits 3                       >> $out/final_timing.rpt
report_worst_slack -min -digits 3                       >> $out/final_timing.rpt
report_checks -path_delay max -group_path_count 5 -digits 3 >> $out/final_timing.rpt
report_checks -path_delay min -group_path_count 1 -digits 3 >> $out/final_timing.rpt
report_check_types -max_slew -max_capacitance -max_fanout -violators >> $out/final_timing.rpt
report_power                                             > $out/final_power.rpt
set fh [open $out/final_metrics.txt w]
puts $fh "design_area_um2 [sta::format_area [rsz::design_area] 0]"
puts $fh "utilization_pct [format %.1f [expr [rsz::utilization] * 100]]"
puts $fh "wns_ns [sta::worst_slack -max]"
puts $fh "tns_ns [sta::total_negative_slack -max]"
puts $fh "drv_count [detailed_route_num_drvs]"
puts $fh "instance_count [sta::network_instance_count]"
puts $fh "die_side_um $side"
close $fh
