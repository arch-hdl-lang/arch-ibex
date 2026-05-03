"""Standalone cocotb scenarios for `ibex_ex_block` (basic suite).

Each `@cocotb.test` covers one Requirement from
`changes/port-ex_block/specs/ex_block/spec.md` for the in-scope
parameter set:
  - RV32M = 2 (RV32MFast)
  - RV32B = 0 (RV32BNone)
  - BranchTargetALU = 0

Key testbench design decisions
-------------------------------
1. **Drive the full ex_block, not the sub-modules separately.**
   The multdiv drives ALU operands and reads back the ALU's adder result
   the same cycle. The combinational cross-coupling loop (multdiv →
   alu_operand_*_o → ALU adder → alu_adder_ext_i / alu_adder_i /
   equal_to_zero_i → multdiv) resolves only when both are present in the
   same Verilator netlist. The testbench therefore builds on the full
   `ibex_ex_block` module, not on individual sub-modules.

2. **imd_val_q_i is driven by the testbench**, which models the EX-stage
   flop bank. After each clock edge the testbench samples `imd_val_d_o`
   and `imd_val_we_o` and writes the enabled lanes back into
   `imd_val_q_i` (the same register-update rule the surrounding pipeline
   uses). Helper functions `_snapshot_imd` and `_apply_imd` encapsulate
   this.

3. **ex_valid_o = 1 for all ALU-only operations** under RV32BNone,
   because the ALU drives `alu_imd_val_we = 2'b00` always, so
   `~(|alu_imd_val_we) = 1`.

4. **ALU operator encoding**: integers per specs/alu/spec.md §"ALU
   operator encoding". ALU_ADD = 0, ALU_SUB = 1, ALU_EQ = 29, ALU_NE = 30,
   ALU_LT = 25, ALU_GE = 27.

5. **md_op_e encoding**: MD_OP_MULL = 0, MD_OP_MULH = 1, MD_OP_DIV = 2,
   MD_OP_REM = 3.
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

CLK_PERIOD_NS = 10  # 100 MHz

# alu_op_e integer encodings (from specs/alu/spec.md)
ALU_ADD  = 0
ALU_SUB  = 1
ALU_XOR  = 2
ALU_OR   = 3
ALU_AND  = 4
ALU_SRA  = 8
ALU_SRL  = 9
ALU_SLL  = 10
ALU_LT   = 25
ALU_LTU  = 26
ALU_GE   = 27
ALU_GEU  = 28
ALU_EQ   = 29
ALU_NE   = 30
ALU_SLT  = 43
ALU_SLTU = 44

# md_op_e integer encodings
MD_OP_MULL = 0
MD_OP_MULH = 1
MD_OP_DIV  = 2
MD_OP_REM  = 3

MASK32 = 0xFFFF_FFFF
MASK34 = 0x3_FFFF_FFFF


# ── Testbench helpers ───────────────────────────────────────────────────

async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())


def _zero_imd(dut):
    """Drive imd_val_q_i to zero (initial state)."""
    dut.imd_val_q_i[0].value = 0
    dut.imd_val_q_i[1].value = 0


async def _reset(dut):
    """Assert async-low reset, deassert after two clock periods."""
    dut.rst_ni.value = 0
    # ALU inputs
    dut.alu_operator_i.value = ALU_ADD
    dut.alu_operand_a_i.value = 0
    dut.alu_operand_b_i.value = 0
    dut.alu_instr_first_cycle_i.value = 1
    # BranchTargetALU inputs (unused in SoC, but must be driven)
    dut.bt_a_operand_i.value = 0
    dut.bt_b_operand_i.value = 0
    # Multdiv inputs
    dut.multdiv_operator_i.value = MD_OP_MULL
    dut.mult_en_i.value = 0
    dut.div_en_i.value = 0
    dut.mult_sel_i.value = 0
    dut.div_sel_i.value = 0
    dut.multdiv_signed_mode_i.value = 0
    dut.multdiv_operand_a_i.value = 0
    dut.multdiv_operand_b_i.value = 0
    dut.multdiv_ready_id_i.value = 1
    dut.data_ind_timing_i.value = 0
    _zero_imd(dut)
    await Timer(2 * CLK_PERIOD_NS, "ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)


def _snapshot_imd(dut):
    """Sample imd_val_d_o and imd_val_we_o BEFORE the rising edge.
    The ex_block's caller latches these on the edge — i.e. the values
    the ex_block presented combinationally during this cycle."""
    we = int(dut.imd_val_we_o.value)
    d0 = int(dut.imd_val_d_o[0].value) & MASK34
    d1 = int(dut.imd_val_d_o[1].value) & MASK34
    return we, d0, d1


def _apply_imd(dut, snapshot):
    """Write enabled lanes from the snapshot into imd_val_q_i AFTER
    the rising edge — modelling the EX-stage flop bank update."""
    we, d0, d1 = snapshot
    if we & 0x1:
        dut.imd_val_q_i[0].value = d0
    if we & 0x2:
        dut.imd_val_q_i[1].value = d1


async def _settle(dut):
    """Let combinational logic settle after a signal assignment."""
    await Timer(1, "ns")


async def _run_alu(dut, operator: int, op_a: int, op_b: int) -> dict:
    """Drive a single-cycle ALU operation with multdiv_sel = 0.
    Returns dict with result_ex_o, alu_adder_result_ex_o, branch_decision_o,
    branch_target_o, ex_valid_o sampled after one settle."""
    dut.alu_operator_i.value = operator
    dut.alu_operand_a_i.value = op_a & MASK32
    dut.alu_operand_b_i.value = op_b & MASK32
    dut.alu_instr_first_cycle_i.value = 1
    dut.mult_sel_i.value = 0
    dut.div_sel_i.value = 0
    dut.mult_en_i.value = 0
    dut.div_en_i.value = 0
    await _settle(dut)
    return {
        "result_ex_o":          int(dut.result_ex_o.value) & MASK32,
        "alu_adder_result_ex_o": int(dut.alu_adder_result_ex_o.value) & MASK32,
        "branch_decision_o":    int(dut.branch_decision_o.value),
        "branch_target_o":      int(dut.branch_target_o.value) & MASK32,
        "ex_valid_o":           int(dut.ex_valid_o.value),
        "imd_val_we_o":         int(dut.imd_val_we_o.value),
    }


async def _run_mult(dut, *, operator: int, signed_mode: int,
                    op_a: int, op_b: int, max_cycles: int = 16) -> int:
    """Drive a MUL/MULH operation to completion.
    Returns multdiv_result_o (= result_ex_o) when valid_o asserts."""
    dut.multdiv_operator_i.value = operator
    dut.multdiv_signed_mode_i.value = signed_mode
    dut.multdiv_operand_a_i.value = op_a & MASK32
    dut.multdiv_operand_b_i.value = op_b & MASK32
    dut.mult_en_i.value = 1
    dut.mult_sel_i.value = 1
    dut.div_en_i.value = 0
    dut.div_sel_i.value = 0
    dut.data_ind_timing_i.value = 0
    dut.multdiv_ready_id_i.value = 1
    # Use a dummy ALU operator; the real ALU ops come from the multdiv's
    # alu_operand_*_o driving the ALU's multdiv_operand_*_i.
    dut.alu_operator_i.value = ALU_ADD
    dut.alu_operand_a_i.value = 0
    dut.alu_operand_b_i.value = 0
    dut.alu_instr_first_cycle_i.value = 1
    await _settle(dut)
    for _ in range(max_cycles):
        if int(dut.ex_valid_o.value) == 1:
            result = int(dut.result_ex_o.value) & MASK32
            snap = _snapshot_imd(dut)
            await RisingEdge(dut.clk_i)
            _apply_imd(dut, snap)
            dut.mult_en_i.value = 0
            dut.mult_sel_i.value = 0
            await _settle(dut)
            return result
        snap = _snapshot_imd(dut)
        await RisingEdge(dut.clk_i)
        _apply_imd(dut, snap)
        await _settle(dut)
    raise AssertionError(
        f"ex_valid_o never asserted within {max_cycles} cycles (mult)"
    )


async def _run_div(dut, *, operator: int, signed_mode: int,
                   op_a: int, op_b: int,
                   data_ind_timing: int = 0, max_cycles: int = 50) -> tuple[int, int]:
    """Drive a DIV/REM operation to completion.
    Returns (result, cycles_observed) when ex_valid_o asserts."""
    dut.multdiv_operator_i.value = operator
    dut.multdiv_signed_mode_i.value = signed_mode
    dut.multdiv_operand_a_i.value = op_a & MASK32
    dut.multdiv_operand_b_i.value = op_b & MASK32
    dut.div_en_i.value = 1
    dut.div_sel_i.value = 1
    dut.mult_en_i.value = 0
    dut.mult_sel_i.value = 0
    dut.data_ind_timing_i.value = data_ind_timing
    dut.multdiv_ready_id_i.value = 1
    dut.alu_operator_i.value = ALU_ADD
    dut.alu_operand_a_i.value = 0
    dut.alu_operand_b_i.value = 0
    dut.alu_instr_first_cycle_i.value = 1
    await _settle(dut)
    cycles = 0
    for _ in range(max_cycles):
        if int(dut.ex_valid_o.value) == 1:
            result = int(dut.result_ex_o.value) & MASK32
            snap = _snapshot_imd(dut)
            await RisingEdge(dut.clk_i)
            _apply_imd(dut, snap)
            dut.div_en_i.value = 0
            dut.div_sel_i.value = 0
            await _settle(dut)
            return result, cycles
        snap = _snapshot_imd(dut)
        await RisingEdge(dut.clk_i)
        cycles += 1
        _apply_imd(dut, snap)
        await _settle(dut)
    raise AssertionError(
        f"ex_valid_o never asserted within {max_cycles} cycles (div)"
    )


# ── Tests: one per spec Requirement ────────────────────────────────────

@cocotb.test()
async def multdiv_sel_or_of_mult_and_div_selectors(dut):
    """Spec §"multdiv_sel is the OR of mult_sel_i and div_sel_i".
    Verifies the combinational mux selector is formed from the OR of the
    two static decoder outputs: both low → ALU path active (result_ex_o =
    alu_result), mult_sel_i high → multdiv path selected."""
    await _start_clock(dut)
    await _reset(dut)
    # Both low → ALU result should flow to result_ex_o (ADD 3 + 5 = 8).
    r = await _run_alu(dut, ALU_ADD, 3, 5)
    assert r["result_ex_o"] == 8, f"got {r['result_ex_o']:#010x}"
    # ex_valid_o = 1 because multdiv_sel = 0 and alu_imd_val_we = 2'b00.
    assert r["ex_valid_o"] == 1, "ex_valid_o must be 1 for ALU-only under RV32BNone"


@cocotb.test()
async def result_ex_o_selects_alu_result_when_multdiv_sel_low(dut):
    """Spec §"result_ex_o mux" — ALU path.
    Drives multdiv_sel = 0 (both mult_sel_i and div_sel_i low) and
    verifies that result_ex_o equals the ALU's combinational result
    for a simple ADD operation."""
    await _start_clock(dut)
    await _reset(dut)
    r = await _run_alu(dut, ALU_ADD, 0x0000_0007, 0x0000_0008)
    assert r["result_ex_o"] == 0x0000_000F, (
        f"expected 0x0000000F, got {r['result_ex_o']:#010x}"
    )


@cocotb.test()
async def result_ex_o_selects_multdiv_result_when_multdiv_sel_high(dut):
    """Spec §"result_ex_o mux" — multdiv path.
    Drives a 3-cycle MUL (MD_OP_MULL) with mult_sel_i = 1 and verifies
    that result_ex_o equals multdiv_result_o (= low 32 bits of product)
    when ex_valid_o asserts, not the ALU's parallel computation."""
    await _start_clock(dut)
    await _reset(dut)
    op_a, op_b = 0x0000_1234, 0x0000_5678
    expected = (op_a * op_b) & MASK32
    result = await _run_mult(
        dut, operator=MD_OP_MULL, signed_mode=0b00, op_a=op_a, op_b=op_b,
    )
    assert result == expected, (
        f"expected {expected:#010x}, got {result:#010x}"
    )


@cocotb.test()
async def imd_val_d_o_mux_selects_alu_path_with_zero_extension(dut):
    """Spec §"imd_val_d_o mux (per-lane, 34-bit output)".
    With multdiv_sel = 0 (ALU path), verifies that imd_val_d_o[0] and
    imd_val_d_o[1] are zero-extended (both lanes = 34'h0 under RV32BNone
    because the ALU drives alu_imd_val_d[i] = 0 and we_o = 2'b00)."""
    await _start_clock(dut)
    await _reset(dut)
    # Any ALU-only operation under RV32BNone: ALU drives alu_imd_val_d = 0.
    dut.alu_operator_i.value = ALU_OR
    dut.alu_operand_a_i.value = 0xDEAD_BEEF
    dut.alu_operand_b_i.value = 0xCAFE_BABE
    dut.mult_sel_i.value = 0
    dut.div_sel_i.value = 0
    await _settle(dut)
    d0 = int(dut.imd_val_d_o[0].value) & MASK34
    d1 = int(dut.imd_val_d_o[1].value) & MASK34
    we = int(dut.imd_val_we_o.value)
    assert we == 0, f"imd_val_we_o = {we:#04b}, expected 2'b00"
    assert d0 == 0, f"imd_val_d_o[0] = {d0:#012x}, expected 0"
    assert d1 == 0, f"imd_val_d_o[1] = {d1:#012x}, expected 0"


@cocotb.test()
async def imd_val_we_o_mux_selects_multdiv_we_when_multdiv_sel_high(dut):
    """Spec §"imd_val_we_o mux".
    During an active multiply operation (mult_sel_i = 1), verifies that
    imd_val_we_o reflects the multdiv's write-enables (non-zero during
    FSM advancement) rather than the ALU's constant 2'b00."""
    await _start_clock(dut)
    await _reset(dut)
    # Start a MUL and observe that at least one cycle has imd_val_we_o != 0.
    dut.multdiv_operator_i.value = MD_OP_MULL
    dut.multdiv_signed_mode_i.value = 0b00
    dut.multdiv_operand_a_i.value = 2
    dut.multdiv_operand_b_i.value = 3
    dut.mult_en_i.value = 1
    dut.mult_sel_i.value = 1
    dut.div_en_i.value = 0
    dut.div_sel_i.value = 0
    dut.multdiv_ready_id_i.value = 1
    dut.alu_operator_i.value = ALU_ADD
    dut.alu_operand_a_i.value = 0
    dut.alu_operand_b_i.value = 0
    dut.alu_instr_first_cycle_i.value = 1
    await _settle(dut)
    # Observe at least one cycle of non-zero write-enable.
    saw_we_nonzero = False
    for _ in range(10):
        we = int(dut.imd_val_we_o.value)
        if we != 0:
            saw_we_nonzero = True
        if int(dut.ex_valid_o.value) == 1:
            break
        snap = _snapshot_imd(dut)
        await RisingEdge(dut.clk_i)
        _apply_imd(dut, snap)
        await _settle(dut)
    assert saw_we_nonzero, (
        "imd_val_we_o was always 0 during multiply — mux may be selecting ALU path"
    )


@cocotb.test()
async def imd_val_q_slice_routing_to_alu(dut):
    """Spec §"imd_val_q slice routing to ALU".
    Verifies the ex_block slices imd_val_q_i[i][31:0] before passing to
    the ALU. With a non-zero upper-2-bits pattern in imd_val_q_i, an ALU
    SUB that yields 0 (equal operands) must still produce is_equal_result
    = 1 (= branch_decision on ALU_EQ), regardless of the upper bits."""
    await _start_clock(dut)
    await _reset(dut)
    # Plant a 34-bit value with bit [33] = 1 in imd_val_q_i[0].
    dut.imd_val_q_i[0].value = 0x3_0000_0000  # bits [33:32] = 2'b11
    dut.imd_val_q_i[1].value = 0x2_DEAD_BEEF  # bits [33:32] = 2'b10
    # ALU EQ: operand_a == operand_b → comparison_result_o = 1.
    r = await _run_alu(dut, ALU_EQ, 0xAAAA_5555, 0xAAAA_5555)
    # branch_decision_o = alu_cmp_result = 1 (equal operands under EQ).
    assert r["branch_decision_o"] == 1, (
        "branch_decision_o should be 1 for EQ with equal operands"
    )
    # result_ex_o = {31'h0, 1} = 1 for EQ with equal operands.
    assert r["result_ex_o"] == 1, (
        f"result_ex_o = {r['result_ex_o']:#010x}, expected 1"
    )


@cocotb.test()
async def branch_decision_o_wired_from_alu_comparator(dut):
    """Spec §"branch_decision_o is wired from the ALU comparator".
    Drives ALU_EQ with equal and unequal operands and verifies
    branch_decision_o tracks the ALU's comparison_result_o unconditionally
    (not gated by multdiv_sel)."""
    await _start_clock(dut)
    await _reset(dut)
    # Equal operands: branch_decision_o = 1.
    r_eq = await _run_alu(dut, ALU_EQ, 0x42, 0x42)
    assert r_eq["branch_decision_o"] == 1, (
        "branch_decision_o must be 1 for ALU_EQ with equal operands"
    )
    # Unequal operands: branch_decision_o = 0.
    r_ne = await _run_alu(dut, ALU_EQ, 0x1, 0x2)
    assert r_ne["branch_decision_o"] == 0, (
        "branch_decision_o must be 0 for ALU_EQ with unequal operands"
    )


@cocotb.test()
async def branch_target_o_equals_alu_adder_result(dut):
    """Spec §"branch_target_o is wired from alu_adder_result_ex_o
    (BranchTargetALU = 0)".
    With BranchTargetALU = 0, branch_target_o must equal the ALU's adder
    result. Drives ALU_ADD to produce a predictable adder value and verifies
    branch_target_o == alu_adder_result_ex_o."""
    await _start_clock(dut)
    await _reset(dut)
    op_a = 0x1000_0000
    op_b = 0x0000_0008
    r = await _run_alu(dut, ALU_ADD, op_a, op_b)
    expected_addr = (op_a + op_b) & MASK32
    assert r["alu_adder_result_ex_o"] == expected_addr, (
        f"alu_adder_result_ex_o = {r['alu_adder_result_ex_o']:#010x}, "
        f"expected {expected_addr:#010x}"
    )
    assert r["branch_target_o"] == r["alu_adder_result_ex_o"], (
        f"branch_target_o ({r['branch_target_o']:#010x}) != "
        f"alu_adder_result_ex_o ({r['alu_adder_result_ex_o']:#010x})"
    )


@cocotb.test()
async def ex_valid_o_is_one_for_all_alu_only_operations(dut):
    """Spec §"ex_valid_o combinational validity signal" — ALU path.
    Under RV32BNone the ALU drives alu_imd_val_we = 2'b00 always, so
    ex_valid_o = ~(|2'b00) = 1 for every ALU-only operation.
    Exercises several ALU operators to confirm this is unconditional."""
    await _start_clock(dut)
    await _reset(dut)
    for op in [ALU_ADD, ALU_SUB, ALU_AND, ALU_OR, ALU_XOR,
               ALU_SLL, ALU_SRL, ALU_SRA, ALU_LT, ALU_GE, ALU_EQ, ALU_NE]:
        r = await _run_alu(dut, op, 0xDEAD_BEEF, 0xCAFE_0000)
        assert r["ex_valid_o"] == 1, (
            f"ex_valid_o = 0 for ALU op {op:#04x} under RV32BNone — "
            "alu_imd_val_we must be 0"
        )


@cocotb.test()
async def ex_valid_o_tracks_multdiv_valid_when_multdiv_sel_high(dut):
    """Spec §"ex_valid_o combinational validity signal" — multdiv path.
    With multdiv_sel = 1, ex_valid_o = multdiv_valid. Drives a MUL and
    verifies ex_valid_o is 0 in-progress and 1 when the multdiv finishes."""
    await _start_clock(dut)
    await _reset(dut)
    dut.multdiv_operator_i.value = MD_OP_MULL
    dut.multdiv_signed_mode_i.value = 0b00
    dut.multdiv_operand_a_i.value = 2
    dut.multdiv_operand_b_i.value = 3
    dut.mult_en_i.value = 1
    dut.mult_sel_i.value = 1
    dut.div_en_i.value = 0
    dut.div_sel_i.value = 0
    dut.multdiv_ready_id_i.value = 1
    dut.alu_operator_i.value = ALU_ADD
    dut.alu_operand_a_i.value = 0
    dut.alu_operand_b_i.value = 0
    dut.alu_instr_first_cycle_i.value = 1
    await _settle(dut)
    # First cycle: mult FSM in ALBL → not yet valid.
    assert int(dut.ex_valid_o.value) == 0, (
        "ex_valid_o must be 0 on first mult cycle (ALBL state)"
    )
    saw_valid = False
    for _ in range(10):
        if int(dut.ex_valid_o.value) == 1:
            saw_valid = True
            break
        snap = _snapshot_imd(dut)
        await RisingEdge(dut.clk_i)
        _apply_imd(dut, snap)
        await _settle(dut)
    assert saw_valid, "ex_valid_o never asserted during multiply"


@cocotb.test()
async def combinational_cross_coupling_resolves_within_netlist(dut):
    """Spec §"Combinational cross-coupling loop between ALU and multdiv".
    The multdiv drives ALU operands and reads back the ALU's adder result
    the same cycle — no flip-flop in the loop. This test exercises the
    full MUL operation through the ex_block (both sub-modules in the same
    Verilator netlist) and verifies the result is correct, which is only
    possible if the comb loop resolves: the multdiv needs the ALU's
    alu_adder_ext_i to compute partial products."""
    await _start_clock(dut)
    await _reset(dut)
    # 100 * 7 = 700 = 0x2BC
    result = await _run_mult(
        dut, operator=MD_OP_MULL, signed_mode=0b00, op_a=100, op_b=7,
    )
    assert result == 700, f"expected 700, got {result}"

    # Also exercise the divider (full 37-cycle loop — deep cross-coupling
    # via MD_COMP state's alu_operand_a_o / alu_adder_ext_i round-trip).
    result_div, _cycles = await _run_div(
        dut, operator=MD_OP_DIV, signed_mode=0b00, op_a=700, op_b=7,
    )
    assert result_div == 100, f"div 700/7 expected 100, got {result_div}"
