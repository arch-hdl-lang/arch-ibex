// model_test.h — RISC-V Architectural Test target adapter for the
// arch-ibex `ibex_mini_soc`. Plugged into each test under
// `vendor/riscv-arch-tests/riscv-test-suite/rv32i_m/{I,M,C}/src/*.S`
// via the gcc `-I` flag (see tests/arch_tests/Makefile).
//
// The arch-test framework in `arch_test.h` calls a handful of model-
// specific macros (`RVMODEL_BOOT`, `RVMODEL_HALT`, `RVMODEL_DATA_*`,
// IO no-ops). We only need them to:
//   1. Enter `_start` at the test's `rvtest_entry_point`. Our linker
//      script puts that at the Ibex reset vector (0x0010_0080) so
//      RVMODEL_BOOT is a no-op.
//   2. On HALT, stamp a known done-marker in RAM and infinite-loop.
//   3. Mark the signature region with the global symbols
//      `begin_signature` / `end_signature` so the cocotb harness can
//      dump it from RAM into a .signature file.
//
// IO_* macros are no-ops — our SoC is headless. The SET/CLEAR
// interrupt macros aren't used by the `rv32i_m/{I,M,C}` suite (those
// suites don't program the timer / SW interrupt path) so we leave the
// arch_test.h fallbacks in place.

#ifndef _COMPLIANCE_MODEL_H
#define _COMPLIANCE_MODEL_H

// `la x0, <sym>`: jalr-01's TEST_JALR_OP initialises rd with LA(rd, 5b),
// and one case has rd = x0. Current binutils reject `la` with x0 as the
// destination ("illegal operands"); older ones assembled it as
// auipc x0 / addi x0 (both no-ops). This assembler macro restores that for
// x0 only and is otherwise plain `lla`, which is what `la` assembles to
// without `.option pic` (every test here is non-PIC). Assembled images of
// all other tests are byte-identical with and without the macro.
.macro la rd:req, sym:req
.ifc \rd,x0
.Lmodel_la_x0\@:
  auipc x0, %pcrel_hi(\sym)
  addi  x0, x0, %pcrel_lo(.Lmodel_la_x0\@)
.else
  lla   \rd, \sym
.endif
.endm

// Aligned-to-word signature region.
#define RVMODEL_DATA_BEGIN                                              \
  .align 4; .global begin_signature; begin_signature:

// `end_signature` is a label (no bytes); `done_marker` immediately
// follows as a single word and shares its byte address. Signature
// dump reads RAM in [begin_signature, end_signature). The harness
// polls `done_marker` for the FEEDFACE sentinel that RVMODEL_HALT
// writes — that read is one word *past* end_signature.
#define RVMODEL_DATA_END                                                \
  .align 4; .global end_signature; end_signature:                       \
  .align 4; .global done_marker;   done_marker: .word 0;

// Reset trampoline at 0x0010_0080 jumps to rvtest_entry_point. We
// don't need any boot setup beyond what the linker script and the
// reset trampoline already do.
#define RVMODEL_BOOT

// Trap-handler alignment, log2 bytes. Ibex's mtvec BASE is 256-byte
// aligned and its MODE is always vectored ({wdata[31:8], 6'b0, 2'b01}), so
// the framework's trap trampoline must start on a 256-byte boundary for its
// `csrw mtvec, trampoline | mode` to read back unchanged. Otherwise the
// framework decides mtvec is not writable and falls back to copying the
// trampoline to wherever mtvec points. Out of reset that is the boot
// address 0x0010_0000, so the copy overwrites the running init code; and in
// this framework revision the copied trampoline's return to the common
// handler is PC-relative, so it never gets back to the original code.
// RVMODEL_MTVEC_ALIGN is the framework's model hook for this (riscv-arch-test
// 062a3908da). The vendored revision predates it, so env/arch_test.h.patch
// backports it. It only affects the trap handler, which is assembled only
// for tests with a trap handler (cebreak-01), so every other image is
// unchanged.
#define RVMODEL_MTVEC_ALIGN 8

// HALT: write 0xFEEDFACE to `done_marker` (placed by RVMODEL_DATA_END
// at the tail of the signature region) and spin. The cocotb harness
// polls `done_marker` to know when the test has finished, then dumps
// the signature region from `begin_signature` to `end_signature`.
#define RVMODEL_HALT                                                    \
  fence;                                                                \
  la    t0, done_marker;                                                \
  li    t1, 0xFEEDFACE;                                                 \
  sw    t1, 0(t0);                                                      \
1:                                                                      \
  j     1b

// IO no-ops — our SoC has no console.
#define RVMODEL_IO_INIT
#define RVMODEL_IO_WRITE_STR(_R, _STR)
#define RVMODEL_IO_CHECK()
#define RVMODEL_IO_ASSERT_GPR_EQ(_S, _R, _I)
#define RVMODEL_IO_ASSERT_SFPR_EQ(_F, _R, _I)
#define RVMODEL_IO_ASSERT_DFPR_EQ(_D, _R, _I)

// Software/timer/external interrupt hooks — not used by rv32i_m/{I,M,C},
// but the arch_test.h "warning" stubs are confusing if they fire, so
// just no-op them explicitly.
#define RVMODEL_SET_MSW_INT
#define RVMODEL_CLEAR_MSW_INT
#define RVMODEL_CLEAR_MTIMER_INT
#define RVMODEL_CLEAR_MEXT_INT

#endif // _COMPLIANCE_MODEL_H
