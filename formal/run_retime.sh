#!/bin/bash
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
D="${1:-}"; DEPTH="${2:-12}"
W="$ROOT/flow/out/formal_rt"; mkdir -p "$W"; cp "$ROOT/formal/icache_grant_retime.sv" "$W/"
cat > "$W/job.sby" <<SBY
[options]
mode bmc
depth $DEPTH
[engines]
smtbmc z3
[script]
read -formal $D icache_grant_retime.sv
prep -top icache_grant_retime
[files]
icache_grant_retime.sv
SBY
cd "$W" && rm -rf job && sby -f job.sby 2>&1 | grep -E 'returned|failed assertion|DONE'
