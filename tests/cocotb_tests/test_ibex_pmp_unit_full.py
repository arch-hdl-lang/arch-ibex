"""Full-regression cocotb scenarios for `ibex_pmp`.

Covers every Scenario S1..S10 in
`changes/2026-05-06-port-ibex_pmp/specs/pmp/spec.md`, cross-scenario
integration combinations (≥4 explicit ones), and edge-case sweeps:
boundary widths, all-zero / all-one configs, every region-mode
permutation across 4 regions, the 8 L/R/W/X combinations under MML and
non-MML.

Settling is `Timer(1, "ns")` — DUT is purely combinational.

Channel encoding (PMPNumChan=3, see proposal §"Pinned parameters"):
PMP_I=0 (i-fetch addr), PMP_I2=1 (fetch+2 upper-half), PMP_D=2 (data).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer

# Reuse the helpers + constants from the basic suite — both files live
# in the same cocotb_tests folder, and Verilator finds them via
# PYTHONPATH set by cocotb.runner.
from test_ibex_pmp_unit import (  # type: ignore
    PRIV_LVL_M, PRIV_LVL_U,
    PMP_ACC_EXEC, PMP_ACC_WRITE, PMP_ACC_READ, PMP_ACC_RSVD,
    PMP_MODE_OFF, PMP_MODE_TOR, PMP_MODE_NA4, PMP_MODE_NAPOT,
    PMP_NUM_REGIONS, PMP_NUM_CHAN,
    PMP_I, PMP_I2, PMP_D,
    _pmp_cfg, _mseccfg,
    _drive_region, _zero_regions,
    _drive_channel, _zero_channels,
    _idle, _settle, _err,
)


# ─────────────────────────────────────────────────────────────────────────
# Scenarios S1..S10 (one test each)
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_s1_off_region_never_matches(dut):
    """Spec §S1: region 0 OFF + all other regions OFF + U-mode → deny."""
    await _idle(dut)
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_OFF, R=1, W=1, X=1),
                  0x0000_1000)
    _drive_channel(dut, PMP_I, addr=0x0000_1000, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_s2_tor_inclusive_lower_exclusive_upper(dut):
    """Spec §S2: TOR region 1 with addr0=0x100, addr1=0x200.
    Lower bound inclusive, upper bound exclusive."""
    await _idle(dut)
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_OFF), 0x100)
    _drive_region(dut, 1, _pmp_cfg(mode=PMP_MODE_TOR, R=1), 0x200)
    _drive_channel(dut, PMP_I, addr=0x100, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    _drive_channel(dut, PMP_I, addr=0x200, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_s3_napot_at_granularity_zero(dut):
    """Spec §S3 (corrected per Ibex algorithm): NAPOT G=0 16-byte at
    byte base 0x10 encoded by csr=0x14. Spec §S3 description used
    csr=0x1F which actually encodes 64-byte at base 0 per the same
    algorithm — see proposal §Spec ambiguity resolutions A3."""
    await _idle(dut)
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_NAPOT, R=1), 0x14)
    for byte_pa in [0x10, 0x14, 0x18, 0x1F]:
        _drive_channel(dut, PMP_I, addr=byte_pa, priv=PRIV_LVL_U,
                       req_type=PMP_ACC_READ)
        await _settle(dut)
        assert _err(dut, PMP_I) == 0
    for byte_pa in [0xF, 0x20, 0x40, 0x100]:
        _drive_channel(dut, PMP_I, addr=byte_pa, priv=PRIV_LVL_U,
                       req_type=PMP_ACC_READ)
        await _settle(dut)
        assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_s4_locked_region_mmode_read(dut):
    """Spec §S4: MML=0, locked NAPOT region {R=1, W=0, X=0}, M-mode
    READ allowed; M-mode WRITE denied."""
    await _idle(dut)
    _drive_region(dut, 0, _pmp_cfg(L=1, mode=PMP_MODE_NAPOT, R=1), 0x1F)
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_WRITE)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_s5_multiple_matches_lowest_wins(dut):
    """Spec §S5: Region 0 R=1 + region 2 R=0 both match → R=1 wins.
    Swap → deny wins."""
    await _idle(dut)
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_NA4, R=1), 0x100)
    _drive_region(dut, 2, _pmp_cfg(mode=PMP_MODE_NA4, R=0), 0x100)
    _drive_channel(dut, PMP_I, addr=0x100, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_NA4, R=0), 0x100)
    _drive_region(dut, 2, _pmp_cfg(mode=PMP_MODE_NA4, R=1), 0x100)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_s6_mml_m_only_execute_encoding(dut):
    """Spec §S6: MML=1, {L=1, X=1, R=0, W=0} encodes M-only EXEC."""
    await _idle(dut)
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mml=1)
    _drive_region(dut, 0, _pmp_cfg(L=1, mode=PMP_MODE_NAPOT, X=1), 0x1F)
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_EXEC)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_EXEC)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_s7_mmwp_mmode_no_match_deny(dut):
    """Spec §S7: MMWP=1, all OFF, M-mode → deny."""
    await _idle(dut)
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mmwp=1)
    _drive_channel(dut, PMP_I, addr=0x1234, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_s8_debug_mode_dm_window_bypass(dut):
    """Spec §S8: debug_mode=1 + addr in DM window → allow even with
    MMWP=1; just outside the window → MMWP-deny applies."""
    await _idle(dut)
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mmwp=1)
    dut.debug_mode_i.value = 1
    # byte-PA 0x0 (inside [0..3]).
    _drive_channel(dut, PMP_I, addr=0x0, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_EXEC)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    # byte-PA 0x4 (outside).
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_EXEC)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_s9_iside_dside_independence(dut):
    """Spec §S9: i-side EXEC at A_X allowed; d-side WRITE at A_W denied
    in the same cycle, independently."""
    await _idle(dut)
    # MML=1; region 0 = M-only EXEC at A_X (word 0x4..0x7).
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mml=1)
    _drive_region(dut, 0, _pmp_cfg(L=0, mode=PMP_MODE_NAPOT, X=1), 0x1F)
    # Channel 0 (i-fetch): U-mode EXEC at word 0x4.
    # Under MML, {L=0,X=1,R=0,W=0} grants non-M EXEC by REQ-MML-3 path.
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_EXEC)
    # Channel 2 (d-side): M-mode WRITE at word 0x4.
    # Under MML, basic_perm_check has W=0, so denied.
    _drive_channel(dut, PMP_D, addr=0x4, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_WRITE)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    assert _err(dut, PMP_D) == 1


@cocotb.test()
async def test_s10_all_zero_csr_nonm_deny(dut):
    """Spec §S10: All CSR zero, U-mode, debug=0 → deny."""
    await _idle(dut)
    _drive_channel(dut, PMP_I, addr=0xDEAD, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


# ─────────────────────────────────────────────────────────────────────────
# Cross-scenario integration tests (≥ 4 required)
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_cross_c1_multimatch_under_mmwp(dut):
    """Cross §S5 ∩ §S7: With MMWP=1, multi-region match still picks
    the lowest-index match — MMWP only fires when NO region matches."""
    await _idle(dut)
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mmwp=1)
    # Region 1 NA4 R=1, region 3 NA4 R=0; both at word 0x100.
    _drive_region(dut, 1, _pmp_cfg(mode=PMP_MODE_NA4, R=1), 0x100)
    _drive_region(dut, 3, _pmp_cfg(mode=PMP_MODE_NA4, R=0), 0x100)
    _drive_channel(dut, PMP_I, addr=0x100, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    # Region 1 (allow) wins; MMWP must NOT override an actual match.
    assert _err(dut, PMP_I) == 0
    # If we move the request to a non-matching addr, MMWP deny fires.
    _drive_channel(dut, PMP_I, addr=0x200, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_cross_c2_locked_region_under_mml(dut):
    """Cross §S4 ∩ §S6: A locked NAPOT {L=1,R=1,W=0,X=0} that grants
    M-mode-read pre-MML behaves DIFFERENTLY post-MML — the
    {R,W}={0,1} table doesn't apply ({R=1,W=0}), so the lock-flip
    path of REQ-MML-3 governs. Under MML+locked, M-mode requires
    `lock=1` ✓ AND `basic_perm_check=read=1` → grant."""
    await _idle(dut)
    cfg = _pmp_cfg(L=1, mode=PMP_MODE_NAPOT, X=0, W=0, R=1)
    _drive_region(dut, 0, cfg, 0x1F)
    # Pre-MML, M-mode READ → allow (REQ-PERM-2).
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    # Same setup, MML=1.
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mml=1)
    await _settle(dut)
    # REQ-MML-3 path: M-mode requires L=1 ✓; basic R=1 ✓ → still allow.
    assert _err(dut, PMP_I) == 0
    # U-mode same setup pre-MML: basic R=1 → allow.
    dut.csr_pmp_mseccfg_i.value = _mseccfg()  # MML off
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    # U-mode with MML=1: REQ-MML-3 needs L=0 for non-M; we have L=1 → deny.
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mml=1)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_cross_c3_debug_overrides_mml_lockdown(dut):
    """Cross §S8 ∩ §S6: MML=1 with all regions OFF would deny M-mode
    EXEC (REQ-MMWP-3); debug-mode bypass overrides it inside the DM
    window."""
    await _idle(dut)
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mml=1)
    # Plain mode: M-mode EXEC, no match, MML=1 → deny.
    dut.debug_mode_i.value = 0
    _drive_channel(dut, PMP_I, addr=0x0, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_EXEC)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1
    # Same setup, debug_mode=1, addr in DM window → allow.
    dut.debug_mode_i.value = 1
    await _settle(dut)
    assert _err(dut, PMP_I) == 0


@cocotb.test()
async def test_cross_c4_per_channel_with_multi_region_table(dut):
    """Cross §S5 ∩ §S9: A multi-region table yields different verdicts
    per channel because each channel addresses a different region."""
    await _idle(dut)
    # Region 0 NA4 R=1 at word 0x100 (i-fetch target).
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_NA4, R=1), 0x100)
    # Region 1 NA4 W=0,R=0,X=0 at word 0x200 (d-side denies).
    _drive_region(dut, 1, _pmp_cfg(mode=PMP_MODE_NA4), 0x200)
    # Channel 0: U-mode READ at 0x100 → allow.
    _drive_channel(dut, PMP_I, addr=0x100, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    # Channel 1: same addr as channel 0 (sharing).
    _drive_channel(dut, PMP_I2, addr=0x100, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    # Channel 2: U-mode WRITE at 0x200 → match but W=0 → deny.
    _drive_channel(dut, PMP_D, addr=0x200, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_WRITE)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    assert _err(dut, PMP_I2) == 0
    assert _err(dut, PMP_D) == 1


@cocotb.test()
async def test_cross_c5_tor_region0_vs_region1_chain(dut):
    """Cross §S2 ∩ §S5: Region 0 in TOR with addr0=0x80, region 1 in
    TOR with addr1=0x100. Region 0 covers [0..0x80), region 1 covers
    [0x80..0x100). Verify each address picks the right region."""
    await _idle(dut)
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_TOR, R=1), 0x80)
    _drive_region(dut, 1, _pmp_cfg(mode=PMP_MODE_TOR, R=0, W=0, X=0), 0x100)
    # 0x40 → region 0 (R=1) → allow.
    _drive_channel(dut, PMP_I, addr=0x40, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    # 0xC0 → region 1 (R=0) → deny.
    _drive_channel(dut, PMP_I, addr=0xC0, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1
    # 0x100 → no region matches → U-mode default deny.
    _drive_channel(dut, PMP_I, addr=0x100, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


# ─────────────────────────────────────────────────────────────────────────
# Edge-case sweeps
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_edge_all_zero_csr_mmode_allow(dut):
    """All CSR zero + M-mode + debug=0 → allow (MMWP=0 default-allow)."""
    await _idle(dut)
    for c in range(PMP_NUM_CHAN):
        _drive_channel(dut, c, addr=0xDEAD, priv=PRIV_LVL_M,
                       req_type=PMP_ACC_READ)
    await _settle(dut)
    for c in range(PMP_NUM_CHAN):
        assert _err(dut, c) == 0


@cocotb.test()
async def test_edge_all_one_addr_napot(dut):
    """NAPOT region with addr_bits = all-ones (32 bits set in word
    field) covers the entire 34-bit word space; any address matches."""
    await _idle(dut)
    all_ones = (1 << 34) - 1
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_NAPOT, R=1), all_ones)
    for word in [0x0, 0x100, 0xFFFF_FFFF, all_ones]:
        _drive_channel(dut, PMP_I, addr=word, priv=PRIV_LVL_U,
                       req_type=PMP_ACC_READ)
        await _settle(dut)
        assert _err(dut, PMP_I) == 0, f"word {word:#x} should match all-ones NAPOT"


@cocotb.test()
async def test_edge_napot_degenerate_4byte(dut):
    """A3: NAPOT smallest region at G=0 — when csr_addr[2] = 0,
    REQ-MODE-3 gives mask[3] = 1 (tag) and only mask[2] = 0 (size).
    Since bit 2 of addr is always size, the smallest NAPOT region
    is 8 bytes (not 4 — NA4 is the 4-byte mode). Use csr=0x0; the
    region matches bytes 0x0..0x7."""
    await _idle(dut)
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_NAPOT, R=1), 0x0)
    # Bytes 0x0..0x7 (in 8-byte region) → match.
    for byte_pa in [0x0, 0x4, 0x7]:
        _drive_channel(dut, PMP_I, addr=byte_pa, priv=PRIV_LVL_U,
                       req_type=PMP_ACC_READ)
        await _settle(dut)
        assert _err(dut, PMP_I) == 0, f"byte {byte_pa:#x} should match"
    # Byte 0x8 (next 8-byte block, outside) → no match → U-mode deny.
    _drive_channel(dut, PMP_I, addr=0x8, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_edge_every_region_mode_permutation(dut):
    """Sweep every (mode_0, mode_1, mode_2, mode_3) over OFF/TOR/NA4/NAPOT.
    Permutations are 4^4 = 256; for each, verify the module produces
    a defined output (no x-prop, no exception). We don't compare
    semantics — just that the verdict is 0 or 1 for a fixed request."""
    await _idle(dut)
    # Pick a single canonical request and a single canonical addr-bits
    # value that's safe for all modes (TOR gets 0x100, NAPOT gets a
    # NAPOT-encoding, etc.).
    addrs = {
        PMP_MODE_OFF:   0x100,
        PMP_MODE_TOR:   0x100,
        PMP_MODE_NA4:   0x100,
        PMP_MODE_NAPOT: 0x1F,  # 16-byte at base 0x10
    }
    cfgs = {
        m: _pmp_cfg(mode=m, R=1) for m in addrs
    }
    modes = [PMP_MODE_OFF, PMP_MODE_TOR, PMP_MODE_NA4, PMP_MODE_NAPOT]
    count = 0
    for m0 in modes:
        for m1 in modes:
            for m2 in modes:
                for m3 in modes:
                    for r, m in zip(range(4), (m0, m1, m2, m3)):
                        _drive_region(dut, r, cfgs[m], addrs[m])
                    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_U,
                                   req_type=PMP_ACC_READ)
                    await _settle(dut)
                    v = _err(dut, PMP_I)
                    assert v in (0, 1), f"mode tuple {(m0,m1,m2,m3)} → {v}"
                    count += 1
    assert count == 256


@cocotb.test()
async def test_edge_lrwx_combinations_non_mml(dut):
    """All 16 combinations of L/R/W/X under MML=0, M-mode and U-mode
    READ at a NAPOT-matching addr. Verifies REQ-PERM-2 / REQ-PERM-3
    truth tables exhaustively."""
    await _idle(dut)
    for L in (0, 1):
        for X in (0, 1):
            for W in (0, 1):
                for R in (0, 1):
                    cfg = _pmp_cfg(L=L, mode=PMP_MODE_NAPOT, X=X, W=W, R=R)
                    _drive_region(dut, 0, cfg, 0x1F)
                    # M-mode READ.
                    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_M,
                                   req_type=PMP_ACC_READ)
                    await _settle(dut)
                    # REQ-PERM-2: ~L | basic_R = ~L | R
                    expect_m_err = 0 if ((not L) or R) else 1
                    assert _err(dut, PMP_I) == expect_m_err, \
                        f"M-mode READ L={L} R={R}: got {_err(dut, PMP_I)}"
                    # U-mode READ.
                    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_U,
                                   req_type=PMP_ACC_READ)
                    await _settle(dut)
                    # REQ-PERM-3: basic_R = R
                    expect_u_err = 0 if R else 1
                    assert _err(dut, PMP_I) == expect_u_err, \
                        f"U-mode READ L={L} R={R}: got {_err(dut, PMP_I)}"


@cocotb.test()
async def test_edge_lrwx_combinations_mml(dut):
    """All 16 L/R/W/X combinations under MML=1 for M-mode READ. The
    {R=0,W=1} table (REQ-MML-1) and {L=W=R=X=1} (REQ-MML-2) overlay
    the lock-flip rule (REQ-MML-3); this test bakes in the spec-table
    expected verdicts."""
    await _idle(dut)
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mml=1)
    # Truth table for M-mode READ under MML, derived from the spec:
    # - REQ-MML-1 ({R=0,W=1}) rows for {L,X}:
    #     {L=0,X=0}: READ any → READ allow
    #     {L=0,X=1}: R/W any → READ allow
    #     {L=1,X=0}: EXEC only → READ deny
    #     {L=1,X=1}: EXEC any, READ M-only → READ allow (M)
    # - REQ-MML-2 (L=W=R=X=1): READ-only → READ allow
    # - REQ-MML-3 (else): basic_R & (M ? L : ~L) → for M-mode that's R & L
    expected_m_read = {}
    for L in (0, 1):
        for X in (0, 1):
            for W in (0, 1):
                for R in (0, 1):
                    if R == 0 and W == 1:
                        # REQ-MML-1 table
                        if (L, X) == (0, 0):
                            expected_m_read[(L, X, W, R)] = 0  # allow
                        elif (L, X) == (0, 1):
                            expected_m_read[(L, X, W, R)] = 0
                        elif (L, X) == (1, 0):
                            expected_m_read[(L, X, W, R)] = 1
                        else:  # (1,1)
                            expected_m_read[(L, X, W, R)] = 0  # M-mode read OK
                    elif L == 1 and W == 1 and R == 1 and X == 1:
                        expected_m_read[(L, X, W, R)] = 0  # READ allow
                    else:
                        # REQ-MML-3: R & L for M-mode
                        expected_m_read[(L, X, W, R)] = 0 if (R and L) else 1
    for (L, X, W, R), want in expected_m_read.items():
        cfg = _pmp_cfg(L=L, mode=PMP_MODE_NAPOT, X=X, W=W, R=R)
        _drive_region(dut, 0, cfg, 0x1F)
        _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_M,
                       req_type=PMP_ACC_READ)
        await _settle(dut)
        got = _err(dut, PMP_I)
        assert got == want, \
            f"MML M-READ L={L} X={X} W={W} R={R}: want {want}, got {got}"


@cocotb.test()
async def test_edge_reserved_req_type(dut):
    """A5: pmp_req_type_i == 2'b11 (reserved) yields denied for any
    matched region (basic_perm_check returns 0). Debug-bypass still
    overrides."""
    await _idle(dut)
    # Allow-everything region.
    _drive_region(dut, 0, _pmp_cfg(L=0, mode=PMP_MODE_NAPOT, X=1, W=1, R=1),
                  0x1F)
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_RSVD)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1
    # Debug + DM window still bypasses.
    dut.debug_mode_i.value = 1
    _drive_channel(dut, PMP_I, addr=0x0, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_RSVD)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0


@cocotb.test()
async def test_edge_mseccfg_rlb_unused(dut):
    """A4: rlb bit at the module boundary has NO effect on
    pmp_req_err_o. Toggling rlb across an arbitrary stimulus must
    leave the verdict unchanged."""
    await _idle(dut)
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_NA4, R=1), 0x100)
    _drive_channel(dut, PMP_I, addr=0x100, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    dut.csr_pmp_mseccfg_i.value = _mseccfg(rlb=0)
    await _settle(dut)
    a = _err(dut, PMP_I)
    dut.csr_pmp_mseccfg_i.value = _mseccfg(rlb=1)
    await _settle(dut)
    b = _err(dut, PMP_I)
    assert a == b == 0


@cocotb.test()
async def test_edge_tor_addr0_zero_lower(dut):
    """REQ-MODE-5 boundary: TOR region 0 + addr0=0 → range is [0, 0)
    which is empty — region 0 never matches, even at address 0."""
    await _idle(dut)
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_TOR, R=1), 0x0)
    _drive_channel(dut, PMP_I, addr=0x0, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    # No match → U-mode default deny.
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_edge_max_addr_width(dut):
    """REQ-MODE-2: NA4 with addr at the top of the 34-bit byte range.
    NA4 matches on bits [33:2], so an "off-by-one" must differ in
    bits [33:2], not just bits [1:0]."""
    await _idle(dut)
    top_addr = (1 << 34) - 1  # all 34 bits set
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_NA4, R=1), top_addr)
    _drive_channel(dut, PMP_I, addr=top_addr, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    # Differ at bit 2 (within the matched portion) → no match.
    _drive_channel(dut, PMP_I, addr=top_addr - 4, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_edge_debug_mode_no_dm_window(dut):
    """REQ-DBG-2: debug_mode=1 + addr outside DM window with no
    matching region + MMWP=1 → deny (debug bypass scope is only the
    DM window)."""
    await _idle(dut)
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mmwp=1)
    dut.debug_mode_i.value = 1
    _drive_channel(dut, PMP_I, addr=0x1000, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_EXEC)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_edge_priority_chain_all_four(dut):
    """REQ-PRIO-1 + REQ-CHAN-2 with all 4 regions matching the same
    address. Region 0 verdict should win whichever it is."""
    await _idle(dut)
    # All 4 regions NA4 at word 0x100, but different R bits.
    for r, R in zip(range(4), (1, 0, 1, 0)):
        _drive_region(dut, r, _pmp_cfg(mode=PMP_MODE_NA4, R=R), 0x100)
    _drive_channel(dut, PMP_I, addr=0x100, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0  # region 0 R=1 wins
    # Flip region 0.
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_NA4, R=0), 0x100)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_edge_mml_a1_retroactive_reinterpretation(dut):
    """A1: MML reinterprets all regions immediately on the cycle it
    is set; there is no module-internal latch. Setting MML must
    cause the verdict for an existing config to flip if the new
    rules disagree with the old."""
    await _idle(dut)
    # {L=1, R=0, W=0, X=1, NAPOT}: pre-MML, M-mode EXEC requires basic
    # X=1 ✓ → allow. U-mode EXEC: basic X=1 ✓ → allow.
    _drive_region(dut, 0, _pmp_cfg(L=1, mode=PMP_MODE_NAPOT, X=1), 0x1F)
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_EXEC)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0  # pre-MML U-EXEC allow
    # Set MML in the same continuous-comb evaluation; verdict must
    # flip because REQ-MML-3 needs L=0 for U-mode (we have L=1).
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mml=1)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1  # post-MML U-EXEC deny — A1 honored
