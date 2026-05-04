"""Standalone cocotb scenarios for `ibex_controller` (basic suite).

Each `@cocotb.test` covers one Requirement from
`changes/port-controller/specs/controller/spec.md`, walking the single
most representative scenario from that Requirement. Optimised for fast
feedback (target full-suite runtime ≤ 30 s).

In-scope SoC parameter pinning (per spec § "Pinned parameter values"):
  - WritebackStage  = 0
  - BranchPredictor = 0
  - MemECC          = 0

FSM state encoding (`ctrl_fsm_e` from `ibex_pkg.sv`, 4-bit):
  - RESET=0, BOOT_SET=1, WAIT_SLEEP=2, SLEEP=3, FIRST_FETCH=4,
    DECODE=5, FLUSH=6, IRQ_TAKEN=7, DBG_TAKEN_IF=8, DBG_TAKEN_ID=9.

PcSel / ExcPcSel encodings (`ibex_pkg.sv`):
  - PcSel:    PC_BOOT=0, PC_JUMP=1, PC_EXC=2, PC_ERET=3, PC_DRET=4, PC_BP=5.
  - ExcPcSel: EXC_PC_EXC=0, EXC_PC_IRQ=1, EXC_PC_DBD=2, EXC_PC_DBG_EXC=3.

`exc_cause` packed struct (7 bits): {irq_int[6], irq_ext[5], lower_cause[4:0]}.
`irqs_i` packed struct (18 bits): {irq_fast[17:3], irq_external[2], irq_timer[1], irq_software[0]}.
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

CLK_PERIOD_NS = 10  # 100 MHz

# FSM state encodings
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

# Privilege levels (PrivLvl, 2-bit)
PRIV_LVL_M = 3
PRIV_LVL_U = 0

# Exception cause encodings (lower_cause[4:0])
EXC_CAUSE_IRQ_NM         = 31
EXC_CAUSE_IRQ_EXTERNAL_M = 11
EXC_CAUSE_IRQ_SOFTWARE_M = 3
EXC_CAUSE_IRQ_TIMER_M    = 7
EXC_CAUSE_INSN_ADDR_MISA = 0  # default reset value

MASK32 = 0xFFFF_FFFF


def _pack_exc_cause(*, irq_int=0, irq_ext=0, lower_cause=0) -> int:
    """Pack ExcCause struct {irq_int, irq_ext, lower_cause[4:0]} into 7 bits."""
    return ((irq_int & 1) << 6) | ((irq_ext & 1) << 5) | (lower_cause & 0x1F)


def _pack_irqs(*, irq_software=0, irq_timer=0, irq_external=0, irq_fast=0) -> int:
    """Pack Irqs struct {irq_software, irq_timer, irq_external, irq_fast[14:0]}.
    SV packed struct puts the FIRST declared field at the high bits, so:
    bit 17 = irq_software, bit 16 = irq_timer, bit 15 = irq_external,
    bits [14:0] = irq_fast.
    """
    return ((irq_software & 1) << 17) | ((irq_timer & 1) << 16) | ((irq_external & 1) << 15) | (irq_fast & 0x7FFF)


async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())


async def _settle(dut):
    """Let combinational logic settle after a signal assignment."""
    await Timer(1, "ns")


def _idle_inputs(dut):
    """Drive every controller input to a benign idle baseline.

    All decoder/LSU/IRQ/debug flags low, valid-instruction inputs zero,
    privilege M-mode, no stalls. From this baseline the test layers in
    only the inputs the scenario cares about.
    """
    # Decoder flags
    dut.illegal_insn_i.value         = 0
    dut.ecall_insn_i.value           = 0
    dut.mret_insn_i.value            = 0
    dut.dret_insn_i.value            = 0
    dut.wfi_insn_i.value             = 0
    dut.ebrk_insn_i.value            = 0
    dut.csr_pipe_flush_i.value       = 0
    # ID stage instruction
    dut.instr_valid_i.value          = 0
    dut.instr_i.value                = 0
    dut.instr_compressed_i.value     = 0
    dut.instr_is_compressed_i.value  = 0
    dut.instr_bp_taken_i.value       = 0  # pinned 0
    dut.instr_fetch_err_i.value      = 0
    dut.instr_fetch_err_plus2_i.value = 0
    dut.pc_id_i.value                = 0
    dut.instr_exec_i.value           = 1
    # LSU
    dut.lsu_addr_last_i.value        = 0
    dut.load_err_i.value             = 0
    dut.store_err_i.value             = 0
    dut.mem_resp_intg_err_i.value    = 0
    # Branch / jump
    dut.branch_set_i.value           = 0
    dut.branch_not_set_i.value       = 0  # pinned 0
    dut.jump_set_i.value             = 0
    # CSR / IRQ
    dut.csr_mstatus_mie_i.value      = 1
    dut.irq_pending_i.value          = 0
    dut.irqs_i.value                 = _pack_irqs()
    dut.irq_nm_ext_i.value           = 0
    # Debug
    dut.debug_req_i.value            = 0
    dut.debug_single_step_i.value    = 0
    dut.debug_ebreakm_i.value        = 0
    dut.debug_ebreaku_i.value        = 0
    dut.trigger_match_i.value        = 0
    # Privilege
    dut.priv_mode_i.value            = PRIV_LVL_M
    # Stalls
    dut.stall_id_i.value             = 0
    dut.stall_wb_i.value             = 0  # pinned 0
    dut.ready_wb_i.value             = 1  # pinned 1


async def _reset(dut):
    """Apply async-low reset for two clock periods, then release. Inputs idle."""
    _idle_inputs(dut)
    dut.rst_ni.value = 0
    await Timer(2 * CLK_PERIOD_NS, "ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await _settle(dut)


async def _land_in_decode(dut, *, instr_valid: int = 0):
    """Walk the FSM from reset through RESET → BOOT_SET → FIRST_FETCH → DECODE.

    Returns when the FSM has been in DECODE for one full cycle. By
    default the ID stage is empty (`instr_valid_i = 0`); pass
    `instr_valid=1` to drive a held instruction.
    """
    await _start_clock(dut)
    await _reset(dut)
    # After reset the FSM starts in RESET (cycle 0). Each posedge advances
    # one state: RESET → BOOT_SET → FIRST_FETCH (then conditional on
    # id_in_ready_o, which is 1 by default in FIRST_FETCH).
    for _ in range(3):
        await RisingEdge(dut.clk_i)
    dut.instr_valid_i.value = instr_valid
    await _settle(dut)


# ──────────────────────────────────────────────────────────────────────
# Requirement 1: Reset → Boot → First-fetch startup sequence
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req1_cold_reset_startup_sequence(dut):
    """Spec §"Requirement 1" — Scenario "Cold reset". Validates the
    post-reset boot sequence reaches BOOT_SET then FIRST_FETCH on
    successive cycles, and that BOOT_SET drives instr_req_o + pc_set_o
    high while FIRST_FETCH drives instr_req_o high with pc_set_o low.

    The exact moment the FSM leaves RESET depends on cocotb's clock
    phase relative to the Timer-based reset; we don't assert that
    starting state, just the sequence after the first edge.
    """
    await _start_clock(dut)
    await _reset(dut)
    # Reset has just deasserted and one posedge has fired. State is
    # either still RESET or already in BOOT_SET depending on phase;
    # advance until we land in BOOT_SET.
    for _ in range(2):
        if int(dut.state_r.value) == S_BOOT_SET:
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert int(dut.state_r.value) == S_BOOT_SET
    assert int(dut.instr_req_o.value) == 1, "BOOT_SET drives instr_req_o high"
    assert int(dut.pc_mux_o.value) == PC_BOOT
    assert int(dut.pc_set_o.value) == 1
    # Advance to FIRST_FETCH.
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.state_r.value) == S_FIRST_FETCH
    assert int(dut.instr_req_o.value) == 1
    assert int(dut.pc_set_o.value) == 0
    # Throughout: ctrl_busy_o = 1.
    assert int(dut.ctrl_busy_o.value) == 1


# ──────────────────────────────────────────────────────────────────────
# Requirement 2: DECODE-state behavior + special-request gating
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req2_decode_plain_alu_instruction(dut):
    """Spec §"Requirement 2" — Scenario "Plain ALU instruction".
    DECODE with a valid simple instruction: pc_set_o=0, controller_run_o=1,
    instr_valid_clear_o=1, id_in_ready_o=1, next-state remains DECODE.
    """
    await _land_in_decode(dut, instr_valid=1)
    assert int(dut.state_r.value) == S_DECODE
    assert int(dut.controller_run_o.value) == 1, "DECODE asserts controller_run_o"
    assert int(dut.pc_set_o.value) == 0, "no branch → no pc_set_o"
    assert int(dut.id_in_ready_o.value) == 1
    assert int(dut.instr_valid_clear_o.value) == 1
    # pc_mux_o is PC_JUMP throughout DECODE (only sampled on pc_set_o pulse).
    assert int(dut.pc_mux_o.value) == PC_JUMP


# ──────────────────────────────────────────────────────────────────────
# Requirement 3: IRQ priority and entry sequence
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req3_external_irq_priority_and_entry(dut):
    """Spec §"Requirement 3" — external IRQ entry. DECODE with idle ID
    and irq_external pending → IRQ_TAKEN with exc_cause_o = ExcCauseIrqExternalM.
    """
    await _land_in_decode(dut, instr_valid=0)
    assert int(dut.state_r.value) == S_DECODE
    # Drive an external IRQ.
    dut.irq_pending_i.value = 1
    dut.irqs_i.value = _pack_irqs(irq_external=1)
    await _settle(dut)
    # Next cycle should be IRQ_TAKEN.
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.state_r.value) == S_IRQ_TAKEN
    assert int(dut.pc_mux_o.value) == PC_EXC
    assert int(dut.exc_pc_mux_o.value) == EXC_PC_IRQ
    assert int(dut.pc_set_o.value) == 1
    assert int(dut.csr_save_if_o.value) == 1
    assert int(dut.csr_save_cause_o.value) == 1
    # exc_cause = {irq_ext=1, irq_int=0, lower_cause=11}.
    expected = _pack_exc_cause(irq_ext=1, lower_cause=EXC_CAUSE_IRQ_EXTERNAL_M)
    assert int(dut.exc_cause_o.value) == expected, (
        f"got exc_cause_o={int(dut.exc_cause_o.value):#04x}, "
        f"expected {expected:#04x}"
    )


# ──────────────────────────────────────────────────────────────────────
# Requirement 4: Debug entry
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req4_external_debug_req_enters_dbg_taken_if(dut):
    """Spec §"Requirement 4" — Scenario "External debug_req on idle DECODE".
    DECODE, debug_req_i=1, no IRQ → DBG_TAKEN_IF with PC_EXC/EXC_PC_DBD,
    debug_csr_save_o=1, debug_mode_entering_o=1.
    """
    await _land_in_decode(dut, instr_valid=0)
    assert int(dut.state_r.value) == S_DECODE
    dut.debug_req_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.state_r.value) == S_DBG_TAKEN_IF
    assert int(dut.pc_mux_o.value) == PC_EXC
    assert int(dut.exc_pc_mux_o.value) == EXC_PC_DBD
    assert int(dut.pc_set_o.value) == 1
    assert int(dut.debug_csr_save_o.value) == 1
    assert int(dut.csr_save_if_o.value) == 1
    assert int(dut.debug_mode_entering_o.value) == 1


# ──────────────────────────────────────────────────────────────────────
# Requirement 5: Exception handling in FLUSH
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req5_illegal_instruction_flushes(dut):
    """Spec §"Requirement 5" — illegal-insn exception. Pulse illegal_insn_i
    in DECODE → FLUSH on next cycle with csr_save_cause_o=1, pc_mux=PC_EXC,
    exc_pc_mux=EXC_PC_EXC.
    """
    await _land_in_decode(dut, instr_valid=1)
    dut.illegal_insn_i.value = 1
    await _settle(dut)
    # Cycle N: DECODE with illegal_insn_d=1, special_req=1 → next FLUSH.
    await RisingEdge(dut.clk_i)
    # Drop illegal_insn_i (latched into illegal_insn_q).
    dut.illegal_insn_i.value = 0
    await _settle(dut)
    assert int(dut.state_r.value) == S_FLUSH, (
        f"expected FLUSH, got state={int(dut.state_r.value)}"
    )
    assert int(dut.illegal_insn_q.value) == 1
    assert int(dut.exc_req_q.value) == 1
    assert int(dut.csr_save_cause_o.value) == 1
    assert int(dut.pc_mux_o.value) == PC_EXC
    assert int(dut.exc_pc_mux_o.value) == EXC_PC_EXC
    assert int(dut.pc_set_o.value) == 1


# ──────────────────────────────────────────────────────────────────────
# Requirement 6: WFI / sleep cycle
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req6_wfi_then_irq_wake(dut):
    """Spec §"Requirement 6" — WFI then external IRQ wake.
    DECODE WFI → FLUSH → WAIT_SLEEP → SLEEP → (on IRQ) FIRST_FETCH.

    Note: wfi_insn_i and instr_valid_i must be held across the FLUSH
    cycle because retain_id keeps the ID-stage `instr_valid` latched
    in real Ibex; we model that here by not dropping the inputs until
    after the FLUSH→WAIT_SLEEP transition.
    """
    await _land_in_decode(dut, instr_valid=1)
    dut.wfi_insn_i.value = 1
    await _settle(dut)
    # DECODE → FLUSH (special_req); keep wfi_insn_i/instr_valid_i HIGH.
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.state_r.value) == S_FLUSH
    # FLUSH(wfi-only) → WAIT_SLEEP. Drop the wfi inputs after the
    # transition is committed.
    await RisingEdge(dut.clk_i)
    dut.wfi_insn_i.value = 0
    dut.instr_valid_i.value = 0
    await _settle(dut)
    assert int(dut.state_r.value) == S_WAIT_SLEEP
    assert int(dut.ctrl_busy_o.value) == 0  # core idle
    assert int(dut.instr_req_o.value) == 0
    # WAIT_SLEEP → SLEEP.
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.state_r.value) == S_SLEEP
    # Drive an IRQ to wake.
    dut.irq_pending_i.value = 1
    dut.irqs_i.value = _pack_irqs(irq_external=1)
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.state_r.value) == S_FIRST_FETCH


# ──────────────────────────────────────────────────────────────────────
# Requirement 7: MRET / DRET return
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req7_mret_return(dut):
    """Spec §"Requirement 7" — MRET in DECODE → FLUSH(mret) with
    csr_restore_mret_id_o=1 and pc_mux_o=PC_ERET.
    """
    await _land_in_decode(dut, instr_valid=1)
    dut.mret_insn_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.mret_insn_i.value = 0
    dut.instr_valid_i.value = 0
    await _settle(dut)
    assert int(dut.state_r.value) == S_FLUSH
    # In FLUSH (mret) the controller asserts the restore strobe and PC mux.
    # NOTE: mret_insn (= mret_insn_i & instr_valid_i) is COMBINATIONAL per
    # spec Req 9 — so by FLUSH cycle we need mret_insn_i high again with
    # a held valid instruction. Re-drive:
    dut.mret_insn_i.value = 1
    dut.instr_valid_i.value = 1
    await _settle(dut)
    assert int(dut.csr_restore_mret_id_o.value) == 1
    assert int(dut.pc_mux_o.value) == PC_ERET
    assert int(dut.pc_set_o.value) == 1


# ──────────────────────────────────────────────────────────────────────
# Requirement 8: csr_save_* output rules
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req8_csr_save_strobes_only_in_their_states(dut):
    """Spec §"Requirement 8" — csr_save matrix. In DECODE all save strobes
    are 0; csr_save_wb_o is constant 0 under WritebackStage=0.
    """
    await _land_in_decode(dut, instr_valid=0)
    assert int(dut.csr_save_if_o.value) == 0
    assert int(dut.csr_save_id_o.value) == 0
    assert int(dut.csr_save_wb_o.value) == 0
    assert int(dut.csr_save_cause_o.value) == 0
    assert int(dut.csr_restore_mret_id_o.value) == 0
    assert int(dut.csr_restore_dret_id_o.value) == 0
    assert int(dut.debug_csr_save_o.value) == 0


# ──────────────────────────────────────────────────────────────────────
# Requirement 9: Latched decoder/LSU state registers
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req9_illegal_insn_latches_then_clears_in_flush(dut):
    """Spec §"Requirement 9" — Scenario "Illegal instruction sample-and-flush".
    illegal_insn_q latches in DECODE, holds for the FLUSH cycle, clears on
    the FLUSH→DECODE return (because illegal_insn_d gates on
    `state_r != FLUSH`).
    """
    await _land_in_decode(dut, instr_valid=1)
    dut.illegal_insn_i.value = 1
    await _settle(dut)
    # DECODE: illegal_insn_d=1, transitioning to FLUSH on next edge.
    await RisingEdge(dut.clk_i)
    dut.illegal_insn_i.value = 0
    await _settle(dut)
    assert int(dut.state_r.value) == S_FLUSH
    assert int(dut.illegal_insn_q.value) == 1, "should hold during FLUSH"
    # Next edge: FLUSH → DECODE, illegal_insn_q clears.
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.illegal_insn_q.value) == 0, "should clear on FLUSH→DECODE"


# ──────────────────────────────────────────────────────────────────────
# Requirement 10: debug_mode_q and nmi_mode_q
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req10_debug_mode_q_sets_in_dbg_taken_if(dut):
    """Spec §"Requirement 10" — debug_mode_q. After DBG_TAKEN_IF, the
    debug_mode_q flop equals 1 (and stays 1 until DRET clears it).
    """
    await _land_in_decode(dut, instr_valid=0)
    dut.debug_req_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.state_r.value) == S_DBG_TAKEN_IF
    # Next edge: DBG_TAKEN_IF → DECODE, debug_mode_q latches to 1.
    await RisingEdge(dut.clk_i)
    dut.debug_req_i.value = 0
    await _settle(dut)
    assert int(dut.debug_mode_o.value) == 1
    assert int(dut.debug_mode_q.value) == 1


# ──────────────────────────────────────────────────────────────────────
# Requirement 11: mfip_id priority encoder
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req11_mfip_id_fast_irq_zero(dut):
    """Spec §"Requirement 11" — Scenario "fast IRQ 0 only". Single fast
    IRQ at index 0 → mfip_id=0, lower_cause=16 (ExcCauseIrqFast0).
    """
    await _land_in_decode(dut, instr_valid=0)
    dut.irq_pending_i.value = 1
    dut.irqs_i.value = _pack_irqs(irq_fast=1)  # bit 0 set
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    # IRQ_TAKEN — exc_cause_o = {irq_ext=1, irq_int=0, lower_cause={1'b1, mfip_id=0}}
    # = 5'b1_0000 = 5'd16.
    assert int(dut.state_r.value) == S_IRQ_TAKEN
    expected = _pack_exc_cause(irq_ext=1, lower_cause=16)
    assert int(dut.exc_cause_o.value) == expected, (
        f"got {int(dut.exc_cause_o.value):#04x}, expected {expected:#04x}"
    )


# ──────────────────────────────────────────────────────────────────────
# Requirement 12: pc_mux_o / exc_pc_mux_o driving rules per state
# ──────────────────────────────────────────────────────────────────────

@cocotb.test()
async def req12_pc_mux_per_state_smoke(dut):
    """Spec §"Requirement 12" — pc_mux_o per state. Smoke-check the four
    most distinctive PC_mux values across the state walk: PC_BOOT in
    RESET, PC_JUMP in DECODE, PC_EXC in IRQ_TAKEN. Also: nt_branch_mispredict_o
    is constant 0 under BranchPredictor=0.
    """
    await _start_clock(dut)
    await _reset(dut)
    # RESET: PC_BOOT.
    assert int(dut.pc_mux_o.value) == PC_BOOT
    assert int(dut.nt_branch_mispredict_o.value) == 0
    # Walk to DECODE.
    for _ in range(3):
        await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.state_r.value) == S_DECODE
    assert int(dut.pc_mux_o.value) == PC_JUMP
    assert int(dut.nt_branch_mispredict_o.value) == 0
    # Drive an IRQ to enter IRQ_TAKEN.
    dut.irq_pending_i.value = 1
    dut.irqs_i.value = _pack_irqs(irq_external=1)
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.state_r.value) == S_IRQ_TAKEN
    assert int(dut.pc_mux_o.value) == PC_EXC
    assert int(dut.exc_pc_mux_o.value) == EXC_PC_IRQ
