"""Standalone unit-test for the ARCH-emitted `ibex_load_store_unit`
(basic suite).

Builds Verilator on `build/ibex_load_store_unit.sv` standalone with the
in-scope parameter override (`MemECC = 0`, implying `MemDataWidth = 32`)
and runs the `test_load_store_unit_unit` cocotb module against it.
Coverage maps to the Requirements in
`changes/port-load_store_unit/specs/load_store_unit/spec.md`, one cocotb
test per Requirement (13 tests).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"
LSU_SV = REPO_ROOT / "build" / "ibex_load_store_unit.sv"


pytest.importorskip("cocotb_tools.runner")


@pytest.fixture(scope="module")
def lsu_runner(verilator_bin, tmp_path_factory):
    """Build a standalone Verilator model of `ibex_load_store_unit` once
    per session, with the in-scope parameter set:
      - MemECC = 0  (MemDataWidth = 32 implied)
    """
    from cocotb_tools.runner import get_runner

    if not LSU_SV.is_file():
        pytest.skip(f"missing {LSU_SV}; run `make build` first")

    sim_build = tmp_path_factory.mktemp("lsu_sim_build")
    runner = get_runner("verilator")
    runner.build(
        sources=[str(LSU_SV)],
        hdl_toplevel="ibex_load_store_unit",
        build_dir=str(sim_build),
        always=True,
        parameters={
            "MemECC": 0,
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


def test_load_store_unit_unit(lsu_runner, tmp_path):
    runner, sim_build = lsu_runner
    results_xml = runner.test(
        test_module="test_load_store_unit_unit",
        hdl_toplevel="ibex_load_store_unit",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_load_store_unit_unit.xml"),
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
