"""Standalone cocotb scenarios for `ibex_pmp` (basic suite).

PMP is a pure combinational permission checker. For each access channel
`c`, the module consumes a 34-bit physical address, an access type
(EXEC/WRITE/READ), and the requesting privilege mode, and against a
CSR-supplied region table (`csr_pmp_cfg_i`, `csr_pmp_addr_i`) plus ePMP
control (`csr_pmp_mseccfg_i`), it emits `pmp_req_err_o[c]` (`1` = deny).

There is one `@cocotb.test()` per RFC-2119 Requirement in
`changes/2026-05-06-port-ibex_pmp/specs/pmp/spec.md` (R-MODE 1..5,
R-PERM 1..3, R-MML 1..3, R-MMWP 1..4, R-DBG 1..3, R-PRIO 1, R-CHAN 1..3
= 22 tests). Settling is `Timer(1, "ns")` after every input change since
the DUT is fully combinational.

Spec ambiguity resolutions follow proposal §"Spec ambiguity resolutions"
(A1-A5), NOT the spec's flagged punt list.

Pinned parameters: DmBaseAddr=0, DmAddrMask=3, PMPGranularity=0,
PMPNumChan=3, PMPNumRegions=4.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer


# ── priv_lvl_e (only M vs not-M is distinguished) ────────────────────────
PRIV_LVL_M = 0b11
PRIV_LVL_U = 0b00

# ── pmp_req_e ────────────────────────────────────────────────────────────
PMP_ACC_EXEC  = 0b00
PMP_ACC_WRITE = 0b01
PMP_ACC_READ  = 0b10
PMP_ACC_RSVD  = 0b11  # reserved encoding (A5)

# ── pmp_cfg_mode_e ───────────────────────────────────────────────────────
PMP_MODE_OFF   = 0b00
PMP_MODE_TOR   = 0b01
PMP_MODE_NA4   = 0b10
PMP_MODE_NAPOT = 0b11

# ── Pinned parameters ────────────────────────────────────────────────────
PMP_NUM_REGIONS = 4
PMP_NUM_CHAN    = 3
DM_BASE_ADDR    = 0x0000_0000
DM_ADDR_MASK    = 0x0000_0003

# Convenience channel indices (matching upstream localparams in
# ibex_core.sv:177 — exposed in spec §"Pinned parameters").
PMP_I  = 0
PMP_I2 = 1
PMP_D  = 2


# ── Packing helpers ──────────────────────────────────────────────────────

def _pmp_cfg(*, L: int = 0, mode: int = PMP_MODE_OFF,
             X: int = 0, W: int = 0, R: int = 0) -> int:
    """Pack a 6-bit `pmp_cfg_t` per spec §"Type definitions":
    [5]=lock, [4:3]=mode, [2]=exec, [1]=write, [0]=read.
    """
    return ((L & 1) << 5) | ((mode & 3) << 3) | ((X & 1) << 2) \
        | ((W & 1) << 1) | (R & 1)


def _mseccfg(*, rlb: int = 0, mmwp: int = 0, mml: int = 0) -> int:
    """Pack a 3-bit `pmp_mseccfg_t`: [2]=rlb, [1]=mmwp, [0]=mml."""
    return ((rlb & 1) << 2) | ((mmwp & 1) << 1) | (mml & 1)


# ── Vec drivers ──────────────────────────────────────────────────────────

def _set_unpacked_vec(port, idx: int, val: int) -> None:
    """Drive one element of an unpacked Vec port."""
    port[idx].value = val


def _drive_region(dut, idx: int, cfg: int, addr: int) -> None:
    _set_unpacked_vec(dut.csr_pmp_cfg_i, idx, cfg)
    _set_unpacked_vec(dut.csr_pmp_addr_i, idx, addr & ((1 << 34) - 1))


def _zero_regions(dut) -> None:
    for r in range(PMP_NUM_REGIONS):
        _drive_region(dut, r, _pmp_cfg(), 0)


def _drive_channel(dut, c: int, *, addr: int = 0,
                   priv: int = PRIV_LVL_M,
                   req_type: int = PMP_ACC_EXEC) -> None:
    _set_unpacked_vec(dut.priv_mode_i, c, priv)
    _set_unpacked_vec(dut.pmp_req_addr_i, c, addr & ((1 << 34) - 1))
    _set_unpacked_vec(dut.pmp_req_type_i, c, req_type)


def _zero_channels(dut, *, priv: int = PRIV_LVL_U) -> None:
    for c in range(PMP_NUM_CHAN):
        _drive_channel(dut, c, addr=0, priv=priv, req_type=PMP_ACC_EXEC)


async def _idle(dut) -> None:
    """Drive a benign all-zero state, then settle."""
    _zero_regions(dut)
    _zero_channels(dut, priv=PRIV_LVL_M)
    dut.csr_pmp_mseccfg_i.value = _mseccfg()
    dut.debug_mode_i.value = 0
    await Timer(1, "ns")


async def _settle(dut) -> None:
    await Timer(1, "ns")


def _err(dut, c: int) -> int:
    return int(dut.pmp_req_err_o[c].value)


# ─────────────────────────────────────────────────────────────────────────
# R-MODE: region match modes
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_mode_1_off_never_matches(dut):
    """REQ-MODE-1: A region with `mode == PMP_MODE_OFF` SHALL never
    match, regardless of address. With all regions OFF and U-mode,
    the unmatched non-M-mode default-deny (REQ-MMWP-4) fires."""
    await _idle(dut)
    # Region 0: OFF, but with addr equal to the request — must NOT match.
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_OFF, R=1, W=1, X=1), 0x0000_1000)
    _drive_channel(dut, PMP_I, addr=0x0000_1000, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    # No region matches → non-M-mode → deny per REQ-MMWP-4.
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_r_mode_2_na4_exact_match(dut):
    """REQ-MODE-2: NA4 matches iff `pmp_req_addr_i[c][33:2] ==
    csr_pmp_addr_i[r][33:2]`. NA4 covers a 4-byte aligned region
    (the 4 bytes whose [33:2] match)."""
    await _idle(dut)
    # Region 0: NA4, R=1. csr_pmp_addr=0x100 means csr_pmp_addr[33:2] = 0x40,
    # so the NA4 region covers byte addrs 0x100..0x103.
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_NA4, R=1), 0x100)
    # Byte 0x100: req[33:2] = 0x40 == csr[33:2] = 0x40 → match.
    _drive_channel(dut, PMP_I, addr=0x100, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0  # match → R=1 grants
    # Byte 0x103 (still in the 4-byte region) → match.
    _drive_channel(dut, PMP_I, addr=0x103, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    # Byte 0x104 (next 4-byte block, [33:2] = 0x41) → no match → deny.
    _drive_channel(dut, PMP_I, addr=0x104, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1  # no match → U-mode default deny


@cocotb.test()
async def test_r_mode_3_napot_mask(dut):
    """REQ-MODE-3: NAPOT matches addresses whose top bits agree under
    a mask derived from the trailing-ones encoding in csr_pmp_addr.
    Per spec REQ-MODE-3 algorithm: `mask[b]=0 iff csr_addr[b-1:2] all-
    ones`. For csr_addr=0x14 = 0b10100: bit 2 = 1, bit 3 = 0; mask
    covers addr bits [3:2] (size); tag bits [33:4] = 1 → region at
    byte base 0x10, 16 bytes. (Note: this differs from canonical
    RISC-V NAPOT encoding, which uses trailing 1s starting at bit 0
    of pmpaddr; Ibex's algorithm slices bits [33:2] only — see spec
    A3 resolution.)"""
    await _idle(dut)
    # csr=0x14: bit 2=1, bit 4=1, others=0. Encodes "16-byte at base 0x10".
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_NAPOT, R=1), 0x14)
    # Byte addrs 0x10..0x1F must hit; 0xF and 0x20 must miss.
    for byte_pa in [0x10, 0x14, 0x18, 0x1F]:
        _drive_channel(dut, PMP_I, addr=byte_pa, priv=PRIV_LVL_U,
                       req_type=PMP_ACC_READ)
        await _settle(dut)
        assert _err(dut, PMP_I) == 0, f"byte {byte_pa:#x} should hit"
    for byte_pa in [0xF, 0x20]:
        _drive_channel(dut, PMP_I, addr=byte_pa, priv=PRIV_LVL_U,
                       req_type=PMP_ACC_READ)
        await _settle(dut)
        assert _err(dut, PMP_I) == 1, f"byte {byte_pa:#x} should miss"


@cocotb.test()
async def test_r_mode_4_tor_inclusive_lower_exclusive_upper(dut):
    """REQ-MODE-4: TOR region r>0 matches iff
    csr_pmp_addr_i[r-1] <= addr < csr_pmp_addr_i[r]."""
    await _idle(dut)
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_OFF), 0x100)  # supplies the lower bound
    _drive_region(dut, 1, _pmp_cfg(mode=PMP_MODE_TOR, R=1), 0x200)
    # 0x100 inclusive — match.
    _drive_channel(dut, PMP_I, addr=0x100, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    # 0x1FF — match.
    _drive_channel(dut, PMP_I, addr=0x1FF, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    # 0x200 exclusive upper — no match → U-mode default deny.
    _drive_channel(dut, PMP_I, addr=0x200, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_r_mode_5_tor_region0_lower_is_zero(dut):
    """REQ-MODE-5: Region 0 in TOR mode uses 0 as its lower bound."""
    await _idle(dut)
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_TOR, R=1), 0x80)
    # addr 0 matches (lower bound).
    _drive_channel(dut, PMP_I, addr=0x0, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    # addr 0x7F matches (just below upper bound).
    _drive_channel(dut, PMP_I, addr=0x7F, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    # addr 0x80 misses (exclusive upper).
    _drive_channel(dut, PMP_I, addr=0x80, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


# ─────────────────────────────────────────────────────────────────────────
# R-PERM: basic permission rules
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_perm_1_basic_perm_check_encoding(dut):
    """REQ-PERM-1: basic_perm_check picks `cfg.exec` for EXEC,
    `cfg.write` for WRITE, `cfg.read` for READ. Locked region under
    M-mode forces basic gate (REQ-PERM-2)."""
    await _idle(dut)
    # Locked region with X=1, W=0, R=1 — distinguishes the three types.
    _drive_region(dut, 0, _pmp_cfg(L=1, mode=PMP_MODE_NAPOT, X=1, W=0, R=1),
                  0x1F)
    # M-mode (so lock matters) at addr 0x4 (in window).
    for req, want_err in [
        (PMP_ACC_EXEC,  0),  # X=1 → allow
        (PMP_ACC_WRITE, 1),  # W=0 → deny
        (PMP_ACC_READ,  0),  # R=1 → allow
    ]:
        _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_M, req_type=req)
        await _settle(dut)
        assert _err(dut, PMP_I) == want_err, f"req {req} → err {want_err}"


@cocotb.test()
async def test_r_perm_2_mml0_mmode_lock_gates_basic(dut):
    """REQ-PERM-2: With MML=0, M-mode access is allowed if the region
    is unlocked (lock=0 grants regardless of basic bits) OR if locked
    AND the basic R/W/X bit is set."""
    await _idle(dut)
    # Region 0: unlocked, R=W=X=0 — M-mode still allowed (~lock | basic = 1).
    _drive_region(dut, 0, _pmp_cfg(L=0, mode=PMP_MODE_NAPOT, X=0, W=0, R=0),
                  0x1F)
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    # Region 0: locked, R=W=X=0 — M-mode now denied.
    _drive_region(dut, 0, _pmp_cfg(L=1, mode=PMP_MODE_NAPOT, X=0, W=0, R=0),
                  0x1F)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1
    # Region 0: locked, R=1 — read allowed, write denied.
    _drive_region(dut, 0, _pmp_cfg(L=1, mode=PMP_MODE_NAPOT, X=0, W=0, R=1),
                  0x1F)
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_WRITE)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_r_perm_3_mml0_nonmmode_basic_only(dut):
    """REQ-PERM-3: With MML=0 and non-M-mode, lock is irrelevant —
    only the basic R/W/X bit matters."""
    await _idle(dut)
    # Locked region, R=1 only. U-mode read → allowed; U-mode write → denied.
    _drive_region(dut, 0, _pmp_cfg(L=1, mode=PMP_MODE_NAPOT, X=0, W=0, R=1),
                  0x1F)
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_WRITE)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1
    # Unlocked, R=0 — U-mode read still denied (lock irrelevant; basic=0).
    _drive_region(dut, 0, _pmp_cfg(L=0, mode=PMP_MODE_NAPOT, X=0, W=0, R=0),
                  0x1F)
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


# ─────────────────────────────────────────────────────────────────────────
# R-MML: Machine Mode Lockdown
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_mml_1_shared_region_table(dut):
    """REQ-MML-1: With MML=1 and {R=0, W=1}, the four-row {L, X} table
    governs READ/WRITE. Spot-check {L=0,X=0}: READ any mode, WRITE
    M-mode only."""
    await _idle(dut)
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mml=1)
    # {L=0, X=0, R=0, W=1}: READ any, WRITE M only.
    _drive_region(dut, 0, _pmp_cfg(L=0, mode=PMP_MODE_NAPOT, X=0, W=1, R=0),
                  0x1F)
    # M-mode READ → allow.
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    # U-mode READ → allow.
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    # M-mode WRITE → allow.
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_WRITE)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    # U-mode WRITE → deny.
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_WRITE)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_r_mml_2_shared_read_only(dut):
    """REQ-MML-2: With MML=1 and L=W=R=X=1, only READ is granted
    regardless of privilege."""
    await _idle(dut)
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mml=1)
    _drive_region(dut, 0, _pmp_cfg(L=1, mode=PMP_MODE_NAPOT, X=1, W=1, R=1),
                  0x1F)
    # READ allowed any mode.
    for priv in (PRIV_LVL_M, PRIV_LVL_U):
        _drive_channel(dut, PMP_I, addr=0x4, priv=priv,
                       req_type=PMP_ACC_READ)
        await _settle(dut)
        assert _err(dut, PMP_I) == 0
    # WRITE / EXEC denied any mode.
    for priv in (PRIV_LVL_M, PRIV_LVL_U):
        for req in (PMP_ACC_WRITE, PMP_ACC_EXEC):
            _drive_channel(dut, PMP_I, addr=0x4, priv=priv, req_type=req)
            await _settle(dut)
            assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_r_mml_3_lock_bit_polarity_flips(dut):
    """REQ-MML-3: Outside the special MML rows of REQ-MML-1/-2, the
    lock-bit polarity flips: M-mode requires lock=1, non-M-mode requires
    lock=0. Spec scenario S6: {L=1, X=1, R=0, W=0} encodes M-only EXEC."""
    await _idle(dut)
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mml=1)
    _drive_region(dut, 0, _pmp_cfg(L=1, mode=PMP_MODE_NAPOT, X=1, W=0, R=0),
                  0x1F)
    # M-mode EXEC → allow.
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_EXEC)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    # U-mode EXEC → deny (lock-flip).
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_EXEC)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1
    # Counter-case: {L=0, X=1, R=0, W=0} — non-M-only EXEC.
    _drive_region(dut, 0, _pmp_cfg(L=0, mode=PMP_MODE_NAPOT, X=1, W=0, R=0),
                  0x1F)
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_EXEC)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_EXEC)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


# ─────────────────────────────────────────────────────────────────────────
# R-MMWP: Machine Mode Whitelist Policy
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_mmwp_1_unmatched_always_deny(dut):
    """REQ-MMWP-1: With MMWP=1 and no matching region, deny regardless
    of privilege. Spec scenario S7."""
    await _idle(dut)
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mmwp=1)
    # All regions OFF, M-mode access — must deny.
    _drive_channel(dut, PMP_I, addr=0x1234, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_r_mmwp_2_mmode_default_allow(dut):
    """REQ-MMWP-2: With MMWP=0, no matching region, M-mode access is
    allowed (modulo the MML M-mode-EXEC clause covered by REQ-MMWP-3)."""
    await _idle(dut)
    # MMWP=0, MML=0, all regions OFF, M-mode → allow.
    _drive_channel(dut, PMP_I, addr=0x1234, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    # M-mode EXEC also allowed (MML=0, so REQ-MMWP-3 doesn't trigger).
    _drive_channel(dut, PMP_I, addr=0x1234, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_EXEC)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0


@cocotb.test()
async def test_r_mmwp_3_mml_mmode_exec_requires_match(dut):
    """REQ-MMWP-3: With MML=1 and M-mode EXEC, a missing region match
    forces deny even when MMWP=0."""
    await _idle(dut)
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mml=1)  # MMWP=0, MML=1
    # All regions OFF, M-mode EXEC → deny.
    _drive_channel(dut, PMP_I, addr=0x1234, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_EXEC)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1
    # M-mode READ under same conditions must still allow (MMWP-2 path).
    _drive_channel(dut, PMP_I, addr=0x1234, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0


@cocotb.test()
async def test_r_mmwp_4_nonmmode_default_deny(dut):
    """REQ-MMWP-4: Non-M-mode with no matching region denies regardless
    of mseccfg. Spec scenario S10."""
    await _idle(dut)
    # MMWP=0, MML=0, all regions OFF, U-mode → deny.
    _drive_channel(dut, PMP_I, addr=0x1234, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


# ─────────────────────────────────────────────────────────────────────────
# R-DBG: Debug-mode bypass
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_dbg_1_dm_address_bypass(dut):
    """REQ-DBG-1: In debug mode and address inside the DM window
    (DmBaseAddr=0, DmAddrMask=3 → bytes 0x0..0x3), the access is
    allowed regardless of region/MML/MMWP. Scenario S8."""
    await _idle(dut)
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mmwp=1)  # would normally deny
    dut.debug_mode_i.value = 1
    # addr-bits = 0 → bytes [0..3] in the bypass window.
    _drive_channel(dut, PMP_I, addr=0x0, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_EXEC)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0


@cocotb.test()
async def test_r_dbg_2_bypass_scope(dut):
    """REQ-DBG-2: Debug mode does NOT blanket-bypass — addresses
    outside the DM window go through the normal PMP check."""
    await _idle(dut)
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mmwp=1)
    dut.debug_mode_i.value = 1
    # DM window with DmBaseAddr=0, DmAddrMask=3 covers bytes 0x0..0x3.
    # Byte addr 0x4 is outside the window.
    _drive_channel(dut, PMP_I, addr=0x4, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_EXEC)
    await _settle(dut)
    # MMWP=1, no match → deny (debug bypass doesn't apply).
    assert _err(dut, PMP_I) == 1


@cocotb.test()
async def test_r_dbg_3_bypass_uses_low32_only(dut):
    """REQ-DBG-3: Bypass test consumes `pmp_req_addr_i[c][31:0]` only;
    bits [33:32] of the 34-bit address port are ignored.

    The 34-bit port carries the upper bits of the byte PA; bit-33 of
    the port maps to byte-PA bit-35 (out of byte-[31:0] entirely). So
    we set port bits [33:32] high while keeping port bits [31:0] = 0,
    placing byte-PA[31:0] inside the [0..3] DM window."""
    await _idle(dut)
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mmwp=1)
    dut.debug_mode_i.value = 1
    # port bits [33:32] = 0b11, [31:0] = 0 → byte-PA[31:0] = 0 (in window).
    addr_above_32 = (0b11 << 32) | 0
    _drive_channel(dut, PMP_I, addr=addr_above_32, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_EXEC)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    # Sanity: same upper bits but with byte-PA[31:0] = 0x4 (outside
    # the [0..3] DM window) must still deny.
    addr_outside = (0b11 << 32) | 0x4
    _drive_channel(dut, PMP_I, addr=addr_outside, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_EXEC)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1


# ─────────────────────────────────────────────────────────────────────────
# R-PRIO: Region priority
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_prio_1_lowest_index_wins(dut):
    """REQ-PRIO-1: When multiple regions match, the lowest-index match
    decides. Spec scenario S5."""
    await _idle(dut)
    # Region 0 NA4 R=1, region 2 NA4 R=0; both at addr 0x100.
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_NA4, R=1), 0x100)
    _drive_region(dut, 2, _pmp_cfg(mode=PMP_MODE_NA4, R=0), 0x100)
    _drive_channel(dut, PMP_I, addr=0x100, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0  # region 0 (allow) wins
    # Swap roles — region 0 denies, region 2 allows.
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_NA4, R=0), 0x100)
    _drive_region(dut, 2, _pmp_cfg(mode=PMP_MODE_NA4, R=1), 0x100)
    await _settle(dut)
    assert _err(dut, PMP_I) == 1  # region 0 (deny) wins


# ─────────────────────────────────────────────────────────────────────────
# R-CHAN: Per-channel independence
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_chan_1_channels_independent(dut):
    """REQ-CHAN-1: Each channel's `pmp_req_err_o[c]` depends only on
    its own per-channel inputs (plus the shared CSR/debug inputs)."""
    await _idle(dut)
    # Region 0: NA4, R=1 only at addr 0x100.
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_NA4, R=1), 0x100)
    # Channel 0: U-mode READ at 0x100 (matches → allow).
    _drive_channel(dut, PMP_I, addr=0x100, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    # Channel 2: U-mode READ at 0x200 (no match → deny per REQ-MMWP-4).
    _drive_channel(dut, PMP_D, addr=0x200, priv=PRIV_LVL_U,
                   req_type=PMP_ACC_READ)
    await _settle(dut)
    assert _err(dut, PMP_I) == 0
    assert _err(dut, PMP_D) == 1


@cocotb.test()
async def test_r_chan_2_shared_region_table(dut):
    """REQ-CHAN-2: All channels see the same region table; identical
    per-channel inputs yield identical outputs."""
    await _idle(dut)
    _drive_region(dut, 0, _pmp_cfg(mode=PMP_MODE_NA4, R=1), 0x100)
    # Drive every channel with the same address / priv / type.
    for c in range(PMP_NUM_CHAN):
        _drive_channel(dut, c, addr=0x100, priv=PRIV_LVL_U,
                       req_type=PMP_ACC_READ)
    await _settle(dut)
    for c in range(PMP_NUM_CHAN):
        assert _err(dut, c) == 0, f"channel {c} should match-allow"


@cocotb.test()
async def test_r_chan_3_output_formula(dut):
    """REQ-CHAN-3: Output = ~debug_mode_allowed_access & access_fault.
    Verified by toggling the debug bypass over a would-be-denying
    setup: with MMWP=1 and no match, plain mode denies; debug mode
    in the DM window flips it to 0."""
    await _idle(dut)
    dut.csr_pmp_mseccfg_i.value = _mseccfg(mmwp=1)
    # No match, M-mode → would deny.
    _drive_channel(dut, PMP_I, addr=0x0, priv=PRIV_LVL_M,
                   req_type=PMP_ACC_EXEC)
    dut.debug_mode_i.value = 0
    await _settle(dut)
    assert _err(dut, PMP_I) == 1  # access_fault=1, dbg_allow=0 → err=1
    # Same setup but debug_mode_i = 1, addr=0 (in DM window).
    dut.debug_mode_i.value = 1
    await _settle(dut)
    assert _err(dut, PMP_I) == 0  # dbg_allow=1 → err=0
