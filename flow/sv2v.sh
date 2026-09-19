#!/usr/bin/env bash
# Convert each lane's ibex_top filelist to a single Verilog-2005 file with sv2v.
#   flow/sv2v.sh            -> flow/out/sv/ibex_top.v and flow/out/arch/ibex_top.v
# Env: IBEX_ROOT (default ~/github/ibex). Logs: flow/out/<lane>/sv2v.log
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export IBEX_ROOT="${IBEX_ROOT:-$HOME/github/ibex}"
export REPO_ROOT
rc=0
for lane in sv arch; do
  out="$REPO_ROOT/flow/out/$lane"; mkdir -p "$out"
  args=(); files=()
  while IFS= read -r line; do
    line="${line//\$\{IBEX_ROOT\}/$IBEX_ROOT}"; line="${line//\$\{REPO_ROOT\}/$REPO_ROOT}"
    case "$line" in
      ''|'#'*) ;;
      +incdir+*) args+=("-I${line#+incdir+}") ;;
      -D*) args+=("--define=${line#-D}") ;;
      *) files+=("$line") ;;
    esac
  done < "$REPO_ROOT/flow/ibex_top_${lane}.f"
  echo "sv2v [$lane]: ${#files[@]} files"
  if sv2v --define=SYNTHESIS --define=YOSYS "${args[@]}" --write="$out/ibex_top.v" "${files[@]}" > "$out/sv2v.log" 2>&1; then
    echo "  ok: $out/ibex_top.v ($(wc -l < "$out/ibex_top.v" | tr -d ' ') lines)"
  else
    echo "  FAILED (see $out/sv2v.log)"; tail -5 "$out/sv2v.log"; rc=1
  fi
done
exit $rc
