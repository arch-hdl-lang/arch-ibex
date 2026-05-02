"""Full-regression unit-test for the ARCH-emitted `ibex_prefetch_buffer`.

Builds Verilator on `build/ibex_prefetch_buffer.sv` and
`build/ibex_fetch_fifo.sv` (the internally instantiated submodule) and
runs the `test_prefetch_buffer_unit_full` cocotb module against it.

The full regression covers every Scenario from
`changes/port-prefetch_buffer/specs/prefetch_buffer/spec.md` plus the
edge cases enumerated in the test-author brief.

Skipped wholesale if either source SV file is missing.
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
def _verilator():
    """Pre-flight: skip the whole module if any SV file is missing."""
    if not PREFETCH_BUFFER_SV.is_file():
        pytest.skip(f"missing {PREFETCH_BUFFER_SV}; run `make build` first")
    if not FETCH_FIFO_SV.is_file():
        pytest.skip(f"missing {FETCH_FIFO_SV}; run `make build` first")


def test_prefetch_buffer_unit_full(
    _verilator,
    verilator_bin,
    tmp_path_factory,
    tmp_path,
):
    from cocotb_tools.runner import get_runner

    sim_build = tmp_path_factory.mktemp("prefetch_buffer_full_sim_build")
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
    results_xml = runner.test(
        test_module="test_prefetch_buffer_unit_full",
        hdl_toplevel="ibex_prefetch_buffer",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_prefetch_buffer_unit_full.xml"),
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
