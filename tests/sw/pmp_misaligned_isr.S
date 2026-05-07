// PMP misaligned-fetch fault bring-up program (D2-followup integration
// coverage, gap B of the planned A/B/C set).
//
// What it does
// ------------
// Builds a 32-bit instruction whose PC is misaligned by 2 (PC[1]=1)
// such that its first half lives in a PMP-allowed word and its
// second half lives in a PMP-denied word. Executing through this
// instruction must fault on fetch with cause=1, mepc pointing at
// the straddle instruction's PC, and mtval pointing at the +2
// (faulting) fetch address.
//
//   1. Stack up; install trap_entry as mtvec.
//   2. Configure PMP region 0 NA4-locked covering exactly the word
//      at `forbidden_word`, with X=W=R=0.
//   3. Jump to `pre_straddle`. After a 16-bit `c.nop`, the next 32-bit
//      instruction `straddle_insn` lands at PC = `pre_straddle + 2`
//      (misaligned). Its bytes [PC..PC+3] cross the 4-byte boundary
//      at PC+2 (= `forbidden_word`).
//   4. The IF-stage fetch chain:
//        pmp_req_addr_in[0] = PC                        → allowed
//        pmp_req_addr_in[1] = PC + 2 = forbidden_word   → DENIED
//        pmp_err_if_i       = 0
//        pmp_err_if_plus2_i = 1
//        if_instr_pmp_err   = 0 | (PC[1] & ~compressed & pmp_err_if_plus2)
//                           = 1
//      Trap with cause=1, mtval = PC + 2 (per controller's StFlush
//      `csr_mtval_o = instr_fetch_err_plus2_i ? (pc_id_i + 32'd2) :
//      pc_id_i;`).
//   5. Trap handler stashes mcause/mepc/mtval, reroutes mepc to
//      `recovery_point`, mret. recovery_point writes done_marker.
//
// Why it exists
// -------------
// This is the only way to exercise IF-stage `pmp_err_if_plus2_i` and
// the controller's `instr_fetch_err_plus2 → mtval = pc + 2` formula
// (see `IbexController.arch:485` PR #24). pmp_exec_isr (gap A) only
// hits aligned fetches (pmp_err_if_i path); pmp_load_isr (gap C) is
// LSU-side. This program is the misaligned-32-bit-insn fault corner.
//
// Toolchain note
// --------------
// Built with `rv32imc_zicsr` (per-target MARCH override in
// tests/sw/Makefile) so the assembler accepts `c.nop`. The 32-bit
// straddle instruction is hand-encoded as `.4byte 0x00000013`
// (= `addi x0, x0, 0`, a canonical 32-bit nop) to guarantee the
// assembler doesn't compress it to `c.nop` when it falls within a
// short-branch range. Same idea for the straddle's "second half"
// word — pad with explicit `.short 0x0001` (c.nop encoding) so the
// faulting word is a clean 4-byte chunk.

#include "common.h"

// PMP cfg byte: L=1, A=2 (NA4), X=W=R=0 → 0x90.  See pmp_exec_isr.S
// for the TOR-vs-NA4 encoding gotcha.
#define PMP_CFG_NA4_DENY_LOCKED   0x90

// ── trap vector table + reset trampoline (shared layout) ────────────
// Force `norvc` for the vector table so each `j` is 4 bytes; otherwise
// rv32imc lets the assembler mix c.j (2 bytes) and jal (4 bytes) and
// the resulting 32-entry table no longer fits the 128-byte hole the
// linker reserves between 0x00100000 and the reset trampoline at
// 0x00100080.
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

// ── main ───────────────────────────────────────────────────────────
.section .text, "ax"
.globl _start
.balign 4
_start:
    la     sp, _stack_top

    // mtvec ← trap_entry. Ibex forces vectored mode; trap_entry IS
    // the table (per A/C programs).
    la     t0, trap_entry
    csrw   mtvec, t0

    // pmpaddr0 = forbidden_word >> 2 (NA4 covers exactly one 4-byte
    // word). forbidden_word is also straddle_insn+2, so this is the
    // boundary the straddle insn crosses.
    la     t0, forbidden_word
    srli   t0, t0, 2
    csrw   pmpaddr0, t0

    // pmpcfg0 byte 0 = locked NA4 with no permissions.
    li     t0, PMP_CFG_NA4_DENY_LOCKED
    csrw   pmpcfg0, t0

    // JALR directly to `straddle_insn` (= pre_straddle + 2, a 2-byte-
    // aligned address). This makes the icache's Fill-Buffer start
    // misaligned: `out_fb_addr[1] = 1` is preserved through
    // `addr_out_q`, so the icache delivers PC = straddle_insn on the
    // first cycle after the branch.
    //
    // We deliberately AVOID the simpler "fall through a c.nop into
    // straddle_insn" pattern because our IbexIcache outputs in 4-byte
    // beats: a c.nop at a word's lower half advances out_beat_idx by
    // a full beat, skipping the upper-half (misaligned) PC. That's a
    // latent bug — see feedback memory — and works around it here by
    // branching directly to the misaligned target.
    la     t0, straddle_insn
    jr     t0


// ── straddle layout ────────────────────────────────────────────────
// `pre_straddle` is 4-byte aligned. After 2 bytes of `c.nop`, PC is
// at `pre_straddle + 2` (misaligned). The 32-bit `addi x0, x0, 0` at
// that PC spans the 4-byte boundary at `pre_straddle + 4`, which
// IS `forbidden_word` (and is exactly the address PMP region 0 will
// cover).
//
// The 32-bit insn's encoding 0x00000013 is split into two halfwords
// so we can place the `forbidden_word` label at the exact byte the
// fault must report (PC+2 of the straddle fetch). Little-endian halves:
//   lower (bytes pre_straddle+2..+3) = 0x0013
//   upper (bytes pre_straddle+4..+5) = 0x0000     ← second-half fetch
.balign 4
.globl pre_straddle
pre_straddle:
    .short 0x0001                 // c.nop @ +0..+1: pushes PC to misaligned +2

.globl straddle_insn
straddle_insn:
    .short 0x0013                 // lower half of 32-bit nop @ +2..+3 (PMP-allowed word)

.globl forbidden_word
forbidden_word:
    .short 0x0000                 // upper half of 32-bit nop @ +4..+5 (PMP-DENIED word)
    .short 0x0001                 // pad to fill the rest of the protected word
                                   // (bytes +6..+7); content irrelevant — fetch fault
                                   // fires on +4..+5 before any decode.

// Past the forbidden region. Reachable only via the trap handler's
// `mepc <- recovery_point` rewrite + mret.
.balign 4
.globl recovery_point
recovery_point:
    la     t0, done_marker
    li     t1, 0xFEEDFACE
    sw     t1, 0(t0)

halt:
    j      halt


// ── trap handler ───────────────────────────────────────────────────
.globl common_trap_handler
.balign 4
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
.balign 4
saved_mcause:    .word 0
saved_mepc:      .word 0
saved_mtval:     .word 0
done_marker:     .word 0
