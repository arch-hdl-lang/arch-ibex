"""Standalone cocotb scenarios for `ibex_fetch_fifo` (basic suite).

Each `@cocotb.test` covers one Requirement from
`changes/port-fetch_fifo/specs/fetch_fifo/spec.md`, walking the single
most representative scenario from the spec for that requirement.

In-scope parameters: NUM_REQS = 2 (DEPTH = 3), ResetAll = 0.

Reset semantics: asynchronous, active-low (`rst_ni`).
Read path: combinational. After driving inputs, settle with
`await Timer(1, "ns")` before sampling outputs. After clock edges, use
`await RisingEdge(dut.clk_i); await Timer(1, "ns")` then sample.

Per the spec, the producer always issues `clear_i` first after reset to
seed the internal PC. Tests therefore start with a clear-driven seed
before exercising any push/pop, except for Req 7 (Reset state), which
is explicitly allowed to sample directly after reset.

Per the producer-side input boundary in the spec:
  - `in_addr_i` is consulted ONLY when `clear_i` is asserted; on
    non-clear pushes it is don't-care.
  - `in_err_i` is gated by `in_valid_i`; the FIFO ignores it when
    `in_valid_i == 0`.

Spec-faithful sampling pitfalls baked in:
  - `out_addr_o[0]` is hard-wired 0 (always asserted).
  - `out_err_plus2_o` is don't-care unless `out_err_o == 1` AND
    `out_addr_o[1] == 1`. Tests where `out_err_o == 0` MUST NOT pin
    a specific `out_err_plus2_o` value.
  - `busy_o` width is `NUM_REQS = 2`, not 3.
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


# ── Test parameters ──────────────────────────────────────────────────────
CLK_PERIOD_NS = 10  # 100 MHz


# ── Helpers ──────────────────────────────────────────────────────────────
async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())


async def _idle_inputs(dut):
    """Drive all producer/consumer inputs to a benign idle state."""
    dut.clear_i.value = 0
    dut.in_valid_i.value = 0
    dut.in_rdata_i.value = 0
    dut.in_addr_i.value = 0
    dut.in_err_i.value = 0
    dut.out_ready_i.value = 0


async def _reset(dut):
    """Async-active-low reset; idles all inputs first."""
    await _idle_inputs(dut)
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")


async def _seed_pc(dut, addr: int):
    """Issue a one-cycle `clear_i` with `in_addr_i = addr` (no push) so
    the internal PC is seeded; FIFO becomes empty. Required first
    transaction per the producer-side contract.
    """
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


async def _push(dut, data: int, err: int = 0):
    """One-cycle push of `data` (and optional err) into the FIFO. Drives
    `in_addr_i = 0` because it's don't-care on non-clear pushes."""
    dut.in_valid_i.value = 1
    dut.in_rdata_i.value = data & 0xFFFF_FFFF
    dut.in_err_i.value = err & 1
    dut.in_addr_i.value = 0  # don't-care per spec
    await RisingEdge(dut.clk_i)
    dut.in_valid_i.value = 0
    dut.in_rdata_i.value = 0
    dut.in_err_i.value = 0
    await Timer(1, "ns")


async def _pop(dut):
    """One-cycle consumer accept (`out_ready_i = 1`). Holds inputs
    otherwise idle."""
    dut.out_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.out_ready_i.value = 0
    await Timer(1, "ns")


# ── Tests: one per spec Requirement ──────────────────────────────────────
@cocotb.test()
async def empty_fifo_idle_then_bypass(dut):
    """Spec Req 1 §"Empty-FIFO bypass and idle behavior" — verifies that
    the empty FIFO holds `out_valid_o` low when `in_valid_i = 0`, and
    that a same-cycle bypass of an aligned word with `in_valid_i = 1`
    drives `out_valid_o = 1`, `out_rdata_o = D`, `out_err_o = E`,
    `out_err_plus2_o = 0`. Walks the second Scenario (bypass) which
    subsumes the idle Scenario (covered in the same test before the
    bypass). Aligned PC seeded via `clear_i`."""
    await _start_clock(dut)
    await _reset(dut)
    # Seed PC to an aligned (bit[1] = 0) address.
    await _seed_pc(dut, 0x0000_1000)
    # Idle Scenario: empty + in_valid_i = 0.
    dut.in_valid_i.value = 0
    dut.out_ready_i.value = 0
    await Timer(1, "ns")
    assert int(dut.out_valid_o.value) == 0, "empty + no push must keep out_valid_o low"
    assert int(dut.out_addr_o.value) & 1 == 0, "out_addr_o[0] must be hard-wired 0"
    assert int(dut.out_addr_o.value) == 0x0000_1000
    # Bypass Scenario: same cycle, drive in_valid_i = 1 with an aligned
    # uncompressed word and a non-zero err tag — both must surface
    # combinationally with no clock edge.
    bypass_word = 0xCAFE_BABE  # arbitrary; D[1:0] = 2'b10 (compressed),
    # but Req 1 only checks the bypass plumbing — pop/PC-advance
    # semantics are Req 2's job. Use a clearly distinct constant.
    dut.in_valid_i.value = 1
    dut.in_rdata_i.value = bypass_word
    dut.in_err_i.value = 1
    dut.in_addr_i.value = 0  # don't-care on bypass
    await Timer(1, "ns")
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_rdata_o.value) == bypass_word
    assert int(dut.out_err_o.value) == 1
    # out_addr_o[1] == 0 (aligned), so out_err_plus2_o is hard-wired 0
    # per spec line 26.
    assert int(dut.out_err_plus2_o.value) == 0
    assert int(dut.out_addr_o.value) & 1 == 0


@cocotb.test()
async def push_then_aligned_pop(dut):
    """Spec Req 2 §"Single-write / single-aligned-pop FIFO discipline" —
    walks the first Scenario (push then aligned-32 pop). Pushes one
    uncompressed word (D[1:0] == 2'b11) into the empty FIFO, confirms
    entry 0 becomes valid and the head is presented. Then asserts
    out_ready_i for one cycle and confirms entry 0 drains and the PC
    has advanced by 4."""
    await _start_clock(dut)
    await _reset(dut)
    # Seed PC aligned.
    pc0 = 0x0000_2000
    await _seed_pc(dut, pc0)
    # Cycle 0: push uncompressed word, out_ready_i = 0.
    word = 0xDEAD_BEF3  # [1:0] = 2'b11 → uncompressed
    dut.out_ready_i.value = 0
    await _push(dut, word, err=0)
    # After the edge: entry 0 valid, output presents the word.
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_rdata_o.value) == word
    assert int(dut.out_addr_o.value) == pc0
    assert int(dut.out_err_o.value) == 0
    # Cycle 1: pop.
    await _pop(dut)
    # After the edge: entry 0 popped (FIFO empty, out_valid_o low) and
    # PC has advanced by 4.
    assert int(dut.out_valid_o.value) == 0, "FIFO drained — out_valid_o must be 0"
    assert int(dut.out_addr_o.value) == pc0 + 4


@cocotb.test()
async def busy_reflects_upper_entries(dut):
    """Spec Req 3 §"Depth and producer back-pressure" — walks the
    `busy_o` Scenario. With NUM_REQS = 2, after pushing two words the
    FIFO has `valid_q == 3'b011`, i.e. entries 0 and 1 valid. The spec
    requires `busy_o == 2'b01`, i.e. {valid_q[2], valid_q[1]} = {0, 1}.
    The "no-push-when-full" Scenario is producer-enforced UB and is
    explicitly skipped per spec. busy_o is also confirmed empty (0)
    immediately after the seeding clear."""
    await _start_clock(dut)
    await _reset(dut)
    await _seed_pc(dut, 0x0000_3000)
    # After the seeding clear, FIFO is empty → busy_o == 2'b00.
    assert int(dut.busy_o.value) == 0b00
    # Push two uncompressed words (out_ready_i held low).
    dut.out_ready_i.value = 0
    await _push(dut, 0x1111_1113)  # entry 0 takes this on the next edge
    # After first push, valid_q == 3'b001 → busy_o == 2'b00.
    assert int(dut.busy_o.value) == 0b00
    await _push(dut, 0x2222_2223)  # entry 1 takes this
    # Now valid_q == 3'b011 → busy_o == {valid_q[2], valid_q[1]} = 2'b01.
    assert int(dut.busy_o.value) == 0b01


@cocotb.test()
async def pure_clear_flushes_and_reseeds(dut):
    """Spec Req 4 §"Clear flushes all entries and reseeds PC" — walks
    the pure clear Scenario. Pre-loads two valid entries, then asserts
    `clear_i = 1` with `in_valid_i = 0` and `in_addr_i = A`. After the
    next edge: `valid_q == 0` (so `out_valid_o == 0` and `busy_o == 0`)
    and `out_addr_o == {A[31:1], 1'b0}`."""
    await _start_clock(dut)
    await _reset(dut)
    await _seed_pc(dut, 0x0000_4000)
    # Pre-load two entries so valid_q == 3'b011.
    dut.out_ready_i.value = 0
    await _push(dut, 0xAAAA_AAA3)
    await _push(dut, 0xBBBB_BBB3)
    assert int(dut.busy_o.value) == 0b01, "precondition: two entries valid"
    # Pure clear with a fresh seed address. Bit[0] is don't-care (the
    # FIFO drops it); use an odd value to verify it's discarded.
    new_seed = 0x0000_5001
    dut.clear_i.value = 1
    dut.in_valid_i.value = 0
    dut.in_addr_i.value = new_seed
    await RisingEdge(dut.clk_i)
    dut.clear_i.value = 0
    dut.in_addr_i.value = 0
    await Timer(1, "ns")
    # FIFO empty, PC reseeded, bit[0] hard-wired 0.
    assert int(dut.out_valid_o.value) == 0
    assert int(dut.busy_o.value) == 0b00
    assert int(dut.out_addr_o.value) == (new_seed & 0xFFFF_FFFE)


@cocotb.test()
async def unaligned_32bit_both_halves_in_fifo(dut):
    """Spec Req 5 §"Unaligned 32-bit instruction read straddles two
    sources" — walks the first Scenario (both halves in FIFO).
    Seeds a half-word-aligned PC (`out_addr_o[1] == 1`), pushes two
    words such that the upper 16 bits of entry 0 decode as
    uncompressed (`[17:16] == 2'b11`). Asserts the spec-mandated
    `out_rdata_o == { rdata_q[1][15:0], rdata_q[0][31:16] }` and
    `out_valid_o == 1`. Then pops and confirms entry 0 drops and PC
    advances by 4."""
    await _start_clock(dut)
    await _reset(dut)
    # Seed half-word-aligned PC.
    pc0 = 0x0000_6002  # bit[1] == 1
    await _seed_pc(dut, pc0)
    assert int(dut.out_addr_o.value) == 0x0000_6002
    # Push entry 0: upper 16 bits must decode as uncompressed
    # ([17:16] == 2'b11). e.g. word = 0xBBBB_AAAA → upper16 = 0xBBBB,
    # bits [17:16] = 0b11.
    e0 = 0xBBBB_AAAA
    e1 = 0x1234_5678
    dut.out_ready_i.value = 0
    await _push(dut, e0)
    await _push(dut, e1)
    # Both entries valid; head's upper half is 0xBBBB which decodes as
    # uncompressed, so the FIFO presents { e1[15:0], e0[31:16] }.
    expected = ((e1 & 0xFFFF) << 16) | ((e0 >> 16) & 0xFFFF)
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_rdata_o.value) == expected
    assert int(dut.out_err_o.value) == 0
    # Pop: entry 0 drops, PC advances by 4 (uncompressed straddle).
    await _pop(dut)
    # After the edge: entry 0 popped; entry 1 has been shifted into
    # entry 0's slot. PC is now pc0 + 4 = 0x6006 (still bit[1] == 1).
    assert int(dut.out_addr_o.value) == pc0 + 4


@cocotb.test()
async def err_unaligned_second_half_only_sets_err_plus2(dut):
    """Spec Req 6 §"Bus-error propagation across straddling
    boundaries" — walks the "Unaligned 32-bit, err on second half only"
    Scenario. Seeds half-word-aligned PC, pushes entry 0 with err=0
    and entry 1 with err=1, where entry 0's upper 16 bits decode as
    uncompressed (so the instruction does straddle). Asserts
    `out_err_o == 1` and `out_err_plus2_o == 1` (the +2 flag must
    indicate the error originated from the second half).

    Critical because `out_err_plus2_o` is don't-care unless
    `out_err_o == 1` AND `out_addr_o[1] == 1` — both conditions hold
    here, so the assertion is meaningful (this is the only mode in
    which the consumer reads `out_err_plus2_o`)."""
    await _start_clock(dut)
    await _reset(dut)
    pc0 = 0x0000_7002
    await _seed_pc(dut, pc0)
    # Entry 0 upper-half uncompressed ([17:16] == 2'b11), err=0.
    # 0xBBC3 = 0b1011_1011_1100_0011, low 2 bits = 2'b11 → [17:16] of
    # the full word (= low 2 bits of upper16) = 2'b11 → uncompressed.
    e0 = 0xBBC3_DDDD
    # Entry 1 carries the err.
    e1 = 0x9999_8888
    dut.out_ready_i.value = 0
    await _push(dut, e0, err=0)
    await _push(dut, e1, err=1)
    # Both halves available, instruction straddles, second half errs.
    assert int(dut.out_valid_o.value) == 1
    assert int(dut.out_err_o.value) == 1
    assert int(dut.out_err_plus2_o.value) == 1


@cocotb.test()
async def reset_state_clears_valid_and_busy(dut):
    """Spec Req 7 §"Reset state" — walks the After-reset Scenario.
    Drives `rst_ni = 0` for ~2 cycles, releases, then samples
    immediately (no clear, no push). The async-reset must clear
    `valid_q`, so `busy_o == 0` and (with `in_valid_i == 0`)
    `out_valid_o == 0`. Per ResetAll = 0, the data/err/PC flops are
    not reset; the test does NOT assert anything about
    `out_addr_o[31:1]` or `out_rdata_o`."""
    await _start_clock(dut)
    # Idle inputs first; assert rst_ni asynchronously.
    await _idle_inputs(dut)
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    # While reset is held, valid_q is forced to 0.
    await Timer(1, "ns")
    assert int(dut.busy_o.value) == 0
    assert int(dut.out_valid_o.value) == 0
    # Release reset; sample immediately after the next rising edge.
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    # Still no push and no clear → still empty.
    assert int(dut.busy_o.value) == 0
    assert int(dut.out_valid_o.value) == 0
    # And out_addr_o[0] is hard-wired 0 regardless of unreset upper bits.
    assert int(dut.out_addr_o.value) & 1 == 0
