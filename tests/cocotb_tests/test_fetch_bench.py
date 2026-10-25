"""Fetch-path cycle-count pins (tests/sw/fetch_bench.S).

The program times five warm-cache kernels with mcycle (see the .S header)
and stores one cycle count per kernel. This test runs it on the SoC and
checks each count against an upper bound, so a fetch-path performance
regression fails here instead of surfacing only as a CoreMark delta.

Bounds are the counts measured with the fixes that introduced them; the
equivalent upstream-Ibex counts are listed for reference. A change that
makes a kernel faster passes; raise a bound only with a measured reason.
Measured with arch 0.74.1:

  kernel   bound   upstream Ibex   before (main ebf3410)
  k_seq      685        685             689
  k_fwd     1645       1645            2527
  k_jt0      845        844            1319
  k_jt4      854        844            1752
  k_jmis6    704        686             762

The k_fwd / k_jt* / k_jmis6 pins come from the branch-coalesce fix
(prefetch advances past a line a delivering fill buffer covers; branch
stales phase-1 fill buffers; hit run-ahead throttle). k_jmis6's remaining
18 cycles over upstream are the line-crossing 32-bit fetch penalty.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


RAM_BASE    = 0x0010_0000
SAW_TRAP    = 0x0010_1000
DONE_MARKER = 0x0010_1004
RESULTS     = 0x0010_1008

# (name, upper bound on the 10-iteration cycle count)
KERNELS = [
    ("k_seq",     685),
    ("k_fwd",    1645),
    ("k_jt0",     845),
    ("k_jt4",     854),
    ("k_jmis6",   704),
]


def _mem_word(dut, byte_addr: int) -> int:
    idx = (byte_addr - RAM_BASE) // 4
    return int(dut.u_ram.u_ram.mem[idx].value)


def _load_vmem(dut, path: str) -> int:
    count = 0
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("@"):
                continue
            dut.u_ram.u_ram.mem[count].value = int(line, 16)
            count += 1
    return count


@cocotb.test()
async def fetch_bench(dut):
    cocotb.start_soon(Clock(dut.IO_CLK, 10, unit="ns").start())
    dut.ext_irq_sources_i.value = 0
    dut.IO_RST_N.value = 1
    await RisingEdge(dut.IO_CLK)
    dut.IO_RST_N.value = 0
    await RisingEdge(dut.IO_CLK)
    _load_vmem(dut, os.environ["VMEM_PATH"])
    for _ in range(5):
        await RisingEdge(dut.IO_CLK)
    dut.IO_RST_N.value = 1

    for _ in range(200_000):
        await RisingEdge(dut.IO_CLK)
        if _mem_word(dut, DONE_MARKER) == 0xFEEDFACE:
            break
    else:
        raise AssertionError(
            f"fetch_bench never finished; saw_trap={_mem_word(dut, SAW_TRAP):#x}"
        )
    assert _mem_word(dut, SAW_TRAP) == 0, "fetch_bench trapped"

    over = []
    for i, (name, bound) in enumerate(KERNELS):
        cycles = _mem_word(dut, RESULTS + 4 * i)
        dut._log.info(f"fetch_bench {name:8s} cycles={cycles} bound={bound}")
        if cycles > bound:
            over.append(f"{name}: {cycles} > {bound}")
    assert not over, "fetch-path cycle counts above their pins: " + "; ".join(over)
