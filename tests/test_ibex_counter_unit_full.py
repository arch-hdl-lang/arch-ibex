"""Full-regression unit-test for the ARCH-emitted `ibex_counter`.

Builds Verilator on `build/ibex_counter.sv` once per parameter
combination (CounterWidth ∈ {1, 32, 64}, ProvideValUpd ∈ {0, 1}, six
total) and runs the `test_ibex_counter_unit_full` cocotb module
against each binary. The cocotb module reads the build's parameters
from environment variables `COUNTER_WIDTH` and `PROVIDE_VAL_UPD` and
gates each test on its applicable param subset.

Skipped wholesale if `build/ibex_counter.sv` is missing.
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


# All parameter combinations the upstream CSR block instantiates.
PARAM_COMBOS = [
    (cw, pvu)
    for cw in (1, 32, 64)
    for pvu in (0, 1)
]


@pytest.fixture(scope="module")
def _verilator():
    """Pre-flight: skip the whole module if the SV file is missing."""
    if not COUNTER_SV.is_file():
        pytest.skip(f"missing {COUNTER_SV}; run `make build` first")


@pytest.mark.parametrize(
    "counter_width,provide_val_upd",
    PARAM_COMBOS,
    ids=[f"cw{cw}_pvu{pvu}" for cw, pvu in PARAM_COMBOS],
)
def test_ibex_counter_unit_full(
    _verilator,
    verilator_bin,
    tmp_path_factory,
    tmp_path,
    counter_width: int,
    provide_val_upd: int,
    monkeypatch,
):
    from cocotb_tools.runner import get_runner

    sim_build = tmp_path_factory.mktemp(
        f"counter_full_cw{counter_width}_pvu{provide_val_upd}"
    )
    runner = get_runner("verilator")
    runner.build(
        sources=[str(COUNTER_SV)],
        hdl_toplevel="ibex_counter",
        build_dir=str(sim_build),
        always=True,
        parameters={
            "CounterWidth": counter_width,
            "ProvideValUpd": provide_val_upd,
        },
        build_args=[
            "--public-flat-rw",
            "-Wno-fatal",
            "-Wno-UNUSEDSIGNAL",
            "-Wno-UNUSEDPARAM",
            "-Wno-WIDTHEXPAND",
        ],
    )
    # Pass the parameters to the cocotb module via environment vars.
    monkeypatch.setenv("COUNTER_WIDTH", str(counter_width))
    monkeypatch.setenv("PROVIDE_VAL_UPD", str(provide_val_upd))
    results_xml = runner.test(
        test_module="test_ibex_counter_unit_full",
        hdl_toplevel="ibex_counter",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(
            tmp_path / f"results_counter_full_cw{counter_width}_pvu{provide_val_upd}.xml"
        ),
        extra_env={
            "COUNTER_WIDTH": str(counter_width),
            "PROVIDE_VAL_UPD": str(provide_val_upd),
        },
    )
    tree = ET.parse(results_xml)
    root = tree.getroot()
    failures = (
        int(root.attrib.get("failures", "0"))
        + int(root.attrib.get("errors", "0"))
    )
    assert failures == 0, (
        f"cocotb reported {failures} failures for "
        f"CounterWidth={counter_width}, ProvideValUpd={provide_val_upd}; "
        f"see {results_xml}"
    )
