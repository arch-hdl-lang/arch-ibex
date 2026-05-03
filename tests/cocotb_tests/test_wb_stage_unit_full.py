"""Full-regression cocotb scenarios for `ibex_wb_stage`.

Covers every Requirement in
`changes/port-wb_stage/specs/wb_stage/spec.md` plus additional edge cases:
  - Address passthrough: all 32 register addresses (x0..x31).
  - Write-data combiner: varying data patterns, all-zeros, all-ones, alternating.
  - Perf counter: all combinations of instr_perf_count_id_i, en_wb_i,
    lsu_resp_valid_i, lsu_resp_err_i (2^4 = 16 combinations).
  - Perf compressed counter: tabulated against perf_instr_ret_wb_o.
  - Speculative counters: exhaustive 8-combination sweep.
  - Dummy flag: both 0 and 1 passthrough.
  - Tie-off outputs: checked under varied input activity to confirm no coupling.
  - Ready_wb_o: confirmed across all valid WE combinations.

In-scope parameters: WritebackStage=0, DummyInstructions=0, ResetAll=0.

The module is purely combinational. Timer(1, "ns") is used to settle
comb outputs; no clock edge is required for correctness checks.
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


CLK_PERIOD_NS = 10


async def _start_and_reset(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())
    _idle(dut)
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)


def _idle(dut):
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


# ── REQ-1: Address passthrough — all 32 addresses ────────────────────────

@cocotb.test()
async def req1_address_passthrough_all(dut):
    """REQ-1: rf_waddr_wb_o == rf_waddr_id_i for all x0..x31."""
    await _start_and_reset(dut)
    for addr in range(32):
        _idle(dut)
        dut.rf_waddr_id_i.value = addr
        await Timer(1, "ns")
        got = int(dut.rf_waddr_wb_o.value)
        assert got == addr, f"addr {addr}: rf_waddr_wb_o={got}"


# ── REQ-2: Write-enable OR — all valid combinations ──────────────────────

@cocotb.test()
async def req2_we_or_all_valid_combos(dut):
    """REQ-2: rf_we_wb_o = rf_we_id_i | rf_we_lsu_i for all valid combos."""
    await _start_and_reset(dut)
    cases = [
        (0, 0, 0),
        (1, 0, 1),
        (0, 1, 1),
        # (1, 1) is invalid per IC-1 — not tested
    ]
    for we_id, we_lsu, expected in cases:
        _idle(dut)
        dut.rf_we_id_i.value  = we_id
        dut.rf_we_lsu_i.value = we_lsu
        await Timer(1, "ns")
        got = int(dut.rf_we_wb_o.value)
        assert got == expected, (
            f"we_id={we_id} we_lsu={we_lsu}: expected rf_we_wb_o={expected}, got={got}"
        )


# ── REQ-3: Write-data masked-OR — data patterns ───────────────────────────

@cocotb.test()
async def req3_wdata_id_patterns(dut):
    """REQ-3: rf_wdata_wb_o = rf_wdata_id_i (masked) for varied data patterns."""
    await _start_and_reset(dut)
    patterns = [
        0x0000_0000,
        0xFFFF_FFFF,
        0xAAAA_AAAA,
        0x5555_5555,
        0x1234_5678,
        0xDEAD_BEEF,
    ]
    for data in patterns:
        _idle(dut)
        dut.rf_we_id_i.value    = 1
        dut.rf_wdata_id_i.value = data
        await Timer(1, "ns")
        got = int(dut.rf_wdata_wb_o.value)
        assert got == data, (
            f"ID path: expected 0x{data:08X}, got 0x{got:08X}"
        )


@cocotb.test()
async def req3_wdata_lsu_patterns(dut):
    """REQ-3: rf_wdata_wb_o = rf_wdata_lsu_i (masked) for varied data patterns."""
    await _start_and_reset(dut)
    patterns = [
        0x0000_0000,
        0xFFFF_FFFF,
        0xAAAA_AAAA,
        0x5555_5555,
        0xC0DE_CAFE,
        0x0000_0001,
    ]
    for data in patterns:
        _idle(dut)
        dut.rf_we_lsu_i.value    = 1
        dut.rf_wdata_lsu_i.value = data
        await Timer(1, "ns")
        got = int(dut.rf_wdata_wb_o.value)
        assert got == data, (
            f"LSU path: expected 0x{data:08X}, got 0x{got:08X}"
        )


@cocotb.test()
async def req3_wdata_neither_enable_zero(dut):
    """REQ-3: rf_wdata_wb_o = 0 when both enables are low."""
    await _start_and_reset(dut)
    for data_id, data_lsu in [
        (0xFFFF_FFFF, 0xFFFF_FFFF),
        (0xAAAA_AAAA, 0x5555_5555),
        (0x1234_5678, 0xABCD_EF01),
    ]:
        _idle(dut)
        dut.rf_we_id_i.value     = 0
        dut.rf_wdata_id_i.value  = data_id
        dut.rf_we_lsu_i.value    = 0
        dut.rf_wdata_lsu_i.value = data_lsu
        await Timer(1, "ns")
        got = int(dut.rf_wdata_wb_o.value)
        assert got == 0, (
            f"rf_wdata_wb_o must be 0 when both WEs=0, got 0x{got:08X}"
        )


# ── REQ-4: Ready always asserted — swept inputs ───────────────────────────

@cocotb.test()
async def req4_ready_swept(dut):
    """REQ-4: ready_wb_o = 1 across swept input combinations."""
    await _start_and_reset(dut)
    for en in (0, 1):
        for count in (0, 1):
            for we_id in (0, 1):
                for we_lsu in (0, 1):
                    if we_id and we_lsu:
                        continue
                    _idle(dut)
                    dut.en_wb_i.value                 = en
                    dut.instr_perf_count_id_i.value   = count
                    dut.rf_we_id_i.value              = we_id
                    dut.rf_we_lsu_i.value             = we_lsu
                    await Timer(1, "ns")
                    assert int(dut.ready_wb_o.value) == 1, (
                        f"ready_wb_o must be 1 for en={en},count={count},we_id={we_id},we_lsu={we_lsu}"
                    )


# ── REQ-5: Perf counter — all 2^4 combinations ────────────────────────────

@cocotb.test()
async def req5_perf_ret_exhaustive(dut):
    """REQ-5: perf_instr_ret_wb_o exhaustive test over all 16 input combos."""
    await _start_and_reset(dut)
    for count in (0, 1):
        for en in (0, 1):
            for rvalid in (0, 1):
                for rerr in (0, 1):
                    expected = count & en & ~(rvalid & rerr)
                    _idle(dut)
                    dut.instr_perf_count_id_i.value = count
                    dut.en_wb_i.value               = en
                    dut.lsu_resp_valid_i.value      = rvalid
                    dut.lsu_resp_err_i.value        = rerr
                    await Timer(1, "ns")
                    got = int(dut.perf_instr_ret_wb_o.value)
                    assert got == expected, (
                        f"count={count} en={en} rvalid={rvalid} rerr={rerr}: "
                        f"expected perf_instr_ret_wb_o={expected}, got={got}"
                    )


# ── REQ-6: Compressed perf counter — sweep ───────────────────────────────

@cocotb.test()
async def req6_perf_compressed_sweep(dut):
    """REQ-6: perf_instr_ret_compressed_wb_o = perf_ret & instr_is_compressed_id_i."""
    await _start_and_reset(dut)
    for count in (0, 1):
        for en in (0, 1):
            for compressed in (0, 1):
                perf_ret = count & en  # no lsu error in this sweep
                expected = perf_ret & compressed
                _idle(dut)
                dut.instr_perf_count_id_i.value     = count
                dut.en_wb_i.value                   = en
                dut.instr_is_compressed_id_i.value  = compressed
                await Timer(1, "ns")
                got = int(dut.perf_instr_ret_compressed_wb_o.value)
                assert got == expected, (
                    f"count={count} en={en} comp={compressed}: "
                    f"expected perf_instr_ret_compressed_wb_o={expected}, got={got}"
                )


# ── REQ-7: Speculative counters — all 8 input combinations ────────────────

@cocotb.test()
async def req7_speculative_counters_exhaustive(dut):
    """REQ-7: perf_instr_ret_wb_spec_o and ..._compressed_... are always 0."""
    await _start_and_reset(dut)
    for en in (0, 1):
        for count in (0, 1):
            for compressed in (0, 1):
                _idle(dut)
                dut.en_wb_i.value                   = en
                dut.instr_perf_count_id_i.value     = count
                dut.instr_is_compressed_id_i.value  = compressed
                await Timer(1, "ns")
                spec = int(dut.perf_instr_ret_wb_spec_o.value)
                comp_spec = int(dut.perf_instr_ret_compressed_wb_spec_o.value)
                assert spec == 0, (
                    f"perf_instr_ret_wb_spec_o must be 0 (en={en},count={count},comp={compressed}), got={spec}"
                )
                assert comp_spec == 0, (
                    f"perf_instr_ret_compressed_wb_spec_o must be 0 (en={en},count={count},comp={compressed}), got={comp_spec}"
                )


# ── REQ-8: Dummy-instruction flag passthrough ─────────────────────────────

@cocotb.test()
async def req8_dummy_instr_both_values(dut):
    """REQ-8: dummy_instr_wb_o = dummy_instr_id_i for both 0 and 1."""
    await _start_and_reset(dut)
    for val in (0, 1):
        _idle(dut)
        dut.dummy_instr_id_i.value = val
        await Timer(1, "ns")
        got = int(dut.dummy_instr_wb_o.value)
        assert got == val, f"dummy_instr_wb_o: expected {val}, got {got}"


# ── REQ-9: WS=1-only outputs — varied input activity ─────────────────────

@cocotb.test()
async def req9_tieoffs_under_activity(dut):
    """REQ-9: tie-off outputs remain 0 regardless of input activity."""
    await _start_and_reset(dut)
    input_combos = [
        # (en_wb, we_id, waddr_id, wdata_id, we_lsu, wdata_lsu, rvalid, rerr)
        (0, 0, 0,  0x00000000, 0, 0x00000000, 0, 0),
        (1, 1, 5,  0xDEAD_BEEF, 0, 0x00000000, 0, 0),
        (1, 0, 0,  0x00000000, 1, 0x1234_5678, 0, 0),
        (1, 1, 15, 0xAAAA_AAAA, 0, 0x00000000, 1, 0),
        (1, 0, 0,  0x00000000, 1, 0xFFFF_FFFF, 1, 1),
    ]
    for (en, we_id, waddr_id, wdata_id, we_lsu, wdata_lsu, rvalid, rerr) in input_combos:
        _idle(dut)
        dut.en_wb_i.value            = en
        dut.rf_we_id_i.value         = we_id
        dut.rf_waddr_id_i.value      = waddr_id
        dut.rf_wdata_id_i.value      = wdata_id
        dut.rf_we_lsu_i.value        = we_lsu
        dut.rf_wdata_lsu_i.value     = wdata_lsu
        dut.lsu_resp_valid_i.value   = rvalid
        dut.lsu_resp_err_i.value     = rerr
        await Timer(1, "ns")
        assert int(dut.outstanding_load_wb_o.value)  == 0, "outstanding_load_wb_o must be 0"
        assert int(dut.outstanding_store_wb_o.value) == 0, "outstanding_store_wb_o must be 0"
        assert int(dut.pc_wb_o.value)                == 0, "pc_wb_o must be 0"
        assert int(dut.rf_write_wb_o.value)          == 0, "rf_write_wb_o must be 0"
        assert int(dut.rf_wdata_fwd_wb_o.value)      == 0, "rf_wdata_fwd_wb_o must be 0"
        assert int(dut.instr_done_wb_o.value)        == 0, "instr_done_wb_o must be 0"


# ── Combinational stability (no glitch) ───────────────────────────────────

@cocotb.test()
async def comb_stability_rapid_toggling(dut):
    """Verify outputs track inputs within 1 ns when inputs change rapidly."""
    await _start_and_reset(dut)
    # Toggle rf_waddr_id_i rapidly and verify passthrough at each step.
    for addr in range(32):
        _idle(dut)
        dut.rf_waddr_id_i.value = addr
        await Timer(1, "ns")
        assert int(dut.rf_waddr_wb_o.value) == addr, \
            f"rapid toggle: addr={addr} mismatch"

    # Toggle rf_wdata_id_i with we=1 rapidly.
    test_data = [0x00000000, 0xFFFFFFFF, 0xA5A5A5A5, 0x5A5A5A5A, 0x12345678]
    for data in test_data:
        _idle(dut)
        dut.rf_we_id_i.value    = 1
        dut.rf_wdata_id_i.value = data
        await Timer(1, "ns")
        got = int(dut.rf_wdata_wb_o.value)
        assert got == data, f"rapid data toggle: expected 0x{data:08X}, got 0x{got:08X}"
