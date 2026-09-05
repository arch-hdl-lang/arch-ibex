# ORFS design config, lane = sv. Copied from ORFS flow/designs/sky130hd/ibex/config.mk
# and retargeted: top = ibex_top (icache + PMP + FF regfile, RVFI off), input = the
# sv2v single-file Verilog of this lane, plain read_verilog frontend (no slang
# plugin on this host). Every knob below is identical between flow/orfs/sv and
# flow/orfs/arch; only VERILOG_FILES and DESIGN_NICKNAME differ.
export DESIGN_NICKNAME = ibex_top_sv
export DESIGN_NAME = ibex_top
export PLATFORM    = sky130hd
export VERILOG_FILES = $(ARCH_IBEX_ROOT)/flow/out/sv/ibex_top.v
export SDC_FILE      = $(ARCH_IBEX_ROOT)/flow/orfs/constraint.sdc
# Adders degrade ibex setup repair (as in the ORFS ibex config)
export ADDER_MAP_FILE :=
export CORE_UTILIZATION = 50
export PLACE_DENSITY_LB_ADDON = 0.25
export TNS_END_PERCENT = 100
export REMOVE_ABC_BUFFERS = 1
export CTS_CLUSTER_SIZE = 20
export CTS_CLUSTER_DIAMETER = 50
export SWAP_ARITH_OPERATORS = 1
export OPENROAD_HIERARCHICAL = 1
