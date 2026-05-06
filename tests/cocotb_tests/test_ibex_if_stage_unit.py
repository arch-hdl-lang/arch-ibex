"""Standalone cocotb scenarios for `ibex_if_stage` (basic suite).

Each `@cocotb.test` covers one Requirement from
`changes/port-if_stage/specs/if_stage/spec.md`, walking the single most
representative scenario from that Requirement. Optimised for fast
feedback (target full-suite runtime ≤ 30 s).

In-scope SoC parameter pinning (per spec § "Pinned parameter values"):
  - ICache            = 0  (ICache outputs tied to 0; only prefetch path)
  - BranchPredictor   = 0  (no skid; PC_BP collapses to boot path)
  - DummyInstructions = 0  (dummy_instr_id_o = 0)
  - MemECC            = 0  (instr_intg_err = 0; MemDataWidth = 32)
  - PCIncrCheck       = 0  (pc_mismatch_alert_o = 0)
  - ResetAll          = 0  (IF→ID pipe regs are no-reset)
  - RV32ZC            = RV32ZcaZcbZcmp (= 3)
  - DmHaltAddr        = 32'h1A11_0800
  - DmExceptionAddr   = 32'h1A11_0808

Type / port encodings (per spec & port-shape gotchas):
  - PcSel:    PC_BOOT=0, PC_JUMP=1, PC_EXC=2, PC_ERET=3, PC_DRET=4, PC_BP=5
  - ExcPcSel: EXC_PC_EXC=0, EXC_PC_IRQ=1, EXC_PC_DBD=2, EXC_PC_DBG_EXC=3
  - InstrExp: INSTR_NOT_EXPANDED=0, INSTR_EXPANDED=1, INSTR_EXPANDED_LAST=2
  - exc_cause: 7-bit packed {irq_int[6], irq_ext[5], lower_cause[4:0]}
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

# ── Test parameters ──────────────────────────────────────────────────────
CLK_PERIOD_NS = 10  # 100 MHz

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

# Pinned constants from spec
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
    """Lay out exc_cause as 7-bit packed {irq_int[6], irq_ext[5], lc[4:0]}."""
    return ((irq_int & 1) << 6) | ((irq_ext & 1) << 5) | (lower_cause & 0x1F)


# ── Testbench helpers ───────────────────────────────────────────────────

async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())


async def _settle(dut):
    """Let combinational logic settle after a signal assignment."""
    await Timer(1, "ns")


def _idle_inputs(dut):
    """Drive all DUT inputs to a benign idle state (no fetch in flight)."""
    dut.req_i.value = 0
    dut.boot_addr_i.value = 0x0010_0000
    # ID-side
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
    # Bus side
    dut.instr_gnt_i.value = 0
    dut.instr_rvalid_i.value = 0
    dut.instr_rdata_i.value = 0
    dut.instr_bus_err_i.value = 0
    # Unused / tieoff inputs.
    # NOTE: `ic_scr_key_valid_i` is tied to 1 by the SoC (`ibex_top.sv:581`,
    # under `ICacheScramble=0`) — the icache otherwise raises
    # `ic_scr_key_req_o` and stalls in `AWAIT_SCRAMBLE_KEY` (R-INV-3).
    dut.icache_enable_i.value = 0
    dut.icache_inval_i.value = 0
    dut.ic_scr_key_valid_i.value = 1
    dut.dummy_instr_en_i.value = 0
    dut.dummy_instr_mask_i.value = 0
    dut.dummy_instr_seed_en_i.value = 0
    dut.dummy_instr_seed_i.value = 0
    # Per-lane unpacked Vec inputs
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

    When `wait_idle` is true (the default) additionally advance past the
    icache cold-boot inval walk (`IC_NUM_LINES = 128` cycles + slack) so
    that subsequent test logic starts from an idle/ready icache. Tests
    that probe purely combinational outputs immediately after reset
    (e.g. tieoff readbacks, csr_mtvec_init pulse) can pass
    `wait_idle=False` to skip the wait.
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


async def _land_one_instruction(dut, *, branch_addr: int, rdata: int,
                                bus_err: int = 0,
                                max_cycles: int = 32) -> bool:
    """Drive a branch + bus handshake to land one instruction in the
    IF→ID pipe register so that `instr_valid_id_o` goes high.

    Under D1's `ICache=1` flip, IfStage wraps `ibex_icache`. The
    icache fills a 64-bit line per miss (`IC_LINE_BEATS = 2` bus
    beats), so this helper serves BOTH beats with the same `rdata`
    word (and the same `bus_err`). Whichever halfword the icache
    presents, the resulting decoded instruction is `rdata`.

    Caller must have:
      - clock running
      - dut out of reset (and ideally past the inval walk;
        `_reset(wait_idle=True)` does this)
      - `req_i = 1` is set inside this helper
    """
    # Issue a branch to load the new fetch address.
    dut.pc_set_i.value = 1
    dut.pc_mux_i.value = PC_JUMP
    dut.branch_target_ex_i.value = branch_addr & MASK32
    dut.req_i.value = 1
    dut.id_in_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.pc_set_i.value = 0
    await _settle(dut)

    # Serve `IC_LINE_BEATS_PER_FILL` bus beats; the icache fills a
    # full cache line per miss.
    for _ in range(IC_LINE_BEATS_PER_FILL):
        # Wait for instr_req_o for THIS beat.
        seen_req = False
        for _ in range(max_cycles):
            if int(dut.instr_req_o.value) == 1:
                seen_req = True
                break
            await RisingEdge(dut.clk_i)
            await _settle(dut)
        if not seen_req:
            return False
        # Grant.
        dut.instr_gnt_i.value = 1
        await RisingEdge(dut.clk_i)
        dut.instr_gnt_i.value = 0
        await _settle(dut)
        # Respond next cycle with rdata + (optional) bus error.
        dut.instr_rvalid_i.value = 1
        dut.instr_rdata_i.value = rdata & MASK32
        dut.instr_bus_err_i.value = bus_err & 1
        await RisingEdge(dut.clk_i)
        dut.instr_rvalid_i.value = 0
        dut.instr_rdata_i.value = 0
        dut.instr_bus_err_i.value = 0
        await _settle(dut)

    # Wait a few cycles for the icache to land valid_o → IF→ID pipe.
    # Hold id_in_ready_i = 1 so the pipe-reg write fires; then drop it
    # so the entry sticks in the IF→ID register for the caller's
    # observation.
    for _ in range(8):
        if int(dut.instr_valid_id_o.value) == 1:
            dut.id_in_ready_i.value = 0
            await _settle(dut)
            return True
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    return int(dut.instr_valid_id_o.value) == 1


# ── Tests: one per spec Requirement (10 total) ──────────────────────────

@cocotb.test()
async def req1_exception_pc_mux_irq_vector(dut):
    """Spec §"Requirement 1: Exception PC mux" — Scenario "vectorised
    external IRQ". Verifies that with EXC_PC_IRQ + irq_int=0 + lower_cause=11,
    the IF stage drives a fetch_addr_n that reflects the vectored IRQ
    target {csr_mtvec[31:8], 1'b0, irq_vec=11, 2'b00} = 0x1000_202C.

    The exc_pc value is observed indirectly via fetch_addr_n →
    icache.branch_addr, by selecting PC_EXC and asserting pc_set_i.
    Under D1's `ICache=1` flip the visible `instr_addr_o` is the
    icache's bus-master output, which line-aligns to the 8-byte cache
    line boundary: expected = 0x1000_202C & ~0x7 = 0x1000_2028.
    """
    await _start_clock(dut)
    await _reset(dut)  # waits for the cold-boot inval walk
    # Drive the exception PC mux + cause; route via PC_EXC and observe
    # what address the icache is told to branch to (instr_addr_o tracks
    # the bus-master line-base addr).
    dut.exc_pc_mux_i.value = EXC_PC_IRQ
    dut.csr_mtvec_i.value = 0x1000_2000
    dut.exc_cause.value = _pack_exc_cause(irq_int=0, irq_ext=1, lower_cause=11)
    dut.pc_mux_i.value = PC_EXC
    dut.pc_set_i.value = 1
    dut.req_i.value = 1
    dut.id_in_ready_i.value = 1
    await _settle(dut)
    # Wait until the icache's bus master starts driving a request for
    # the new branch target; instr_addr_o then carries the line-base.
    await RisingEdge(dut.clk_i)
    dut.pc_set_i.value = 0
    await _settle(dut)
    for _ in range(16):
        if int(dut.instr_req_o.value) == 1:
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    addr = int(dut.instr_addr_o.value) & MASK32
    expected = _line_aligned(0x1000_202C)  # = 0x1000_2028
    assert addr == expected, (
        f"instr_addr_o = {addr:#010x}, expected {expected:#010x} "
        f"(IRQ vector with lower_cause=11, line-aligned)"
    )


@cocotb.test()
async def req2_fetch_address_mux_boot_pc(dut):
    """Spec §"Requirement 2: Fetch address mux" — Scenario "boot PC".
    PC_BOOT + boot_addr_i = 0x0010_0000 → fetch_addr_n = 0x0010_0080.
    Observe via instr_addr_o after a pc_set on PC_BOOT. Boot PC is
    already 8-byte cache-line aligned so the visible bus addr matches.
    """
    await _start_clock(dut)
    await _reset(dut)  # waits for the cold-boot inval walk
    dut.boot_addr_i.value = 0x0010_0000
    dut.pc_mux_i.value = PC_BOOT
    dut.pc_set_i.value = 1
    dut.req_i.value = 1
    dut.id_in_ready_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.pc_set_i.value = 0
    await _settle(dut)
    for _ in range(16):
        if int(dut.instr_req_o.value) == 1:
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    addr = int(dut.instr_addr_o.value) & MASK32
    expected = _line_aligned(0x0010_0080)  # = 0x0010_0080
    assert addr == expected, (
        f"instr_addr_o = {addr:#010x}, expected boot PC {expected:#010x}"
    )


@cocotb.test()
async def req3_branch_request_synthesis_aligns_to_halfword(dut):
    """Spec §"Requirement 3: Branch request synthesis" — Scenario
    "regular pc_set_i". With pc_set_i=1, fetch_addr_n=0x0010_0083, the
    IF stage's prefetch_addr forces bit 0 to zero. Under D1's
    `ICache=1` flip the icache's bus master then line-aligns to the
    8-byte cache line boundary (`addr & ~0x7`), so the visible
    `instr_addr_o` lands on 0x0010_0080. The bit-0 force is internal
    to the IF stage (subsumed by the icache's stricter line alignment);
    the full-regression suite covers the icache-internal half-PC
    handling separately.
    """
    await _start_clock(dut)
    await _reset(dut)  # waits for the cold-boot inval walk
    # Use PC_JUMP with a deliberately misaligned-by-1 branch target.
    dut.pc_mux_i.value = PC_JUMP
    dut.branch_target_ex_i.value = 0x0010_0083
    dut.pc_set_i.value = 1
    dut.req_i.value = 1
    dut.id_in_ready_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.pc_set_i.value = 0
    await _settle(dut)
    for _ in range(16):
        if int(dut.instr_req_o.value) == 1:
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    addr = int(dut.instr_addr_o.value) & MASK32
    expected = _line_aligned(0x0010_0080)  # = 0x0010_0080
    assert addr == expected, (
        f"instr_addr_o = {addr:#010x}, expected {expected:#010x} "
        f"(line-aligned bus address after misaligned-branch path)"
    )


@cocotb.test()
async def req4_prefetch_buffer_clean_fetch_passes_through(dut):
    """Spec §"Requirement 4: Prefetch buffer wiring + valid squash" —
    Scenario "clean fetch passes through". With no misprediction,
    fetch_valid_raw → fetch_valid → IF→ID pipe register so that
    instr_valid_id_o eventually goes high after a successful bus handshake.
    """
    await _start_clock(dut)
    await _reset(dut)
    # Land a clean instruction (RV32 ADDI x1,x0,1 = 0x00100093).
    landed = await _land_one_instruction(
        dut, branch_addr=0x0010_0080, rdata=0x00100093, bus_err=0,
    )
    assert landed, (
        "fetch_valid never propagated to instr_valid_id_o under clean fetch"
    )


@cocotb.test()
async def req5_compressed_decoder_uncompressed_passthrough(dut):
    """Spec §"Requirement 5: Compressed decoder wiring".
    Land a canonical RV32 ADDI (0x00100093). Verify the latched IF→ID
    register holds the instruction with is_compressed_id_o = 0 and
    illegal_c_insn_id_o = 0 — i.e. the compressed decoder's outputs
    were properly wired through to the pipe registers.
    """
    await _start_clock(dut)
    await _reset(dut)
    landed = await _land_one_instruction(
        dut, branch_addr=0x0010_0080, rdata=0x00100093,
    )
    assert landed, "instruction never reached the IF→ID register"
    assert int(dut.instr_rdata_id_o.value) & MASK32 == 0x00100093, (
        f"instr_rdata_id_o = {int(dut.instr_rdata_id_o.value):#010x}"
    )
    assert int(dut.instr_is_compressed_id_o.value) == 0, (
        "is_compressed_id_o must be 0 for an RV32 instruction"
    )
    assert int(dut.illegal_c_insn_id_o.value) == 0, (
        "illegal_c_insn_id_o must be 0 for a legal RV32 instruction"
    )


@cocotb.test()
async def req6_instruction_error_pmp_first_half_overrides_plus2(dut):
    """Spec §"Requirement 6: Instruction-error combination" — Scenario
    "PMP first-half overrides plus2". With pmp_err_if_i=1 and
    pmp_err_if_plus2_i=1, instr_fetch_err_o latches as 1 and
    instr_fetch_err_plus2_o latches as 0 (the & ~pmp_err_if_i mask
    suppresses plus2 when the first half already errored).
    """
    await _start_clock(dut)
    await _reset(dut)
    # Drive PMP errors on both halves while also landing a fetch.
    dut.pmp_err_if_i.value = 1
    dut.pmp_err_if_plus2_i.value = 1
    landed = await _land_one_instruction(
        dut, branch_addr=0x0010_0080, rdata=0x00100093, bus_err=0,
    )
    assert landed, "PMP-error fetch never reached IF→ID register"
    assert int(dut.instr_fetch_err_o.value) == 1, (
        "instr_fetch_err_o must be 1 when pmp_err_if_i=1"
    )
    assert int(dut.instr_fetch_err_plus2_o.value) == 0, (
        "instr_fetch_err_plus2_o must be 0 when pmp_err_if_i=1 (override)"
    )


@cocotb.test()
async def req7_pipe_reg_we_clean_register_write(dut):
    """Spec §"Requirement 7: IF→ID pipeline-register write enable" —
    Scenario "clean register write". With if_instr_valid=1 and
    id_in_ready_i=1 and pc_set_i=0 at posedge, the pipe registers
    update: pc_id_o latches the fetch address and instr_rdata_id_o
    latches the (un-decompressed) instruction.
    """
    await _start_clock(dut)
    await _reset(dut)
    # 0x00100093 = RV32 ADDI x1,x0,1
    branch_addr = 0x0010_0080
    landed = await _land_one_instruction(
        dut, branch_addr=branch_addr, rdata=0x00100093,
    )
    assert landed, "instruction never reached the IF→ID register"
    pc_id = int(dut.pc_id_o.value) & MASK32
    assert pc_id == branch_addr, (
        f"pc_id_o = {pc_id:#010x}, expected {branch_addr:#010x}"
    )
    assert int(dut.instr_rdata_id_o.value) & MASK32 == 0x00100093
    assert int(dut.instr_fetch_err_o.value) == 0


@cocotb.test()
async def req8_instr_valid_state_holds_across_stalls(dut):
    """Spec §"Requirement 8: instr_valid_id_q / instr_new_id_q state
    register" — Scenario "valid latches and holds across stalls".
    After an instruction lands, instr_valid_id_o must remain 1 in
    subsequent cycles where instr_valid_clear_i=0; instr_new_id_o
    is a one-cycle pulse that drops back to 0.
    """
    await _start_clock(dut)
    await _reset(dut)
    landed = await _land_one_instruction(
        dut, branch_addr=0x0010_0080, rdata=0x00100093,
    )
    assert landed, "instruction never reached IF→ID register"
    # Now hold id_in_ready_i = 0 and clear = 0; valid must stay high
    # while new pulses to 0.
    dut.id_in_ready_i.value = 0
    dut.instr_valid_clear_i.value = 0
    # Run a couple of cycles and check held-valid + dropped-new.
    saw_new_zero = False
    for _ in range(3):
        await RisingEdge(dut.clk_i)
        await _settle(dut)
        assert int(dut.instr_valid_id_o.value) == 1, (
            "instr_valid_id_o dropped despite instr_valid_clear_i=0"
        )
        if int(dut.instr_new_id_o.value) == 0:
            saw_new_zero = True
    assert saw_new_zero, (
        "instr_new_id_o must drop to 0 after the one-cycle pulse"
    )


@cocotb.test()
async def req9_csr_mtvec_init_pulses_on_pc_boot(dut):
    """Spec §"Requirement 9: csr_mtvec_init_o" — Scenario "boot pulse".
    csr_mtvec_init_o = (pc_mux_i == PC_BOOT) & pc_set_i (pure comb).
    """
    await _start_clock(dut)
    await _reset(dut)
    # Boot pulse: PC_BOOT + pc_set_i=1.
    dut.pc_mux_i.value = PC_BOOT
    dut.pc_set_i.value = 1
    await _settle(dut)
    assert int(dut.csr_mtvec_init_o.value) == 1, (
        "csr_mtvec_init_o must be 1 for PC_BOOT + pc_set_i=1"
    )
    # PC_JUMP with pc_set_i=1 → must be 0.
    dut.pc_mux_i.value = PC_JUMP
    dut.pc_set_i.value = 1
    await _settle(dut)
    assert int(dut.csr_mtvec_init_o.value) == 0, (
        "csr_mtvec_init_o must be 0 for PC_JUMP + pc_set_i=1"
    )
    # PC_BOOT with pc_set_i=0 → must be 0.
    dut.pc_mux_i.value = PC_BOOT
    dut.pc_set_i.value = 0
    await _settle(dut)
    assert int(dut.csr_mtvec_init_o.value) == 0, (
        "csr_mtvec_init_o must be 0 for PC_BOOT + pc_set_i=0"
    )


@cocotb.test()
async def req10_tieoffs_constants(dut):
    """Spec §"Requirement 10: branch-predictor + dummy-instr + integrity
    tieoffs". After reset these IfStage tieoff outputs must read 0
    combinationally (they don't depend on icache state).

    Under D1's `ICache=1` flip, the `ic_*` ICache RAM-port signals are
    NOT tieoffs — they are real driven outputs of the live `ibex_icache`
    instance (R-INV-1..7 cold-boot walk drives `ic_tag_req_o` /
    `ic_tag_write_o` / `ic_tag_addr_o` / `ic_data_req_o` etc.). They're
    asserted dynamically by other tests and verified for shape /
    line-alignment under the icache spec. Same for `ic_scr_key_req_o`:
    when `ic_scr_key_valid_i=1` (the SoC binding, see `_idle_inputs`),
    the icache holds it low past `OUT_OF_RESET` (R-INV-3).
    `icache_ecc_error_o` is 0 under MemECC=0.
    """
    await _start_clock(dut)
    await _reset(dut, wait_idle=False)
    # Even without any active fetch, the IfStage-side tieoffs must read 0.
    await _settle(dut)
    # Branch-predictor + dummy-instr + integrity tieoffs (constant
    # under SoC pinning).
    assert int(dut.dummy_instr_id_o.value) == 0
    assert int(dut.instr_bp_taken_o.value) == 0
    assert int(dut.pc_mismatch_alert_o.value) == 0
    assert int(dut.instr_intg_err_o.value) == 0
    # ECC disabled in this swap.
    assert int(dut.icache_ecc_error_o.value) == 0
    # Scramble-key request stays 0 because ic_scr_key_valid_i is held 1
    # (SoC binding under ICacheScramble=0).
    assert int(dut.ic_scr_key_req_o.value) == 0
