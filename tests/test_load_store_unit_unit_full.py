"""Full-regression unit-test for the ARCH-emitted `ibex_load_store_unit`.

Builds Verilator on `build/ibex_load_store_unit.sv` once with the
in-scope parameter set (`MemECC = 0`, implying `MemDataWidth = 32`) and
runs the `test_load_store_unit_unit_full` cocotb module against it. The
full suite covers every Scenario from the spec plus edge cases:
  - All access types × all byte offsets for byte-enables.
  - All access types × all offsets for write-data rotation.
  - All byte offsets for load data extraction (signed and unsigned).
  - Misaligned halfword and word accesses.
  - Delayed grant (gnt arrives 2 cycles after req).
  - Bus error on load, bus error on store.
  - PMP error on store.
  - Reset in the middle of a transaction.

Skipped wholesale if `build/ibex_load_store_unit.sv` is missing.
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
def _verilator():
    """Pre-flight: skip the whole module if the SV file is missing."""
    if not LSU_SV.is_file():
        pytest.skip(f"missing {LSU_SV}; run `make build` first")


def test_load_store_unit_unit_full(
    _verilator,
    verilator_bin,
    tmp_path_factory,
    tmp_path,
):
    from cocotb_tools.runner import get_runner

    sim_build = tmp_path_factory.mktemp("lsu_full_sim_build")
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
    results_xml = runner.test(
        test_module="test_load_store_unit_unit_full",
        hdl_toplevel="ibex_load_store_unit",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_load_store_unit_unit_full.xml"),
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
