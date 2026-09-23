#!/bin/bash
# Usage: formal/run_grant_lemma.sh "<verilog defines>" [depth]
# Requires SymbiYosys + z3 (engine smtbmc z3).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
D="${1:-}"; DEPTH="${2:-12}"
W="$ROOT/flow/out/formal"; mkdir -p "$W"; cp "$ROOT/formal/icache_grant_lemma.sv" "$W/"
cat > "$W/job.sby" <<SBY
[options]
mode bmc
depth $DEPTH
[engines]
smtbmc z3
[script]
read -formal $D icache_grant_lemma.sv
prep -top icache_grant_lemma
[files]
icache_grant_lemma.sv
SBY
cd "$W" && rm -rf job && sby -f job.sby 2>&1 | grep -E 'returned|failed assertion|DONE'
