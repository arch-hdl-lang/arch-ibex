"""Standalone cocotb scenarios for `ibex_decoder` (basic suite).

Each `@cocotb.test` covers one Requirement from
`specs/decoder/spec.md`, walking the single most representative
scenario from the spec for that requirement with a real RISC-V
instruction encoding (hex pulled directly from the spec scenarios).

The decoder is purely combinational with `RV32B = RV32BNone`. `clk_i`
and `rst_ni` are SVA-only on the SV boundary; the test driver pins
`clk_i = 0`, `rst_ni = 1` for every test (never toggling). Settling is
just `Timer(1, "ns")` after each input change.

Operator/selector enum integer encodings are pulled from the spec's
§"Enum encodings" section, not from any RTL package.

In-scope parameters: RV32E=0, RV32M=RV32MFast (=2), RV32B=RV32BNone (=0),
BranchTargetALU=0.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer


# ── Enum encodings (from spec §"Enum encodings") ─────────────────────────

# alu_op_e — width 7
ALU_ADD = 0
ALU_SUB = 1
ALU_XOR = 2
ALU_OR = 3
ALU_AND = 4
ALU_SRA = 8
ALU_SRL = 9
ALU_SLL = 10
ALU_LT = 25
ALU_LTU = 26
ALU_GE = 27
ALU_GEU = 28
ALU_EQ = 29
ALU_NE = 30
ALU_SLT = 43
ALU_SLTU = 44

# op_a_sel_e — width 2
OP_A_REG_A = 0
OP_A_FWD = 1
OP_A_CURRPC = 2
OP_A_IMM = 3

# op_b_sel_e — width 1
OP_B_REG_B = 0
OP_B_IMM = 1

# imm_a_sel_e — width 1
IMM_A_Z = 0
IMM_A_ZERO = 1

# imm_b_sel_e — width 3
IMM_B_I = 0
IMM_B_S = 1
IMM_B_B = 2
IMM_B_U = 3
IMM_B_J = 4
IMM_B_INCR_PC = 5
IMM_B_INCR_ADDR = 6

# rf_wd_sel_e — width 1
RF_WD_EX = 0
RF_WD_CSR = 1

# csr_op_e — width 2
CSR_OP_READ = 0
CSR_OP_WRITE = 1
CSR_OP_SET = 2
CSR_OP_CLEAR = 3

# md_op_e — width 2
MD_OP_MULL = 0
MD_OP_MULH = 1
MD_OP_DIV = 2
MD_OP_REM = 3


# ── Driver ───────────────────────────────────────────────────────────────
async def _drive(
    dut,
    *,
    instr: int,
    instr_alu: int | None = None,
    instr_first_cycle: int = 1,
    illegal_c_insn: int = 0,
    branch_taken: int = 0,
):
    """Apply inputs and settle.

    Defaults: `clk_i = 0`, `rst_ni = 1` (SVA-only, never toggled),
    `branch_taken_i = 0`, `instr_first_cycle_i = 1`,
    `illegal_c_insn_i = 0`. `instr_rdata_i` and `instr_rdata_alu_i`
    mirror each other unless `instr_alu` is overridden.
    """
    if instr_alu is None:
        instr_alu = instr
    dut.clk_i.value = 0
    dut.rst_ni.value = 1
    dut.branch_taken_i.value = branch_taken
    dut.instr_first_cycle_i.value = instr_first_cycle
    dut.illegal_c_insn_i.value = illegal_c_insn
    dut.instr_rdata_i.value = instr & 0xFFFF_FFFF
    dut.instr_rdata_alu_i.value = instr_alu & 0xFFFF_FFFF
    await Timer(1, "ns")


# ── Tests: one per spec Requirement ──────────────────────────────────────
@cocotb.test()
async def immediate_extraction_canonical_set(dut):
    """Spec §"Immediate extraction" — verifies that the six fully-decoded
    immediate ports are fixed bit-string functions of `instr_rdata_i`,
    independent of opcode. Walks one canonical encoding for an I-type
    instruction and confirms that `imm_i_type_o` matches the spec
    formula's sign-extension behaviour. The other five immediates
    (S/B/U/J/zimm) are exercised in the full suite."""
    # ADDI x1, x0, -1 → 0xFFF00093, imm_i = 32'hFFFF_FFFF.
    await _drive(dut, instr=0xFFF00093)
    assert int(dut.imm_i_type_o.value) == 0xFFFF_FFFF


@cocotb.test()
async def register_addressing_slices(dut):
    """Spec §"Register addressing" — verifies that `rf_raddr_a_o`,
    `rf_raddr_b_o`, and `rf_waddr_o` are fixed slices of
    `instr_rdata_i` (`[19:15]`, `[24:20]`, `[11:7]`) regardless of
    opcode. Walks an R-type ADD with three distinct register
    operands so each field maps to a unique value. Under
    `RV32B = RV32BNone` the rs3 latch is elided and rs1 always wins
    the read-port-A mux."""
    # ADD x10, x11, x12 → 0x00C58533 → rs1=11, rs2=12, rd=10.
    await _drive(dut, instr=0x00C58533)
    assert int(dut.rf_raddr_a_o.value) == 11
    assert int(dut.rf_raddr_b_o.value) == 12
    assert int(dut.rf_waddr_o.value) == 10


@cocotb.test()
async def rf_we_asserted_for_arithmetic_and_cleared_on_illegal(dut):
    """Spec §"Register-file write enable" — verifies that `rf_we_o`
    is asserted for an instruction that produces an architectural
    register write via the EX/CSR path (canonical R-type ADD), is forced
    low when the decoder detects an illegal instruction, AND is held
    LOW for LOAD instructions whose writeback flows through the LSU's
    separate `rf_we_lsu` path (asserting `rf_we_o = 1` on a LOAD would
    OR the loaded data with the address-calc ALU result in the
    writeback stage, producing silently wrong load data — the failure
    mode that broke 3 of 4 ISR programs during initial A4 development)."""
    # Legal ADD asserts rf_we_o.
    await _drive(dut, instr=0x00C58533)
    assert int(dut.rf_we_o.value) == 1
    # All-zero word: illegal opcode, rf_we_o forced low.
    await _drive(dut, instr=0x00000000)
    assert int(dut.rf_we_o.value) == 0
    assert int(dut.illegal_insn_o.value) == 1
    # LW: writeback is via the LSU, NOT through rf_we_o. The decoder
    # MUST leave rf_we_o = 0; otherwise wb_stage's OR-of-two-sources
    # corrupts the loaded data.
    await _drive(dut, instr=0x0002A303)  # LW x6, 0(x5)
    assert int(dut.rf_we_o.value) == 0, (
        "LOAD must not set rf_we_o; the LSU drives rf_we_lsu "
        "separately and wb_stage OR-combines the two write sources."
    )
    assert int(dut.data_req_o.value) == 1
    assert int(dut.rf_ren_a_o.value) == 1


@cocotb.test()
async def rf_ren_per_opcode(dut):
    """Spec §"Register read enables" — verifies that `rf_ren_a_o` and
    `rf_ren_b_o` are asserted exactly when the active opcode arm
    enables them. Walks an OP-class instruction (canonical ADD) which
    must read both rs1 and rs2; the corresponding zero-defaults case
    (LUI, which reads neither) is covered in the full suite."""
    # ADD reads both rs1 and rs2.
    await _drive(dut, instr=0x00C58533)
    assert int(dut.rf_ren_a_o.value) == 1
    assert int(dut.rf_ren_b_o.value) == 1


@cocotb.test()
async def alu_operator_for_add(dut):
    """Spec §"ALU operator selection (per-opcode)" — verifies that
    for an R-type ADD (funct7 = 0x00, funct3 = 000) the decoder emits
    the canonical `ALU_ADD` operator on `alu_operator_o`. This is the
    representative case for the per-opcode `alu_operator_o` mux; the
    full suite walks each of the 16 in-scope operators."""
    await _drive(dut, instr=0x00C58533)
    assert int(dut.alu_operator_o.value) == ALU_ADD


@cocotb.test()
async def alu_operand_mux_for_op_class(dut):
    """Spec §"ALU operand-A and operand-B mux selection" — verifies
    that an OP-class instruction (canonical ADD) routes register file
    port A onto `alu_op_a_mux_sel_o` and register file port B onto
    `alu_op_b_mux_sel_o`. This is the simplest non-default operand-mux
    routing exposed by the decoder."""
    await _drive(dut, instr=0x00C58533)
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_REG_A
    assert int(dut.alu_op_b_mux_sel_o.value) == OP_B_REG_B


@cocotb.test()
async def bt_mux_constants_under_branch_target_alu_zero(dut):
    """Spec §"Branch-target mux selection" — verifies that with
    `BranchTargetALU = 0` the BT mux selectors keep their block-level
    defaults for every opcode. Drives a canonical ADD (opcode 0x33,
    arbitrary representative) and confirms `bt_a_mux_sel_o` = OP_A_CURRPC
    and `bt_b_mux_sel_o` = IMM_B_I, which is the constant assignment
    the spec mandates in scope."""
    await _drive(dut, instr=0x00C58533)
    assert int(dut.bt_a_mux_sel_o.value) == OP_A_CURRPC
    assert int(dut.bt_b_mux_sel_o.value) == IMM_B_I


@cocotb.test()
async def multdiv_control_for_mul(dut):
    """Spec §"Mult/Div control" — verifies that for a canonical RV32M
    MUL (OPCODE_OP, funct7 = 0x01, funct3 = 000) the decoder emits the
    representative multdiv control word (operator MULL, unsigned
    signed-mode, `mult_sel_o` asserted, `div_sel_o` low) and forces
    the ALU operator to ADD so the adder can pass partial products.
    The illegal-mask path on `mult_en_o`/`div_en_o` is checked in the
    full suite."""
    # MUL x10, x11, x12 → 0x02C58533.
    await _drive(dut, instr=0x02C58533)
    assert int(dut.multdiv_operator_o.value) == MD_OP_MULL
    assert int(dut.multdiv_signed_mode_o.value) == 0b00
    assert int(dut.mult_sel_o.value) == 1
    assert int(dut.div_sel_o.value) == 0
    assert int(dut.mult_en_o.value) == 1
    assert int(dut.div_en_o.value) == 0
    assert int(dut.alu_operator_o.value) == ALU_ADD


@cocotb.test()
async def csr_control_for_csrrw(dut):
    """Spec §"CSR control" — verifies that a canonical CSRRW
    (`OPCODE_SYSTEM`, funct3 = 001, with non-zero rs1) produces a CSR
    access at the correct address (raw `instr[31:20]`), with
    `CSR_OP_WRITE` on the externally-visible `csr_op_o`, and routes
    the register-file write data from the CSR side. Boundary cases
    (rs1=0 demote, immediate forms) are walked in the full suite."""
    # CSRRW x10, mtvec(0x305), x11 → 0x30559573.
    await _drive(dut, instr=0x30559573)
    assert int(dut.csr_access_o.value) == 1
    assert int(dut.csr_addr_o.value) == 0x305
    assert int(dut.csr_op_o.value) == CSR_OP_WRITE
    assert int(dut.rf_wdata_sel_o.value) == RF_WD_CSR
    assert int(dut.rf_we_o.value) == 1


@cocotb.test()
async def lsu_control_for_sw(dut):
    """Spec §"LSU control" — verifies that a canonical store-word
    (`OPCODE_STORE`, funct3 = 010) raises `data_req_o` and `data_we_o`,
    selects the word access size on `data_type_o`, and leaves
    `data_sign_extension_o` at its default. This is the representative
    LSU scenario; the full suite walks each load/store funct3 and the
    illegal-mask path."""
    # SW x12, 0(x11) → 0x00C5A023.
    await _drive(dut, instr=0x00C5A023)
    assert int(dut.data_req_o.value) == 1
    assert int(dut.data_we_o.value) == 1
    assert int(dut.data_type_o.value) == 0b00
    assert int(dut.data_sign_extension_o.value) == 0


@cocotb.test()
async def control_flag_outputs_for_jal(dut):
    """Spec §"Control flag outputs" — verifies that JAL on its first
    execution cycle raises `jump_in_dec_o` together with `jump_set_o`,
    and that the trap flags (ebrk/mret/dret/ecall/wfi) and the
    `branch_in_dec_o` / `icache_inval_o` flags stay low. Picks JAL as
    the representative scenario because it exercises the
    `instr_first_cycle_i`-gated `jump_set_o` strobe; SYSTEM trap flag
    cases are in the full suite."""
    # JAL x1, +8 → 0x008000EF.
    await _drive(dut, instr=0x008000EF, instr_first_cycle=1)
    assert int(dut.jump_in_dec_o.value) == 1
    assert int(dut.jump_set_o.value) == 1
    assert int(dut.branch_in_dec_o.value) == 0
    assert int(dut.icache_inval_o.value) == 0
    assert int(dut.ebrk_insn_o.value) == 0
    assert int(dut.mret_insn_o.value) == 0
    assert int(dut.dret_insn_o.value) == 0
    assert int(dut.ecall_insn_o.value) == 0
    assert int(dut.wfi_insn_o.value) == 0


@cocotb.test()
async def illegal_insn_aggregation_for_rv32b_opcode(dut):
    """Spec §"Illegal-instruction aggregation" — verifies that an
    OPCODE_OP encoding that maps to an RV32B-only operator (BSET,
    funct7 = 0x29) is flagged illegal under `RV32B = RV32BNone`, and
    that the illegal-mask machinery clears `rf_we_o`, `data_req_o`,
    `jump_in_dec_o`, `branch_in_dec_o`, and `csr_access_o`. This is
    the representative aggregator test; other illegal causes (bad
    opcode, illegal funct3, compressed pass-through) appear in the
    full suite."""
    # BSET x10, x11, x12 → 0x28C58533 (RV32B opcode in OP arm).
    await _drive(dut, instr=0x28C58533)
    assert int(dut.illegal_insn_o.value) == 1
    assert int(dut.rf_we_o.value) == 0
    assert int(dut.data_req_o.value) == 0
    assert int(dut.jump_in_dec_o.value) == 0
    assert int(dut.branch_in_dec_o.value) == 0
    assert int(dut.csr_access_o.value) == 0
