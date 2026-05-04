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
