#!/usr/bin/env bash

# rdl2arch-riscv Phase-6.5 yosys smoke-synth setup.
#
# Targets the sky130_fd_sc_hd standard-cell library (installed via
# Volare at ~/.volare/sky130A). We use the typical 25C/1v80 corner
# for a realistic post-techmap netlist.
#
# `LR_SYNTH_TIMING_RUN=0` (the flow-var default) so the script skips
# constraint-driven ABC + SDC writes — OpenSTA isn't installed on this
# box, and timing isn't what we're after right now. The Yosys stages
# (read_verilog → synth → dfflibmap → abc -liberty → flatten →
# write_verilog → stat) all still run and give us area + cell counts.

if [ $# -eq 1 ]; then
  export LR_SYNTH_OUT_DIR=$1
elif [ $# -eq 0 ]; then
  export LR_SYNTH_OUT_DIR_PREFIX="syn_out/ibex"
  LR_SYNTH_OUT_DIR=$(date +"${LR_SYNTH_OUT_DIR_PREFIX}_%d_%m_%Y_%H_%M_%S")
  export LR_SYNTH_OUT_DIR
else
  echo "Usage $0 [synth_out_dir]"
  exit 1
fi

export LR_SYNTH_FLATTEN=1
# OpenSTA is now installed at ~/OpenSTA/build/sta — enable timing.
export LR_SYNTH_TIMING_RUN=1
export PATH="$HOME/OpenSTA/build:$PATH"

export LR_SYNTH_CELL_LIBRARY_PATH=~/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
export LR_SYNTH_CELL_LIBRARY_NAME=sky130
