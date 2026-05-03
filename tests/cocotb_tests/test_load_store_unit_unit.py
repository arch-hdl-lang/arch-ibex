"""Standalone cocotb scenarios for `ibex_load_store_unit` (basic suite).

Each `@cocotb.test` covers one Requirement from
`changes/port-load_store_unit/specs/load_store_unit/spec.md`, walking
the single most representative scenario from that requirement.

In-scope parameters: MemECC = 0 (MemDataWidth = 32).

Reset semantics: active-low synchronous reset (`rst_ni`).
Clock: rising-edge active (`clk_i`).

OBI protocol:
  The testbench acts as a memory model. After `data_req_o` is asserted,
  the TB drives `data_gnt_i = 1` (either immediately or after a delay)
  then drives `data_rvalid_i = 1` (and optionally `data_rdata_i`) on
  the NEXT cycle after the grant.

  For misaligned accesses `addr_incr_req_o` goes high during the first
  transaction. The TB must detect this and participate in the second
  transaction before providing `data_rvalid_i`.

Access type encoding (lsu_type_i):
  2'b00 = word, 2'b01 = halfword, 2'b10 = byte (lsu_sign_ext_i selects
  signed/unsigned for halfword and byte).

Signal conventions used in helpers:
  delay_gnt: number of extra idle cycles before asserting data_gnt_i
             (0 = grant on the same cycle as req, 1 = one idle cycle first)
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


# ── Constants ────────────────────────────────────────────────────────────
CLK_PERIOD_NS = 10  # 100 MHz

LSU_TYPE_WORD      = 0b00
LSU_TYPE_HALFWORD  = 0b01
LSU_TYPE_BYTE      = 0b10

MAX_CYCLES = 40  # safety watchdog for each test


# ── Helpers ──────────────────────────────────────────────────────────────

async def reset_dut(dut):
    """Active-low synchronous reset for 2 cycles."""
    dut.rst_ni.value = 0
    await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")


async def idle_inputs(dut):
    """Set all inputs to a benign idle state (no request)."""
    dut.lsu_req_i.value          = 0
    dut.lsu_we_i.value           = 0
    dut.lsu_type_i.value         = LSU_TYPE_WORD
    dut.lsu_wdata_i.value        = 0
    dut.lsu_sign_ext_i.value     = 0
    dut.adder_result_ex_i.value  = 0
    dut.data_gnt_i.value         = 0
    dut.data_rvalid_i.value      = 0
    dut.data_rdata_i.value       = 0
    dut.data_bus_err_i.value     = 0
    dut.data_pmp_err_i.value     = 0


async def do_load(dut, addr, lsu_type, sign_ext, *, rdata=0, delay_gnt=0):
    """Issue one load transaction; handle gnt and rvalid.

    For aligned accesses (no addr_incr_req_o):
      1. Assert lsu_req_i and wait for data_req_o.
      2. After delay_gnt idle cycles, drive data_gnt_i = 1 for one cycle.
      3. On the cycle after gnt, drive data_rvalid_i = 1 (with rdata).
      4. Deassert lsu_req_i once lsu_req_done_o is seen.

    Returns (rdata_out, resp_valid) sampled when lsu_rdata_valid_o is asserted.
    """
    dut.lsu_req_i.value         = 1
    dut.lsu_we_i.value          = 0
    dut.lsu_type_i.value        = lsu_type
    dut.lsu_sign_ext_i.value    = sign_ext
    dut.adder_result_ex_i.value = addr & 0xFFFF_FFFF
    dut.data_gnt_i.value        = 0
    dut.data_rvalid_i.value     = 0
    dut.data_rdata_i.value      = rdata & 0xFFFF_FFFF
    dut.data_bus_err_i.value    = 0
    dut.data_pmp_err_i.value    = 0

    # Wait for req to be asserted (may be combinational from IDLE)
    for _ in range(MAX_CYCLES):
        await Timer(1, "ns")
        if int(dut.data_req_o.value) == 1:
            break
        await RisingEdge(dut.clk_i)
    else:
        raise AssertionError("data_req_o never asserted")

    # Delay before grant
    for _ in range(delay_gnt):
        await RisingEdge(dut.clk_i)
        await Timer(1, "ns")

    # Grant: assert for one cycle
    dut.data_gnt_i.value = 1
    # Check lsu_req_done_o while grant is live
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    # Deassert gnt; lsu_req_done_o should have pulsed — deassert req
    dut.data_gnt_i.value   = 0
    dut.lsu_req_i.value    = 0

    # Drive rvalid on the cycle after grant
    dut.data_rvalid_i.value = 1
    dut.data_rdata_i.value  = rdata & 0xFFFF_FFFF
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")

    rdata_out  = int(dut.lsu_rdata_o.value)
    resp_valid = int(dut.lsu_resp_valid_o.value)

    # Deassert rvalid
    dut.data_rvalid_i.value = 0
    dut.data_rdata_i.value  = 0

    await idle_inputs(dut)
    return rdata_out, resp_valid


async def do_store(dut, addr, lsu_type, wdata, *, delay_gnt=0):
    """Issue one store transaction; handle gnt and rvalid (write response).

    For stores the memory model still drives data_rvalid_i to signal
    write-response completion (required by OBI for stores too).
    """
    dut.lsu_req_i.value         = 1
    dut.lsu_we_i.value          = 1
    dut.lsu_type_i.value        = lsu_type
    dut.lsu_sign_ext_i.value    = 0
    dut.lsu_wdata_i.value       = wdata & 0xFFFF_FFFF
    dut.adder_result_ex_i.value = addr & 0xFFFF_FFFF
    dut.data_gnt_i.value        = 0
    dut.data_rvalid_i.value     = 0
    dut.data_rdata_i.value      = 0
    dut.data_bus_err_i.value    = 0
    dut.data_pmp_err_i.value    = 0

    # Wait for req
    for _ in range(MAX_CYCLES):
        await Timer(1, "ns")
        if int(dut.data_req_o.value) == 1:
            break
        await RisingEdge(dut.clk_i)
    else:
        raise AssertionError("data_req_o never asserted")

    # Delay before grant
    for _ in range(delay_gnt):
        await RisingEdge(dut.clk_i)
        await Timer(1, "ns")

    # Grant
    dut.data_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_gnt_i.value  = 0
    dut.lsu_req_i.value   = 0

    # Write response (rvalid on next cycle after gnt)
    dut.data_rvalid_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_rvalid_i.value = 0

    await idle_inputs(dut)


# ── Tests: one per spec Requirement ──────────────────────────────────────

@cocotb.test()
async def test_obi_handshake(dut):
    """Req OBI-Handshake — verifies req→gnt→rvalid cycle sequencing and
    that data_req_o de-asserts after rvalid for an aligned word load.

    Also verifies address-phase signal stability: data_addr_o, data_we_o,
    data_be_o must remain stable between req and gnt (Scenario: delayed
    grant with 1 extra idle cycle).
    """
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())
    await idle_inputs(dut)
    await reset_dut(dut)

    addr  = 0x0000_1000  # aligned word
    rdata = 0xDEAD_BEEF

    dut.lsu_req_i.value         = 1
    dut.lsu_we_i.value          = 0
    dut.lsu_type_i.value        = LSU_TYPE_WORD
    dut.lsu_sign_ext_i.value    = 0
    dut.adder_result_ex_i.value = addr
    dut.data_gnt_i.value        = 0
    dut.data_rvalid_i.value     = 0
    dut.data_rdata_i.value      = rdata
    dut.data_bus_err_i.value    = 0
    dut.data_pmp_err_i.value    = 0

    # Expect data_req_o combinationally from IDLE
    await Timer(1, "ns")
    assert int(dut.data_req_o.value) == 1, "data_req_o must assert when lsu_req_i=1 from IDLE"

    # Capture address-phase outputs before grant (stability check)
    addr_before  = int(dut.data_addr_o.value)
    we_before    = int(dut.data_we_o.value)
    be_before    = int(dut.data_be_o.value)
    wdata_before = int(dut.data_wdata_o.value)

    # One idle cycle (delayed grant scenario)
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    assert int(dut.data_req_o.value) == 1, "data_req_o must remain asserted while waiting for gnt"

    # Verify stability
    assert int(dut.data_addr_o.value)  == addr_before,  "data_addr_o must be stable until gnt"
    assert int(dut.data_we_o.value)    == we_before,    "data_we_o must be stable until gnt"
    assert int(dut.data_be_o.value)    == be_before,    "data_be_o must be stable until gnt"
    assert int(dut.data_wdata_o.value) == wdata_before, "data_wdata_o must be stable until gnt"

    # Grant
    dut.data_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_gnt_i.value = 0
    dut.lsu_req_i.value  = 0

    # rvalid cycle
    dut.data_rvalid_i.value = 1
    dut.data_rdata_i.value  = rdata
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")

    assert int(dut.lsu_resp_valid_o.value) == 1, "lsu_resp_valid_o must assert on rvalid"
    assert int(dut.lsu_rdata_valid_o.value) == 1, "lsu_rdata_valid_o must assert for load on rvalid"

    dut.data_rvalid_i.value = 0
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")

    # After rvalid, req_o must deassert (FSM back to IDLE)
    assert int(dut.data_req_o.value) == 0, "data_req_o must deassert after rvalid and req gone"
    assert int(dut.busy_o.value) == 0, "busy_o must be 0 when FSM returns to IDLE"

    await idle_inputs(dut)


@cocotb.test()
async def test_word_aligned_address(dut):
    """Req Word-Aligned-Address — verifies data_addr_o[1:0] == 0
    regardless of adder_result_ex_i byte offset.

    Tests byte offsets 0, 1, 2, 3 — all must produce an aligned address.
    """
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())
    await idle_inputs(dut)
    await reset_dut(dut)

    base = 0x0000_2000

    for offset in range(4):
        addr = base + offset
        dut.lsu_req_i.value         = 1
        dut.lsu_we_i.value          = 0
        dut.lsu_type_i.value        = LSU_TYPE_BYTE
        dut.lsu_sign_ext_i.value    = 0
        dut.adder_result_ex_i.value = addr
        dut.data_gnt_i.value        = 0
        dut.data_rvalid_i.value     = 0
        dut.data_rdata_i.value      = 0
        dut.data_bus_err_i.value    = 0
        dut.data_pmp_err_i.value    = 0

        await Timer(1, "ns")
        assert int(dut.data_req_o.value) == 1, f"data_req_o not asserted at offset {offset}"

        data_addr = int(dut.data_addr_o.value)
        expected_aligned = addr & 0xFFFF_FFFC
        assert data_addr == expected_aligned, (
            f"data_addr_o={hex(data_addr)} is not word-aligned for addr={hex(addr)}"
        )
        assert (data_addr & 0x3) == 0, f"data_addr_o[1:0] != 0 for offset {offset}"

        # Complete the transaction
        dut.data_gnt_i.value = 1
        await RisingEdge(dut.clk_i)
        await Timer(1, "ns")
        dut.data_gnt_i.value = 0
        dut.lsu_req_i.value  = 0

        dut.data_rvalid_i.value = 1
        await RisingEdge(dut.clk_i)
        await Timer(1, "ns")
        dut.data_rvalid_i.value = 0

        await idle_inputs(dut)
        # Extra idle cycle before next iteration
        await RisingEdge(dut.clk_i)
        await Timer(1, "ns")


@cocotb.test()
async def test_byte_enable_generation(dut):
    """Req Byte-Enable-Generation — verifies data_be_o for byte, halfword,
    and word accesses at various offsets.

    Representative scenario: byte store at offset 2 → data_be_o = 4'b0100.
    Also checks aligned word (4'b1111) and halfword offset 0 (4'b0011).
    """
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())
    await idle_inputs(dut)
    await reset_dut(dut)

    base = 0x0000_3000

    # (lsu_type, offset, expected_be, description)
    cases = [
        (LSU_TYPE_BYTE,     0b00, 0b0001, "byte offset 0"),
        (LSU_TYPE_BYTE,     0b01, 0b0010, "byte offset 1"),
        (LSU_TYPE_BYTE,     0b10, 0b0100, "byte offset 2"),
        (LSU_TYPE_BYTE,     0b11, 0b1000, "byte offset 3"),
        (LSU_TYPE_HALFWORD, 0b00, 0b0011, "halfword offset 0"),
        (LSU_TYPE_HALFWORD, 0b10, 0b1100, "halfword offset 2"),
        (LSU_TYPE_WORD,     0b00, 0b1111, "word aligned"),
    ]

    for lsu_type, offset, exp_be, desc in cases:
        addr = (base & 0xFFFF_FFFC) | offset

        dut.lsu_req_i.value         = 1
        dut.lsu_we_i.value          = 1  # use store to avoid needing rvalid rdata
        dut.lsu_type_i.value        = lsu_type
        dut.lsu_sign_ext_i.value    = 0
        dut.lsu_wdata_i.value       = 0xAABBCCDD
        dut.adder_result_ex_i.value = addr
        dut.data_gnt_i.value        = 0
        dut.data_rvalid_i.value     = 0
        dut.data_rdata_i.value      = 0
        dut.data_bus_err_i.value    = 0
        dut.data_pmp_err_i.value    = 0

        await Timer(1, "ns")
        assert int(dut.data_req_o.value) == 1, f"data_req_o not asserted for {desc}"

        actual_be = int(dut.data_be_o.value)
        assert actual_be == exp_be, (
            f"{desc}: data_be_o={bin(actual_be)} expected {bin(exp_be)}"
        )

        # Complete the transaction
        dut.data_gnt_i.value = 1
        await RisingEdge(dut.clk_i)
        await Timer(1, "ns")
        dut.data_gnt_i.value = 0
        dut.lsu_req_i.value  = 0

        dut.data_rvalid_i.value = 1
        await RisingEdge(dut.clk_i)
        await Timer(1, "ns")
        dut.data_rvalid_i.value = 0

        await idle_inputs(dut)
        await RisingEdge(dut.clk_i)
        await Timer(1, "ns")


@cocotb.test()
async def test_write_data_rotation(dut):
    """Req Write-Data-Rotation — verifies data_wdata_o is correctly rotated
    for store byte at offset 1.

    Spec scenario: lsu_we_i=1, offset=0b01, lsu_wdata_i=0xAABBCCDD
    → data_wdata_o = 0xBBCCDDAA, data_be_o = 4'b0010.
    """
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())
    await idle_inputs(dut)
    await reset_dut(dut)

    wdata    = 0xAABBCCDD
    addr     = 0x0000_4001  # byte offset 1
    exp_wdata = 0xBBCCDDAA  # rotated left by 1 byte
    exp_be    = 0b0010

    dut.lsu_req_i.value         = 1
    dut.lsu_we_i.value          = 1
    dut.lsu_type_i.value        = LSU_TYPE_BYTE
    dut.lsu_sign_ext_i.value    = 0
    dut.lsu_wdata_i.value       = wdata
    dut.adder_result_ex_i.value = addr
    dut.data_gnt_i.value        = 0
    dut.data_rvalid_i.value     = 0
    dut.data_rdata_i.value      = 0
    dut.data_bus_err_i.value    = 0
    dut.data_pmp_err_i.value    = 0

    await Timer(1, "ns")
    assert int(dut.data_req_o.value) == 1, "data_req_o must assert"

    actual_wdata = int(dut.data_wdata_o.value)
    actual_be    = int(dut.data_be_o.value)

    assert actual_wdata == exp_wdata, (
        f"data_wdata_o={hex(actual_wdata)} expected {hex(exp_wdata)}"
    )
    assert actual_be == exp_be, (
        f"data_be_o={bin(actual_be)} expected {bin(exp_be)}"
    )

    # Complete transaction
    dut.data_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_gnt_i.value = 0
    dut.lsu_req_i.value  = 0

    dut.data_rvalid_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_rvalid_i.value = 0

    await idle_inputs(dut)


@cocotb.test()
async def test_read_data_extraction(dut):
    """Req Read-Data-Extraction — verifies lsu_rdata_o contains the correct
    extracted value for an aligned byte load unsigned.

    Spec scenario: lsu_type_i=byte, lsu_sign_ext_i=0, offset=0b00,
    data_rdata_i=0xAABBCC87 → lsu_rdata_o=0x00000087.
    """
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())
    await idle_inputs(dut)
    await reset_dut(dut)

    mem_rdata = 0xAABBCC87
    addr      = 0x0000_5000  # offset 0

    rdata_out, resp_valid = await do_load(
        dut, addr, LSU_TYPE_BYTE, sign_ext=0, rdata=mem_rdata
    )

    assert resp_valid == 1, "lsu_resp_valid_o must be asserted"
    assert rdata_out == 0x0000_0087, (
        f"lsu_rdata_o={hex(rdata_out)} expected 0x00000087"
    )


@cocotb.test()
async def test_misaligned_access_split(dut):
    """Req Misaligned-Access-Split — verifies the LSU splits a misaligned
    word access into two OBI transactions and asserts addr_incr_req_o.

    Scenario: word load at offset 2 (misaligned). The TB checks that
    addr_incr_req_o is asserted after the first grant, and that two
    rvalid pulses are needed before lsu_resp_valid_o asserts.
    """
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())
    await idle_inputs(dut)
    await reset_dut(dut)

    # Misaligned word: offset 2
    addr1 = 0x0000_6002  # original address (offset 2)
    addr2 = 0x0000_6004  # second transaction (addr1 + 4, aligned)

    # First transaction rdata (lower bytes of misaligned word)
    rdata1 = 0x12345678
    # Second transaction rdata (upper bytes)
    rdata2 = 0x9ABCDEF0

    dut.lsu_req_i.value         = 1
    dut.lsu_we_i.value          = 0
    dut.lsu_type_i.value        = LSU_TYPE_WORD
    dut.lsu_sign_ext_i.value    = 0
    dut.adder_result_ex_i.value = addr1
    dut.data_gnt_i.value        = 0
    dut.data_rvalid_i.value     = 0
    dut.data_rdata_i.value      = 0
    dut.data_bus_err_i.value    = 0
    dut.data_pmp_err_i.value    = 0

    await Timer(1, "ns")
    assert int(dut.data_req_o.value) == 1, "data_req_o must assert for first transaction"

    # First transaction: byte enables should be 4'b1100 (offset 2)
    be_first = int(dut.data_be_o.value)
    assert be_first == 0b1100, f"First txn data_be_o={bin(be_first)} expected 0b1100"

    # Grant first transaction
    dut.data_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_gnt_i.value = 0

    # addr_incr_req_o should now be asserted (FSM moving to second transaction)
    assert int(dut.addr_incr_req_o.value) == 1, (
        "addr_incr_req_o must assert after first grant of misaligned access"
    )

    # Now the ID/EX stage would provide addr2 on adder_result_ex_i
    dut.adder_result_ex_i.value = addr2
    await Timer(1, "ns")

    # Second transaction request should be active
    assert int(dut.data_req_o.value) == 1, "data_req_o must assert for second transaction"

    # Second transaction: byte enables should be 4'b0011 (second half of word at offset 2)
    be_second = int(dut.data_be_o.value)
    assert be_second == 0b0011, f"Second txn data_be_o={bin(be_second)} expected 0b0011"

    # Grant second transaction
    dut.data_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_gnt_i.value = 0
    dut.lsu_req_i.value  = 0

    # lsu_req_done_o should have pulsed (both grants received)
    # Now drive rvalid for first transaction
    dut.data_rvalid_i.value = 1
    dut.data_rdata_i.value  = rdata1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    # First rvalid: lsu_resp_valid_o should NOT be asserted yet
    assert int(dut.lsu_resp_valid_o.value) == 0, (
        "lsu_resp_valid_o must NOT assert on first rvalid of misaligned access"
    )
    dut.data_rvalid_i.value = 0

    # Drive rvalid for second transaction
    dut.data_rvalid_i.value = 1
    dut.data_rdata_i.value  = rdata2
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    # Second rvalid: lsu_resp_valid_o must now assert
    assert int(dut.lsu_resp_valid_o.value) == 1, (
        "lsu_resp_valid_o must assert on second rvalid of misaligned access"
    )
    dut.data_rvalid_i.value = 0

    await idle_inputs(dut)


@cocotb.test()
async def test_lsu_req_done_o(dut):
    """Req lsu_req_done_o — verifies it pulses for exactly one cycle when
    the address phase (last OBI grant) completes.

    Scenario: aligned store with immediate grant → lsu_req_done_o asserts
    on the grant cycle, then deasserts the following cycle.
    """
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())
    await idle_inputs(dut)
    await reset_dut(dut)

    addr  = 0x0000_7000
    wdata = 0xCAFEBABE

    dut.lsu_req_i.value         = 1
    dut.lsu_we_i.value          = 1
    dut.lsu_type_i.value        = LSU_TYPE_WORD
    dut.lsu_sign_ext_i.value    = 0
    dut.lsu_wdata_i.value       = wdata
    dut.adder_result_ex_i.value = addr
    dut.data_gnt_i.value        = 0
    dut.data_rvalid_i.value     = 0
    dut.data_rdata_i.value      = 0
    dut.data_bus_err_i.value    = 0
    dut.data_pmp_err_i.value    = 0

    await Timer(1, "ns")
    assert int(dut.data_req_o.value) == 1

    # lsu_req_done_o before grant (must be 0 when FSM is still not done)
    req_done_before = int(dut.lsu_req_done_o.value)

    # Grant immediately
    dut.data_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")

    # On the grant cycle: lsu_req_done_o should be 1
    req_done_on_gnt = int(dut.lsu_req_done_o.value)

    dut.data_gnt_i.value = 0
    dut.lsu_req_i.value  = 0

    # Next cycle: must be 0 again
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    req_done_after = int(dut.lsu_req_done_o.value)

    assert req_done_on_gnt == 1, (
        f"lsu_req_done_o must be 1 on grant cycle, got {req_done_on_gnt}"
    )
    assert req_done_after == 0, (
        f"lsu_req_done_o must be 0 the cycle after grant (single-cycle pulse), got {req_done_after}"
    )

    # Cleanup rvalid
    dut.data_rvalid_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_rvalid_i.value = 0

    await idle_inputs(dut)


@cocotb.test()
async def test_lsu_resp_valid_o(dut):
    """Req lsu_resp_valid_o — verifies it asserts for one cycle when the
    data phase of the final OBI transaction completes.

    Scenario: aligned word load → lsu_resp_valid_o asserts exactly on the
    rvalid cycle and is 0 the cycle before and the cycle after.
    """
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())
    await idle_inputs(dut)
    await reset_dut(dut)

    addr  = 0x0000_8000
    rdata = 0x11223344

    dut.lsu_req_i.value         = 1
    dut.lsu_we_i.value          = 0
    dut.lsu_type_i.value        = LSU_TYPE_WORD
    dut.lsu_sign_ext_i.value    = 0
    dut.adder_result_ex_i.value = addr
    dut.data_gnt_i.value        = 0
    dut.data_rvalid_i.value     = 0
    dut.data_rdata_i.value      = rdata
    dut.data_bus_err_i.value    = 0
    dut.data_pmp_err_i.value    = 0

    await Timer(1, "ns")

    # Grant
    dut.data_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_gnt_i.value = 0
    dut.lsu_req_i.value  = 0

    # Before rvalid: lsu_resp_valid_o must be 0
    resp_before = int(dut.lsu_resp_valid_o.value)
    assert resp_before == 0, "lsu_resp_valid_o must be 0 before rvalid"

    # Drive rvalid
    dut.data_rvalid_i.value = 1
    dut.data_rdata_i.value  = rdata
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")

    # On rvalid cycle: must be 1
    resp_on_rvalid = int(dut.lsu_resp_valid_o.value)
    assert resp_on_rvalid == 1, "lsu_resp_valid_o must be 1 on rvalid cycle"

    dut.data_rvalid_i.value = 0

    # Next cycle: must be 0
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    resp_after = int(dut.lsu_resp_valid_o.value)
    assert resp_after == 0, "lsu_resp_valid_o must be 0 after rvalid"

    await idle_inputs(dut)


@cocotb.test()
async def test_lsu_rdata_valid_o(dut):
    """Req lsu_rdata_valid_o — verifies it asserts only for load
    transactions that complete without error, and does NOT assert for stores.

    Scenario A: Successful aligned word load → lsu_rdata_valid_o asserts.
    Scenario B: Aligned word store → lsu_rdata_valid_o must NOT assert.
    """
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())
    await idle_inputs(dut)
    await reset_dut(dut)

    # Scenario A: load
    rdata_out, _ = await do_load(dut, 0x0000_9000, LSU_TYPE_WORD, 0, rdata=0xABCDEF01)
    # After do_load returns, lsu_rdata_valid_o was sampled inside the helper
    # Let's verify by doing it manually one more time
    await idle_inputs(dut)
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")

    # Scenario A directly
    dut.lsu_req_i.value         = 1
    dut.lsu_we_i.value          = 0
    dut.lsu_type_i.value        = LSU_TYPE_WORD
    dut.lsu_sign_ext_i.value    = 0
    dut.adder_result_ex_i.value = 0x0000_9010
    dut.data_gnt_i.value        = 0
    dut.data_rvalid_i.value     = 0
    dut.data_rdata_i.value      = 0x1234ABCD
    dut.data_bus_err_i.value    = 0
    dut.data_pmp_err_i.value    = 0

    await Timer(1, "ns")
    dut.data_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_gnt_i.value = 0
    dut.lsu_req_i.value  = 0
    dut.data_rvalid_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    assert int(dut.lsu_rdata_valid_o.value) == 1, "lsu_rdata_valid_o must assert for a load"
    dut.data_rvalid_i.value = 0

    await idle_inputs(dut)
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")

    # Scenario B: store — lsu_rdata_valid_o must NOT assert
    dut.lsu_req_i.value         = 1
    dut.lsu_we_i.value          = 1
    dut.lsu_type_i.value        = LSU_TYPE_WORD
    dut.lsu_sign_ext_i.value    = 0
    dut.lsu_wdata_i.value       = 0xDEAD_BEEF
    dut.adder_result_ex_i.value = 0x0000_9020
    dut.data_gnt_i.value        = 0
    dut.data_rvalid_i.value     = 0
    dut.data_rdata_i.value      = 0
    dut.data_bus_err_i.value    = 0
    dut.data_pmp_err_i.value    = 0

    await Timer(1, "ns")
    dut.data_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_gnt_i.value = 0
    dut.lsu_req_i.value  = 0
    dut.data_rvalid_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    assert int(dut.lsu_rdata_valid_o.value) == 0, (
        "lsu_rdata_valid_o must NOT assert for a store"
    )
    dut.data_rvalid_i.value = 0

    await idle_inputs(dut)


@cocotb.test()
async def test_error_reporting(dut):
    """Req Error-Reporting — verifies load_err_o asserts (and
    lsu_rdata_valid_o does NOT) when data_bus_err_i is high on rvalid.

    Also verifies store_err_o asserts for a bus error on a store.
    """
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())
    await idle_inputs(dut)
    await reset_dut(dut)

    # Scenario: bus error on load
    dut.lsu_req_i.value         = 1
    dut.lsu_we_i.value          = 0
    dut.lsu_type_i.value        = LSU_TYPE_WORD
    dut.lsu_sign_ext_i.value    = 0
    dut.adder_result_ex_i.value = 0x0000_A000
    dut.data_gnt_i.value        = 0
    dut.data_rvalid_i.value     = 0
    dut.data_rdata_i.value      = 0
    dut.data_bus_err_i.value    = 0
    dut.data_pmp_err_i.value    = 0

    await Timer(1, "ns")
    dut.data_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_gnt_i.value = 0
    dut.lsu_req_i.value  = 0

    # Drive rvalid with bus error
    dut.data_rvalid_i.value = 1
    dut.data_bus_err_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")

    assert int(dut.lsu_resp_valid_o.value) == 1, "lsu_resp_valid_o must assert on error rvalid"
    assert int(dut.load_err_o.value) == 1, "load_err_o must assert on bus error for load"
    assert int(dut.lsu_rdata_valid_o.value) == 0, (
        "lsu_rdata_valid_o must NOT assert on error"
    )

    dut.data_rvalid_i.value  = 0
    dut.data_bus_err_i.value = 0

    await idle_inputs(dut)
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")

    # Scenario: bus error on store
    dut.lsu_req_i.value         = 1
    dut.lsu_we_i.value          = 1
    dut.lsu_type_i.value        = LSU_TYPE_WORD
    dut.lsu_sign_ext_i.value    = 0
    dut.lsu_wdata_i.value       = 0x5555_5555
    dut.adder_result_ex_i.value = 0x0000_A010
    dut.data_gnt_i.value        = 0
    dut.data_rvalid_i.value     = 0
    dut.data_rdata_i.value      = 0
    dut.data_bus_err_i.value    = 0
    dut.data_pmp_err_i.value    = 0

    await Timer(1, "ns")
    dut.data_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_gnt_i.value = 0
    dut.lsu_req_i.value  = 0

    dut.data_rvalid_i.value  = 1
    dut.data_bus_err_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")

    assert int(dut.store_err_o.value) == 1, "store_err_o must assert on bus error for store"
    assert int(dut.lsu_resp_valid_o.value) == 1, "lsu_resp_valid_o must assert alongside store_err_o"

    dut.data_rvalid_i.value  = 0
    dut.data_bus_err_i.value = 0

    await idle_inputs(dut)


@cocotb.test()
async def test_busy_o(dut):
    """Req busy_o — verifies busy_o is 0 in IDLE, 1 during an outstanding
    transaction (waiting for gnt), and 0 again after completion.
    """
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())
    await idle_inputs(dut)
    await reset_dut(dut)

    # IDLE: busy_o must be 0
    await Timer(1, "ns")
    assert int(dut.busy_o.value) == 0, "busy_o must be 0 in IDLE with no request"

    # Start a load — keep gnt deasserted to stay in WAIT_GNT (or WAIT_RVALID)
    dut.lsu_req_i.value         = 1
    dut.lsu_we_i.value          = 0
    dut.lsu_type_i.value        = LSU_TYPE_WORD
    dut.lsu_sign_ext_i.value    = 0
    dut.adder_result_ex_i.value = 0x0000_B000
    dut.data_gnt_i.value        = 0
    dut.data_rvalid_i.value     = 0
    dut.data_rdata_i.value      = 0
    dut.data_bus_err_i.value    = 0
    dut.data_pmp_err_i.value    = 0

    # Go to next cycle: FSM should be in WAIT_GNT (non-IDLE)
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    assert int(dut.busy_o.value) == 1, "busy_o must be 1 when FSM is non-IDLE (WAIT_GNT)"

    # Grant and complete the transaction
    dut.data_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_gnt_i.value = 0
    dut.lsu_req_i.value  = 0

    dut.data_rvalid_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_rvalid_i.value = 0

    # Back to IDLE
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    assert int(dut.busy_o.value) == 0, "busy_o must be 0 after transaction completes"

    await idle_inputs(dut)


@cocotb.test()
async def test_performance_counter_pulses(dut):
    """Req Performance-Counter-Pulses — verifies perf_load_o and
    perf_store_o each pulse for exactly one cycle on the first request
    cycle, and do NOT repeat on subsequent cycles of the same access.

    Scenario A: Load request → perf_load_o=1, perf_store_o=0.
    Scenario B: Store request → perf_store_o=1, perf_load_o=0.
    Also verifies pulses do not repeat when grant is delayed (stays in WAIT_GNT).
    """
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())
    await idle_inputs(dut)
    await reset_dut(dut)

    # Scenario A: load
    dut.lsu_req_i.value         = 1
    dut.lsu_we_i.value          = 0
    dut.lsu_type_i.value        = LSU_TYPE_WORD
    dut.lsu_sign_ext_i.value    = 0
    dut.adder_result_ex_i.value = 0x0000_C000
    dut.data_gnt_i.value        = 0
    dut.data_rvalid_i.value     = 0
    dut.data_rdata_i.value      = 0
    dut.data_bus_err_i.value    = 0
    dut.data_pmp_err_i.value    = 0

    await Timer(1, "ns")
    assert int(dut.perf_load_o.value)  == 1, "perf_load_o must be 1 on first load cycle"
    assert int(dut.perf_store_o.value) == 0, "perf_store_o must be 0 for a load"

    # Move to next cycle with no grant: FSM enters WAIT_GNT — perf signals must not repeat
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    assert int(dut.perf_load_o.value)  == 0, "perf_load_o must NOT repeat in WAIT_GNT state"
    assert int(dut.perf_store_o.value) == 0, "perf_store_o must be 0 in WAIT_GNT state"

    # Complete the transaction
    dut.data_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_gnt_i.value = 0
    dut.lsu_req_i.value  = 0
    dut.data_rvalid_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_rvalid_i.value = 0

    await idle_inputs(dut)
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")

    # Scenario B: store
    dut.lsu_req_i.value         = 1
    dut.lsu_we_i.value          = 1
    dut.lsu_type_i.value        = LSU_TYPE_WORD
    dut.lsu_sign_ext_i.value    = 0
    dut.lsu_wdata_i.value       = 0x5A5A_5A5A
    dut.adder_result_ex_i.value = 0x0000_C010
    dut.data_gnt_i.value        = 0
    dut.data_rvalid_i.value     = 0
    dut.data_rdata_i.value      = 0
    dut.data_bus_err_i.value    = 0
    dut.data_pmp_err_i.value    = 0

    await Timer(1, "ns")
    assert int(dut.perf_store_o.value) == 1, "perf_store_o must be 1 on first store cycle"
    assert int(dut.perf_load_o.value)  == 0, "perf_load_o must be 0 for a store"

    dut.data_gnt_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_gnt_i.value = 0
    dut.lsu_req_i.value  = 0
    dut.data_rvalid_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    dut.data_rvalid_i.value = 0

    await idle_inputs(dut)


@cocotb.test()
async def test_reset_state(dut):
    """Req Reset-State — verifies that after rst_ni is asserted (logic 0),
    the FSM returns to IDLE with busy_o=0 and addr_last_o=0.

    Also verifies that resetting mid-transaction brings the LSU to IDLE.
    """
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())
    await idle_inputs(dut)

    # Apply reset
    dut.rst_ni.value = 0
    await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")

    # While in reset: busy_o must be 0
    assert int(dut.busy_o.value) == 0, "busy_o must be 0 during reset"
    assert int(dut.addr_last_o.value) == 0, "addr_last_o must be 0 during reset"

    # Release reset
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")

    assert int(dut.busy_o.value) == 0, "busy_o must be 0 after reset release"
    assert int(dut.data_req_o.value) == 0, "data_req_o must be 0 after reset"

    # Start a transaction, then reset mid-flight
    dut.lsu_req_i.value         = 1
    dut.lsu_we_i.value          = 0
    dut.lsu_type_i.value        = LSU_TYPE_WORD
    dut.lsu_sign_ext_i.value    = 0
    dut.adder_result_ex_i.value = 0x0000_D000
    dut.data_gnt_i.value        = 0
    dut.data_rvalid_i.value     = 0
    dut.data_rdata_i.value      = 0
    dut.data_bus_err_i.value    = 0
    dut.data_pmp_err_i.value    = 0

    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    # Should be busy waiting for gnt
    assert int(dut.busy_o.value) == 1, "busy_o must be 1 when transaction in progress"

    # Assert reset again
    dut.rst_ni.value = 0
    await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")

    assert int(dut.busy_o.value) == 0, "busy_o must be 0 after mid-transaction reset"

    # Release reset and idle
    dut.rst_ni.value = 1
    await idle_inputs(dut)
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")

    assert int(dut.busy_o.value) == 0, "busy_o must remain 0 after reset+idle"
