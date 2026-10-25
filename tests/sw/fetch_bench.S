// Fetch-path cycle-count probes with the icache enabled (warm cache).
//
// Each kernel is a counted loop whose body repeats one fetch pattern 16
// times; it runs once to warm the cache, then 10 iterations are timed with
// mcycle. Encodings are explicit (.option rvc / norvc), so the layout does
// not depend on the assembler's compression choices. Results go to
// `results[]` in kernel order; `done_marker = 0xFEEDFACE` hands off to
// tests/cocotb_tests/test_fetch_bench.py, which pins the cycle counts.
//
//   0 k_seq    aligned 32-bit straight-line code (reference: no branches)
//   1 k_fwd    short forward taken branch (skips one instruction) into the
//              lines the prefetcher has already requested, then 8
//              sequential instructions
//   2 k_jt0    jump to word 0 of a 64-bit line, run into the next line
//   3 k_jt4    jump to word 1 of a 64-bit line, run into the next line
//   4 k_jmis6  jump to a 32-bit instruction at line offset 6 (it spans two
//              64-bit lines)

#include "common.h"

#define ITERS 10

// Vector table + reset trampoline forced to norvc (each `j` 4 bytes) so
// the 32-entry table fits the 128 bytes below the reset vector; same idiom
// as pmp_misaligned_isr.S.
.section .text.trap, "ax"
.option push
.option norvc
.globl trap_entry
.align 2
trap_entry:
#include "vector_table.inc"
.option pop

.section .text.reset, "ax"
.option push
.option norvc
.globl _reset
.align 2
_reset:
    j   _start
.option pop

.section .text, "ax"
.globl _start
.align 2
_start:
    la     sp, _stack_top
    la     t0, trap_entry
    csrw   mtvec, t0
    csrsi  0x7c0, 1              // cpuctrlsts.icache_enable = 1
    li     t0, 512               // absorb the cold-boot inval walk
1:  addi   t0, t0, -1
    bnez   t0, 1b

    la     s0, results
    la     a1, k_seq
    jal    ra, measure
    la     a1, k_fwd
    jal    ra, measure
    la     a1, k_jt0
    jal    ra, measure
    la     a1, k_jt4
    jal    ra, measure
    la     a1, k_jmis6
    jal    ra, measure

    la     t0, done_marker
    li     t1, 0xFEEDFACE
    sw     t1, 0(t0)
3:  j 3b

// measure(a1 = kernel): warm once, time ITERS iterations, store at 0(s0),
// advance s0.
measure:
    mv     s2, ra
    li     a0, 1
    jalr   ra, 0(a1)
    li     a0, ITERS
    csrr   s1, mcycle
    jalr   ra, 0(a1)
    csrr   t0, mcycle
    sub    t0, t0, s1
    sw     t0, 0(s0)
    addi   s0, s0, 4
    jr     s2

.option push
.option norvc

.balign 64
k_seq:
1:
    .rept 64
    addi   t1, t1, 1
    .endr
    addi   a0, a0, -1
    bnez   a0, 1b
    ret

.balign 64
k_fwd:
1:
    .rept 16
    j      2f
    nop
2:  addi   t1, t1, 1
    addi   t2, t2, 1
    addi   t1, t1, 1
    addi   t2, t2, 1
    addi   t1, t1, 1
    addi   t2, t2, 1
    addi   t1, t1, 1
    addi   t2, t2, 1
    .endr
    addi   a0, a0, -1
    bnez   a0, 1b
    ret

.balign 64
k_jt0:
1:
    .rept 16
    j      2f
    .balign 16
2:  addi   t1, t1, 1
    addi   t2, t2, 1
    addi   t1, t1, 1
    .endr
    addi   a0, a0, -1
    bnez   a0, 1b
    ret

.balign 64
k_jt4:
1:
    .rept 16
    j      2f
    .balign 16
    nop
2:  addi   t1, t1, 1
    addi   t2, t2, 1
    addi   t1, t1, 1
    .endr
    addi   a0, a0, -1
    bnez   a0, 1b
    ret

.balign 64
k_jmis6:
1:
    .rept 16
    j      2f
    .balign 16
    .option rvc
    c.nop
    c.nop
    c.nop
    .option norvc
2:  addi   t1, t1, 1
    .endr
    addi   a0, a0, -1
    bnez   a0, 1b
    ret

.option pop

// ── Trap handler — any unexpected trap halts. ──────────────────────
.globl common_trap_handler
common_trap_handler:
    la     t0, saw_trap
    li     t1, 1
    sw     t1, 0(t0)
9:  j 9b

// ── Data section ───────────────────────────────────────────────────
.section .data
.globl saw_trap
.globl done_marker
.globl results
.align 2
saw_trap:        .word 0
done_marker:     .word 0
results:         .word 0, 0, 0, 0, 0, 0, 0, 0
