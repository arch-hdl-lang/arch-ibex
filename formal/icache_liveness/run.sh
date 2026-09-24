#!/bin/bash
# formal/icache_liveness/run.sh <task> [<task> ...]    (needs `make build` first)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
W="$ROOT/flow/out/formal_live"
python3 "$ROOT/formal/icache_liveness/make_variants.py" "$W" >/dev/null
cp "$ROOT/formal/icache_liveness/live.sby" "$W/"
# A FAIL is an expected verdict for several tasks, and sby exits non-zero on
# it -- so never let one task's verdict abort the rest of the loop.
cd "$W"
for t in "$@"; do
  echo "== $t"
  { sby -f live.sby "$t" 2>&1 || true; } | grep -E "returned|failed assertion|reached cover|DONE" || true
done
