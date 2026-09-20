#!/usr/bin/env bash
# Hierarchical (unflattened) sky130 synthesis, for per-module area attribution.
#
#   flow/sky130_hier_stat.sh          -> flow/out/<lane>/sky130/hier_area.rpt
#
# Mirrors review-package/reports/<lane>_sky130_synth.ys exactly EXCEPT that the
# explicit `flatten` is omitted, so per-module cell areas survive. The
# `memory -nomap` / `memory_map` handling either side of it is kept verbatim:
# it exists to keep inferred RAM write ports intact and is not flatten-specific.
#
# Unflattened totals are EXPECTED to exceed the flattened ones; cross-module
# optimisation is what flattening buys. The flattened numbers stay the
# headline (14-sky130.md); this is a breakdown.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIB=~/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
for lane in sv arch; do
  out="$REPO_ROOT/flow/out/$lane/sky130"; mkdir -p "$out"
  sed -e "s|\${REPO_ROOT}|$REPO_ROOT|g" -e "s|/sv/|/$lane/|g" \
      "$REPO_ROOT/flow/sky130_hier.ys.in" > "$out/hier.ys"
  echo "tee -o $out/hier_area.rpt stat -liberty $LIB" >> "$out/hier.ys"
  yosys -q -s "$out/hier.ys" 2>"$out/hier.log"
  echo "$lane -> $out/hier_area.rpt"
done
