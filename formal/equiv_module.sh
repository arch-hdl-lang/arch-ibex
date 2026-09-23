#!/bin/bash
# Prove two versions of one generated module bit-exactly equivalent.
#
#   formal/equiv_module.sh <module> <gold.sv> <gate.sv> [shared.sv ...]
#
# For behaviour-preserving timing restructures (regfile, ALU, PMP, ...).
# The two versions are renamed gold_top / gate_top, flattened, and paired
# with equiv_make (registers matched by name), then discharged with
# equiv_simple + equiv_induct. Both sides go through sv2v first, with the
# shared files (packages) alongside. Exit 0 = PROVED, 1 = NOT PROVED, 2 = usage/tool error.
set -uo pipefail
[ $# -ge 3 ] || { echo "usage: $0 <module> <gold.sv> <gate.sv> [shared.sv ...]" >&2; exit 2; }
M=$1; GOLD=$2; GATE=$3; shift 3
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
sed -E "s/^([[:space:]]*module[[:space:]]+)$M([^A-Za-z0-9_]|$)/\1gold_top\2/" "$GOLD" > "$W/gold.sv"
sed -E "s/^([[:space:]]*module[[:space:]]+)$M([^A-Za-z0-9_]|$)/\1gate_top\2/" "$GATE" > "$W/gate.sv"
grep -q "module gold_top" "$W/gold.sv" && grep -q "module gate_top" "$W/gate.sv" \
  || { echo "module $M not found in inputs" >&2; exit 2; }
# sv2v each side together with the shared files (packages are inlined, so
# nothing is defined twice); Yosys's native frontend cannot parse the
# unpacked-array ports ARCH emits, which is why the synthesis flow does the same.
command -v sv2v >/dev/null || { echo "sv2v not found" >&2; exit 2; }
sv2v "$@" "$W/gold.sv" > "$W/gold.v" 2>"$W/sv2v.log" || { echo "sv2v failed on gold:"; cat "$W/sv2v.log"; exit 2; }
sv2v "$@" "$W/gate.sv" > "$W/gate.v" 2>"$W/sv2v.log" || { echo "sv2v failed on gate:"; cat "$W/sv2v.log"; exit 2; }
cat > "$W/e.ys" <<YS
read_verilog $W/gold.v
read_verilog $W/gate.v
hierarchy -check
proc; flatten; async2sync; opt_clean; memory -nomap; memory_map; opt -fast
equiv_make gold_top gate_top equiv
hierarchy -top equiv
equiv_simple -seq 5
equiv_induct -seq 5
equiv_status -assert
YS
if yosys -q -l "$W/log" -s "$W/e.ys" >/dev/null 2>&1; then
  echo "PROVED: $M gold == gate ($(grep -oE 'Found [0-9]+ \$equiv cells' "$W/log" | tail -1))"; exit 0
else
  echo "NOT PROVED: $M"; grep -iE "unproven|ERROR" "$W/log" | head -4; exit 1
fi
