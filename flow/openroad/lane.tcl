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

# Final reports: flow/openroad/report.tcl (run by run.sh on the saved design).
