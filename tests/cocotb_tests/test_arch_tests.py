"""Generic cocotb runner for the RISC-V Architectural Tests.

Driven by `tests/test_arch_tests.py` — that pytest collector parametrizes
over each `.S` test and invokes this module via cocotb-runner. Per-test
inputs come in via env vars:

  VMEM_PATH       : path to the .vmem to load into RAM
  SYMS_PATH       : path to the `nm`-dumped symbol table; we extract
                    `begin_signature` / `end_signature` / `done_marker`
                    from it so we know which RAM words to poll/dump
  SIGNATURE_OUT   : path where we write the captured signature
                    (one 32-bit word per line, hex)
  TIMEOUT_CYCLES  : optional override for the done-marker timeout
                    (default 1_000_000 — long because the C suite's
                    cswsp test does ~30K stores)

The runner:
  1. Releases reset, pokes the .vmem into RAM word-by-word via VPI
     (matching the existing timer_isr / sw_isr pattern).
  2. Polls `done_marker` until it reads 0xFEEDFACE.
  3. Reads the words in [begin_signature, end_signature) and writes
     them to SIGNATURE_OUT, one hex word per line.

Comparison against the reference happens upstream in the pytest
harness — keeping it out of cocotb makes mismatch reporting easier
to surface (cocotb assertion failures are flattened into XML).
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


RAM_BASE = 0x0010_0000
RAM_WORDS = (1 << 20) // 4  # 1 MB


def _byte_to_idx(addr: int) -> int:
    """RAM byte address → word index in `u_ram.u_ram.mem[]`."""
    return (addr - RAM_BASE) // 4


def _read_syms(path: str) -> dict[str, int]:
    """Parse a `riscv64-elf-nm` dump into {symbol: byte_addr}.

    Format: `<8-hex-addr> <type> <name>`. We only keep the symbols we
    actually care about — saves a couple thousand .S-internal labels."""
    wanted = {"begin_signature", "end_signature", "done_marker"}
    out: dict[str, int] = {}
    with open(path) as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 3:
                continue
            addr_s, _kind, name = parts[0], parts[1], parts[2]
            if name in wanted:
                out[name] = int(addr_s, 16)
    missing = wanted - out.keys()
    if missing:
        raise RuntimeError(f"symbols missing from {path}: {missing}")
    return out


def _load_vmem(dut, path: str) -> int:
    """Poke the Verilator-backed RAM word-by-word from the vmem file.
    Same approach as `tests/cocotb_tests/test_timer_isr.py:_load_vmem`."""
    count = 0
    with open(path) as fh:
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


def _read_word(dut, byte_addr: int) -> int:
    return int(dut.u_ram.u_ram.mem[_byte_to_idx(byte_addr)].value)


@cocotb.test()
async def run_arch_test(dut) -> None:
    vmem_path     = os.environ["VMEM_PATH"]
    syms_path     = os.environ["SYMS_PATH"]
    signature_out = os.environ["SIGNATURE_OUT"]
    timeout_cycles = int(os.environ.get("TIMEOUT_CYCLES", "1000000"))

    syms = _read_syms(syms_path)
    sig_begin = syms["begin_signature"]
    sig_end   = syms["end_signature"]
    done      = syms["done_marker"]

    dut._log.info(
        f"arch test layout: begin_signature={sig_begin:#x} "
        f"end_signature={sig_end:#x} done_marker={done:#x}"
    )

    # 10 ns clock (100 MHz). Drive continuously.
    cocotb.start_soon(Clock(dut.IO_CLK, 10, units="ns").start())

    # PLIC sources tied off — the rv32i_m/{I,M,C} suites don't touch
    # the interrupt path.
    dut.ext_irq_sources_i.value = 0

    # Async active-low reset: clean 1→0 edge, hold low while we load.
    dut.IO_RST_N.value = 1
    await RisingEdge(dut.IO_CLK)
    dut.IO_RST_N.value = 0
    await RisingEdge(dut.IO_CLK)

    loaded = _load_vmem(dut, vmem_path)
    dut._log.info(f"loaded {loaded} words from {vmem_path}")

    for _ in range(5):
        await RisingEdge(dut.IO_CLK)
    dut.IO_RST_N.value = 1

    # Poll `done_marker` for the RVMODEL_HALT sentinel. The largest
    # tests in the C suite execute ~600K cycles end-to-end on
    # Verilator; 1M cycles default is a comfortable margin.
    for cycle in range(timeout_cycles):
        await RisingEdge(dut.IO_CLK)
        if _read_word(dut, done) == 0xFEEDFACE:
            dut._log.info(f"done_marker hit at cycle {cycle}")
            break
    else:
        # Timeout — surface enough state to triage.
        try:
            pc = int(dut.u_ibex.u_ibex_top.u_ibex_core.if_stage_i.pc_id_o.value)
        except Exception:
            pc = -1
        raise AssertionError(
            f"arch test never wrote done_marker after {timeout_cycles} "
            f"cycles; last pc_id={pc:#x} done_marker={_read_word(dut, done):#x}"
        )

    # Dump the signature region.
    n_words = (sig_end - sig_begin) // 4
    if n_words <= 0:
        raise AssertionError(
            f"empty signature region: begin={sig_begin:#x} end={sig_end:#x}"
        )
    Path(signature_out).parent.mkdir(parents=True, exist_ok=True)
    with open(signature_out, "w") as fh:
        for i in range(n_words):
            word = _read_word(dut, sig_begin + 4 * i)
            fh.write(f"{word:08x}\n")
    dut._log.info(
        f"signature: {n_words} words written to {signature_out}"
    )
