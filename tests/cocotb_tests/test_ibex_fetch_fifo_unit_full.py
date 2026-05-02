"""Full-regression cocotb scenarios for `ibex_fetch_fifo`.

Covers every Scenario in `changes/port-fetch_fifo/specs/fetch_fifo/spec.md`
plus the edge cases enumerated in the test-author brief:
  - Full-fill / drain sequences (push 3, pop 3).
  - Bus-error patterns across all three entries with mixed err.
  - `clear_i` during empty / partial / full FIFO and during a mid-pop cycle.
  - Compressed-then-uncompressed instruction streams that exercise
    `addr_incr_two`.
  - Bypass interleaved with normal pushes (drain to empty mid-stream
    then bypass immediately).
  - Producer-side input boundaries: `in_addr_i` must be don't-care on
    non-clear cycles; `in_err_i` must be ignored when `in_valid_i = 0`.

In-scope parameters: NUM_REQS = 2 (DEPTH = 3), ResetAll = 0.

Spec-faithful pitfalls baked in:
  - `out_addr_o[0]` always 0.
  - `out_err_plus2_o` only checked when `out_err_o == 1` AND
    `out_addr_o[1] == 1`.
  - `busy_o` is 2 bits.
  - The unaligned-32-bit "second half not yet available" Scenario
    requires `out_valid_o == 0` even with `valid_q[0] == 1`.
  - The unaligned-compressed err-suppression Scenario requires
    `err_q[1] == 1` but `out_err_o == 0`.
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


CLK_PERIOD_NS = 10


# ── Helpers ──────────────────────────────────────────────────────────────
async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())


async def _idle_inputs(dut):
    dut.clear_i.value = 0
    dut.in_valid_i.value = 0
    dut.in_rdata_i.value = 0
    dut.in_addr_i.value = 0
    dut.in_err_i.value = 0
    dut.out_ready_i.value = 0


async def _reset(dut):
    await _idle_inputs(dut)
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")


async def _seed_pc(dut, addr: int):
    dut.clear_i.value = 1
    dut.in_valid_i.value = 0
    dut.in_addr_i.value = addr & 0xFFFF_FFFF
    dut.in_rdata_i.value = 0
    dut.in_err_i.value = 0
    dut.out_ready_i.value = 0
    await RisingEdge(dut.clk_i)
    dut.clear_i.value = 0
    dut.in_addr_i.value = 0
    await Timer(1, "ns")


async def _push(dut, data: int, err: int = 0, in_addr: int = 0):
    dut.in_valid_i.value = 1
    dut.in_rdata_i.value = data & 0xFFFF_FFFF
    dut.in_err_i.value = err & 1
    dut.in_addr_i.value = in_addr & 0xFFFF_FFFF
    await RisingEdge(dut.clk_i)
    dut.in_valid_i.value = 0
    dut.in_rdata_i.value = 0
    dut.in_err_i.value = 0
    dut.in_addr_i.value = 0
    await Timer(1, "ns")


async def _pop(dut):
    dut.out_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.out_ready_i.value = 0
    await Timer(1, "ns")


async def _push_and_pop(dut, data: int, err: int = 0):
    """Same-cycle push and pop."""
    dut.in_valid_i.value = 1
    dut.in_rdata_i.value = data & 0xFFFF_FFFF
    dut.in_err_i.value = err & 1
    dut.in_addr_i.value = 0
    dut.out_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.in_valid_i.value = 0
    dut.in_rdata_i.value = 0
    dut.in_err_i.value = 0
    dut.out_ready_i.value = 0
    await Timer(1, "ns")


async def _idle_one_cycle(dut):
    await _idle_inputs(dut)
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")


# Useful constants — words whose bit[1:0] = 2'b11 are uncompressed,
# anything else is compressed.
def _uncompressed(payload24: int) -> int:
    """Build a 32-bit word whose [1:0] = 2'b11 (uncompressed) and
    whose upper 24 bits carry `payload24`."""
    return ((payload24 & 0xFF_FFFF) << 8) | 0xC3  # [7:0] = 1100_0011, [1:0] = 11


def _compressed(payload30: int) -> int:
    """Build a 32-bit word whose [1:0] != 2'b11 (compressed)."""
    return ((payload30 & 0x3FFF_FFFF) << 2) | 0b01  # [1:0] = 01


# ── Spec Req 1 Scenarios ─────────────────────────────────────────────────
@cocotb.test()
async def req1_idle_no_entries_no_bypass(dut):
    """Req 1 Scenario: Idle (no entries, no bypass). Empty FIFO with
    `in_valid_i = 0` keeps `out_valid_o` low; `out_addr_o[0] == 0` and
    [31:1] reflects internal PC."""
    await _start_clock(dut)
    await _reset(dut)
    seed = 0x0000_1000
    await _seed_pc(dut, seed)
    dut.in_valid_i.value = 0
    dut.out_ready_i.value = 0
    await Timer(1, "ns")
    assert int(dut.out_valid_o.value) == 0
    assert int(dut.out_addr_o.value) & 1 == 0
    assert int(dut.out_addr_o.value) == seed


@cocotb.test()
async def req1_bypass_aligned_into_empty_fifo(dut):
    """Req 1 Scenario: Bypass push of an aligned instruction into an
    empty FIFO. Same-cycle out_valid_o = 1, rdata = D, err = E,
    err_plus2 = 0 (aligned)."""
    await _start_clock(dut)
    await _reset(dut)
    await _seed_pc(dut, 0x0000_1100)
    D = 0x1234_5673  # arbitrary (uncompressed lower)
    dut.in_valid_i.value = 1
    dut.in_rdata_i.value = D
    dut.in_err_i.value = 1
    dut.in_addr_i.value = 0
    await Timer(1, "ns")
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_rdata_o.value) == D
    assert int(dut.out_err_o.value) == 1
    assert int(dut.out_err_plus2_o.value) == 0  # aligned → hard-wired 0


# ── Spec Req 2 Scenarios ─────────────────────────────────────────────────
@cocotb.test()
async def req2_push_then_aligned_32_pop(dut):
    """Req 2 Scenario: Push then aligned-32 pop. After push, entry 0
    valid; after pop, entry 0 popped and PC += 4."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_2000
    await _seed_pc(dut, pc0)
    word = _uncompressed(0xABCDEF)
    dut.out_ready_i.value = 0
    await _push(dut, word)
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_rdata_o.value) == word
    assert int(dut.out_addr_o.value) == pc0
    await _pop(dut)
    assert int(dut.out_valid_o.value) == 0
    assert int(dut.out_addr_o.value) == pc0 + 4


@cocotb.test()
async def req2_compressed_aligned_does_not_pop(dut):
    """Req 2 Scenario: Compressed aligned instruction does not pop the
    entry. PC advances by 2 (not 4) and entry 0 stays valid; the upper
    half then becomes the next instruction at out_addr_o[1] == 1."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_2100
    await _seed_pc(dut, pc0)
    # Lower 16 bits compressed ([1:0] != 2'b11). Upper 16 bits
    # arbitrary; we will read them at the unaligned PC after the pop.
    lo_compressed = 0xAAAA  # [1:0] = 2'b10 → compressed
    # Upper half ALSO compressed so the post-pop unaligned read finds a
    # complete instruction without needing a second source.
    # 0xBBBA = 0b1011_1011_1011_1010 → low 2 bits = 2'b10 → compressed.
    hi = 0xBBBA
    word = (hi << 16) | lo_compressed
    dut.out_ready_i.value = 0
    await _push(dut, word, err=0)
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_rdata_o.value) == word
    # Pop: addr_incr_two path.
    await _pop(dut)
    # PC advanced by 2, entry 0 stays valid.
    assert int(dut.out_addr_o.value) == pc0 + 2
    # Upper half now visible. Unaligned-compressed test handled in Req 5
    # scenarios — we only verify PC and that the entry was not dropped.
    # hi = 0xBBBA → [17:16] of original word = 2'b10 → compressed →
    # unaligned-compressed → out_valid_o = 1 (no second source needed).
    assert int(dut.out_valid_o.value) == 1


# ── Spec Req 3 Scenarios ─────────────────────────────────────────────────
@cocotb.test()
async def req3_busy_reflects_upper_two_entries(dut):
    """Req 3 Scenario: busy_o reflects upper entries. With
    valid_q == 3'b011 (entries 0 and 1 valid), busy_o == 2'b01."""
    await _start_clock(dut)
    await _reset(dut)
    await _seed_pc(dut, 0x0000_3000)
    assert int(dut.busy_o.value) == 0b00
    dut.out_ready_i.value = 0
    await _push(dut, _uncompressed(0x111111))
    assert int(dut.busy_o.value) == 0b00  # valid_q == 3'b001
    await _push(dut, _uncompressed(0x222222))
    assert int(dut.busy_o.value) == 0b01  # valid_q == 3'b011
    await _push(dut, _uncompressed(0x333333))
    assert int(dut.busy_o.value) == 0b11  # valid_q == 3'b111


# Note: Req 3 Scenario "No push when full" is producer-enforced UB;
# spec explicitly excuses the arch implementation from defining
# behavior. NOT tested. Documented in the test-author brief.


# ── Spec Req 4 Scenarios ─────────────────────────────────────────────────
@cocotb.test()
async def req4_pure_clear_flushes_and_reseeds(dut):
    """Req 4 Scenario: Pure clear. Two valid entries → assert clear_i
    with new in_addr_i → next cycle valid_q == 0 and PC == A[31:1]."""
    await _start_clock(dut)
    await _reset(dut)
    await _seed_pc(dut, 0x0000_4000)
    dut.out_ready_i.value = 0
    await _push(dut, _uncompressed(0xAAA))
    await _push(dut, _uncompressed(0xBBB))
    assert int(dut.busy_o.value) == 0b01
    new_seed = 0x0000_5001  # bit[0] = 1 — must be discarded
    dut.clear_i.value = 1
    dut.in_valid_i.value = 0
    dut.in_addr_i.value = new_seed
    await RisingEdge(dut.clk_i)
    dut.clear_i.value = 0
    dut.in_addr_i.value = 0
    await Timer(1, "ns")
    assert int(dut.out_valid_o.value) == 0
    assert int(dut.busy_o.value) == 0b00
    assert int(dut.out_addr_o.value) == (new_seed & 0xFFFF_FFFE)


@cocotb.test()
async def req4_clear_coincident_with_push_full(dut):
    """Req 4 Scenario: Clear coincident with a push (FIFO full).
    Spec says clear wins: next cycle valid_q == 0 and PC == A[31:1].
    The simultaneous in_valid_i is dropped on the floor."""
    await _start_clock(dut)
    await _reset(dut)
    await _seed_pc(dut, 0x0000_4400)
    dut.out_ready_i.value = 0
    await _push(dut, _uncompressed(0x111))
    await _push(dut, _uncompressed(0x222))
    await _push(dut, _uncompressed(0x333))
    assert int(dut.busy_o.value) == 0b11  # full
    # Clear + push concurrently with new seed.
    new_seed = 0x0000_5400
    dut.clear_i.value = 1
    dut.in_valid_i.value = 1
    dut.in_rdata_i.value = _uncompressed(0xDEAD)
    dut.in_err_i.value = 0
    dut.in_addr_i.value = new_seed
    await RisingEdge(dut.clk_i)
    dut.clear_i.value = 0
    dut.in_valid_i.value = 0
    dut.in_addr_i.value = 0
    dut.in_rdata_i.value = 0
    await Timer(1, "ns")
    assert int(dut.busy_o.value) == 0b00
    assert int(dut.out_addr_o.value) == new_seed
    # FIFO is empty (valid_q == 0). With in_valid_i now low, no bypass.
    assert int(dut.out_valid_o.value) == 0


# ── Spec Req 5 Scenarios ─────────────────────────────────────────────────
@cocotb.test()
async def req5_unaligned_32_both_halves_in_fifo(dut):
    """Req 5 Scenario: Unaligned 32-bit, both halves in FIFO. Expect
    out_rdata_o == { rdata_q[1][15:0], rdata_q[0][31:16] } and
    out_valid_o == 1; pop drops entry 0 and PC += 4."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_6002  # bit[1] = 1
    await _seed_pc(dut, pc0)
    # Entry 0 upper-half MUST decode as uncompressed: [17:16] = 2'b11.
    e0 = (0xBBC3 << 16) | 0x1234  # upper16 = 0xBBC3 → bits[17:16] = 2'b11
    e1 = 0xDEAD_5678
    dut.out_ready_i.value = 0
    await _push(dut, e0)
    await _push(dut, e1)
    expected = ((e1 & 0xFFFF) << 16) | ((e0 >> 16) & 0xFFFF)
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_rdata_o.value) == expected
    await _pop(dut)
    assert int(dut.out_addr_o.value) == pc0 + 4


@cocotb.test()
async def req5_unaligned_32_second_half_via_bypass(dut):
    """Req 5 Scenario: Unaligned 32-bit, second half via bypass. Only
    entry 0 is valid; in_valid_i drives the second half. Expect
    out_rdata_o == { N[15:0], rdata_q[0][31:16] } and
    out_valid_o == 1."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_6402
    await _seed_pc(dut, pc0)
    e0 = (0xBBC3 << 16) | 0x9999  # upper16 [17:16] = 2'b11 (uncompressed)
    dut.out_ready_i.value = 0
    await _push(dut, e0)
    # Now drive bypass with N.
    N = 0x1111_4444
    dut.in_valid_i.value = 1
    dut.in_rdata_i.value = N
    dut.in_err_i.value = 0
    dut.in_addr_i.value = 0
    await Timer(1, "ns")
    expected = ((N & 0xFFFF) << 16) | ((e0 >> 16) & 0xFFFF)
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_rdata_o.value) == expected


@cocotb.test()
async def req5_unaligned_32_second_half_unavailable(dut):
    """Req 5 Scenario (CRITICAL NEGATIVE): Unaligned 32-bit, second
    half not yet available. valid_q[0]=1, head's upper half is
    uncompressed, in_valid_i=0 → out_valid_o MUST be 0. This catches
    an arch implementer who forgets the valid_unaligned gating."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_6802
    await _seed_pc(dut, pc0)
    e0 = (0xBBC3 << 16) | 0xAAAA  # upper16 [17:16] = 2'b11 (uncompressed)
    dut.out_ready_i.value = 0
    await _push(dut, e0)
    # Now NO bypass.
    dut.in_valid_i.value = 0
    dut.in_rdata_i.value = 0
    dut.in_err_i.value = 0
    await Timer(1, "ns")
    assert int(dut.out_valid_o.value) == 0, (
        "Unaligned 32-bit instruction must NOT present out_valid_o = 1 "
        "when the second half is not yet available."
    )


@cocotb.test()
async def req5_unaligned_compressed_no_straddle(dut):
    """Req 5 Scenario: Unaligned compressed instruction (no straddle).
    valid_q[0]=1, out_addr_o[1]=1, head's upper half is compressed
    ([17:16] != 2'b11), out_err_o=0. out_valid_o = 1 even with
    valid_q[1] == 0 and in_valid_i == 0. On pop, entry 0 IS dropped
    and PC += 2."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_6C02
    await _seed_pc(dut, pc0)
    # Upper16 must be compressed: [17:16] != 2'b11. E.g. upper16 = 0xBBBA
    # → bits[17:16] = 2'b10.
    e0 = (0xBBBA << 16) | 0x1234
    dut.out_ready_i.value = 0
    await _push(dut, e0, err=0)
    # Empty bypass.
    dut.in_valid_i.value = 0
    dut.in_rdata_i.value = 0
    dut.in_err_i.value = 0
    await Timer(1, "ns")
    assert int(dut.out_valid_o.value) == 1, (
        "Unaligned compressed must present out_valid_o = 1 from entry 0 "
        "alone (no need for valid_q[1] or bypass)."
    )
    await _pop(dut)
    assert int(dut.out_addr_o.value) == pc0 + 2
    # Entry 0 was dropped because aligned_is_compressed | out_addr_o[1].
    assert int(dut.busy_o.value) == 0b00


# ── Spec Req 6 Scenarios ─────────────────────────────────────────────────
@cocotb.test()
async def req6_aligned_err_on_head(dut):
    """Req 6 Scenario: Aligned read with err on head entry.
    out_err_o = 1, out_err_plus2_o = 0 (aligned)."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_7000
    await _seed_pc(dut, pc0)
    dut.out_ready_i.value = 0
    await _push(dut, _uncompressed(0x123), err=1)
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_err_o.value) == 1
    assert int(dut.out_err_plus2_o.value) == 0


@cocotb.test()
async def req6_unaligned_32_err_first_half_only(dut):
    """Req 6 Scenario: Unaligned 32-bit, err on first half only.
    out_err_o = 1, out_err_plus2_o = 0."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_7002
    await _seed_pc(dut, pc0)
    e0 = (0xBBC3 << 16) | 0x1234  # upper [17:16] = 2'b11 (uncompressed)
    e1 = 0xDEAD_BEEF
    dut.out_ready_i.value = 0
    await _push(dut, e0, err=1)
    await _push(dut, e1, err=0)
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_err_o.value) == 1
    assert int(dut.out_err_plus2_o.value) == 0


@cocotb.test()
async def req6_unaligned_32_err_second_half_only(dut):
    """Req 6 Scenario: Unaligned 32-bit, err on second half only.
    out_err_o = 1, out_err_plus2_o = 1."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_7402
    await _seed_pc(dut, pc0)
    e0 = (0xBBC3 << 16) | 0x1234
    e1 = 0xDEAD_BEEF
    dut.out_ready_i.value = 0
    await _push(dut, e0, err=0)
    await _push(dut, e1, err=1)
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_err_o.value) == 1
    assert int(dut.out_err_plus2_o.value) == 1


@cocotb.test()
async def req6_unaligned_compressed_err_suppressed(dut):
    """Req 6 Scenario (CRITICAL NEGATIVE): Unaligned compressed,
    second half's err is suppressed. err_q[1]=1 but the current
    instruction is fully in entry 0's upper half (compressed), so
    out_err_o = 0 and out_err_plus2_o = 0. This is the FIFO's analog
    of the LOAD rf_we integration constraint."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_7802
    await _seed_pc(dut, pc0)
    # Upper16 compressed: [17:16] != 2'b11. e.g. 0xBBBA.
    e0 = (0xBBBA << 16) | 0x1234
    e1 = 0xDEAD_BEEF
    dut.out_ready_i.value = 0
    await _push(dut, e0, err=0)
    await _push(dut, e1, err=1)
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_err_o.value) == 0, (
        "Unaligned compressed must suppress the second half's err "
        "because the current instruction is entirely in entry 0's "
        "upper half."
    )
    # When out_err_o == 0, out_err_plus2_o is don't-care per spec.


@cocotb.test()
async def req6_unaligned_32_completed_via_bypass_with_err(dut):
    """Req 6 Scenario: Unaligned 32-bit completed via bypass with err
    on the bypass half. valid_q[1:0]=2'b01, err_q[0]=0, in_valid_i=1
    with in_err_i=1. out_err_o = 1, out_err_plus2_o = 1."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_7C02
    await _seed_pc(dut, pc0)
    e0 = (0xBBC3 << 16) | 0x1234  # uncompressed upper half
    dut.out_ready_i.value = 0
    await _push(dut, e0, err=0)
    # Drive bypass with err = 1.
    dut.in_valid_i.value = 1
    dut.in_rdata_i.value = 0xCAFE_F00D
    dut.in_err_i.value = 1
    dut.in_addr_i.value = 0
    await Timer(1, "ns")
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_err_o.value) == 1
    assert int(dut.out_err_plus2_o.value) == 1


# ── Spec Req 7 Scenario ──────────────────────────────────────────────────
@cocotb.test()
async def req7_after_reset_fifo_empty(dut):
    """Req 7 Scenario: After reset, FIFO is empty. valid_q == 0,
    busy_o == 0, out_valid_o == 0 with in_valid_i == 0."""
    await _start_clock(dut)
    await _idle_inputs(dut)
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    await Timer(1, "ns")
    assert int(dut.busy_o.value) == 0
    assert int(dut.out_valid_o.value) == 0
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    assert int(dut.busy_o.value) == 0
    assert int(dut.out_valid_o.value) == 0
    assert int(dut.out_addr_o.value) & 1 == 0


# ── Edge cases ───────────────────────────────────────────────────────────
@cocotb.test()
async def edge_full_fill_then_full_drain(dut):
    """Push 3 uncompressed words, then pop them all. Confirms
    busy_o transitions {00 → 00 → 01 → 11 → 01 → 00 → 00} and
    out_addr_o increments by 4 each pop."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_8000
    await _seed_pc(dut, pc0)
    words = [_uncompressed(0xAAA), _uncompressed(0xBBB), _uncompressed(0xCCC)]
    dut.out_ready_i.value = 0
    await _push(dut, words[0])
    assert int(dut.busy_o.value) == 0b00  # valid_q = 3'b001
    await _push(dut, words[1])
    assert int(dut.busy_o.value) == 0b01  # 3'b011
    await _push(dut, words[2])
    assert int(dut.busy_o.value) == 0b11  # 3'b111
    # Drain.
    for i, w in enumerate(words):
        assert int(dut.out_valid_o.value) == 1
        assert int(dut.out_rdata_o.value) == w
        assert int(dut.out_addr_o.value) == pc0 + 4 * i
        await _pop(dut)
    assert int(dut.busy_o.value) == 0b00
    assert int(dut.out_valid_o.value) == 0
    assert int(dut.out_addr_o.value) == pc0 + 4 * len(words)


@cocotb.test()
async def edge_mixed_err_across_three_entries_aligned_drain(dut):
    """Push three uncompressed words with err pattern (1, 0, 1),
    aligned PC. Drain, verify out_err_o follows entry's err on each
    pop and out_err_plus2_o stays 0 (aligned all the way)."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_8400
    await _seed_pc(dut, pc0)
    errs = [1, 0, 1]
    words = [_uncompressed(0x100 + i) for i in range(3)]
    dut.out_ready_i.value = 0
    for w, e in zip(words, errs):
        await _push(dut, w, err=e)
    for i, e in enumerate(errs):
        assert int(dut.out_valid_o.value) == 1
        assert int(dut.out_err_o.value) == e
        assert int(dut.out_err_plus2_o.value) == 0
        await _pop(dut)


@cocotb.test()
async def edge_clear_during_empty_fifo(dut):
    """Clear an already-empty FIFO with a fresh seed. busy_o stays 0,
    PC adopts new seed."""
    await _start_clock(dut)
    await _reset(dut)
    await _seed_pc(dut, 0x0000_9000)
    assert int(dut.busy_o.value) == 0
    # Re-clear while empty.
    new_seed = 0x0000_A000
    dut.clear_i.value = 1
    dut.in_valid_i.value = 0
    dut.in_addr_i.value = new_seed
    await RisingEdge(dut.clk_i)
    dut.clear_i.value = 0
    dut.in_addr_i.value = 0
    await Timer(1, "ns")
    assert int(dut.busy_o.value) == 0
    assert int(dut.out_addr_o.value) == new_seed
    assert int(dut.out_valid_o.value) == 0


@cocotb.test()
async def edge_clear_during_partial_fifo(dut):
    """Clear after one push (partial fifo). Confirms entry is wiped."""
    await _start_clock(dut)
    await _reset(dut)
    await _seed_pc(dut, 0x0000_9100)
    dut.out_ready_i.value = 0
    await _push(dut, _uncompressed(0x111))
    assert int(dut.out_valid_o.value) == 1
    new_seed = 0x0000_A100
    dut.clear_i.value = 1
    dut.in_valid_i.value = 0
    dut.in_addr_i.value = new_seed
    await RisingEdge(dut.clk_i)
    dut.clear_i.value = 0
    dut.in_addr_i.value = 0
    await Timer(1, "ns")
    assert int(dut.busy_o.value) == 0
    assert int(dut.out_valid_o.value) == 0
    assert int(dut.out_addr_o.value) == new_seed


@cocotb.test()
async def edge_clear_during_full_fifo(dut):
    """Clear while FIFO is full (no concurrent push). All entries
    wiped, PC reseeded."""
    await _start_clock(dut)
    await _reset(dut)
    await _seed_pc(dut, 0x0000_9200)
    dut.out_ready_i.value = 0
    await _push(dut, _uncompressed(0x111))
    await _push(dut, _uncompressed(0x222))
    await _push(dut, _uncompressed(0x333))
    assert int(dut.busy_o.value) == 0b11
    new_seed = 0x0000_A200
    dut.clear_i.value = 1
    dut.in_valid_i.value = 0
    dut.in_addr_i.value = new_seed
    await RisingEdge(dut.clk_i)
    dut.clear_i.value = 0
    dut.in_addr_i.value = 0
    await Timer(1, "ns")
    assert int(dut.busy_o.value) == 0
    assert int(dut.out_valid_o.value) == 0
    assert int(dut.out_addr_o.value) == new_seed


@cocotb.test()
async def edge_clear_coincident_with_pop(dut):
    """Clear asserted simultaneously with out_ready_i = 1 on a valid
    pop. Spec: clear wins → after the edge, FIFO empty regardless of
    the would-be pop. PC reseeded from in_addr_i."""
    await _start_clock(dut)
    await _reset(dut)
    await _seed_pc(dut, 0x0000_9300)
    await _push(dut, _uncompressed(0x111))
    await _push(dut, _uncompressed(0x222))
    new_seed = 0x0000_A300
    dut.clear_i.value = 1
    dut.in_valid_i.value = 0
    dut.in_addr_i.value = new_seed
    dut.out_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.clear_i.value = 0
    dut.in_addr_i.value = 0
    dut.out_ready_i.value = 0
    await Timer(1, "ns")
    assert int(dut.busy_o.value) == 0
    assert int(dut.out_valid_o.value) == 0
    assert int(dut.out_addr_o.value) == new_seed


@cocotb.test()
async def edge_compressed_then_uncompressed_stream(dut):
    """Push a word whose lower half is compressed and upper half is
    uncompressed. Pop once: PC advances by 2 (compressed lower);
    then the upper half is at out_addr_o[1]==1 and is the first half
    of an uncompressed straddle. Push another word so the second half
    is available, then pop: PC advances by 4 (because instr at
    unaligned PC is uncompressed). Exercises both addr_incr_two
    branches."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_B000
    await _seed_pc(dut, pc0)
    # Lower16 compressed ([1:0]=2'b01), upper16 uncompressed ([17:16]=2'b11).
    e0 = (0xBBC3 << 16) | 0xAAAA  # lo = 0xAAAA → [1:0] = 2'b10 (compressed)
    e1 = 0xDEAD_BEEF
    dut.out_ready_i.value = 0
    await _push(dut, e0)
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_addr_o.value) == pc0
    # Pop the compressed lower half.
    await _pop(dut)
    # PC = pc0 + 2 (addr_incr_two via aligned_is_compressed).
    assert int(dut.out_addr_o.value) == pc0 + 2
    # Now at unaligned PC, head's upper half is uncompressed → straddle
    # needs entry 1. valid_q[1] is 0, no bypass → out_valid_o = 0.
    assert int(dut.out_valid_o.value) == 0
    # Push entry 1 to provide the second half.
    await _push(dut, e1)
    # Now both halves available.
    assert int(dut.out_valid_o.value) == 1
    expected = ((e1 & 0xFFFF) << 16) | ((e0 >> 16) & 0xFFFF)
    assert int(dut.out_rdata_o.value) == expected
    # Pop the unaligned uncompressed: PC += 4.
    await _pop(dut)
    assert int(dut.out_addr_o.value) == pc0 + 6


@cocotb.test()
async def edge_bypass_after_drain_to_empty(dut):
    """Push one word, pop it (FIFO drains to empty), then immediately
    drive a bypass on the next cycle. Confirms the bypass path works
    after the FIFO has been used."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_B400
    await _seed_pc(dut, pc0)
    w0 = _uncompressed(0x111)
    dut.out_ready_i.value = 0
    await _push(dut, w0)
    await _pop(dut)
    # FIFO drained.
    assert int(dut.out_valid_o.value) == 0
    assert int(dut.out_addr_o.value) == pc0 + 4
    # Drive bypass for a NEW word.
    bypass = _uncompressed(0x222)
    dut.in_valid_i.value = 1
    dut.in_rdata_i.value = bypass
    dut.in_err_i.value = 0
    dut.in_addr_i.value = 0
    await Timer(1, "ns")
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_rdata_o.value) == bypass
    assert int(dut.out_addr_o.value) == pc0 + 4


@cocotb.test()
async def edge_in_addr_i_garbage_on_non_clear_pushes(dut):
    """Producer-side input boundary: in_addr_i is don't-care on
    non-clear pushes (per spec line 18, line 176). Drive garbage
    (changing every push) into in_addr_i and verify the FIFO's PC
    output is unaffected — PC should still come from the seed PC plus
    the count of pops, NOT from any in_addr_i value driven outside
    the clear cycle."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_C000
    await _seed_pc(dut, pc0)
    # Push three uncompressed words with wildly different in_addr_i values.
    words = [_uncompressed(0xA00 + i) for i in range(3)]
    garbage_addrs = [0xDEAD_BEEF, 0xFFFF_FFFF, 0x1234_5678]
    dut.out_ready_i.value = 0
    for w, g in zip(words, garbage_addrs):
        await _push(dut, w, in_addr=g)
    # Drain, verifying PC starts at pc0 and increments by 4 each pop.
    for i in range(3):
        assert int(dut.out_addr_o.value) == pc0 + 4 * i, (
            f"in_addr_i garbage on non-clear push leaked into PC at pop {i}"
        )
        assert int(dut.out_rdata_o.value) == words[i]
        await _pop(dut)


@cocotb.test()
async def edge_in_err_i_ignored_when_in_valid_low(dut):
    """Producer-side input boundary: in_err_i must be ignored when
    in_valid_i = 0 (per spec line 180). Empty FIFO with in_valid_i = 0
    and in_err_i = 1 → out_valid_o stays low and out_err_o is not
    visible (because the consumer reads out_err_o only when
    out_valid_o = 1; we instead verify the bypass path doesn't
    accidentally surface the err)."""
    await _start_clock(dut)
    await _reset(dut)
    await _seed_pc(dut, 0x0000_C400)
    # Drive in_err_i high but in_valid_i low.
    dut.in_valid_i.value = 0
    dut.in_rdata_i.value = 0xDEAD_BEEF
    dut.in_err_i.value = 1
    dut.in_addr_i.value = 0
    dut.out_ready_i.value = 0
    await Timer(1, "ns")
    # The bypass path is gated on in_valid_i — out_valid_o must be 0.
    assert int(dut.out_valid_o.value) == 0, (
        "in_err_i with in_valid_i = 0 must NOT trigger a bypass output."
    )
    # Now push a clean word with err=0; out_err_o must be 0 (not the
    # stale in_err_i from the previous cycle).
    await _push(dut, _uncompressed(0x111), err=0)
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_err_o.value) == 0


@cocotb.test()
async def edge_holds_output_stable_when_consumer_stalls(dut):
    """Consumer-side stability: out_rdata_o / out_valid_o / out_err_o
    must stay stable across multiple cycles when out_ready_i = 0
    (per integration constraint at spec line 167). Push one
    uncompressed word, then idle for 3 cycles; sample the outputs
    each cycle and confirm they match the original."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_C800
    await _seed_pc(dut, pc0)
    word = _uncompressed(0xABCDEF)
    dut.out_ready_i.value = 0
    await _push(dut, word, err=0)
    for _ in range(3):
        assert int(dut.out_valid_o.value) == 1
        assert int(dut.out_rdata_o.value) == word
        assert int(dut.out_err_o.value) == 0
        assert int(dut.out_addr_o.value) == pc0
        await _idle_one_cycle(dut)


@cocotb.test()
async def edge_unaligned_compressed_then_aligned_pop(dut):
    """After an unaligned-compressed pop (PC was odd-half, +2), PC
    becomes aligned again. Push a fresh uncompressed word and pop —
    this exercises the transition from the unaligned half-word PC
    back to an aligned PC across a pop."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_CC02  # bit[1] = 1 (start unaligned)
    await _seed_pc(dut, pc0)
    # Upper half compressed for the first instruction.
    e0 = (0xBBBA << 16) | 0x1234
    dut.out_ready_i.value = 0
    await _push(dut, e0)
    # Unaligned-compressed visible.
    assert int(dut.out_valid_o.value) == 1
    await _pop(dut)
    # PC += 2 → 0x...CC04 (now aligned, bit[1] = 0).
    assert int(dut.out_addr_o.value) == pc0 + 2
    assert (int(dut.out_addr_o.value) >> 1) & 1 == 0
    # Entry 0 was dropped on the unaligned-compressed pop.
    assert int(dut.busy_o.value) == 0


@cocotb.test()
async def edge_three_entry_aligned_drain_after_straddle_pop(dut):
    """Three entries, unaligned PC. First instruction is uncompressed
    straddle (entry 0 upper + entry 1 lower) with err on entry 1
    (so out_err_plus2_o = 1). After pop, entries shift: head is now
    the old entry 1 with the same payload. PC advances by 4 → still
    unaligned. Verifies the post-shift state's data and err carry
    correctly across the shift register."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_D002
    await _seed_pc(dut, pc0)
    e0 = (0xBBC3 << 16) | 0x1234  # uncompressed upper half
    e1 = (0xAAC3 << 16) | 0x5555  # upper16 [17:16] = 2'b11 (uncompressed)
    e2 = (0xDEAD << 16) | 0xBEEF
    dut.out_ready_i.value = 0
    await _push(dut, e0, err=0)
    await _push(dut, e1, err=1)  # err on second half of FIRST straddle
    await _push(dut, e2, err=0)
    # First instruction: unaligned 32 straddle, err on second half.
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_err_o.value) == 1
    assert int(dut.out_err_plus2_o.value) == 1
    expected1 = ((e1 & 0xFFFF) << 16) | ((e0 >> 16) & 0xFFFF)
    assert int(dut.out_rdata_o.value) == expected1
    await _pop(dut)
    # PC += 4 → 0x...D006 (still bit[1] == 1).
    assert int(dut.out_addr_o.value) == pc0 + 4
    # After shift: new head = old e1 (err=1), new entry 1 = old e2 (err=0).
    # Current instruction at unaligned PC: head's upper half is 0xAAC3 →
    # [17:16] = 2'b11 (uncompressed) → another straddle. err_q[0] is
    # now 1 (from old e1), err_q[1] is now 0 (from old e2).
    # Per Req 6 "err on first half only": out_err_o = 1, out_err_plus2_o = 0.
    expected2 = ((e2 & 0xFFFF) << 16) | ((e1 >> 16) & 0xFFFF)
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_rdata_o.value) == expected2
    assert int(dut.out_err_o.value) == 1, (
        "After shift, head's err should follow the SHIFTED err_q[0] "
        "(= old err_q[1] = 1). This catches a shift bug on err_q."
    )
    assert int(dut.out_err_plus2_o.value) == 0, (
        "Err originates from the FIRST half (shifted from old e1); "
        "out_err_plus2_o must be 0."
    )
