"""Standalone unit-test for the ARCH-emitted `ibex_wb_stage` (basic suite).

Builds Verilator on `build/ibex_wb_stage.sv` standalone with the in-scope
parameter set (WritebackStage=0, DummyInstructions=0, ResetAll=0) and runs
the `test_wb_stage_unit` cocotb module against it.

Coverage maps to the Requirements in
`changes/port-wb_stage/specs/wb_stage/spec.md`, one cocotb test per
Requirement (9 Requirements, 16 test functions in basic suite).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"
WB_SV = REPO_ROOT / "build" / "ibex_wb_stage.sv"


pytest.importorskip("cocotb_tools.runner")


@pytest.fixture(scope="module")
def wb_runner(verilator_bin, tmp_path_factory):
    """Build a standalone Verilator model of `ibex_wb_stage` once per session,
    with the in-scope parameter set:
      - WritebackStage    = 0  (passthrough mode — purely combinational)
      - DummyInstructions = 0
      - ResetAll          = 0
    """
    from cocotb_tools.runner import get_runner

    if not WB_SV.is_file():
        pytest.skip(f"missing {WB_SV}; run `make build` first")

    sim_build = tmp_path_factory.mktemp("wb_sim_build")
    runner = get_runner("verilator")
    runner.build(
        sources=[str(WB_SV)],
        hdl_toplevel="ibex_wb_stage",
        build_dir=str(sim_build),
        always=True,
        parameters={
            "WritebackStage":    0,
            "DummyInstructions": 0,
            "ResetAll":          0,
        },
        build_args=[
            "--public-flat-rw",
            "-Wno-fatal",
            "-Wno-UNUSEDSIGNAL",
            "-Wno-UNUSEDPARAM",
            "-Wno-WIDTHEXPAND",
        ],
    )
    return runner, sim_build


def test_wb_stage_unit(wb_runner, tmp_path):
    runner, sim_build = wb_runner
    results_xml = runner.test(
        test_module="test_wb_stage_unit",
        hdl_toplevel="ibex_wb_stage",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_wb_stage_unit.xml"),
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
