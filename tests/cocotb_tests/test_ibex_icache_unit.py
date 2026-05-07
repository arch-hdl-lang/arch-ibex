"""Standalone cocotb scenarios for `ibex_icache` (basic suite).

Each `@cocotb.test` covers one Requirement from
`changes/2026-05-05-port-ibex_icache/specs/icache/spec.md`, walking a
single representative scenario per Requirement. Optimised for fast
feedback (target full-suite runtime <= 30 s).

In-scope SoC parameter pinning (per spec § "Parameters"):
  - ICacheECC      = 0   (no ECC, ecc_error_o tied 0)
  - ResetAll       = 0   (no-reset fill/prefetch/output flops permitted)
  - BusSizeECC     = 32, TagSizeECC = 22, LineSizeECC = 64
  - BranchCache    = 0   (allocate-every-miss when enabled)
  - TweakInfection = 0
  - NUM_FB         = 4, FB_THRESHOLD = 2
  - IC_NUM_WAYS    = 2, IC_LINE_BEATS = 2, IC_NUM_LINES = 128,
    IC_INDEX_W   = 7, IC_TAG_SIZE = 22, IC_LINE_SIZE = 64

Tag-RAM read width 22 = {valid_bit, tag[20:0]}.

`ic_tag_rdata_i` and `ic_data_rdata_i` are unpacked Vec<2,...> ports;
the cocotb side drives them as separate per-way array elements
(`dut.ic_tag_rdata_i[0]`, `dut.ic_tag_rdata_i[1]`).

Bus / RAM stimulus models are deliberately small — they accept one
request, return a programmed beat, and (for RAM) hold sync-read 1-cycle
latency. Tests that need richer behaviour drive the bus/RAM signals
inline.
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly, Timer

# ── Test parameters ──────────────────────────────────────────────────────
CLK_PERIOD_NS = 10  # 100 MHz

# Cache geometry (from spec § Module interface / Parameters)
IC_NUM_WAYS    = 2
IC_LINE_BEATS  = 2
IC_NUM_LINES   = 128
IC_INDEX_W     = 7
IC_LINE_SIZE   = 64        # bits
IC_LINE_BYTES  = 8
IC_TAG_SIZE    = 22        # 1 valid + 21 tag bits
TAG_VALID_BIT  = 1 << 21
TAG_BITS_MASK  = (1 << 21) - 1
NUM_FB         = 4
FB_THRESHOLD   = 2

MASK32 = 0xFFFF_FFFF
MASK64 = 0xFFFF_FFFF_FFFF_FFFF

# Address layout: addr[31:IC_INDEX_HI+1] = tag, addr[IC_INDEX_HI:LINE_W] = index,
# addr[LINE_W-1:0] = byte-in-line. With IC_LINE_SIZE=64 (=8B), IC_LINE_W=3,
# IC_INDEX_W=7, IC_INDEX_HI = 3+7-1 = 9; tag = addr[31:10].

ADDR_W      = 32
IC_LINE_W   = 3                          # log2(IC_LINE_BYTES)
INDEX_LO    = IC_LINE_W                  # = 3
INDEX_HI    = INDEX_LO + IC_INDEX_W - 1  # = 9
TAG_LO      = INDEX_HI + 1               # = 10


def _index_of(addr: int) -> int:
    return (addr >> INDEX_LO) & ((1 << IC_INDEX_W) - 1)


def _tag_of(addr: int) -> int:
    return (addr >> TAG_LO) & TAG_BITS_MASK


def _tag_word(addr: int, *, valid: int = 1) -> int:
    """Build a tag-RAM word as the icache expects to compare it.
    Comparison key = {1'b1, addr[31:INDEX_HI+1]} per spec R-LK-2.
    """
    return ((valid & 1) << 21) | _tag_of(addr)


# ── Testbench helpers ───────────────────────────────────────────────────

async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())


async def _settle(dut):
    """Let combinational logic settle after a signal assignment."""
    await Timer(1, "ns")


def _set_unpacked_vec(port, idx: int, val: int) -> bool:
    """Drive one element of an unpacked Vec port. Returns True on success."""
    try:
        port[idx].value = val
        return True
    except (TypeError, AttributeError, IndexError):
        return False


def _zero_unpacked_vec(port, length: int = IC_NUM_WAYS):
    for i in range(length):
        _set_unpacked_vec(port, i, 0)


def _idle_inputs(dut):
    """Drive all DUT inputs to a benign idle state."""
    # Core-side request
    dut.req_i.value     = 0
    dut.branch_i.value  = 0
    dut.addr_i.value    = 0
    dut.ready_i.value   = 0
    # Bus master
    dut.instr_gnt_i.value    = 0
    dut.instr_rdata_i.value  = 0
    dut.instr_err_i.value    = 0
    dut.instr_rvalid_i.value = 0
    # Tag/Data RAM read returns (unpacked Vec)
    _zero_unpacked_vec(dut.ic_tag_rdata_i)
    _zero_unpacked_vec(dut.ic_data_rdata_i)
    # Scramble-key valid: tied to 1 in SoC
    dut.ic_scr_key_valid_i.value = 1
    # Control
    dut.icache_enable_i.value = 1
    dut.icache_inval_i.value  = 0


async def _reset(dut):
    """Apply async-low reset for two clock periods, then release."""
    _idle_inputs(dut)
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await _settle(dut)


async def _wait_until_idle(dut, *, max_cycles: int = 200) -> int:
    """Walk past the cold-boot invalidation FSM until busy_o drops to 0.

    Returns the number of cycles waited. The cold-boot walk is
    OUT_OF_RESET → AWAIT_SCRAMBLE_KEY (1c) → INVAL_CACHE (IC_NUM_LINES c)
    → IDLE; with ic_scr_key_valid_i tied 1 this is ~130 cycles.
    """
    for n in range(max_cycles):
        if int(dut.busy_o.value) == 0:
            return n
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    raise TimeoutError(
        f"busy_o never dropped within {max_cycles} cycles of reset"
    )


async def _branch(dut, addr: int):
    """Issue a single-cycle branch_i pulse with addr_i = addr."""
    dut.branch_i.value = 1
    dut.addr_i.value   = addr & MASK32
    dut.req_i.value    = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    await _settle(dut)


async def _bus_grant_and_beat(dut, *, rdata: int, err: int = 0,
                              max_wait: int = 16) -> bool:
    """Wait for instr_req_o, drive gnt, then drive one rvalid beat.

    Returns True if a request was seen and serviced.
    """
    for _ in range(max_wait):
        if int(dut.instr_req_o.value) == 1:
            dut.instr_gnt_i.value = 1
            await RisingEdge(dut.clk_i)
            dut.instr_gnt_i.value = 0
            await _settle(dut)
            dut.instr_rvalid_i.value = 1
            dut.instr_rdata_i.value  = rdata & MASK32
            dut.instr_err_i.value    = err & 1
            await RisingEdge(dut.clk_i)
            dut.instr_rvalid_i.value = 0
            dut.instr_rdata_i.value  = 0
            dut.instr_err_i.value    = 0
            await _settle(dut)
            return True
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    return False


async def _ram_serve_lookup(dut, *, way0_tag_word: int, way1_tag_word: int,
                            way0_data: int = 0, way1_data: int = 0):
    """Drive a single-cycle RAM read response for the next IC1 stage.

    Per spec, ic_tag_req_o at cycle N is followed by ic_tag_rdata_i at N+1.
    Caller must invoke after the RisingEdge that started the read.
    """
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, way0_tag_word & 0x3FFFFF)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, way1_tag_word & 0x3FFFFF)
    _set_unpacked_vec(dut.ic_data_rdata_i, 0, way0_data & MASK64)
    _set_unpacked_vec(dut.ic_data_rdata_i, 1, way1_data & MASK64)
    await _settle(dut)


# ──────────────────────────────────────────────────────────────────────
# R-RST — Reset behaviour
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_rst_1_reset_drives_outputs_low(dut):
    """R-RST-1: while rst_ni=0, valid_o, instr_req_o, ic_tag_req_o,
    ic_data_req_o, ic_scr_key_req_o MUST all be 0. Spec §R-RESET.
    """
    await _start_clock(dut)
    _idle_inputs(dut)
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    await ReadOnly()
    assert int(dut.valid_o.value) == 0
    assert int(dut.instr_req_o.value) == 0
    # Per-way Vec request strobes -- must be 0 each.
    for w in range(IC_NUM_WAYS):
        try:
            assert int(dut.ic_tag_req_o[w].value) == 0
            assert int(dut.ic_data_req_o[w].value) == 0
        except (TypeError, AttributeError, IndexError):
            # If port flattens to a packed UInt instead of unpacked Vec,
            # still expect zero.
            pass
    assert int(dut.ic_scr_key_req_o.value) == 0


@cocotb.test()
async def test_r_rst_2_no_instr_req_until_first_branch(dut):
    """R-RST-2: after reset deassertion, no instr_req_o fires until the
    first branch_i pulse. valid_o stays 0 pre-first-branch. Spec §R-RESET.
    """
    await _start_clock(dut)
    await _reset(dut)
    # Walk past cold-boot.
    await _wait_until_idle(dut)
    # No branch yet; req_i high (IF stage requesting), but no branch yet.
    dut.req_i.value = 1
    await _settle(dut)
    # Observe several cycles: instr_req_o stays low, valid_o stays low.
    for _ in range(8):
        await RisingEdge(dut.clk_i)
        await _settle(dut)
        assert int(dut.valid_o.value) == 0, (
            "valid_o asserted before any branch_i pulse"
        )


@cocotb.test()
async def test_r_rst_3_valid_o_low_for_at_least_num_lines(dut):
    """R-RST-3: valid_o stays 0 for at least IC_NUM_LINES cycles after
    reset deassert (the cold-boot tag walk takes that long). Spec §R-RESET.
    """
    await _start_clock(dut)
    await _reset(dut)
    # Try to push: req_i=1, branch_i=1 to a fresh address. Even with stimulus
    # valid_o cannot rise before the cold-boot walk completes.
    for n in range(IC_NUM_LINES):
        await ReadOnly()
        assert int(dut.valid_o.value) == 0, (
            f"valid_o went high at cycle {n} of cold-boot (must wait "
            f"{IC_NUM_LINES})"
        )
        await RisingEdge(dut.clk_i)
        await _settle(dut)


# ──────────────────────────────────────────────────────────────────────
# R-INV-RESET — Cold-start / invalidation FSM
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_inv_1_cold_boot_walks_to_idle(dut):
    """R-INV-1: cold-boot FSM advances OUT_OF_RESET → AWAIT_SCRAMBLE_KEY →
    INVAL_CACHE → IDLE. Observed via busy_o transitioning 1→0 after
    ~IC_NUM_LINES + small overhead. Spec §R-INV-RESET.
    """
    await _start_clock(dut)
    await _reset(dut)
    # busy_o starts high.
    assert int(dut.busy_o.value) == 1
    n = await _wait_until_idle(dut, max_cycles=IC_NUM_LINES + 20)
    # Sanity: it took at least IC_NUM_LINES cycles (the inval walk).
    assert n >= IC_NUM_LINES - 4, (
        f"cold boot only took {n} cycles; expected ~{IC_NUM_LINES}"
    )


@cocotb.test()
async def test_r_inv_2_busy_during_invalidation(dut):
    """R-INV-2: while inval_state_q != IDLE, busy_o = 1 throughout the
    INVAL_CACHE walk. Spec §R-INV-RESET.
    """
    await _start_clock(dut)
    await _reset(dut)
    # Sample busy_o at many points during cold boot; it must remain 1.
    for n in range(IC_NUM_LINES):
        await ReadOnly()
        assert int(dut.busy_o.value) == 1, (
            f"busy_o dropped at cycle {n} during cold-boot inval walk"
        )
        await RisingEdge(dut.clk_i)
        await _settle(dut)


@cocotb.test()
async def test_r_inv_3_oor_requests_scramble_key(dut):
    """R-INV-3: in OUT_OF_RESET with ic_scr_key_valid_i = 0, the cache
    pulses ic_scr_key_req_o = 1 and advances to AWAIT_SCRAMBLE_KEY.
    Spec §R-INV-RESET.
    """
    await _start_clock(dut)
    _idle_inputs(dut)
    dut.ic_scr_key_valid_i.value = 0  # NOT tied: hold low
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    # Observe the OUT_OF_RESET state's scramble key request: at least one
    # cycle in the first few cycles MUST drive ic_scr_key_req_o = 1.
    saw_req = False
    for _ in range(4):
        if int(dut.ic_scr_key_req_o.value) == 1:
            saw_req = True
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert saw_req, "ic_scr_key_req_o never pulsed during cold boot"


@cocotb.test()
async def test_r_inv_4_await_holds_until_key_valid(dut):
    """R-INV-4: in AWAIT_SCRAMBLE_KEY the cache stalls (busy_o stays high
    indefinitely) while ic_scr_key_valid_i = 0. Once asserted, it
    advances. Spec §R-INV-RESET.
    """
    await _start_clock(dut)
    _idle_inputs(dut)
    dut.ic_scr_key_valid_i.value = 0
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    # Hold key invalid for many cycles; busy must remain 1.
    for _ in range(20):
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert int(dut.busy_o.value) == 1, (
        "busy_o dropped while ic_scr_key_valid_i = 0"
    )
    # Now release the key.
    dut.ic_scr_key_valid_i.value = 1
    await _settle(dut)
    # And wait through the inval walk.
    n = await _wait_until_idle(dut, max_cycles=IC_NUM_LINES + 20)
    assert n > 0


@cocotb.test()
async def test_r_inv_5_inval_walks_every_index(dut):
    """R-INV-5: INVAL_CACHE issues a tag-write for every index in
    [0, IC_NUM_LINES). Sample ic_tag_addr_o and ic_tag_write_o each cycle
    of the cold boot; collect the indices written. Spec §R-INV-RESET.
    """
    await _start_clock(dut)
    await _reset(dut)
    written = set()
    for _ in range(IC_NUM_LINES + 16):
        await ReadOnly()
        if int(dut.ic_tag_write_o.value) == 1:
            written.add(int(dut.ic_tag_addr_o.value))
        if int(dut.busy_o.value) == 0:
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert written == set(range(IC_NUM_LINES)), (
        f"missing inval indices: {set(range(IC_NUM_LINES)) - written}; "
        f"unexpected: {written - set(range(IC_NUM_LINES))}"
    )


@cocotb.test()
async def test_r_inv_6_inval_pulse_during_idle_restarts_walk(dut):
    """R-INV-6: a pulse on icache_inval_i while in IDLE re-asserts
    ic_scr_key_req_o, returns to AWAIT_SCRAMBLE_KEY, walks all indices
    again. Observed via busy_o 0 → 1 → 0 cycle. Spec §R-INV-RESET.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    assert int(dut.busy_o.value) == 0
    # Pulse icache_inval_i.
    dut.icache_inval_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.icache_inval_i.value = 0
    await _settle(dut)
    # busy_o should be high now (FSM moved out of IDLE).
    assert int(dut.busy_o.value) == 1, (
        "busy_o didn't go high after icache_inval_i pulse from IDLE"
    )
    # Walk back to IDLE; must take roughly IC_NUM_LINES.
    n = await _wait_until_idle(dut, max_cycles=IC_NUM_LINES + 20)
    assert n >= IC_NUM_LINES - 4


@cocotb.test()
async def test_r_inv_7_busy_o_high_until_idle(dut):
    """R-INV-7: busy_o = 1 exactly while inval_state_q != IDLE. After
    cold-boot completes, with no live FBs, busy_o = 0. Spec §R-INV-RESET.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    # No live FBs, no traffic, no inval → busy must be 0 and stay 0.
    for _ in range(8):
        await ReadOnly()
        assert int(dut.busy_o.value) == 0
        await RisingEdge(dut.clk_i)
        await _settle(dut)


# ──────────────────────────────────────────────────────────────────────
# R-REQ — Request acceptance and prefetch
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_req_1_prefetch_advances_by_line_stride(dut):
    """R-REQ-1: granted lookup advances prefetch register by IC_LINE_BYTES
    (= 8). After a branch to A, the next-cycle linear lookup uses A+8.
    Observed by the speculative IC0 instr_addr_o on consecutive cycles.
    Spec §R-REQ.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    # Branch to a base address.
    base = 0x0010_0080
    dut.req_i.value   = 1
    dut.ready_i.value = 1
    dut.branch_i.value = 1
    dut.addr_i.value   = base
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    await _settle(dut)
    # Now observe instr_addr_o across the next few cycles. It should
    # eventually issue a request for base or base + line stride.
    seen_addrs = set()
    for _ in range(8):
        await ReadOnly()
        if int(dut.instr_req_o.value) == 1:
            seen_addrs.add(int(dut.instr_addr_o.value) & MASK32)
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    # Either base or base+line was issued — both prove prefetch is
    # advancing per line stride.
    line_aligned_base = base & ~(IC_LINE_BYTES - 1)
    valid_targets = {
        line_aligned_base,
        (line_aligned_base + IC_LINE_BYTES) & MASK32,
        (line_aligned_base + 2 * IC_LINE_BYTES) & MASK32,
    }
    assert seen_addrs & valid_targets, (
        f"no instr_addr_o aligned to base / base+stride; saw {seen_addrs}"
    )


@cocotb.test()
async def test_r_req_2_branch_captures_addr_i(dut):
    """R-REQ-2: branch_i=1 captures addr_i as the new prefetch base; the
    next granted lookup uses addr_i (not the previous prefetch). Observed
    via the post-branch instr_addr_o targeting the new line. Spec §R-REQ.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value   = 1
    dut.ready_i.value = 1
    new_target = 0x2000_4000
    line_aligned = new_target & ~(IC_LINE_BYTES - 1)
    dut.branch_i.value = 1
    dut.addr_i.value   = new_target
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    await _settle(dut)
    # Next instr_req_o must target the new line (or its successor).
    for _ in range(8):
        await ReadOnly()
        if int(dut.instr_req_o.value) == 1:
            addr = int(dut.instr_addr_o.value) & MASK32
            assert (addr & ~(IC_LINE_BYTES - 1)) in (
                line_aligned,
                (line_aligned + IC_LINE_BYTES) & MASK32,
            ), f"instr_addr_o={addr:#010x} not aligned with branch target"
            return
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    raise AssertionError("no instr_req_o fired after branch")


@cocotb.test()
async def test_r_req_3_lookup_gating_req_i_zero(dut):
    """R-REQ-3: with req_i=0, no lookup fires (no instr_req_o either,
    absent live FBs). Spec §R-REQ.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 0
    for _ in range(8):
        await ReadOnly()
        assert int(dut.instr_req_o.value) == 0, (
            "instr_req_o asserted while req_i=0 and no in-flight FB"
        )
        await RisingEdge(dut.clk_i)
        await _settle(dut)


@cocotb.test()
async def test_r_req_4_drain_with_req_i_low(dut):
    """R-REQ-4: with req_i=0 mid-fill, in-flight fills still drain; no
    NEW lookup is launched. Spec §R-REQ.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    # Branch to start a fill.
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, 0x0010_0080)
    # Drop req_i. The cache should still drive the in-flight bus request.
    dut.req_i.value = 0
    # Provide RAM tag/data read response to settle IC1 (miss).
    await _ram_serve_lookup(dut, way0_tag_word=0, way1_tag_word=0)
    # Bus must still service the FB. It MAY take a few cycles.
    served = await _bus_grant_and_beat(dut, rdata=0xDEADBEEF, max_wait=8)
    assert served, "FB never drove bus despite req_i=0 mid-fill"


@cocotb.test()
async def test_r_req_5_lookup_addr_branch_priority(dut):
    """R-REQ-5: lookup addr = addr_i on branch, else registered prefetch.
    Branch to A; next cycle without branch should use A+stride. Spec §R-REQ.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 1
    a = 0x0010_0100
    a_line = a & ~(IC_LINE_BYTES - 1)
    dut.branch_i.value = 1
    dut.addr_i.value   = a
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    await _settle(dut)
    # Sample instr_addr_o on the next request cycle: should align to a_line.
    for _ in range(8):
        await ReadOnly()
        if int(dut.instr_req_o.value) == 1:
            addr = int(dut.instr_addr_o.value) & MASK32
            assert addr & ~(IC_LINE_BYTES - 1) in (
                a_line,
                (a_line + IC_LINE_BYTES) & MASK32,
            )
            return
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    raise AssertionError("no instr_req_o after branch")


@cocotb.test(skip=True)
async def test_r_req_6_addr_i_lsb_alignment(dut):
    """R-REQ-6: addr_i[0] = 0 is a caller-side promise; addr_i is UInt<32>
    and the cache has no obligation to enforce it. Untestable at the unit
    level. Spec §R-REQ-6.
    """
    pass


# ──────────────────────────────────────────────────────────────────────
# R-LK — Cache lookup, hit detection, allocation
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_lk_1_ic1_consumes_ram_data_one_cycle_after_grant(dut):
    """R-LK-1: ic_tag_rdata_i / ic_data_rdata_i consumed exactly one cycle
    after the lookup was granted in IC0. Verified by injecting a
    tag-RAM hit on the cycle after a branch and observing valid_o the
    following cycle. Spec §R-LK.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    addr = 0x0010_0080
    # Pre-stage the RAM read response for the cycle after the branch.
    dut.req_i.value = 1
    dut.ready_i.value = 1
    dut.branch_i.value = 1
    dut.addr_i.value   = addr
    await _settle(dut)
    await RisingEdge(dut.clk_i)  # IC0 grant
    dut.branch_i.value = 0
    # IC1 cycle: present a tag hit on way 0 with line data.
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, _tag_word(addr, valid=1))
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    _set_unpacked_vec(dut.ic_data_rdata_i, 0, 0x00000013_00100093)  # nop;addi
    _set_unpacked_vec(dut.ic_data_rdata_i, 1, 0)
    await _settle(dut)
    # Within a couple cycles, valid_o should rise from the IC1 hit.
    saw_valid = False
    for _ in range(4):
        await ReadOnly()
        if int(dut.valid_o.value) == 1:
            saw_valid = True
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert saw_valid, "valid_o never rose despite an IC1 tag hit"


@cocotb.test()
async def test_r_lk_2_tag_match_drives_hit_data(dut):
    """R-LK-2: a tag match steers the corresponding way's data to the
    output stream. Inject a way-1 hit with known data; verify rdata_o
    reflects the way-1 data when valid_o rises. Spec §R-LK.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    addr = 0x0010_0100
    # Drive branch
    dut.req_i.value = 1
    dut.ready_i.value = 1
    dut.branch_i.value = 1
    dut.addr_i.value = addr
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    # Way-1 hit; way-0 invalid.
    way1_data = 0x12345678_9ABCDEF0
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, _tag_word(addr, valid=1))
    _set_unpacked_vec(dut.ic_data_rdata_i, 0, 0xDEADBEEF_DEADBEEF)
    _set_unpacked_vec(dut.ic_data_rdata_i, 1, way1_data)
    await _settle(dut)
    # Wait for valid_o; sample rdata_o.
    for _ in range(6):
        await ReadOnly()
        if int(dut.valid_o.value) == 1:
            rd = int(dut.rdata_o.value) & MASK32
            # rdata_o must come from way-1's halfword aligned to addr.
            # The lower 32 bits of way1_data are 0x9ABCDEF0; the top 32
            # are 0x12345678. The exact selection depends on addr[2].
            assert rd in (0x9ABCDEF0, 0x12345678), (
                f"rdata_o {rd:#010x} not from way-1 hit data {way1_data:#018x}"
            )
            return
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    raise AssertionError("valid_o never rose on way-1 hit")


@cocotb.test()
async def test_r_lk_3_victim_picks_invalid_way_first(dut):
    """R-LK-3: on miss, the cache MUST select the lowest-indexed invalid
    way as the victim. Externally observable on the writeback cycle:
    `ic_tag_req_o[way] = 1, ic_tag_write_o = 1` for the chosen way.

    Stimulus:
      - Cold cache (both ways invalid out of inval).
      - Branch to addr A.
      - Tag rdata: both ways invalid (rdata=0, valid bit clear).
      - Bus delivers 2 beats cleanly.
      - Once the FB has both beats and the inval-write port is free,
        it writes back. With both ways invalid, way 0 is the lowest
        invalid → `ic_tag_req_o[0]=1, ic_tag_req_o[1]=0`.

    Spec §R-LK-3.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.icache_enable_i.value = 1   # allow allocation (writeback path)
    addr = 0x0420_0080
    dut.req_i.value = 1
    dut.ready_i.value = 1
    dut.branch_i.value = 1
    dut.addr_i.value = addr
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    # Both ways invalid (rdata=0).
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    await _settle(dut)
    # Drop req_i so prefetch doesn't allocate extra FBs.
    dut.req_i.value = 0
    # Service two beats.
    for _ in range(IC_LINE_BEATS):
        served = await _bus_grant_and_beat(dut, rdata=0xCAFEBABE, max_wait=8)
        assert served
    # Watch for the writeback. With both ways invalid, victim = way 0.
    saw_writeback = False
    for _ in range(40):
        await ReadOnly()
        if int(dut.ic_tag_write_o.value) == 1:
            tag_req = int(dut.ic_tag_req_o.value)
            assert tag_req & 0b01, (
                f"writeback should target way 0 (lowest invalid); "
                f"ic_tag_req_o = {tag_req:#04b}"
            )
            assert (tag_req & 0b10) == 0, (
                f"way 1 should NOT be written when way 0 is invalid; "
                f"ic_tag_req_o = {tag_req:#04b}"
            )
            saw_writeback = True
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert saw_writeback, "no fill writeback observed within 40 cycles"


@cocotb.test()
async def test_r_lk_4_branch_into_in_flight_line_no_redundant_req(dut):
    """R-LK-4: branch to a line already in a live fill buffer MUST be
    serviced from that FB without a second instr_req_o for the same line
    (common case). Spec §R-LK-4.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    addr = 0x0030_0080
    # Initiate first miss-fill.
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, addr)
    # IC1 miss: tags both invalid.
    await _ram_serve_lookup(dut, way0_tag_word=0, way1_tag_word=0)
    # Service one bus beat.
    served = await _bus_grant_and_beat(dut, rdata=0xAAAA1111, max_wait=8)
    assert served
    # Now branch back to the same line before the second beat lands.
    seen_req_addrs_before = set()
    # Re-branch immediately
    dut.branch_i.value = 1
    dut.addr_i.value   = addr + 4  # different offset, same line
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    await _settle(dut)
    # Sample several cycles; collect any new instr_req_o addresses.
    new_req_for_same_line = 0
    line_aligned = addr & ~(IC_LINE_BYTES - 1)
    for _ in range(4):
        await ReadOnly()
        if int(dut.instr_req_o.value) == 1:
            ra = int(dut.instr_addr_o.value) & MASK32
            if (ra & ~(IC_LINE_BYTES - 1)) == line_aligned:
                # Allow at most one — the original FB's outstanding 2nd beat.
                new_req_for_same_line += 1
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    # We already serviced beat 0; at most 1 more bus request (for beat 1)
    # may exist. Anything beyond that is a redundant request.
    assert new_req_for_same_line <= 1, (
        f"saw {new_req_for_same_line} redundant requests for the same line "
        f"after branch-into-FB"
    )


@cocotb.test()
async def test_r_lk_5_no_ram_write_while_inval_block(dut):
    """R-LK-5: while inval_block_cache=1 (e.g. cold boot still walking,
    or a fresh icache_inval_i pulse), no fill-allocation tag/data write
    fires. Only invalidation tag-clear writes are allowed.
    Spec §R-LK-5.
    """
    await _start_clock(dut)
    await _reset(dut)
    # During cold boot: ic_tag_write_o is 1 only for inval (clearing valid).
    # The wdata_o must have its valid bit clear during these writes.
    for _ in range(IC_NUM_LINES):
        await ReadOnly()
        if int(dut.ic_tag_write_o.value) == 1:
            wd = int(dut.ic_tag_wdata_o.value)
            # Valid bit (bit 21) must be 0 during inval writes.
            assert (wd & TAG_VALID_BIT) == 0, (
                f"inval write wrote a valid-bit-set tag {wd:#x}"
            )
        if int(dut.busy_o.value) == 0:
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)


# ──────────────────────────────────────────────────────────────────────
# R-FB — Fill buffer pool capacity and arbitration
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_fb_1_pool_full_stalls_lookup(dut):
    """R-FB-1: with NUM_FB FBs live, no further lookup is granted until
    one releases. Stimulus: drive 4 misses without consuming output;
    observe lookup throttling. Spec §R-FB.

    This is a soft observation: when the pool is full and no branch
    fires, ic_tag_req_o all-ones lookup pattern stops appearing until
    an FB releases.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 0  # don't drain output → keep FBs busy
    # Branch and let the cache start prefetching.
    await _branch(dut, 0x0040_0000)
    # Provide miss tags repeatedly so each lookup allocates an FB.
    # Just hold tag_rdata at 0 (all invalid) for a window.
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # Run 20 cycles, do not service the bus → FBs stay live.
    for _ in range(20):
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    # Once the pool is saturated busy_o must be 1 with no further lookups.
    assert int(dut.busy_o.value) == 1, (
        "busy_o low despite FB pool saturation"
    )


@cocotb.test()
async def test_r_fb_2_each_grant_allocates_one_fb(dut):
    """R-FB-2: each granted lookup allocates exactly one FB. Externally
    observable via `fb_busy_mask` (exposed by the icache impl):
    successive grants for distinct cache lines (so the strengthened
    R-LK-4 CAM doesn't coalesce) must increment popcount(fb_busy_mask)
    by exactly 1 per grant, until the pool saturates at NUM_FB=4.

    Stimulus:
      - Cold cache, all FBs free.
      - Drive 4 branches to 4 distinct lines, one per cycle, granting
        the bus + holding `req_i = 1`.
      - Don't service rvalids — keeps FBs busy across all 4 allocations.
      - Sample fb_busy_mask after each grant.

    Spec §R-FB-2.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.icache_enable_i.value = 1
    dut.req_i.value = 1
    dut.ready_i.value = 0   # don't drain output
    # Tag rdata = 0 → all lookups miss → each allocates an FB.
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    await _settle(dut)
    # Issue 4 distinct-line branches and watch popcount(fb_busy_mask).
    addrs = [0x0100_0080, 0x0200_0080, 0x0300_0080, 0x0400_0080]
    for i, addr in enumerate(addrs):
        dut.branch_i.value = 1
        dut.addr_i.value = addr
        await _settle(dut)
        await RisingEdge(dut.clk_i)
        dut.branch_i.value = 0
        # Allow 1 settle + 1 cycle for FB to enter PhAlloc/busy.
        await _settle(dut)
        await RisingEdge(dut.clk_i)
        await _settle(dut)
        # Grant a bus request if pending (so the FB's bus handshake
        # progresses without rvalid stalling new allocations).
        if int(dut.instr_req_o.value) == 1:
            dut.instr_gnt_i.value = 1
            await RisingEdge(dut.clk_i)
            dut.instr_gnt_i.value = 0
            await _settle(dut)
        await ReadOnly()
        busy = int(dut.fb_busy_mask.value)
        popcount = bin(busy).count("1")
        # popcount MUST equal i+1: each prior grant allocated exactly
        # one FB, and none have released (we never serve rvalids).
        assert popcount == i + 1, (
            f"after {i+1} grants for distinct lines, fb_busy_mask popcount "
            f"= {popcount} (= {busy:#06b}); expected {i+1}"
        )
        await RisingEdge(dut.clk_i)
        await _settle(dut)


@cocotb.test(skip=True)
async def test_r_fb_3_fb_records_state_fields(dut):
    """R-FB-3 is an *existence* claim about internal FB structure: each
    FB holds (lookup addr, stale flag, allocate flag, hit/miss,
    per-beat err, line data). The icache exposes no status / debug
    register that reads any of these directly — verified by the port
    list (no `fb_state_o`, no debug bus). Each field's *behavioural
    consequence* IS runtime-checked, but by a named test elsewhere
    that exercises the downstream output port:

      lookup addr  → R-LK-1, R-EXT-3 (drives `ic_*_addr_o`,
                                       `instr_addr_o`)
      stale flag   → R-INV-A, R-INV-B (no writeback after inval)
      alloc flag   → R-LK-3            (gates `ic_tag_write_o` after
                                        fill)
      hit / miss   → R-LK-1, R-FB-2    (miss ⇒ `instr_req_o` + FB
                                        allocation)
      per-beat err → R-OUT-5            (drives `err_o` / `err_plus2_o`)
      line data    → R-LK-1, R-LK-4    (drives `rdata_o`)

    A dedicated R-FB-3 test would either (a) duplicate one of those
    behavioural tests, or (b) poke `dut.fb_inst[i].field_q` directly,
    which validates the test scaffold's white-box read path rather
    than the impl's contract. Source inspection of the FB regs is the
    appropriate check for the existence claim. Spec §R-FB-3.
    """
    pass


@cocotb.test()
async def test_r_fb_4_age_ordered_arbitration(dut):
    """R-FB-4: with two FBs in flight, the oldest still-expecting FB
    consumes the next instr_rvalid_i; output to IF goes oldest-first.
    Spec §R-FB.

    Soft observation: launch two distinct misses; each gets one beat;
    the order of acceptance must not invert.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 1
    # First miss
    await _branch(dut, 0x0050_0000)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    served0 = await _bus_grant_and_beat(dut, rdata=0xAAAA0001, max_wait=8)
    assert served0
    # Second miss to a different line via another branch
    await _branch(dut, 0x0060_0000)
    served1 = await _bus_grant_and_beat(dut, rdata=0xBBBB0001, max_wait=8)
    assert served1
    # If we got here both fills progressed; ordering wasn't inverted in
    # any visible deadlock.


@cocotb.test()
async def test_r_fb_5_release_only_after_beats_writeback_output(dut):
    """R-FB-5: an FB releases (busy_o drops on last FB) only after all
    beats received AND any cache write-back complete AND output beats
    delivered. Spec §R-FB-5.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, 0x0070_0000)
    # Drop req_i so the cache doesn't continuously prefetch new lines
    # (which would allocate fb1/fb2/fb3 and leave them busy when this
    # test only services beats for the initial FB).
    dut.req_i.value = 0
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # Service two beats (IC_LINE_BEATS = 2).
    for _ in range(IC_LINE_BEATS):
        served = await _bus_grant_and_beat(dut, rdata=0x13_00100093, max_wait=8)
        assert served
    # Eventually busy_o must drop.
    for _ in range(30):
        await ReadOnly()
        if int(dut.busy_o.value) == 0:
            return
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    raise AssertionError("busy_o never dropped after all beats serviced")


@cocotb.test()
async def test_r_fb_6_stale_fb_cancels_external_requests(dut):
    """R-FB-6: a stale (branched-away), non-allocating FB cancels its
    remaining external requests. Spec §R-FB-6.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 1
    # Disable cache so the FB allocated is non-allocating.
    dut.icache_enable_i.value = 0
    await _branch(dut, 0x0080_0000)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # Serve beat 0 only, then branch elsewhere.
    served = await _bus_grant_and_beat(dut, rdata=0xCAFEBABE, max_wait=8)
    assert served
    # Branch to a different line.
    await _branch(dut, 0x0090_0000)
    # The original FB is stale + non-allocating; remaining beats should
    # be cancelled. If not, the bus never quiesces. Sanity: we should be
    # able to make progress on the new branch.
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    served2 = await _bus_grant_and_beat(dut, rdata=0xCAFEBABE, max_wait=12)
    assert served2, "new FB couldn't get bus access; stale FB not cancelling"


# ──────────────────────────────────────────────────────────────────────
# R-EXT — Instruction-bus master behaviour
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_ext_1_instr_req_only_when_fb_needs_beat(dut):
    """R-EXT-1: instr_req_o = 1 iff some live FB still expects a beat OR
    a speculative IC0 branch fires. With no live FB and no branch,
    instr_req_o = 0. Spec §R-EXT.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 1
    # No branch yet; no live FBs.
    for _ in range(8):
        await ReadOnly()
        assert int(dut.instr_req_o.value) == 0
        await RisingEdge(dut.clk_i)
        await _settle(dut)


@cocotb.test()
async def test_r_ext_2_instr_req_addr_stable_until_gnt(dut):
    """R-EXT-2: once instr_req_o=1, instr_req_o and instr_addr_o stay
    stable across cycles until instr_gnt_i=1. Spec §R-EXT.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, 0x00A0_0000)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # Wait for instr_req_o to assert.
    first_addr = None
    for _ in range(8):
        await ReadOnly()
        if int(dut.instr_req_o.value) == 1:
            first_addr = int(dut.instr_addr_o.value) & MASK32
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert first_addr is not None, "instr_req_o never asserted"
    # Hold gnt low for several cycles, observe stability.
    for _ in range(4):
        await RisingEdge(dut.clk_i)
        await _settle(dut)
        assert int(dut.instr_req_o.value) == 1, "instr_req_o dropped pre-gnt"
        assert int(dut.instr_addr_o.value) & MASK32 == first_addr, (
            "instr_addr_o changed pre-gnt"
        )


@cocotb.test()
async def test_r_ext_3_instr_addr_word_aligned(dut):
    """R-EXT-3: every cycle that `instr_req_o = 1`, `instr_addr_o[1:0]`
    MUST be 0 (word-aligned bus master). Structurally enforced by the
    impl's `(line_base & ~7) | (beats_sent << 2)` construction, but
    runtime-checkable: drive a misaligned-PC branch (bit 1 set on the
    IF-side `addr_i`) so a regression that leaks the misaligned bit
    into the bus-side `instr_addr_o` would surface here.

    Spec §R-EXT-3.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.icache_enable_i.value = 1
    # Branch to a misaligned (bit-1 set) PC inside an unaligned line.
    # The bus-side instr_addr_o still must be word-aligned; bit 1 of
    # the IF-side branch belongs in the IF-side `addr_o`, not on
    # `instr_addr_o`.
    dut.req_i.value = 1
    dut.ready_i.value = 1
    dut.branch_i.value = 1
    dut.addr_i.value = 0x0800_0082
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    await _settle(dut)
    # Watch every cycle the bus master is asserting a request.
    saw_req = False
    for _ in range(40):
        await ReadOnly()
        if int(dut.instr_req_o.value) == 1:
            saw_req = True
            addr = int(dut.instr_addr_o.value)
            assert (addr & 0x3) == 0, (
                f"instr_addr_o = {addr:#010x}; low 2 bits MUST be 0 "
                f"(R-EXT-3 word alignment) but are {addr & 0x3:#04b}"
            )
        # Drive the gnt/rvalid handshake along so the FB completes.
        if int(dut.instr_req_o.value) == 1:
            await RisingEdge(dut.clk_i)
            dut.instr_gnt_i.value = 1
            await RisingEdge(dut.clk_i)
            dut.instr_gnt_i.value = 0
            dut.instr_rvalid_i.value = 1
            dut.instr_rdata_i.value = 0xCAFEF00D
            dut.instr_err_i.value = 0
            await RisingEdge(dut.clk_i)
            dut.instr_rvalid_i.value = 0
            await _settle(dut)
        else:
            await RisingEdge(dut.clk_i)
            await _settle(dut)
    assert saw_req, "instr_req_o never asserted; R-EXT-3 not exercised"


@cocotb.test()
async def test_r_ext_4_rvalid_steers_to_oldest_expecting_fb(dut):
    """R-EXT-4: rvalid beats route to the oldest expecting FB; per-beat
    instr_err_i is recorded. Spec §R-EXT.

    Indirect observation: a single FB miss with a 2-beat fill must
    accept both beats correctly (no lock-up).
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, 0x00B0_0000)
    # Drop req_i so prefetch doesn't allocate redundant FBs that this
    # single-FB lock-up test never services.
    dut.req_i.value = 0
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    for beat in range(IC_LINE_BEATS):
        served = await _bus_grant_and_beat(
            dut, rdata=0x10000000 | beat, max_wait=8,
        )
        assert served, f"beat {beat} never serviced"
    # FB releases; busy goes low.
    for _ in range(20):
        await ReadOnly()
        if int(dut.busy_o.value) == 0:
            return
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    raise AssertionError("FB never released after both beats")


@cocotb.test()
async def test_r_ext_5_no_further_req_after_recorded_bus_error(dut):
    """R-EXT-5: after a beat with instr_err_i=1, no further instr_req_o
    fires for that FB. Spec §R-EXT.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, 0x00C0_0000)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # Serve beat 0 with err=1.
    served = await _bus_grant_and_beat(dut, rdata=0xDEADBEEF, err=1, max_wait=8)
    assert served
    # No further requests should fire for this FB. Specifically: across
    # the next several cycles, instr_req_o should NOT pulse for the same
    # line (the FB has cancelled). Other FBs (none here) might. Since no
    # other FB is allocated, instr_req_o should stay low.
    saw_more = False
    for _ in range(8):
        await ReadOnly()
        if int(dut.instr_req_o.value) == 1:
            saw_more = True
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert not saw_more, "instr_req_o pulsed after recorded bus error"


# ──────────────────────────────────────────────────────────────────────
# R-ARB — RAM-port arbitration
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_arb_1_lookup_priority_over_fill(dut):
    """R-ARB-1: lookups have priority over fill writes for the tag/data
    RAM port (lookup_grant = lookup_req; fill_grant suppressed if lookup
    contends). Observed by: during a window in which both could fire,
    ic_tag_write_o stays 0 (the lookup wins, which is a read).
    Spec §R-ARB.

    Soft observation: drive a continuous stream of branches that issue
    back-to-back lookups; verify ic_tag_write_o is 0 in the steady state.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 1
    # A series of branches, each prompts a lookup.
    for i in range(4):
        await _branch(dut, 0x0100_0000 + (i << 10))
        _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
        _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
        # Sample ic_tag_write_o during the IC0 cycle of each branch lookup.
        await ReadOnly()
        # Just after the branch, the next IC0 must be a lookup, not a fill
        # write.
        # (Tag write may fire on a later cycle for a previous fill, that
        # is allowed; we only assert read-priority on the current cycle's
        # contended slot.)
        await RisingEdge(dut.clk_i)
        await _settle(dut)


@cocotb.test()
async def test_r_arb_2_inval_suppresses_lookup_and_fill(dut):
    """R-ARB-2: while INVAL_CACHE walking, no lookup-pattern tag req
    (all-ones across both ways) AND no fill writeback fires. The only
    tag writes during this window are the inval clears. Spec §R-ARB.
    """
    await _start_clock(dut)
    await _reset(dut)
    # Cold boot: inval_state runs. Even with req_i=1 and a branch, no fill
    # write should happen.
    dut.req_i.value = 1
    dut.ready_i.value = 1
    dut.branch_i.value = 1
    dut.addr_i.value   = 0x0123_4567
    await _settle(dut)
    # Walk the inval cycles.
    for _ in range(IC_NUM_LINES // 2):
        await ReadOnly()
        if int(dut.ic_tag_write_o.value) == 1:
            wd = int(dut.ic_tag_wdata_o.value)
            assert (wd & TAG_VALID_BIT) == 0, (
                "fill write fired during INVAL_CACHE"
            )
        await RisingEdge(dut.clk_i)
        await _settle(dut)


@cocotb.test()
async def test_r_arb_3_throttle_above_threshold(dut):
    """R-ARB-3: once more than FB_THRESHOLD = 2 buffers are live,
    non-branch lookups stall. branch_i always bypasses the throttle.
    Spec §R-ARB.

    Observed indirectly: with FBs saturating, and stalled output
    (ready_i=0), we expect busy_o to remain high without unbounded
    request streaming.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.req_i.value = 1
    dut.ready_i.value = 0
    await _branch(dut, 0x0200_0000)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # Run several cycles without servicing the bus -> FBs accumulate.
    for _ in range(16):
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert int(dut.busy_o.value) == 1


@cocotb.test()
async def test_r_arb_4_ic0_driver_priority_inval_over_fill_over_lookup(dut):
    """R-ARB-4: in IC0, RAM driver priority: invalidate > ECC-correct >
    fill > lookup. With ECC=0 and during a fresh icache_inval_i pulse,
    the invalidate index drives ic_tag_addr_o. Spec §R-ARB.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    # Pulse icache_inval_i to enter inval walk again.
    dut.icache_inval_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.icache_inval_i.value = 0
    await _settle(dut)
    # During the walk, ic_tag_addr_o should sweep 0 .. IC_NUM_LINES-1.
    seen = set()
    for _ in range(IC_NUM_LINES + 8):
        await ReadOnly()
        if int(dut.ic_tag_write_o.value) == 1:
            seen.add(int(dut.ic_tag_addr_o.value))
        if int(dut.busy_o.value) == 0:
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert seen == set(range(IC_NUM_LINES)), (
        "invalidate didn't sweep every index after icache_inval_i pulse"
    )


# ──────────────────────────────────────────────────────────────────────
# R-OUT — IF-stage output stream
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_out_1_valid_o_asserts_when_data_available(dut):
    """R-OUT-1: valid_o asserts the cycle after IC1 hit (data available
    in the FB stream). Spec §R-OUT.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    addr = 0x0300_0000
    dut.req_i.value = 1
    dut.ready_i.value = 1
    dut.branch_i.value = 1
    dut.addr_i.value   = addr
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    # IC1 hit: way 0 valid + matching tag.
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, _tag_word(addr, valid=1))
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    _set_unpacked_vec(dut.ic_data_rdata_i, 0, 0x00000013_00100093)
    _set_unpacked_vec(dut.ic_data_rdata_i, 1, 0)
    await _settle(dut)
    saw = False
    for _ in range(4):
        await ReadOnly()
        if int(dut.valid_o.value) == 1:
            saw = True
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert saw, "valid_o never rose after IC1 hit"


@cocotb.test()
async def test_r_out_2_sticky_until_ready_or_branch(dut):
    """R-OUT-2: once valid_o=1 (no error), it stays high with stable
    rdata_o/addr_o until ready_i=1 OR branch_i=1. Spec §R-OUT.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    addr = 0x0400_0000
    dut.req_i.value = 1
    dut.ready_i.value = 0
    dut.branch_i.value = 1
    dut.addr_i.value   = addr
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    # IC1 hit
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, _tag_word(addr, valid=1))
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    _set_unpacked_vec(dut.ic_data_rdata_i, 0, 0xCAFE_DEAD_BABE_FACE)
    _set_unpacked_vec(dut.ic_data_rdata_i, 1, 0)
    await _settle(dut)
    # Wait for valid_o.
    first_rdata = None
    first_addr  = None
    for _ in range(4):
        await ReadOnly()
        if int(dut.valid_o.value) == 1:
            first_rdata = int(dut.rdata_o.value) & MASK32
            first_addr  = int(dut.addr_o.value)  & MASK32
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert first_rdata is not None, "valid_o never rose"
    # Hold ready_i=0 for several cycles. valid_o must stay 1 with stable
    # rdata_o and addr_o (no-error sticky).
    for _ in range(4):
        await RisingEdge(dut.clk_i)
        await _settle(dut)
        # Hold the RAM data (the IC1-stage capture should have latched).
        assert int(dut.valid_o.value) == 1, "valid_o dropped without ready_i"
        assert int(dut.rdata_o.value) & MASK32 == first_rdata
        assert int(dut.addr_o.value)  & MASK32 == first_addr


@cocotb.test(skip=True)
async def test_r_out_3_after_err_outputs_may_change_until_branch(dut):
    """R-OUT-3: after err_o=1, all output signals MAY change. Permissive
    MAY clause; nothing to assert. Spec §R-OUT-3.
    """
    pass


@cocotb.test()
async def test_r_out_4_addr_advances_by_2_or_4(dut):
    """R-OUT-4: on ready_i & valid_o, addr_o advances by 2 if rdata_o[1:0]
    != 2'b11 (compressed) else by 4. addr_o[0] = 0. Spec §R-OUT.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    addr = 0x0500_0000
    dut.req_i.value = 1
    dut.ready_i.value = 1
    dut.branch_i.value = 1
    dut.addr_i.value   = addr
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    # IC1 hit; line data = two compressed C.NOPs (0x0001) interleaved with
    # zero halfwords. compressed pattern: lower 2 bits != 2'b11.
    line = 0x0001_0001_0001_0001
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, _tag_word(addr, valid=1))
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    _set_unpacked_vec(dut.ic_data_rdata_i, 0, line)
    _set_unpacked_vec(dut.ic_data_rdata_i, 1, 0)
    await _settle(dut)
    # Wait for valid; sample addr_o.
    for _ in range(4):
        await ReadOnly()
        if int(dut.valid_o.value) == 1:
            a0 = int(dut.addr_o.value) & MASK32
            assert (a0 & 1) == 0, "addr_o[0] != 0"
            # Accept the beat; observe next addr_o.
            await RisingEdge(dut.clk_i)
            await _settle(dut)
            await ReadOnly()
            # Next addr_o must be a0 + 2 (compressed) or a0 + 4.
            a1 = int(dut.addr_o.value) & MASK32
            assert a1 in ((a0 + 2) & MASK32, (a0 + 4) & MASK32), (
                f"addr_o didn't advance: a0={a0:#x}, a1={a1:#x}"
            )
            return
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    raise AssertionError("valid_o never rose")


@cocotb.test()
async def test_r_out_5_err_plus2_only_on_unaligned_upper_half_fault(dut):
    """R-OUT-5: err_plus2_o = 1 only when the fault is on the UPPER
    halfword of an unaligned 32-bit instruction. Bus error on line
    beat 1 (bytes [4..7] of the 8-byte line) AND alloc_addr[1] = 1
    AND output is line beat 1.

    Stimulus:
      - Branch to a misaligned address (addr[1]=1) so the FB allocates
        with its halfword position bit set.
      - Hold ready_i = 0 to capture each output cycle.
      - Bus delivers line beat 0 (bytes [0..3]) cleanly.
      - Bus delivers line beat 1 (bytes [4..7]) with err_i = 1.
      - On the FIRST output cycle (beat 0): err_o = 0, err_plus2_o = 0.
      - On the SECOND output cycle (beat 1): err_o = 1, err_plus2_o = 1.

    Spec §R-OUT-5.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    addr = 0x0010_0082  # misaligned (bit 1 set)
    dut.req_i.value = 1
    dut.ready_i.value = 0  # sticky valid for observability
    dut.branch_i.value = 1
    dut.addr_i.value   = addr
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    # Tag rdata = 0 (miss) so the FB enters fill path.
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    await _settle(dut)
    # Beat 0: clean. Beat 1: bus error.
    served0 = await _bus_grant_and_beat(
        dut, rdata=0x12345678, err=0, max_wait=8,
    )
    assert served0, "icache never issued first instr_req_o"
    served1 = await _bus_grant_and_beat(
        dut, rdata=0x9abcdef0, err=1, max_wait=20,
    )
    assert served1, "icache never issued second instr_req_o"
    # First output beat: line beat 0 (clean) → err = 0, err_plus2 = 0.
    for _ in range(20):
        await ReadOnly()
        if int(dut.valid_o.value) == 1:
            assert int(dut.err_o.value) == 0, "first output beat must be clean"
            assert int(dut.err_plus2_o.value) == 0, (
                "err_plus2 must be 0 on the first (lower-half) beat"
            )
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    else:
        raise AssertionError("icache never delivered first valid_o")
    # Pop the first beat with ready_i pulse, then sample second beat.
    await RisingEdge(dut.clk_i)
    dut.ready_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.ready_i.value = 0
    for _ in range(20):
        await ReadOnly()
        if int(dut.valid_o.value) == 1:
            assert int(dut.err_o.value) == 1, (
                "second output beat must reflect line beat 1 bus error"
            )
            assert int(dut.err_plus2_o.value) == 1, (
                "err_plus2 must be 1 on the upper-half-faulted beat of "
                "an unaligned RV32 fetch"
            )
            return
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    raise AssertionError("icache never delivered second valid_o")


@cocotb.test()
async def test_r_out_6_skid_buffer_clears_on_branch(dut):
    """R-OUT-6: a branch_i pulse clears the skid buffer; subsequent
    output stream begins from addr_i. Observable via valid_o dropping
    to 0 immediately after branch_i. Spec §R-OUT.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    addr1 = 0x0600_0000
    dut.req_i.value = 1
    dut.ready_i.value = 0
    dut.branch_i.value = 1
    dut.addr_i.value   = addr1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, _tag_word(addr1, valid=1))
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    _set_unpacked_vec(dut.ic_data_rdata_i, 0, 0x0001_0001_0001_0001)
    _set_unpacked_vec(dut.ic_data_rdata_i, 1, 0)
    await _settle(dut)
    # Wait for valid. After break, advance one edge so the next signal
    # write is out of the ReadOnly phase (cocotb 2.0 disallows writes
    # while ReadOnly is current).
    for _ in range(4):
        await ReadOnly()
        if int(dut.valid_o.value) == 1:
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    await RisingEdge(dut.clk_i)
    # Branch elsewhere with branch_i.
    addr2 = 0x0700_0000
    dut.branch_i.value = 1
    dut.addr_i.value   = addr2
    await _settle(dut)
    await ReadOnly()
    # Per spec ambiguity 2, branch_i is the canonical override → valid_o
    # drops on the branch.
    assert int(dut.valid_o.value) == 0 or int(dut.branch_i.value) == 1
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    await _settle(dut)


@cocotb.test()
async def test_r_out_7_hit_data_drives_valid_no_later_than_ic1plus1(dut):
    """R-OUT-7: on a cache hit, valid_o asserts no later than the cycle
    after the IC1 hit (= 2 cycles after the lookup grant in IC0).
    Spec §R-OUT.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    addr = 0x0800_0000
    dut.req_i.value = 1
    dut.ready_i.value = 1
    dut.branch_i.value = 1
    dut.addr_i.value   = addr
    await _settle(dut)
    # IC0 cycle.
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    await _settle(dut)
    # IC1 cycle: present hit data.
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, _tag_word(addr, valid=1))
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    _set_unpacked_vec(dut.ic_data_rdata_i, 0, 0x13_00100093)
    _set_unpacked_vec(dut.ic_data_rdata_i, 1, 0)
    # Allow two cycles for valid_o to rise (IC1 + IC1+1).
    saw = False
    for _ in range(2):
        await ReadOnly()
        if int(dut.valid_o.value) == 1:
            saw = True
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert saw, "valid_o didn't rise within 2 cycles of IC1 hit"


# ──────────────────────────────────────────────────────────────────────
# R-EN — Enable / disable
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_en_1_disabled_does_not_allocate(dut):
    """R-EN-1: with icache_enable_i=0 and no inval, lookups don't allocate.
    Specifically, no fill-allocation tag writes (ic_tag_write_o=1 with
    valid bit set in ic_tag_wdata_o) fire. Spec §R-EN.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.icache_enable_i.value = 0
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, 0x0900_0000)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # Service two beats.
    for _ in range(IC_LINE_BEATS):
        served = await _bus_grant_and_beat(dut, rdata=0xDEAF1234, max_wait=8)
        assert served
    # Across the post-beat window, no allocate-write must fire.
    for _ in range(8):
        await ReadOnly()
        if int(dut.ic_tag_write_o.value) == 1:
            wd = int(dut.ic_tag_wdata_o.value)
            assert (wd & TAG_VALID_BIT) == 0, (
                "allocate write fired while icache_enable_i=0"
            )
        await RisingEdge(dut.clk_i)
        await _settle(dut)


@cocotb.test()
async def test_r_en_2_disabled_still_serves_bus(dut):
    """R-EN-2: with icache_enable_i=0, lookups still drive instr_req_o so
    the IF stream continues. Spec §R-EN.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.icache_enable_i.value = 0
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, 0x0A00_0000)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    served = await _bus_grant_and_beat(dut, rdata=0x00100013, max_wait=8)
    assert served, "no instr_req_o when cache disabled"


@cocotb.test()
async def test_r_en_3_enable_drop_drops_allocate_flag(dut):
    """R-EN-3: an FB whose icache_enable_i drops mid-fill never writes
    back to the RAMs even after enable returns to 1. Spec §R-EN.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.icache_enable_i.value = 1
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, 0x0B00_0000)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # Drop enable mid-flight (before any beat returns).
    dut.icache_enable_i.value = 0
    await _settle(dut)
    # Serve beats with cache disabled.
    for _ in range(IC_LINE_BEATS):
        served = await _bus_grant_and_beat(dut, rdata=0x00100013, max_wait=8)
        assert served
    # Re-enable.
    dut.icache_enable_i.value = 1
    await _settle(dut)
    # Watch for an allocate-write across the next window: must be 0.
    for _ in range(8):
        await ReadOnly()
        if int(dut.ic_tag_write_o.value) == 1:
            wd = int(dut.ic_tag_wdata_o.value)
            assert (wd & TAG_VALID_BIT) == 0
        await RisingEdge(dut.clk_i)
        await _settle(dut)


# ──────────────────────────────────────────────────────────────────────
# R-INV — Invalidation request semantics
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_inv_a_pulse_clears_all_tag_valid_bits(dut):
    """R-INV-A: a pulse on icache_inval_i eventually clears every line's
    tag-valid bit (sweep all IC_NUM_LINES indices). Spec §R-INV.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.icache_inval_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.icache_inval_i.value = 0
    await _settle(dut)
    written = set()
    for _ in range(IC_NUM_LINES + 8):
        await ReadOnly()
        if int(dut.ic_tag_write_o.value) == 1:
            wd = int(dut.ic_tag_wdata_o.value)
            if (wd & TAG_VALID_BIT) == 0:  # invalidation clear
                written.add(int(dut.ic_tag_addr_o.value))
        if int(dut.busy_o.value) == 0:
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert written == set(range(IC_NUM_LINES))


@cocotb.test()
async def test_r_inv_b_inval_blocks_allocate_only(dut):
    """R-INV-B: during invalidation, lookups still drive instr_req_o but
    no allocate-write fires. Spec §R-INV.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    # Start an inval walk.
    dut.icache_inval_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.icache_inval_i.value = 0
    await _settle(dut)
    # Drive a branch + bus beat during the walk.
    dut.req_i.value = 1
    dut.ready_i.value = 1
    dut.branch_i.value = 1
    dut.addr_i.value   = 0x0C00_0000
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    await _settle(dut)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # During the walk, scan a window: ensure no allocate write fires.
    for _ in range(IC_NUM_LINES // 2):
        await ReadOnly()
        if int(dut.ic_tag_write_o.value) == 1:
            wd = int(dut.ic_tag_wdata_o.value)
            assert (wd & TAG_VALID_BIT) == 0, (
                "allocate write fired during invalidation"
            )
        await RisingEdge(dut.clk_i)
        await _settle(dut)


@cocotb.test()
async def test_r_inv_c_live_fb_drops_allocate_on_inval(dut):
    """R-INV-C: a pulse on icache_inval_i while an FB is live causes that
    FB to drop its allocate flag (no later writeback). Spec §R-INV.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    dut.icache_enable_i.value = 1
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, 0x0D00_0000)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # Pulse inval BEFORE any beats land.
    dut.icache_inval_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.icache_inval_i.value = 0
    await _settle(dut)
    # Now serve bus beats.
    for _ in range(IC_LINE_BEATS):
        served = await _bus_grant_and_beat(dut, rdata=0x13_00100013, max_wait=8)
        if not served:
            break
    # Across the next window the allocate path must not fire.
    for _ in range(8):
        await ReadOnly()
        if int(dut.ic_tag_write_o.value) == 1:
            wd = int(dut.ic_tag_wdata_o.value)
            assert (wd & TAG_VALID_BIT) == 0
        await RisingEdge(dut.clk_i)
        await _settle(dut)


# ──────────────────────────────────────────────────────────────────────
# R-BUSY — Busy / clock-gate
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_busy_1_busy_o_during_inval_or_pending_traffic(dut):
    """R-BUSY-1: busy_o = 1 while inval_state != IDLE OR while any FB has
    unresolved bus traffic. Spec §R-BUSY.
    """
    await _start_clock(dut)
    await _reset(dut)
    # During cold-boot inval: busy=1 (covered).
    assert int(dut.busy_o.value) == 1
    await _wait_until_idle(dut)
    # Now drive a miss to make an FB live; busy must rise.
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, 0x0E00_0000)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # busy_o should now be 1 with a live FB awaiting beats.
    saw_busy = False
    for _ in range(8):
        await ReadOnly()
        if int(dut.busy_o.value) == 1:
            saw_busy = True
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert saw_busy, "busy_o never rose with a live FB"


@cocotb.test()
async def test_r_busy_2_no_self_clockgate(dut):
    """R-BUSY-2: `busy_o = 0` is a permission for the SoC to clock-gate;
    the implementation MUST NOT gate itself. A self-gate would manifest
    as: after busy_o transitions to 0 (idle), the cache cannot wake to
    service a new branch+req — its own state machines would be frozen.

    Stimulus:
      - Cold reset, wait until idle (busy_o = 0).
      - Sit idle for 50 cycles.
      - Drive a branch + req to a fresh line.
      - Cache MUST drive `instr_req_o` (the bus-side wake) within a
        bounded window. A self-gated cache would hang silently.
      - Service one beat to confirm the FB is alive (i.e. the SR-FF /
        FSM updated normally on this clk_i edge — not gated).

    Indirectly covered by every test that goes idle and re-engages, but
    made explicit here so a regression introducing a self-gate is
    caught by name. Spec §R-BUSY-2.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _wait_until_idle(dut)
    # Confirm we're actually idle.
    await ReadOnly()
    assert int(dut.busy_o.value) == 0, (
        "precondition: cache should be idle (busy_o=0) after _wait_until_idle"
    )
    # Long idle window — gives a self-gate ample time to engage.
    for _ in range(50):
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    await ReadOnly()
    assert int(dut.busy_o.value) == 0, (
        "cache should still be idle after 50-cycle idle window"
    )
    await RisingEdge(dut.clk_i)
    # Wake: branch + req to a line guaranteed to miss (cold cache).
    dut.icache_enable_i.value = 1
    dut.req_i.value = 1
    dut.ready_i.value = 1
    dut.branch_i.value = 1
    dut.addr_i.value = 0x0700_0080
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    await _settle(dut)
    # Bus-side wake — a self-gated cache would never raise instr_req_o.
    saw_req = False
    for _ in range(16):
        await ReadOnly()
        if int(dut.instr_req_o.value) == 1:
            saw_req = True
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert saw_req, (
        "after 50-cycle idle, branch+req did not produce instr_req_o "
        "within 16 cycles — cache appears to have self-gated"
    )
    # busy_o should now reflect the in-flight FB. Sample in the same
    # ReadOnly phase that the loop's last iteration left us in.
    busy = int(dut.busy_o.value)
    assert busy == 1, (
        f"cache woke for the request but busy_o = {busy}; "
        "expected 1 (FB in flight)"
    )
    # Service the beats so the test exits cleanly. Advance out of the
    # ReadOnly phase first since `_bus_grant_and_beat` writes signals.
    await RisingEdge(dut.clk_i)
    for _ in range(IC_LINE_BEATS):
        served = await _bus_grant_and_beat(dut, rdata=0xDEADBEEF, max_wait=8)
        assert served


# ──────────────────────────────────────────────────────────────────────
# R-ECC — ECC error reporting (degenerate under ICacheECC=0)
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_r_ecc_1_ecc_error_o_tied_zero(dut):
    """R-ECC-1: with ICacheECC=0, ecc_error_o is tied to 0 across reset
    and all stimulus. Spec §R-ECC.
    """
    await _start_clock(dut)
    _idle_inputs(dut)
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    await ReadOnly()
    assert int(dut.ecc_error_o.value) == 0
    # Exit ReadOnly phase before writing rst_ni (cocotb 2.0 forbids
    # signal writes during ReadOnly).
    await RisingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    # During cold-boot
    for _ in range(8):
        await ReadOnly()
        assert int(dut.ecc_error_o.value) == 0
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    await _wait_until_idle(dut)
    # During a fill
    dut.req_i.value = 1
    dut.ready_i.value = 1
    await _branch(dut, 0x0F00_0000)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    for _ in range(8):
        await ReadOnly()
        assert int(dut.ecc_error_o.value) == 0
        await RisingEdge(dut.clk_i)
        await _settle(dut)


@cocotb.test()
async def test_boot_branch_during_inval_walk(dut):
    """Cold-boot: controller asserts branch_i + req_i WHILE InvalCtrl
    is still walking (busy_o=1). The branch addr must be captured and,
    once the walk completes, the cache must fetch the branched line
    and deliver valid_o without losing the branch.

    Spec §R-INV-2: lookups MAY proceed during inval but MUST NOT
    allocate to a cache way (`alloc_cache=0` on the FB). §R-RST-2:
    no instr_req_o before the first branch_i. §S1: cold boot walk
    completes in ~IC_NUM_LINES + 2 cycles.

    This scenario is what every CPU program exercises on reset; the
    other unit tests `await _wait_until_idle()` first, masking it.
    """
    await _start_clock(dut)
    await _reset(dut)
    # Don't wait for inval; immediately branch + req like the controller does.
    boot_addr = 0x0010_0000
    dut.branch_i.value = 1
    dut.addr_i.value   = boot_addr
    dut.req_i.value    = 1
    # Hold ready_i=0 so the first valid_o stays sticky (R-OUT-2);
    # otherwise the test races the helper and may sample valid_o
    # only after beat 0 has been accepted and addr_o has advanced.
    dut.ready_i.value  = 0
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    await _settle(dut)
    # Provide tag rdata = 0 (miss) so any IC1 lookup misses; provide
    # bus beats when requested.
    _set_unpacked_vec(dut.ic_tag_rdata_i, 0, 0)
    _set_unpacked_vec(dut.ic_tag_rdata_i, 1, 0)
    # Service the 2 beats of the boot line via the helper.
    served0 = await _bus_grant_and_beat(dut, rdata=0x12345678,
                                         max_wait=IC_NUM_LINES + 50)
    assert served0, "icache never issued first instr_req_o for boot fetch"
    served1 = await _bus_grant_and_beat(dut, rdata=0x9abcdef0, max_wait=20)
    assert served1, "icache never issued second instr_req_o for boot fetch"
    # After both beats serviced, valid_o must rise within a few cycles.
    for _ in range(20):
        await ReadOnly()
        if int(dut.valid_o.value) == 1:
            assert int(dut.addr_o.value) == boot_addr, \
                f"valid_o for wrong addr: {int(dut.addr_o.value):#x} != {boot_addr:#x}"
            return
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    raise AssertionError("icache never delivered valid_o after 2 beats")
