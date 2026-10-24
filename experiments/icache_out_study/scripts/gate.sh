#!/bin/bash
# gate.sh <cfg>  -- build, build-synth, full make test, coremark; logs under $S/logs/<cfg>/
source ${STUDY_SCRATCH:?}/env.sh
cfg="$1"; L="$S/logs/$cfg"; mkdir -p "$L"
cd "$W" || exit 1
git rev-parse HEAD > "$L/head.txt"; git status --short >> "$L/head.txt"
step() { echo "== $1 $(date +%T)"; }
step build;       make build > "$L/build.log" 2>&1; echo "build rc=$?"
step buildsynth;  make build-synth > "$L/build_synth.log" 2>&1; echo "build-synth rc=$?"
step maketest;    python3 -m pytest tests/ -n auto --dist=loadfile -q -rfE > "$L/make_test.log" 2>&1; echo "make test rc=$?"; tail -15 "$L/make_test.log"
step coremark;    RUN_COREMARK_COMPARE=1 python3 -m pytest -q -s tests/test_coremark_compare.py > "$L/coremark.log" 2>&1; echo "coremark rc=$?"; grep -iE "dut_ticks|dut_cm|ref_|passed|failed" "$L/coremark.log" | tail -8
step done
