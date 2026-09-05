read_liberty ~/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_verilog ${REPO_ROOT}/flow/out/sv/sky130/netlist_sta.v
link_design ibex_top
create_clock -name clk_i -period 10.0 [get_ports clk_i]
set_input_delay 0 -clock clk_i [delete_from_list [all_inputs] [get_ports clk_i]]
set_output_delay 0 -clock clk_i [all_outputs]
report_checks -path_delay max -group_path_count 5 > ${REPO_ROOT}/flow/out/sv/sky130/sta_checks.rpt
report_wns > ${REPO_ROOT}/flow/out/sv/sky130/sta_wns_tns.rpt
report_tns >> ${REPO_ROOT}/flow/out/sv/sky130/sta_wns_tns.rpt
report_checks -path_delay max -format summary >> ${REPO_ROOT}/flow/out/sv/sky130/sta_wns_tns.rpt
exit
