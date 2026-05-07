"""D2-followup gap C: PMP load-fault end-to-end on the swapped Ibex SoC.

Tests that the LSU + IbexPmp + cs_registers + controller chain
correctly delivers a synchronous load-access-fault when an M-mode
load hits a PMP-locked, read-denied region.

Released reset → Ibex executes `_start` from 0x0010_0100, which:
  1. Installs `mtvec` at trap_entry.
  2. Programs PMP region 0 as NA4-locked covering `forbidden_data`,
     with X=W=R=0 (cfg byte = 0x90).
  3. `lw t1, 0(t0)` against `forbidden_data` — the LSU's data-side
     PMP check (channel PMP_D=2) MUST deny this and the controller
     MUST raise a load-access-fault before t1 is written.

The trap handler stashes mcause/mepc/mtval, rewrites mepc to point at
`recovery_point`, and `mret`s. recovery_point writes done_marker and
halts.

Asserts:
  * `done_marker == 0xFEEDFACE`     — full path completed.
  * `saved_mcause == 5`              — load access fault
                                       (RISC-V Privileged Spec Table 3.6).
  * `saved_mepc   == &lw_insn`       — faulting load instruction's PC.
  * `saved_mtval  == &forbidden_data`
                                     — faulting load address (Privileged
                                       Spec Vol II §3.1.16).

Why it exists: gap C of the planned A/B/C PMP-violation ISR set.
A (`pmp_exec_isr`) covered the IF-stage path (PMP channels 0/1).
This program covers the LSU/data-side path (PMP channel 2), which
travels a different chain (LSU → IbexPmp → controller via load_err)
and was untested end-to-end.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


RAM_BASE        = 0x0010_0000
SAVED_MCAUSE    = 0x0010_1000
SAVED_MEPC      = 0x0010_1004
SAVED_MTVAL     = 0x0010_1008
DONE_MARKER     = 0x0010_100C

# Symbol addresses pinned by `tests/sw/link.ld` + the .S layout. If
# the assembly grows, update both. Verified via
# `tests/sw/build/pmp_load_isr.dis`.
LW_INSN         = 0x0010_0134
FORBIDDEN_DATA  = 0x0010_1010


def _mem_word(dut, byte_addr: int) -> int:
    """Read one 32-bit word from the SoC's RAM via hierarchical access."""
    idx = (byte_addr - RAM_BASE) // 4
    return int(dut.u_ram.u_ram.mem[idx].value)


def _load_vmem(dut, path: str) -> int:
    """Poke the Verilator-backed RAM word-by-word from a $readmemh-style
    vmem file."""
    with open(path) as fh:
        count = 0
        for line in fh:
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("#"):
                continue
            if line.startswith("@"):
                raise RuntimeError(
                    f"unexpected @addr line in {path}: {line!r}"
                )
            dut.u_ram.u_ram.mem[count].value = int(line, 16)
            count += 1
    return count


@cocotb.test()
async def pmp_load_fault_delivers_to_handler(dut) -> None:
    cocotb.start_soon(Clock(dut.IO_CLK, 10, units="ns").start())

    # External PLIC sources tied off — this test is pure synchronous
    # exception, no interrupt path.
    dut.ext_irq_sources_i.value = 0

    # Reset pulse: 1 → 0 → 1 (Ibex async-low reset).
    dut.IO_RST_N.value = 1
    await RisingEdge(dut.IO_CLK)
    dut.IO_RST_N.value = 0
    await RisingEdge(dut.IO_CLK)

    vmem_path = os.environ["VMEM_PATH"]
    loaded = _load_vmem(dut, vmem_path)
    dut._log.info(f"loaded {loaded} words from {vmem_path}")

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
        mtval  = _mem_word(dut, SAVED_MTVAL)
        done   = _mem_word(dut, DONE_MARKER)
        raise AssertionError(
            f"PMP load-fault program never completed after 5000 cycles; "
            f"saved_mcause={mcause:#x} saved_mepc={mepc:#x} "
            f"saved_mtval={mtval:#x} done_marker={done:#x}"
        )

    saved_mcause = _mem_word(dut, SAVED_MCAUSE)
    saved_mepc   = _mem_word(dut, SAVED_MEPC)
    saved_mtval  = _mem_word(dut, SAVED_MTVAL)

    # cause = 5: Load access fault (Privileged Spec Vol II Table 3.6).
    # Top bit clear → synchronous exception, not interrupt.
    assert saved_mcause == 5, (
        f"mcause: expected load-access-fault (cause=5), "
        f"got {saved_mcause:#x}; "
        f"saved_mepc={saved_mepc:#x} saved_mtval={saved_mtval:#x}; "
        f"lw_insn={LW_INSN:#x} forbidden_data={FORBIDDEN_DATA:#x}"
    )

    # mepc carries the faulting instruction's PC — the lw itself.
    assert saved_mepc == LW_INSN, (
        f"mepc: expected lw_insn {LW_INSN:#x}, got {saved_mepc:#x}"
    )

    # mtval carries the faulting load address (Privileged Spec Vol II
    # §3.1.16).
    assert saved_mtval == FORBIDDEN_DATA, (
        f"mtval: expected load addr {FORBIDDEN_DATA:#x}, "
        f"got {saved_mtval:#x}"
    )
