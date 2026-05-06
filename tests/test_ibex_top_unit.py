"""Standalone unit-test for the ARCH-emitted `ibex_top` (basic suite).

Builds Verilator on `build/ibex_top.sv` (the C2 swap, a `module`
containing four sub-instances: IbexCore, IbexRegisterFileFf,
prim_clock_gating, prim_buf) plus all the ARCH-emitted swaps that
those sub-modules need (the full C1 IbexCore stack, IbexRegisterFileFf
from A2, plus all its leaves), plus the upstream-SV `prim_clock_gating`
and `prim_buf` cells, plus `ibex_cs_registers` (instantiated inside
IbexCore as the upstream-SV CSR file).

Coverage maps to the Requirements in
`changes/port-ibex_top/specs/ibex_top/spec.md`, one cocotb test per
Requirement (15 tests total).

Fixed parameters at build (matching `ibex_top.sv` defaults under the
SoC's `ibex_mini_soc.sv` pinning):
  - RV32E              = 0
  - RV32M / RV32B      = enum-typed; defaults match SoC pinning
  - BranchTargetALU    = 0
  - WritebackStage     = 0
  - ICache             = 0
  - BranchPredictor    = 0
  - DbgTriggerEn       = 0
  - MemECC             = 0
  - DataIndTiming      = 0
  - DummyInstructions  = 0
  - PMPEnable          = 0
  - SecureIbex         = 0
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
COCOTB_TESTS_DIR = TESTS_DIR / "cocotb_tests"
BUILD_DIR = REPO_ROOT / "build"

IBEX_ROOT = Path(os.environ.get("IBEX_ROOT", str(Path.home() / "github" / "ibex")))

# ── ARCH-emitted swaps. Package SV must be linked first (B5 lesson).
SHARED_PKG_SV         = BUILD_DIR / "ibex_core_shared_pkg.sv"
TOP_SV                = BUILD_DIR / "ibex_top.sv"
CORE_SV               = BUILD_DIR / "ibex_core.sv"
IF_STAGE_SV           = BUILD_DIR / "ibex_if_stage.sv"
ID_STAGE_SV           = BUILD_DIR / "ibex_id_stage.sv"
DECODER_SV            = BUILD_DIR / "ibex_decoder.sv"
CONTROLLER_SV         = BUILD_DIR / "ibex_controller.sv"
EX_BLOCK_SV           = BUILD_DIR / "ibex_ex_block.sv"
ALU_SV                = BUILD_DIR / "ibex_alu.sv"
MULTDIV_FAST_SV       = BUILD_DIR / "ibex_multdiv_fast.sv"
LSU_SV                = BUILD_DIR / "ibex_load_store_unit.sv"
WB_STAGE_SV           = BUILD_DIR / "ibex_wb_stage.sv"
PREFETCH_BUFFER_SV    = BUILD_DIR / "ibex_prefetch_buffer.sv"
FETCH_FIFO_SV         = BUILD_DIR / "ibex_fetch_fifo.sv"
COMPRESSED_DECODER_SV = BUILD_DIR / "ibex_compressed_decoder.sv"
COUNTER_SV            = BUILD_DIR / "ibex_counter.sv"
REGISTER_FILE_FF_SV   = BUILD_DIR / "ibex_register_file_ff.sv"
# D1: ICache=1 path — icache + sub-constructs + 4× prim_ram_1p banks.
ICACHE_SV             = BUILD_DIR / "ibex_icache.sv"
FB_AGE_ARB_SV         = BUILD_DIR / "fb_age_arb.sv"
RAM_PORT_ARB_SV       = BUILD_DIR / "ram_port_arb.sv"
FILL_BUFFER_CAM_SV    = BUILD_DIR / "fill_buffer_cam.sv"
FILL_BUFFER_CTRL_SV   = BUILD_DIR / "fill_buffer_ctrl.sv"
INVAL_CTRL_SV         = BUILD_DIR / "inval_ctrl.sv"
PMP_SV                = BUILD_DIR / "ibex_pmp.sv"

# ── Upstream-SV dependencies. Order matters:
#   - ibex_pkg.sv first (defines enums consumed by IbexCore native
#     parameter declarations + by ibex_top.sv's ibex_pkg::* import).
#   - prim_pkg.sv next (vendor primitives package).
#   - prim_buf.sv and prim_clock_gating.sv next (the two cells that
#     IbexTop instantiates as upstream-SV against hand-written .archi
#     stubs — see N-4).
#   - ibex_csr.sv + ibex_cs_registers.sv last (consumed by IbexCore).
IBEX_PKG_SV       = IBEX_ROOT / "rtl" / "ibex_pkg.sv"
CS_REGISTERS_SV   = IBEX_ROOT / "rtl" / "ibex_cs_registers.sv"
IBEX_CSR_SV       = IBEX_ROOT / "rtl" / "ibex_csr.sv"
PRIM_PKG_SV       = IBEX_ROOT / "vendor" / "lowrisc_ip" / "ip" / "prim_generic" / "rtl" / "prim_pkg.sv"
PRIM_BUF_SV       = IBEX_ROOT / "vendor" / "lowrisc_ip" / "ip" / "prim_generic" / "rtl" / "prim_buf.sv"
PRIM_CLOCK_GATING = IBEX_ROOT / "vendor" / "lowrisc_ip" / "ip" / "prim_generic" / "rtl" / "prim_clock_gating.sv"
# D1: IbexTop instantiates 4× upstream `prim_ram_1p` (gen_noscramble_rams).
PRIM_RAM_1P_PKG_SV = IBEX_ROOT / "vendor" / "lowrisc_ip" / "ip" / "prim_generic" / "rtl" / "prim_ram_1p_pkg.sv"
PRIM_RAM_1P_SV     = IBEX_ROOT / "vendor" / "lowrisc_ip" / "ip" / "prim_generic" / "rtl" / "prim_ram_1p.sv"


# ── ARCH swap files in link order: package(s) first, then leaves
# (sub-instances), then composites (the stages, the core, the top).
ARCH_SV_FILES = [
    SHARED_PKG_SV,
    # Leaves used by multiple stages.
    COUNTER_SV,
    # ID stage leaves.
    DECODER_SV,
    CONTROLLER_SV,
    # EX block leaves.
    ALU_SV,
    MULTDIV_FAST_SV,
    # IF stage leaves.
    FETCH_FIFO_SV,
    PREFETCH_BUFFER_SV,
    COMPRESSED_DECODER_SV,
    # D1: icache + sub-constructs (linked into IfStage when ICache=1).
    FB_AGE_ARB_SV,
    RAM_PORT_ARB_SV,
    FILL_BUFFER_CAM_SV,
    FILL_BUFFER_CTRL_SV,
    INVAL_CTRL_SV,
    ICACHE_SV,
    PMP_SV,
    # Stages.
    ID_STAGE_SV,
    EX_BLOCK_SV,
    LSU_SV,
    WB_STAGE_SV,
    IF_STAGE_SV,
    # Register file (A2 leaf — instantiated by IbexTop, NOT by IbexCore).
    REGISTER_FILE_FF_SV,
    # IbexCore (C1 swap — instantiated by IbexTop).
    CORE_SV,
    # Top (C2 swap).
    TOP_SV,
]

# ── Upstream-SV files in link order: ibex_pkg first, then prim_pkg,
# then prim_buf + prim_clock_gating (IbexTop's two upstream-SV
# instances), then the CSR file (consumed by IbexCore).
UPSTREAM_SV_FILES = [
    IBEX_PKG_SV,
    PRIM_PKG_SV,
    # D1: prim_ram_1p_pkg defines `ram_1p_cfg_t` / `ram_1p_cfg_rsp_t`
    # consumed by `prim_ram_1p`'s port types (and by the SoC binding
    # `prim_ram_1p_pkg::RAM_1P_CFG_DEFAULT`).
    PRIM_RAM_1P_PKG_SV,
    PRIM_BUF_SV,
    PRIM_CLOCK_GATING,
    PRIM_RAM_1P_SV,
    IBEX_CSR_SV,
    CS_REGISTERS_SV,
]


pytest.importorskip("cocotb_tools.runner")


@pytest.fixture(scope="module")
def top_runner(verilator_bin, tmp_path_factory):
    """Build a standalone Verilator model of `ibex_top` once per session."""
    from cocotb_tools.runner import get_runner

    for sv in ARCH_SV_FILES:
        if not sv.is_file():
            pytest.skip(f"missing {sv}; run `make build` first")
    for sv in UPSTREAM_SV_FILES:
        if not sv.is_file():
            pytest.skip(
                f"missing upstream SV {sv}; check IBEX_ROOT (= {IBEX_ROOT}) or "
                f"the lowrisc_ip vendor tree"
            )

    sim_build = tmp_path_factory.mktemp("top_sim_build")
    runner = get_runner("verilator")
    runner.build(
        # Upstream first, then ARCH builds. ibex_pkg.sv must be parsed
        # before IbexCore (which uses `ibex_pkg::rv32m_e` etc. in its
        # native parameter declarations).
        sources=[str(p) for p in (UPSTREAM_SV_FILES + ARCH_SV_FILES)],
        hdl_toplevel="ibex_top",
        build_dir=str(sim_build),
        always=True,
        parameters={
            "RV32E":              0,
            # RV32M / RV32B are enum-typed in IbexCore; defaults match
            # the SoC pinning. Passing integer overrides via -G would
            # implicit-convert into the enum and trip Verilator's
            # ENUMVALUE error.
            "BranchTargetALU":    0,
            "WritebackStage":     0,
            "ICache":             0,
            "BranchPredictor":    0,
            "DbgTriggerEn":       0,
            "MemECC":             0,
            "DummyInstructions":  0,
            "PMPEnable":          1,
            "SecureIbex":         0,
        },
        build_args=[
            "--public-flat-rw",
            "-Wno-fatal",
            "-Wno-UNUSEDSIGNAL",
            "-Wno-UNUSEDPARAM",
            "-Wno-WIDTHEXPAND",
            "-Wno-UNOPTFLAT",
            "-Wno-PINCONNECTEMPTY",
            "-Wno-DECLFILENAME",
            f"-I{IBEX_ROOT}/vendor/lowrisc_ip/ip/prim/rtl",
        ],
    )
    return runner, sim_build


def test_ibex_top_unit(top_runner, tmp_path):
    runner, sim_build = top_runner
    results_xml = runner.test(
        test_module="test_ibex_top_unit",
        hdl_toplevel="ibex_top",
        build_dir=str(sim_build),
        test_dir=str(COCOTB_TESTS_DIR),
        results_xml=str(tmp_path / "results_top_unit.xml"),
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
