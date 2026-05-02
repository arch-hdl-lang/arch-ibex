"""Full-regression cocotb scenarios for `ibex_prefetch_buffer`.

Covers every Scenario in
`changes/port-prefetch_buffer/specs/prefetch_buffer/spec.md` plus the
edge cases enumerated in the test-author brief:
  - Branch arriving the same cycle as `instr_rvalid_i` (simultaneous
    branch + rvalid — discard must fire).
  - Back-to-back grants without rvalid (fill up both outstanding slots).
  - Branch with 2 in-flight requests (both get discard bits).
  - `req_i` low for multiple cycles then high (verify no spurious requests).
  - `busy_o` transitions: goes low exactly when outstanding tracker empties
    and `instr_req_o` is low.

In-scope parameters: NUM_REQS = 2.

Reset semantics: asynchronous active-low (`rst_ni`).
Timing model:
  - `instr_req_o` / `instr_addr_o` are combinational.
  - Use `await Timer(1, "ns")` after driving inputs (before a clock edge)
    to observe combinational outputs.
  - Use `await RisingEdge(dut.clk_i); await Timer(1, "ns")` to sample
    registered outputs after a clock edge.
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

CLK_PERIOD_NS = 10
BOOT_ADDR = 0x8000_0000


# ── Helpers ──────────────────────────────────────────────────────────────

async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())


async def _idle_inputs(dut):
    dut.req_i.value = 0
    dut.branch_i.value = 0
    dut.addr_i.value = 0
    dut.ready_i.value = 0
    dut.instr_gnt_i.value = 0
    dut.instr_rdata_i.value = 0
    dut.instr_err_i.value = 0
    dut.instr_rvalid_i.value = 0


async def _reset(dut):
    """Async active-low reset; idles all inputs first."""
    await _idle_inputs(dut)
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")


async def _boot(dut, addr: int = BOOT_ADDR):
    """One-cycle branch to initialise the fetch address after reset."""
    dut.branch_i.value = 1
    dut.addr_i.value = addr & 0xFFFF_FFFF
    dut.req_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    dut.addr_i.value = 0
    await Timer(1, "ns")


async def _grant(dut):
    """Grant the pending OBI request for one cycle."""
    dut.instr_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.instr_gnt_i.value = 0
    await Timer(1, "ns")


async def _rvalid(dut, rdata: int = 0xDEAD_BEEF, err: int = 0):
    """Return one rvalid pulse."""
    dut.instr_rvalid_i.value = 1
    dut.instr_rdata_i.value = rdata & 0xFFFF_FFFF
    dut.instr_err_i.value = err & 1
    await RisingEdge(dut.clk_i)
    dut.instr_rvalid_i.value = 0
    dut.instr_rdata_i.value = 0
    dut.instr_err_i.value = 0
    await Timer(1, "ns")


async def _idle_cycle(dut):
    """One idle clock cycle with all inputs low (rst_ni kept high)."""
    await _idle_inputs(dut)
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")


async def _grant_current_request(dut):
    """Grant the currently pending OBI request, draining valid_req_q back to 0."""
    await _grant(dut)


# ── Spec Req 1: Request Issuance Gating ──────────────────────────────────

@cocotb.test()
async def req1_new_request_when_fifo_has_space(dut):
    """Req 1 Scenario: New request issued when FIFO has space and no
    pending request. After boot with req_i = 1, FIFO is empty and the
    outstanding queue is empty → instr_req_o must be asserted with a
    word-aligned address."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 1, (
        "instr_req_o must be high: req_i=1, FIFO empty, queue empty"
    )
    assert (int(dut.instr_addr_o.value) & 0x3) == 0, (
        "instr_addr_o[1:0] must be 2'b00"
    )


@cocotb.test()
async def req1_request_suppressed_when_req_i_low(dut):
    """Req 1 Scenario: Request suppressed when req_i = 0. Even with FIFO
    empty and outstanding queue empty, instr_req_o must stay low."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    # Drain the boot request (OBI hold keeps valid_req_q=1 until granted).
    await _grant_current_request(dut)

    dut.req_i.value = 0
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 0, (
        "instr_req_o must be suppressed when req_i = 0"
    )


@cocotb.test()
async def req1_branch_forces_request_despite_fifo_full(dut):
    """Req 1 Scenario: Branch forces request issuance regardless of FIFO fill.
    Fill the FIFO by granting + rvalid-ing two requests (two FIFO slots
    occupied), then branch. With branch_i = 1, the FIFO-full back-pressure
    term is overridden → instr_req_o MAY be asserted (outstanding queue
    is checked: both slots just cleared by the branch's discard mechanism,
    so queue is not full). Verify instr_req_o is high after the branch."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")

    # Grant request #1 and return rvalid → FIFO slot 0 filled.
    await _grant(dut)
    await _rvalid(dut, rdata=0x1111_1113)

    # Grant request #2 and return rvalid → FIFO slot 1 filled (busy_o[0]=1).
    assert int(dut.instr_req_o.value) == 1
    await _grant(dut)
    await _rvalid(dut, rdata=0x2222_2223)

    # Grant request #3 without rvalid → 1 outstanding (rdata_outstanding_q[0]=1).
    # fifo_combined = busy_o(2'b01) | rdata_outstanding_rev(2'b10) = 2'b11 → full.
    assert int(dut.instr_req_o.value) == 1
    await _grant(dut)

    # FIFO combined overlay is now full. With req_i=1 and no branch, no new req.
    assert int(dut.instr_req_o.value) == 0, (
        "instr_req_o must be low when FIFO+outstanding overlay is full and no branch"
    )

    # Now branch → overrides FIFO-full back-pressure.
    dut.branch_i.value = 1
    dut.addr_i.value = 0x8000_0000
    await Timer(1, "ns")
    # With branch_i=1 and outstanding queue empty, instr_req_o should be high.
    assert int(dut.instr_req_o.value) == 1, (
        "branch_i overrides FIFO-full: instr_req_o must be asserted"
    )
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    dut.addr_i.value = 0
    await Timer(1, "ns")


# ── Spec Req 2: OBI Hold-Until-Granted ───────────────────────────────────

@cocotb.test()
async def req2_ungrated_request_held_through_cycles(dut):
    """Req 2 Scenario: Ungranted request held through back-to-back cycles.
    Observe instr_req_o = 1 with address A; keep instr_gnt_i = 0 for
    3 cycles; confirm address and request unchanged."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    dut.instr_gnt_i.value = 0
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 1
    held_addr = int(dut.instr_addr_o.value)

    for i in range(3):
        await RisingEdge(dut.clk_i)
        await Timer(1, "ns")
        assert int(dut.instr_req_o.value) == 1, (
            f"instr_req_o must remain asserted on ungrated cycle {i}"
        )
        assert int(dut.instr_addr_o.value) == held_addr, (
            f"instr_addr_o must stay at 0x{held_addr:08X} on cycle {i}"
        )


@cocotb.test()
async def req2_request_released_after_grant(dut):
    """Req 2 Scenario: Request released after grant. After instr_gnt_i is
    asserted, instr_addr_o MAY change to the next fetch address and
    instr_req_o reflects fresh gating conditions on the next cycle."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 1
    addr_before = int(dut.instr_addr_o.value)

    # Grant the request.
    dut.instr_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.instr_gnt_i.value = 0
    await Timer(1, "ns")

    # After grant: a new request should be issued (FIFO still has space,
    # one outstanding slot used, one free). Address must have advanced.
    assert int(dut.instr_req_o.value) == 1, (
        "DUT should issue a new request immediately after the first grant"
    )
    addr_after = int(dut.instr_addr_o.value)
    assert addr_after == addr_before + 4, (
        f"Address must advance by 4 after grant: expected 0x{addr_before+4:08X}, "
        f"got 0x{addr_after:08X}"
    )


# ── Spec Req 3: Fetch Address Sequencing ─────────────────────────────────

@cocotb.test()
async def req3_sequential_prefetch(dut):
    """Req 3 Scenario: Sequential prefetch. Grant three consecutive requests
    and verify each issued address is the previous plus 4 (word-aligned)."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    addr0 = int(dut.instr_addr_o.value)
    assert (addr0 & 0x3) == 0

    # Grant #1.
    dut.instr_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.instr_gnt_i.value = 0
    await Timer(1, "ns")
    addr1 = int(dut.instr_addr_o.value)
    assert addr1 == addr0 + 4, f"After grant #1: expected {addr0+4:#010x}, got {addr1:#010x}"

    # Return rvalid for slot #1 to free a FIFO slot before granting #2.
    await _rvalid(dut)

    # Grant #2.
    assert int(dut.instr_req_o.value) == 1, "should have a pending request"
    dut.instr_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.instr_gnt_i.value = 0
    await Timer(1, "ns")
    addr2 = int(dut.instr_addr_o.value)
    assert addr2 == addr0 + 8, f"After grant #2: expected {addr0+8:#010x}, got {addr2:#010x}"


@cocotb.test()
async def req3_branch_redirects_fetch_address(dut):
    """Req 3 Scenario: Branch redirects fetch address. After a branch with
    addr_i = T, the next bus address must be {T[31:2], 2'b00}."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    # Grant the initial request to advance out of boot.
    dut.req_i.value = 1
    await Timer(1, "ns")
    await _grant(dut)
    await _rvalid(dut)

    # A new request auto-fires when rvalid clears the outstanding slot.
    # Grant it so valid_req_q=0 before the branch; otherwise instr_addr
    # replays stored_addr_q instead of the branch target.
    await _grant_current_request(dut)

    # Issue a branch to a new target (unaligned input to test masking).
    BRANCH_TARGET = 0xABCD_E003  # bit[1:0] = 2'b11 → masked to 0xABCD_E000
    EXPECTED_ADDR = BRANCH_TARGET & 0xFFFF_FFFC

    dut.branch_i.value = 1
    dut.addr_i.value = BRANCH_TARGET
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    dut.addr_i.value = 0
    await Timer(1, "ns")

    # The new request address must reflect the word-aligned branch target.
    assert int(dut.instr_req_o.value) == 1, "req must be asserted after branch"
    new_addr = int(dut.instr_addr_o.value)
    assert new_addr == EXPECTED_ADDR, (
        f"After branch, instr_addr_o must be {EXPECTED_ADDR:#010x}, "
        f"got {new_addr:#010x}"
    )


@cocotb.test()
async def req3_held_request_address_does_not_advance(dut):
    """Req 3 Scenario: Held-request address does not advance while
    instr_gnt_i = 0 and branch_i = 0."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    dut.instr_gnt_i.value = 0
    await Timer(1, "ns")
    held_addr = int(dut.instr_addr_o.value)

    for _ in range(4):
        await RisingEdge(dut.clk_i)
        await Timer(1, "ns")
        assert int(dut.instr_addr_o.value) == held_addr, (
            "Address must not advance while request is held (gnt=0, branch=0)"
        )


# ── Spec Req 4: Branch Flush and Discard ─────────────────────────────────

@cocotb.test()
async def req4_in_flight_request_discarded_after_branch(dut):
    """Req 4 Scenario: In-flight request discarded after branch. Grant one
    request, then branch before rvalid arrives. The rvalid data must be
    silently dropped (valid_o stays 0)."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    await _grant(dut)
    dut.req_i.value = 0
    await Timer(1, "ns")

    # Branch before rvalid → marks slot for discard.
    dut.branch_i.value = 1
    dut.addr_i.value = 0x9000_0000
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    dut.addr_i.value = 0
    await Timer(1, "ns")

    # rvalid arrives — must be discarded.
    await _rvalid(dut, rdata=0xBAD1_BAD0)
    assert int(dut.valid_o.value) == 0, (
        "valid_o must be 0: rvalid was discarded after branch"
    )


@cocotb.test()
async def req4_ungranted_request_cancelled_by_branch(dut):
    """Req 4 Scenario: Ungranted request cancelled by branch. Branch occurs
    while instr_req_o is high but not yet granted. The module must track the
    request as a discardable slot (discard-pending flag propagates at grant
    time). After the bus eventually grants it, the subsequent rvalid is
    dropped."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    dut.instr_gnt_i.value = 0
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 1

    # Branch before the request is granted. The discard-pending flag is set.
    dut.branch_i.value = 1
    dut.addr_i.value = 0xB000_0000
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    dut.addr_i.value = 0
    await Timer(1, "ns")

    # Bus now grants the (stale) request.
    dut.instr_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.instr_gnt_i.value = 0
    await Timer(1, "ns")

    # rvalid arrives for the stale grant — must be discarded.
    await _rvalid(dut, rdata=0xBAD2_BAD0)
    assert int(dut.valid_o.value) == 0, (
        "valid_o must be 0: rvalid was for a request that was pre-branch"
    )


@cocotb.test()
async def req4_branch_with_no_in_flight_requests(dut):
    """Req 4 Scenario: Branch with no in-flight requests. FIFO is cleared,
    fetch address is loaded from addr_i, and discard state remains all-zero
    (nothing to discard)."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    # Grant the boot request so valid_req_q drains to 0 (OBI hold-until-granted).
    await _grant_current_request(dut)

    # Ensure no outstanding requests: drop req_i and don't grant anything.
    dut.req_i.value = 0
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")

    NEW_PC = 0xC000_0000
    dut.branch_i.value = 1
    dut.addr_i.value = NEW_PC
    dut.req_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    dut.addr_i.value = 0
    await Timer(1, "ns")

    # FIFO should be empty (valid_o = 0) and fetch address should be NEW_PC.
    assert int(dut.valid_o.value) == 0, "FIFO must be empty after branch with no in-flight"
    assert int(dut.instr_req_o.value) == 1, "New request should be issued from NEW_PC"
    assert int(dut.instr_addr_o.value) == NEW_PC, (
        f"instr_addr_o must reflect the branch target {NEW_PC:#010x}"
    )


# ── Spec Req 5: Outstanding Request Tracking ─────────────────────────────

@cocotb.test()
async def req5_two_back_to_back_requests_fill_queue(dut):
    """Req 5 Scenario: Two back-to-back requests accumulate in the queue.
    Grant two consecutive requests without returning rvalid. After the
    second grant, both slots are occupied → instr_req_o must be low."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 1

    await _grant(dut)
    assert int(dut.instr_req_o.value) == 1, "second request should be pending after first grant"

    await _grant(dut)
    assert int(dut.instr_req_o.value) == 0, (
        "instr_req_o must be low when both NUM_REQS=2 slots are outstanding"
    )


@cocotb.test()
async def req5_rvalid_shifts_queue_down(dut):
    """Req 5 Scenario: rvalid shifts the queue down. Fill both outstanding
    slots, then send one rvalid → one slot is freed → instr_req_o goes high
    again (if req_i is still asserted)."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")

    # Fill both outstanding slots.
    await _grant(dut)
    await _grant(dut)
    assert int(dut.instr_req_o.value) == 0, "queue must be full after two grants"

    # Return rvalid for slot 0.
    await _rvalid(dut)

    # One slot freed; a new request should be allowed.
    assert int(dut.instr_req_o.value) == 1, (
        "instr_req_o must be asserted again after rvalid frees a slot"
    )


# ── Spec Req 6: FIFO Back-Pressure Accounting ────────────────────────────

@cocotb.test()
async def req6_fifo_full_and_one_outstanding_no_new_req(dut):
    """Req 6 Scenario: FIFO half-full and one request outstanding — no new
    issue permitted. fifo_busy | reversed_outstanding = all-ones → no req.

    Strategy: Grant req #1 and return rvalid (1 FIFO slot used). Grant
    req #2 (1 outstanding slot). Now combined overlay full → instr_req_o = 0.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")

    # Grant req #1; return rvalid → FIFO slot 0 filled.
    await _grant(dut)
    await _rvalid(dut, rdata=0x1111_1113)

    # Grant req #2; return rvalid → FIFO slot 1 filled (busy_o[0]=1).
    assert int(dut.instr_req_o.value) == 1
    await _grant(dut)
    await _rvalid(dut, rdata=0x2222_2223)

    # Grant req #3 without rvalid → 1 outstanding (rdata_outstanding_q[0]=1).
    # fifo_combined = busy_o(2'b01) | rdata_outstanding_rev(2'b10) = 2'b11.
    assert int(dut.instr_req_o.value) == 1
    await _grant(dut)
    await Timer(1, "ns")

    # Overlay = all-ones → no new request.
    assert int(dut.instr_req_o.value) == 0, (
        "Combined FIFO+outstanding overlay is full; instr_req_o must be 0"
    )


@cocotb.test()
async def req6_fifo_empty_no_outstanding_permits_request(dut):
    """Req 6 Scenario: FIFO empty and no outstanding requests — request
    is permitted. After a clean branch/boot with req_i = 1, instr_req_o
    must be high immediately."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 1, (
        "FIFO empty and no outstanding → new request must be permitted"
    )


# ── Spec Req 7: Busy Status ───────────────────────────────────────────────

@cocotb.test()
async def req7_busy_while_request_asserted(dut):
    """Req 7 Scenario: Busy while request is asserted. When instr_req_o is
    high (pending grant), busy_o must be 1."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 1
    assert int(dut.busy_o.value) == 1, "busy_o must be 1 when instr_req_o is high"


@cocotb.test()
async def req7_busy_while_awaiting_rvalid(dut):
    """Req 7 Scenario: Busy while awaiting rvalid. Even if instr_req_o is
    low, busy_o must be 1 while at least one outstanding slot is occupied."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    await _grant(dut)

    # Drop req_i so no new request is issued.
    dut.req_i.value = 0
    await Timer(1, "ns")

    # One slot outstanding, instr_req_o may be low (req_i=0) but busy_o = 1.
    assert int(dut.busy_o.value) == 1, (
        "busy_o must be 1 while an outstanding slot awaits rvalid"
    )


@cocotb.test()
async def req7_idle_after_all_responses_returned(dut):
    """Req 7 Scenario: Idle after all responses returned. busy_o must be 0
    when the outstanding tracker is all-zero and instr_req_o is low."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    await _grant(dut)
    dut.req_i.value = 0
    await Timer(1, "ns")

    assert int(dut.busy_o.value) == 1, "precondition: one outstanding slot"

    # Return rvalid to clear the slot.
    await _rvalid(dut)

    assert int(dut.busy_o.value) == 0, (
        "busy_o must be 0 after all outstanding slots are cleared with req_i=0"
    )
    assert int(dut.instr_req_o.value) == 0, "instr_req_o must be 0 with req_i=0"


# ── Spec Req 8: Reset State ───────────────────────────────────────────────

@cocotb.test()
async def req8_post_reset_state_before_branch(dut):
    """Req 8 Scenario: Post-reset state before first branch. instr_req_o = 0,
    outstanding tracker all-zero, busy_o = 0. No bus request issued until
    req_i and valid gating conditions are met."""
    await _start_clock(dut)
    await _idle_inputs(dut)
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 0, "instr_req_o must be 0 while in reset"
    assert int(dut.busy_o.value) == 0, "busy_o must be 0 while in reset"

    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")

    assert int(dut.instr_req_o.value) == 0, "instr_req_o must be 0 after reset with req_i=0"
    assert int(dut.busy_o.value) == 0, "busy_o must be 0 after reset before any request"

    # With req_i = 0 still, no bus request should be issued after a clock.
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 0, "No spurious request after reset"


# ── Spec Req 9: FIFO Push Gating on Discard ──────────────────────────────

@cocotb.test()
async def req9_normal_rvalid_push_no_discard(dut):
    """Req 9 Scenario: Normal rvalid push (no discard). With discard bit
    clear, instr_rvalid_i causes a push → valid_o goes high."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    await _grant(dut)
    dut.req_i.value = 0

    await _rvalid(dut, rdata=0x1234_5673, err=0)

    assert int(dut.valid_o.value) == 1, (
        "valid_o must be 1 after a normal (non-discarded) rvalid"
    )


@cocotb.test()
async def req9_discarded_rvalid_no_push(dut):
    """Req 9 Scenario: Discarded rvalid (branch was seen). With discard bit
    set, in_valid_i to FIFO is suppressed → valid_o stays 0."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    await _grant(dut)
    dut.req_i.value = 0

    # Branch marks the outstanding slot for discard.
    dut.branch_i.value = 1
    dut.addr_i.value = 0xD000_0000
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    dut.addr_i.value = 0
    await Timer(1, "ns")

    await _rvalid(dut, rdata=0xBAD3_BAD0, err=0)

    assert int(dut.valid_o.value) == 0, (
        "valid_o must be 0: rvalid was discarded (discard bit was set)"
    )


# ── Spec Req 10: FIFO Address Forwarding ─────────────────────────────────

@cocotb.test()
async def req10_branch_address_reaches_fifo(dut):
    """Req 10 Scenario: Branch address reaches FIFO. With branch_i = 1 and
    addr_i = T, the FIFO's internal PC is seeded from T[31:1]. After the
    data arrives, addr_o reflects the word-aligned branch target."""
    await _start_clock(dut)
    await _reset(dut)

    BRANCH_TARGET = 0xE000_0008

    dut.branch_i.value = 1
    dut.addr_i.value = BRANCH_TARGET
    dut.req_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    dut.addr_i.value = 0
    await Timer(1, "ns")

    assert int(dut.instr_req_o.value) == 1
    await _grant(dut)
    dut.req_i.value = 0
    await _rvalid(dut, rdata=0xABCD_EF13)

    assert int(dut.valid_o.value) == 1, "FIFO should have a valid instruction"
    assert int(dut.addr_o.value) == BRANCH_TARGET, (
        f"addr_o must equal branch target {BRANCH_TARGET:#010x}, "
        f"got {int(dut.addr_o.value):#010x}"
    )
    assert (int(dut.addr_o.value) & 1) == 0, "addr_o[0] must always be 0"


# ── Edge Cases ────────────────────────────────────────────────────────────

@cocotb.test()
async def edge_simultaneous_branch_and_rvalid(dut):
    """Edge: Branch arriving the same cycle as instr_rvalid_i. The discard
    bit for the oldest slot is a registered tracker and may not yet be set
    when both signals coincide. The FIFO's clear_i wins (FIFO is flushed),
    and valid_o must be 0 after the combined event.

    Per spec §Integration constraints: 'clear_i and in_valid_i may coincide;
    the FIFO MUST let clear_i win.'  From the prefetch-buffer perspective,
    rvalid arriving the same cycle as branch_i targets the slot whose discard
    flag is about to be set; the FIFO flush clears any data that may have
    been pushed on that cycle.
    """
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    await _grant(dut)
    dut.req_i.value = 0

    # Drive branch and rvalid on the same cycle.
    dut.branch_i.value = 1
    dut.addr_i.value = 0xF000_0000
    dut.instr_rvalid_i.value = 1
    dut.instr_rdata_i.value = 0x5555_5553
    dut.instr_err_i.value = 0
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    dut.addr_i.value = 0
    dut.instr_rvalid_i.value = 0
    dut.instr_rdata_i.value = 0
    await Timer(1, "ns")

    # FIFO was cleared by branch; valid_o must be 0.
    assert int(dut.valid_o.value) == 0, (
        "valid_o must be 0: branch flush wins over concurrent rvalid"
    )


@cocotb.test()
async def edge_back_to_back_grants_no_rvalid(dut):
    """Edge: Back-to-back grants without rvalid. Fill both outstanding slots.
    Confirm instr_req_o is suppressed (queue full) and busy_o = 1."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")

    await _grant(dut)
    assert int(dut.busy_o.value) == 1, "busy_o after first grant"

    await _grant(dut)
    assert int(dut.instr_req_o.value) == 0, "queue full — no new request"
    assert int(dut.busy_o.value) == 1, "busy_o still high with 2 outstanding"


@cocotb.test()
async def edge_branch_with_two_in_flight_requests(dut):
    """Edge: Branch with 2 in-flight requests. Both outstanding slots must
    have their discard bits set. Verify that both subsequent rvalids are
    dropped (valid_o stays 0 after each)."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")

    # Fill both outstanding slots.
    await _grant(dut)
    await _grant(dut)
    dut.req_i.value = 0

    # Branch: both slots are outstanding → both get discard bits.
    dut.branch_i.value = 1
    dut.addr_i.value = 0x8000_0000
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    dut.addr_i.value = 0
    await Timer(1, "ns")

    # rvalid for slot 0 — must be discarded.
    await _rvalid(dut, rdata=0xBAD4_0000)
    assert int(dut.valid_o.value) == 0, "First discarded rvalid must not push FIFO"

    # rvalid for slot 1 — must also be discarded.
    await _rvalid(dut, rdata=0xBAD4_0001)
    assert int(dut.valid_o.value) == 0, "Second discarded rvalid must not push FIFO"


@cocotb.test()
async def edge_req_i_low_for_multiple_cycles_then_high(dut):
    """Edge: req_i low for multiple cycles then high. No spurious requests
    should be issued while req_i is low; once req_i goes high a request
    should be asserted promptly."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    # Drain the boot request so valid_req_q=0 (OBI hold keeps it high until granted).
    await _grant_current_request(dut)

    # Hold req_i low for 5 cycles.
    dut.req_i.value = 0
    for _ in range(5):
        await RisingEdge(dut.clk_i)
        await Timer(1, "ns")
        assert int(dut.instr_req_o.value) == 0, (
            "No spurious instr_req_o while req_i = 0"
        )

    # Raise req_i → request should be issued.
    dut.req_i.value = 1
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 1, (
        "instr_req_o must be asserted promptly when req_i goes high"
    )


@cocotb.test()
async def edge_busy_transitions_precise(dut):
    """Edge: busy_o transitions — goes low exactly when the outstanding
    tracker empties and instr_req_o is low.

    Sequence:
      1. req_i=1, grant, drop req_i → 1 outstanding, busy=1.
      2. rvalid arrives → outstanding=0, req_i=0 → busy must go to 0.
      3. Raise req_i again → busy goes to 1 (instr_req_o asserted).
    """
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    await _grant(dut)
    dut.req_i.value = 0
    await Timer(1, "ns")

    assert int(dut.busy_o.value) == 1, "busy after grant with outstanding slot"

    await _rvalid(dut)
    assert int(dut.busy_o.value) == 0, "busy must drop to 0 after rvalid clears the slot"

    # Re-raise req_i → busy goes high again.
    dut.req_i.value = 1
    await Timer(1, "ns")
    assert int(dut.instr_req_o.value) == 1
    assert int(dut.busy_o.value) == 1, "busy must re-assert when instr_req_o goes high"


@cocotb.test()
async def edge_instr_addr_o_word_aligned_every_cycle(dut):
    """Edge: instr_addr_o[1:0] must always be 2'b00 when instr_req_o is
    high, across sequential prefetches and after a branch to an unaligned
    address."""
    await _start_clock(dut)
    await _reset(dut)

    # Branch to an address whose bits[1:0] are non-zero to test masking.
    dut.branch_i.value = 1
    dut.addr_i.value = 0x8000_0003  # unaligned; should be masked to 0x8000_0000
    dut.req_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.branch_i.value = 0
    dut.addr_i.value = 0
    await Timer(1, "ns")

    for _ in range(3):
        if int(dut.instr_req_o.value) == 1:
            addr = int(dut.instr_addr_o.value)
            assert (addr & 0x3) == 0, (
                f"instr_addr_o[1:0] must be 2'b00 but got 0x{addr:08X}"
            )
        await _grant(dut)
        await _rvalid(dut)


@cocotb.test()
async def edge_valid_o_low_before_first_rvalid(dut):
    """Edge: valid_o must be 0 immediately after reset and after a branch,
    before any rvalid has arrived (FIFO is empty)."""
    await _start_clock(dut)
    await _reset(dut)

    # Immediately after reset, before boot.
    await Timer(1, "ns")
    assert int(dut.valid_o.value) == 0, "valid_o must be 0 before first rvalid"

    await _boot(dut)
    await Timer(1, "ns")
    assert int(dut.valid_o.value) == 0, "valid_o must be 0 after boot (FIFO still empty)"


@cocotb.test()
async def edge_rdata_and_addr_stable_when_consumer_stalls(dut):
    """Edge: rdata_o / valid_o / addr_o must remain stable across multiple
    cycles when ready_i = 0 (consumer stalls)."""
    await _start_clock(dut)
    await _reset(dut)
    await _boot(dut)

    dut.req_i.value = 1
    await Timer(1, "ns")
    await _grant(dut)
    dut.req_i.value = 0

    # Return rvalid to push data into FIFO.
    WORD = 0x1234_5673
    await _rvalid(dut, rdata=WORD, err=0)

    assert int(dut.valid_o.value) == 1, "valid_o must be 1 after rvalid"
    expected_rdata = int(dut.rdata_o.value)
    expected_addr = int(dut.addr_o.value)

    # Keep ready_i = 0 for 4 cycles; verify outputs stay stable.
    dut.ready_i.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk_i)
        await Timer(1, "ns")
        assert int(dut.valid_o.value) == 1, "valid_o must stay high when consumer stalls"
        assert int(dut.rdata_o.value) == expected_rdata, "rdata_o must be stable"
        assert int(dut.addr_o.value) == expected_addr, "addr_o must be stable"
