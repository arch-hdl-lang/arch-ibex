"""Standalone unit-test for the ARCH-emitted `ibex_alu`.

Builds Verilator on `build/ibex_alu.sv` alone (no Ibex, no fusesoc) and
runs the `test_ibex_alu_unit` cocotb module against it. Coverage maps
to the requirements in `specs/alu/spec.md` — one test function per
requirement, walking representative scenarios with concrete numeric
values from the spec's Given/When/Then table.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"
ALU_SV = REPO_ROOT / "build" / "ibex_alu.sv"


pytest.importorskip("cocotb_tools.runner")


@pytest.fixture(scope="module")
def alu_runner(verilator_bin, tmp_path_factory):
    """Build a standalone Verilator model of `ibex_alu` once per session.

    No Ibex sources, no CLINT/PLIC — the module is purely combinational
    and self-contained, so the build is a one-file invocation.
    """
    from cocotb_tools.runner import get_runner

    if not ALU_SV.is_file():
        pytest.skip(f"missing {ALU_SV}; run `make build` first")

    sim_build = tmp_path_factory.mktemp("alu_sim_build")
    runner = get_runner("verilator")
    runner.build(
        sources=[str(ALU_SV)],
        hdl_toplevel="ibex_alu",
        build_dir=str(sim_build),
        always=True,
        build_args=[
            "--public-flat-rw",
            "-Wno-fatal",
            "-Wno-UNUSEDSIGNAL",
            "-Wno-WIDTHEXPAND",
        ],
    )
    return runner, sim_build


def test_ibex_alu_unit(alu_runner, tmp_path):
    runner, sim_build = alu_runner
    results_xml = runner.test(
        test_module="test_ibex_alu_unit",
        hdl_toplevel="ibex_alu",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_alu_unit.xml"),
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
