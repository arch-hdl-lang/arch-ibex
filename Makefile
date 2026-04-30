# Top-level driver for arch-ibex.
#
# Per-swap loop:
#   1. write/edit src/IbexFoo.arch
#   2. `make build`            -> arch -> build/ibex_foo.sv
#   3. `make lint`             -> verilator --lint-only on the swapped SoC
#   4. `make test`             -> full gate (lint + ISR programs + unit suites)
#
# Lint composes the SoC filelist via fusesoc (vendor incdirs / -D defines
# come from the upstream Ibex core file); we route through the
# tests/test_soc_lint.py harness rather than duplicating that logic.

.PHONY: build lint test clean

REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BUILD_DIR := $(REPO_ROOT)/build

build:
	@bash scripts/build.sh

lint:
	pytest tests/test_soc_lint.py

test:
	# `-n auto --dist=loadfile`: parallelize across test files so each
	# file's session-scoped fixtures (notably ibex_soc_filelist's
	# fusesoc setup) build once per worker, not once per case. Falls
	# back gracefully to sequential when pytest-xdist isn't installed.
	pytest tests/ -n auto --dist=loadfile

clean:
	rm -rf $(BUILD_DIR)
