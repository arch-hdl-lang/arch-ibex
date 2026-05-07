"""Full regression cocotb scenarios for `ibex_if_stage`.

Extends the basic suite with one `@cocotb.test` per Scenario in the
spec plus boundary / edge cases.

Spec mapping:
  - Requirement 1 (Exception PC mux): vectorised IRQ, NMI override,
    sync-exception, debug entry, debug exception
  - Requirement 2 (Fetch addr mux): boot, jump, ERET, BP collapse,
    DRET (additional)
  - Requirement 3 (Branch req synthesis): regular pc_set_i, nt-branch
    misprediction
  - Requirement 4 (Prefetch buffer): clean fetch, valid squashed on
    misprediction
  - Requirement 5 (Compressed decoder): RV32 passthrough, compressed
    instruction expansion
  - Requirement 6 (Instr error): bus error only, PMP plus2,
    PMP-first-half override
  - Requirement 7 (Pipe-reg WE): clean write, suppressed by pc_set_i,
    suppressed by ~id_in_ready_i
  - Requirement 8 (state regs): held across stall, explicit clear, reset
  - Requirement 9 (mtvec init): boot pulse, any other PC mux
  - Requirement 10 (tieoffs): constant outputs

Boundary / edge cases:
  - csr_mtvec all-ones / lower-8 ignored
  - boot_addr lower-8 ignored
  - csr_mepc / csr_depc mux paths
  - exc_cause irq_int=0/1 boundary at lower_cause=0 and lower_cause=31
  - PC_DRET path
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

CLK_PERIOD_NS = 10

# PcSel encodings
PC_BOOT = 0
PC_JUMP = 1
PC_EXC  = 2
PC_ERET = 3
PC_DRET = 4
PC_BP   = 5

# ExcPcSel encodings
EXC_PC_EXC     = 0
EXC_PC_IRQ     = 1
EXC_PC_DBD     = 2
EXC_PC_DBG_EXC = 3

# InstrExp encodings
INSTR_NOT_EXPANDED  = 0
INSTR_EXPANDED      = 1
INSTR_EXPANDED_LAST = 2

DM_HALT_ADDR      = 0x1A11_0800
DM_EXCEPTION_ADDR = 0x1A11_0808

MASK32 = 0xFFFF_FFFF

# Icache geometry (D1's `ICache=1` flip swapped IfStage to wrap
# `ibex_icache`):
#   - IC_LINE_BEATS = 2: every miss fills a 64-bit line = 2 × 32-bit
#     bus beats. The helper that drives a single fetch must serve BOTH
#     beats or the FB stays half-filled and never delivers `valid_o`.
#   - IC_NUM_LINES = 128: cold-boot inval walk takes ~128 cycles before
#     any lookup fires. Tests that observe `instr_addr_o` or expect a
#     fetch must first wait for the walk to drain.
#   - The icache's bus master line-aligns the request address to the
#     cache-line boundary: `instr_addr_o = (fb.addr & ~0x7)` for the
#     first beat.
IC_LINE_BEATS_PER_FILL = 2
IC_INVAL_DRAIN_CYCLES  = 140  # cover IC_NUM_LINES = 128 + small slack
LINE_ALIGN_MASK        = 0xFFFF_FFF8  # 8-byte cache-line alignment


def _line_aligned(addr: int) -> int:
    return addr & LINE_ALIGN_MASK & MASK32


def _pack_exc_cause(*, irq_int: int = 0, irq_ext: int = 0,
                    lower_cause: int = 0) -> int:
    return ((irq_int & 1) << 6) | ((irq_ext & 1) << 5) | (lower_cause & 0x1F)


# ── Testbench helpers ───────────────────────────────────────────────────

async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())


async def _settle(dut):
    await Timer(1, "ns")


def _idle_inputs(dut):
    dut.req_i.value = 0
    dut.boot_addr_i.value = 0x0010_0000
    dut.instr_valid_clear_i.value = 0
    dut.id_in_ready_i.value = 0
    dut.pc_set_i.value = 0
    dut.pc_mux_i.value = PC_BOOT
    dut.nt_branch_mispredict_i.value = 0
    dut.nt_branch_addr_i.value = 0
    dut.exc_pc_mux_i.value = EXC_PC_EXC
    dut.exc_cause.value = _pack_exc_cause()
    dut.branch_target_ex_i.value = 0
    dut.csr_mepc_i.value = 0
    dut.csr_depc_i.value = 0
    dut.csr_mtvec_i.value = 0
    dut.pmp_err_if_i.value = 0
    dut.pmp_err_if_plus2_i.value = 0
    dut.instr_gnt_i.value = 0
    dut.instr_rvalid_i.value = 0
    dut.instr_rdata_i.value = 0
    dut.instr_bus_err_i.value = 0
    # NOTE: `ic_scr_key_valid_i` tied to 1 to match SoC binding
    # (`ibex_top.sv:581`, `ICacheScramble=0`); otherwise the icache
    # parks in `AWAIT_SCRAMBLE_KEY` (R-INV-3).
    dut.icache_enable_i.value = 0
    dut.icache_inval_i.value = 0
    dut.ic_scr_key_valid_i.value = 1
    dut.dummy_instr_en_i.value = 0
    dut.dummy_instr_mask_i.value = 0
    dut.dummy_instr_seed_en_i.value = 0
    dut.dummy_instr_seed_i.value = 0
    try:
        for i in range(len(dut.ic_tag_rdata_i)):
            dut.ic_tag_rdata_i[i].value = 0
    except (TypeError, AttributeError):
        pass
    try:
        for i in range(len(dut.ic_data_rdata_i)):
            dut.ic_data_rdata_i[i].value = 0
    except (TypeError, AttributeError):
        pass


async def _reset(dut, *, wait_idle: bool = True):
    """Apply async-low reset for two clock periods, then release.

    When `wait_idle` is true (default) additionally advance past the
    icache cold-boot inval walk (`IC_NUM_LINES = 128` cycles + slack)
    so subsequent test logic starts from an idle/ready icache. Tests
    that probe purely combinational outputs immediately after reset
    (e.g. tieoff readbacks, csr_mtvec_init pulse, async-reset state
    flush) can pass `wait_idle=False`.
    """
    _idle_inputs(dut)
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    if wait_idle:
        for _ in range(IC_INVAL_DRAIN_CYCLES):
            await RisingEdge(dut.clk_i)
            await _settle(dut)


async def _branch_to(dut, *, pc_mux: int, **mux_inputs) -> int:
    """Drive a single-cycle pc_set_i pulse with the given pc_mux value
    and the various mux-input signals named via kwargs (e.g.
    branch_target_ex_i=, csr_mepc_i=, csr_depc_i=, exc_pc_mux_i=,
    csr_mtvec_i=, exc_cause=, boot_addr_i=). Returns the resulting
    instr_addr_o once the icache's bus master starts driving a request.

    Under D1's `ICache=1` flip the visible address is the icache's
    bus master output, which line-aligns the request to the 8-byte
    cache-line boundary (`addr & ~0x7`). Caller is responsible for
    comparing against the correct line-aligned expected value.
    """
    for k, v in mux_inputs.items():
        getattr(dut, k).value = v & MASK32 if isinstance(v, int) else v
    dut.pc_mux_i.value = pc_mux
    dut.pc_set_i.value = 1
    dut.req_i.value = 1
    dut.id_in_ready_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.pc_set_i.value = 0
    await _settle(dut)
    # Wait for the icache to start driving the bus request for the
    # new branch; instr_addr_o then carries the line-base addr.
    for _ in range(16):
        if int(dut.instr_req_o.value) == 1:
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    return int(dut.instr_addr_o.value) & MASK32


async def _land_one_instruction(dut, *, branch_addr: int, rdata: int,
                                bus_err: int = 0,
                                pmp_err_if: int = 0,
                                pmp_err_if_plus2: int = 0,
                                max_cycles: int = 32) -> bool:
    """Drive a branch + bus handshake to land one instruction in the
    IF→ID pipe register.

    Under D1's `ICache=1` flip, the icache fills a 64-bit line per
    miss (`IC_LINE_BEATS = 2` bus beats), so this helper serves BOTH
    beats with the same `rdata` (and the same `bus_err`). Whichever
    halfword the icache presents, the resulting decoded instruction
    is `rdata`.
    """
    dut.pmp_err_if_i.value = pmp_err_if
    dut.pmp_err_if_plus2_i.value = pmp_err_if_plus2
    dut.pc_mux_i.value = PC_JUMP
    dut.branch_target_ex_i.value = branch_addr & MASK32
    dut.pc_set_i.value = 1
    dut.req_i.value = 1
    dut.id_in_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.pc_set_i.value = 0
    await _settle(dut)

    for beat in range(IC_LINE_BEATS_PER_FILL):
        # Wait for instr_req_o for THIS beat. After a bus-error first
        # beat the icache may abort the fill and stop driving req_o,
        # so don't insist on a second beat.
        seen_req = False
        for _ in range(max_cycles):
            if int(dut.instr_req_o.value) == 1:
                seen_req = True
                break
            await RisingEdge(dut.clk_i)
            await _settle(dut)
        if not seen_req:
            if beat > 0 and bus_err:
                break  # error path: second beat suppressed by the icache
            return False
        dut.instr_gnt_i.value = 1
        await RisingEdge(dut.clk_i)
        dut.instr_gnt_i.value = 0
        await _settle(dut)
        dut.instr_rvalid_i.value = 1
        dut.instr_rdata_i.value = rdata & MASK32
        dut.instr_bus_err_i.value = bus_err & 1
        await RisingEdge(dut.clk_i)
        dut.instr_rvalid_i.value = 0
        dut.instr_rdata_i.value = 0
        dut.instr_bus_err_i.value = 0
        await _settle(dut)

    for _ in range(16):
        if int(dut.instr_valid_id_o.value) == 1:
            dut.id_in_ready_i.value = 0
            await _settle(dut)
            return True
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    return int(dut.instr_valid_id_o.value) == 1


# ── Requirement 1 — Exception PC mux scenarios ─────────────────────────

@cocotb.test()
async def req1_exc_pc_irq_lower_cause_11(dut):
    """Spec Req 1 — Scenario "vectorised external IRQ":
    EXC_PC_IRQ + irq_int=0 + lower_cause=11 →
    {csr_mtvec[31:8], 1'b0, 5'd11, 2'b00} = 0x1000_202C.
    """
    await _start_clock(dut)
    await _reset(dut)
    addr = await _branch_to(
        dut, pc_mux=PC_EXC,
        exc_pc_mux_i=EXC_PC_IRQ,
        csr_mtvec_i=0x1000_2000,
        exc_cause=_pack_exc_cause(irq_int=0, irq_ext=1, lower_cause=11),
    )
    # icache bus master line-aligns to 8-byte boundary.
    assert addr == _line_aligned(0x1000_202C), f"got {addr:#010x}"


@cocotb.test()
async def req1_exc_pc_irq_nmi_override(dut):
    """Spec Req 1 — Scenario "NMI override": when irq_int=1 the irq_vec
    selector is forced to 5'd31 regardless of lower_cause.
    Expected fetch addr = {csr_mtvec[31:8], 1'b0, 5'd31, 2'b00} = 0x1000_207C.
    """
    await _start_clock(dut)
    await _reset(dut)
    addr = await _branch_to(
        dut, pc_mux=PC_EXC,
        exc_pc_mux_i=EXC_PC_IRQ,
        csr_mtvec_i=0x1000_2000,
        exc_cause=_pack_exc_cause(irq_int=1, irq_ext=0, lower_cause=3),
    )
    assert addr == _line_aligned(0x1000_207C), f"got {addr:#010x}"


@cocotb.test()
async def req1_exc_pc_sync_exception_entry(dut):
    """Spec Req 1 — Scenario "synchronous exception entry":
    EXC_PC_EXC → {csr_mtvec[31:8], 8'h00}. csr_mtvec[7:0] is forced to 0.
    """
    await _start_clock(dut)
    await _reset(dut)
    addr = await _branch_to(
        dut, pc_mux=PC_EXC,
        exc_pc_mux_i=EXC_PC_EXC,
        csr_mtvec_i=0x1000_20FF,  # lower 8 bits non-zero, must be forced 0
    )
    assert addr == _line_aligned(0x1000_2000), f"got {addr:#010x}"


@cocotb.test()
async def req1_exc_pc_debug_entry(dut):
    """Spec Req 1 — Scenario "debug entry": EXC_PC_DBD → DM_HALT_ADDR."""
    await _start_clock(dut)
    await _reset(dut)
    addr = await _branch_to(
        dut, pc_mux=PC_EXC,
        exc_pc_mux_i=EXC_PC_DBD,
        csr_mtvec_i=0xDEAD_BEEF,  # ignored on this path
    )
    assert addr == _line_aligned(DM_HALT_ADDR), f"got {addr:#010x}"


@cocotb.test()
async def req1_exc_pc_debug_exception(dut):
    """Spec Req 1 — Scenario "debug exception":
    EXC_PC_DBG_EXC → DM_EXCEPTION_ADDR.
    """
    await _start_clock(dut)
    await _reset(dut)
    addr = await _branch_to(
        dut, pc_mux=PC_EXC,
        exc_pc_mux_i=EXC_PC_DBG_EXC,
        csr_mtvec_i=0xDEAD_BEEF,
    )
    assert addr == _line_aligned(DM_EXCEPTION_ADDR), f"got {addr:#010x}"


@cocotb.test()
async def req1_exc_pc_irq_lower_cause_zero(dut):
    """Edge: EXC_PC_IRQ with lower_cause=0 → vector at csr_mtvec[31:8]||00."""
    await _start_clock(dut)
    await _reset(dut)
    addr = await _branch_to(
        dut, pc_mux=PC_EXC,
        exc_pc_mux_i=EXC_PC_IRQ,
        csr_mtvec_i=0x1000_2000,
        exc_cause=_pack_exc_cause(irq_int=0, irq_ext=0, lower_cause=0),
    )
    # {0x1000_20, 0, 5'd0, 2'b00} = 0x1000_2000 (already line-aligned)
    assert addr == _line_aligned(0x1000_2000), f"got {addr:#010x}"


@cocotb.test()
async def req1_exc_pc_irq_lower_cause_max(dut):
    """Edge: EXC_PC_IRQ with lower_cause=31 (= NMI vector slot, but
    irq_int=0 so it's the legitimate cause #31).
    """
    await _start_clock(dut)
    await _reset(dut)
    addr = await _branch_to(
        dut, pc_mux=PC_EXC,
        exc_pc_mux_i=EXC_PC_IRQ,
        csr_mtvec_i=0x1000_2000,
        exc_cause=_pack_exc_cause(irq_int=0, irq_ext=1, lower_cause=31),
    )
    # {0x1000_20, 0, 5'd31, 2'b00} = 0x1000_207C → line-aligned 0x1000_2078
    assert addr == _line_aligned(0x1000_207C), f"got {addr:#010x}"


# ── Requirement 2 — Fetch address mux scenarios ─────────────────────────

@cocotb.test()
async def req2_fetch_boot_pc(dut):
    """Spec Req 2 — Scenario "boot PC": PC_BOOT + boot=0x0010_0000 →
    fetch_addr_n = 0x0010_0080.
    """
    await _start_clock(dut)
    await _reset(dut)
    addr = await _branch_to(
        dut, pc_mux=PC_BOOT, boot_addr_i=0x0010_0000,
    )
    assert addr == _line_aligned(0x0010_0080), f"got {addr:#010x}"


@cocotb.test()
async def req2_fetch_jump_target(dut):
    """Spec Req 2 — Scenario "jump-target": PC_JUMP + branch_target=
    0x0010_1234 → fetch_addr_n = 0x0010_1234, line-aligned to
    0x0010_1230 by the icache bus master.
    """
    await _start_clock(dut)
    await _reset(dut)
    addr = await _branch_to(
        dut, pc_mux=PC_JUMP, branch_target_ex_i=0x0010_1234,
    )
    assert addr == _line_aligned(0x0010_1234), f"got {addr:#010x}"


@cocotb.test()
async def req2_fetch_eret(dut):
    """Spec Req 2 — Scenario "ERET / mret return": PC_ERET + csr_mepc=
    0x0010_2000 → fetch_addr_n = 0x0010_2000.
    """
    await _start_clock(dut)
    await _reset(dut)
    addr = await _branch_to(
        dut, pc_mux=PC_ERET, csr_mepc_i=0x0010_2000,
    )
    assert addr == _line_aligned(0x0010_2000), f"got {addr:#010x}"


@cocotb.test()
async def req2_fetch_dret(dut):
    """Spec Req 2 (additional): PC_DRET → csr_depc_i."""
    await _start_clock(dut)
    await _reset(dut)
    addr = await _branch_to(
        dut, pc_mux=PC_DRET, csr_depc_i=0x0010_3000,
    )
    assert addr == _line_aligned(0x0010_3000), f"got {addr:#010x}"


@cocotb.test()
async def req2_fetch_bp_collapses_under_predictor_off(dut):
    """Spec Req 2 — Scenario "BP collapse": PC_BP + boot=0x0010_0000 →
    fetch_addr_n = 0x0010_0080 under BranchPredictor=0.
    """
    await _start_clock(dut)
    await _reset(dut)
    addr = await _branch_to(
        dut, pc_mux=PC_BP, boot_addr_i=0x0010_0000,
    )
    assert addr == _line_aligned(0x0010_0080), f"got {addr:#010x}"


@cocotb.test()
async def req2_fetch_boot_lower_8_bits_ignored(dut):
    """Edge: PC_BOOT only uses boot_addr_i[31:8]; the lower 8 bits are
    forced to 8'h80.
    """
    await _start_clock(dut)
    await _reset(dut)
    addr = await _branch_to(
        dut, pc_mux=PC_BOOT, boot_addr_i=0x0010_00FF,
    )
    assert addr == _line_aligned(0x0010_0080), f"got {addr:#010x}"


# ── Requirement 3 — Branch request synthesis scenarios ─────────────────

@cocotb.test()
async def req3_pc_set_aligns_to_halfword(dut):
    """Spec Req 3 — Scenario "regular pc_set_i":
    fetch_addr_n=0x0010_0083 with pc_set_i=1. The IF stage forces bit 0
    to 0 producing prefetch_addr=0x0010_0082; the prefetch buffer then
    additionally word-aligns its bus address (bits [1:0]=0), so
    instr_addr_o = 0x0010_0080. The IF stage's bit-0 force is internal
    (subsumed by the buffer's stricter word alignment); this test
    exercises the misaligned-branch path and verifies word alignment.
    """
    await _start_clock(dut)
    await _reset(dut)
    addr = await _branch_to(
        dut, pc_mux=PC_JUMP, branch_target_ex_i=0x0010_0083,
    )
    assert addr == _line_aligned(0x0010_0080), f"got {addr:#010x}"


@cocotb.test()
async def req3_nt_branch_misprediction_replay(dut):
    """Spec Req 3 — Scenario "nt-branch misprediction replay":
    pc_set_i=0, nt_branch_mispredict_i=1, nt_branch_addr_i=0x0010_4000
    → icache.branch_addr = 0x0010_4000 (no bit-0 force on the replay
    path). Visible `instr_addr_o` is the icache bus master, which
    line-aligns to the 8-byte boundary (0x0010_4000 is already aligned).
    """
    await _start_clock(dut)
    await _reset(dut)  # waits for the cold-boot inval walk
    # Drive a misprediction replay: branch_req=0 but prefetch_branch=1
    # because nt_branch_mispredict_i=1; icache branch addr = nt_branch_addr_i.
    dut.pc_set_i.value = 0
    dut.nt_branch_mispredict_i.value = 1
    dut.nt_branch_addr_i.value = 0x0010_4000
    dut.req_i.value = 1
    dut.id_in_ready_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.nt_branch_mispredict_i.value = 0
    await _settle(dut)
    # Wait for the icache bus master to drive the request.
    for _ in range(16):
        if int(dut.instr_req_o.value) == 1:
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    addr = int(dut.instr_addr_o.value) & MASK32
    assert addr == _line_aligned(0x0010_4000), f"got {addr:#010x}"


# ── Requirement 4 — Prefetch buffer wiring + valid squash ──────────────

@cocotb.test()
async def req4_clean_fetch_passes_through(dut):
    """Spec Req 4 — Scenario "clean fetch passes through": no
    misprediction, fetch_valid_raw → fetch_valid → instr_valid_id_o.
    """
    await _start_clock(dut)
    await _reset(dut)
    landed = await _land_one_instruction(
        dut, branch_addr=0x0010_0080, rdata=0x00100093,
    )
    assert landed, "instr_valid_id_o never asserted under clean fetch"


@cocotb.test()
async def req4_misprediction_squashes_fetch_valid(dut):
    """Spec Req 4 — Scenario "fetch valid squashed on misprediction":
    nt_branch_mispredict_i=1 squashes fetch_valid → instr_new_id_o
    must NOT pulse on the squash cycle even if the prefetch buffer
    presents data internally.
    """
    await _start_clock(dut)
    await _reset(dut)
    # Land an instruction in the prefetch FIFO but assert mispredict
    # before id_in_ready_i lets it through.
    dut.pc_mux_i.value = PC_JUMP
    dut.branch_target_ex_i.value = 0x0010_0080
    dut.pc_set_i.value = 1
    dut.req_i.value = 1
    dut.id_in_ready_i.value = 0
    await RisingEdge(dut.clk_i)
    dut.pc_set_i.value = 0
    await _settle(dut)
    # Issue the bus handshake.
    for _ in range(8):
        if int(dut.instr_req_o.value) == 1:
            dut.instr_gnt_i.value = 1
            await RisingEdge(dut.clk_i)
            dut.instr_gnt_i.value = 0
            await _settle(dut)
            dut.instr_rvalid_i.value = 1
            dut.instr_rdata_i.value = 0x00100093
            await RisingEdge(dut.clk_i)
            dut.instr_rvalid_i.value = 0
            dut.instr_rdata_i.value = 0
            await _settle(dut)
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    # Now assert misprediction and id_in_ready_i. The squash means the
    # instruction must NOT enter the IF→ID register (instr_new_id_o = 0
    # at the next posedge).
    dut.nt_branch_mispredict_i.value = 1
    dut.id_in_ready_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.nt_branch_mispredict_i.value = 0
    await _settle(dut)
    # instr_new_id_o was driven by fetch_valid which was squashed.
    assert int(dut.instr_new_id_o.value) == 0, (
        "instr_new_id_o pulsed despite fetch_valid being squashed by "
        "nt_branch_mispredict_i"
    )


# ── Requirement 5 — Compressed decoder wiring ──────────────────────────

@cocotb.test()
async def req5_compressed_decoder_rv32_passthrough(dut):
    """Spec Req 5: an RV32 instruction (low bits 2'b11) passes through
    the compressed decoder with is_compressed=0 and illegal=0.
    """
    await _start_clock(dut)
    await _reset(dut)
    landed = await _land_one_instruction(
        dut, branch_addr=0x0010_0080, rdata=0x00100093,
    )
    assert landed
    assert int(dut.instr_rdata_id_o.value) & MASK32 == 0x00100093
    assert int(dut.instr_is_compressed_id_o.value) == 0
    assert int(dut.illegal_c_insn_id_o.value) == 0


@cocotb.test()
async def req5_compressed_instruction_expansion(dut):
    """Spec Req 5: a compressed instruction (low bits != 2'b11) is
    expanded by the decoder. Use C.ADDI x8, 4 = 0x0411 (expands to
    addi x8, x8, 4 = 0x00440413). The full-word fetch lands the
    halfword at [15:0] (bits [31:16] don't matter for compressed
    decoding when fetch_addr is half-aligned to 0).
    Also verify is_compressed_id_o = 1 and instr_rdata_c_id_o latches
    the original 16-bit half-word.
    """
    await _start_clock(dut)
    await _reset(dut)
    # Encode a fetch where the low halfword is the compressed instr.
    # Half-aligned address (bit 1 = 0) so the prefetch FIFO presents
    # rdata[15:0] as the instruction.
    landed = await _land_one_instruction(
        dut, branch_addr=0x0010_0080, rdata=0x0000_0411,
    )
    assert landed, "compressed instruction never reached IF→ID register"
    assert int(dut.instr_is_compressed_id_o.value) == 1, (
        "is_compressed_id_o must be 1 for a compressed encoding"
    )
    assert int(dut.illegal_c_insn_id_o.value) == 0, (
        "illegal_c_insn_id_o must be 0 for a legal compressed encoding"
    )
    # The original 16-bit halfword survives in instr_rdata_c_id_o.
    assert int(dut.instr_rdata_c_id_o.value) & 0xFFFF == 0x0411, (
        f"instr_rdata_c_id_o = "
        f"{int(dut.instr_rdata_c_id_o.value) & 0xFFFF:#06x}, expected 0x0411"
    )


# ── Requirement 6 — Instruction-error combination ──────────────────────

@cocotb.test()
async def req6_bus_error_only(dut):
    """Spec Req 6 — Scenario "bus error only":
    fetch_err=1 (via instr_bus_err_i), pmp_err_if_i=0, pmp_err_if_plus2_i=0.
    instr_fetch_err_o latches as 1.
    """
    await _start_clock(dut)
    await _reset(dut)
    landed = await _land_one_instruction(
        dut, branch_addr=0x0010_0080, rdata=0x00100093, bus_err=1,
    )
    assert landed
    assert int(dut.instr_fetch_err_o.value) == 1, (
        "instr_fetch_err_o must be 1 under bus error"
    )


@cocotb.test()
async def req6_pmp_plus2_on_misaligned_uncompressed(dut):
    """Spec Req 6 — Scenario "PMP plus2 on misaligned uncompressed":
    pmp_err_if_plus2=1, fetch_addr[1]=1, instr_is_compressed=0.
    instr_fetch_err_o=1, instr_fetch_err_plus2_o=1.
    """
    await _start_clock(dut)
    await _reset(dut)
    # branch_addr=0x0010_0082 → addr[1]=1.
    # The icache delivers the misaligned 32-bit instruction by
    # combining the upper halfword of the current beat (= bytes
    # [82..83]) with the lower halfword of the NEXT beat (= bytes
    # [84..85]). For the icache to recognise it as RV32 (not
    # compressed) we need both halfwords to have bits[1:0]=2'b11 in
    # their LOW positions: rdata[17:16]==2'b11 (gates output_valid)
    # AND the assembled rdata_o[1:0]==2'b11 (drives compressed=0).
    # Choosing rdata=0x00130013 satisfies both since bits[1:0]=11
    # and bits[17:16]=11.
    landed = await _land_one_instruction(
        dut, branch_addr=0x0010_0082, rdata=0x00130013,
        pmp_err_if=0, pmp_err_if_plus2=1,
    )
    assert landed, "instruction never reached IF→ID register"
    assert int(dut.instr_fetch_err_o.value) == 1, (
        "instr_fetch_err_o must be 1 under PMP plus2 + misaligned RV32"
    )
    assert int(dut.instr_fetch_err_plus2_o.value) == 1, (
        "instr_fetch_err_plus2_o must be 1"
    )


@cocotb.test()
async def req6_pmp_first_half_overrides_plus2(dut):
    """Spec Req 6 — Scenario "PMP first-half overrides plus2":
    pmp_err_if_i=1 + pmp_err_if_plus2_i=1 → err=1, plus2=0
    (the & ~pmp_err_if_i mask suppresses plus2).
    """
    await _start_clock(dut)
    await _reset(dut)
    landed = await _land_one_instruction(
        dut, branch_addr=0x0010_0080, rdata=0x00100093,
        pmp_err_if=1, pmp_err_if_plus2=1,
    )
    assert landed
    assert int(dut.instr_fetch_err_o.value) == 1
    assert int(dut.instr_fetch_err_plus2_o.value) == 0


# ── Requirement 7 — IF→ID pipe-register write enable ──────────────────

@cocotb.test()
async def req7_clean_register_write(dut):
    """Spec Req 7 — Scenario "clean register write":
    pipe regs latch instr_decompressed and fetch_addr.
    """
    await _start_clock(dut)
    await _reset(dut)
    branch_addr = 0x0010_0084
    landed = await _land_one_instruction(
        dut, branch_addr=branch_addr, rdata=0x00100093,
    )
    assert landed
    assert int(dut.pc_id_o.value) & MASK32 == branch_addr
    assert int(dut.instr_rdata_id_o.value) & MASK32 == 0x00100093
    assert int(dut.instr_is_compressed_id_o.value) == 0


@cocotb.test()
async def req7_write_suppressed_by_pc_set(dut):
    """Spec Req 7 — Scenario "write suppressed by pc_set_i":
    if_id_pipe_reg_we = 0 when pc_set_i = 1 even if everything else is
    ready. The pre-existing pipe-reg state must NOT be overwritten.
    """
    await _start_clock(dut)
    await _reset(dut)
    # First land a known instruction.
    landed = await _land_one_instruction(
        dut, branch_addr=0x0010_0080, rdata=0x00100093,
    )
    assert landed
    pc_id_pre = int(dut.pc_id_o.value) & MASK32
    rdata_pre = int(dut.instr_rdata_id_o.value) & MASK32
    # Now drive a pc_set_i with id_in_ready_i=1 — the WE must be suppressed.
    dut.pc_set_i.value = 1
    dut.pc_mux_i.value = PC_JUMP
    dut.branch_target_ex_i.value = 0x0010_2000
    dut.id_in_ready_i.value = 1
    # Try to drive a different rdata via the bus (won't matter; suppress wins).
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.pc_set_i.value = 0
    await _settle(dut)
    # Pipe regs must be unchanged.
    assert int(dut.pc_id_o.value) & MASK32 == pc_id_pre, (
        "pc_id_o changed despite pc_set_i suppressing the WE"
    )
    assert int(dut.instr_rdata_id_o.value) & MASK32 == rdata_pre


@cocotb.test()
async def req7_write_suppressed_by_id_not_ready(dut):
    """Spec Req 7 — Scenario "write suppressed by ~id_in_ready_i":
    With id_in_ready_i=0, the IF→ID pipe regs do not update even
    if the prefetch buffer presents a valid instruction.
    """
    await _start_clock(dut)
    await _reset(dut)
    # Branch to a fetch address.
    dut.pc_mux_i.value = PC_JUMP
    dut.branch_target_ex_i.value = 0x0010_0080
    dut.pc_set_i.value = 1
    dut.req_i.value = 1
    dut.id_in_ready_i.value = 0  # ID not ready
    await RisingEdge(dut.clk_i)
    dut.pc_set_i.value = 0
    await _settle(dut)
    # Issue the bus handshake.
    for _ in range(8):
        if int(dut.instr_req_o.value) == 1:
            dut.instr_gnt_i.value = 1
            await RisingEdge(dut.clk_i)
            dut.instr_gnt_i.value = 0
            await _settle(dut)
            dut.instr_rvalid_i.value = 1
            dut.instr_rdata_i.value = 0x00100093
            await RisingEdge(dut.clk_i)
            dut.instr_rvalid_i.value = 0
            dut.instr_rdata_i.value = 0
            await _settle(dut)
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    # Now wait several cycles with id_in_ready_i still 0.
    for _ in range(4):
        await RisingEdge(dut.clk_i)
        await _settle(dut)
        # The pipe-reg WE must remain 0 → instr_valid_id_o stays 0.
        assert int(dut.instr_valid_id_o.value) == 0, (
            "instr_valid_id_o went high despite id_in_ready_i=0"
        )


# ── Requirement 8 — instr_valid_id_q / instr_new_id_q state ────────────

@cocotb.test()
async def req8_valid_holds_across_stalls(dut):
    """Spec Req 8 — Scenario "valid latches and holds across stalls":
    after instr_new_id_d=1 cycle, instr_valid_id_o stays 1 while
    instr_valid_clear_i stays 0.
    """
    await _start_clock(dut)
    await _reset(dut)
    landed = await _land_one_instruction(
        dut, branch_addr=0x0010_0080, rdata=0x00100093,
    )
    assert landed
    dut.id_in_ready_i.value = 0
    dut.instr_valid_clear_i.value = 0
    saw_new_zero = False
    for _ in range(3):
        await RisingEdge(dut.clk_i)
        await _settle(dut)
        assert int(dut.instr_valid_id_o.value) == 1
        if int(dut.instr_new_id_o.value) == 0:
            saw_new_zero = True
    assert saw_new_zero


@cocotb.test()
async def req8_explicit_clear(dut):
    """Spec Req 8 — Scenario "explicit clear":
    instr_valid_clear_i=1 forces instr_valid_id_q to 0 next cycle.
    """
    await _start_clock(dut)
    await _reset(dut)
    landed = await _land_one_instruction(
        dut, branch_addr=0x0010_0080, rdata=0x00100093,
    )
    assert landed
    # Now assert clear.
    dut.id_in_ready_i.value = 0
    dut.instr_valid_clear_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.instr_valid_clear_i.value = 0
    await _settle(dut)
    assert int(dut.instr_valid_id_o.value) == 0, (
        "instr_valid_id_o must be 0 after instr_valid_clear_i pulse"
    )


@cocotb.test()
async def req8_async_reset(dut):
    """Spec Req 8 — Scenario "reset":
    rst_ni falling forces instr_valid_id_q and instr_new_id_q to 0.
    """
    await _start_clock(dut)
    await _reset(dut)
    landed = await _land_one_instruction(
        dut, branch_addr=0x0010_0080, rdata=0x00100093,
    )
    assert landed
    # Async-low reset.
    dut.rst_ni.value = 0
    await Timer(1, "ns")
    assert int(dut.instr_valid_id_o.value) == 0, (
        "instr_valid_id_o must be 0 immediately after rst_ni falls"
    )
    assert int(dut.instr_new_id_o.value) == 0
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)


# ── Requirement 9 — csr_mtvec_init_o ───────────────────────────────────

@cocotb.test()
async def req9_boot_pulse(dut):
    """Spec Req 9 — Scenario "boot pulse": PC_BOOT + pc_set_i=1 → 1."""
    await _start_clock(dut)
    await _reset(dut, wait_idle=False)
    dut.pc_mux_i.value = PC_BOOT
    dut.pc_set_i.value = 1
    await _settle(dut)
    assert int(dut.csr_mtvec_init_o.value) == 1


@cocotb.test()
async def req9_any_other_pc_mux(dut):
    """Spec Req 9 — Scenario "any other PC mux": PC_JUMP+pc_set_i=1 → 0."""
    await _start_clock(dut)
    await _reset(dut, wait_idle=False)
    for mux in (PC_JUMP, PC_EXC, PC_ERET, PC_DRET, PC_BP):
        dut.pc_mux_i.value = mux
        dut.pc_set_i.value = 1
        await _settle(dut)
        assert int(dut.csr_mtvec_init_o.value) == 0, (
            f"csr_mtvec_init_o = 1 for pc_mux={mux} (should only fire on PC_BOOT)"
        )


@cocotb.test()
async def req9_pc_boot_without_pc_set(dut):
    """Edge: PC_BOOT but pc_set_i=0 → init must be 0."""
    await _start_clock(dut)
    await _reset(dut, wait_idle=False)
    dut.pc_mux_i.value = PC_BOOT
    dut.pc_set_i.value = 0
    await _settle(dut)
    assert int(dut.csr_mtvec_init_o.value) == 0


# ── Requirement 10 — tieoffs ───────────────────────────────────────────

@cocotb.test()
async def req10_tieoff_outputs_constant_zero(dut):
    """Spec Req 10: branch-predictor + dummy-instruction + pc-mismatch
    + integrity tieoff outputs are 0 after reset.

    Under D1's `ICache=1` flip, the `ic_*` ICache RAM-port signals are
    NOT tieoffs — they are real driven outputs of the live `ibex_icache`
    instance (R-INV-1..7 cold-boot walk drives `ic_tag_req_o` /
    `ic_tag_write_o` / `ic_tag_addr_o` / `ic_data_req_o` etc.). They're
    asserted dynamically by other tests. `ic_scr_key_req_o` stays 0
    because `ic_scr_key_valid_i = 1` (SoC binding under
    ICacheScramble=0), so the icache bypasses `AWAIT_SCRAMBLE_KEY`
    (R-INV-3). `icache_ecc_error_o` is 0 under MemECC=0.
    """
    await _start_clock(dut)
    await _reset(dut, wait_idle=False)
    await _settle(dut)
    constants = {
        "ic_scr_key_req_o":    0,  # ic_scr_key_valid_i held high
        "icache_ecc_error_o":  0,
        "dummy_instr_id_o":    0,
        "instr_bp_taken_o":    0,
        "pc_mismatch_alert_o": 0,
        "instr_intg_err_o":    0,
    }
    for name, expected in constants.items():
        actual = int(getattr(dut, name).value)
        assert actual == expected, f"{name} = {actual}, expected {expected}"


@cocotb.test()
async def req10_tieoffs_stay_zero_during_active_fetch(dut):
    """Edge: branch-predictor / dummy-instruction / integrity tieoffs
    remain 0 even during an active fetch — these are constant
    combinational, not register-controlled. (The `ic_*` signals are
    real ICache RAM-port outputs and are exercised dynamically; not
    a tieoff under D1's `ICache=1` flip.)
    """
    await _start_clock(dut)
    await _reset(dut)
    landed = await _land_one_instruction(
        dut, branch_addr=0x0010_0080, rdata=0x00100093,
    )
    assert landed
    assert int(dut.dummy_instr_id_o.value) == 0
    assert int(dut.instr_bp_taken_o.value) == 0
    assert int(dut.pc_mismatch_alert_o.value) == 0
    assert int(dut.instr_intg_err_o.value) == 0


@cocotb.test()
async def req10_pc_if_o_tracks_fetch_addr(dut):
    """Spec Req 10: pc_if_o = fetch_addr (the icache `addr_o`).
    After a successful fetch and pop, pc_if_o tracks the head of the
    icache output (= next instruction). The latched-at-pop PC lives in
    pc_id_o; pc_if_o has advanced by one instruction word.
    """
    await _start_clock(dut)
    await _reset(dut)
    branch_addr = 0x0010_0084
    landed = await _land_one_instruction(
        dut, branch_addr=branch_addr, rdata=0x00100093,
    )
    assert landed
    pc_if = int(dut.pc_if_o.value) & MASK32
    pc_id = int(dut.pc_id_o.value) & MASK32
    # pc_id_o latches the popped instruction's PC; pc_if_o tracks the
    # current icache head (= next instruction, advanced by 4 bytes for
    # an uncompressed pop).
    assert pc_id == branch_addr, (
        f"pc_id_o = {pc_id:#010x}, expected {branch_addr:#010x}"
    )
    assert pc_if == branch_addr + 4, (
        f"pc_if_o = {pc_if:#010x}, expected {branch_addr + 4:#010x} "
        f"(advanced by one uncompressed instruction)"
    )
