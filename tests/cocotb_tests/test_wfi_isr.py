"""C2-followup: WFI sleep-drain end-to-end test.

Program (`tests/sw/wfi_isr.S`):
  _start arms mie.MTIE + mstatus.MIE, schedules CLINT.mtimecmp =
  mtime + 32, raises `wfi_armed` (handshake), then issues WFI. The
  pipeline drains and `core_sleep_o` rises to 1.

  The mtime counter keeps ticking during sleep (driven by the SoC's
  always-on mtime register, not the gated core clock). When mtime >=
  mtimecmp, ClintLogic asserts mtip_out → ibex.irq_timer_i → core
  wakes, takes the M-timer trap (mcause = 0x8000_0007), handler
  clears mie.MTIE, mret resumes past WFI, main writes
  `done_marker = 0xFEEDFACE`.

  This cocotb harness simply runs the simulation, polls the program's
  flags, and verifies it observes `core_sleep_o == 1` between
  `wfi_armed` and the trap (proving the post-WFI drain happened).

Asserts:
  * `core_sleep_o == 1` was observed between wfi_armed and trap.
  * `saw_trap == 1`, `saved_mcause == 0x8000_0007`.
  * `done_marker == 0xFEEDFACE`.

Closes the spec §PS-2 ("core_sleep_o rises when drained") coverage gap
that the IbexTop unit suite cannot exercise (multi-instruction WFI
sequence required).
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


RAM_BASE        = 0x0010_0000
WFI_ARMED       = 0x0010_1000
SAW_TRAP        = 0x0010_1004
SAVED_MCAUSE    = 0x0010_1008
SAVED_MEPC      = 0x0010_100C
SAVED_MIP       = 0x0010_1010
DONE_MARKER     = 0x0010_1014

START_PC        = 0x0010_0100
HALT_PC_UPPER   = 0x0010_0300


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
                raise RuntimeError(f"unexpected @addr line in {path}: {line!r}")
            dut.u_ram.u_ram.mem[count].value = int(line, 16)
            count += 1
    return count


def _core_sleep(dut) -> int:
    return int(dut.u_ibex.u_ibex_top.core_sleep_o.value)


@cocotb.test()
async def wfi_drains_and_wakes_on_timer(dut) -> None:
    cocotb.start_soon(Clock(dut.IO_CLK, 10, units="ns").start())
    dut.ext_irq_sources_i.value = 0

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

    # 1. Wait for the program to reach the WFI handshake point.
    for _ in range(2000):
        await RisingEdge(dut.IO_CLK)
        if _mem_word(dut, WFI_ARMED) == 1:
            break
    else:
        raise AssertionError(
            "program never raised wfi_armed — did _start / mtvec setup run?"
        )

    # 2. Watch core_sleep_o until either we observe the post-WFI drain
    #    (success) or the trap fires (failure — never slept).
    saw_sleep = False
    for _ in range(500):
        await RisingEdge(dut.IO_CLK)
        if _core_sleep(dut) == 1:
            saw_sleep = True
            break
        if _mem_word(dut, SAW_TRAP) == 1:
            # Trap fired before we observed sleep — pipeline didn't
            # drain to core_sleep_o == 1, or we polled too late.
            break
    assert saw_sleep, (
        "core_sleep_o never rose between wfi_armed and trap; "
        "pipeline did not drain"
    )

    # 3. Wait for the timer interrupt to fire and the program to
    #    complete past WFI.
    for _ in range(2000):
        await RisingEdge(dut.IO_CLK)
        if _mem_word(dut, DONE_MARKER) == 0xFEEDFACE:
            break
    else:
        mcause = _mem_word(dut, SAVED_MCAUSE)
        mepc   = _mem_word(dut, SAVED_MEPC)
        saw    = _mem_word(dut, SAW_TRAP)
        done   = _mem_word(dut, DONE_MARKER)
        raise AssertionError(
            f"WFI ISR never completed; saw_trap={saw} "
            f"saved_mcause={mcause:#x} saved_mepc={mepc:#x} "
            f"done_marker={done:#x}"
        )

    saved_mcause = _mem_word(dut, SAVED_MCAUSE)
    saved_mepc   = _mem_word(dut, SAVED_MEPC)
    saved_mip    = _mem_word(dut, SAVED_MIP)

    # M-timer interrupt: (1 << 31) | 7 = 0x8000_0007.
    assert saved_mcause == 0x80000007, (
        f"mcause: expected M-timer 0x80000007, got {saved_mcause:#x}"
    )

    # mip.MTIP is bit 7.
    assert (saved_mip >> 7) & 1 == 1, (
        f"mip at trap entry did not have MTIP set: {saved_mip:#x}"
    )

    assert START_PC <= saved_mepc < HALT_PC_UPPER, (
        f"mepc {saved_mepc:#x} outside _start..halt window "
        f"[{START_PC:#x}, {HALT_PC_UPPER:#x})"
    )
