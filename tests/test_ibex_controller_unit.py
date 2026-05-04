"""Standalone unit-test for the ARCH-emitted `ibex_controller` (basic suite).

Builds Verilator on `build/ibex_controller.sv` (leaf-shaped: no
sub-instances) and runs the `test_ibex_controller_unit` cocotb module
against it.

Coverage maps to the Requirements in
`changes/port-controller/specs/controller/spec.md`, one cocotb test per
Requirement (12 tests total).

Fixed parameters (matching `ibex_top.sv` defaults under the SoC's
`mini_soc.sv` pinning):
  - WritebackStage  = 0
  - BranchPredictor = 0
  - MemECC          = 0
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"
BUILD_DIR = REPO_ROOT / "build"
CONTROLLER_SV = BUILD_DIR / "ibex_controller.sv"


pytest.importorskip("cocotb_tools.runner")


@pytest.fixture(scope="module")
def controller_runner(verilator_bin, tmp_path_factory):
    """Build a standalone Verilator model of `ibex_controller` once per session."""
    from cocotb_tools.runner import get_runner

    if not CONTROLLER_SV.is_file():
        pytest.skip(f"missing {CONTROLLER_SV}; run `make build` first")

    sim_build = tmp_path_factory.mktemp("controller_sim_build")
    runner = get_runner("verilator")
    runner.build(
        sources=[str(CONTROLLER_SV)],
        hdl_toplevel="ibex_controller",
        build_dir=str(sim_build),
        always=True,
        parameters={
            "WritebackStage":  0,
            "BranchPredictor": 0,
            "MemECC":          0,
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


def test_ibex_controller_unit(controller_runner, tmp_path):
    runner, sim_build = controller_runner
    results_xml = runner.test(
        test_module="test_ibex_controller_unit",
        hdl_toplevel="ibex_controller",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_controller_unit.xml"),
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
