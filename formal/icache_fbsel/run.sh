#!/bin/bash
# formal/icache_fbsel/run.sh <task> [<task> ...]    (needs `make build` first)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
W="$ROOT/flow/out/formal_fbsel"
python3 "$ROOT/formal/icache_fbsel/make.py" "$W"
cp "$ROOT/formal/icache_fbsel/fbsel.sby" "$W/"
cd "$W"
for t in "$@"; do
  echo "== $t"
  { sby -f fbsel.sby "$t" 2>&1 || true; } | grep -E "returned|failed assertion|reached cover|unreached|DONE" || true
done
