# Top-level driver. Each phase swap is:
#   1. write/edit src/IbexFoo.arch
#   2. `make build`            -> arch -> build/IbexFoo.sv
#   3. add "ibex_foo" to scripts/gen_filelist.py SWAPPED set
#   4. `make filelist`         -> writes build/ibex_soc.vc
#   5. `make lint`             -> verilator --lint-only
#   6. `make test`             -> pytest gate (4 ISR programs)

.PHONY: build filelist lint test clean

REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BUILD_DIR := $(REPO_ROOT)/build

build:
	@bash scripts/build.sh

filelist: $(BUILD_DIR)/ibex_soc.vc

$(BUILD_DIR)/ibex_soc.vc: scripts/gen_filelist.py
	@mkdir -p $(BUILD_DIR)
	@python3 scripts/gen_filelist.py $@
	@echo "wrote $@"

lint: filelist
	verilator --lint-only -f $(BUILD_DIR)/ibex_soc.vc --top-module ibex_mini_soc

test:
	pytest tests/

clean:
	rm -rf $(BUILD_DIR)
