"""Standalone unit-test for the ARCH-emitted `ibex_counter` (basic suite).

Builds Verilator on `build/ibex_counter.sv` standalone (with parameters
`CounterWidth = 32` and `ProvideValUpd = 1` — the most common
combination) and runs the `test_ibex_counter_unit` cocotb module
against it. Coverage maps to the Requirements in
`specs/counter/spec.md`, one cocotb test per Requirement.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"
COUNTER_SV = REPO_ROOT / "build" / "ibex_counter.sv"


pytest.importorskip("cocotb_tools.runner")


@pytest.fixture(scope="module")
def counter_runner(verilator_bin, tmp_path_factory):
    """Build a standalone Verilator model of `ibex_counter` once per
    session, with CounterWidth = 32 and ProvideValUpd = 1.
    """
    from cocotb_tools.runner import get_runner

    if not COUNTER_SV.is_file():
        pytest.skip(f"missing {COUNTER_SV}; run `make build` first")

    sim_build = tmp_path_factory.mktemp("counter_sim_build")
    runner = get_runner("verilator")
    runner.build(
        sources=[str(COUNTER_SV)],
        hdl_toplevel="ibex_counter",
        build_dir=str(sim_build),
        always=True,
        parameters={"CounterWidth": 32, "ProvideValUpd": 1},
        build_args=[
            "--public-flat-rw",
            "-Wno-fatal",
            "-Wno-UNUSEDSIGNAL",
            "-Wno-UNUSEDPARAM",
            "-Wno-WIDTHEXPAND",
        ],
    )
    return runner, sim_build


def test_ibex_counter_unit(counter_runner, tmp_path):
    runner, sim_build = counter_runner
    results_xml = runner.test(
        test_module="test_ibex_counter_unit",
        hdl_toplevel="ibex_counter",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_counter_unit.xml"),
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
