"""Standalone cocotb scenarios for `ibex_alu`.

Each `@cocotb.test` covers one Requirement from `specs/alu/spec.md`,
walking 1-3 of the spec's Given/When/Then scenarios with concrete
operand values. The ALU is purely combinational, so settling is just
`Timer(1, "ns")` after every input change.

Operator opcodes are pulled from the spec's Port contract, NOT from
ibex_pkg.sv, per the spec-first methodology. Decimal in the spec maps
to the 7-bit codes below.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer


# ── alu_op_e (RV32BNone scope) ─────────────────────────────────────────
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

# An RV32B-only operator (CLZ in upstream's enum). Used to verify that
# any out-of-scope opcode falls through to result_o = 0 without
# disturbing the unconditional adder/equality ports.
ALU_CLZ_RV32B_ONLY = 50


async def _drive(dut, *, imd_q0=0, imd_q1=0, **kw):
    """Apply inputs, settle combinationally."""
    defaults = dict(
        operator_i           = 0,
        operand_a_i          = 0,
        operand_b_i          = 0,
        instr_first_cycle_i  = 1,
        multdiv_operand_a_i  = 0,
        multdiv_operand_b_i  = 0,
        multdiv_sel_i        = 0,
    )
    defaults.update(kw)
    for name, val in defaults.items():
        getattr(dut, name).value = val
    # imd_val_q_i is a packed Vec<UInt<32>, 2>; lane 0 occupies bits [31:0],
    # lane 1 occupies bits [63:32]. Both cocotb-verilator and arch-sim
    # accept the whole-value setter (arch-com #265, fixed by adding
    # `.value` to `_ArchVecProxy`).
    dut.imd_val_q_i.value = ((imd_q1 & 0xFFFF_FFFF) << 32) | (imd_q0 & 0xFFFF_FFFF)
    await Timer(1, "ns")


@cocotb.test()
async def adder_unconditional(dut):
    """Spec §"Adder produces unconditional sum of operands A and B"."""
    # ADD path
    await _drive(dut, operator_i=ALU_ADD, operand_a_i=1, operand_b_i=2)
    assert int(dut.adder_result_o.value) == 0x0000_0003
    assert int(dut.result_o.value) == 0x0000_0003
    # Adder still produces the sum on a non-arithmetic operator (LSU
    # consumes adder_result_o regardless of operator_i).
    await _drive(dut, operator_i=ALU_OR, operand_a_i=0x1000_0000, operand_b_i=0x10)
    assert int(dut.adder_result_o.value) == 0x1000_0010


@cocotb.test()
async def subtract_via_twos_complement(dut):
    """Spec §"Subtraction and comparison operators drive the adder via two's-complement negation"."""
    # 5 - 3 = 2.
    await _drive(dut, operator_i=ALU_SUB, operand_a_i=5, operand_b_i=3)
    assert int(dut.adder_result_o.value) == 0x0000_0002
    assert int(dut.result_o.value) == 0x0000_0002
    # 0 - 1 wraps to 0xFFFF_FFFF.
    await _drive(dut, operator_i=ALU_SUB, operand_a_i=0, operand_b_i=1)
    assert int(dut.adder_result_o.value) == 0xFFFF_FFFF


@cocotb.test()
async def multdiv_mux_overrides_operands(dut):
    """Spec §"Multdiv mux on the shared adder" (Scenario: multdiv path
    overrides operand inputs). adder_result_o = sum[32:1] always — the
    multdiv unit pre-shifts operands when it wants the LSB-1 trick."""
    await _drive(
        dut,
        operator_i=ALU_ADD,
        operand_a_i=0xDEAD_BEEF,            # ignored under multdiv_sel
        operand_b_i=0xCAFE_BABE,            # ignored under multdiv_sel
        multdiv_sel_i=1,
        multdiv_operand_a_i=0x0A,
        multdiv_operand_b_i=0x14,
    )
    # 0xA + 0x14 = 0x1E in 33-bit; [32:1] of that is 0xF.
    assert int(dut.adder_result_ext_o.value) & 0x1_FFFF_FFFF == 0x0000_001E
    assert int(dut.adder_result_o.value) == 0x0000_000F


@cocotb.test()
async def equality_flag(dut):
    """Spec §"Equality flag" — `is_equal_result_o = (adder_result_o == 0)`.
    The caller selects a SUB-class operator (e.g. ALU_EQ) so the adder
    computes `a - b` and equality reads as operand-equality."""
    await _drive(dut, operator_i=ALU_EQ, operand_a_i=0xDEAD_BEEF, operand_b_i=0xDEAD_BEEF)
    assert int(dut.is_equal_result_o.value) == 1
    await _drive(dut, operator_i=ALU_EQ, operand_a_i=1, operand_b_i=2)
    assert int(dut.is_equal_result_o.value) == 0


@cocotb.test()
async def comparator_signed_and_unsigned(dut):
    """Spec §"Signed and unsigned comparator"."""
    # Signed LT: -1 < +1.
    await _drive(dut, operator_i=ALU_LT, operand_a_i=0xFFFF_FFFF, operand_b_i=1)
    assert int(dut.comparison_result_o.value) == 1
    # Unsigned LTU same operands: 0xFFFFFFFF unsigned > 1, so LT is false.
    await _drive(dut, operator_i=ALU_LTU, operand_a_i=0xFFFF_FFFF, operand_b_i=1)
    assert int(dut.comparison_result_o.value) == 0
    # GE on equal operands.
    await _drive(dut, operator_i=ALU_GE, operand_a_i=7, operand_b_i=7)
    assert int(dut.comparison_result_o.value) == 1
    # NE on equal operands.
    await _drive(dut, operator_i=ALU_NE, operand_a_i=7, operand_b_i=7)
    assert int(dut.comparison_result_o.value) == 0


@cocotb.test()
async def slt_writes_extended_result(dut):
    """Spec §"Comparison operators expose boolean result" — SLT/SLTU 32-bit form."""
    # Signed SLT true: -2 < 0.
    await _drive(dut, operator_i=ALU_SLT, operand_a_i=0xFFFF_FFFE, operand_b_i=0)
    assert int(dut.comparison_result_o.value) == 1
    assert int(dut.result_o.value) == 1
    # SLTU false (equal).
    await _drive(dut, operator_i=ALU_SLTU, operand_a_i=0x10, operand_b_i=0x10)
    assert int(dut.comparison_result_o.value) == 0
    assert int(dut.result_o.value) == 0


@cocotb.test()
async def bitwise_logic(dut):
    """Spec §"Bitwise logic operators"."""
    await _drive(dut, operator_i=ALU_XOR, operand_a_i=0xFFFF_FFFF, operand_b_i=0xAAAA_5555)
    assert int(dut.result_o.value) == 0x5555_AAAA
    await _drive(dut, operator_i=ALU_OR,  operand_a_i=0x0000_FF00, operand_b_i=0x00FF_0000)
    assert int(dut.result_o.value) == 0x00FF_FF00
    await _drive(dut, operator_i=ALU_AND, operand_a_i=0xFF0F_FFFF, operand_b_i=0x0FFF_FF0F)
    assert int(dut.result_o.value) == 0x0F0F_FF0F


@cocotb.test()
async def standard_shifts(dut):
    """Spec §"Standard shifts (SLL, SRL, SRA)" — instr_first_cycle_i = 1."""
    # SLL by 4.
    await _drive(dut, operator_i=ALU_SLL, operand_a_i=0x1234_5678, operand_b_i=4)
    assert int(dut.result_o.value) == 0x2345_6780
    # SRL by 8.
    await _drive(dut, operator_i=ALU_SRL, operand_a_i=0x1234_5678, operand_b_i=8)
    assert int(dut.result_o.value) == 0x0012_3456
    # SRA preserves sign on negative input.
    await _drive(dut, operator_i=ALU_SRA, operand_a_i=0x8000_0000, operand_b_i=4)
    assert int(dut.result_o.value) == 0xF800_0000
    # Upper bits of operand_b ignored — shamt = b[4:0] = 1.
    await _drive(dut, operator_i=ALU_SLL, operand_a_i=1, operand_b_i=0xFFFF_FFE1)
    assert int(dut.result_o.value) == 0x0000_0002


@cocotb.test()
async def rv32b_operator_inert(dut):
    """Spec §"RV32B-inert behavior" — disabled operator → result_o = 0,
    but the unconditional adder output stays valid (op_b_negate = 0
    on RV32B-only opcodes, so the adder sums rather than subtracts)."""
    await _drive(
        dut,
        operator_i=ALU_CLZ_RV32B_ONLY,
        operand_a_i=0x0000_F000,
        operand_b_i=0x0000_0123,
    )
    assert int(dut.result_o.value) == 0
    # Adder still drives op_a + op_b (33-bit sum >> 1 = (a+b) for
    # values that don't overflow into bit 32). Spec §"Adder produces
    # unconditional sum...".
    assert int(dut.adder_result_o.value) == 0x0000_F123
    # imd_val_we_o stays 0 under RV32BNone.
    assert int(dut.imd_val_we_o.value) == 0


@cocotb.test()
async def imd_val_outputs_under_rv32bnone(dut):
    """Spec §"imd_val_d_o and imd_val_we_o under RV32BNone"."""
    await _drive(
        dut,
        operator_i=ALU_ADD,
        imd_q0=0xDEAD_BEEF,
        imd_q1=0xCAFE_BABE,
    )
    # Spec mandates imd_val_we_o = 0.
    assert int(dut.imd_val_we_o.value) == 0
    # imd_val_d_o[i] specifics: spec permits either pass-through or
    # zero. Both are spec-conformant. Just check we_o stays 0 so no
    # stray write activates downstream.
    # (No check on imd_val_d_o lane values.)
