"""Standalone unit-test for the ARCH-emitted `ibex_core` (basic suite).

Builds Verilator on `build/ibex_core.sv` (the C1 swap, a `pipeline`
containing five sub-module `inst`s) plus all the ARCH-emitted swaps
that those sub-modules need (IF, ID, EX, LSU, WB and their nested
sub-instances), plus the upstream-SV `ibex_cs_registers` and its
dependency chain.

Coverage maps to the Requirements in
`changes/port-ibex_core/specs/ibex_core/spec.md`, one cocotb test per
Requirement (21 tests total).

Fixed parameters (matching `ibex_top.sv` defaults under the SoC's
`ibex_mini_soc.sv` pinning):
  - RV32E              = 0
  - RV32M              = 2 (RV32MFast)
  - RV32B              = 0 (RV32BNone)
  - BranchTargetALU    = 0
  - WritebackStage     = 0
  - ICache             = 0
  - BranchPredictor    = 0
  - DbgTriggerEn       = 0
  - MemECC             = 0
  - DataIndTiming      = 0
  - DummyInstructions  = 0
  - PMPEnable          = 0
  - SecureIbex         = 0
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"
BUILD_DIR = REPO_ROOT / "build"

IBEX_ROOT = Path(os.environ.get("IBEX_ROOT", str(Path.home() / "github" / "ibex")))

# ── ARCH-emitted swaps. Package SV must be linked first (B5 lesson).
SHARED_PKG_SV         = BUILD_DIR / "ibex_core_shared_pkg.sv"
CORE_SV               = BUILD_DIR / "ibex_core.sv"
IF_STAGE_SV           = BUILD_DIR / "ibex_if_stage.sv"
ID_STAGE_SV           = BUILD_DIR / "ibex_id_stage.sv"
DECODER_SV            = BUILD_DIR / "ibex_decoder.sv"
CONTROLLER_SV         = BUILD_DIR / "ibex_controller.sv"
EX_BLOCK_SV           = BUILD_DIR / "ibex_ex_block.sv"
ALU_SV                = BUILD_DIR / "ibex_alu.sv"
MULTDIV_FAST_SV       = BUILD_DIR / "ibex_multdiv_fast.sv"
LSU_SV                = BUILD_DIR / "ibex_load_store_unit.sv"
WB_STAGE_SV           = BUILD_DIR / "ibex_wb_stage.sv"
PREFETCH_BUFFER_SV    = BUILD_DIR / "ibex_prefetch_buffer.sv"
FETCH_FIFO_SV         = BUILD_DIR / "ibex_fetch_fifo.sv"
COMPRESSED_DECODER_SV = BUILD_DIR / "ibex_compressed_decoder.sv"
COUNTER_SV            = BUILD_DIR / "ibex_counter.sv"

# ── Upstream-SV dependencies for `ibex_cs_registers` (kept upstream-SV
# per spec note N-2). The CSR file imports `ibex_pkg::*` and
# instantiates `ibex_csr` plus `prim_buf` (via the ibex_csr's wrapper).
# `prim_clock_gating` is required for the `ibex_counter` module that
# the CSR file instantiates internally for performance counters.
IBEX_PKG_SV       = IBEX_ROOT / "rtl" / "ibex_pkg.sv"
CS_REGISTERS_SV   = IBEX_ROOT / "rtl" / "ibex_cs_registers.sv"
IBEX_CSR_SV       = IBEX_ROOT / "rtl" / "ibex_csr.sv"
PRIM_PKG_SV       = IBEX_ROOT / "vendor" / "lowrisc_ip" / "ip" / "prim_generic" / "rtl" / "prim_pkg.sv"
PRIM_BUF_SV       = IBEX_ROOT / "vendor" / "lowrisc_ip" / "ip" / "prim_generic" / "rtl" / "prim_buf.sv"
PRIM_CLOCK_GATING = IBEX_ROOT / "vendor" / "lowrisc_ip" / "ip" / "prim_generic" / "rtl" / "prim_clock_gating.sv"


# ── ARCH swap files in link order: package(s) first, then leaves
# (sub-instances), then composites (the stages and the top).
ARCH_SV_FILES = [
    SHARED_PKG_SV,
    # Leaves used by multiple stages.
    COUNTER_SV,
    # ID stage leaves.
    DECODER_SV,
    CONTROLLER_SV,
    # EX block leaves.
    ALU_SV,
    MULTDIV_FAST_SV,
    # IF stage leaves.
    FETCH_FIFO_SV,
    PREFETCH_BUFFER_SV,
    COMPRESSED_DECODER_SV,
    # Stages.
    ID_STAGE_SV,
    EX_BLOCK_SV,
    LSU_SV,
    WB_STAGE_SV,
    IF_STAGE_SV,
    # Top.
    CORE_SV,
]

# ── Upstream-SV files in link order: ibex_pkg first, then prim deps,
# then the CSR file. These are best-effort — see tests-inventory.md
# for known gaps.
UPSTREAM_SV_FILES = [
    IBEX_PKG_SV,
    PRIM_PKG_SV,
    PRIM_BUF_SV,
    PRIM_CLOCK_GATING,
    IBEX_CSR_SV,
    CS_REGISTERS_SV,
]


pytest.importorskip("cocotb_tools.runner")


@pytest.fixture(scope="module")
def core_runner(verilator_bin, tmp_path_factory):
    """Build a standalone Verilator model of `ibex_core` once per session."""
    from cocotb_tools.runner import get_runner

    for sv in ARCH_SV_FILES:
        if not sv.is_file():
            pytest.skip(f"missing {sv}; run `make build` first")
    for sv in UPSTREAM_SV_FILES:
        if not sv.is_file():
            pytest.skip(
                f"missing upstream SV {sv}; check IBEX_ROOT (= {IBEX_ROOT}) or "
                f"the lowrisc_ip vendor tree"
            )

    sim_build = tmp_path_factory.mktemp("core_sim_build")
    runner = get_runner("verilator")
    runner.build(
        # ibex_pkg.sv defines the SV-side enums (`rv32m_e`, `rv32b_e`)
        # that IbexCore now exposes natively as `parameter
        # ibex_pkg::rv32m_e RV32M = ...`, so the package must be parsed
        # before any consumer references it.
        sources=[str(p) for p in (UPSTREAM_SV_FILES + ARCH_SV_FILES)],
        hdl_toplevel="ibex_core",
        build_dir=str(sim_build),
        always=True,
        parameters={
            "RV32E":              0,
            # RV32M / RV32B are SV-typed enum params (`ibex_pkg::rv32m_e`,
            # `rv32b_e`) and default to RV32MFast / RV32BNone in
            # IbexCore.arch — passing integer overrides via -G would
            # implicit-convert into the enum type and trip Verilator's
            # ENUMVALUE error. The defaults already match the SoC pinning.
            "BranchTargetALU":    0,
            "WritebackStage":     0,
            "ICache":             0,
            "BranchPredictor":    0,
            "DbgTriggerEn":       0,
            "MemECC":             0,
            "DataIndTiming":      0,
            "DummyInstructions":  0,
            "PMPEnable":          0,
            "SecureIbex":         0,
        },
        build_args=[
            "--public-flat-rw",
            "-Wno-fatal",
            "-Wno-UNUSEDSIGNAL",
            "-Wno-UNUSEDPARAM",
            "-Wno-WIDTHEXPAND",
            "-Wno-UNOPTFLAT",
            "-Wno-PINCONNECTEMPTY",
            "-Wno-DECLFILENAME",
            f"-I{IBEX_ROOT}/vendor/lowrisc_ip/ip/prim/rtl",
        ],
    )
    return runner, sim_build


def test_ibex_core_unit(core_runner, tmp_path):
    runner, sim_build = core_runner
    results_xml = runner.test(
        test_module="test_ibex_core_unit",
        hdl_toplevel="ibex_core",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_core_unit.xml"),
    )
    tree = ET.parse(results_xml)
    root = tree.getroot()
    failures = (
        int(root.attrib.get("failures", "0"))
        + int(root.attrib.get("errors", "0"))
    )
    assert failures == 0, (
        f"cocotb reported {failures} failures; see {results_xml}"
    )
