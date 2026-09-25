"""Standalone unit-test for the ARCH-emitted `ibex_register_file_ff`.

Builds Verilator on `build/ibex_register_file_ff.sv` alone and runs the
`test_ibex_register_file_ff_unit` cocotb module against it. Coverage
maps to the requirements in `specs/register_file_ff/spec.md` for the
in-scope parameter set (RV32E=0, DummyInstructions=0, DataWidth=32,
WordZeroVal=0).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"
RF_SV = REPO_ROOT / "build" / "ibex_register_file_ff.sv"


pytest.importorskip("cocotb_tools.runner")


def _build_rf(tmp_path_factory, name: str, parameters: dict | None = None):
    from cocotb_tools.runner import get_runner

    if not RF_SV.is_file():
        pytest.skip(f"missing {RF_SV}; run `make build` first")

    sim_build = tmp_path_factory.mktemp(name)
    runner = get_runner("verilator")
    runner.build(
        sources=[str(RF_SV)],
        hdl_toplevel="ibex_register_file_ff",
        build_dir=str(sim_build),
        always=True,
        parameters=parameters or {},
        build_args=[
            "--public-flat-rw",
            "-Wno-fatal",
            "-Wno-UNUSEDSIGNAL",
            "-Wno-UNUSEDPARAM",
            "-Wno-WIDTHEXPAND",
        ],
    )
    return runner, sim_build


@pytest.fixture(scope="module")
def rf_runner(verilator_bin, tmp_path_factory):
    return _build_rf(tmp_path_factory, "rf_sim_build")


@pytest.fixture(scope="module")
def rf_onehot_runner(verilator_bin, tmp_path_factory):
    """ReadOneHotA = 1: the configuration ibex_top instantiates."""
    return _build_rf(tmp_path_factory, "rf_onehot_sim_build", {"ReadOneHotA": 1})


def test_ibex_register_file_ff_onehot(rf_onehot_runner, tmp_path):
    runner, sim_build = rf_onehot_runner
    results_xml = runner.test(
        test_module="test_ibex_register_file_ff_onehot",
        hdl_toplevel="ibex_register_file_ff",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_rf_onehot.xml"),
    )
    root = ET.parse(results_xml).getroot()
    failures = int(root.attrib.get("failures", "0")) + int(root.attrib.get("errors", "0"))
    assert failures == 0, f"cocotb reported {failures} failures; see {results_xml}"


def test_ibex_register_file_ff_unit(rf_runner, tmp_path):
    runner, sim_build = rf_runner
    results_xml = runner.test(
        test_module="test_ibex_register_file_ff_unit",
        hdl_toplevel="ibex_register_file_ff",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_rf_unit.xml"),
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
