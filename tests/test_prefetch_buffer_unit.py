"""Standalone unit-test for the ARCH-emitted `ibex_prefetch_buffer` (basic suite).

Builds Verilator on `build/ibex_prefetch_buffer.sv` (which internally
instantiates `ibex_fetch_fifo`, so both source files are compiled together)
and runs the `test_prefetch_buffer_unit` cocotb module against it.

Coverage maps to the Requirements in
`changes/port-prefetch_buffer/specs/prefetch_buffer/spec.md`, one cocotb
test per Requirement (10 tests).

The build compiles both `ibex_prefetch_buffer.sv` and `ibex_fetch_fifo.sv`
so Verilator can resolve the internally instantiated submodule. The top
module under simulation is `ibex_prefetch_buffer`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"
PREFETCH_BUFFER_SV = REPO_ROOT / "build" / "ibex_prefetch_buffer.sv"
FETCH_FIFO_SV = REPO_ROOT / "build" / "ibex_fetch_fifo.sv"


pytest.importorskip("cocotb_tools.runner")


@pytest.fixture(scope="module")
def prefetch_buffer_runner(verilator_bin, tmp_path_factory):
    """Build a standalone Verilator model of `ibex_prefetch_buffer` once per
    session, including the `ibex_fetch_fifo` submodule that it instantiates
    internally.
    """
    from cocotb_tools.runner import get_runner

    if not PREFETCH_BUFFER_SV.is_file():
        pytest.skip(f"missing {PREFETCH_BUFFER_SV}; run `make build` first")
    if not FETCH_FIFO_SV.is_file():
        pytest.skip(f"missing {FETCH_FIFO_SV}; run `make build` first")

    sim_build = tmp_path_factory.mktemp("prefetch_buffer_sim_build")
    runner = get_runner("verilator")
    runner.build(
        sources=[str(PREFETCH_BUFFER_SV), str(FETCH_FIFO_SV)],
        hdl_toplevel="ibex_prefetch_buffer",
        build_dir=str(sim_build),
        always=True,
        parameters={
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


def test_prefetch_buffer_unit(prefetch_buffer_runner, tmp_path):
    runner, sim_build = prefetch_buffer_runner
    results_xml = runner.test(
        test_module="test_prefetch_buffer_unit",
        hdl_toplevel="ibex_prefetch_buffer",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_prefetch_buffer_unit.xml"),
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
