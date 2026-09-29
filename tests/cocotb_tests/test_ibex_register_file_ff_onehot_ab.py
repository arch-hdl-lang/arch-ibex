"""cocotb scenarios for `ibex_register_file_ff` built with ReadOneHotA = 1 and
ReadOneHotB = 1, the configuration ibex_top instantiates.

Both read ports are then selected by one-hot inputs (`raddr_a_oh_i`,
`raddr_b_oh_i`) that the IF stage registers next to the instruction, so the
5->32 decodes sit in front of the IF/ID register instead of on the
register-file read path. The scenarios drive the binary addresses to
*different* registers than the one-hot selects, so they fail if a port still
follows its binary address, if a select bit is mapped to the wrong register,
if the two ports' selects are crossed, or if x0 stops reading as zero.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer

from test_ibex_register_file_ff_onehot import _fill, _value
from test_ibex_register_file_ff_unit import _reset, _start_clock


async def _read(dut, sel_a: int, sel_b: int, decoy_a: int, decoy_b: int) -> tuple[int, int]:
    dut.raddr_a_oh_i.value = sel_a
    dut.raddr_b_oh_i.value = sel_b
    dut.raddr_a_i.value = decoy_a
    dut.raddr_b_i.value = decoy_b
    await Timer(1, "ns")
    return int(dut.rdata_a_o.value), int(dut.rdata_b_o.value)


async def _setup(dut):
    await _start_clock(dut)
    await _reset(dut)
    dut.raddr_a_oh_i.value = 0
    dut.raddr_b_oh_i.value = 0
    await _fill(dut)


@cocotb.test()
async def onehot_b_reads_each_register(dut):
    """Bit i of raddr_b_oh_i reads x_i on port B, whatever raddr_b_i says."""
    await _setup(dut)
    for i in range(1, 32):
        decoy = 31 - i if 31 - i != i else 1
        _, got = await _read(dut, 1 << 1, 1 << i, 2, decoy)
        assert got == _value(i), (
            f"raddr_b_oh_i = 1<<{i} (raddr_b_i = {decoy}) read {got:#010x}, "
            f"expected x{i} = {_value(i):#010x}"
        )


@cocotb.test()
async def onehot_b_x0_reads_zero(dut):
    """Bit 0 (x0) reads WordZeroVal on port B even with every register written."""
    await _setup(dut)
    _, got = await _read(dut, 1 << 5, 1, 5, 7)
    assert got == 0, f"x0 via raddr_b_oh_i read {got:#010x}, expected 0"


@cocotb.test()
async def onehot_ports_are_independent(dut):
    """Each port follows its own one-hot select: no crossing between A and B."""
    await _setup(dut)
    for a, b in ((3, 17), (17, 3), (31, 1), (1, 31), (9, 9)):
        got_a, got_b = await _read(dut, 1 << a, 1 << b, b, a)
        assert got_a == _value(a), f"port A select x{a} read {got_a:#010x}"
        assert got_b == _value(b), f"port B select x{b} read {got_b:#010x}"
