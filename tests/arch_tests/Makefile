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

# Each suite is assembled for its own ISA, as the framework does (riscof
# builds a test with the ISA it declares): rv32i_m/I as RV32I, M as RV32IM,
# C as RV32IC. That matters beyond legality: with C enabled the assembler
# compresses the I/M tests' code, which moves the PC-relative values that
# jal-01 / jalr-01 store into their signatures, so they would no longer
# match the suite's reference outputs. Zicsr and Zifencei are added for the
# framework's trap setup (cebreak-01's handler uses fence.i); they change no
# encoding. MARCH is only used for linking.
MARCH     := rv32imc_zicsr_zifencei
MARCH_I   := rv32i_zicsr_zifencei
MARCH_M   := rv32im_zicsr_zifencei
MARCH_C   := rv32ic_zicsr_zifencei
# Exception: jal-01 pads its jumps with `nop`s and is about 1.7 MB as RV32I,
# more than the SoC's 1 MB RAM. Assembled with C (compressed nops) it fits,
# but its PC-relative signature values then differ from the suite's RV32I
# reference outputs, so it is checked against upstream Ibex only.
JAL01_MARCH := rv32ic_zicsr_zifencei
MABI      := ilp32

# Locations.
TESTS_DIR     := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ENV_DIR       := $(TESTS_DIR)/env
ARCH_TEST_SRC ?= $(HOME)/github/ibex/vendor/riscv-arch-tests/riscv-test-suite
ARCH_ENV_DIR  := $(ARCH_TEST_SRC)/env

# Include path: our model_test.h FIRST so it shadows any in-tree default;
# then the patched arch_test.h (below); then the arch-tests env dir for
# everything else (encoding.h, test_macros.h).
#
# arch_test.h is the vendored framework header with env/arch_test.h.patch
# applied, built into $(BUILD)/env. The patch backports the framework's
# RVMODEL_MTVEC_ALIGN hook (upstream 062a3908da), which model_test.h uses to
# put the trap trampoline where Ibex's 256-byte-aligned mtvec can point.
# It only affects the trap handler, which is assembled only for tests with
# a trap handler (cebreak-01), so every other image is unchanged. `patch`
# fails loudly if the vendored header ever changes under it.
PATCHED_ENV_DIR = $(BUILD)/env
PATCHED_ARCH_TEST_H = $(PATCHED_ENV_DIR)/arch_test.h
INCLUDES  = -I$(ENV_DIR) -I$(PATCHED_ENV_DIR) -I$(ARCH_ENV_DIR)

# `--no-relax` keeps `la` from being shrunk via gp-relative addressing.
ASFLAGS   = -mabi=$(MABI) -c $(INCLUDES)
# Test-case defines. Every test body sits under `#ifdef TEST_CASE_1` (and
# cebreak-01's trap handler under `rvtest_mtrap_routine`); the framework
# (riscof) turns each `def NAME=VALUE` in the RVTEST_CASE strings of a test
# whose `check ISA` conditions match the target into -DNAME=VALUE. Without
# them every test assembles to the init/halt stub and passes vacuously.
# All RVTEST_CASE conditions in rv32i_m/{I,M,C} match this target
# (RV32IMC + Zicsr): `.*32.*` with `.*I.*`, `.*I.*M.*`, `.*I.*Zmmul.*`,
# `.*I.*C.*`, `.*RV32.*I.*C.*` or `.*I.*Zicsr.*.C*`, so every `def` applies.
case_defs = $(shell grep -o 'RVTEST_CASE.*' $(1) | grep -o 'def [A-Za-z_][A-Za-z0-9_]*=[A-Za-z0-9_]*' | sed 's/^def /-D/' | sort -u)
# $(call assemble,<march>): assemble one test with its defines. A test
# with none is refused (it would assemble to an empty body).
define assemble
@defs="$(call case_defs,$<)"; \
	  if [ -z "$$defs" ]; then echo "error: no RVTEST_CASE defines in $<" >&2; exit 1; fi; \
	  echo "$(AS) -march=$(1) $(ASFLAGS) $$defs -o $@ $<"; \
	  $(AS) -march=$(1) $(ASFLAGS) $$defs -o $@ $<
endef

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

$(PATCHED_ARCH_TEST_H): $(ARCH_ENV_DIR)/arch_test.h $(ENV_DIR)/arch_test.h.patch
	mkdir -p $(@D)
	cp $(ARCH_ENV_DIR)/arch_test.h $@.tmp
	patch --quiet --forward $@.tmp $(ENV_DIR)/arch_test.h.patch
	mv $@.tmp $@

# Per-ISA pattern rules. We can't use a single pattern across I/M/C
# because make's pattern matching only takes one stem.

$(BUILD)/I/%.o: $(ARCH_TEST_SRC)/rv32i_m/I/src/%.S $(PATCHED_ARCH_TEST_H) $(ENV_DIR)/model_test.h | $(BUILD)/I
	$(call assemble,$(MARCH_I))

$(BUILD)/I/jal-01.o: MARCH_I := $(JAL01_MARCH)

$(BUILD)/M/%.o: $(ARCH_TEST_SRC)/rv32i_m/M/src/%.S $(PATCHED_ARCH_TEST_H) $(ENV_DIR)/model_test.h | $(BUILD)/M
	$(call assemble,$(MARCH_M))

$(BUILD)/C/%.o: $(ARCH_TEST_SRC)/rv32i_m/C/src/%.S $(PATCHED_ARCH_TEST_H) $(ENV_DIR)/model_test.h | $(BUILD)/C
	$(call assemble,$(MARCH_C))

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
