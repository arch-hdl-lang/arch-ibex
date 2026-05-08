// CPU benchmark with the icache enabled at runtime.
//
// `_start`:
//   1. Sets mtvec to a halt-on-trap handler.
//   2. Enables the icache by writing `cpuctrlsts.icache_enable = 1`
//      (CSR 0x7C0 bit 0).
//   3. Spins for ~512 cycles to absorb the cold-boot inval walk
//      (256-cycle walk + slack).
//   4. Warm-up: runs `bench_kernel` ONCE so the cache holds its
//      lines on the measured runs.
//   5. Reads `mcycle`, runs `bench_kernel` 8 times, reads `mcycle`
//      again, stores the delta to `result_cycles`.
//   6. Writes `done_marker = 0xFEEDFACE` and halts.
//
// `bench_kernel` is a tight 200-iteration counted loop using
// add/mul/addi/bnez — RV32IM mix, predictable branches.

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

    // Enable the icache (cpuctrlsts CSR 0x7C0, bit 0).
    csrsi  0x7c0, 1

    // Soak the cold-boot inval walk + cpuctrlsts propagation.
    li     t0, 512
1:  addi   t0, t0, -1
    bnez   t0, 1b

    // Warm-up: prime the icache with the kernel.
    call   bench_kernel

    // Start measurement.
    csrr   t6, mcycle

    // Run kernel N=8 times.
    li     t5, 8
2:  call   bench_kernel
    addi   t5, t5, -1
    bnez   t5, 2b

    // End measurement.
    csrr   t4, mcycle
    sub    t3, t4, t6

    // Stash the delta in result_cycles.
    la     t0, result_cycles
    sw     t3, 0(t0)

    // Hand off to the cocotb harness.
    la     t0, done_marker
    li     t1, 0xFEEDFACE
    sw     t1, 0(t0)

3:  j 3b

// ── Benchmark kernel ───────────────────────────────────────────────
.align 4
bench_kernel:
    li     t0, 200            // iteration counter
    li     t1, 0              // accumulator
    li     t2, 7              // step
4:  add    t1, t1, t2
    mul    t1, t1, t2
    addi   t2, t2, 1
    addi   t0, t0, -1
    bnez   t0, 4b
    ret

// ── Trap handler — any unexpected trap halts. ──────────────────────
.globl common_trap_handler
common_trap_handler:
9:  j 9b

// ── Data section ───────────────────────────────────────────────────
.section .data
.globl saw_trap
.globl done_marker
.globl result_cycles
.align 2
saw_trap:        .word 0
done_marker:     .word 0
result_cycles:   .word 0
