// Minimum trap-delivery sanity check (D3-followup probe).
//
// Triggers a single `ecall` from M-mode and asserts the trap handler
// receives cause=11 (Environment call from M-mode). Confirms the
// trap-delivery path (mtvec / vector dispatch / mret / mepc) works
// end-to-end on our swap before piling on PMP / misaligned-PC scenarios.
//
// Existence rationale: pmp_exec_isr WIP saw mcause=0 (the controller's
// default ExcCauseInsnAddrMisa = 6'h00) which is also the value left
// when no real exception priority asserts. ecall is the simplest
// possible synchronous exception with no PMP / fetch-side complications.

#include "common.h"

// ── trap vector table + reset trampoline (shared layout) ────────────
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

// ── main ───────────────────────────────────────────────────────────
.section .text, "ax"
.globl _start
.align 2
_start:
    la     sp, _stack_top

    la     t0, trap_entry
    csrw   mtvec, t0

    // Trigger M-mode ecall — synchronous exception, cause = 11.
.globl ecall_site
ecall_site:
    ecall

    // Trap handler resumes us here via mepc rewrite.
.globl recovery_point
recovery_point:
    la     t0, done_marker
    li     t1, 0xFEEDFACE
    sw     t1, 0(t0)

halt:
    j      halt


// ── trap handler ───────────────────────────────────────────────────
.globl common_trap_handler
.align 2
common_trap_handler:
    csrr   t0, mcause
    la     t1, saved_mcause
    sw     t0, 0(t1)

    csrr   t0, mepc
    la     t1, saved_mepc
    sw     t0, 0(t1)

    // Steer mret to recovery_point so we land at a known address
    // regardless of where the trap fired (mepc on ecall = ecall_site,
    // and mret without rewriting mepc would re-execute ecall ⇒
    // infinite loop).
    la     t0, recovery_point
    csrw   mepc, t0

    mret


// ── data: cocotb-readable slots ────────────────────────────────────
.section .data
.globl saved_mcause
.globl saved_mepc
.globl done_marker
.align 2
saved_mcause:    .word 0
saved_mepc:      .word 0
done_marker:     .word 0
