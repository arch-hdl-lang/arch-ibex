"""Standalone cocotb scenarios for `ibex_prefetch_buffer` (basic suite).

Each `@cocotb.test` covers one Requirement from
`changes/port-prefetch_buffer/specs/prefetch_buffer/spec.md`, walking the
single most representative scenario from the spec for that requirement.

In-scope parameters: NUM_REQS = 2.

Reset semantics: asynchronous, active-low (`rst_ni`).
Timing model:
  - `instr_req_o` and `instr_addr_o` are combinational outputs.
  - After driving inputs use `await Timer(1, "ns")` to observe
    combinational outputs before any clock edge.
  - After `RisingEdge(dut.clk_i)` use `await Timer(1, "ns")` to let
    registered outputs settle before sampling.

OBI handshake convention used throughout:
  - Drive `instr_gnt_i = 1` to grant `instr_req_o` high; the grant is
    sampled on the rising clock edge.
  - Drive `instr_rvalid_i = 1` (with rdata/err) for one cycle per
    previously granted request; the rvalid is sampled on the rising edge
    that follows.

Boot sequence: After reset, one branch cycle (`branch_i = 1`,
`addr_i = BOOT_ADDR`) is issued.  This mirrors CPU boot behaviour and
initialises the FIFO's internal PC to a known value.
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

# ── Test parameters ──────────────────────────────────────────────────────
CLK_PERIOD_NS = 10  # 100 MHz
BOOT_ADDR = 0x8000_0000


# ── Helpers ──────────────────────────────────────────────────────────────
async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())


async def _idle_inputs(dut):
    """Drive all DUT inputs to a benign idle state."""
    dut.req_i.value = 0
    dut.branch_i.value = 0
    dut.addr_i.value = 0
    dut.ready_i.value = 0
    dut.instr_gnt_i.value = 0
    dut.instr_rdata_i.value = 0
    dut.instr_err_i.value = 0
    dut.instr_rvalid_i.value = 0


async def _reset(dut):
    """Apply async active-low reset for 2 cycles then release."""
    await _idle_inputs(dut)
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")


async def _boot(dut, addr: int = BOOT_ADDR):
    """Issue one branch cycle to initialise the fetch address.

    Per the spec: 'CPU resets with a branch, so the very first IF-stage
    operation after reset SHALL be a branch that loads addr_i.'
    This seeds the FIFO's internal PC and lets the DUT start issuing
    fetch requests.
    """
    dut.branch_i.value = 1
    dut.addr_i.value = addr & 0xFFFF_FFFF
    dut.req_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    dut.addr_i.value = 0
    await Timer(1, "ns")


async def _grant_current_request(dut):
    """Assert instr_gnt_i for one cycle to grant the pending OBI request.

    Waits for the current clock edge and then deasserts the grant.
    Call this while instr_req_o is high.
    """
    dut.instr_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.instr_gnt_i.value = 0
    await Timer(1, "ns")


async def _send_rvalid(dut, rdata: int = 0xDEAD_BEEF, err: int = 0):
    """Issue one rvalid pulse (one cycle) to return a response."""
    dut.instr_rvalid_i.value = 1
    dut.instr_rdata_i.value = rdata & 0xFFFF_FFFF
    dut.instr_err_i.value = err & 1
    await RisingEdge(dut.clk_i)
    dut.instr_rvalid_i.value = 0
    dut.instr_rdata_i.value = 0
    dut.instr_err_i.value = 0
    await Timer(1, "ns")


# ── Tests: one per spec Requirement ──────────────────────────────────────

@cocotb.test()
async def test_request_issuance_gating(dut):
    """Spec Req: Request Issuance Gating — verifies that `instr_req_o` is
    only asserted when `req_i` is high, the FIFO has a free slot, and the
    outstanding queue is not full.  Also verifies that `instr_req_o` is
    suppressed when `req_i` is low.

    Scenario: New request issued when FIFO has space and no pending request.
    After boot, assert req_i = 1 with FIFO empty → instr_req_o must be
    high combinationally.  Drop req_i = 0 → instr_req_o must go low.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    # After boot+branch, req_i was held high. The FIFO is empty, outstanding
    # queue is empty → instr_req_o should be asserted.
    dut.req_i.value = 1
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 1, (
        "instr_req_o must be high when req_i=1 and FIFO/queue have space"
    )
    # Verify address is word-aligned (bits[1:0] == 2'b00).
    addr = int(dut.instr_addr_o.value)
    assert (addr & 0x3) == 0, (
        f"instr_addr_o[1:0] must be 2'b00 but got 0x{addr:08X}"
    )

    # Grant the boot request so valid_req_q is cleared.  Without this,
    # the OBI hold-until-granted rule keeps valid_req_q=1, and dropping
    # req_i cannot suppress instr_req_o while an ungranted request is held.
    await _grant_current_request(dut)

    # Suppress: drop req_i → instr_req_o must go low (no ungranted held request).
    dut.req_i.value = 0
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 0, (
        "instr_req_o must be low when req_i = 0 and no held request"
    )


@cocotb.test()
async def test_hold_until_granted(dut):
    """Spec Req: OBI Hold-Until-Granted — verifies that `instr_req_o` and
    `instr_addr_o` remain stable across multiple cycles until `instr_gnt_i`
    is asserted.

    Scenario: Ungranted request held through back-to-back cycles.
    Observe instr_req_o = 1 and capture address A; keep instr_gnt_i = 0
    for 2 extra cycles; confirm address unchanged; then grant and confirm
    the request can be retracted.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    dut.instr_gnt_i.value = 0
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 1, "instr_req_o must be high after boot with req_i=1"
    held_addr = int(dut.instr_addr_o.value)

    # Hold for 2 extra cycles without granting.
    for cycle in range(2):
        await RisingEdge(dut.clk_i)
        await Timer(1, "ns")
        assert int(dut.instr_req_o.value) == 1, (
            f"instr_req_o must remain high on ungrated cycle {cycle}"
        )
        assert int(dut.instr_addr_o.value) == held_addr, (
            f"instr_addr_o must remain stable on ungrated cycle {cycle}"
        )

    # Now grant — request should be accepted.
    dut.instr_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.instr_gnt_i.value = 0
    await Timer(1, "ns")
    # After grant the module is free to advance; we just verify no crash.
    # (The new req state depends on FIFO back-pressure; not checked here.)


@cocotb.test()
async def test_fetch_addr_sequencing(dut):
    """Spec Req: Fetch Address Sequencing — verifies that the fetch address
    advances by 4 after each granted request and stays word-aligned.

    Scenario: Sequential prefetch — grant two back-to-back requests and
    confirm each new address is the previous plus 4.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 1, "DUT must issue a request after boot"
    addr0 = int(dut.instr_addr_o.value)
    assert (addr0 & 0x3) == 0, "First fetch address must be word-aligned"

    # Grant the first request.
    dut.instr_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.instr_gnt_i.value = 0
    await Timer(1, "ns")

    # A new request should be issued (outstanding queue has one slot free).
    assert int(dut.instr_req_o.value) == 1, "DUT must issue a new request after first grant"
    addr1 = int(dut.instr_addr_o.value)
    assert (addr1 & 0x3) == 0, "Second fetch address must be word-aligned"
    assert addr1 == addr0 + 4, (
        f"Expected addr1 = 0x{addr0+4:08X} but got 0x{addr1:08X}"
    )


@cocotb.test()
async def test_branch_flush_and_discard(dut):
    """Spec Req: Branch Flush and Discard — verifies that on `branch_i`
    any outstanding granted requests are marked for discard and that a
    subsequent rvalid does NOT push data into the FIFO (valid_o stays low).

    Scenario: In-flight request discarded after branch.
    Issue a request, grant it, send a branch (1 outstanding slot live),
    then send rvalid → valid_o must remain 0 (data discarded).
    """
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    # Step 1: issue and grant one request.
    dut.req_i.value = 1
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 1

    dut.instr_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.instr_gnt_i.value = 0
    dut.req_i.value = 0
    await Timer(1, "ns")
    # One slot is now outstanding, awaiting rvalid.

    # Step 2: branch before rvalid arrives → marks the slot for discard.
    dut.branch_i.value = 1
    dut.addr_i.value = 0x9000_0000
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    dut.addr_i.value = 0
    await Timer(1, "ns")

    # Step 3: rvalid arrives — should be discarded.
    await _send_rvalid(dut, rdata=0xCAFE_BABE, err=0)

    # FIFO should be empty: valid_o == 0.
    assert int(dut.valid_o.value) == 0, (
        "valid_o must be 0 after discarded rvalid (branch saw the request)"
    )


@cocotb.test()
async def test_outstanding_request_tracking(dut):
    """Spec Req: Outstanding Request Tracking — verifies that after two
    back-to-back grants with no rvalid, the module's outstanding queue is
    full and `instr_req_o` is suppressed even when `req_i = 1`.

    Scenario: Two back-to-back requests accumulate in the queue.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 1, "First request should be issued"

    # Grant request #1.
    dut.instr_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.instr_gnt_i.value = 0
    await Timer(1, "ns")
    # Outstanding queue has 1 slot used; a second request should be issued.
    assert int(dut.instr_req_o.value) == 1, "Second request should be issued (one free slot)"

    # Grant request #2.
    dut.instr_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.instr_gnt_i.value = 0
    await Timer(1, "ns")
    # Both slots occupied → instr_req_o must be low even with req_i = 1.
    assert int(dut.instr_req_o.value) == 0, (
        "instr_req_o must be low when outstanding queue is full (NUM_REQS=2 slots used)"
    )


@cocotb.test()
async def test_fifo_backpressure_accounting(dut):
    """Spec Req: FIFO Back-Pressure Accounting — verifies that the module
    does not issue a new request when the combined FIFO fill + outstanding
    slots leave no free entry.

    Scenario: FIFO deep-slot 1 occupied, one request outstanding — no new issue.
    ibex_fetch_fifo.busy_o[i] = valid_q[i+1], so it reports occupancy of
    the two NON-output slots (slots 1 and 2).  One FIFO entry at slot 0
    (the output) does NOT contribute to busy_o.  To produce fifo_combined
    = 2'b11 we need slot 1 occupied (2 responses received with out_ready_i=0)
    PLUS one outstanding request (rdata_outstanding_q[0]=1):
      fifo_combined[0] = busy[0] | rev[0] = valid_q[1] | rdata_outstanding_q[1] = 1 | 0 = 1
      fifo_combined[1] = busy[1] | rev[1] = valid_q[2] | rdata_outstanding_q[0] = 0 | 1 = 1
    Sequence: grant+rvalid × 2 (fills slots 0 then 1) then grant #3 (no rvalid).
    """
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 1

    # Grant boot request and return its response → FIFO slot 0 filled.
    await _grant_current_request(dut)
    await _send_rvalid(dut, rdata=0x0000_0013, err=0)

    # New request is pending (valid_req_q latched during rvalid cycle).
    assert int(dut.instr_req_o.value) == 1, "second request should be pending"

    # Grant it and return its response → FIFO slot 1 filled (slot 0 occupied,
    # so lowest_free_1=1 routes the push to slot 1).
    await _grant_current_request(dut)
    await _send_rvalid(dut, rdata=0x0000_0013, err=0)

    # FIFO: valid_q = {0, 1, 1}. busy_o = {valid_q[2], valid_q[1]} = 2'b01.
    # A third request is pending (rdata_outstanding_q empty, fifo_ready=1 still).
    assert int(dut.instr_req_o.value) == 1, "third request should be pending"

    # Grant it (no rvalid) → rdata_outstanding_q[0] = 1, valid_req_q = 0.
    await _grant_current_request(dut)

    # State: fifo_busy_w=2'b01 (slot 1 filled), rdata_outstanding_rev=2'b10 (slot 0 outstanding).
    # fifo_combined = 2'b01 | 2'b10 = 2'b11 → fifo_ready=0 → instr_req_o must be low.
    assert int(dut.instr_req_o.value) == 0, (
        "instr_req_o must be suppressed: combined FIFO+outstanding overlay is full"
    )


@cocotb.test()
async def test_busy_status(dut):
    """Spec Req: Busy Status — verifies that `busy_o` is high when
    `instr_req_o` is asserted, high when a slot is outstanding (even with
    instr_req_o low), and low only when both conditions are false.

    Walks all three busy Scenarios from the spec.
    """
    await _start_clock(dut)
    await _reset(dut)

    # Immediately after reset (before boot): no request, no outstanding →
    # busy_o must be 0.
    await Timer(1, "ns")
    assert int(dut.busy_o.value) == 0, "busy_o must be 0 immediately after reset"

    await _boot(dut)

    # Scenario: Busy while request is asserted.
    dut.req_i.value = 1
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 1, "instr_req_o must be high"
    assert int(dut.busy_o.value) == 1, "busy_o must be 1 when instr_req_o is high"

    # Grant the request; now one slot is outstanding.
    dut.instr_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.instr_gnt_i.value = 0
    # Drop req_i so no new request is issued.
    dut.req_i.value = 0
    await Timer(1, "ns")

    # Scenario: Busy while awaiting rvalid (instr_req_o may be low).
    # Confirm busy_o = 1 even if instr_req_o is currently low.
    assert int(dut.busy_o.value) == 1, (
        "busy_o must be 1 while at least one outstanding slot is pending rvalid"
    )

    # Return rvalid to clear the outstanding slot.
    await _send_rvalid(dut)

    # Scenario: Idle after all responses returned.
    assert int(dut.busy_o.value) == 0, (
        "busy_o must be 0 after all outstanding slots are cleared and instr_req_o is low"
    )


@cocotb.test()
async def test_reset_state(dut):
    """Spec Req: Reset State — verifies that after rst_ni is deasserted
    the module initialises with no active request, no pending discard, and
    all outstanding slots cleared.

    Scenario: Post-reset state, before first branch.
    Sample directly after reset with req_i = 0 — no bus request and no
    busy should be asserted.
    """
    await _start_clock(dut)
    await _idle_inputs(dut)
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")

    # While reset is held, all control state must be cleared.
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 0, "instr_req_o must be 0 while reset is held"
    assert int(dut.busy_o.value) == 0, "busy_o must be 0 while reset is held"

    # Release reset; give one clock edge for any registered state to settle.
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")

    # req_i = 0 → no bus request should be issued.
    assert int(dut.instr_req_o.value) == 0, (
        "instr_req_o must be 0 after reset with req_i = 0"
    )
    assert int(dut.busy_o.value) == 0, (
        "busy_o must be 0 after reset before any request is made"
    )


@cocotb.test()
async def test_fifo_push_gating_on_discard(dut):
    """Spec Req: FIFO Push Gating on Discard — verifies the two sub-scenarios:
    (a) Normal rvalid with no discard bit set → valid_o goes high.
    (b) Rvalid with discard bit set (after branch) → valid_o stays low.

    This test exercises scenario (a) then resets and exercises scenario (b).
    """
    # ── Scenario (a): normal push (no discard) ─────────────────────────
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 1

    # Grant and return rvalid — no branch, so discard bit is clear.
    dut.instr_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.instr_gnt_i.value = 0
    dut.req_i.value = 0
    await Timer(1, "ns")

    await _send_rvalid(dut, rdata=0xAAAA_AAA3, err=0)

    # Data should have been pushed — valid_o must be high.
    assert int(dut.valid_o.value) == 1, (
        "valid_o must be 1 after a non-discarded rvalid"
    )

    # ── Scenario (b): discarded rvalid (branch was seen) ───────────────
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 1

    dut.instr_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.instr_gnt_i.value = 0
    dut.req_i.value = 0
    await Timer(1, "ns")

    # Branch: marks the outstanding slot for discard.
    dut.branch_i.value = 1
    dut.addr_i.value = 0xA000_0000
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    dut.addr_i.value = 0
    await Timer(1, "ns")

    await _send_rvalid(dut, rdata=0xBBBB_BBB3, err=0)

    # Data must have been discarded — valid_o must be 0.
    assert int(dut.valid_o.value) == 0, (
        "valid_o must be 0 after a discarded rvalid (branch set the discard bit)"
    )


@cocotb.test()
async def test_fifo_addr_forwarding(dut):
    """Spec Req: FIFO Address Forwarding — verifies that `addr_i` is
    forwarded to the FIFO's `in_addr_i` on every cycle, and that a branch
    correctly seeds the FIFO's internal PC so `addr_o` reflects the branch
    target after data arrives.

    Scenario: Branch address reaches FIFO.
    Issue a branch with addr_i = T, then grant+rvalid a request.  After
    the data arrives, addr_o from the FIFO output must reflect T (the
    word-aligned branch target that was seeded into the FIFO).
    """
    await _start_clock(dut)
    await _reset(dut)

    BRANCH_TARGET = 0xC000_0004  # word-aligned

    # Boot at BRANCH_TARGET.
    dut.branch_i.value = 1
    dut.addr_i.value = BRANCH_TARGET
    dut.req_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    dut.addr_i.value = 0
    await Timer(1, "ns")

    # Grant the request that was (likely) issued on the boot cycle.
    assert int(dut.instr_req_o.value) == 1
    dut.instr_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.instr_gnt_i.value = 0
    dut.req_i.value = 0
    await Timer(1, "ns")

    # Return rvalid — data pushed into FIFO at address BRANCH_TARGET.
    await _send_rvalid(dut, rdata=0x1234_5673, err=0)

    # FIFO should now present the instruction at BRANCH_TARGET.
    assert int(dut.valid_o.value) == 1, "FIFO should have a valid instruction"
    assert int(dut.addr_o.value) == BRANCH_TARGET, (
        f"addr_o must equal branch target 0x{BRANCH_TARGET:08X}, "
        f"got 0x{int(dut.addr_o.value):08X}"
    )
    # Bit [0] always 0 (guaranteed by FIFO).
    assert (int(dut.addr_o.value) & 1) == 0
