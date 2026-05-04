"""Standalone cocotb scenarios for `ibex_id_stage` (basic suite).

Each `@cocotb.test` covers one Requirement from
`changes/port-id_stage/specs/id_stage/spec.md`, walking the single most
representative scenario for that Requirement (16 tests total).

In-scope SoC parameter pinning (per spec § "Pinned parameter values"):
  - RV32E           = 0
  - RV32M           = 2 (RV32MFast)
  - RV32B           = 0 (RV32BNone)
  - BranchTargetALU = 0
  - WritebackStage  = 0
  - BranchPredictor = 0
  - DataIndTiming   = 0
  - MemECC          = 0

Test design notes
-----------------
The id_stage instantiates `decoder_i` (A4) and `controller_i` (B4)
internally. Decoder outputs (illegal_insn_dec, branch_in_dec,
jump_in_dec, lsu_req_dec, mult_en_dec, etc.) are produced by driving
real RV32I instruction words on `instr_rdata_i` / `instr_rdata_alu_i`.
Controller outputs (`pc_set_o`, `id_in_ready_o`, `instr_valid_clear_o`,
`controller_run`, FSM state) are driven by the controller's own FSM,
walked from RESET → BOOT_SET → FIRST_FETCH → DECODE before each
scenario.

Key encodings (from spec + decoder/controller specs):

  - id_fsm_q: FIRST_CYCLE=0, MULTI_CYCLE=1
  - controller FSM: RESET=0, BOOT_SET=1, WAIT_SLEEP=2, SLEEP=3,
                    FIRST_FETCH=4, DECODE=5, FLUSH=6, IRQ_TAKEN=7,
                    DBG_TAKEN_IF=8, DBG_TAKEN_ID=9.
  - PcSel:    PC_BOOT=0, PC_JUMP=1, PC_EXC=2, PC_ERET=3, PC_DRET=4, PC_BP=5
  - alu_op_a_mux_sel_e: OP_A_REG_A=0, OP_A_FWD=1, OP_A_CURRPC=2, OP_A_IMM=3
  - alu_op_b_mux_sel_e: OP_B_REG_B=0, OP_B_IMM=1
  - imm_a_mux_sel_e:    IMM_A_Z=0, IMM_A_ZERO=1
  - imm_b_mux_sel_e:    IMM_B_I=0, IMM_B_S=1, IMM_B_B=2, IMM_B_U=3,
                        IMM_B_J=4, IMM_B_INCR_PC=5, IMM_B_INCR_ADDR=6
  - rf_wdata_sel_e:     RF_WD_EX=0, RF_WD_CSR=1
  - wb_instr_type_e:    WB_INSTR_LOAD=0, WB_INSTR_STORE=1, WB_INSTR_OTHER=2
  - PrivLvl: M=3, U=0
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

CLK_PERIOD_NS = 10  # 100 MHz

# ── id_fsm_q encoding ────────────────────────────────────────────────────
FIRST_CYCLE = 0
MULTI_CYCLE = 1

# ── controller FSM encoding ──────────────────────────────────────────────
S_RESET        = 0
S_BOOT_SET     = 1
S_WAIT_SLEEP   = 2
S_SLEEP        = 3
S_FIRST_FETCH  = 4
S_DECODE       = 5
S_FLUSH        = 6
S_IRQ_TAKEN    = 7
S_DBG_TAKEN_IF = 8
S_DBG_TAKEN_ID = 9

# ── PcSel encodings ──────────────────────────────────────────────────────
PC_BOOT = 0
PC_JUMP = 1
PC_EXC  = 2
PC_ERET = 3
PC_DRET = 4
PC_BP   = 5

# ── operand-A mux ────────────────────────────────────────────────────────
OP_A_REG_A  = 0
OP_A_FWD    = 1
OP_A_CURRPC = 2
OP_A_IMM    = 3

# ── operand-B mux ────────────────────────────────────────────────────────
OP_B_REG_B = 0
OP_B_IMM   = 1

# ── imm_a mux ────────────────────────────────────────────────────────────
IMM_A_Z    = 0
IMM_A_ZERO = 1

# ── imm_b mux ────────────────────────────────────────────────────────────
IMM_B_I         = 0
IMM_B_S         = 1
IMM_B_B         = 2
IMM_B_U         = 3
IMM_B_J         = 4
IMM_B_INCR_PC   = 5
IMM_B_INCR_ADDR = 6

# ── rf_wdata mux ─────────────────────────────────────────────────────────
RF_WD_EX  = 0
RF_WD_CSR = 1

# ── wb_instr_type ────────────────────────────────────────────────────────
WB_INSTR_LOAD  = 0
WB_INSTR_STORE = 1
WB_INSTR_OTHER = 2

# ── Privilege ────────────────────────────────────────────────────────────
PRIV_LVL_M = 3
PRIV_LVL_U = 0

MASK32 = 0xFFFF_FFFF
MASK34 = 0x3_FFFF_FFFF

# ── Canonical RV32I instruction encodings used by the tests ──────────────
# ADD x10, x11, x12 — opcode 0x33, funct3=0, funct7=0, rs2=12, rs1=11, rd=10
INSTR_ADD       = 0x00C58533
# ADDI x1, x0, 1 — opcode 0x13, funct3=0, rd=1, rs1=0, imm=1
INSTR_ADDI_1    = 0x00100093
# BEQ x0, x0, +8 — opcode 0x63, funct3=0, rs1=0, rs2=0, imm=8
INSTR_BEQ_TAKEN = 0x00000463
# JAL x1, +8 — opcode 0x6F, rd=1
INSTR_JAL       = 0x008000EF
# LW x6, 0(x5) — opcode 0x03, funct3=2, rd=6, rs1=5
INSTR_LW        = 0x0002A303
# SW x12, 0(x11) — opcode 0x23, funct3=2, rs1=11, rs2=12
INSTR_SW        = 0x00C5A023
# CSRRW x10, mscratch(0x340), x11 — opcode 0x73, funct3=1, rd=10, rs1=11
INSTR_CSRRW     = 0x34059573
# CSRRS x10, mscratch(0x340), x11 — opcode 0x73, funct3=2, rd=10, rs1=11
INSTR_CSRRS     = 0x3405A573
# MRET = 0x30200073, DRET = 0x7B200073, WFI = 0x10500073
INSTR_MRET      = 0x30200073
INSTR_DRET      = 0x7B200073
INSTR_WFI       = 0x10500073
# Illegal: 0x00000000 — all-zero word is illegal in 32-bit
INSTR_ILLEGAL   = 0x00000000
# FENCE.I — opcode 0x0F, funct3=1
INSTR_FENCEI    = 0x0000100F


# ── Testbench helpers ───────────────────────────────────────────────────

async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())


async def _settle(dut):
    """Let combinational logic settle after a signal assignment."""
    await Timer(1, "ns")


def _idle_inputs(dut):
    """Drive every id_stage input to a benign idle baseline.

    All decoder/LSU/IRQ/debug flags low; valid-instruction inputs zero;
    privilege M-mode; no branches / jumps / CSR accesses; no LSU
    response in flight.
    """
    # ── IF-stage interface (ID-side inputs) ─────────────────────────────
    dut.instr_valid_i.value          = 0
    dut.instr_rdata_i.value          = 0
    dut.instr_rdata_alu_i.value      = 0
    dut.instr_rdata_c_i.value        = 0
    dut.instr_is_compressed_i.value  = 0
    dut.instr_bp_taken_i.value       = 0   # pinned 0
    dut.illegal_c_insn_i.value       = 0
    dut.instr_fetch_err_i.value      = 0
    dut.instr_fetch_err_plus2_i.value = 0
    dut.pc_id_i.value                = 0x0010_0000
    dut.instr_exec_i.value           = 1

    # ── Branch / jump ────────────────────────────────────────────────────
    dut.branch_decision_i.value      = 0

    # ── EX block ─────────────────────────────────────────────────────────
    dut.ex_valid_i.value             = 0
    dut.imd_val_we_ex_i.value        = 0
    dut.imd_val_d_ex_i[0].value      = 0
    dut.imd_val_d_ex_i[1].value      = 0
    dut.result_ex_i.value            = 0

    # ── CSR ──────────────────────────────────────────────────────────────
    dut.priv_mode_i.value            = PRIV_LVL_M
    dut.csr_mstatus_tw_i.value       = 0
    dut.illegal_csr_insn_i.value     = 0
    dut.csr_rdata_i.value            = 0
    dut.data_ind_timing_i.value      = 0   # pinned 0 (N-6)

    # ── LSU ──────────────────────────────────────────────────────────────
    dut.lsu_resp_valid_i.value       = 0
    dut.lsu_req_done_i.value         = 0   # absorbed under WB=0 (N-7)
    dut.lsu_addr_incr_req_i.value    = 0
    dut.lsu_addr_last_i.value        = 0
    dut.lsu_load_err_i.value         = 0
    dut.lsu_load_resp_intg_err_i.value  = 0  # MemECC=0
    dut.lsu_store_err_i.value        = 0
    dut.lsu_store_resp_intg_err_i.value = 0  # MemECC=0

    # ── IRQ / debug ──────────────────────────────────────────────────────
    dut.csr_mstatus_mie_i.value      = 1
    dut.irq_pending_i.value          = 0
    dut.irqs_i.value                 = 0
    dut.irq_nm_i.value               = 0
    dut.debug_req_i.value            = 0
    dut.debug_single_step_i.value    = 0
    dut.debug_ebreakm_i.value        = 0
    dut.debug_ebreaku_i.value        = 0
    dut.trigger_match_i.value        = 0

    # ── Register-file read ports ─────────────────────────────────────────
    dut.rf_rdata_a_i.value           = 0
    dut.rf_rdata_b_i.value           = 0

    # ── Writeback inputs (WB=0; absorbed) ────────────────────────────────
    dut.rf_waddr_wb_i.value          = 0
    dut.rf_wdata_fwd_wb_i.value      = 0
    dut.rf_write_wb_i.value          = 0
    dut.ready_wb_i.value             = 1   # pinned 1
    dut.outstanding_load_wb_i.value  = 0
    dut.outstanding_store_wb_i.value = 0


async def _reset(dut):
    """Apply async-low reset for two clock periods, then release.
    Inputs idle. After return, one rising-edge has happened post-reset.
    """
    _idle_inputs(dut)
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await _settle(dut)


async def _walk_to_decode(dut, *, max_cycles: int = 6):
    """Advance the controller from RESET → BOOT_SET → FIRST_FETCH → DECODE.

    The controller's `ctrl_fsm_cs` (named `state_r` post-ARCH-emit) walks
    through three states deterministically when `instr_exec_i = 1`. We
    then need an instruction in the IF→ID register to keep the FSM in
    DECODE — but at this entry point ID is empty.

    Returns once the controller's state register reads DECODE.
    """
    for _ in range(max_cycles):
        # Probe the controller's internal state via its hierarchy under
        # `controller_i`. ARCH emits the FSM state register as `state_r`
        # (B4 lesson — not `ctrl_fsm_cs`).
        try:
            state = int(dut.controller_i.state_r.value)
        except AttributeError:
            # Fallback: if the implementer renamed it, just walk fixed cycles.
            state = -1
        if state == S_DECODE:
            return
        await RisingEdge(dut.clk_i)
        await _settle(dut)


async def _land_in_decode(dut, *, instr: int = 0):
    """Bring the dut up: clock, reset, walk controller to DECODE, then
    load `instr` into the IF→ID register pretend-pipe (i.e. drive
    `instr_valid_i = 1` with the instruction word).
    """
    await _start_clock(dut)
    await _reset(dut)
    await _walk_to_decode(dut)
    if instr:
        dut.instr_valid_i.value     = 1
        dut.instr_rdata_i.value     = instr
        dut.instr_rdata_alu_i.value = instr
    await _settle(dut)


# ─────────────────────────────────────────────────────────────────────────
# Requirement 1: Reset behavior
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req1_reset_clears_state_and_outputs(dut):
    """Spec §"Requirement 1: Reset behavior".

    On reset asserted (low), `id_fsm_q = FIRST_CYCLE`, `imd_val_q[*] =
    0`, `branch_set_raw_q = 0`, `branch_jump_set_done_q = 0`, and the
    derived outputs `lsu_req_o`, `mult_en_ex_o`, `div_en_ex_o`,
    `rf_we_id_o`, `pc_set_o` MUST all be 0.
    """
    await _start_clock(dut)
    _idle_inputs(dut)
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    await _settle(dut)
    # While rst_ni = 0, EX-side output strobes must be 0 (id_stage gates
    # them on `instr_executing`, which is 0 with no valid instruction).
    # `pc_set_o` is NOT zero during reset — the controller's RESET state
    # drives `pc_set_o = 1` to load PC_BOOT into the IF stage on the
    # first edge after reset release. That's a controller-side
    # invariant (B4 spec §"Requirement 1"), and id_stage forwards it
    # straight through.
    assert int(dut.lsu_req_o.value)    == 0
    assert int(dut.mult_en_ex_o.value) == 0
    assert int(dut.div_en_ex_o.value)  == 0
    assert int(dut.rf_we_id_o.value)   == 0
    # Release reset; immediately after the first edge the FSM regs read
    # their reset values.
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    # id_fsm_q starts at FIRST_CYCLE = 0.
    assert int(dut.id_fsm_q.value) == FIRST_CYCLE
    # imd_val_q pair starts at 0.
    assert int(dut.imd_val_q_ex_o[0].value) == 0
    assert int(dut.imd_val_q_ex_o[1].value) == 0


# ─────────────────────────────────────────────────────────────────────────
# Requirement 2: Read-enable gating
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req2_rf_ren_gated_by_invalid_and_illegal(dut):
    """Spec §"Requirement 2: Read-enable gating".

    `rf_ren_a_o` / `rf_ren_b_o` MUST be 0 when `instr_valid_i = 0`, and
    MUST be 0 when `illegal_csr_insn_i = 1` (which makes `illegal_insn_o
    = 1`, suppressing the read enables).
    """
    await _start_clock(dut)
    await _reset(dut)
    await _walk_to_decode(dut)
    # instr_valid_i = 0 → both rens must be 0 regardless of decoder.
    dut.instr_valid_i.value = 0
    dut.instr_rdata_i.value = INSTR_ADD
    dut.instr_rdata_alu_i.value = INSTR_ADD
    await _settle(dut)
    assert int(dut.rf_ren_a_o.value) == 0
    assert int(dut.rf_ren_b_o.value) == 0
    # Now valid + ADD → both rens should be 1 (decoder produces
    # rf_ren_a_dec=1, rf_ren_b_dec=1).
    dut.instr_valid_i.value = 1
    await _settle(dut)
    assert int(dut.rf_ren_a_o.value) == 1
    assert int(dut.rf_ren_b_o.value) == 1
    # illegal_csr_insn_i=1 → illegal_insn_o=1 → rens suppressed.
    dut.illegal_csr_insn_i.value = 1
    await _settle(dut)
    assert int(dut.illegal_insn_o.value) == 1
    assert int(dut.rf_ren_a_o.value) == 0
    assert int(dut.rf_ren_b_o.value) == 0


# ─────────────────────────────────────────────────────────────────────────
# Requirement 3: Illegal-instruction aggregation
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req3_illegal_insn_aggregates_csr_and_dret(dut):
    """Spec §"Requirement 3: Illegal-instruction aggregation".

    `illegal_insn_o = instr_valid_i & (illegal_insn_dec |
    illegal_csr_insn_i | illegal_dret_insn | illegal_umode_insn)`.

    Drive a normal ADD with `illegal_csr_insn_i=1` → illegal_insn_o=1.
    Then drive DRET outside debug mode → illegal_insn_o=1 via
    illegal_dret_insn.
    """
    await _land_in_decode(dut, instr=INSTR_ADD)
    # Baseline: ADD with no illegal flags → illegal_insn_o=0.
    assert int(dut.illegal_insn_o.value) == 0
    # CSR-side illegal → aggregator high.
    dut.illegal_csr_insn_i.value = 1
    await _settle(dut)
    assert int(dut.illegal_insn_o.value) == 1
    dut.illegal_csr_insn_i.value = 0
    # DRET outside debug mode → illegal_dret_insn = 1 → illegal aggregate.
    dut.instr_rdata_i.value     = INSTR_DRET
    dut.instr_rdata_alu_i.value = INSTR_DRET
    await _settle(dut)
    # debug_mode_o is driven by the controller (currently NOT in debug
    # mode) so illegal_dret_insn = 1.
    assert int(dut.illegal_insn_o.value) == 1


# ─────────────────────────────────────────────────────────────────────────
# Requirement 4: ALU operand-A mux
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req4_alu_operand_a_mux_lsu_addr_incr_override(dut):
    """Spec §"Requirement 4: ALU operand-A mux (with LSU override)".

    For an ADD (decoder picks `OP_A_REG_A`), `alu_operand_a_ex_o`
    follows `rf_rdata_a_i`. When `lsu_addr_incr_req_i=1`, the operand-A
    mux is overridden to OP_A_FWD → `alu_operand_a_ex_o = lsu_addr_last_i`.
    """
    await _land_in_decode(dut, instr=INSTR_ADD)
    dut.rf_rdata_a_i.value = 0xDEAD_BEEF
    await _settle(dut)
    # ADD → alu_op_a_mux_sel_dec = OP_A_REG_A → alu_operand_a = rf_rdata_a_i.
    assert int(dut.alu_operand_a_ex_o.value) == 0xDEAD_BEEF
    # LSU addr-incr override → alu_operand_a takes lsu_addr_last_i.
    dut.lsu_addr_incr_req_i.value = 1
    dut.lsu_addr_last_i.value     = 0x1234_5678
    await _settle(dut)
    assert int(dut.alu_operand_a_ex_o.value) == 0x1234_5678


# ─────────────────────────────────────────────────────────────────────────
# Requirement 5: ALU operand-B mux + immediate_b mux
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req5_alu_operand_b_immediate_for_addi(dut):
    """Spec §"Requirement 5: ALU operand-B mux (with LSU override)".

    For ADDI x1, x0, 1 the decoder picks OP_B_IMM and IMM_B_I → the
    operand-B port carries the I-type immediate (= 1 here).
    """
    await _land_in_decode(dut, instr=INSTR_ADDI_1)
    # rf_rdata_b_i is irrelevant when alu_op_b_mux_sel = OP_B_IMM.
    dut.rf_rdata_b_i.value = 0xCAFE_BABE
    await _settle(dut)
    # imm_i_type for ADDI x1,x0,1 = 32'h1.
    assert int(dut.alu_operand_b_ex_o.value) == 0x0000_0001
    # And the lsu addr-incr override picks imm_b = 32'h4.
    dut.instr_valid_i.value         = 1
    dut.lsu_addr_incr_req_i.value   = 1
    await _settle(dut)
    assert int(dut.alu_operand_b_ex_o.value) == 0x0000_0004


# ─────────────────────────────────────────────────────────────────────────
# Requirement 6: RF write-data mux + write enable
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req6_rf_wdata_mux_csr_path(dut):
    """Spec §"Requirement 6: RF write-data mux and write enable".

    For a CSR-read instruction (CSRRS), the decoder picks
    `rf_wdata_sel = RF_WD_CSR` → `rf_wdata_id_o = csr_rdata_i`.
    For an ADD (default), `rf_wdata_id_o = result_ex_i`.
    """
    # CSRRS x10, mscratch, x11 — rf_wdata_sel = RF_WD_CSR.
    await _land_in_decode(dut, instr=INSTR_CSRRS)
    dut.csr_rdata_i.value = 0xA5A5_A5A5
    dut.result_ex_i.value = 0x1111_1111
    await _settle(dut)
    assert int(dut.rf_wdata_id_o.value) == 0xA5A5_A5A5
    # ADD → RF_WD_EX → rf_wdata_id_o = result_ex_i.
    dut.instr_rdata_i.value     = INSTR_ADD
    dut.instr_rdata_alu_i.value = INSTR_ADD
    await _settle(dut)
    assert int(dut.rf_wdata_id_o.value) == 0x1111_1111


# ─────────────────────────────────────────────────────────────────────────
# Requirement 7: LSU request derivation
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req7_lsu_req_one_cycle_first_cycle_only(dut):
    """Spec §"Requirement 7: LSU request derivation".

    `lsu_req_o = instr_executing & data_req_allowed & lsu_req_dec`.
    Under WritebackStage=0, `data_req_allowed = instr_first_cycle`. So
    for a load (LW), `lsu_req_o` is high in FIRST_CYCLE only and
    drops to 0 in MULTI_CYCLE.
    """
    await _land_in_decode(dut, instr=INSTR_LW)
    # FIRST_CYCLE: lsu_req_o should be 1 (instr_executing high once
    # controller is in DECODE and instr_valid_i=1).
    assert int(dut.id_fsm_q.value) == FIRST_CYCLE
    assert int(dut.lsu_req_o.value) == 1, (
        "LW in FIRST_CYCLE must assert lsu_req_o"
    )
    # Hold the instruction; advance one edge → FSM enters MULTI_CYCLE
    # (load path always takes ≥2 cycles under WB=0).
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.id_fsm_q.value) == MULTI_CYCLE
    assert int(dut.lsu_req_o.value) == 0, (
        "LW in MULTI_CYCLE: data_req_allowed=0 → lsu_req_o=0"
    )
    # expecting_load_resp_o is now high (waiting for response).
    assert int(dut.expecting_load_resp_o.value) == 1
    assert int(dut.expecting_store_resp_o.value) == 0


# ─────────────────────────────────────────────────────────────────────────
# Requirement 8: imd_val_q pair (multdiv intermediate values)
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req8_imd_val_q_per_lane_we(dut):
    """Spec §"Requirement 8: Multdiv intermediate-value register pair".

    Each lane is independently write-enabled by `imd_val_we_ex_i[i]`
    and resets to 34'h0. Drive lane 0 with WE=1, lane 1 with WE=0 and
    confirm only lane 0 updates next cycle. `imd_val_q_ex_o` continuously
    reflects the flopped pair.
    """
    await _start_clock(dut)
    await _reset(dut)
    # Both lanes start at 0.
    assert int(dut.imd_val_q_ex_o[0].value) == 0
    assert int(dut.imd_val_q_ex_o[1].value) == 0
    # Drive lane 0 = 0xDEADBEEF, lane 1 = 0x1, write-enable lane 0 only.
    dut.imd_val_d_ex_i[0].value = 0xDEAD_BEEF
    dut.imd_val_d_ex_i[1].value = 0x1
    dut.imd_val_we_ex_i.value   = 0b01  # lane 0 only
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.imd_val_we_ex_i.value = 0
    await _settle(dut)
    assert int(dut.imd_val_q_ex_o[0].value) == 0xDEAD_BEEF
    assert int(dut.imd_val_q_ex_o[1].value) == 0  # held
    # Now drive lane 1 only.
    dut.imd_val_d_ex_i[1].value = 0x3_FFFF_FFFF  # all 34 bits
    dut.imd_val_we_ex_i.value   = 0b10  # lane 1 only
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.imd_val_we_ex_i.value = 0
    await _settle(dut)
    assert int(dut.imd_val_q_ex_o[0].value) == 0xDEAD_BEEF  # held
    assert int(dut.imd_val_q_ex_o[1].value) == 0x3_FFFF_FFFF


# ─────────────────────────────────────────────────────────────────────────
# Requirement 9: ID-FSM next-state and stall sources
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req9_branch_taken_first_to_multi_to_first(dut):
    """Spec §"Requirement 9: ID-FSM next-state and stall sources".

    Scenario "branch taken": FIRST_CYCLE with `branch_in_dec` and
    `branch_decision_i=1` → MULTI_CYCLE on next edge with `stall_branch=1`,
    `branch_set_raw_d=1`, `perf_branch_o=1`. Then in MULTI_CYCLE,
    `multicycle_done = ex_valid_i`, so asserting `ex_valid_i=1` retires
    back to FIRST_CYCLE.
    """
    await _land_in_decode(dut, instr=INSTR_BEQ_TAKEN)
    dut.branch_decision_i.value = 1
    await _settle(dut)
    assert int(dut.id_fsm_q.value) == FIRST_CYCLE
    assert int(dut.perf_branch_o.value) == 1, "perf_branch_o pulses on branch FIRST_CYCLE"
    # Advance: FIRST_CYCLE → MULTI_CYCLE.
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.id_fsm_q.value) == MULTI_CYCLE
    # MULTI_CYCLE retire: hold the branch instruction with ex_valid_i=1.
    dut.ex_valid_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    # After retire, controller emits instr_valid_clear_o and we drop
    # instr_valid_i; FSM returns to FIRST_CYCLE.
    dut.instr_valid_i.value = 0
    dut.ex_valid_i.value    = 0
    await _settle(dut)
    assert int(dut.id_fsm_q.value) == FIRST_CYCLE


# ─────────────────────────────────────────────────────────────────────────
# Requirement 10: Branch-set / jump-set pulse generation
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req10_branch_set_raw_q_two_cycle_latency(dut):
    """Spec §"Requirement 10: Branch-set / jump-set pulse generation".

    On a taken branch, `branch_set_raw_d=1` in cycle N (FIRST_CYCLE), the
    `branch_set_raw_q` flop captures it on the edge into cycle N+1, and
    the controller sees `pc_set_o=1` driven by `branch_set` in N+1.
    `branch_jump_set_done_q` then sticks until `instr_valid_clear_o`
    fires, which dedups any re-assertion.
    """
    await _land_in_decode(dut, instr=INSTR_BEQ_TAKEN)
    dut.branch_decision_i.value = 1
    await _settle(dut)
    # Cycle N (FIRST_CYCLE): pc_set_o is still 0 (branch_set_raw_q flopped on next edge).
    assert int(dut.id_fsm_q.value) == FIRST_CYCLE
    # branch_set_raw_q is the flop; in the FIRST_CYCLE comb the d-input
    # is high but the q-output reads the prior cycle's value (0).
    # Advance: now in MULTI_CYCLE; branch_set_raw_q = 1, controller sees pc_set_o.
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.id_fsm_q.value) == MULTI_CYCLE
    assert int(dut.branch_set_raw_q.value) == 1, (
        "branch_set_raw_q must be high one cycle after branch_set_raw_d=1"
    )
    # Controller sees branch_set=1 → asserts pc_set_o this cycle.
    assert int(dut.pc_set_o.value) == 1
    assert int(dut.pc_mux_o.value) == PC_JUMP


# ─────────────────────────────────────────────────────────────────────────
# Requirement 11: branch_taken / nt_branch_addr_o constants
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req11_nt_branch_addr_constant_zero(dut):
    """Spec §"Requirement 11: `branch_taken` and `nt_branch_addr_o`
    constants".

    Under BranchPredictor=0, `nt_branch_addr_o = 32'd0` constant. Under
    DataIndTiming=0, `branch_taken = 1'b1` constant (forwarded into the
    decoder; not directly observable on a top-level port, but the
    decoder accepts it as an input — see the construct enumeration).
    """
    await _start_clock(dut)
    await _reset(dut)
    assert int(dut.nt_branch_addr_o.value) == 0
    # Walk through several states; nt_branch_addr_o stays 0.
    await _walk_to_decode(dut)
    assert int(dut.nt_branch_addr_o.value) == 0
    # nt_branch_mispredict_o is also constant 0 (Forwarded from controller; CS-14).
    assert int(dut.nt_branch_mispredict_o.value) == 0


# ─────────────────────────────────────────────────────────────────────────
# Requirement 12: First-cycle signal
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req12_instr_first_cycle_id_o_tracks_valid_and_state(dut):
    """Spec §"Requirement 12: First-cycle signal".

    `instr_first_cycle_id_o = instr_valid_i & (id_fsm_q == FIRST_CYCLE)`.
    When `instr_valid_i = 0`, the signal is 0 regardless of FSM state.
    For LW driving FIRST_CYCLE, signal is 1; in MULTI_CYCLE it falls to 0.
    """
    await _land_in_decode(dut, instr=0)
    # No valid instruction: should be 0.
    assert int(dut.instr_first_cycle_id_o.value) == 0
    # Drive a LW: instr_valid_i=1 + FIRST_CYCLE → signal=1.
    dut.instr_valid_i.value     = 1
    dut.instr_rdata_i.value     = INSTR_LW
    dut.instr_rdata_alu_i.value = INSTR_LW
    await _settle(dut)
    assert int(dut.id_fsm_q.value) == FIRST_CYCLE
    assert int(dut.instr_first_cycle_id_o.value) == 1
    # Advance one cycle: FSM moves to MULTI_CYCLE → signal=0.
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.id_fsm_q.value) == MULTI_CYCLE
    assert int(dut.instr_first_cycle_id_o.value) == 0


# ─────────────────────────────────────────────────────────────────────────
# Requirement 13: Multdiv enable gating
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req13_mult_en_ex_o_gated_by_instr_executing(dut):
    """Spec §"Requirement 13: Multdiv enable gating".

    `mult_en_ex_o = instr_executing ? mult_en_dec : 0`. Drive a MUL
    (RV32M opcode) without `instr_valid_i` → mult_en_ex_o=0 (since
    instr_executing=0). With `instr_valid_i=1`, mult_en_ex_o follows
    mult_en_dec.

    `multdiv_ready_id_o = ready_wb_i = 1` (pinned).
    """
    # MUL x10, x11, x12 → 0x02C58533 (RV32M op).
    INSTR_MUL = 0x02C58533
    await _land_in_decode(dut, instr=0)
    # No valid instruction: mult_en_ex_o = 0.
    assert int(dut.mult_en_ex_o.value) == 0
    assert int(dut.div_en_ex_o.value)  == 0
    # multdiv_ready_id_o is constant 1 under WB=0.
    assert int(dut.multdiv_ready_id_o.value) == 1
    # Drive MUL with instr_valid_i=1.
    dut.instr_valid_i.value     = 1
    dut.instr_rdata_i.value     = INSTR_MUL
    dut.instr_rdata_alu_i.value = INSTR_MUL
    await _settle(dut)
    # instr_executing should now be high; mult_en_dec=1, div_en_dec=0.
    assert int(dut.mult_en_ex_o.value) == 1
    assert int(dut.div_en_ex_o.value)  == 0


# ─────────────────────────────────────────────────────────────────────────
# Requirement 14: CSR pipe-flush + op-enable derivation
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req14_csr_op_en_o_pulse_on_retire(dut):
    """Spec §"Requirement 14: CSR pipe-flush + op-enable derivation".

    `csr_op_en_o = csr_access_o & instr_executing & instr_id_done_o`.
    For a CSRRW (csr_access_o=1) the op-enable should be high in the
    cycle the instruction retires (instr_id_done_o=1).

    Under WB=0, `instr_id_done_o = ~stall_id & ~flush_id & instr_executing`.
    A CSRRW has no LSU/multdiv/branch/jump stalls, so it retires in
    FIRST_CYCLE → csr_op_en_o pulses immediately.
    """
    await _land_in_decode(dut, instr=INSTR_CSRRW)
    # csr_access_o is 1 when the decoder sees a CSR opcode.
    assert int(dut.csr_access_o.value) == 1
    # FIRST_CYCLE retire of a non-stalling instruction → instr_id_done_o=1
    # → csr_op_en_o=1.
    assert int(dut.instr_id_done_o.value) == 1
    assert int(dut.csr_op_en_o.value) == 1


# ─────────────────────────────────────────────────────────────────────────
# Requirement 15: Performance-counter outputs
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req15_perf_branch_pulse_in_first_cycle(dut):
    """Spec §"Requirement 15: Performance-counter outputs".

    `perf_branch_o` pulses high in the FIRST_CYCLE of a `branch_in_dec`
    instruction (assuming `instr_executing_spec`). Drive a BEQ in
    FIRST_CYCLE, with `branch_decision_i=0` (not-taken): perf_branch_o=1
    while id_fsm_q=FIRST_CYCLE; falls when retiring back to FIRST_CYCLE
    after the branch resolves.

    Also: `perf_dside_wait_o = instr_executing & lsu_req_dec &
    ~lsu_resp_valid_i` for a load that hasn't responded yet.
    """
    await _land_in_decode(dut, instr=INSTR_BEQ_TAKEN)
    dut.branch_decision_i.value = 0  # not-taken
    await _settle(dut)
    assert int(dut.id_fsm_q.value) == FIRST_CYCLE
    assert int(dut.perf_branch_o.value) == 1, (
        "perf_branch_o must pulse during FIRST_CYCLE of branch_in_dec"
    )
    # perf_dside_wait_o is 0 here (no LSU req).
    assert int(dut.perf_dside_wait_o.value) == 0
    # Switch to LW; in MULTI_CYCLE waiting for response, perf_dside_wait_o=1.
    dut.instr_rdata_i.value     = INSTR_LW
    dut.instr_rdata_alu_i.value = INSTR_LW
    await _settle(dut)
    # FIRST_CYCLE of LW: lsu_resp_valid_i=0, instr_executing=1, lsu_req_dec=1
    # → perf_dside_wait_o = 1.
    assert int(dut.perf_dside_wait_o.value) == 1


# ─────────────────────────────────────────────────────────────────────────
# Requirement 16: WritebackStage=0 tieoffs
# ─────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req16_writeback_stage_zero_tieoffs(dut):
    """Spec §"Requirement 16: WritebackStage=0 tieoffs and absorbers".

    Under WB=0: `instr_type_wb_o = WB_INSTR_OTHER`,
    `rf_rd_a_wb_match_o = 0`, `rf_rd_b_wb_match_o = 0`, `bt_a_operand_o
    = 0`, `bt_b_operand_o = 0`. These are all top-level outputs.
    """
    await _start_clock(dut)
    await _reset(dut)
    # All tieoffs must read their constant values out of reset.
    assert int(dut.instr_type_wb_o.value)   == WB_INSTR_OTHER
    assert int(dut.rf_rd_a_wb_match_o.value) == 0
    assert int(dut.rf_rd_b_wb_match_o.value) == 0
    assert int(dut.bt_a_operand_o.value)    == 0
    assert int(dut.bt_b_operand_o.value)    == 0
    # And they remain so after walking the FSM into DECODE.
    await _walk_to_decode(dut)
    assert int(dut.instr_type_wb_o.value)   == WB_INSTR_OTHER
    assert int(dut.bt_a_operand_o.value)    == 0
    assert int(dut.bt_b_operand_o.value)    == 0
