"""Full-regression cocotb scenarios for `ibex_counter`.

Walks every `#### Scenario:` from `specs/counter/spec.md`, plus edge
cases the spec implies but doesn't enumerate exhaustively:

  * Wraparound at every in-scope CounterWidth ∈ {1, 32, 64}.
  * ProvideValUpd = 0: counter_val_upd_o stays zero even on cycles
    where the counter is incrementing.
  * Reset asserted mid-write: reset wins.

The pytest collector builds a separate Verilator binary for each of
the six parameter combinations (CounterWidth × ProvideValUpd) and
re-runs this module against each binary. Each test reads the
build-time parameters from env vars `COUNTER_WIDTH` and
`PROVIDE_VAL_UPD` (set by the collector) and skips itself when its
preconditions don't match.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


CLK_PERIOD_NS = 10
RESET_VAL = 0x0000_0000_0000_0000


def _params() -> tuple[int, int]:
    """Read CounterWidth / ProvideValUpd of the currently-built binary
    from environment variables set by the pytest collector."""
    cw = int(os.environ.get("COUNTER_WIDTH", "32"))
    pvu = int(os.environ.get("PROVIDE_VAL_UPD", "1"))
    return cw, pvu


def _mask(cw: int) -> int:
    if cw >= 64:
        return (1 << 64) - 1
    return (1 << cw) - 1


# ── Helpers ──────────────────────────────────────────────────────────────
async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())


async def _idle_strobes(dut):
    dut.counter_inc_i.value = 0
    dut.counterh_we_i.value = 0
    dut.counter_we_i.value = 0
    dut.counter_val_i.value = 0


async def _reset(dut):
    dut.rst_ni.value = 0
    await _idle_strobes(dut)
    await Timer(2 * CLK_PERIOD_NS, "ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")


async def _write_low(dut, val: int):
    dut.counter_we_i.value = 1
    dut.counterh_we_i.value = 0
    dut.counter_inc_i.value = 0
    dut.counter_val_i.value = val & 0xFFFF_FFFF
    await RisingEdge(dut.clk_i)
    await _idle_strobes(dut)
    await Timer(1, "ns")


async def _write_high(dut, val: int):
    dut.counterh_we_i.value = 1
    dut.counter_we_i.value = 0
    dut.counter_inc_i.value = 0
    dut.counter_val_i.value = val & 0xFFFF_FFFF
    await RisingEdge(dut.clk_i)
    await _idle_strobes(dut)
    await Timer(1, "ns")


async def _seed_to(dut, target: int):
    """Seed the counter to a target value via half-word writes.
    Works for any CounterWidth via low/high writes; bits above
    CounterWidth are silently dropped by storage, which is fine for
    seed targets that already respect the mask."""
    cw, _ = _params()
    target &= _mask(cw)
    if cw <= 32:
        await _write_low(dut, target)
    else:
        # 64-bit case: high half then low half. (counterh_we_i has
        # priority and preserves low half; sequential writes are fine.)
        await _write_high(dut, (target >> 32) & 0xFFFF_FFFF)
        await _write_low(dut, target & 0xFFFF_FFFF)


# ─────────────────────────────────────────────────────────────────────────
# Requirement: Asynchronous reset clears the counter
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def reset_from_arbitrary_state(dut):
    """Spec §reset, Scenario: Reset from arbitrary state."""
    cw, _ = _params()
    await _start_clock(dut)
    await _reset(dut)
    # Seed something non-zero (skip if width is too small).
    seed = 0xDEAD_BEEF & _mask(cw)
    if seed == 0:
        seed = 1 & _mask(cw)
    await _seed_to(dut, seed)
    # Async reset (no clock edge between assertion and observation).
    dut.rst_ni.value = 0
    await Timer(1, "ns")
    assert int(dut.counter_val_o.value) == RESET_VAL
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)


@cocotb.test()
async def reset_overrides_simultaneous_increment_and_write(dut):
    """Spec §reset, Scenario: Reset overrides simultaneous increment and write."""
    await _start_clock(dut)
    await _reset(dut)
    dut.rst_ni.value = 0
    dut.counter_inc_i.value = 1
    dut.counter_we_i.value = 1
    dut.counterh_we_i.value = 0
    dut.counter_val_i.value = 0xFFFF_FFFF
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    assert int(dut.counter_val_o.value) == RESET_VAL
    await _idle_strobes(dut)
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)


@cocotb.test()
async def counter_starts_at_zero_after_reset_deassertion(dut):
    """Spec §reset, Scenario: Counter starts at zero after reset deassertion."""
    await _start_clock(dut)
    await _reset(dut)
    # All strobes idle on the first post-reset cycle and beyond.
    await Timer(1, "ns")
    assert int(dut.counter_val_o.value) == RESET_VAL
    # And remains zero across a few idle cycles.
    for _ in range(3):
        await RisingEdge(dut.clk_i)
        await Timer(1, "ns")
        assert int(dut.counter_val_o.value) == RESET_VAL


# ─────────────────────────────────────────────────────────────────────────
# Requirement: Increment advances the low CounterWidth bits and wraps
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def single_step_increment_full_width(dut):
    """Spec §increment, Scenario: Single-step increment, CounterWidth = 64
    (parametrized to current width — verifies one increment from a seed)."""
    cw, _ = _params()
    await _start_clock(dut)
    await _reset(dut)
    seed = 0x2A & _mask(cw)
    await _seed_to(dut, seed)
    dut.counter_inc_i.value = 1
    dut.counter_we_i.value = 0
    dut.counterh_we_i.value = 0
    await RisingEdge(dut.clk_i)
    await _idle_strobes(dut)
    await Timer(1, "ns")
    assert int(dut.counter_val_o.value) == ((seed + 1) & _mask(cw))


@cocotb.test()
async def wraparound_at_counter_width(dut):
    """Spec §increment, Scenarios: Wraparound at CounterWidth = 32 / 64,
    plus the implied edge case for CounterWidth = 1. Seeds the counter
    to its all-ones state then increments once and verifies wrap to 0."""
    cw, _ = _params()
    await _start_clock(dut)
    await _reset(dut)
    all_ones = _mask(cw)
    await _seed_to(dut, all_ones)
    assert int(dut.counter_val_o.value) == all_ones
    dut.counter_inc_i.value = 1
    dut.counter_we_i.value = 0
    dut.counterh_we_i.value = 0
    await RisingEdge(dut.clk_i)
    await _idle_strobes(dut)
    await Timer(1, "ns")
    assert int(dut.counter_val_o.value) == 0


@cocotb.test()
async def toggle_behaviour_at_counter_width_1(dut):
    """Spec §increment, Scenario: Toggle behaviour at CounterWidth = 1.
    Skipped for other widths."""
    cw, _ = _params()
    if cw != 1:
        return  # not applicable
    await _start_clock(dut)
    await _reset(dut)
    dut.counter_inc_i.value = 1
    dut.counter_we_i.value = 0
    dut.counterh_we_i.value = 0
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    assert int(dut.counter_val_o.value) == 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    assert int(dut.counter_val_o.value) == 0
    await _idle_strobes(dut)


@cocotb.test()
async def no_increment_when_inc_low(dut):
    """Spec §increment, Scenario: No increment when counter_inc_i is low."""
    cw, _ = _params()
    await _start_clock(dut)
    await _reset(dut)
    seed = 0x42 & _mask(cw)
    await _seed_to(dut, seed)
    # All strobes low across a clock edge.
    await _idle_strobes(dut)
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    assert int(dut.counter_val_o.value) == seed


# ─────────────────────────────────────────────────────────────────────────
# Requirement: Bits above CounterWidth are tied to zero on counter_val_o
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def tied_zero_high_half_at_counter_width_32(dut):
    """Spec §tied-zero, Scenario: Tied-zero high half for CounterWidth = 32.
    Skipped for other widths."""
    cw, _ = _params()
    if cw != 32:
        return
    await _start_clock(dut)
    await _reset(dut)
    # Try to land ones in the high half via a high-half write (which
    # is silently discarded for CW=32) and via increment activity.
    await _write_low(dut, 0xDEAD_BEEF)
    await _write_high(dut, 0xFFFF_FFFF)
    val = int(dut.counter_val_o.value)
    assert (val >> 32) == 0
    # And after some increments.
    dut.counter_inc_i.value = 1
    for _ in range(5):
        await RisingEdge(dut.clk_i)
        await Timer(1, "ns")
        assert (int(dut.counter_val_o.value) >> 32) == 0
    await _idle_strobes(dut)


@cocotb.test()
async def tied_zero_high_half_at_counter_width_1(dut):
    """Spec §tied-zero, Scenario: Tied-zero high half for CounterWidth = 1.
    Skipped for other widths."""
    cw, _ = _params()
    if cw != 1:
        return
    await _start_clock(dut)
    await _reset(dut)
    # Write all-ones (only bit 0 lands in storage).
    await _write_low(dut, 0xFFFF_FFFF)
    val = int(dut.counter_val_o.value)
    assert (val >> 1) == 0
    assert (val & 1) == 1


# ─────────────────────────────────────────────────────────────────────────
# Requirement: Write priority — any write beats increment
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def counter_we_beats_inc(dut):
    """Spec §write-priority, Scenario: counter_we_i and counter_inc_i asserted together.
    Only meaningful for CounterWidth >= 1 with low-half storage; runs at all widths."""
    cw, _ = _params()
    await _start_clock(dut)
    await _reset(dut)
    write_val = 0x1234_5678
    dut.counter_we_i.value = 1
    dut.counterh_we_i.value = 0
    dut.counter_inc_i.value = 1
    dut.counter_val_i.value = write_val
    await RisingEdge(dut.clk_i)
    await _idle_strobes(dut)
    await Timer(1, "ns")
    expected = write_val & _mask(cw)
    assert int(dut.counter_val_o.value) == expected, (
        "write must win over increment (no carry)"
    )


@cocotb.test()
async def counterh_we_beats_inc_preserves_low(dut):
    """Spec §write-priority, Scenario: counterh_we_i and counter_inc_i asserted together.
    Spec exemplar uses CounterWidth = 64; for CounterWidth < 64 the
    high write is silently discarded — the observable property is
    "low half preserved (not incremented)"."""
    cw, _ = _params()
    await _start_clock(dut)
    await _reset(dut)
    # Seed low to a known value.
    seed = 0xFFFF_FFFF & _mask(cw)
    await _seed_to(dut, seed)
    # counterh_we_i + counter_inc_i, no counter_we_i.
    dut.counterh_we_i.value = 1
    dut.counter_we_i.value = 0
    dut.counter_inc_i.value = 1
    dut.counter_val_i.value = 0xCAFE_BABE
    await RisingEdge(dut.clk_i)
    await _idle_strobes(dut)
    await Timer(1, "ns")
    val = int(dut.counter_val_o.value)
    # Low half (within the storage's reach) preserved — NOT incremented.
    if cw >= 32:
        assert (val & 0xFFFF_FFFF) == (seed & 0xFFFF_FFFF)
    else:
        # CW=1: low half is just the LSB; preserved regardless.
        assert (val & _mask(cw)) == (seed & _mask(cw))
    if cw == 64:
        # High half written from counter_val_i.
        assert (val >> 32) == 0xCAFE_BABE
    else:
        # High write discarded by storage.
        assert (val >> cw) == 0


# ─────────────────────────────────────────────────────────────────────────
# Requirement: Half-word write semantics
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def low_half_write_only_full_width(dut):
    """Spec §half-word, Scenario: Low-half write only, CounterWidth = 64.
    Only meaningful when high half is observable (cw == 64)."""
    cw, _ = _params()
    if cw != 64:
        return
    await _start_clock(dut)
    await _reset(dut)
    # Seed the full 64 bits.
    await _seed_to(dut, 0xAAAA_AAAA_BBBB_BBBB)
    # Low-half write.
    await _write_low(dut, 0x1111_2222)
    val = int(dut.counter_val_o.value)
    assert val == 0xAAAA_AAAA_1111_2222


@cocotb.test()
async def high_half_write_only_full_width(dut):
    """Spec §half-word, Scenario: High-half write only, CounterWidth = 64."""
    cw, _ = _params()
    if cw != 64:
        return
    await _start_clock(dut)
    await _reset(dut)
    await _seed_to(dut, 0xAAAA_AAAA_BBBB_BBBB)
    await _write_high(dut, 0x3333_4444)
    val = int(dut.counter_val_o.value)
    assert val == 0x3333_4444_BBBB_BBBB


@cocotb.test()
async def counterh_priority_when_both_strobes_high(dut):
    """Spec §half-word, Scenario: counterh_we_i has priority when both
    write strobes are high. CounterWidth = 64 in the spec exemplar; runs
    only at cw == 64 to assert both halves' behaviour."""
    cw, _ = _params()
    if cw != 64:
        return
    await _start_clock(dut)
    await _reset(dut)
    await _seed_to(dut, 0xAAAA_AAAA_BBBB_BBBB)
    dut.counter_we_i.value = 1
    dut.counterh_we_i.value = 1
    dut.counter_inc_i.value = 0
    dut.counter_val_i.value = 0x5555_6666
    await RisingEdge(dut.clk_i)
    await _idle_strobes(dut)
    await Timer(1, "ns")
    val = int(dut.counter_val_o.value)
    # High half written from bus, low half preserved.
    assert val == 0x5555_6666_BBBB_BBBB


@cocotb.test()
async def low_half_write_at_counter_width_32(dut):
    """Spec §half-word, Scenario: Low-half write at CounterWidth = 32."""
    cw, _ = _params()
    if cw != 32:
        return
    await _start_clock(dut)
    await _reset(dut)
    await _seed_to(dut, 0xDEAD_BEEF)
    await _write_low(dut, 0xFEED_FACE)
    assert int(dut.counter_val_o.value) == 0xFEED_FACE


@cocotb.test()
async def high_half_write_discarded_at_counter_width_32(dut):
    """Spec §half-word, Scenario: High-half write is silently discarded
    when CounterWidth = 32."""
    cw, _ = _params()
    if cw != 32:
        return
    await _start_clock(dut)
    await _reset(dut)
    await _seed_to(dut, 0xDEAD_BEEF)
    await _write_high(dut, 0xCAFE_BABE)
    val = int(dut.counter_val_o.value)
    assert val == 0xDEAD_BEEF


@cocotb.test()
async def low_half_write_truncates_at_counter_width_1(dut):
    """Spec §half-word, Scenario: Low-half write at CounterWidth = 1
    truncates to one bit (write all-but-LSB-zero, see zero land)."""
    cw, _ = _params()
    if cw != 1:
        return
    await _start_clock(dut)
    await _reset(dut)
    await _write_low(dut, 0xFFFF_FFFE)
    assert int(dut.counter_val_o.value) == 0


@cocotb.test()
async def low_half_write_odd_at_counter_width_1(dut):
    """Spec §half-word, Scenario: Low-half write at CounterWidth = 1 with odd value."""
    cw, _ = _params()
    if cw != 1:
        return
    await _start_clock(dut)
    await _reset(dut)
    await _write_low(dut, 0x0000_0001)
    assert int(dut.counter_val_o.value) == 1


# ─────────────────────────────────────────────────────────────────────────
# Requirement: counter_val_upd_o gating by ProvideValUpd
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def upd_zero_when_provide_val_upd_zero_with_increment(dut):
    """Spec §upd, Scenario: ProvideValUpd = 0, increment in flight.
    Verifies upd reads zero even on cycles where the counter is being
    incremented, across multiple values."""
    cw, pvu = _params()
    if pvu != 0:
        return
    await _start_clock(dut)
    await _reset(dut)
    # Seed a known value.
    seed = 0x07 & _mask(cw)
    await _seed_to(dut, seed)
    # Hold counter_inc_i high and check upd stays zero across edges.
    dut.counter_inc_i.value = 1
    dut.counter_we_i.value = 0
    dut.counterh_we_i.value = 0
    for _ in range(4):
        await Timer(1, "ns")
        assert int(dut.counter_val_upd_o.value) == 0
        await RisingEdge(dut.clk_i)
    await _idle_strobes(dut)


@cocotb.test()
async def upd_zero_when_provide_val_upd_zero_idle(dut):
    """Spec §upd, Scenario: ProvideValUpd = 0, idle."""
    cw, pvu = _params()
    if pvu != 0:
        return
    await _start_clock(dut)
    await _reset(dut)
    await _idle_strobes(dut)
    await Timer(1, "ns")
    assert int(dut.counter_val_upd_o.value) == 0


@cocotb.test()
async def upd_normal_forwarding(dut):
    """Spec §upd, Scenario: ProvideValUpd = 1, normal forwarding.
    Seeds a value and verifies upd == counter + 1 (mod 2^CounterWidth)."""
    cw, pvu = _params()
    if pvu != 1:
        return
    await _start_clock(dut)
    await _reset(dut)
    seed = 0x07 & _mask(cw)
    await _seed_to(dut, seed)
    await _idle_strobes(dut)
    await Timer(1, "ns")
    assert int(dut.counter_val_o.value) == seed
    assert int(dut.counter_val_upd_o.value) == ((seed + 1) & _mask(cw))


@cocotb.test()
async def upd_wraparound_forwarding(dut):
    """Spec §upd, Scenario: ProvideValUpd = 1, wraparound forwarding.
    Seeds counter to all-ones and checks upd reads zero (wrap)."""
    cw, pvu = _params()
    if pvu != 1:
        return
    await _start_clock(dut)
    await _reset(dut)
    all_ones = _mask(cw)
    await _seed_to(dut, all_ones)
    await _idle_strobes(dut)
    await Timer(1, "ns")
    assert int(dut.counter_val_o.value) == all_ones
    assert int(dut.counter_val_upd_o.value) == 0


@cocotb.test()
async def upd_high_bits_tied_to_zero(dut):
    """Spec §upd, Scenario: ProvideValUpd = 1, high bits tied to zero.
    Only meaningful when CounterWidth < 64."""
    cw, pvu = _params()
    if pvu != 1 or cw >= 64:
        return
    await _start_clock(dut)
    await _reset(dut)
    seed = 0x1234_5677 & _mask(cw)
    await _seed_to(dut, seed)
    await _idle_strobes(dut)
    await Timer(1, "ns")
    upd = int(dut.counter_val_upd_o.value)
    assert (upd >> cw) == 0


@cocotb.test()
async def upd_independent_of_counter_inc(dut):
    """Spec §upd, Scenario: ProvideValUpd = 1 is independent of counter_inc_i."""
    cw, pvu = _params()
    if pvu != 1:
        return
    await _start_clock(dut)
    await _reset(dut)
    seed = 0x10 & _mask(cw)
    await _seed_to(dut, seed)
    # counter_inc_i = 0; upd must still publish counter + 1.
    await _idle_strobes(dut)
    await Timer(1, "ns")
    assert int(dut.counter_val_upd_o.value) == ((seed + 1) & _mask(cw))


@cocotb.test()
async def upd_reflects_current_register_not_next(dut):
    """Spec §upd, Scenario: ProvideValUpd = 1 reflects the *current*
    register, not the next. Asserts a write strobe in the same cycle
    as upd is sampled, and verifies upd uses counter (pre-write), not
    counter_d (post-write)."""
    cw, pvu = _params()
    if pvu != 1:
        return
    await _start_clock(dut)
    await _reset(dut)
    seed = 0x05 & _mask(cw)
    await _seed_to(dut, seed)
    # Assert a write but sample upd before the rising edge.
    dut.counter_we_i.value = 1
    dut.counterh_we_i.value = 0
    dut.counter_inc_i.value = 0
    dut.counter_val_i.value = 0x0000_00FF
    await Timer(1, "ns")
    # upd must equal seed + 1, NOT 0xFF + 1.
    assert int(dut.counter_val_upd_o.value) == ((seed + 1) & _mask(cw))
    # Let the write commit and idle, so the next test starts clean.
    await RisingEdge(dut.clk_i)
    await _idle_strobes(dut)
    await Timer(1, "ns")


# ─────────────────────────────────────────────────────────────────────────
# Edge cases the spec implies but doesn't enumerate exhaustively
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def increment_past_all_ones_wraps(dut):
    """Edge case: drive consecutive increments through the wrap point.
    Seeds counter to (all-ones - 1), then issues two increments and
    confirms counter goes all-ones, then 0."""
    cw, _ = _params()
    await _start_clock(dut)
    await _reset(dut)
    if cw == 1:
        # Already covered by toggle_behaviour_at_counter_width_1 from 0.
        return
    near_top = (_mask(cw) - 1) & _mask(cw)
    await _seed_to(dut, near_top)
    dut.counter_inc_i.value = 1
    dut.counter_we_i.value = 0
    dut.counterh_we_i.value = 0
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    assert int(dut.counter_val_o.value) == _mask(cw)
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    assert int(dut.counter_val_o.value) == 0
    await _idle_strobes(dut)


@cocotb.test()
async def reset_mid_write_reset_wins(dut):
    """Edge case: reset asserted in the same cycle as a write strobe.
    Verifies reset wins (counter_val_o reads zero asynchronously)."""
    await _start_clock(dut)
    await _reset(dut)
    # Seed a non-zero value.
    await _seed_to(dut, 0x55)
    # Drive a write and assert reset before the rising edge.
    dut.counter_we_i.value = 1
    dut.counterh_we_i.value = 0
    dut.counter_inc_i.value = 0
    dut.counter_val_i.value = 0xAAAA_AAAA
    await Timer(1, "ns")
    dut.rst_ni.value = 0
    await Timer(1, "ns")
    assert int(dut.counter_val_o.value) == RESET_VAL
    # And after the rising edge — still zero.
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    assert int(dut.counter_val_o.value) == RESET_VAL
    dut.rst_ni.value = 1
    await _idle_strobes(dut)
    await RisingEdge(dut.clk_i)


@cocotb.test()
async def upd_zero_during_increment_when_pvu_zero(dut):
    """Edge case (ProvideValUpd = 0 only): upd stays zero specifically
    on cycles where the counter is incrementing — overlaps with the
    spec scenario but adds a clock-edge sweep to catch glitches."""
    cw, pvu = _params()
    if pvu != 0:
        return
    await _start_clock(dut)
    await _reset(dut)
    seed = 0x0F & _mask(cw)
    await _seed_to(dut, seed)
    dut.counter_inc_i.value = 1
    dut.counter_we_i.value = 0
    dut.counterh_we_i.value = 0
    for _ in range(8):
        await Timer(1, "ns")
        assert int(dut.counter_val_upd_o.value) == 0, "upd must be zero when PVU=0"
        await RisingEdge(dut.clk_i)
    await _idle_strobes(dut)
