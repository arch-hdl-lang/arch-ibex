// PMP exec-fault bring-up program (D2-followup integration coverage).
//
// What it does
// ------------
//   1. Stack up; install trap_entry as mtvec.
//   2. Configure PMP region 0 as NA4-locked covering exactly the
//      4-byte word containing `forbidden_func`, with X=W=R=0. The
//      L bit makes the rule apply in M-mode too (default Ibex is
//      M-mode, MML=0).
//   3. Jump to `forbidden_func` (jal x0, …) — instruction fetch
//      from a PMP-denied region MUST trap with mcause=1
//      (instruction access fault).
//   4. Trap handler stashes mcause / mepc / mtval, then advances
//      mepc to `recovery_point` so mret resumes at known PC.
//   5. recovery_point writes done_marker = 0xFEEDFACE; halts.
//
// Why it exists: D2 flipped PMPEnable=1 but our existing 5 ISR
// programs don't exercise any PMP-violation path. A single
// PMP-denied fetch is the smallest meaningful test that wires
// IbexPmp + IF stage + cs_registers + controller end-to-end under
// the flipped pinning.

#include "common.h"

// PMP cfg byte (RISC-V Privileged Spec Vol II Table 3.10):
//   {L[7], 00[6:5], A[4:3], X[2], W[1], R[0]}
// A field: 0=OFF, 1=TOR, 2=NA4, 3=NAPOT.
// L=1, A=2 (NA4), X=W=R=0 → 0x90. Locked + zero perms = denied
// on every access type from every privilege level.
//
// (An earlier draft used 0x88 with the comment "A=01 (NA4)".
// 0x88 is actually TOR mode, which under prev=0 covers the
// entire [0, forbidden_func) range — including the trap vector
// and _start. Result: every fetch faults after the csrw flush
// → infinite trap loop at vector base. 0x90 gives real
// NA4-only-this-word coverage.)
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

    // pmpaddr0 = forbidden_func >> 2 (NA4 covers exactly that word).
    la     t0, forbidden_func
    srli   t0, t0, 2
    csrw   pmpaddr0, t0

    // pmpcfg0 byte 0 = locked NA4 with no permissions.
    li     t0, PMP_CFG_NA4_DENY_LOCKED
    csrw   pmpcfg0, t0

    // Trigger the violation. `jal x0, …` because we don't expect
    // to return — the fetch from forbidden_func MUST fault before
    // any instruction there executes. Handler resumes us at
    // `recovery_point` via mepc rewrite.
    jal    x0, forbidden_func

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


// ── forbidden region (1 word, PMP-locked) ──────────────────────────
.align 2
.globl forbidden_func
forbidden_func:
    nop                          // never executed
    j      halt                  // safety net (should be unreachable)


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


// ── data: cocotb-readable slots ────────────────────────────────────
.section .data
.globl saved_mcause
.globl saved_mepc
.globl saved_mtval
.globl done_marker
.align 2
saved_mcause:    .word 0
saved_mepc:      .word 0
saved_mtval:     .word 0
done_marker:     .word 0
