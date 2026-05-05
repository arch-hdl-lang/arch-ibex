// C2-followup: WFI sleep-drain bring-up program.
//
// Exercises the post-WFI sleep-drain path end-to-end with a
// self-scheduled wake via the CLINT mtime / mtimecmp comparator
// (same trigger as timer_isr but with a WFI between arm and trap
// instead of a busy-wait):
//
//   _start arms mie.MTIE + mstatus.MIE, schedules the timer
//   comparator a small number of cycles into the future, raises
//   `wfi_armed` (handshake to the cocotb harness), then issues WFI.
//   The pipeline drains, `core_sleep_o` rises to 1.
//
//   The mtime counter keeps ticking while the core sleeps (it's
//   driven by the SoC's mtime register, not by the gated core
//   clock). When mtime >= mtimecmp, ClintLogic asserts mtip_out,
//   which propagates to ibex.irq_timer_i. The core wakes, takes
//   the M-timer interrupt (mcause = 0x8000_0007), the handler
//   acknowledges by clearing mie.MTIE (the standard pattern from
//   timer_isr), mret resumes past WFI, and main writes
//   `done_marker = 0xFEEDFACE`.
//
//   Asserts (in cocotb, see test_wfi_isr.py):
//     * core_sleep_o was observed at 1 between wfi_armed and the
//       trap (drain happened).
//     * core_sleep_o falls combinationally on irq_timer_i rise.
//     * saw_trap == 1, saved_mcause == 0x8000_0007.
//     * done_marker == 0xFEEDFACE (main resumed past WFI).

#include "common.h"

.section .text.trap, "ax"
.globl trap_entry
.align 2
trap_entry:
#include "vector_table.inc"

.section .text.reset, "ax"
.globl _reset
.align 2
_reset:
    j   _start

.section .text, "ax"
.globl _start
.align 2
_start:
    la     sp, _stack_top

    la     t0, trap_entry
    csrw   mtvec, t0

    // Enable only the M-timer interrupt source.
    li     t0, MIE_MTIE_MASK
    csrw   mie, t0

    // Schedule the comparator: mtimecmp = mtime + delta.
    // Pick delta = 32 cycles — generous enough that we observe
    // `core_sleep_o == 1` between WFI and trap, but tight enough
    // that simulation completes quickly.
    li     t0, CLINT_MTIME_LO
    lw     t1, 0(t0)             // mtime_lo
    addi   t1, t1, 32
    li     t0, CLINT_MTIMECMP_LO
    sw     t1, 0(t0)             // mtimecmp_lo = mtime_lo + 32
    sw     zero, 4(t0)           // mtimecmp_hi = 0

    // Unleash traps globally.
    li     t0, MSTATUS_MIE_MASK
    csrs   mstatus, t0

    // Signal to the cocotb harness that WFI is the next instruction.
    la     t0, wfi_armed
    li     t1, 1
    sw     t1, 0(t0)

    // Drain the pipeline and sleep until the comparator fires.
    wfi

    // Resume here after handler mret.
    la     t0, done_marker
    li     t1, 0xFEEDFACE
    sw     t1, 0(t0)

halt:
    j      halt


.globl common_trap_handler
.align 2
common_trap_handler:
    csrr   t0, mcause
    la     t1, saved_mcause
    sw     t0, 0(t1)

    csrr   t0, mepc
    la     t1, saved_mepc
    sw     t0, 0(t1)

    csrr   t0, mip
    la     t1, saved_mip
    sw     t0, 0(t1)

    // Acknowledge the timer interrupt by clearing mie.MTIE so we
    // don't re-fire (same pattern as timer_isr.S).
    li     t0, MIE_MTIE_MASK
    csrc   mie, t0

    la     t0, saw_trap
    li     t1, 1
    sw     t1, 0(t0)

    mret


.section .data
.globl wfi_armed
.globl saw_trap
.globl saved_mcause
.globl saved_mepc
.globl saved_mip
.globl done_marker
.align 2
wfi_armed:       .word 0
saw_trap:        .word 0
saved_mcause:    .word 0
saved_mepc:      .word 0
saved_mip:       .word 0
done_marker:     .word 0
