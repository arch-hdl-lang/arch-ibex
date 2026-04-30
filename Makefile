# Top-level driver for arch-ibex.
#
# Per-swap loop:
#   1. write/edit src/IbexFoo.arch
#   2. `make build`            -> arch -> build/ibex_foo.sv
#   3. `make test`             -> SoC lint + ISR programs + unit suites
#
# `make test` is the real gate. Standalone lint over the SoC requires
# fusesoc-resolved vendor incdirs and is run inside tests/test_soc_lint.py.

.PHONY: build test clean

REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BUILD_DIR := $(REPO_ROOT)/build

build:
	@bash scripts/build.sh

test:
	# `-n auto --dist=loadfile`: parallelize across test files so each
	# file's session-scoped fixtures (notably ibex_soc_filelist's
	# fusesoc setup) build once per worker, not once per case. Falls
	# back gracefully to sequential when pytest-xdist isn't installed.
	pytest tests/ -n auto --dist=loadfile

clean:
	rm -rf $(BUILD_DIR)
