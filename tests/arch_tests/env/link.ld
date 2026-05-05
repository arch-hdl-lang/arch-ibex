/* Linker script for the RISC-V Architectural Tests on ibex_mini_soc.
 *
 * Each test source uses:
 *   .section .text.init
 *   .org 0x80
 *   rvtest_entry_point:
 *
 * Ibex starts executing at boot_addr + 0x80 = 0x0010_0080 after reset
 * (our SoC's RAM base is 0x0010_0000). So we anchor `.text.init` at
 * the RAM base and the `.org 0x80` inside the test source lines
 * `rvtest_entry_point` up at 0x0010_0080 — the first instruction
 * executed.
 *
 * The signature region (between `begin_signature` and `end_signature`,
 * defined by the RVMODEL_DATA_BEGIN/END macros in our model_test.h)
 * lives in .data, just past the code. Both symbols are exported as
 * globals; the cocotb harness extracts them from the ELF and reads
 * those words back from RAM after the test halts.
 */

ENTRY(rvtest_entry_point)

MEMORY
{
  RAM (rwx) : ORIGIN = 0x00100000, LENGTH = 1M
}

SECTIONS
{
  /* Reset vector is at +0x80 inside .text.init. */
  .text.init 0x00100000 : {
    *(.text.init)
  } > RAM

  .text : ALIGN(4) {
    *(.text .text.*)
  } > RAM

  .rodata : ALIGN(4) {
    *(.rodata .rodata.*)
  } > RAM

  /* `.data` first, then the signature; arch_test.h's
   * RVMODEL_DATA_BEGIN/END stamp `begin_signature`/`end_signature`
   * symbols inside whichever section contains them. The tests place
   * RVTEST_DATA + the signature in the catch-all `.data` block. */
  .data : ALIGN(16) {
    *(.data .data.*)
    *(.sdata .sdata.*)
  } > RAM

  /* Trap signature region for tests that exercise the trap path
   * (none in rv32i_m/{I,M,C} but harmless). */
  .tohost : ALIGN(64) {
    *(.tohost)
  } > RAM

  .bss : ALIGN(4) {
    *(.bss .bss.*)
    *(.sbss .sbss.*)
    *(COMMON)
  } > RAM

  /* 4 KB stack at the top of the first 1 MB. */
  _stack_top = 0x001F0000;
}
