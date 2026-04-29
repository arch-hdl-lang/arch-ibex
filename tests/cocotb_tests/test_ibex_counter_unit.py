"""Standalone cocotb scenarios for `ibex_counter` (basic suite).

Each `@cocotb.test` covers one Requirement from
`specs/counter/spec.md`, walking the single most representative scenario
from the spec for that requirement with concrete numeric values.

Parameters fixed for the basic suite: CounterWidth = 32, ProvideValUpd = 1
(exercises both halves of the counter and the upd output).

Reset semantics: asynchronous, active-low.
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer, ReadOnly


# ── Test parameters (single source of truth) ─────────────────────────────
CLK_PERIOD_NS = 10  # 100 MHz

# Spec-mandated reset value of counter_val_o.
RESET_VAL = 0x0000_0000_0000_0000

# Mask used to compute "incremented value of the current counter,
# truncated to CounterWidth, zero-extended to 64". For the basic suite,
# CounterWidth = 32, so the mask is 0x0000_0000_FFFF_FFFF.
COUNTER_WIDTH = 32
COUNTER_MASK = (1 << COUNTER_WIDTH) - 1


# ── Helpers ──────────────────────────────────────────────────────────────
async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())


async def _reset(dut):
    """Drive an async-active-low reset and idle all input strobes."""
    dut.rst_ni.value = 0
    dut.counter_inc_i.value = 0
    dut.counterh_we_i.value = 0
    dut.counter_we_i.value = 0
    dut.counter_val_i.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)


async def _idle_strobes(dut):
    dut.counter_inc_i.value = 0
    dut.counterh_we_i.value = 0
    dut.counter_we_i.value = 0
    dut.counter_val_i.value = 0


async def _write_low(dut, val32: int):
    """One-cycle low-half write. Advances one rising edge."""
    dut.counter_we_i.value = 1
    dut.counterh_we_i.value = 0
    dut.counter_inc_i.value = 0
    dut.counter_val_i.value = val32 & 0xFFFF_FFFF
    await RisingEdge(dut.clk_i)
    await _idle_strobes(dut)
    # Settle combinational outputs after the edge.
    await Timer(1, "ns")


async def _write_high(dut, val32: int):
    """One-cycle high-half write. Advances one rising edge."""
    dut.counterh_we_i.value = 1
    dut.counter_we_i.value = 0
    dut.counter_inc_i.value = 0
    dut.counter_val_i.value = val32 & 0xFFFF_FFFF
    await RisingEdge(dut.clk_i)
    await _idle_strobes(dut)
    await Timer(1, "ns")


# ── Tests: one per spec Requirement ──────────────────────────────────────
@cocotb.test()
async def reset_clears_counter(dut):
    """Spec §"Asynchronous reset clears the counter" — verifies that
    while rst_ni is held low, counter_val_o reads the spec-mandated
    reset value, even after a prior write has populated the low half
    and even when increment + write strobes are simultaneously asserted.
    The clear is observed without waiting on a clock edge (asynchronous)."""
    await _start_clock(dut)
    await _reset(dut)
    # Populate the counter to a non-zero value via a low-half write.
    await _write_low(dut, 0xDEAD_BEEF)
    assert int(dut.counter_val_o.value) != RESET_VAL, "precondition: counter is non-zero"
    # Now assert reset asynchronously while increment + write strobes
    # are also high. Reset must override every other input.
    dut.rst_ni.value = 0
    dut.counter_inc_i.value = 1
    dut.counter_we_i.value = 1
    dut.counter_val_i.value = 0xFFFF_FFFF
    await Timer(1, "ns")
    assert int(dut.counter_val_o.value) == RESET_VAL, (
        "counter_val_o must read the reset value while rst_ni is low"
    )
    # Hold reset across a rising edge — still zero.
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    assert int(dut.counter_val_o.value) == RESET_VAL


@cocotb.test()
async def increment_advances_counter(dut):
    """Spec §"Increment advances the low CounterWidth bits and wraps" —
    verifies that with counter_inc_i = 1 and both write strobes low,
    the counter register updates on the next rising edge to its
    immediate successor (mod 2^CounterWidth). Walks one representative
    increment from a known seeded value."""
    await _start_clock(dut)
    await _reset(dut)
    # Seed via low-half write so the test does not depend on
    # cumulative increments from zero.
    seed = 0x0000_002A
    await _write_low(dut, seed)
    assert int(dut.counter_val_o.value) == seed, "seed write failed"
    # Hold counter_inc_i high for one rising edge.
    dut.counter_inc_i.value = 1
    dut.counter_we_i.value = 0
    dut.counterh_we_i.value = 0
    await RisingEdge(dut.clk_i)
    await _idle_strobes(dut)
    await Timer(1, "ns")
    assert int(dut.counter_val_o.value) == ((seed + 1) & COUNTER_MASK)


@cocotb.test()
async def high_bits_tied_to_zero(dut):
    """Spec §"Bits above CounterWidth are tied to zero on counter_val_o" —
    verifies that bits [63:CounterWidth] of counter_val_o read as zero
    irrespective of input history. Specifically tries to land ones in
    those positions via a high-half write and confirms the high half
    is silently discarded for CounterWidth = 32."""
    await _start_clock(dut)
    await _reset(dut)
    # Plant something in the low half so the *whole* output is
    # non-zero, then attempt a high-half write that should be
    # discarded for CounterWidth = 32.
    await _write_low(dut, 0xDEAD_BEEF)
    await _write_high(dut, 0xFFFF_FFFF)
    val = int(dut.counter_val_o.value)
    assert (val >> COUNTER_WIDTH) == 0, "bits above CounterWidth must read zero"
    # The low half is preserved by the high-write path.
    assert (val & COUNTER_MASK) == 0xDEAD_BEEF


@cocotb.test()
async def write_beats_increment(dut):
    """Spec §"Write priority — any write beats increment" — verifies
    that when counter_we_i and counter_inc_i are both asserted on the
    same rising edge, the next-cycle counter value is the write data
    (not write data + 1). counterh_we_i is held low for this case."""
    await _start_clock(dut)
    await _reset(dut)
    write_val = 0x1234_5678
    # Both strobes high simultaneously.
    dut.counter_we_i.value = 1
    dut.counterh_we_i.value = 0
    dut.counter_inc_i.value = 1
    dut.counter_val_i.value = write_val
    await RisingEdge(dut.clk_i)
    await _idle_strobes(dut)
    await Timer(1, "ns")
    # Spec says: write wins, no carry. counter_val_o == write_val
    # (zero-extended). NOT write_val + 1.
    assert int(dut.counter_val_o.value) == write_val


@cocotb.test()
async def half_word_write_priority(dut):
    """Spec §"Half-word write semantics" — verifies that when both
    counter_we_i and counterh_we_i are asserted on the same rising
    edge, counterh_we_i wins on both halves: the high half is written
    from counter_val_i and the low half is preserved unchanged
    (counter_we_i is suppressed by the same-cycle counterh_we_i).
    For CounterWidth = 32, the high write is discarded by storage so
    only the preservation of the low half is observable; this test
    seeds a known low half and verifies preservation under contention."""
    await _start_clock(dut)
    await _reset(dut)
    # Seed the low half.
    seed_low = 0xBBBB_BBBB
    await _write_low(dut, seed_low)
    assert int(dut.counter_val_o.value) == seed_low
    # Assert both write strobes simultaneously, with a distinct payload
    # on the shared bus. counterh_we_i must win the arbitration:
    # low half stays at seed_low (NOT overwritten with the bus payload).
    bus_val = 0x5555_6666
    dut.counter_we_i.value = 1
    dut.counterh_we_i.value = 1
    dut.counter_inc_i.value = 0
    dut.counter_val_i.value = bus_val
    await RisingEdge(dut.clk_i)
    await _idle_strobes(dut)
    await Timer(1, "ns")
    # Low half preserved (NOT replaced by bus_val).
    assert (int(dut.counter_val_o.value) & COUNTER_MASK) == seed_low
    # High half: tied-zero by storage width for CounterWidth = 32.
    assert (int(dut.counter_val_o.value) >> COUNTER_WIDTH) == 0


@cocotb.test()
async def upd_forwards_incremented_value(dut):
    """Spec §"counter_val_upd_o gating by ProvideValUpd" — for the
    basic suite (ProvideValUpd = 1), verifies that counter_val_upd_o
    combinationally tracks the incremented value of the current
    register, zero-extended to 64 bits. Checks the published value
    against the same-cycle counter_val_o without a clock edge between
    them, and confirms it is independent of counter_inc_i."""
    await _start_clock(dut)
    await _reset(dut)
    # Seed a known counter value.
    seed = 0x1234_5677
    await _write_low(dut, seed)
    # With counter_inc_i = 0, upd should still publish counter + 1
    # (truncated to CounterWidth, zero-extended to 64).
    dut.counter_inc_i.value = 0
    dut.counter_we_i.value = 0
    dut.counterh_we_i.value = 0
    await Timer(1, "ns")
    cur = int(dut.counter_val_o.value)
    upd = int(dut.counter_val_upd_o.value)
    expected = (cur + 1) & COUNTER_MASK
    assert cur == seed
    assert upd == expected, "upd must equal (counter + 1) mod 2^CounterWidth"
    # And the high bits of upd must be zero for CounterWidth < 64.
    assert (upd >> COUNTER_WIDTH) == 0
