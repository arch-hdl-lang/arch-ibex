"""Standalone unit-test for the ARCH-emitted `ibex_id_stage` (basic suite).

Builds Verilator on `build/ibex_id_stage.sv` (composite: instantiates
`ibex_decoder` and `ibex_controller` as sub-modules) and runs the
`test_ibex_id_stage_unit` cocotb module against it.

Coverage maps to the Requirements in
`changes/port-id_stage/specs/id_stage/spec.md`, one cocotb test per
Requirement (16 tests total).

Fixed parameters (matching `ibex_top.sv` defaults under the SoC's
`ibex_mini_soc.sv` pinning):
  - RV32E           = 0
  - RV32M           = 2 (RV32MFast)
  - RV32B           = 0 (RV32BNone)
  - BranchTargetALU = 0
  - WritebackStage  = 0
  - BranchPredictor = 0
  - DataIndTiming   = 0
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

# id_stage instantiates decoder + controller. Both consumer SVs
# `import IbexCoreSharedPkg::*;`, so the shared-types package SV must
# be linked first (Verilator needs `package <Name>` declared before any
# `import <Name>::*;`).
SHARED_PKG_SV = BUILD_DIR / "ibex_core_shared_pkg.sv"
ID_STAGE_SV   = BUILD_DIR / "ibex_id_stage.sv"
DECODER_SV    = BUILD_DIR / "ibex_decoder.sv"
CONTROLLER_SV = BUILD_DIR / "ibex_controller.sv"


pytest.importorskip("cocotb_tools.runner")


@pytest.fixture(scope="module")
def id_stage_runner(verilator_bin, tmp_path_factory):
    """Build a standalone Verilator model of `ibex_id_stage` once per session."""
    from cocotb_tools.runner import get_runner

    for sv in [SHARED_PKG_SV, ID_STAGE_SV, DECODER_SV, CONTROLLER_SV]:
        if not sv.is_file():
            pytest.skip(f"missing {sv}; run `make build` first")

    sim_build = tmp_path_factory.mktemp("id_stage_sim_build")
    runner = get_runner("verilator")
    runner.build(
        sources=[str(SHARED_PKG_SV), str(DECODER_SV), str(CONTROLLER_SV), str(ID_STAGE_SV)],
        hdl_toplevel="ibex_id_stage",
        build_dir=str(sim_build),
        always=True,
        parameters={
            "RV32E":           0,
            "RV32M":           2,
            "RV32B":           0,
            "BranchTargetALU": 0,
            "WritebackStage":  0,
            "BranchPredictor": 0,
            "DataIndTiming":   0,
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


def test_ibex_id_stage_unit(id_stage_runner, tmp_path):
    runner, sim_build = id_stage_runner
    results_xml = runner.test(
        test_module="test_ibex_id_stage_unit",
        hdl_toplevel="ibex_id_stage",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_id_stage_unit.xml"),
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
