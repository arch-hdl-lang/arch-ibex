"""Full regression suite for the ARCH-emitted `ibex_if_stage`.

Builds Verilator on `build/ibex_if_stage.sv` (with the same sub-module
file list as the basic suite) and runs the
`test_ibex_if_stage_unit_full` cocotb module, which covers every
`#### Scenario:` from the spec plus boundary / edge cases.

A separate fixture is used so `pytest -n auto --dist=loadfile` can
parallelize the basic and full suites.

Fixed parameters (matching the SoC's `ibex_mini_soc.sv` pinning):
  - ICache            = 0
  - BranchPredictor   = 0
  - DummyInstructions = 0
  - MemECC            = 0
  - PCIncrCheck       = 0
  - ResetAll          = 0
  - RV32ZC            = 3 (RV32ZcaZcbZcmp)
  - DmHaltAddr        = 0x1A11_0800
  - DmExceptionAddr   = 0x1A11_0808
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"
BUILD_DIR = REPO_ROOT / "build"
SHARED_PKG_SV         = BUILD_DIR / "ibex_core_shared_pkg.sv"
IF_STAGE_SV           = BUILD_DIR / "ibex_if_stage.sv"
PREFETCH_BUFFER_SV    = BUILD_DIR / "ibex_prefetch_buffer.sv"
FETCH_FIFO_SV         = BUILD_DIR / "ibex_fetch_fifo.sv"
COMPRESSED_DECODER_SV = BUILD_DIR / "ibex_compressed_decoder.sv"
# D1: IbexIfStage now `inst`s `ibex_icache` (replaces prefetch_buffer).
ICACHE_SV             = BUILD_DIR / "ibex_icache.sv"
FB_AGE_ARB_SV         = BUILD_DIR / "fb_age_arb.sv"
RAM_PORT_ARB_SV       = BUILD_DIR / "ram_port_arb.sv"
INVAL_CTRL_SV         = BUILD_DIR / "inval_ctrl.sv"
ICACHE_OUTPUT_STAGE_SV = BUILD_DIR / "ibex_icache_output_stage.sv"


pytest.importorskip("cocotb_tools.runner")


@pytest.fixture(scope="module")
def if_stage_full_runner(verilator_bin, tmp_path_factory):
    """Build a standalone Verilator model of `ibex_if_stage` once per
    session for the full regression suite."""
    from cocotb_tools.runner import get_runner

    needed = [SHARED_PKG_SV, IF_STAGE_SV, PREFETCH_BUFFER_SV, FETCH_FIFO_SV,
              COMPRESSED_DECODER_SV, ICACHE_SV, FB_AGE_ARB_SV, RAM_PORT_ARB_SV,
              INVAL_CTRL_SV, ICACHE_OUTPUT_STAGE_SV]
    for sv in needed:
        if not sv.is_file():
            pytest.skip(f"missing {sv}; run `make build` first")

    sim_build = tmp_path_factory.mktemp("if_stage_full_sim_build")
    runner = get_runner("verilator")
    runner.build(
        sources=[
            str(SHARED_PKG_SV),
            str(FETCH_FIFO_SV),
            str(PREFETCH_BUFFER_SV),
            str(COMPRESSED_DECODER_SV),
            # D1: icache + sub-constructs (linked into IfStage when ICache=1).
            str(FB_AGE_ARB_SV),
            str(RAM_PORT_ARB_SV),
            str(INVAL_CTRL_SV),
            str(ICACHE_OUTPUT_STAGE_SV),
            str(ICACHE_SV),
            str(IF_STAGE_SV),
        ],
        hdl_toplevel="ibex_if_stage",
        build_dir=str(sim_build),
        always=True,
        parameters={
            "ICache":            0,
            "BranchPredictor":   0,
            "DummyInstructions": 0,
            "MemECC":            0,
            "PCIncrCheck":       0,
            "ResetAll":          0,
            "RV32ZC":            3,
            "DmHaltAddr":        0x1A110800,
            "DmExceptionAddr":   0x1A110808,
        },
        build_args=[
            "--public-flat-rw",
            "-Wno-fatal",
            "-Wno-UNUSEDSIGNAL",
            "-Wno-UNUSEDPARAM",
            "-Wno-WIDTHEXPAND",
            "-Wno-UNOPTFLAT",
        ],
    )
    return runner, sim_build


def test_ibex_if_stage_unit_full(if_stage_full_runner, tmp_path):
    runner, sim_build = if_stage_full_runner
    results_xml = runner.test(
        test_module="test_ibex_if_stage_unit_full",
        hdl_toplevel="ibex_if_stage",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_if_stage_unit_full.xml"),
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
