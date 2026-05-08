"""Standalone unit-test for the ARCH-emitted `ibex_icache` (basic suite).

Builds Verilator on `build/ibex_icache.sv` and runs the
`test_ibex_icache_unit` cocotb module against it.

Coverage maps to the Requirements in
`changes/2026-05-05-port-ibex_icache/specs/icache/spec.md`, one cocotb
test per Requirement (33 tests total, 7 of which are decorator-skipped
as documented in the inventory).

Fixed parameters (matching `ibex_top.sv` defaults under the SoC's
`mini_soc.sv` pinning):
  - ICacheECC      = 0
  - ResetAll       = 0
  - BusSizeECC     = 32
  - TagSizeECC     = 22
  - LineSizeECC    = 64
  - BranchCache    = 0
  - TweakInfection = 0
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"
BUILD_DIR = REPO_ROOT / "build"
SHARED_PKG_SV = BUILD_DIR / "ibex_core_shared_pkg.sv"
ICACHE_SV = BUILD_DIR / "ibex_icache.sv"


pytest.importorskip("cocotb_tools.runner")


@pytest.fixture(scope="module")
def icache_runner(verilator_bin, tmp_path_factory):
    """Build a standalone Verilator model of `ibex_icache` once per session."""
    from cocotb_tools.runner import get_runner

    if not ICACHE_SV.is_file():
        pytest.skip(f"missing {ICACHE_SV}; run `make build` first")

    sim_build = tmp_path_factory.mktemp("icache_sim_build")
    runner = get_runner("verilator")
    sources = []
    if SHARED_PKG_SV.is_file():
        sources.append(str(SHARED_PKG_SV))
    # Sub-constructs are emitted as standalone .sv files (see build.sh
    # strip pass) to avoid MODDUP at SoC link time. Add them ahead of
    # the consumer .sv so Verilator sees the decls before the inst sites.
    build_dir = ICACHE_SV.parent
    for sib in ("fb_age_arb.sv", "ram_port_arb.sv", "inval_ctrl.sv"):
        sib_path = build_dir / sib
        if sib_path.is_file():
            sources.append(str(sib_path))
    sources.append(str(ICACHE_SV))
    runner.build(
        sources=sources,
        hdl_toplevel="ibex_icache",
        build_dir=str(sim_build),
        always=True,
        parameters={
            "ICacheECC":      0,
            "ResetAll":       0,
            "BusSizeECC":     32,
            "TagSizeECC":     22,
            "LineSizeECC":    64,
            "BranchCache":    0,
            "TweakInfection": 0,
        },
        build_args=[
            "--public-flat-rw",
            "-Wno-fatal",
            "-Wno-UNUSEDSIGNAL",
            "-Wno-UNUSEDPARAM",
            "-Wno-WIDTHEXPAND",
            "-Wno-UNOPTFLAT",
        ],
    )
    return runner, sim_build


def test_ibex_icache_unit(icache_runner, tmp_path):
    runner, sim_build = icache_runner
    results_xml = runner.test(
        test_module="test_ibex_icache_unit",
        hdl_toplevel="ibex_icache",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_icache_unit.xml"),
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
