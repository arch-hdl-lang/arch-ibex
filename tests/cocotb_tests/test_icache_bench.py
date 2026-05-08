"""End-to-end CPU benchmark with the icache enabled at runtime.

The companion `tests/sw/icache_bench.S` enables the icache (writes
`cpuctrlsts.icache_enable = 1`), warms it up, then measures `mcycle`
across N=32 invocations of a tight RV32IM loop kernel. The measured
cycle delta is stored to `result_cycles` and the program writes
`done_marker = 0xFEEDFACE` to hand off.

This test loads the .vmem, releases reset, polls for `done_marker`,
and reports `result_cycles`. Use with the swap and the upstream-Ibex
baseline to compare CPU performance head-to-head with the icache
actively used.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


RAM_BASE        = 0x0010_0000
SAW_TRAP        = 0x0010_1000
DONE_MARKER     = 0x0010_1004
RESULT_CYCLES   = 0x0010_1008


def _mem_word(dut, byte_addr: int) -> int:
    idx = (byte_addr - RAM_BASE) // 4
    return int(dut.u_ram.u_ram.mem[idx].value)


def _load_vmem(dut, path: str) -> int:
    with open(path) as fh:
        count = 0
        for line in fh:
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("@"):
                continue
            word = int(line, 16)
            dut.u_ram.u_ram.mem[count].value = word
            count += 1
    dut._log.info(f"loaded {count} words from {path}")
    return count


@cocotb.test()
async def icache_bench(dut):
    cocotb.start_soon(Clock(dut.IO_CLK, 10, units="ns").start())

    # Tie off external IRQs.
    dut.ext_irq_sources_i.value = 0

    # Drive rst_ni HIGH then pulse LOW for a deterministic falling
    # edge under Verilator's X/Z-at-t0 default. (timer_isr pattern.)
    dut.IO_RST_N.value = 1
    await RisingEdge(dut.IO_CLK)
    dut.IO_RST_N.value = 0
    await RisingEdge(dut.IO_CLK)

    vmem_path = os.environ["VMEM_PATH"]
    _load_vmem(dut, vmem_path)

    for _ in range(5):
        await RisingEdge(dut.IO_CLK)
    dut.IO_RST_N.value = 1

    # The benchmark soaks the inval walk (~256 cycles), runs warm-up +
    # N measured kernel invocations. Each kernel is a 200-iteration
    # loop of ~5 ops with a multi-cycle `mul`, so per-kernel cost is
    # in the low thousands of cycles. 8 measured runs + 1 warm-up
    # plus boot fits well inside a 100k ceiling.
    for _ in range(100_000):
        await RisingEdge(dut.IO_CLK)
        if _mem_word(dut, DONE_MARKER) == 0xFEEDFACE:
            break
    else:
        raise AssertionError(
            "icache_bench never wrote done_marker"
        )

    result_cycles = _mem_word(dut, RESULT_CYCLES)
    dut._log.info(f"icache_bench result_cycles = {result_cycles}")

    # Sanity: kernel does 200 × 5 ops × 8 invocations = 8000 base ops.
    # At 1 IPC that's 8000 cycles minimum; mul + branch overhead pulls
    # it higher. Reject obvious nonsense (= 0 / x).
    # Sanity: 8 × ~200 iter loop with mul = a few thousand cycles minimum.
    assert result_cycles > 1_000, (
        f"result_cycles={result_cycles} suspiciously low; "
        f"kernel didn't run or mcycle isn't ticking"
    )
