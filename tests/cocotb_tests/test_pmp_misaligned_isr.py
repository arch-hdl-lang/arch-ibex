"""D2-followup gap B: PMP misaligned-fetch fault end-to-end.

Tests that the IF-stage `pmp_err_if_plus2_i` path and the controller's
`instr_fetch_err_plus2 → mtval = pc + 2` formula correctly deliver a
synchronous instruction-access-fault when an M-mode 32-bit instruction
straddles a 4-byte PMP boundary, with PC's word allowed but PC+2's
word denied.

Released reset → Ibex executes `_start` from 0x0010_0100, which:
  1. Installs `mtvec` at trap_entry.
  2. Programs PMP region 0 as NA4-locked covering `forbidden_word`,
     with X=W=R=0 (cfg byte = 0x90).
  3. Jumps to `pre_straddle` (4-byte aligned). After a 16-bit
     `c.nop`, the 32-bit `addi x0, x0, 0` at `straddle_insn`
     (= pre_straddle + 2, misaligned) spans the 4-byte boundary at
     `forbidden_word` (= straddle_insn + 2 = pre_straddle + 4):
        bytes pre_straddle+2..+3  → word at pre_straddle (allowed)
        bytes pre_straddle+4..+5  → word at forbidden_word (DENIED)
  4. The IF-stage fetch produces:
        pmp_err_if_i       = 0       (word at pc_if  = pre_straddle)
        pmp_err_if_plus2_i = 1       (word at pc_if+2 = forbidden_word)
        if_instr_pmp_err   = 0 | (PC[1] & ~compressed & pmp_err_if_plus2)
                           = 1
     Controller traps with cause=1, mtval = pc_id + 2 (per
     `IbexController.arch:485` `csr_mtval_o = instr_fetch_err_plus2_i ?
     (pc_id_i +% 32'd2) : pc_id_i;`).

Asserts:
  * `done_marker == 0xFEEDFACE`     — full path completed.
  * `saved_mcause == 1`             — instruction access fault.
  * `saved_mepc   == &straddle_insn` — faulting insn's PC.
  * `saved_mtval  == &forbidden_word` (= straddle_insn + 2)
                                     — the +2 fetch addr (Privileged
                                       Spec Vol II §3.1.16).

Why it exists: gap B of the planned A/B/C set. A (pmp_exec_isr)
hits the aligned fetch path (pmp_err_if_i); C (pmp_load_isr) hits
the LSU/data-side path (PMP channel 2). Only this program exercises
the IF-stage `pmp_err_if_plus2_i` channel and the matching mtval
formula in the controller — both of which had no end-to-end
coverage before.

Toolchain note
--------------
Built with `rv32imc_zicsr` (per-target MARCH override in
tests/sw/Makefile) so the assembler accepts `c.nop`. The straddle
encoding is hand-rolled via `.short` directives so the assembler
can't compress or rearrange it.
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
# `tests/sw/build/pmp_misaligned_isr.dis`.
STRADDLE_INSN   = 0x0010_013A   # = pre_straddle + 2 (misaligned by 2)
FORBIDDEN_WORD  = 0x0010_013C   # = straddle_insn + 2 = the +2 fetch addr


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
async def pmp_misaligned_fault_delivers_to_handler(dut) -> None:
    cocotb.start_soon(Clock(dut.IO_CLK, 10, units="ns").start())

    # External PLIC sources tied off — pure synchronous exception.
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
            f"PMP misaligned-fault program never completed after 5000 "
            f"cycles; saved_mcause={mcause:#x} saved_mepc={mepc:#x} "
            f"saved_mtval={mtval:#x} done_marker={done:#x}"
        )

    saved_mcause = _mem_word(dut, SAVED_MCAUSE)
    saved_mepc   = _mem_word(dut, SAVED_MEPC)
    saved_mtval  = _mem_word(dut, SAVED_MTVAL)
    dut._log.info(
        f"trap state: mcause={saved_mcause:#x} mepc={saved_mepc:#x} "
        f"mtval={saved_mtval:#x}"
    )

    # cause = 1: Instruction access fault (Privileged Spec Vol II Table 3.6).
    assert saved_mcause == 1, (
        f"mcause: expected instruction-access-fault (cause=1), "
        f"got {saved_mcause:#x}; "
        f"saved_mepc={saved_mepc:#x} saved_mtval={saved_mtval:#x}; "
        f"straddle_insn={STRADDLE_INSN:#x} "
        f"forbidden_word={FORBIDDEN_WORD:#x}"
    )

    # mepc carries the faulting instruction's PC — the misaligned 32-bit
    # straddle.
    assert saved_mepc == STRADDLE_INSN, (
        f"mepc: expected straddle_insn {STRADDLE_INSN:#x}, "
        f"got {saved_mepc:#x}"
    )

    # mtval = pc_id + 2 because only the +2 fetch faulted
    # (instr_fetch_err_plus2_i path; controller branch
    # `csr_mtval_o = instr_fetch_err_plus2_i ? (pc_id_i +% 32'd2) :
    # pc_id_i;`). That equals `forbidden_word`.
    assert saved_mtval == FORBIDDEN_WORD, (
        f"mtval: expected +2 fetch addr {FORBIDDEN_WORD:#x}, "
        f"got {saved_mtval:#x}"
    )
