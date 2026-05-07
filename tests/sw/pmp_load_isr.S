// PMP load-fault bring-up program (D2-followup integration coverage,
// gap C of the planned A/B/C set; A landed as pmp_exec_isr).
//
// What it does
// ------------
//   1. Stack up; install trap_entry as mtvec.
//   2. Configure PMP region 0 as NA4-locked covering exactly the
//      4-byte word at `forbidden_data`, with X=W=R=0. The L bit
//      makes the rule apply in M-mode too (default Ibex is M-mode,
//      MML=0).
//   3. Execute `lw t1, 0(t0)` against `forbidden_data` — a data load
//      from a PMP-denied region MUST trap with mcause=5
//      (load access fault). Unlike A's exec-fault, the faulting
//      instruction is the lw itself, so mepc points at the lw's PC
//      and mtval carries the load address.
//   4. Trap handler stashes mcause / mepc / mtval, then advances
//      mepc to `recovery_point` so mret resumes at known PC.
//   5. recovery_point writes done_marker = 0xFEEDFACE; halts.
//
// Why it exists: pmp_exec_isr (gap A) covered the IF-stage PMP path
// (channels PMP_I=0 / PMP_I2=1). The data-side path (channel PMP_D=2)
// goes through a different chain — LSU → IbexPmp → cs_registers — and
// has no end-to-end coverage today. This is the smallest meaningful
// LSU-side load-violation test.

#include "common.h"

// PMP cfg byte (RISC-V Privileged Spec Vol II Table 3.10):
//   {L[7], 00[6:5], A[4:3], X[2], W[1], R[0]}
// A field: 0=OFF, 1=TOR, 2=NA4, 3=NAPOT.
// L=1, A=2 (NA4), X=W=R=0 → 0x90.  See pmp_exec_isr.S for the
// TOR-vs-NA4-encoding gotcha that bricks the trap vector.
#define PMP_CFG_NA4_DENY_LOCKED   0x90

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

    // mtvec — Ibex forces vectored mode; trap_entry IS the table.
    la     t0, trap_entry
    csrw   mtvec, t0

    // pmpaddr0 = forbidden_data >> 2 (NA4 covers exactly that word).
    la     t0, forbidden_data
    srli   t0, t0, 2
    csrw   pmpaddr0, t0

    // pmpcfg0 byte 0 = locked NA4 with no permissions.
    li     t0, PMP_CFG_NA4_DENY_LOCKED
    csrw   pmpcfg0, t0

    // Trigger the violation. `lw` against `forbidden_data` — the
    // LSU's data-side PMP check (channel PMP_D=2) MUST deny this and
    // the controller MUST raise a load-access-fault before t1 is
    // architecturally written. `lw_insn:` label lets the test locate
    // the faulting PC.
    la     t0, forbidden_data
.globl lw_insn
.align 2
lw_insn:
    lw     t1, 0(t0)

    // The handler steers mret to `recovery_point` so we land here
    // post-trap.
.globl recovery_point
.align 2
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
    // mcause / mepc / mtval → cocotb-readable data slots.
    csrr   t0, mcause
    la     t1, saved_mcause
    sw     t0, 0(t1)

    csrr   t0, mepc
    la     t1, saved_mepc
    sw     t0, 0(t1)

    csrr   t0, mtval
    la     t1, saved_mtval
    sw     t0, 0(t1)

    // Steer mret to recovery_point so the program continues
    // deterministically regardless of where exactly the trap landed.
    la     t0, recovery_point
    csrw   mepc, t0

    mret


// ── data: cocotb-readable slots + the PMP-locked target word ───────
.section .data
.globl saved_mcause
.globl saved_mepc
.globl saved_mtval
.globl done_marker
.globl forbidden_data
.align 2
saved_mcause:    .word 0
saved_mepc:      .word 0
saved_mtval:     .word 0
done_marker:     .word 0
// The actual word the lw is targeting. Value is irrelevant — the
// load must fault before this byte is read. Placed in .data (not
// .text) so the IF-stage PMP can't fault on prefetch of this
// address; only the LSU sees it.
.align 2
forbidden_data:  .word 0xDEADBEEF
