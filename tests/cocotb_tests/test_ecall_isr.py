"""Minimum trap-delivery sanity check on the swapped Ibex SoC.

A bare ecall from M-mode should produce mcause=11 (Environment call
from M-mode). If this passes, the trap delivery path works and any
mcause=0-on-PMP-test failure is PMP-specific. If this fails, trap
delivery itself is broken in our swap and PMP integration coverage
needs to wait.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


RAM_BASE      = 0x0010_0000
SAVED_MCAUSE  = 0x0010_1000
SAVED_MEPC    = 0x0010_1004
DONE_MARKER   = 0x0010_1008


def _mem_word(dut, byte_addr: int) -> int:
    idx = (byte_addr - RAM_BASE) // 4
    return int(dut.u_ram.u_ram.mem[idx].value)


def _load_vmem(dut, path: str) -> int:
    with open(path) as fh:
        count = 0
        for line in fh:
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("#"):
                continue
            if line.startswith("@"):
                raise RuntimeError(f"unexpected @addr: {line!r}")
            dut.u_ram.u_ram.mem[count].value = int(line, 16)
            count += 1
    return count


@cocotb.test()
async def ecall_delivers_mcause_11(dut) -> None:
    cocotb.start_soon(Clock(dut.IO_CLK, 10, units="ns").start())
    dut.ext_irq_sources_i.value = 0

    dut.IO_RST_N.value = 1
    await RisingEdge(dut.IO_CLK)
    dut.IO_RST_N.value = 0
    await RisingEdge(dut.IO_CLK)

    vmem_path = os.environ["VMEM_PATH"]
    _load_vmem(dut, vmem_path)

    for _ in range(5):
        await RisingEdge(dut.IO_CLK)
    dut.IO_RST_N.value = 1

    for _ in range(5000):
        await RisingEdge(dut.IO_CLK)
        if _mem_word(dut, DONE_MARKER) == 0xFEEDFACE:
            break
    else:
        mcause = _mem_word(dut, SAVED_MCAUSE)
        mepc   = _mem_word(dut, SAVED_MEPC)
        done   = _mem_word(dut, DONE_MARKER)
        raise AssertionError(
            f"ecall sanity probe never completed; mcause={mcause:#x} "
            f"mepc={mepc:#x} done={done:#x}"
        )

    saved_mcause = _mem_word(dut, SAVED_MCAUSE)
    saved_mepc   = _mem_word(dut, SAVED_MEPC)

    # cause = 11: Environment call from M-mode (Privileged Spec Vol II
    # Table 3.6). Top bit clear → synchronous exception.
    assert saved_mcause == 11, (
        f"mcause: expected M-mode ecall (cause=11), got {saved_mcause:#x}; "
        f"saved_mepc={saved_mepc:#x}"
    )
