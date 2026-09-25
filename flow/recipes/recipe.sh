# Per-lane flow recipes. Sourced by flow/sky130_synth.sh, flow/openroad/run.sh
# and flow/openroad/estimate.sh.
#
# The Arch and SV lanes are different designs, so each closes timing with its
# own recipe: flow/recipes/<lane>.env, one KEY=VALUE per line (# comments).
# Precedence, per knob: an explicitly set environment variable, then the
# lane's recipe file, then the knob's default (the plain flow).
# FLOW_RECIPE=none ignores the recipe files, which reproduces the submitted
# paper's flow (identical settings on both lanes; review-package/).
#
#   recipe_value <lane> <KNOB> <default>   prints the value to use
#   recipe_describe <lane> <KNOB>[=default]...
#                                          prints "KNOB=value (source)" lines
#                                          (default 0 when not given)
recipe_value() {
  local lane="$1" knob="$2" def="$3" f v
  if [ -n "${!knob+x}" ]; then printf '%s\n' "${!knob}"; return; fi
  f="$REPO_ROOT/flow/recipes/$lane.env"
  if [ "${FLOW_RECIPE:-lane}" != none ] && [ -f "$f" ]; then
    v=$(sed -n "s/^$knob=\([^ #]*\).*/\1/p" "$f" | tail -1)
    if [ -n "$v" ]; then printf '%s\n' "$v"; return; fi
  fi
  printf '%s\n' "$def"
}
recipe_describe() {
  local lane="$1" arg knob def src; shift
  for arg in "$@"; do
    knob="${arg%%=*}"; def=0; [ "$arg" != "$knob" ] && def="${arg#*=}"
    if [ -n "${!knob+x}" ]; then src=env
    elif [ "${FLOW_RECIPE:-lane}" != none ] && [ -f "$REPO_ROOT/flow/recipes/$lane.env" ] \
         && grep -q "^$knob=" "$REPO_ROOT/flow/recipes/$lane.env"; then src="flow/recipes/$lane.env"
    else src=default; fi
    printf '%s=%s (%s)\n' "$knob" "$(recipe_value "$lane" "$knob" "$def")" "$src"
  done
}
