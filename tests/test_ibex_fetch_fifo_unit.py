"""Standalone unit-test for the ARCH-emitted `ibex_fetch_fifo` (basic suite).

Builds Verilator on `build/ibex_fetch_fifo.sv` standalone with the
in-scope parameter overrides (`NUM_REQS = 2`, `ResetAll = 0`) and runs
the `test_ibex_fetch_fifo_unit` cocotb module against it. Coverage maps
to the Requirements in
`changes/port-fetch_fifo/specs/fetch_fifo/spec.md`, one cocotb test per
Requirement (7 tests).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"
FETCH_FIFO_SV = REPO_ROOT / "build" / "ibex_fetch_fifo.sv"


pytest.importorskip("cocotb_tools.runner")


@pytest.fixture(scope="module")
def fetch_fifo_runner(verilator_bin, tmp_path_factory):
    """Build a standalone Verilator model of `ibex_fetch_fifo` once per
    session, with the in-scope parameter set:
      - NUM_REQS = 2 (DEPTH = 3)
      - ResetAll = 0
    """
    from cocotb_tools.runner import get_runner

    if not FETCH_FIFO_SV.is_file():
        pytest.skip(f"missing {FETCH_FIFO_SV}; run `make build` first")

    sim_build = tmp_path_factory.mktemp("fetch_fifo_sim_build")
    runner = get_runner("verilator")
    runner.build(
        sources=[str(FETCH_FIFO_SV)],
        hdl_toplevel="ibex_fetch_fifo",
        build_dir=str(sim_build),
        always=True,
        parameters={
            "NUM_REQS": 2,
            "ResetAll": 0,
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


def test_ibex_fetch_fifo_unit(fetch_fifo_runner, tmp_path):
    runner, sim_build = fetch_fifo_runner
    results_xml = runner.test(
        test_module="test_ibex_fetch_fifo_unit",
        hdl_toplevel="ibex_fetch_fifo",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_fetch_fifo_unit.xml"),
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
