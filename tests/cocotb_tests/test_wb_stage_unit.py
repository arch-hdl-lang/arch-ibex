"""Standalone cocotb scenarios for `ibex_wb_stage` (basic suite).

Each `@cocotb.test` covers one Requirement from
`changes/port-wb_stage/specs/wb_stage/spec.md`.

In-scope parameters: WritebackStage=0, DummyInstructions=0, ResetAll=0.

The module is purely combinational in WritebackStage=0 mode. Tests drive
inputs and check outputs after a Timer(1, "ns") settle — no clock edge
is required for correctness checks. A clock is started to satisfy
Verilator's clock requirements (clk_i/rst_ni are wired but unused in
the passthrough path).

Signal conventions:
  - All inputs are driven to 0 before each test then set as needed.
  - Timer(1, "ns") is used to allow combinational paths to settle.
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


CLK_PERIOD_NS = 10  # 100 MHz


async def _start_and_reset(dut):
    """Start clock and deassert reset. Idle all inputs."""
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())
    _idle(dut)
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)


def _idle(dut):
    """Drive all inputs to benign (inactive) values."""
    dut.en_wb_i.value                   = 0
    dut.instr_type_wb_i.value           = 0
    dut.pc_id_i.value                   = 0
    dut.instr_is_compressed_id_i.value  = 0
    dut.instr_perf_count_id_i.value     = 0
    dut.rf_waddr_id_i.value             = 0
    dut.rf_wdata_id_i.value             = 0
    dut.rf_we_id_i.value                = 0
    dut.dummy_instr_id_i.value          = 0
    dut.rf_wdata_lsu_i.value            = 0
    dut.rf_we_lsu_i.value               = 0
    dut.lsu_resp_valid_i.value          = 0
    dut.lsu_resp_err_i.value            = 0


# ── REQ-1: Address passthrough ────────────────────────────────────────────

@cocotb.test()
async def req1_address_passthrough(dut):
    """REQ-1: rf_waddr_wb_o equals rf_waddr_id_i combinatorially."""
    await _start_and_reset(dut)
    for addr in (0, 1, 15, 16, 31):
        _idle(dut)
        dut.rf_waddr_id_i.value = addr
        await Timer(1, "ns")
        got = int(dut.rf_waddr_wb_o.value)
        assert got == addr, (
            f"rf_waddr_wb_o expected {addr}, got {got}"
        )


# ── REQ-2: Write-enable OR combination ───────────────────────────────────

@cocotb.test()
async def req2_we_or_id_only(dut):
    """REQ-2a: rf_we_wb_o = rf_we_id_i | rf_we_lsu_i — ID only active."""
    await _start_and_reset(dut)
    _idle(dut)
    dut.rf_we_id_i.value  = 1
    dut.rf_we_lsu_i.value = 0
    await Timer(1, "ns")
    assert int(dut.rf_we_wb_o.value) == 1, "rf_we_wb_o should be 1 when rf_we_id_i=1"


@cocotb.test()
async def req2_we_or_lsu_only(dut):
    """REQ-2b: rf_we_wb_o = rf_we_id_i | rf_we_lsu_i — LSU only active."""
    await _start_and_reset(dut)
    _idle(dut)
    dut.rf_we_id_i.value  = 0
    dut.rf_we_lsu_i.value = 1
    await Timer(1, "ns")
    assert int(dut.rf_we_wb_o.value) == 1, "rf_we_wb_o should be 1 when rf_we_lsu_i=1"


@cocotb.test()
async def req2_we_or_neither(dut):
    """REQ-2c: rf_we_wb_o = 0 when both enables are 0."""
    await _start_and_reset(dut)
    _idle(dut)
    dut.rf_we_id_i.value  = 0
    dut.rf_we_lsu_i.value = 0
    await Timer(1, "ns")
    assert int(dut.rf_we_wb_o.value) == 0, "rf_we_wb_o should be 0 when both enables are 0"


# ── REQ-3: Write-data masked-OR combiner ──────────────────────────────────

@cocotb.test()
async def req3_wdata_id_path(dut):
    """REQ-3a: rf_wdata_wb_o = rf_wdata_id_i when rf_we_id_i=1, rf_we_lsu_i=0."""
    await _start_and_reset(dut)
    _idle(dut)
    dut.rf_we_id_i.value    = 1
    dut.rf_wdata_id_i.value = 0xDEAD_BEEF
    dut.rf_we_lsu_i.value   = 0
    dut.rf_wdata_lsu_i.value = 0xFFFF_FFFF
    await Timer(1, "ns")
    got = int(dut.rf_wdata_wb_o.value)
    assert got == 0xDEAD_BEEF, (
        f"rf_wdata_wb_o: expected 0xDEAD_BEEF, got 0x{got:08X}"
    )


@cocotb.test()
async def req3_wdata_lsu_path(dut):
    """REQ-3b: rf_wdata_wb_o = rf_wdata_lsu_i when rf_we_lsu_i=1, rf_we_id_i=0."""
    await _start_and_reset(dut)
    _idle(dut)
    dut.rf_we_id_i.value     = 0
    dut.rf_wdata_id_i.value  = 0xFFFF_FFFF
    dut.rf_we_lsu_i.value    = 1
    dut.rf_wdata_lsu_i.value = 0x1234_5678
    await Timer(1, "ns")
    got = int(dut.rf_wdata_wb_o.value)
    assert got == 0x1234_5678, (
        f"rf_wdata_wb_o: expected 0x1234_5678, got 0x{got:08X}"
    )


@cocotb.test()
async def req3_wdata_neither_zero(dut):
    """REQ-3c: rf_wdata_wb_o = 0 when neither write enable is asserted."""
    await _start_and_reset(dut)
    _idle(dut)
    dut.rf_we_id_i.value     = 0
    dut.rf_wdata_id_i.value  = 0xCAFE_CAFE
    dut.rf_we_lsu_i.value    = 0
    dut.rf_wdata_lsu_i.value = 0xF00D_F00D
    await Timer(1, "ns")
    got = int(dut.rf_wdata_wb_o.value)
    assert got == 0, (
        f"rf_wdata_wb_o: expected 0x00000000 when both WEs=0, got 0x{got:08X}"
    )


# ── REQ-4: Ready always asserted ─────────────────────────────────────────

@cocotb.test()
async def req4_ready_always_one(dut):
    """REQ-4: ready_wb_o is constant 1 regardless of other inputs."""
    await _start_and_reset(dut)
    # Check across several input combinations.
    for en in (0, 1):
        for we_id in (0, 1):
            for we_lsu in (0, 1):
                if we_id and we_lsu:
                    continue  # skip invalid dual-assert case
                _idle(dut)
                dut.en_wb_i.value    = en
                dut.rf_we_id_i.value  = we_id
                dut.rf_we_lsu_i.value = we_lsu
                await Timer(1, "ns")
                assert int(dut.ready_wb_o.value) == 1, (
                    f"ready_wb_o must be 1 (en={en}, we_id={we_id}, we_lsu={we_lsu})"
                )


# ── REQ-5: Performance counter — instruction retired ─────────────────────

@cocotb.test()
async def req5_perf_ret_basic(dut):
    """REQ-5a: perf_instr_ret_wb_o — normal retire (no error)."""
    await _start_and_reset(dut)
    _idle(dut)
    dut.instr_perf_count_id_i.value = 1
    dut.en_wb_i.value               = 1
    dut.lsu_resp_valid_i.value      = 0
    dut.lsu_resp_err_i.value        = 0
    await Timer(1, "ns")
    assert int(dut.perf_instr_ret_wb_o.value) == 1, (
        "perf_instr_ret_wb_o should be 1 for countable instruction with en_wb=1, no error"
    )


@cocotb.test()
async def req5_perf_ret_lsu_error_suppressed(dut):
    """REQ-5b: perf_instr_ret_wb_o suppressed when lsu_resp_valid & lsu_resp_err."""
    await _start_and_reset(dut)
    _idle(dut)
    dut.instr_perf_count_id_i.value = 1
    dut.en_wb_i.value               = 1
    dut.lsu_resp_valid_i.value      = 1
    dut.lsu_resp_err_i.value        = 1
    await Timer(1, "ns")
    assert int(dut.perf_instr_ret_wb_o.value) == 0, (
        "perf_instr_ret_wb_o should be 0 when lsu_resp_valid & lsu_resp_err"
    )


@cocotb.test()
async def req5_perf_ret_en_wb_gating(dut):
    """REQ-5c: perf_instr_ret_wb_o = 0 when en_wb_i = 0."""
    await _start_and_reset(dut)
    _idle(dut)
    dut.instr_perf_count_id_i.value = 1
    dut.en_wb_i.value               = 0
    dut.lsu_resp_valid_i.value      = 0
    dut.lsu_resp_err_i.value        = 0
    await Timer(1, "ns")
    assert int(dut.perf_instr_ret_wb_o.value) == 0, (
        "perf_instr_ret_wb_o should be 0 when en_wb_i=0"
    )


@cocotb.test()
async def req5_perf_ret_count_gating(dut):
    """REQ-5d: perf_instr_ret_wb_o = 0 when instr_perf_count_id_i = 0."""
    await _start_and_reset(dut)
    _idle(dut)
    dut.instr_perf_count_id_i.value = 0
    dut.en_wb_i.value               = 1
    dut.lsu_resp_valid_i.value      = 0
    dut.lsu_resp_err_i.value        = 0
    await Timer(1, "ns")
    assert int(dut.perf_instr_ret_wb_o.value) == 0, (
        "perf_instr_ret_wb_o should be 0 when instr_perf_count_id_i=0"
    )


# ── REQ-6: Performance counter — compressed instruction retired ───────────

@cocotb.test()
async def req6_perf_compressed_retire(dut):
    """REQ-6a: perf_instr_ret_compressed_wb_o asserted for compressed retired instr."""
    await _start_and_reset(dut)
    _idle(dut)
    dut.instr_perf_count_id_i.value      = 1
    dut.en_wb_i.value                    = 1
    dut.instr_is_compressed_id_i.value   = 1
    dut.lsu_resp_valid_i.value           = 0
    dut.lsu_resp_err_i.value             = 0
    await Timer(1, "ns")
    assert int(dut.perf_instr_ret_wb_o.value) == 1, "perf_instr_ret_wb_o must be 1"
    assert int(dut.perf_instr_ret_compressed_wb_o.value) == 1, (
        "perf_instr_ret_compressed_wb_o should be 1 for compressed instruction retire"
    )


@cocotb.test()
async def req6_perf_noncompressed_no_compressed_count(dut):
    """REQ-6b: perf_instr_ret_compressed_wb_o = 0 for non-compressed retired instr."""
    await _start_and_reset(dut)
    _idle(dut)
    dut.instr_perf_count_id_i.value      = 1
    dut.en_wb_i.value                    = 1
    dut.instr_is_compressed_id_i.value   = 0
    dut.lsu_resp_valid_i.value           = 0
    dut.lsu_resp_err_i.value             = 0
    await Timer(1, "ns")
    assert int(dut.perf_instr_ret_wb_o.value) == 1, "perf_instr_ret_wb_o must be 1"
    assert int(dut.perf_instr_ret_compressed_wb_o.value) == 0, (
        "perf_instr_ret_compressed_wb_o should be 0 for non-compressed instruction"
    )


# ── REQ-7: Speculative performance counters tied zero ────────────────────

@cocotb.test()
async def req7_speculative_counters_zero(dut):
    """REQ-7: perf_instr_ret_wb_spec_o and perf_instr_ret_compressed_wb_spec_o are always 0."""
    await _start_and_reset(dut)
    for en in (0, 1):
        for count in (0, 1):
            for compressed in (0, 1):
                _idle(dut)
                dut.en_wb_i.value                   = en
                dut.instr_perf_count_id_i.value      = count
                dut.instr_is_compressed_id_i.value   = compressed
                await Timer(1, "ns")
                assert int(dut.perf_instr_ret_wb_spec_o.value) == 0, (
                    f"perf_instr_ret_wb_spec_o must be 0 (en={en},count={count},comp={compressed})"
                )
                assert int(dut.perf_instr_ret_compressed_wb_spec_o.value) == 0, (
                    f"perf_instr_ret_compressed_wb_spec_o must be 0 (en={en},count={count},comp={compressed})"
                )


# ── REQ-8: Dummy-instruction flag passthrough ─────────────────────────────

@cocotb.test()
async def req8_dummy_instr_passthrough(dut):
    """REQ-8: dummy_instr_wb_o equals dummy_instr_id_i combinatorially."""
    await _start_and_reset(dut)
    for val in (0, 1):
        _idle(dut)
        dut.dummy_instr_id_i.value = val
        await Timer(1, "ns")
        got = int(dut.dummy_instr_wb_o.value)
        assert got == val, (
            f"dummy_instr_wb_o: expected {val}, got {got}"
        )


# ── REQ-9: WS=1-only outputs tied zero ────────────────────────────────────

@cocotb.test()
async def req9_ws1_outputs_tied_zero(dut):
    """REQ-9: outstanding_load_wb_o, outstanding_store_wb_o, pc_wb_o,
    rf_write_wb_o, rf_wdata_fwd_wb_o, and instr_done_wb_o are all 0."""
    await _start_and_reset(dut)
    # Drive some non-trivial inputs to confirm tie-offs are not input-dependent.
    _idle(dut)
    dut.en_wb_i.value                   = 1
    dut.instr_perf_count_id_i.value     = 1
    dut.rf_we_id_i.value                = 1
    dut.rf_waddr_id_i.value             = 5
    dut.rf_wdata_id_i.value             = 0xABCD_EF01
    dut.lsu_resp_valid_i.value          = 1
    await Timer(1, "ns")
    assert int(dut.outstanding_load_wb_o.value)  == 0, "outstanding_load_wb_o must be 0"
    assert int(dut.outstanding_store_wb_o.value) == 0, "outstanding_store_wb_o must be 0"
    assert int(dut.pc_wb_o.value)                == 0, "pc_wb_o must be 0"
    assert int(dut.rf_write_wb_o.value)          == 0, "rf_write_wb_o must be 0"
    assert int(dut.rf_wdata_fwd_wb_o.value)      == 0, "rf_wdata_fwd_wb_o must be 0"
    assert int(dut.instr_done_wb_o.value)        == 0, "instr_done_wb_o must be 0"
