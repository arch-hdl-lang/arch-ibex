"""Standalone unit-test for the ARCH-emitted `ibex_multdiv_fast`
(full regression).

Builds Verilator on `build/ibex_multdiv_fast.sv` standalone with the
in-scope parameter override (`RV32M = 2` = RV32MFast) and runs the
`test_ibex_multdiv_fast_unit_full` cocotb module against it. Walks
every spec scenario plus operand sweeps, divide-by-zero and signed-
overflow edges, both data-independent timing modes, back-to-back FSM
transitions, and ID-stage backpressure.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"
MULTDIV_FAST_SV = REPO_ROOT / "build" / "ibex_multdiv_fast.sv"


pytest.importorskip("cocotb_tools.runner")


@pytest.fixture(scope="module")
def multdiv_fast_full_runner(verilator_bin, tmp_path_factory):
    from cocotb_tools.runner import get_runner

    if not MULTDIV_FAST_SV.is_file():
        pytest.skip(
            f"missing {MULTDIV_FAST_SV}; run `make build` first"
        )

    sim_build = tmp_path_factory.mktemp("multdiv_fast_full_sim_build")
    runner = get_runner("verilator")
    runner.build(
        sources=[str(MULTDIV_FAST_SV)],
        hdl_toplevel="ibex_multdiv_fast",
        build_dir=str(sim_build),
        always=True,
        parameters={
            "RV32M": 2,
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


def test_ibex_multdiv_fast_unit_full(multdiv_fast_full_runner, tmp_path):
    runner, sim_build = multdiv_fast_full_runner
    results_xml = runner.test(
        test_module="test_ibex_multdiv_fast_unit_full",
        hdl_toplevel="ibex_multdiv_fast",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_multdiv_fast_unit_full.xml"),
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
