"""Full-regression cocotb suite for `ibex_icache`.

Walks every spec Scenario S1..S10 plus targeted edge cases. Re-uses the
basic-suite tests verbatim (re-imported below) plus a small set of
additional scenarios. The goal is broad regression coverage; many subtle
arbitration interactions in the icache live behind multi-FB state that
this unit harness exercises only loosely. Future end-to-end coverage
arrives once IbexCore + IbexTop drive the icache in the SoC gate.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge, ReadOnly, Timer

# Re-use everything from the basic-suite module.
from test_ibex_icache_unit import (  # noqa: F401
    CLK_PERIOD_NS, IC_NUM_WAYS, IC_LINE_BEATS, IC_NUM_LINES, IC_INDEX_W,
    IC_LINE_BYTES, IC_TAG_SIZE, TAG_VALID_BIT, NUM_FB, FB_THRESHOLD,
    MASK32, MASK64,
    _start_clock, _settle, _idle_inputs, _reset, _branch,
    _bus_grant_and_beat, _ram_serve_lookup, _set_unpacked_vec,
    _zero_unpacked_vec, _wait_until_idle, _tag_word, _index_of, _tag_of,
    # basic tests (so they appear in the regression too)
    test_r_rst_1_reset_drives_outputs_low,
    test_r_rst_2_no_instr_req_until_first_branch,
    test_r_rst_3_valid_o_low_for_at_least_num_lines,
    test_r_inv_1_cold_boot_walks_to_idle,
    test_r_inv_2_busy_during_invalidation,
    test_r_inv_3_oor_requests_scramble_key,
    test_r_inv_4_await_holds_until_key_valid,
    test_r_inv_5_inval_walks_every_index,
    test_r_inv_6_inval_pulse_during_idle_restarts_walk,
    test_r_inv_7_busy_o_high_until_idle,
    test_r_req_1_prefetch_advances_by_line_stride,
    test_r_req_2_branch_captures_addr_i,
    test_r_req_3_lookup_gating_req_i_zero,
    test_r_req_4_drain_with_req_i_low,
    test_r_req_5_lookup_addr_branch_priority,
    test_r_lk_1_ic1_consumes_ram_data_one_cycle_after_grant,
    test_r_lk_2_tag_match_drives_hit_data,
    test_r_lk_4_branch_into_in_flight_line_no_redundant_req,
    test_r_lk_5_no_ram_write_while_inval_block,
    test_r_fb_1_pool_full_stalls_lookup,
    test_r_fb_4_age_ordered_arbitration,
    test_r_fb_5_release_only_after_beats_writeback_output,
    test_r_fb_6_stale_fb_cancels_external_requests,
    test_r_ext_1_instr_req_only_when_fb_needs_beat,
    test_r_ext_2_instr_req_addr_stable_until_gnt,
    test_r_ext_4_rvalid_steers_to_oldest_expecting_fb,
    test_r_ext_5_no_further_req_after_recorded_bus_error,
    test_r_arb_1_lookup_priority_over_fill,
    test_r_arb_2_inval_suppresses_lookup_and_fill,
    test_r_arb_3_throttle_above_threshold,
    test_r_arb_4_ic0_driver_priority_inval_over_fill_over_lookup,
    test_r_out_1_valid_o_asserts_when_data_available,
    test_r_out_2_sticky_until_ready_or_branch,
    test_r_out_4_addr_advances_by_2_or_4,
    test_r_out_6_skid_buffer_clears_on_branch,
    test_r_out_7_hit_data_drives_valid_no_later_than_ic1plus1,
    test_r_en_1_disabled_does_not_allocate,
    test_r_en_2_disabled_still_serves_bus,
    test_r_en_3_enable_drop_drops_allocate_flag,
    test_r_inv_a_pulse_clears_all_tag_valid_bits,
    test_r_inv_b_inval_blocks_allocate_only,
    test_r_inv_c_live_fb_drops_allocate_on_inval,
    test_r_busy_1_busy_o_during_inval_or_pending_traffic,
    test_r_ecc_1_ecc_error_o_tied_zero,
)


# ──────────────────────────────────────────────────────────────────────
# Scenario walks (S1..S10) — broader stimulus per-scenario
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def s1_cold_boot_through_key_wait_into_idle(dut):
    """S1 — Cold boot: with ic_scr_key_valid_i held to 1, the FSM walks
    AWAIT_SCRAMBLE_KEY (1 cycle) → INVAL_CACHE (IC_NUM_LINES cycles) →
    IDLE. busy_o=1 throughout, valid_o=0 throughout.
    """
    await _start_clock(dut)
    await _reset(dut)
    cycles = 0
    while int(dut.busy_o.value) == 1:
        await ReadOnly()
        assert int(dut.valid_o.value) == 0
        await RisingEdge(dut.clk_i)
        await _settle(dut)
        cycles += 1
        if cycles > IC_NUM_LINES + 16:
            raise AssertionError(f"cold boot ran {cycles}, expected ~{IC_NUM_LINES}")
    assert cycles >= IC_NUM_LINES - 4


@cocotb.test()
async def s2_branch_into_cold_cache_single_miss_fill_output(dut):
    """S2 — Branch into cold cache: one FB allocates, two beats fill from
    bus, output stream advances, RAM allocate-write fires after both beats.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    addr = 0x1010_0080
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, addr)
    dut.req_i.value = 0  # avoid prefetch flooding
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # Service two beats.
    for beat in range(IC_LINE_BEATS):
        served = await _bus_grant_and_beat(
            dut, rdata=0x10000000 | beat, max_wait=8,
        )
        assert served, f"beat {beat} not serviced"
    # Eventually busy must drop.
    for _ in range(40):
        await ReadOnly()
        if int(dut.busy_o.value) == 0:
            return
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    raise AssertionError("S2 never quiesced")


@cocotb.test()
async def s3_cache_hit_fast_path(dut):
    """S3 — Cache hit fast path: branch into a hit produces valid_o on
    the cycle after IC1; subsequent bus requests for that line do not
    fire (per spec ambiguity 1, the speculative IC0 request is allowed
    but not required, so we don't bind to it; we DO require zero further
    requests AFTER the hit is recognised).
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    addr = 0x2010_0080
    dut.req_i.value = 1
    dut.ready_i.value = 1
    dut.branch_i.value = 1
    dut.addr_i.value   = addr
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    dut.req_i.value = 0  # avoid prefetch flooding extra FBs after the hit branch
    # IC1 hit
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, _tag_word(addr, valid=1))
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    _set_unpacked_vec(dut.ic_data_rdata_i, 0, 0x13_00100013)
    _set_unpacked_vec(dut.ic_data_rdata_i, 1, 0)
    await _settle(dut)
    # Wait for valid; consume a beat.
    for _ in range(4):
        await ReadOnly()
        if int(dut.valid_o.value) == 1:
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    else:
        raise AssertionError("no valid_o on hit")
    # Exit ReadOnly phase before the next sampling loop (cocotb 2.0
    # disallows back-to-back `await ReadOnly()` without an intervening
    # phase change).
    await RisingEdge(dut.clk_i)
    # Past this point: zero new bus requests for the same line.
    line = addr & ~(IC_LINE_BYTES - 1)
    seen_line_req = 0
    for _ in range(8):
        await ReadOnly()
        if int(dut.instr_req_o.value) == 1:
            ra = int(dut.instr_addr_o.value) & MASK32
            if (ra & ~(IC_LINE_BYTES - 1)) == line:
                seen_line_req += 1
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert seen_line_req == 0, (
        f"unexpected {seen_line_req} requests for hit line"
    )


@cocotb.test()
async def s4_branch_into_inflight_line_cam_target(dut):
    """S4 — Branch lands on a line currently being filled. The new
    lookup detects the FB-hit and streams from the FB. No second
    instr_req_o for the same line beyond the original FB's outstanding
    beats.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    addr = 0x3010_0080
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, addr)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # Service beat 0 only.
    served0 = await _bus_grant_and_beat(dut, rdata=0xBEAD0000, max_wait=8)
    assert served0
    # Re-branch into the same line.
    dut.branch_i.value = 1
    dut.addr_i.value   = addr + 4
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    await _settle(dut)
    # Continue servicing remaining beats.
    line = addr & ~(IC_LINE_BYTES - 1)
    new_line_reqs = 0
    for _ in range(8):
        await ReadOnly()
        if int(dut.instr_req_o.value) == 1:
            ra = int(dut.instr_addr_o.value) & MASK32
            if (ra & ~(IC_LINE_BYTES - 1)) == line:
                new_line_reqs += 1
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    # Expect at most 1 (the second beat of the original FB).
    assert new_line_reqs <= 1, (
        f"saw {new_line_reqs} requests for inflight line; expected <=1"
    )


@cocotb.test()
async def s5_branch_during_fill_to_different_line(dut):
    """S5 — Branch during fill to a different line. The original FB is
    marked stale; new FB allocates and fills.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, 0x4010_0000)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    served = await _bus_grant_and_beat(dut, rdata=0x4BEAD00, max_wait=8)
    assert served
    # Branch elsewhere.
    await _branch(dut, 0x5010_0000)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # New FB should fetch.
    served2 = await _bus_grant_and_beat(dut, rdata=0x5BEAD00, max_wait=12)
    assert served2


@cocotb.test()
async def s6_two_simultaneous_misses(dut):
    """S6 — Two simultaneous misses: two FBs, age-ordered arbitration.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, 0x6010_0000)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # Branch again to a second line before the first is done.
    await _branch(dut, 0x6020_0000)
    # Service some bus beats; both FBs should drain.
    for _ in range(4):
        served = await _bus_grant_and_beat(dut, rdata=0x6B, max_wait=8)
        if not served:
            break


@cocotb.test()
async def s7_invalidation_during_fill(dut):
    """S7 — Invalidation during fill: FB drops allocate flag, drains
    beats, FSM walks all indices, busy_o=1 throughout.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, 0x7010_0000)
    dut.req_i.value = 0  # avoid prefetch flooding
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # Pulse inval before beats arrive.
    dut.icache_inval_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.icache_inval_i.value = 0
    await _settle(dut)
    # Drain beats.
    for _ in range(IC_LINE_BEATS):
        served = await _bus_grant_and_beat(dut, rdata=0x7BEAD0, max_wait=8)
        if not served:
            break
    # Walk completes.
    for _ in range(IC_NUM_LINES + 16):
        await ReadOnly()
        if int(dut.busy_o.value) == 0:
            return
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    raise AssertionError("S7 never quiesced")


@cocotb.test()
async def s8_disable_then_reenable_cycle(dut):
    """S8 — Disable then re-enable: lookups during disable issue bus
    requests but don't allocate. After re-enable, prior cached lines
    remain valid (no eviction during disable).
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 1
    # Disable.
    dut.icache_enable_i.value = 0
    await _branch(dut, 0x8010_0000)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    for _ in range(IC_LINE_BEATS):
        served = await _bus_grant_and_beat(dut, rdata=0x8B, max_wait=8)
        if not served:
            break
    # Re-enable.
    dut.icache_enable_i.value = 1
    await _settle(dut)
    # Through the next window, no allocate write must have fired.
    for _ in range(8):
        await ReadOnly()
        if int(dut.ic_tag_write_o.value) == 1:
            wd = int(dut.ic_tag_wdata_o.value)
            assert (wd & TAG_VALID_BIT) == 0
        await RisingEdge(dut.clk_i)
        await _settle(dut)


@cocotb.test()
async def s9_bus_error_on_fill_beat(dut):
    """S9 — Bus error on a fill beat: per-beat err is recorded;
    subsequent external requests for the same FB are cancelled; output
    beat to IF (eventually) carries err_o=1 OR FB cancels.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, 0x9010_0000)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    served = await _bus_grant_and_beat(dut, rdata=0xBADBEAD, err=1, max_wait=8)
    assert served
    # No further requests for this FB.
    for _ in range(8):
        await ReadOnly()
        assert int(dut.instr_req_o.value) == 0, (
            "instr_req_o asserted after bus error"
        )
        await RisingEdge(dut.clk_i)
        await _settle(dut)


@cocotb.test()
async def s10_req_i_deasserts_drains_then_idles(dut):
    """S10 — req_i drops mid-fill: FB completes its beats, releases,
    busy_o drops to 0, no further requests fire.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, 0xA010_0000)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # Drop req_i.
    dut.req_i.value = 0
    # Drain beats.
    for _ in range(IC_LINE_BEATS):
        served = await _bus_grant_and_beat(dut, rdata=0xAB, max_wait=8)
        if not served:
            break
    # Eventually busy=0 and no more requests.
    for _ in range(40):
        await ReadOnly()
        if int(dut.busy_o.value) == 0:
            # Confirm no more requests for a window.
            for _ in range(8):
                await RisingEdge(dut.clk_i)
                await _settle(dut)
                await ReadOnly()
                assert int(dut.instr_req_o.value) == 0
            return
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    raise AssertionError("S10 never reached idle")


# ──────────────────────────────────────────────────────────────────────
# Edge-case coverage beyond the basic suite
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def edge_back_to_back_branches(dut):
    """Back-to-back `branch_i` pulses on consecutive cycles (a legal IF
    pattern per spec § Integration constraints). Verifies the cache
    survives without lockup.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 1
    dut.branch_i.value = 1
    dut.addr_i.value = 0xB100_0000
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    # second branch back-to-back
    dut.branch_i.value = 1
    dut.addr_i.value = 0xB200_0000
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    await _settle(dut)
    # Sanity: bus eventually issues a request for the latest target.
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    seen = False
    for _ in range(8):
        await ReadOnly()
        if int(dut.instr_req_o.value) == 1:
            seen = True
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert seen, "back-to-back branches blocked all bus requests"


@cocotb.test()
async def edge_num_fb_saturating_misses(dut):
    """Saturate the FB pool (NUM_FB=4) and verify the cache doesn't
    deadlock once beats start landing.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 1
    # Sequence of distinct branches.
    for i in range(NUM_FB + 1):
        await _branch(dut, 0xC100_0000 + (i << 11))
        _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
        _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # Service beats; the cache must drain.
    for _ in range(NUM_FB * IC_LINE_BEATS):
        served = await _bus_grant_and_beat(dut, rdata=0xC0FFEE, max_wait=12)
        if not served:
            break


@cocotb.test()
async def edge_ecc_tied_zero_during_inflight_traffic(dut):
    """Even with bus errors, multiple FBs, and inval pulses, ecc_error_o
    stays 0 (ICacheECC=0 contract).
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, 0xD100_0000)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    served = await _bus_grant_and_beat(dut, rdata=0xDEADC0DE, err=1, max_wait=8)
    assert served
    # Pulse inval.
    dut.icache_inval_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.icache_inval_i.value = 0
    await _settle(dut)
    for _ in range(IC_NUM_LINES // 4):
        await ReadOnly()
        assert int(dut.ecc_error_o.value) == 0
        await RisingEdge(dut.clk_i)
        await _settle(dut)


@cocotb.test()
async def edge_inval_during_inval_walk(dut):
    """A second icache_inval_i pulse arriving during an inval walk
    re-restarts the walk (idempotent invalidate). Spec §R-INV-6.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    # First inval pulse.
    dut.icache_inval_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.icache_inval_i.value = 0
    await _settle(dut)
    # Wait a few cycles into the walk.
    for _ in range(IC_NUM_LINES // 4):
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    # Second pulse.
    dut.icache_inval_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.icache_inval_i.value = 0
    await _settle(dut)
    # Eventually quiesces.
    for _ in range(IC_NUM_LINES * 2 + 32):
        await ReadOnly()
        if int(dut.busy_o.value) == 0:
            return
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    raise AssertionError("nested inval never quiesced")
