"""cocotb scenarios for `ibex_register_file_ff` built with ReadOneHotA = 1.

In that mode read port A is selected by the one-hot `raddr_a_oh_i` (the IF
stage registers `1 << rs1` next to the instruction, so the 5->32 decode sits
in front of the IF/ID register instead of on the register-file read path).
The scenarios drive `raddr_a_i` to a *different* register than the one-hot
select, so they fail if port A still follows `raddr_a_i`, if a select bit is
mapped to the wrong register, or if x0 stops reading as zero.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer

from test_ibex_register_file_ff_unit import _reset, _start_clock, _write


def _value(i: int) -> int:
    return (0x9E3779B9 * (i + 1)) & 0xFFFF_FFFF


async def _fill(dut):
    for i in range(1, 32):
        await _write(dut, i, _value(i))


async def _read_a_oh(dut, select: int, decoy: int) -> int:
    dut.raddr_a_oh_i.value = select
    dut.raddr_a_i.value = decoy
    await Timer(1, "ns")
    return int(dut.rdata_a_o.value)


@cocotb.test()
async def onehot_select_reads_each_register(dut):
    """Bit i of raddr_a_oh_i reads x_i, whatever raddr_a_i says."""
    await _start_clock(dut)
    await _reset(dut)
    dut.raddr_a_oh_i.value = 0
    await _fill(dut)
    for i in range(1, 32):
        decoy = 31 - i if 31 - i != i else 1
        got = await _read_a_oh(dut, 1 << i, decoy)
        assert got == _value(i), (
            f"raddr_a_oh_i = 1<<{i} (raddr_a_i = {decoy}) read {got:#010x}, "
            f"expected x{i} = {_value(i):#010x}"
        )


@cocotb.test()
async def onehot_select_x0_reads_zero(dut):
    """Bit 0 (x0) reads WordZeroVal even with every other register written."""
    await _start_clock(dut)
    await _reset(dut)
    dut.raddr_a_oh_i.value = 0
    await _fill(dut)
    got = await _read_a_oh(dut, 1, 7)
    assert got == 0, f"x0 via raddr_a_oh_i read {got:#010x}, expected 0"


@cocotb.test()
async def onehot_select_leaves_port_b_on_raddr_b(dut):
    """Port B still decodes raddr_b_i in ReadOneHotA mode."""
    await _start_clock(dut)
    await _reset(dut)
    dut.raddr_a_oh_i.value = 0
    await _fill(dut)
    dut.raddr_a_oh_i.value = 1 << 3
    for i in (0, 5, 17, 31):
        dut.raddr_b_i.value = i
        await Timer(1, "ns")
        want = 0 if i == 0 else _value(i)
        assert int(dut.rdata_b_o.value) == want, f"port B at x{i}"
