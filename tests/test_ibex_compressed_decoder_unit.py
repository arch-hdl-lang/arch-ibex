"""Standalone unit-test for the ARCH-emitted `ibex_compressed_decoder`
(basic suite).

Builds Verilator on `build/ibex_compressed_decoder.sv` standalone with
the in-scope parameter overrides (`RV32ZC = 3` (RV32ZcaZcbZcmp),
`ResetAll = 0`) and runs the `test_ibex_compressed_decoder_unit`
cocotb module against it. Coverage maps to the Requirements in
`specs/compressed_decoder/spec.md`, one cocotb test per Requirement.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"
COMPRESSED_DECODER_SV = REPO_ROOT / "build" / "ibex_compressed_decoder.sv"


pytest.importorskip("cocotb_tools.runner")


@pytest.fixture(scope="module")
def compressed_decoder_runner(verilator_bin, tmp_path_factory):
    """Build a standalone Verilator model of `ibex_compressed_decoder`
    once per session, with the in-scope parameter set:
      - RV32ZC = 3 (RV32ZcaZcbZcmp)
      - ResetAll = 0
    """
    from cocotb_tools.runner import get_runner

    if not COMPRESSED_DECODER_SV.is_file():
        pytest.skip(
            f"missing {COMPRESSED_DECODER_SV}; run `make build` first"
        )

    sim_build = tmp_path_factory.mktemp("compressed_decoder_sim_build")
    runner = get_runner("verilator")
    runner.build(
        sources=[str(COMPRESSED_DECODER_SV)],
        hdl_toplevel="ibex_compressed_decoder",
        build_dir=str(sim_build),
        always=True,
        parameters={
            "RV32ZC": 3,
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


def test_ibex_compressed_decoder_unit(compressed_decoder_runner, tmp_path):
    runner, sim_build = compressed_decoder_runner
    results_xml = runner.test(
        test_module="test_ibex_compressed_decoder_unit",
        hdl_toplevel="ibex_compressed_decoder",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_compressed_decoder_unit.xml"),
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
