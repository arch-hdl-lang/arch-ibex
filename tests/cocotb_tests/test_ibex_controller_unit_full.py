"""Full-regression cocotb suite for `ibex_controller`.

Walks every `#### Scenario:` from spec §"Requirements 1–12" plus FSM
state-transition edge cases. Re-uses the basic-suite tests plus a
small set of additional scenarios; the goal is broad regression
coverage, not exhaustive — many subtle priority interactions live
inside the FSM and would require a fully driven CSR/IRQ environment
that we don't have in a leaf-only testbench. Future work can add a
larger end-to-end suite once IbexCore is ported (Phase C).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

# Re-import all helpers + basic-suite tests by directly importing the basic module.
# This re-runs every basic test as part of the full regression too — small
# duplication is cheaper than refactoring helpers across two files at this scale.
from test_ibex_controller_unit import (  # noqa: F401
    _start_clock, _settle, _reset, _idle_inputs, _land_in_decode,
    _pack_exc_cause, _pack_irqs,
    S_RESET, S_BOOT_SET, S_WAIT_SLEEP, S_SLEEP, S_FIRST_FETCH, S_DECODE,
    S_FLUSH, S_IRQ_TAKEN, S_DBG_TAKEN_IF, S_DBG_TAKEN_ID,
    PC_BOOT, PC_JUMP, PC_EXC, PC_ERET, PC_DRET, PC_BP,
    EXC_PC_EXC, EXC_PC_IRQ, EXC_PC_DBD, EXC_PC_DBG_EXC,
    EXC_CAUSE_IRQ_NM, EXC_CAUSE_IRQ_EXTERNAL_M, EXC_CAUSE_IRQ_SOFTWARE_M,
    EXC_CAUSE_IRQ_TIMER_M,
    PRIV_LVL_M, PRIV_LVL_U, MASK32,
    req1_cold_reset_startup_sequence,
    req2_decode_plain_alu_instruction,
    req3_external_irq_priority_and_entry,
    req4_external_debug_req_enters_dbg_taken_if,
    req5_illegal_instruction_flushes,
    req6_wfi_then_irq_wake,
    req7_mret_return,
    req8_csr_save_strobes_only_in_their_states,
    req9_illegal_insn_latches_then_clears_in_flush,
    req10_debug_mode_q_sets_in_dbg_taken_if,
    req11_mfip_id_fast_irq_zero,
    req12_pc_mux_per_state_smoke,
)

# ──────────────────────────────────────────────────────────────────────
# Additional scenarios beyond the basic suite
# ──────────────────────────────────────────────────────────────────────


@cocotb.test()
async def req1_debug_request_before_first_instruction(dut):
    """Spec §Req 1, Scenario "Debug request before first instruction":
    FIRST_FETCH + debug_req_i=1 → DBG_TAKEN_IF on next edge.
    """
    await _start_clock(dut)
    await _reset(dut)
    # Walk to FIRST_FETCH. Post-reset clock phase varies, so guard-walk
    # rather than counting fixed edges (mirrors req1_cold).
    for _ in range(4):
        if int(dut.state_r.value) == S_FIRST_FETCH:
            break
        await RisingEdge(dut.clk_i)
        await _settle(dut)
    assert int(dut.state_r.value) == S_FIRST_FETCH
    dut.debug_req_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.state_r.value) == S_DBG_TAKEN_IF


@cocotb.test()
async def req3_nmi_takes_priority(dut):
    """Spec §Req 3 — NMI taken from DECODE has highest priority. Drive
    irq_nm_ext_i=1 with a fast IRQ also set; cause must be ExcCauseIrqNm.
    """
    await _land_in_decode(dut, instr_valid=0)
    dut.irq_nm_ext_i.value = 1
    dut.irq_pending_i.value = 1
    dut.irqs_i.value = _pack_irqs(irq_fast=0x1, irq_external=1)
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.state_r.value) == S_IRQ_TAKEN
    expected = _pack_exc_cause(irq_ext=1, lower_cause=EXC_CAUSE_IRQ_NM)
    assert int(dut.exc_cause_o.value) == expected


@cocotb.test()
async def req3_irq_ignored_in_debug_mode(dut):
    """Spec §Req 3 — IRQs ignored while debug_mode_q=1.
    Enter debug mode first, then assert irq_external; FSM stays in DECODE.
    """
    await _land_in_decode(dut, instr_valid=0)
    # Enter debug mode via debug_req_i.
    dut.debug_req_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.state_r.value) == S_DBG_TAKEN_IF
    await RisingEdge(dut.clk_i)
    dut.debug_req_i.value = 0
    await _settle(dut)
    assert int(dut.debug_mode_q.value) == 1
    assert int(dut.state_r.value) == S_DECODE
    # Now drive an external IRQ. It MUST NOT trigger IRQ_TAKEN.
    dut.irq_pending_i.value = 1
    dut.irqs_i.value = _pack_irqs(irq_external=1)
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.state_r.value) == S_DECODE, (
        "IRQ must be ignored in debug mode; FSM should stay in DECODE"
    )


@cocotb.test()
async def req5_load_access_fault_flushes(dut):
    """Spec §Req 5 — load_err_i pulse latches into load_err_q and triggers
    DECODE → FLUSH on the next cycle.
    """
    await _land_in_decode(dut, instr_valid=1)
    dut.load_err_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    dut.load_err_i.value = 0
    await _settle(dut)
    assert int(dut.state_r.value) == S_FLUSH
    assert int(dut.load_err_q.value) == 1
    assert int(dut.csr_save_cause_o.value) == 1


@cocotb.test()
async def req10_nmi_sets_then_mret_clears(dut):
    """Spec §Req 10 — NMI entry sets nmi_mode_q; MRET in NMI handler
    clears it.
    """
    await _land_in_decode(dut, instr_valid=0)
    # Enter NMI. The NMI line stays asserted across IRQ_TAKEN since the
    # `nmi_mode_q` latch fires from that state's seq block, which samples
    # the live irq_nm_ext_i.
    dut.irq_nm_ext_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    assert int(dut.state_r.value) == S_IRQ_TAKEN
    await RisingEdge(dut.clk_i)
    dut.irq_nm_ext_i.value = 0
    await _settle(dut)
    # Back in DECODE; nmi_mode_q is now 1.
    assert int(dut.state_r.value) == S_DECODE
    assert int(dut.nmi_mode_o.value) == 1
    # Drive MRET.
    dut.instr_valid_i.value = 1
    dut.mret_insn_i.value = 1
    await _settle(dut)
    await RisingEdge(dut.clk_i)
    await _settle(dut)
    # In FLUSH(mret); nmi_mode_d should be 0 → nmi_mode_q clears next edge.
    assert int(dut.state_r.value) == S_FLUSH
    await RisingEdge(dut.clk_i)
    dut.mret_insn_i.value = 0
    dut.instr_valid_i.value = 0
    await _settle(dut)
    assert int(dut.nmi_mode_o.value) == 0
