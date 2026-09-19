# Minimal sky130 SDC for the upstream Ibex syn flow.
# Mirrors the nangate variant; only the driving cell name changes.
set_driving_cell [all_inputs] -lib_cell sky130_fd_sc_hd__buf_2
set_load 10.0 [all_outputs]
