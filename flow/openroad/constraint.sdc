# Shared constraint for both lanes (OpenROAD regression-flow style, cf.
# ~/github/OpenROAD/test/ibex_sky130hd.sdc): one clock, 10 ns, 20 % I/O delays.
create_clock -name core_clock -period 10.0 [get_ports clk_i]
set_all_input_output_delays
