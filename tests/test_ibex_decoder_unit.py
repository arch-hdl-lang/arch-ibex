"""Standalone unit-test for the ARCH-emitted `ibex_decoder` (basic suite).

Builds Verilator on `build/ibex_decoder.sv` standalone with the
in-scope parameter overrides (`RV32E = 0`, `RV32M = 2` (RV32MFast),
`RV32B = 0` (RV32BNone), `BranchTargetALU = 0` — integer encodings
verified against the spec's §"Enum encodings" section) and runs the
`test_ibex_decoder_unit` cocotb module against it. Coverage maps to
the Requirements in `specs/decoder/spec.md`, one cocotb test per
Requirement.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"
DECODER_SV = REPO_ROOT / "build" / "ibex_decoder.sv"


pytest.importorskip("cocotb_tools.runner")


@pytest.fixture(scope="module")
def decoder_runner(verilator_bin, tmp_path_factory):
    """Build a standalone Verilator model of `ibex_decoder` once per
    session, with the in-scope parameter set:
      - RV32E = 0
      - RV32M = 2 (RV32MFast)
      - RV32B = 0 (RV32BNone)
      - BranchTargetALU = 0
    """
    from cocotb_tools.runner import get_runner

    if not DECODER_SV.is_file():
        pytest.skip(f"missing {DECODER_SV}; run `make build` first")

    sim_build = tmp_path_factory.mktemp("decoder_sim_build")
    runner = get_runner("verilator")
    runner.build(
        sources=[str(DECODER_SV)],
        hdl_toplevel="ibex_decoder",
        build_dir=str(sim_build),
        always=True,
        parameters={
            "RV32E": 0,
            "RV32M": 2,
            "RV32B": 0,
            "BranchTargetALU": 0,
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


def test_ibex_decoder_unit(decoder_runner, tmp_path):
    runner, sim_build = decoder_runner
    results_xml = runner.test(
        test_module="test_ibex_decoder_unit",
        hdl_toplevel="ibex_decoder",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_decoder_unit.xml"),
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
