# Post-P&R reports from the ORFS final database. Run inside $ORFS_ROOT/flow as:
#   make DESIGN_CONFIG=<config.mk> open_final ... or, standalone:
#   openroad -exit flow/orfs/report.tcl   with env: PLATFORM_DIR, RESULTS, OUT
set platform $::env(PLATFORM_DIR)
set results  $::env(RESULTS)
set out      $::env(OUT)
foreach lib [glob $platform/lib/*.lib] { read_liberty $lib }
read_db $results/6_final.odb
read_sdc $results/6_final.sdc
source $platform/setRC.tcl
estimate_parasitics -global_routing
report_design_area                      > $out/final_area.rpt
report_cell_usage                      >> $out/final_area.rpt
report_wns                              > $out/final_timing.rpt
report_tns                             >> $out/final_timing.rpt
report_checks -path_delay max -group_path_count 5 >> $out/final_timing.rpt
report_checks -path_delay min -group_path_count 1 >> $out/final_timing.rpt
report_power                            > $out/final_power.rpt
exit
