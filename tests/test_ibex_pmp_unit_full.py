"""Standalone full-regression unit-test for the ARCH-emitted `ibex_pmp`.

Builds Verilator on `build/ibex_pmp.sv` standalone with the in-scope
parameter overrides (`DmBaseAddr=0`, `DmAddrMask=3`, `PMPGranularity=0`,
`PMPNumChan=3`, `PMPNumRegions=4`) and runs the
`test_ibex_pmp_unit_full` cocotb module against it.

Covers every Scenario S1..S10 from the spec, ≥4 cross-scenario
integration tests, and edge-case sweeps (mode permutations, full
L/R/W/X truth tables under MML and non-MML, reserved encodings,
boundary widths).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"
PMP_SV = REPO_ROOT / "build" / "ibex_pmp.sv"


pytest.importorskip("cocotb_tools.runner")


@pytest.fixture(scope="module")
def pmp_full_runner(verilator_bin, tmp_path_factory):
    """Build a standalone Verilator model of `ibex_pmp` once per session,
    with the in-scope parameter set:
      - DmBaseAddr     = 0
      - DmAddrMask     = 3
      - PMPGranularity = 0
      - PMPNumChan     = 3
      - PMPNumRegions  = 4
    """
    from cocotb_tools.runner import get_runner

    if not PMP_SV.is_file():
        pytest.skip(f"missing {PMP_SV}; run `make build` first")

    sim_build = tmp_path_factory.mktemp("pmp_full_sim_build")
    runner = get_runner("verilator")
    runner.build(
        sources=[str(PMP_SV)],
        hdl_toplevel="ibex_pmp",
        build_dir=str(sim_build),
        always=True,
        parameters={
            "DmBaseAddr": 0,
            "DmAddrMask": 3,
            "PMPGranularity": 0,
            "PMPNumChan": 3,
            "PMPNumRegions": 4,
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


def test_ibex_pmp_unit_full(pmp_full_runner, tmp_path):
    runner, sim_build = pmp_full_runner
    results_xml = runner.test(
        test_module="test_ibex_pmp_unit_full",
        hdl_toplevel="ibex_pmp",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_pmp_unit_full.xml"),
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
