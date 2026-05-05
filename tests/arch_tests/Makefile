# Build rules for the RISC-V Architectural Test sources.
#
# For each test under
#   $(ARCH_TEST_SRC)/rv32i_m/{I,M,C}/src/<name>.S
# this Makefile produces:
#   $(BUILD)/<isa>/<name>.elf   — linked ELF
#   $(BUILD)/<isa>/<name>.bin   — flat binary (objcopy -O binary)
#   $(BUILD)/<isa>/<name>.vmem  — one 32-bit word per line, $readmemh-ready
#   $(BUILD)/<isa>/<name>.dis   — disassembly
#   $(BUILD)/<isa>/<name>.syms  — `nm` dump (cocotb pulls
#                                  begin_signature/end_signature/done_marker)
#
# Invoked from the pytest harness as:
#   make -C tests/arch_tests BUILD=<tmp> all
# or for a single test:
#   make -C tests/arch_tests BUILD=<tmp> <tmp>/I/add-01.vmem

CROSS     ?= riscv64-elf-
AS        := $(CROSS)gcc
LD        := $(CROSS)gcc
OBJCOPY   := $(CROSS)objcopy
OBJDUMP   := $(CROSS)objdump
NM        := $(CROSS)nm

MARCH     := rv32imc_zicsr
MABI      := ilp32

# Locations.
TESTS_DIR     := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ENV_DIR       := $(TESTS_DIR)/env
ARCH_TEST_SRC ?= $(HOME)/github/ibex/vendor/riscv-arch-tests/riscv-test-suite
ARCH_ENV_DIR  := $(ARCH_TEST_SRC)/env

# Include path: our model_test.h FIRST so it shadows any in-tree default.
# arch_test.h itself lives in the arch-tests env dir.
INCLUDES  := -I$(ENV_DIR) -I$(ARCH_ENV_DIR)

# `-march` includes Zicsr because some tests use csr* on misa/etc.
# `--no-relax` keeps `la` from being shrunk via gp-relative addressing.
ASFLAGS   := -march=$(MARCH) -mabi=$(MABI) -c $(INCLUDES)
CFLAGS    := -march=$(MARCH) -mabi=$(MABI) -nostdlib -nostartfiles \
             -ffreestanding -Os -g \
             -Wl,-T,$(ENV_DIR)/link.ld -Wl,--no-relax

BUILD     ?= build

# Discover every .S in each ISA dir at make time.
I_TESTS   := $(notdir $(wildcard $(ARCH_TEST_SRC)/rv32i_m/I/src/*.S))
M_TESTS   := $(notdir $(wildcard $(ARCH_TEST_SRC)/rv32i_m/M/src/*.S))
C_TESTS   := $(notdir $(wildcard $(ARCH_TEST_SRC)/rv32i_m/C/src/*.S))

I_VMEMS   := $(I_TESTS:%.S=$(BUILD)/I/%.vmem)
M_VMEMS   := $(M_TESTS:%.S=$(BUILD)/M/%.vmem)
C_VMEMS   := $(C_TESTS:%.S=$(BUILD)/C/%.vmem)

I_SYMS    := $(I_TESTS:%.S=$(BUILD)/I/%.syms)
M_SYMS    := $(M_TESTS:%.S=$(BUILD)/M/%.syms)
C_SYMS    := $(C_TESTS:%.S=$(BUILD)/C/%.syms)

ALL_VMEMS := $(I_VMEMS) $(M_VMEMS) $(C_VMEMS)
ALL_SYMS  := $(I_SYMS)  $(M_SYMS)  $(C_SYMS)

.PHONY: all I M C clean
all: $(ALL_VMEMS) $(ALL_SYMS)
I:   $(I_VMEMS) $(I_SYMS)
M:   $(M_VMEMS) $(M_SYMS)
C:   $(C_VMEMS) $(C_SYMS)

$(BUILD)/I $(BUILD)/M $(BUILD)/C:
	mkdir -p $@

# Per-ISA pattern rules. We can't use a single pattern across I/M/C
# because make's pattern matching only takes one stem.

$(BUILD)/I/%.o: $(ARCH_TEST_SRC)/rv32i_m/I/src/%.S | $(BUILD)/I
	$(AS) $(ASFLAGS) -o $@ $<

$(BUILD)/M/%.o: $(ARCH_TEST_SRC)/rv32i_m/M/src/%.S | $(BUILD)/M
	$(AS) $(ASFLAGS) -o $@ $<

$(BUILD)/C/%.o: $(ARCH_TEST_SRC)/rv32i_m/C/src/%.S | $(BUILD)/C
	$(AS) $(ASFLAGS) -o $@ $<

# ELF / bin / vmem / disassembly / symbols
$(BUILD)/%.elf: $(BUILD)/%.o $(ENV_DIR)/link.ld
	$(LD) $(CFLAGS) -o $@ $<

$(BUILD)/%.bin: $(BUILD)/%.elf
	$(OBJCOPY) -O binary $< $@

# bin2vmem.py reuses tests/sw/bin2vmem.py — flat 32-bit-word vmem,
# no @addr lines (matches what tests/cocotb_tests/test_timer_isr.py
# already understands).
$(BUILD)/%.vmem: $(BUILD)/%.bin
	python3 $(TESTS_DIR)/../sw/bin2vmem.py $< $@

$(BUILD)/%.dis: $(BUILD)/%.elf
	$(OBJDUMP) -d -M no-aliases $< > $@

$(BUILD)/%.syms: $(BUILD)/%.elf
	$(NM) $< > $@

clean:
	rm -rf $(BUILD)
