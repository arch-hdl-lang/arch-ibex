#!/usr/bin/env bash
# Compile every .arch source under src/ into build/ as SystemVerilog.
#
# Usage:
#   scripts/build.sh                  # build everything
#   scripts/build.sh IbexAlu          # build a single module by stem
#
# Environment:
#   ARCH_BIN   path to `arch` binary (default: ../arch-com/target/{release,debug}/arch
#              if present; otherwise `arch` on PATH, ignoring macOS /usr/bin/arch)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${REPO_ROOT}/src"
BUILD_DIR="${REPO_ROOT}/build"

resolve_arch_bin() {
  if [[ -n "${ARCH_BIN:-}" && -x "${ARCH_BIN}" ]]; then
    echo "${ARCH_BIN}"; return
  fi
  for cand in \
      "${REPO_ROOT}/../arch-com/target/release/arch" \
      "${REPO_ROOT}/../arch-com/target/debug/arch"; do
    if [[ -x "${cand}" ]]; then
      echo "${cand}"; return
    fi
  done
  # Fall back to PATH, but skip macOS /usr/bin/arch (an unrelated system tool).
  local found
  found="$(command -v arch || true)"
  if [[ -n "${found}" && "${found}" != "/usr/bin/arch" ]]; then
    echo "${found}"; return
  fi
  echo ""
}

ARCH_BIN="$(resolve_arch_bin)"
if [[ -z "${ARCH_BIN}" ]]; then
  echo "error: arch compiler not found." >&2
  echo "  Build arch-com (cargo build --release in ~/github/arch-com) or set ARCH_BIN." >&2
  exit 1
fi

mkdir -p "${BUILD_DIR}"

if [[ $# -eq 0 ]]; then
  shopt -s nullglob
  files=("${SRC_DIR}"/*.arch)
  if [[ ${#files[@]} -eq 0 ]]; then
    echo "no .arch files in ${SRC_DIR} yet"
    exit 0
  fi
else
  files=()
  for stem in "$@"; do
    files+=("${SRC_DIR}/${stem}.arch")
  done
fi

_build_one() {
  local f="$1"
  # The SV module name is the upstream snake_case basename (e.g.
  # `ibex_alu`), but our `.arch` source uses CamelCase (e.g. `IbexAlu.arch`).
  # The conftest's swap-shadow logic matches on basename equality with the
  # upstream `.sv` file, so the output must land at `build/<snake>.sv`.
  local arch_stem
  arch_stem="$(basename "${f}" .arch)"
  local sv_stem
  sv_stem="$(echo "${arch_stem}" | sed -E 's/([a-z0-9])([A-Z])/\1_\2/g; s/([A-Z]+)([A-Z][a-z])/\1_\2/g' | tr '[:upper:]' '[:lower:]')"
  echo "arch build $(basename "${f}") → build/${sv_stem}.sv"
  "${ARCH_BIN}" build -o "${BUILD_DIR}/${sv_stem}.sv" "${f}"

  # When a consumer `use`s a package via .archi auto-resolution,
  # `arch build -o` inlines the package contents into the consumer's
  # own .sv (alongside the `import Pkg::*;`). When all consumer SVs
  # are linked together at SoC elaboration, Verilator sees N
  # duplicate `package <Name>;` declarations and errors with
  # MODDUP. The standalone `ibex_<pkg>.sv` (built from the package
  # source itself) is the canonical declaration; consumer SVs need
  # only the `import` line. Strip the inlined `package ... endpackage`
  # blocks from any non-package consumer SV.
  if [[ "${arch_stem}" != "IbexCoreSharedPkg" ]]; then
    local sv_path="${BUILD_DIR}/${sv_stem}.sv"
    if [[ -f "${sv_path}" ]] && grep -q '^import IbexCoreSharedPkg::\*;' "${sv_path}"; then
      # Delete the `package IbexCoreSharedPkg; ... endpackage` block in
      # place. The package occurrence is contiguous and starts at
      # column 0; awk between its open and close lines.
      awk '
        /^package IbexCoreSharedPkg;/ { in_pkg = 1; next }
        in_pkg && /^endpackage$/      { in_pkg = 0; next }
        !in_pkg                        { print }
      ' "${sv_path}" > "${sv_path}.tmp" && mv "${sv_path}.tmp" "${sv_path}"
    fi
  fi

  # Same pattern, but for top-level constructs (modules / fsms / arbiters
  # / cams / threads-helper) that arch-com inlines into a consumer's .sv
  # when the consumer `inst`s them. Each sibling `.archi` in src/
  # corresponds to its own `.arch` source whose own `.sv` will be linked
  # at SoC elaboration. The inlined copies in the consumer .sv produce
  # MODDUP. Strip every inlined `module <X> ... endmodule` block whose
  # name matches a sibling `<X>.archi` BUT NOT the consumer's own
  # primary construct (the one named after the .arch stem). See D1 lesson
  # (port-ibex_icache, where IbexIcache inst's 6 sibling constructs).
  local sv_path="${BUILD_DIR}/${sv_stem}.sv"
  if [[ -f "${sv_path}" ]]; then
    # Build the strip set from sibling .archi names, excluding the
    # consumer's own auto-emitted .archi.
    local -a strip_names=()
    shopt -s nullglob
    # Build the strip set from sibling .archi names. Every .archi
    # represents a module that's emitted as a separate .sv (either
    # because it has its own .arch source, or because it's an
    # auto-generated `_<owner>_threads` helper whose .sv is co-emitted
    # by the owner's build). We exclude:
    #   1. `IbexCoreSharedPkg` (handled by the package strip above).
    #   2. The consumer's own primary archi, in CamelCase form
    #      (`IbexTop`) or snake_case form (`ibex_top`).
    #   3. The consumer's own `_<self>_threads.archi`, which lives
    #      inlined inside the owner's .sv (no separate .sv emitted).
    # Threads helper name follows the .arch source's `module <name>`
    # decl, which may use either CamelCase (`FillBufferCtrl`) or
    # snake_case (`ibex_multdiv_fast`). Exclude both forms.
    local self_threads_camel="_${arch_stem}_threads"
    local self_threads_snake="_${sv_stem}_threads"
    for archi_path in "${SRC_DIR}"/*.archi; do
      local archi_stem
      archi_stem="$(basename "${archi_path}" .archi)"
      if [[ "${archi_stem}" == "IbexCoreSharedPkg" ]]; then continue; fi
      if [[ "${archi_stem}" == "${arch_stem}" ]]; then continue; fi
      if [[ "${archi_stem}" == "${sv_stem}" ]]; then continue; fi
      if [[ "${archi_stem}" == "${self_threads_camel}" ]]; then continue; fi
      if [[ "${archi_stem}" == "${self_threads_snake}" ]]; then continue; fi
      strip_names+=("${archi_stem}")
    done
    shopt -u nullglob

    if [[ ${#strip_names[@]} -gt 0 ]]; then
      # Pass the strip set to awk as a regex alternation matching the
      # exact module-name token after `module ` (with optional `#(`
      # parameter list or `(` port list).
      local strip_alt
      strip_alt="$(printf '%s|' "${strip_names[@]}" | sed 's/|$//')"
      awk -v alt="${strip_alt}" '
        BEGIN { in_mod = 0 }
        # Match `module <NAME>` where NAME ∈ strip_alt, at column 0.
        $0 ~ ("^module (" alt ")( |#|\\(|$)") { in_mod = 1; next }
        in_mod && /^endmodule$/ { in_mod = 0; next }
        !in_mod { print }
      ' "${sv_path}" > "${sv_path}.tmp" && mv "${sv_path}.tmp" "${sv_path}"
    fi
  fi
}

# Topological build: composites can instantiate other composites
# (e.g. IbexIfStage → IbexPrefetchBuffer), so leaves-then-composites
# isn't enough. Each pass picks every file whose `inst <name>:` deps
# all already have a `.archi` in src/, builds them, and retries the
# rest until empty. The arch-com dep walker matches inst names
# (snake_case) against filenames (CamelCase) so it can't resolve our
# naming convention itself.
remaining=("${files[@]}")
max_passes=$((${#files[@]} + 1))
pass=0
while [[ ${#remaining[@]} -gt 0 && $pass -lt $max_passes ]]; do
  pass=$((pass + 1))
  next_remaining=()
  built_this_pass=0
  for f in "${remaining[@]}"; do
    inst_modules=$( { grep -E "^[[:space:]]*inst[[:space:]]+[A-Za-z_][A-Za-z0-9_]*[[:space:]]*:[[:space:]]*[A-Za-z_][A-Za-z0-9_]*" "${f}" 2>/dev/null || true; } \
      | sed -E 's/^[[:space:]]*inst[[:space:]]+[A-Za-z_][A-Za-z0-9_]*[[:space:]]*:[[:space:]]*([A-Za-z_][A-Za-z0-9_]*).*/\1/')
    deps_ready=1
    for dep in ${inst_modules}; do
      # `.archi` lands next to the `.arch` source in src/.
      if [[ ! -f "${SRC_DIR}/${dep}.archi" ]]; then
        deps_ready=0
        break
      fi
    done
    if [[ $deps_ready -eq 1 ]]; then
      _build_one "${f}"
      built_this_pass=$((built_this_pass + 1))
    else
      next_remaining+=("${f}")
    fi
  done
  if [[ $built_this_pass -eq 0 ]]; then
    echo "error: scripts/build.sh cannot resolve inst deps for:" >&2
    for f in "${next_remaining[@]}"; do
      missing=$(grep -Eo "^[[:space:]]*inst[[:space:]]+[A-Za-z_][A-Za-z0-9_]*[[:space:]]*:[[:space:]]*[A-Za-z_][A-Za-z0-9_]*" "${f}" \
        | sed -E 's/.*:[[:space:]]*//' \
        | while read d; do [[ -f "${SRC_DIR}/${d}.archi" ]] || echo "$d"; done | tr '\n' ' ')
      echo "  $(basename "${f}") — missing: ${missing}" >&2
    done
    exit 1
  fi
  remaining=("${next_remaining[@]}")
done
