"""Standalone unit-test for the ARCH-emitted `ibex_ex_block` (basic suite).

Builds Verilator on `build/ibex_ex_block.sv` (the ex_block must include
*both* the ALU and the multdiv sub-modules, since the combinational
cross-coupling loop between them resolves only within the combined netlist)
and runs the `test_ibex_ex_block_unit` cocotb module against it.

Coverage maps to the Requirements in
`changes/port-ex_block/specs/ex_block/spec.md`, one cocotb test per
Requirement.

Fixed parameters:
  - RV32M = 2  (RV32MFast)
  - RV32B = 0  (RV32BNone)
  - BranchTargetALU = 0 (no dedicated branch-target adder)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"
BUILD_DIR = REPO_ROOT / "build"
EX_BLOCK_SV = BUILD_DIR / "ibex_ex_block.sv"
# The ex_block instantiates both sub-modules; Verilator needs all three SV files.
ALU_SV = BUILD_DIR / "ibex_alu.sv"
MULTDIV_FAST_SV = BUILD_DIR / "ibex_multdiv_fast.sv"


pytest.importorskip("cocotb_tools.runner")


@pytest.fixture(scope="module")
def ex_block_runner(verilator_bin, tmp_path_factory):
    """Build a standalone Verilator model of `ibex_ex_block` once per
    session, with the in-scope parameter set:
      - RV32M = 2 (RV32MFast)
      - RV32B = 0 (RV32BNone)
      - BranchTargetALU = 0
    """
    from cocotb_tools.runner import get_runner

    for sv in [EX_BLOCK_SV, ALU_SV, MULTDIV_FAST_SV]:
        if not sv.is_file():
            pytest.skip(f"missing {sv}; run `make build` first")

    sim_build = tmp_path_factory.mktemp("ex_block_sim_build")
    runner = get_runner("verilator")
    runner.build(
        # The ex_block instantiates ibex_alu and ibex_multdiv_fast as
        # sub-modules; all three SV files must be passed to Verilator.
        sources=[str(ALU_SV), str(MULTDIV_FAST_SV), str(EX_BLOCK_SV)],
        hdl_toplevel="ibex_ex_block",
        build_dir=str(sim_build),
        always=True,
        parameters={
            "RV32M": 2,
            "RV32B": 0,
            "BranchTargetALU": 0,
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


def test_ex_block_unit(ex_block_runner, tmp_path):
    runner, sim_build = ex_block_runner
    results_xml = runner.test(
        test_module="test_ibex_ex_block_unit",
        hdl_toplevel="ibex_ex_block",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_ex_block_unit.xml"),
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
