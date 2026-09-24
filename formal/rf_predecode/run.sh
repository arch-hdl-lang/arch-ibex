#!/bin/bash
# Proofs for the register-file read-select retime (ibex_register_file_ff
# ReadOneHotA = 1, fed by the IF stage's registered one-hot rs1 select).
#
#   formal/rf_predecode/run.sh [--mutant]
#
# 1. core invariant (SymbiYosys, abc pdr, unbounded): the two ibex_core
#    outputs that drive the register file always satisfy
#        rf_raddr_a_oh_o == 1 << rf_raddr_a_o
#    from any initial state that satisfies it. The IF/ID registers have no
#    reset, so the initial state is constrained by that same relation (the
#    retimed register's initial value is the image of the original one).
# 2. register file (formal/equiv_module.sh-style equiv_make/equiv_induct):
#    ReadOneHotA = 1 with raddr_a_oh_i = 1 << raddr_a_i is equivalent to the
#    upstream-shaped read (ReadOneHotA = 0), i.e. to origin/main's module.
# Together: ibex_top's register-file read data is unchanged, cycle for cycle.
# --mutant runs the same core proof with the select taken from the rs2 field
# (instr[24:20]); it must FAIL, showing the proof can see the register.
# Needs: flow/sv2v.sh output (flow/out/arch/ibex_top.v), sby, yosys, sv2v.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"
SRC="$REPO/flow/out/arch/ibex_top.v"
[ -f "$SRC" ] || { echo "missing $SRC (run make build-synth && flow/sv2v.sh)"; exit 2; }
W="$HERE/work"; rm -rf "$W"; mkdir -p "$W"
python3 - "$SRC" "$W/core.v" "${1:-}" <<'PY'
import sys, re
src, dst, mode = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(src).read()
if mode == "--mutant":
    a = "rf_raddr_a_oh_id_o <= 1 << instr_decompressed[19:15];"
    assert s.count(a) == 1, "mutation site not found"
    s = s.replace(a, "rf_raddr_a_oh_id_o <= 1 << instr_decompressed[24:20];")
m = re.search(r"^module ibex_core\b", s, re.M); assert m
end = s.index("\nendmodule", m.start())
prop = """
`ifdef FORMAL
\t// retime invariant: the register file's one-hot select is the decode
\t// of its binary select, from any initial state where that holds
\talways @(*) if ($initstate) assume (rf_raddr_a_oh_o == (32'd1 << rf_raddr_a_o));
\talways @(*) if (!$initstate) assert (rf_raddr_a_oh_o == (32'd1 << rf_raddr_a_o));
`endif"""
open(dst, "w").write(s[:end] + prop + s[end:])
PY
cat > "$W/core.sby" <<SBY
[options]
mode prove
aigsmt z3

[engines]
abc pdr

[script]
read_verilog -formal -DFORMAL core.v
prep -top ibex_core
async2sync
# Map memories and arithmetic here, then resolve 'x: SBY's own later
# techmap (maccmap) otherwise emits constant-x AND inputs that the AIG
# backend rejects. setundef -anyseq makes every x a free value, which is
# conservative for a safety proof (same recipe as icache_liveness/live.sby).
flatten
memory -nomap
memory_map
opt -full
techmap
opt -fast
setundef -undriven -anyseq
setundef -anyseq

[files]
$W/core.v
SBY
( cd "$W" && sby -f core.sby > sby.log 2>&1 ); rc=$?
grep -E "DONE|summary: engine" "$W/core/logfile.txt" 2>/dev/null | tail -2 || tail -5 "$W/sby.log"
case $rc in
  0) echo "core invariant: PROVED" ;;
  2) echo "core invariant: FAILED (counterexample: $W/core/engine_0/trace.vcd)" ;;
  *) echo "core invariant: ERROR (rc=$rc, see $W/core/logfile.txt)" ;;
esac

# ── 2. register file: ReadOneHotA = 1 (select = 1 << raddr_a) == ReadOneHotA = 0
RF="$REPO/build/ibex_register_file_ff.sv"
[ -f "$RF" ] || { echo "missing $RF (run make build)"; exit 2; }
SHIFT=1; [ "${1:-}" = "--mutant" ] && SHIFT=2
sed -E 's/^(module[[:space:]]+)ibex_register_file_ff([^A-Za-z0-9_]|$)/\1gold_top\2/' "$RF" > "$W/rf_gold.sv"
# gate: the same module with ReadOneHotA = 1 and the one-hot select driven by
# the premise proved in step 1 instead of by a port
sed -E -e 's/^(module[[:space:]]+)ibex_register_file_ff([^A-Za-z0-9_]|$)/\1gate_top\2/' \
       -e 's/parameter int ReadOneHotA = 0,/parameter int ReadOneHotA = 1,/' \
       -e '/^  input logic \[NUM_WORDS-1:0\] raddr_a_oh_i,$/d' "$RF" > "$W/rf_gate.sv"
python3 - "$W/rf_gate.sv" "$SHIFT" <<'PY'
import sys
p, k = sys.argv[1], sys.argv[2]; s = open(p).read()
a = "  logic [NUM_WORDS-1:0] [DataWidth-1:0] rdata_a_oh_terms;\n"
assert s.count(a) == 1 and "ReadOneHotA = 1," in s and "raddr_a_oh_i," not in s
s = s.replace(a, a + f"  logic [NUM_WORDS-1:0] raddr_a_oh_i;\n  assign raddr_a_oh_i = NUM_WORDS'({k}) << raddr_a_i;\n")
open(p, "w").write(s)
PY
grep -q "module gold_top" "$W/rf_gold.sv" && grep -q "module gate_top" "$W/rf_gate.sv" || { echo "module rename failed"; exit 2; }
sv2v "$W/rf_gold.sv" > "$W/rf_gold.v" && sv2v "$W/rf_gate.sv" > "$W/rf_gate.v" || { echo "sv2v failed"; exit 2; }
cat > "$W/rf.ys" <<YS
read_verilog $W/rf_gold.v
read_verilog $W/rf_gate.v
hierarchy -check
proc; flatten; async2sync; opt_clean; memory -nomap; memory_map; opt -fast
equiv_make gold_top gate_top equiv
hierarchy -top equiv
equiv_simple -seq 5
equiv_induct -seq 5
equiv_status -assert
YS
if yosys -q -l "$W/rf.log" -s "$W/rf.ys" >/dev/null 2>&1; then
  echo "register file: PROVED ($(grep -oE 'Found [0-9]+ \$equiv cells' "$W/rf.log" | tail -1))"; rf=0
else
  echo "register file: NOT PROVED ($(grep -oE 'Found [0-9]+ unproven \$equiv cells' "$W/rf.log" | tail -1))"; rf=1
fi
[ $rc -eq 0 ] && [ $rf -eq 0 ]
