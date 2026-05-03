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
    # Unused / tieoff inputs
    dut.icache_enable_i.value = 0
    dut.icache_inval_i.value = 0
    dut.ic_scr_key_valid_i.value = 0
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


async def _reset(dut):
    """Apply async-low reset for two clock periods, then release."""
    _idle_inputs(dut)
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await _settle(dut)


async def _land_one_instruction(dut, *, branch_addr: int, rdata: int,
                                bus_err: int = 0, max_cycles: int = 16) -> bool:
    """Drive a branch + bus handshake to land one instruction in the
    prefetch buffer's FIFO so that fetch_valid_raw goes high.

    Caller must have:
      - clock running
      - dut out of reset
      - id_in_ready_i = 1, req_i = 1

    Returns True if fetch_valid (= prefetch buffer's valid_o) observed.
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

    # Grant the OBI request, then send rvalid with rdata.
    for _ in range(max_cycles):
        if int(dut.instr_req_o.value) == 1:
            dut.instr_gnt_i.value = 1
            await RisingEdge(dut.clk_i)
            dut.instr_gnt_i.value = 0
            await _settle(dut)
            # rvalid one cycle after grant
            dut.instr_rvalid_i.value = 1
            dut.instr_rdata_i.value = rdata & MASK32
            dut.instr_bus_err_i.value = bus_err & 1
            await RisingEdge(dut.clk_i)
            dut.instr_rvalid_i.value = 0
            dut.instr_rdata_i.value = 0
            dut.instr_bus_err_i.value = 0
            await _settle(dut)
            # Wait one or two cycles for fetch_valid_raw to settle.
            for _ in range(4):
                # Hold ready_i low so the entry stays in the FIFO.
                dut.id_in_ready_i.value = 0
                if int(dut.instr_valid_id_o.value) == 1:
                    return True
                # The IF→ID pipe register write also requires id_in_ready_i=1.
                # If the entry already moved, instr_valid_id_o = 1.
                # Otherwise we may need to peek at the prefetch's valid via
                # a single more cycle.
                await RisingEdge(dut.clk_i)
                await _settle(dut)
            return int(dut.instr_valid_id_o.value) == 1
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    return False


# ── Tests: one per spec Requirement (10 total) ──────────────────────────

@cocotb.test()
async def req1_exception_pc_mux_irq_vector(dut):
    """Spec §"Requirement 1: Exception PC mux" — Scenario "vectorised
    external IRQ". Verifies that with EXC_PC_IRQ + irq_int=0 + lower_cause=11,
    the IF stage drives a fetch_addr_n that reflects the vectored IRQ
    target {csr_mtvec[31:8], 1'b0, irq_vec=11, 2'b00} = 0x1000_202C.

    The exc_pc value is observed indirectly via fetch_addr_n → prefetch_addr,
    by selecting PC_EXC and asserting pc_set_i (which routes exc_pc into
    the prefetch buffer's branch addr_i).
    """
    await _start_clock(dut)
    await _reset(dut)
    # Drive the exception PC mux + cause; route via PC_EXC and observe
    # what address the prefetch buffer is told to branch to (instr_addr_o
    # tracks fetch_addr after the branch).
    dut.exc_pc_mux_i.value = EXC_PC_IRQ
    dut.csr_mtvec_i.value = 0x1000_2000
    dut.exc_cause.value = _pack_exc_cause(irq_int=0, irq_ext=1, lower_cause=11)
    dut.pc_mux_i.value = PC_EXC
    dut.pc_set_i.value = 1
    dut.req_i.value = 1
    dut.id_in_ready_i.value = 1
    await _settle(dut)
    # On the same combinational cycle, instr_addr_o (forwarded from the
    # prefetch buffer's instr_addr_o) reflects the new branch target.
    # We sample after one rising edge so the prefetch buffer registers
    # the branch and presents instr_addr_o.
    await RisingEdge(dut.clk_i)
    dut.pc_set_i.value = 0
    await _settle(dut)
    addr = int(dut.instr_addr_o.value) & MASK32
    expected = 0x1000_202C
    assert addr == expected, (
        f"instr_addr_o = {addr:#010x}, expected {expected:#010x} "
        f"(IRQ vector with lower_cause=11)"
    )


@cocotb.test()
async def req2_fetch_address_mux_boot_pc(dut):
    """Spec §"Requirement 2: Fetch address mux" — Scenario "boot PC".
    PC_BOOT + boot_addr_i = 0x0010_0000 → fetch_addr_n = 0x0010_0080.
    Observe via instr_addr_o after a pc_set on PC_BOOT.
    """
    await _start_clock(dut)
    await _reset(dut)
    dut.boot_addr_i.value = 0x0010_0000
    dut.pc_mux_i.value = PC_BOOT
    dut.pc_set_i.value = 1
    dut.req_i.value = 1
    dut.id_in_ready_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.pc_set_i.value = 0
    await _settle(dut)
    addr = int(dut.instr_addr_o.value) & MASK32
    expected = 0x0010_0080
    assert addr == expected, (
        f"instr_addr_o = {addr:#010x}, expected boot PC {expected:#010x}"
    )


@cocotb.test()
async def req3_branch_request_synthesis_aligns_to_halfword(dut):
    """Spec §"Requirement 3: Branch request synthesis" — Scenario
    "regular pc_set_i". With pc_set_i=1, fetch_addr_n=0x0010_0083, the
    IF stage's prefetch_addr forces bit 0 to zero. The downstream
    prefetch buffer additionally word-aligns its bus address
    (`{addr[31:2], 2'b00}`), so the visible `instr_addr_o` lands on
    0x0010_0080. This test validates the IF→prefetch path is exercised
    on a misaligned branch and the bus stays word-aligned. The bit-0
    force is internal to the IF stage (subsumed by the prefetch buffer's
    stricter word alignment); the full-regression suite covers the
    prefetch-buffer-internal bit-1-handling separately.
    """
    await _start_clock(dut)
    await _reset(dut)
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
    addr = int(dut.instr_addr_o.value) & MASK32
    expected = 0x0010_0080
    assert addr == expected, (
        f"instr_addr_o = {addr:#010x}, expected {expected:#010x} "
        f"(word-aligned bus address after misaligned-branch path)"
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
    """Spec §"Requirement 10: ICache + branch-predictor + dummy-instr
    tieoffs". After reset, all tieoff outputs must read 0 combinationally.
    """
    await _start_clock(dut)
    await _reset(dut)
    # Even without any active fetch, all tieoffs must read 0.
    await _settle(dut)
    assert int(dut.ic_tag_req_o.value) == 0
    assert int(dut.ic_tag_write_o.value) == 0
    assert int(dut.ic_tag_addr_o.value) == 0
    assert int(dut.ic_tag_wdata_o.value) == 0
    assert int(dut.ic_data_req_o.value) == 0
    assert int(dut.ic_data_write_o.value) == 0
    assert int(dut.ic_data_addr_o.value) == 0
    assert int(dut.ic_data_wdata_o.value) == 0
    assert int(dut.ic_scr_key_req_o.value) == 0
    assert int(dut.icache_ecc_error_o.value) == 0
    assert int(dut.dummy_instr_id_o.value) == 0
    assert int(dut.instr_bp_taken_o.value) == 0
    assert int(dut.pc_mismatch_alert_o.value) == 0
    assert int(dut.instr_intg_err_o.value) == 0
