"""Full-regression unit-test for the ARCH-emitted `ibex_core`.

Walks every basic-suite Requirement plus the testable Caller-side
(CS-1 through CS-10) and Producer-side (PS-1 through PS-13) rules,
plus extended scenarios for each Given/When/Then in the spec. Runs
as a separate pytest collector so xdist can parallelise it across
files.
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

# ── Mirror the basic collector's file list. Keep them in sync.
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
# D1: IbexIfStage now `inst`s `ibex_icache` — link the icache + 5 subs.
ICACHE_SV             = BUILD_DIR / "ibex_icache.sv"
FB_AGE_ARB_SV         = BUILD_DIR / "fb_age_arb.sv"
RAM_PORT_ARB_SV       = BUILD_DIR / "ram_port_arb.sv"
FILL_BUFFER_CAM_SV    = BUILD_DIR / "fill_buffer_cam.sv"
FILL_BUFFER_CTRL_SV   = BUILD_DIR / "fill_buffer_ctrl.sv"
INVAL_CTRL_SV         = BUILD_DIR / "inval_ctrl.sv"
PMP_SV                = BUILD_DIR / "ibex_pmp.sv"

IBEX_PKG_SV       = IBEX_ROOT / "rtl" / "ibex_pkg.sv"
CS_REGISTERS_SV   = IBEX_ROOT / "rtl" / "ibex_cs_registers.sv"
IBEX_CSR_SV       = IBEX_ROOT / "rtl" / "ibex_csr.sv"
PRIM_PKG_SV       = IBEX_ROOT / "vendor" / "lowrisc_ip" / "ip" / "prim_generic" / "rtl" / "prim_pkg.sv"
PRIM_BUF_SV       = IBEX_ROOT / "vendor" / "lowrisc_ip" / "ip" / "prim_generic" / "rtl" / "prim_buf.sv"
PRIM_CLOCK_GATING = IBEX_ROOT / "vendor" / "lowrisc_ip" / "ip" / "prim_generic" / "rtl" / "prim_clock_gating.sv"


ARCH_SV_FILES = [
    SHARED_PKG_SV,
    COUNTER_SV,
    DECODER_SV,
    CONTROLLER_SV,
    ALU_SV,
    MULTDIV_FAST_SV,
    FETCH_FIFO_SV,
    PREFETCH_BUFFER_SV,
    COMPRESSED_DECODER_SV,
    # D1: icache + sub-constructs (linked into IbexIfStage when ICache=1).
    FB_AGE_ARB_SV,
    RAM_PORT_ARB_SV,
    FILL_BUFFER_CAM_SV,
    FILL_BUFFER_CTRL_SV,
    INVAL_CTRL_SV,
    ICACHE_SV,
    PMP_SV,
    ID_STAGE_SV,
    EX_BLOCK_SV,
    LSU_SV,
    WB_STAGE_SV,
    IF_STAGE_SV,
    CORE_SV,
]

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
def core_full_runner(verilator_bin, tmp_path_factory):
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

    sim_build = tmp_path_factory.mktemp("core_full_sim_build")
    runner = get_runner("verilator")
    runner.build(
        # ibex_pkg.sv must come before any consumer using its enum
        # types in parameter declarations — IbexCore.arch declares
        # `param RV32M: ibex_pkg::rv32m_e = ...` natively (per
        # arch-com PR #286), so Verilator needs the package parsed
        # first.
        sources=[str(p) for p in (UPSTREAM_SV_FILES + ARCH_SV_FILES)],
        hdl_toplevel="ibex_core",
        build_dir=str(sim_build),
        always=True,
        parameters={
            "RV32E":              0,
            # RV32M / RV32B are enum-typed — defaults match SoC pinning;
            # passing int via -G implicit-converts and trips ENUMVALUE.
            "BranchTargetALU":    0,
            "WritebackStage":     0,
            "ICache":             0,
            "BranchPredictor":    0,
            "DbgTriggerEn":       0,
            "MemECC":             0,
            "DataIndTiming":      0,
            "DummyInstructions":  0,
            "PMPEnable":          1,
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


def test_ibex_core_unit_full(core_full_runner, tmp_path):
    runner, sim_build = core_full_runner
    results_xml = runner.test(
        test_module="test_ibex_core_unit_full",
        hdl_toplevel="ibex_core",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_core_unit_full.xml"),
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
