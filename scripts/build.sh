#!/usr/bin/env bash
# Compile every .arch source under src/ into build/ as SystemVerilog.
#
# Usage:
#   scripts/build.sh                  # build everything
#   scripts/build.sh IbexAlu          # build a single module by stem
#
# Environment:
#   ARCH_BIN   path to `arch` binary (default: looked up on PATH)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${REPO_ROOT}/src"
BUILD_DIR="${REPO_ROOT}/build"
ARCH_BIN="${ARCH_BIN:-arch}"

if ! command -v "${ARCH_BIN}" >/dev/null 2>&1; then
  echo "error: '${ARCH_BIN}' not on PATH; set ARCH_BIN or build arch-com" >&2
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

for f in "${files[@]}"; do
  echo "arch build $(basename "${f}")"
  (cd "${BUILD_DIR}" && "${ARCH_BIN}" build "${f}")
done
