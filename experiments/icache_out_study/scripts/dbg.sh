#!/bin/bash
# dbg.sh <pair> <seed> <cycles> <equiv> <err> <flags> <dbg_cycle>
D=${STUDY_SCRATCH:?}/cosim
pair="$1"; B="$D/dbg_$pair"
if [ ! -x "$B/obj_dir/cosim" ] || [ "$D/tb.cpp" -nt "$B/obj_dir/cosim" ]; then
  mkdir -p "$B"
  cp "$D/b_$pair/ref.v" "$D/b_$pair/dut.v" "$D/b_$pair/dual.v" "$B/"
  if ! grep -q 'Vdual___024root.h' "$D/tb.cpp"; then
    sed 's/#include "verilated.h"/#include "verilated.h"\n#ifdef DBG_DUT\n#include "Vdual___024root.h"\n#endif/' "$D/tb.cpp" > "$B/tb.cpp"
  else cp "$D/tb.cpp" "$B/tb.cpp"; fi
  (cd "$B" && verilator --cc --exe --build -O1 -j 4 --top-module dual --public-flat-rw -CFLAGS -DDBG_DUT \
     -Wno-fatal -Wno-lint -Wno-style -Wno-UNOPTFLAT -Wno-MULTIDRIVEN -o cosim dual.v ref.v dut.v tb.cpp > build.log 2>&1) \
     || { grep -i error "$B/build.log" | head; exit 1; }
fi
DBG="$7" "$B/obj_dir/cosim" "$2" "$3" "$4" "$5" $(( $2 % 4 )) "$6" | grep -E "^DBG|cyc $7\]" | head -${HEADN:-14}
