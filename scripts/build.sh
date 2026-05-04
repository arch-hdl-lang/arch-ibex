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

# Composite modules (Phase B+) instantiate leaf sub-modules and require
# those sub-modules' `.archi` stubs to exist first.  Separate them so
# leaf modules are always compiled before composites.
# A module is "composite" if it contains an `inst ` block; leaf modules
# do not. Run two passes: leaves first, composites second.
leaf_files=()
composite_files=()
for f in "${files[@]}"; do
  if grep -q $'^\s*inst ' "${f}" 2>/dev/null; then
    composite_files+=("${f}")
  else
    leaf_files+=("${f}")
  fi
done
ordered_files=("${leaf_files[@]}" "${composite_files[@]}")

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

for f in "${ordered_files[@]}"; do
  _build_one "${f}"
done
