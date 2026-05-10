"""End-to-end CPU benchmark with the icache enabled at runtime.

The companion `tests/sw/icache_bench.S` enables the icache (writes
`cpuctrlsts.icache_enable = 1`), warms it up, then measures `mcycle`
across N=8 invocations of a tight RV32IM loop kernel. The measured
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
    pc_path = dut.u_ibex.u_ibex_top.u_ibex_core.if_stage_i.pc_id_o
    iv_path = dut.u_ibex.u_ibex_top.u_ibex_core.if_stage_i.instr_valid_id_o
    rfwe_path = dut.u_ibex.u_ibex_top.u_ibex_core.id_stage_i.rf_we_id_o
    instr_done_path = dut.u_ibex.u_ibex_top.u_ibex_core.id_stage_i.instr_done

    BINS = [
        ("loop_add",     0x10017c, 0x100180),
        ("loop_mul",     0x100180, 0x100184),
        ("loop_addi_t2", 0x100184, 0x100188),
        ("loop_addi_t0", 0x100188, 0x10018c),
        ("loop_bne",     0x10018c, 0x100190),
    ]
    bin_cycles  = {n: 0 for n, _, _ in BINS}
    bin_commits = {n: 0 for n, _, _ in BINS}
    last_pcs: list[tuple[int, int, int]] = []

    completed = False
    for cy in range(100_000):
        await RisingEdge(dut.IO_CLK)
        try:
            pc   = int(pc_path.value) & 0xFFFF_FFFF
            iv   = int(iv_path.value)
            done = int(instr_done_path.value)
        except Exception:
            pc, iv, done = 0, 0, 0
        last_pcs.append((pc, iv, done))
        if len(last_pcs) > 16:
            last_pcs.pop(0)
        for n, lo, hi in BINS:
            if lo <= pc < hi:
                bin_cycles[n] += 1
                if iv == 1 and done == 1:
                    bin_commits[n] += 1
                break
        if _mem_word(dut, DONE_MARKER) == 0xFEEDFACE:
            completed = True
            break
    if not completed:
        loop_counts = ", ".join(
            f"{n}:cy={bin_cycles[n]} commit={bin_commits[n]}"
            for n, _, _ in BINS
        )
        tail = ", ".join(
            f"{pc:#x}/iv{iv}/done{done}" for pc, iv, done in last_pcs
        )
        raise AssertionError(
            "icache_bench never wrote done_marker; "
            f"saw_trap={_mem_word(dut, SAW_TRAP):#x} "
            f"done_marker={_mem_word(dut, DONE_MARKER):#x} "
            f"result_cycles={_mem_word(dut, RESULT_CYCLES):#x}; "
            f"loop_counts=[{loop_counts}]; tail_pc=[{tail}]"
        )

    dut._log.info("─── per-loop-instr cycles / commits ───")
    for n, _, _ in BINS:
        c = bin_cycles[n]
        k = bin_commits[n]
        cpc = (c / k) if k > 0 else 0.0
        dut._log.info(
            f"  {n:14s}  cycles={c:>7d}  commits={k:>7d}  cy/commit={cpc:5.2f}"
        )

    result_cycles = _mem_word(dut, RESULT_CYCLES)
    dut._log.info(f"icache_bench result_cycles = {result_cycles}")

    # Sanity: kernel does 200 × 5 ops × 8 invocations = 8000 base ops.
    # At 1 IPC that's 8000 cycles minimum; mul + branch overhead pulls
    # it higher. Reject obvious nonsense (= 0 / x).
    assert result_cycles > 1_000, (
        f"result_cycles={result_cycles} suspiciously low; "
        f"kernel didn't run or mcycle isn't ticking"
    )
    assert result_cycles <= 19_000, (
        f"icache_bench result_cycles={result_cycles} exceeds "
        "ARCH-native icache output target of 19000"
    )
