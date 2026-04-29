"""Standalone cocotb scenarios for `ibex_register_file_ff`.

Each `@cocotb.test` covers one Requirement from
`specs/register_file_ff/spec.md` for the in-scope parameter set
(RV32E=0, DummyInstructions=0, DataWidth=32, WordZeroVal=0).
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer, ReadOnly


CLK_PERIOD_NS = 10  # 100 MHz


async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())


async def _reset(dut):
    """Async-active-low reset, deasserted after one full clock period."""
    dut.rst_ni.value = 0
    dut.test_en_i.value = 0
    dut.dummy_instr_id_i.value = 0
    dut.dummy_instr_wb_i.value = 0
    dut.we_a_i.value = 0
    dut.waddr_a_i.value = 0
    dut.wdata_a_i.value = 0
    dut.raddr_a_i.value = 0
    dut.raddr_b_i.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)


async def _write(dut, addr: int, data: int):
    """Drive a single-cycle write, advance one rising edge."""
    dut.we_a_i.value = 1
    dut.waddr_a_i.value = addr
    dut.wdata_a_i.value = data
    await RisingEdge(dut.clk_i)
    dut.we_a_i.value = 0
    dut.waddr_a_i.value = 0
    dut.wdata_a_i.value = 0


async def _read_a(dut, addr: int) -> int:
    dut.raddr_a_i.value = addr
    await Timer(1, "ns")
    return int(dut.rdata_a_o.value)


async def _read_b(dut, addr: int) -> int:
    dut.raddr_b_i.value = addr
    await Timer(1, "ns")
    return int(dut.rdata_b_o.value)


@cocotb.test()
async def async_reset_clears_all(dut):
    """Spec §"Asynchronous reset clears all registers"."""
    await _start_clock(dut)
    # Pre-write x1, x15, x31 to non-zero values, then assert reset
    # mid-cycle and verify reads go to zero without waiting on a clock.
    await _reset(dut)
    await _write(dut, 1,  0x1111_1111)
    await _write(dut, 15, 0x1515_1515)
    await _write(dut, 31, 0x3131_3131)
    # Assert reset asynchronously; check reads immediately (no clock edge).
    dut.rst_ni.value = 0
    await Timer(1, "ns")
    for addr in (1, 15, 31):
        assert await _read_a(dut, addr) == 0, f"x{addr} not cleared by reset"
        assert await _read_b(dut, addr) == 0, f"x{addr} (port b) not cleared"
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)


@cocotb.test()
async def write_then_read_roundtrip(dut):
    """Spec §"Synchronous write on write-enable" — Scenario: write-then-read."""
    await _start_clock(dut)
    await _reset(dut)
    await _write(dut, 7, 0xCAFE_F00D)
    assert await _read_a(dut, 7) == 0xCAFE_F00D
    assert await _read_b(dut, 7) == 0xCAFE_F00D


@cocotb.test()
async def write_enable_low_holds_value(dut):
    """Spec §"Synchronous write on write-enable" — Scenario: WE low holds."""
    await _start_clock(dut)
    await _reset(dut)
    await _write(dut, 12, 0x1111_2222)
    # Drive an attempted write with we=0; value must stay.
    dut.we_a_i.value = 0
    dut.waddr_a_i.value = 12
    dut.wdata_a_i.value = 0xFFFF_FFFF
    await RisingEdge(dut.clk_i)
    assert await _read_a(dut, 12) == 0x1111_2222


@cocotb.test()
async def two_simultaneous_reads(dut):
    """Spec §"Combinational read ports" — distinct + same-address."""
    await _start_clock(dut)
    await _reset(dut)
    await _write(dut, 5, 0x0000_0005)
    await _write(dut, 9, 0x0000_0009)
    dut.raddr_a_i.value = 5
    dut.raddr_b_i.value = 9
    await Timer(1, "ns")
    assert int(dut.rdata_a_o.value) == 0x0000_0005
    assert int(dut.rdata_b_o.value) == 0x0000_0009
    # Same-address: both ports return identical data.
    await _write(dut, 10, 0xA5A5_A5A5)
    dut.raddr_a_i.value = 10
    dut.raddr_b_i.value = 10
    await Timer(1, "ns")
    assert int(dut.rdata_a_o.value) == 0xA5A5_A5A5
    assert int(dut.rdata_b_o.value) == 0xA5A5_A5A5


@cocotb.test()
async def read_during_write_returns_old_value(dut):
    """Spec §"Concurrent read-while-write returns old value"."""
    await _start_clock(dut)
    await _reset(dut)
    await _write(dut, 6, 0x0000_0006)
    # Set up read+write to x6 in the same cycle. Read port must return
    # OLD value (0x6) for the entire cycle; new value visible only
    # after the rising edge.
    dut.raddr_a_i.value = 6
    dut.we_a_i.value = 1
    dut.waddr_a_i.value = 6
    dut.wdata_a_i.value = 0xDEAD_BEEF
    await ReadOnly()
    assert int(dut.rdata_a_o.value) == 0x0000_0006, "read-during-write must return OLD value"
    await RisingEdge(dut.clk_i)
    dut.we_a_i.value = 0
    await Timer(1, "ns")
    assert int(dut.rdata_a_o.value) == 0xDEAD_BEEF, "new value must be visible after the edge"


@cocotb.test()
async def x0_reads_zero_after_reset(dut):
    """Spec §"x0 reads as WordZeroVal under normal operation"."""
    await _start_clock(dut)
    await _reset(dut)
    assert await _read_a(dut, 0) == 0
    assert await _read_b(dut, 0) == 0


@cocotb.test()
async def x0_reads_zero_despite_write(dut):
    """Spec §"x0 reads WordZeroVal regardless of attempted writes"."""
    await _start_clock(dut)
    await _reset(dut)
    # Try to write x0 — must be silently dropped.
    dut.we_a_i.value = 1
    dut.waddr_a_i.value = 0
    dut.wdata_a_i.value = 0xFFFF_FFFF
    dut.raddr_a_i.value = 0
    await Timer(1, "ns")
    assert int(dut.rdata_a_o.value) == 0, "x0 read during write must return 0"
    await RisingEdge(dut.clk_i)
    dut.we_a_i.value = 0
    await Timer(1, "ns")
    assert await _read_a(dut, 0) == 0, "x0 read after attempted write must return 0"


@cocotb.test()
async def x0_write_does_not_alias_other_registers(dut):
    """Spec §"Writes targeting x0 are dropped" — no side-effect on x1..x31."""
    await _start_clock(dut)
    await _reset(dut)
    await _write(dut, 0, 0x1234_5678)
    # Confirm x1..x31 still read zero.
    for addr in (1, 5, 16, 31):
        assert await _read_a(dut, addr) == 0, f"x{addr} disturbed by x0 write"
