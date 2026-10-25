#!/usr/bin/env bash
# icache swap matrix, synthesis side: four designs as flow lanes.
#
#   synth_lanes.sh prep            filelists + sv2v + recipe lanes
#   synth_lanes.sh ecp5-synth      synth_ecp5 once per design
#   synth_lanes.sh ecp5-pnr <tag> <design> <seed>   one nextpnr run
#   synth_lanes.sh sky130 <lane>   sky130 synth + pre-route estimate, one lane
#
# Designs (same split as tests/conftest.py ARCH_IBEX_ICACHE_MATRIX):
#   U     flow/ibex_top_sv.f as is
#   UAic  flow/ibex_top_sv.f, rtl/ibex_icache.sv replaced by the Arch icache
#         and its helpers from build-synth/
#   A     flow/ibex_top_arch.f as is
#   AUic  flow/ibex_top_arch.f minus the Arch icache set, plus rtl/ibex_icache.sv
# Each design's netlist lives in flow/out/<D>/ibex_top.v. A recipe lane
# <D>_r<sv|arch> (flow/out/<D>_r<x>/ibex_top.v -> ../<D>/ibex_top.v and
# flow/recipes/<D>_r<x>.env -> <x>.env) runs the unchanged flow scripts with
# that lane recipe. ECP5 runs on the <D>_rsv lane with the placer weight set
# explicitly (tag w40) or left at the nextpnr default (tag def; the sv recipe
# sets no weight); both tags place the same synth_ecp5 netlist.
# Requires `make build-synth` first. Outputs stay under flow/out/ (untracked);
# reports go to $REPORT_DIR (default /tmp/abcs/cmp/reports), never review-package/.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT" || exit 1
export IBEX_ROOT="${IBEX_ROOT:-$HOME/github/ibex}"
export REPORT_DIR="${REPORT_DIR:-/tmp/abcs/cmp/reports}"
mkdir -p "$REPORT_DIR"
ICACHE_SET="ibex_icache.sv inval_ctrl.sv fb_age_arb.sv bus_resp_fifo.sv ibex_icache_output_stage.sv"
DESIGNS="U UAic A AUic"
FL=experiments/icache_vs_upstream/filelists

is_icache() { local b; b=$(basename "$1"); for x in $ICACHE_SET; do [ "$b" = "$x" ] && return 0; done; return 1; }

prep() {
  mkdir -p "$FL"
  cp flow/ibex_top_sv.f "$FL/U.f"
  cp flow/ibex_top_arch.f "$FL/A.f"
  { grep -v '/rtl/ibex_icache.sv$' flow/ibex_top_sv.f
    for x in $ICACHE_SET; do echo "\${REPO_ROOT}/build-synth/$x"; done; } > "$FL/UAic.f"
  { while IFS= read -r l; do
      case "$l" in *'/build-synth/'*) is_icache "$l" && continue ;; esac
      echo "$l"
    done < flow/ibex_top_arch.f
    echo "\${IBEX_ROOT}/rtl/ibex_icache.sv"; } > "$FL/AUic.f"
  for d in $DESIGNS; do
    out="flow/out/$d"; mkdir -p "$out"
    args=(); files=()
    while IFS= read -r line; do
      line="${line//\$\{IBEX_ROOT\}/$IBEX_ROOT}"; line="${line//\$\{REPO_ROOT\}/$REPO_ROOT}"
      case "$line" in
        ''|'#'*) ;;
        +incdir+*) args+=("-I${line#+incdir+}") ;;
        -D*) args+=("--define=${line#-D}") ;;
        *) files+=("$line") ;;
      esac
    done < "$FL/$d.f"
    # same sv2v invocation as flow/sv2v.sh
    if sv2v --define=SYNTHESIS --define=YOSYS "${args[@]}" --write="$out/ibex_top.v" "${files[@]}" > "$out/sv2v.log" 2>&1; then
      echo "sv2v [$d]: ${#files[@]} files -> $(wc -l < "$out/ibex_top.v" | tr -d ' ') lines; icache: $(grep -c '^module ibex_icache\b' "$out/ibex_top.v") ibex_icache, $(grep -cE '^module (InvalCtrl|FbAgeArb|BusRespFifo|IbexIcacheOutputStage)\b' "$out/ibex_top.v") Arch helpers"
    else
      echo "sv2v [$d] FAILED"; tail -5 "$out/sv2v.log"; return 1
    fi
    for r in sv arch; do
      lane="${d}_r$r"; mkdir -p "flow/out/$lane"
      ln -sfn "../$d/ibex_top.v" "flow/out/$lane/ibex_top.v"
      ln -sfn "$r.env" "flow/recipes/$lane.env"
    done
  done
}

case "${1:-}" in
  prep) prep ;;
  ecp5-synth)
    for d in $DESIGNS; do
      ECP5_TAG=w40 bash flow/ecp5_pnr.sh synth "${d}_rsv" &
    done; wait
    for d in $DESIGNS; do
      mkdir -p "flow/out/${d}_rsv/ecp5_def"
      cp "flow/out/${d}_rsv/ecp5_w40/ibex_top.json" "flow/out/${d}_rsv/ecp5_w40/synth.stat" "flow/out/${d}_rsv/ecp5_def/"
    done ;;
  ecp5-pnr)
    tag="$2"; d="$3"; seed="$4"
    if [ "$tag" = w40 ]; then export ECP5_PLACER_TIMINGWEIGHT=40; else unset ECP5_PLACER_TIMINGWEIGHT; fi
    SEEDS="$seed" ECP5_TAG="$tag" REPORT_DIR="$REPORT_DIR/pnr_${tag}_${d}_s$seed" \
      bash flow/ecp5_pnr.sh pnr "${d}_rsv" ;;
  sky130)
    lane="$2"
    REPORT_DIR="$REPORT_DIR/sky130_$lane" bash flow/sky130_synth.sh "$lane" && \
      bash flow/openroad/estimate.sh "$lane" ;;
  *) sed -n '2,8p' "$0"; exit 2 ;;
esac
