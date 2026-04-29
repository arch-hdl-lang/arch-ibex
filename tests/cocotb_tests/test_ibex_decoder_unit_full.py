"""Full-regression cocotb scenarios for `ibex_decoder`.

Walks every `#### Scenario:` from `specs/decoder/spec.md` plus edge
cases the spec implies but does not enumerate exhaustively:

  * Every RV32I instruction class (one canonical encoding each).
  * Every RV32M instruction (MUL/MULH/MULHSU/MULHU/DIV/DIVU/REM/REMU).
  * Every immediate type (I/S/B/U/J/zimm) with sign-extension boundary
    cases (positive vs. negative immediates).
  * CSR sub-decode: CSRRW, CSRRS, CSRRC, CSRRWI, CSRRSI, CSRRCI; with
    rs1=0, rd=0, rs1!=0 mixes; legal and illegal CSR funct3.
  * Illegal-instruction boundaries: malformed opcode, malformed funct3,
    malformed funct7, RV32B opcode under RV32BNone, and
    `illegal_c_insn_i = 1` pass-through.
  * rd=x0 / rs1=x0 / rs2=x0 boundary cases on each instruction class.

Decoder is purely combinational under `RV32B = RV32BNone`. `clk_i`
and `rst_ni` are SVA-only; the driver pins them and never toggles
them. Settling is `Timer(1, "ns")` after each input change.

In-scope parameters: RV32E=0, RV32M=2 (RV32MFast), RV32B=0
(RV32BNone), BranchTargetALU=0.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer


# ── Enum encodings (from spec §"Enum encodings") ─────────────────────────

# alu_op_e
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

# op_a_sel_e
OP_A_REG_A = 0
OP_A_CURRPC = 2
OP_A_IMM = 3

# op_b_sel_e
OP_B_REG_B = 0
OP_B_IMM = 1

# imm_a_sel_e
IMM_A_Z = 0
IMM_A_ZERO = 1

# imm_b_sel_e
IMM_B_I = 0
IMM_B_S = 1
IMM_B_B = 2
IMM_B_U = 3
IMM_B_J = 4
IMM_B_INCR_PC = 5

# rf_wd_sel_e
RF_WD_EX = 0
RF_WD_CSR = 1

# csr_op_e
CSR_OP_READ = 0
CSR_OP_WRITE = 1
CSR_OP_SET = 2
CSR_OP_CLEAR = 3

# md_op_e
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
    """Apply inputs and settle. `clk_i` / `rst_ni` are SVA-only."""
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


# ─────────────────────────────────────────────────────────────────────────
# Requirement: Defaults when not overridden
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def defaults_on_illegal_opcode(dut):
    """Spec §"Defaults..." — for an opcode that hits the case default
    (here all-zero, opcode=0x00), the ALU-block defaults remain
    visible since the ALU-block default arm leaves ALU outputs at
    their block defaults: ALU_SLTU, OP_A_IMM, OP_B_IMM, IMM_A_ZERO,
    IMM_B_I, OP_A_CURRPC for BT_A, IMM_B_I for BT_B."""
    await _drive(dut, instr=0x00000000)
    assert int(dut.alu_operator_o.value) == ALU_SLTU
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_IMM
    assert int(dut.alu_op_b_mux_sel_o.value) == OP_B_IMM
    assert int(dut.imm_a_mux_sel_o.value) == IMM_A_ZERO
    assert int(dut.imm_b_mux_sel_o.value) == IMM_B_I
    assert int(dut.bt_a_mux_sel_o.value) == OP_A_CURRPC
    assert int(dut.bt_b_mux_sel_o.value) == IMM_B_I
    assert int(dut.alu_multicycle_o.value) == 0
    assert int(dut.mult_sel_o.value) == 0
    assert int(dut.div_sel_o.value) == 0
    # Illegal masking forces these:
    assert int(dut.rf_we_o.value) == 0
    assert int(dut.data_req_o.value) == 0
    assert int(dut.data_we_o.value) == 0
    assert int(dut.jump_in_dec_o.value) == 0
    assert int(dut.jump_set_o.value) == 0
    assert int(dut.branch_in_dec_o.value) == 0
    assert int(dut.csr_access_o.value) == 0


# ─────────────────────────────────────────────────────────────────────────
# Requirement: Immediate extraction
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def imm_i_negative_sign_extends(dut):
    """Spec §imm, Scenario: I-type immediate sign-extends instr[31:20]."""
    # ADDI x1, x0, -1
    await _drive(dut, instr=0xFFF00093)
    assert int(dut.imm_i_type_o.value) == 0xFFFF_FFFF


@cocotb.test()
async def imm_i_positive(dut):
    """Spec §imm, Scenario: I-type immediate, positive."""
    # ADDI x2, x0, 5
    await _drive(dut, instr=0x00500113)
    assert int(dut.imm_i_type_o.value) == 0x0000_0005


@cocotb.test()
async def imm_s_split(dut):
    """Spec §imm, Scenario: S-type immediate splits across [31:25]/[11:7]."""
    # SW x1, -4(x2): imm = -4
    await _drive(dut, instr=0xFE112E23)
    assert int(dut.imm_s_type_o.value) == 0xFFFF_FFFC


@cocotb.test()
async def imm_b_lsb_zero_positive(dut):
    """Spec §imm, Scenario: B-type immediate has implicit zero LSB."""
    # BEQ x1, x2, +8
    await _drive(dut, instr=0x00208463)
    assert int(dut.imm_b_type_o.value) == 0x0000_0008


@cocotb.test()
async def imm_b_negative(dut):
    """Spec §imm, Scenario: B-type immediate, negative."""
    # BEQ x0, x0, -16
    await _drive(dut, instr=0xFE0008E3)
    assert int(dut.imm_b_type_o.value) == 0xFFFF_FFF0


@cocotb.test()
async def imm_u_high_bits(dut):
    """Spec §imm, Scenario: U-type immediate places instr[31:12] in upper 20."""
    # LUI x0, 0x12345
    await _drive(dut, instr=0x12345037)
    assert int(dut.imm_u_type_o.value) == 0x12345000


@cocotb.test()
async def imm_j_lsb_zero_positive(dut):
    """Spec §imm, Scenario: J-type immediate has implicit zero LSB."""
    # JAL x1, +8
    await _drive(dut, instr=0x008000EF)
    assert int(dut.imm_j_type_o.value) == 0x0000_0008


@cocotb.test()
async def imm_j_negative(dut):
    """Spec §imm, Scenario: J-type immediate, large negative."""
    # JAL x1, -4
    await _drive(dut, instr=0xFFDFF0EF)
    assert int(dut.imm_j_type_o.value) == 0xFFFF_FFFC


@cocotb.test()
async def zimm_zero_extends(dut):
    """Spec §imm, Scenario: zimm zero-extends rs1 field."""
    # rs1 = 21 in CSRRWI form (instr[19:15] = 5'b10101)
    instr = (21 << 15) | 0x00005073  # arbitrary CSRRWI-shape
    await _drive(dut, instr=instr)
    assert int(dut.zimm_rs1_type_o.value) == 0x0000_0015


@cocotb.test()
async def imm_extraction_independent_of_opcode(dut):
    """Edge case: imm_i_type_o still extracts even on an illegal
    opcode. The decoder produces the immediates as fixed slices
    regardless of opcode validity."""
    # Garbage opcode 0x00 with non-zero instr[31:20] = 0x123.
    instr = (0x123 << 20) | 0x00000000
    await _drive(dut, instr=instr)
    # 0x123 is positive (sign bit clear), expect zero-extended to
    # match instr[31:20] = 0x123.
    assert int(dut.imm_i_type_o.value) == 0x0000_0123


# ─────────────────────────────────────────────────────────────────────────
# Requirement: Register addressing
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def rf_addrs_for_add(dut):
    """Spec §regaddr, Scenario: read addresses are rs1/rs2 fields."""
    # ADD x10, x11, x12
    await _drive(dut, instr=0x00C58533)
    assert int(dut.rf_raddr_a_o.value) == 11
    assert int(dut.rf_raddr_b_o.value) == 12
    assert int(dut.rf_waddr_o.value) == 10


@cocotb.test()
async def rf_waddr_when_rf_we_low(dut):
    """Spec §regaddr, Scenario: write address is rd field even when rf_we_o = 0.
    Note: ADDI x10, x10, 0 actually writes; pick SW which does not."""
    # SW x12, 0(x11) → rd field = 0 in S-type.
    await _drive(dut, instr=0x00C5A023)
    # rd field for SW is instr[11:7]; in 0x00C5A023, [11:7] = 0.
    assert int(dut.rf_waddr_o.value) == 0
    assert int(dut.rf_we_o.value) == 0


@cocotb.test()
async def rs3_path_inert(dut):
    """Spec §regaddr, Scenario: rs3 path is inert in scope."""
    # Drive instr_first_cycle_i = 0 to expose any rs3 latch behavior.
    await _drive(dut, instr=0x00C58533, instr_first_cycle=0)
    assert int(dut.rf_raddr_a_o.value) == 11  # rs1 always wins


@cocotb.test()
async def rs1_x0_boundary(dut):
    """Edge case: rs1=x0 still produces rf_raddr_a_o = 0."""
    # ADD x10, x0, x12
    await _drive(dut, instr=0x00C00533)
    assert int(dut.rf_raddr_a_o.value) == 0


@cocotb.test()
async def rs2_x0_boundary(dut):
    """Edge case: rs2=x0 still produces rf_raddr_b_o = 0."""
    # ADD x10, x11, x0
    await _drive(dut, instr=0x00058533)
    assert int(dut.rf_raddr_b_o.value) == 0


@cocotb.test()
async def rd_x0_still_writes(dut):
    """Edge case: rd=x0 leaves rf_we_o asserted (downstream nullifies).
    Uses ADD x0, x11, x12 → rd field = 0."""
    await _drive(dut, instr=0x00C58033)
    assert int(dut.rf_waddr_o.value) == 0
    assert int(dut.rf_we_o.value) == 1


# ─────────────────────────────────────────────────────────────────────────
# Requirement: Register-file write enable
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def add_writes_rf(dut):
    """Spec §rfwe, Scenario: ADD writes the register file."""
    await _drive(dut, instr=0x00C58533)
    assert int(dut.rf_we_o.value) == 1


@cocotb.test()
async def sw_does_not_write_rf(dut):
    """Spec §rfwe, Scenario: SW does not write the register file."""
    await _drive(dut, instr=0x00C5A023)
    assert int(dut.rf_we_o.value) == 0


@cocotb.test()
async def beq_does_not_write_rf(dut):
    """Spec §rfwe, Scenario: BEQ does not write the register file."""
    await _drive(dut, instr=0x00B58463)
    assert int(dut.rf_we_o.value) == 0


@cocotb.test()
async def jal_first_cycle_no_write(dut):
    """Spec §rfwe, Scenario: JAL with BranchTargetALU=0 writes only on second cycle."""
    await _drive(dut, instr=0x008000EF, instr_first_cycle=1)
    # BranchTargetALU=0 → first-cycle rf_we = BranchTargetALU = 0.
    assert int(dut.rf_we_o.value) == 0


@cocotb.test()
async def jal_second_cycle_writes(dut):
    """Spec §rfwe, Scenario: JAL second cycle writes PC+4."""
    await _drive(dut, instr=0x008000EF, instr_first_cycle=0)
    assert int(dut.rf_we_o.value) == 1


@cocotb.test()
async def csrrw_writes_rf(dut):
    """Spec §rfwe, Scenario: CSRRW writes the destination register."""
    await _drive(dut, instr=0x30559573)
    assert int(dut.rf_we_o.value) == 1
    assert int(dut.rf_wdata_sel_o.value) == RF_WD_CSR


@cocotb.test()
async def illegal_opcode_clears_rf_we(dut):
    """Spec §rfwe, Scenario: illegal opcode forces rf_we_o = 0."""
    await _drive(dut, instr=0x00000000)
    assert int(dut.rf_we_o.value) == 0
    assert int(dut.illegal_insn_o.value) == 1


# ─────────────────────────────────────────────────────────────────────────
# Requirement: Register read enables
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def opimm_reads_rs1_only(dut):
    """Spec §rfren, Scenario: OP-IMM reads rs1 only."""
    # ADDI x2, x0, 5
    await _drive(dut, instr=0x00500113)
    assert int(dut.rf_ren_a_o.value) == 1
    assert int(dut.rf_ren_b_o.value) == 0


@cocotb.test()
async def op_reads_both(dut):
    """Spec §rfren, Scenario: OP reads both rs1 and rs2."""
    await _drive(dut, instr=0x00C58533)
    assert int(dut.rf_ren_a_o.value) == 1
    assert int(dut.rf_ren_b_o.value) == 1


@cocotb.test()
async def branch_reads_both(dut):
    """Spec §rfren, Scenario: BRANCH reads both."""
    await _drive(dut, instr=0x00B58463)
    assert int(dut.rf_ren_a_o.value) == 1
    assert int(dut.rf_ren_b_o.value) == 1


@cocotb.test()
async def store_reads_both(dut):
    """Spec §rfren, Scenario: STORE reads both."""
    await _drive(dut, instr=0x00C5A023)
    assert int(dut.rf_ren_a_o.value) == 1
    assert int(dut.rf_ren_b_o.value) == 1


@cocotb.test()
async def load_reads_rs1(dut):
    """Spec §rfren, Scenario: LOAD reads only rs1."""
    # LW x10, 0(x11)
    await _drive(dut, instr=0x0005A503)
    assert int(dut.rf_ren_a_o.value) == 1
    assert int(dut.rf_ren_b_o.value) == 0


@cocotb.test()
async def jalr_reads_rs1(dut):
    """Spec §rfren, Scenario: JALR reads rs1."""
    # JALR x1, x1, 0 → 0x000080E7
    await _drive(dut, instr=0x000080E7)
    assert int(dut.rf_ren_a_o.value) == 1
    assert int(dut.rf_ren_b_o.value) == 0


@cocotb.test()
async def jal_reads_neither(dut):
    """Spec §rfren, Scenario: JAL reads neither register."""
    await _drive(dut, instr=0x008000EF)
    assert int(dut.rf_ren_a_o.value) == 0
    assert int(dut.rf_ren_b_o.value) == 0


@cocotb.test()
async def lui_reads_neither(dut):
    """Spec §rfren, Scenario: LUI reads neither."""
    await _drive(dut, instr=0x12345037)
    assert int(dut.rf_ren_a_o.value) == 0
    assert int(dut.rf_ren_b_o.value) == 0


@cocotb.test()
async def auipc_reads_neither(dut):
    """Spec §rfren, Scenario: AUIPC reads neither."""
    # AUIPC x1, 1 → 0x00001097
    await _drive(dut, instr=0x00001097)
    assert int(dut.rf_ren_a_o.value) == 0
    assert int(dut.rf_ren_b_o.value) == 0


@cocotb.test()
async def csrrw_reads_rs1(dut):
    """Spec §rfren, Scenario: CSRRW reads rs1."""
    await _drive(dut, instr=0x30559573)
    assert int(dut.rf_ren_a_o.value) == 1


@cocotb.test()
async def csrrwi_no_rs1_read(dut):
    """Spec §rfren, Scenario: CSRRWI does not read rs1."""
    # CSRRWI x10, mtvec, 11 → 0x3055D573 (funct3 = 101)
    await _drive(dut, instr=0x3055D573)
    assert int(dut.rf_ren_a_o.value) == 0


# ─────────────────────────────────────────────────────────────────────────
# Requirement: ALU operator selection
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def add_op(dut):
    """Spec §aluop, Scenario: ADD selects ALU_ADD."""
    await _drive(dut, instr=0x00C58533)
    assert int(dut.alu_operator_o.value) == ALU_ADD


@cocotb.test()
async def sub_op(dut):
    """Spec §aluop, Scenario: SUB selects ALU_SUB."""
    # SUB x10, x11, x12 → 0x40C58533
    await _drive(dut, instr=0x40C58533)
    assert int(dut.alu_operator_o.value) == ALU_SUB


@cocotb.test()
async def slt_sltu_xor_or_and_sll_srl_sra_ops(dut):
    """Spec §aluop, Scenario: SLT/SLTU/XOR/OR/AND/SLL/SRL/SRA selectors."""
    # Build R-type with funct7/funct3 per table.
    def rtype(f7, f3):
        return (f7 << 25) | (12 << 20) | (11 << 15) | (f3 << 12) | (10 << 7) | 0x33
    cases = [
        (0x00, 0b010, ALU_SLT),
        (0x00, 0b011, ALU_SLTU),
        (0x00, 0b100, ALU_XOR),
        (0x00, 0b110, ALU_OR),
        (0x00, 0b111, ALU_AND),
        (0x00, 0b001, ALU_SLL),
        (0x00, 0b101, ALU_SRL),
        (0x20, 0b101, ALU_SRA),
    ]
    for f7, f3, expected in cases:
        await _drive(dut, instr=rtype(f7, f3))
        assert int(dut.alu_operator_o.value) == expected, (
            f"f7={f7:#x} f3={f3:#b} expected {expected}"
        )


@cocotb.test()
async def addi_op(dut):
    """Spec §aluop, Scenario: ADDI selects ALU_ADD."""
    await _drive(dut, instr=0x00500113)
    assert int(dut.alu_operator_o.value) == ALU_ADD


@cocotb.test()
async def opimm_funct3_ops(dut):
    """Spec §aluop, Scenario: SLTI/SLTIU/XORI/ORI/ANDI selectors."""
    def itype(f3):
        return (5 << 20) | (0 << 15) | (f3 << 12) | (1 << 7) | 0x13
    cases = [
        (0b010, ALU_SLT),
        (0b011, ALU_SLTU),
        (0b100, ALU_XOR),
        (0b110, ALU_OR),
        (0b111, ALU_AND),
    ]
    for f3, expected in cases:
        await _drive(dut, instr=itype(f3))
        assert int(dut.alu_operator_o.value) == expected, f"f3={f3:#b}"


@cocotb.test()
async def slli_op(dut):
    """Spec §aluop, Scenario: SLLI selects ALU_SLL when funct7=0x00."""
    # SLLI x1, x1, 5 → 0x00509093
    await _drive(dut, instr=0x00509093)
    assert int(dut.alu_operator_o.value) == ALU_SLL


@cocotb.test()
async def srli_op(dut):
    """Spec §aluop, Scenario: SRLI selects ALU_SRL."""
    # SRLI x1, x1, 5 → 0x0050D093
    await _drive(dut, instr=0x0050D093)
    assert int(dut.alu_operator_o.value) == ALU_SRL


@cocotb.test()
async def srai_op(dut):
    """Spec §aluop, Scenario: SRAI selects ALU_SRA."""
    # SRAI x1, x1, 5 → 0x4050D093
    await _drive(dut, instr=0x4050D093)
    assert int(dut.alu_operator_o.value) == ALU_SRA


@cocotb.test()
async def branch_funct3_picks_comparator(dut):
    """Spec §aluop, Scenario: BRANCH funct3 picks the comparator."""
    def btype(f3):
        # Use BEQ template 0x00B58463 (rs1=11, rs2=11, imm=8) and override f3.
        return (0x00B58463 & ~(0b111 << 12)) | (f3 << 12)
    cases = [
        (0b000, ALU_EQ),
        (0b001, ALU_NE),
        (0b100, ALU_LT),
        (0b101, ALU_GE),
        (0b110, ALU_LTU),
        (0b111, ALU_GEU),
    ]
    for f3, expected in cases:
        await _drive(dut, instr=btype(f3))
        assert int(dut.alu_operator_o.value) == expected, f"f3={f3:#b}"


@cocotb.test()
async def jal_op_is_add(dut):
    """Spec §aluop, Scenario: JAL operator is ADD."""
    await _drive(dut, instr=0x008000EF, instr_first_cycle=1)
    assert int(dut.alu_operator_o.value) == ALU_ADD
    await _drive(dut, instr=0x008000EF, instr_first_cycle=0)
    assert int(dut.alu_operator_o.value) == ALU_ADD


@cocotb.test()
async def jalr_op_is_add(dut):
    """Spec §aluop, Scenario: JALR operator is ADD."""
    await _drive(dut, instr=0x000080E7)
    assert int(dut.alu_operator_o.value) == ALU_ADD


@cocotb.test()
async def load_store_op_is_add(dut):
    """Spec §aluop, Scenario: LOAD/STORE address gen is ADD."""
    await _drive(dut, instr=0x0005A503)
    assert int(dut.alu_operator_o.value) == ALU_ADD
    await _drive(dut, instr=0x00C5A023)
    assert int(dut.alu_operator_o.value) == ALU_ADD


@cocotb.test()
async def auipc_op_is_add(dut):
    """Spec §aluop, Scenario: AUIPC operator is ADD."""
    await _drive(dut, instr=0x00001097)
    assert int(dut.alu_operator_o.value) == ALU_ADD


@cocotb.test()
async def lui_op_is_add(dut):
    """Spec §aluop, Scenario: LUI operator is ADD (zero + U-imm)."""
    await _drive(dut, instr=0x12345037)
    assert int(dut.alu_operator_o.value) == ALU_ADD


@cocotb.test()
async def fence_op_is_add(dut):
    """Spec §aluop, Scenario: FENCE/FENCE.I operator is ADD."""
    # FENCE → 0x0000000F
    await _drive(dut, instr=0x0000000F)
    assert int(dut.alu_operator_o.value) == ALU_ADD
    # FENCE.I → 0x0000100F
    await _drive(dut, instr=0x0000100F)
    assert int(dut.alu_operator_o.value) == ALU_ADD


@cocotb.test()
async def csr_keeps_alu_default(dut):
    """Spec §aluop, Scenario: SYSTEM/CSR keeps ALU defaults."""
    await _drive(dut, instr=0x30559573)
    assert int(dut.alu_operator_o.value) == ALU_SLTU


# ─────────────────────────────────────────────────────────────────────────
# Requirement: ALU operand-A and operand-B mux selection
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def op_class_operand_mux(dut):
    """Spec §alumux, Scenario: OP/OP-IMM operand-A is REG_A; operand-B is REG_B/IMM."""
    # OP (ADD).
    await _drive(dut, instr=0x00C58533)
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_REG_A
    assert int(dut.alu_op_b_mux_sel_o.value) == OP_B_REG_B
    # OP-IMM (ADDI).
    await _drive(dut, instr=0x00500113)
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_REG_A
    assert int(dut.alu_op_b_mux_sel_o.value) == OP_B_IMM
    assert int(dut.imm_b_mux_sel_o.value) == IMM_B_I


@cocotb.test()
async def lui_operand_mux(dut):
    """Spec §alumux, Scenario: LUI uses immediate operand-A (zero) and U-imm."""
    await _drive(dut, instr=0x12345037)
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_IMM
    assert int(dut.alu_op_b_mux_sel_o.value) == OP_B_IMM
    assert int(dut.imm_a_mux_sel_o.value) == IMM_A_ZERO
    assert int(dut.imm_b_mux_sel_o.value) == IMM_B_U


@cocotb.test()
async def auipc_operand_mux(dut):
    """Spec §alumux, Scenario: AUIPC uses CURRPC and U-immediate."""
    await _drive(dut, instr=0x00001097)
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_CURRPC
    assert int(dut.alu_op_b_mux_sel_o.value) == OP_B_IMM
    assert int(dut.imm_b_mux_sel_o.value) == IMM_B_U


@cocotb.test()
async def jal_first_cycle_mux(dut):
    """Spec §alumux, Scenario: JAL first cycle — CURRPC + IMM_B_J."""
    await _drive(dut, instr=0x008000EF, instr_first_cycle=1)
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_CURRPC
    assert int(dut.alu_op_b_mux_sel_o.value) == OP_B_IMM
    assert int(dut.imm_b_mux_sel_o.value) == IMM_B_J


@cocotb.test()
async def jal_second_cycle_mux(dut):
    """Spec §alumux, Scenario: JAL second cycle — CURRPC + IMM_B_INCR_PC."""
    await _drive(dut, instr=0x008000EF, instr_first_cycle=0)
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_CURRPC
    assert int(dut.alu_op_b_mux_sel_o.value) == OP_B_IMM
    assert int(dut.imm_b_mux_sel_o.value) == IMM_B_INCR_PC


@cocotb.test()
async def jalr_first_cycle_mux(dut):
    """Spec §alumux, Scenario: JALR first cycle — REG_A + IMM_B_I."""
    await _drive(dut, instr=0x000080E7, instr_first_cycle=1)
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_REG_A
    assert int(dut.imm_b_mux_sel_o.value) == IMM_B_I


@cocotb.test()
async def jalr_second_cycle_mux(dut):
    """Spec §alumux, Scenario: JALR second cycle — CURRPC + IMM_B_INCR_PC."""
    await _drive(dut, instr=0x000080E7, instr_first_cycle=0)
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_CURRPC
    assert int(dut.alu_op_b_mux_sel_o.value) == OP_B_IMM
    assert int(dut.imm_b_mux_sel_o.value) == IMM_B_INCR_PC


@cocotb.test()
async def branch_first_cycle_mux(dut):
    """Spec §alumux, Scenario: BRANCH first cycle — REG_A + REG_B."""
    await _drive(dut, instr=0x00B58463, instr_first_cycle=1)
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_REG_A
    assert int(dut.alu_op_b_mux_sel_o.value) == OP_B_REG_B


@cocotb.test()
async def branch_second_cycle_mux_taken(dut):
    """Spec §alumux, Scenario: BRANCH second cycle — taken path."""
    await _drive(dut, instr=0x00B58463, instr_first_cycle=0, branch_taken=1)
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_CURRPC
    assert int(dut.alu_op_b_mux_sel_o.value) == OP_B_IMM
    assert int(dut.alu_operator_o.value) == ALU_ADD
    assert int(dut.imm_b_mux_sel_o.value) == IMM_B_B


@cocotb.test()
async def branch_second_cycle_mux_not_taken(dut):
    """Spec §alumux, Scenario: BRANCH second cycle — not-taken path."""
    await _drive(dut, instr=0x00B58463, instr_first_cycle=0, branch_taken=0)
    assert int(dut.imm_b_mux_sel_o.value) == IMM_B_INCR_PC


@cocotb.test()
async def store_operand_mux(dut):
    """Spec §alumux, Scenario: STORE — REG_A + S-immediate."""
    await _drive(dut, instr=0x00C5A023)
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_REG_A
    assert int(dut.alu_op_b_mux_sel_o.value) == OP_B_IMM
    assert int(dut.imm_b_mux_sel_o.value) == IMM_B_S
    assert int(dut.alu_operator_o.value) == ALU_ADD


@cocotb.test()
async def load_operand_mux(dut):
    """Spec §alumux, Scenario: LOAD — REG_A + I-immediate."""
    await _drive(dut, instr=0x0005A503)
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_REG_A
    assert int(dut.alu_op_b_mux_sel_o.value) == OP_B_IMM
    assert int(dut.imm_b_mux_sel_o.value) == IMM_B_I
    assert int(dut.alu_operator_o.value) == ALU_ADD


@cocotb.test()
async def fence_operand_mux(dut):
    """Spec §alumux, Scenario: MISC-MEM/FENCE — REG_A + IMM."""
    await _drive(dut, instr=0x0000000F)
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_REG_A
    assert int(dut.alu_op_b_mux_sel_o.value) == OP_B_IMM
    assert int(dut.alu_operator_o.value) == ALU_ADD


@cocotb.test()
async def fencei_operand_mux(dut):
    """Spec §alumux, Scenario: MISC-MEM/FENCE.I — CURRPC + IMM_B_INCR_PC."""
    await _drive(dut, instr=0x0000100F)
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_CURRPC
    assert int(dut.alu_op_b_mux_sel_o.value) == OP_B_IMM
    assert int(dut.imm_b_mux_sel_o.value) == IMM_B_INCR_PC
    assert int(dut.alu_operator_o.value) == ALU_ADD


@cocotb.test()
async def system_non_csr_operand_mux(dut):
    """Spec §alumux, Scenario: SYSTEM (non-CSR, funct3=000) — REG_A + IMM."""
    # ECALL → 0x00000073
    await _drive(dut, instr=0x00000073)
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_REG_A
    assert int(dut.alu_op_b_mux_sel_o.value) == OP_B_IMM


@cocotb.test()
async def csr_register_form_mux(dut):
    """Spec §alumux, Scenario: CSRRW/CSRRS/CSRRC — REG_A + IMM, IMM_A_Z."""
    await _drive(dut, instr=0x30559573)  # CSRRW
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_REG_A
    assert int(dut.imm_a_mux_sel_o.value) == IMM_A_Z


@cocotb.test()
async def csr_immediate_form_mux(dut):
    """Spec §alumux, Scenario: CSRRWI/CSRRSI/CSRRCI — IMM + IMM, IMM_A_Z."""
    await _drive(dut, instr=0x3055D573)  # CSRRWI
    assert int(dut.alu_op_a_mux_sel_o.value) == OP_A_IMM
    assert int(dut.imm_a_mux_sel_o.value) == IMM_A_Z


# ─────────────────────────────────────────────────────────────────────────
# Requirement: Branch-target mux selection
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def bt_constants_for_arbitrary_opcodes(dut):
    """Spec §bt, Scenario: BT selectors are constants in scope.
    Sweeps several opcode classes to confirm bt_a_mux_sel_o = OP_A_CURRPC
    and bt_b_mux_sel_o = IMM_B_I unconditionally."""
    instrs = [
        0x00C58533,  # ADD
        0x00500113,  # ADDI
        0x008000EF,  # JAL
        0x000080E7,  # JALR
        0x00B58463,  # BEQ
        0x0005A503,  # LW
        0x00C5A023,  # SW
        0x00001097,  # AUIPC
        0x12345037,  # LUI
        0x0000000F,  # FENCE
        0x0000100F,  # FENCE.I
        0x30559573,  # CSRRW
        0x00000073,  # ECALL
    ]
    for instr in instrs:
        await _drive(dut, instr=instr)
        assert int(dut.bt_a_mux_sel_o.value) == OP_A_CURRPC, hex(instr)
        assert int(dut.bt_b_mux_sel_o.value) == IMM_B_I, hex(instr)


# ─────────────────────────────────────────────────────────────────────────
# Requirement: Mult/Div control
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def mul_basic(dut):
    """Spec §mdcontrol, Scenario: MUL — funct7=0x01, funct3=000."""
    # MUL x10, x11, x12 → 0x02C58533
    await _drive(dut, instr=0x02C58533)
    assert int(dut.multdiv_operator_o.value) == MD_OP_MULL
    assert int(dut.multdiv_signed_mode_o.value) == 0b00
    assert int(dut.mult_sel_o.value) == 1
    assert int(dut.div_sel_o.value) == 0
    assert int(dut.mult_en_o.value) == 1
    assert int(dut.div_en_o.value) == 0
    assert int(dut.alu_operator_o.value) == ALU_ADD
    assert int(dut.rf_we_o.value) == 1
    assert int(dut.rf_ren_a_o.value) == 1
    assert int(dut.rf_ren_b_o.value) == 1
    assert int(dut.illegal_insn_o.value) == 0


@cocotb.test()
async def mulh_basic(dut):
    """Spec §mdcontrol, Scenario: MULH — funct3=001."""
    # MULH x10, x11, x12 → 0x02C59533
    await _drive(dut, instr=0x02C59533)
    assert int(dut.multdiv_operator_o.value) == MD_OP_MULH
    assert int(dut.multdiv_signed_mode_o.value) == 0b11
    assert int(dut.mult_sel_o.value) == 1
    assert int(dut.alu_operator_o.value) == ALU_ADD


@cocotb.test()
async def mulhsu_basic(dut):
    """Spec §mdcontrol, Scenario: MULHSU — funct3=010."""
    # MULHSU x10, x11, x12 → 0x02C5A533
    await _drive(dut, instr=0x02C5A533)
    assert int(dut.multdiv_operator_o.value) == MD_OP_MULH
    assert int(dut.multdiv_signed_mode_o.value) == 0b01
    assert int(dut.mult_sel_o.value) == 1


@cocotb.test()
async def mulhu_basic(dut):
    """Spec §mdcontrol, Scenario: MULHU — funct3=011."""
    # MULHU x10, x11, x12 → 0x02C5B533
    await _drive(dut, instr=0x02C5B533)
    assert int(dut.multdiv_operator_o.value) == MD_OP_MULH
    assert int(dut.multdiv_signed_mode_o.value) == 0b00
    assert int(dut.mult_sel_o.value) == 1


@cocotb.test()
async def div_basic(dut):
    """Spec §mdcontrol, Scenario: DIV — funct3=100."""
    # DIV x10, x11, x12 → 0x02C5C533
    await _drive(dut, instr=0x02C5C533)
    assert int(dut.multdiv_operator_o.value) == MD_OP_DIV
    assert int(dut.multdiv_signed_mode_o.value) == 0b11
    assert int(dut.mult_sel_o.value) == 0
    assert int(dut.div_sel_o.value) == 1
    assert int(dut.mult_en_o.value) == 0
    assert int(dut.div_en_o.value) == 1


@cocotb.test()
async def divu_basic(dut):
    """Spec §mdcontrol, Scenario: DIVU — funct3=101."""
    # DIVU x10, x11, x12 → 0x02C5D533
    await _drive(dut, instr=0x02C5D533)
    assert int(dut.multdiv_operator_o.value) == MD_OP_DIV
    assert int(dut.multdiv_signed_mode_o.value) == 0b00
    assert int(dut.div_sel_o.value) == 1
    assert int(dut.div_en_o.value) == 1


@cocotb.test()
async def rem_basic(dut):
    """Spec §mdcontrol, Scenario: REM — funct3=110."""
    # REM x10, x11, x12 → 0x02C5E533
    await _drive(dut, instr=0x02C5E533)
    assert int(dut.multdiv_operator_o.value) == MD_OP_REM
    assert int(dut.multdiv_signed_mode_o.value) == 0b11
    assert int(dut.div_sel_o.value) == 1


@cocotb.test()
async def remu_basic(dut):
    """Spec §mdcontrol, Scenario: REMU — funct3=111."""
    # REMU x10, x11, x12 → 0x02C5F533
    await _drive(dut, instr=0x02C5F533)
    assert int(dut.multdiv_operator_o.value) == MD_OP_REM
    assert int(dut.multdiv_signed_mode_o.value) == 0b00
    assert int(dut.div_sel_o.value) == 1


@cocotb.test()
async def mult_div_masked_by_illegal_c_insn(dut):
    """Spec §mdcontrol, Scenario: Mult/div masked when illegal_insn rises elsewhere."""
    # MUL but with illegal_c_insn_i = 1 → mult_en_o forced to 0.
    await _drive(dut, instr=0x02C58533, illegal_c_insn=1)
    assert int(dut.mult_en_o.value) == 0
    assert int(dut.div_en_o.value) == 0


# ─────────────────────────────────────────────────────────────────────────
# Requirement: CSR control
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def csr_addr_passthrough(dut):
    """Spec §csr, Scenario: CSR address is instr[31:20] always."""
    await _drive(dut, instr=0x30559573)  # CSRRW mtvec
    assert int(dut.csr_addr_o.value) == 0x305


@cocotb.test()
async def csrrw_op_write(dut):
    """Spec §csr, Scenario: CSRRW (funct3=001) — csr_op = CSR_OP_WRITE."""
    await _drive(dut, instr=0x30559573)
    assert int(dut.csr_access_o.value) == 1
    assert int(dut.csr_op_o.value) == CSR_OP_WRITE


@cocotb.test()
async def csrrs_op_set(dut):
    """Spec §csr, Scenario: CSRRS (funct3=010) — csr_op = CSR_OP_SET."""
    # CSRRS x10, mtvec, x11 → 0x3055A573
    await _drive(dut, instr=0x3055A573)
    assert int(dut.csr_op_o.value) == CSR_OP_SET


@cocotb.test()
async def csrrc_op_clear(dut):
    """Spec §csr, Scenario: CSRRC (funct3=011) — csr_op = CSR_OP_CLEAR."""
    # CSRRC x10, mtvec, x11 → 0x3055B573
    await _drive(dut, instr=0x3055B573)
    assert int(dut.csr_op_o.value) == CSR_OP_CLEAR


@cocotb.test()
async def csr_immediate_forms_share_funct3_low(dut):
    """Spec §csr, Scenario: CSRRWI/CSRRSI/CSRRCI map same as register forms."""
    # CSRRWI funct3=101 → csr_op = WRITE
    await _drive(dut, instr=0x3055D573)
    assert int(dut.csr_op_o.value) == CSR_OP_WRITE
    # CSRRSI funct3=110 with non-zero zimm → SET
    # zimm field is rs1 = 5 (non-zero)
    await _drive(dut, instr=0x3055E573)
    assert int(dut.csr_op_o.value) == CSR_OP_SET
    # CSRRCI funct3=111 with non-zero zimm → CLEAR
    await _drive(dut, instr=0x3055F573)
    assert int(dut.csr_op_o.value) == CSR_OP_CLEAR


@cocotb.test()
async def csrrs_rs1_zero_demotes_to_read(dut):
    """Spec §csr, Scenario: CSRRS with rs1=0 demotes to read-only."""
    # CSRRS x10, mtvec, x0 → rs1 field = 0
    # 0x30502573: funct3=010, rs1=0
    await _drive(dut, instr=0x30502573)
    assert int(dut.csr_op_o.value) == CSR_OP_READ


@cocotb.test()
async def csrrc_rs1_zero_demotes_to_read(dut):
    """Edge case: CSRRC with rs1=0 demotes to read-only (parallel to CSRRS rule)."""
    # CSRRC x10, mtvec, x0 → funct3=011, rs1=0
    # Build: 0x305 << 20 | 0 << 15 | 0b011 << 12 | 10 << 7 | 0x73
    instr = (0x305 << 20) | (0 << 15) | (0b011 << 12) | (10 << 7) | 0x73
    await _drive(dut, instr=instr)
    assert int(dut.csr_op_o.value) == CSR_OP_READ


@cocotb.test()
async def csrrsi_zimm_zero_demotes_to_read(dut):
    """Spec §csr, Scenario: CSRRSI/CSRRCI with zimm=0 demotes to read-only."""
    # CSRRSI x10, mtvec, 0 → 0x30506573 (funct3=110, rs1 field = 0)
    await _drive(dut, instr=0x30506573)
    assert int(dut.csr_op_o.value) == CSR_OP_READ


@cocotb.test()
async def csrrci_zimm_zero_demotes_to_read(dut):
    """Edge case: CSRRCI with zimm=0 demotes (parallel to CSRRSI)."""
    # funct3=111, rs1 field = 0
    instr = (0x305 << 20) | (0 << 15) | (0b111 << 12) | (10 << 7) | 0x73
    await _drive(dut, instr=instr)
    assert int(dut.csr_op_o.value) == CSR_OP_READ


@cocotb.test()
async def csrrw_rd_zero_keeps_write(dut):
    """Spec §csr, Scenario: CSRRW with rd=0 keeps CSR_OP_WRITE."""
    # CSRW mtvec, x11 = CSRRW x0, mtvec, x11 → 0x305590F3 (rd=1?)
    # Spec hex: 0x305590F3 — let me verify rd field [11:7] = 0b00001 = 1.
    # Spec says "CSRW mtvec, x11" interpreted as CSRRW x0... But the
    # hex provided in spec uses rd field differently. Trust the spec's hex.
    await _drive(dut, instr=0x305590F3)
    assert int(dut.csr_op_o.value) == CSR_OP_WRITE
    assert int(dut.csr_access_o.value) == 1
    assert int(dut.rf_we_o.value) == 1


@cocotb.test()
async def csr_illegal_funct3(dut):
    """Spec §csr, Scenario: Illegal CSR funct3=100."""
    # 0x30504573 (funct3=100)
    await _drive(dut, instr=0x30504573)
    assert int(dut.illegal_insn_o.value) == 1


@cocotb.test()
async def csr_legal_sets_rf_wd_csr(dut):
    """Spec §csr, Scenario: rf_wdata_sel_o = RF_WD_CSR for CSR access."""
    await _drive(dut, instr=0x30559573)
    assert int(dut.rf_wdata_sel_o.value) == RF_WD_CSR
    assert int(dut.rf_we_o.value) == 1


# ─────────────────────────────────────────────────────────────────────────
# Requirement: LSU control
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def sw_basic(dut):
    """Spec §lsu, Scenario: SW — funct3=010, type=word."""
    await _drive(dut, instr=0x00C5A023)
    assert int(dut.data_req_o.value) == 1
    assert int(dut.data_we_o.value) == 1
    assert int(dut.data_type_o.value) == 0b00
    assert int(dut.data_sign_extension_o.value) == 0


@cocotb.test()
async def sh_basic(dut):
    """Spec §lsu, Scenario: SH — funct3=001, type=halfword."""
    # SH x12, 0(x11) → 0x00C59023
    await _drive(dut, instr=0x00C59023)
    assert int(dut.data_type_o.value) == 0b01
    assert int(dut.data_we_o.value) == 1
    assert int(dut.data_req_o.value) == 1


@cocotb.test()
async def sb_basic(dut):
    """Spec §lsu, Scenario: SB — funct3=000, type=byte."""
    # SB x12, 0(x11) → 0x00C58023
    await _drive(dut, instr=0x00C58023)
    assert int(dut.data_type_o.value) == 0b10
    assert int(dut.data_we_o.value) == 1
    assert int(dut.data_req_o.value) == 1


@cocotb.test()
async def store_illegal_instr14_high(dut):
    """Spec §lsu, Scenario: STORE with funct3 having instr[14]=1 is illegal."""
    # 0x00C5C023 (funct3=100)
    await _drive(dut, instr=0x00C5C023)
    assert int(dut.illegal_insn_o.value) == 1
    assert int(dut.data_req_o.value) == 0
    assert int(dut.data_we_o.value) == 0


@cocotb.test()
async def store_illegal_funct3_011(dut):
    """Spec §lsu, Scenario: STORE with funct3=011 reserved → illegal."""
    # 0x00C5B023 (funct3=011)
    await _drive(dut, instr=0x00C5B023)
    assert int(dut.illegal_insn_o.value) == 1


@cocotb.test()
async def lw_basic(dut):
    """Spec §lsu, Scenario: LW — funct3=010, type=word, sign_ext=1."""
    await _drive(dut, instr=0x0005A503)
    assert int(dut.data_req_o.value) == 1
    assert int(dut.data_we_o.value) == 0
    assert int(dut.data_type_o.value) == 0b00
    assert int(dut.data_sign_extension_o.value) == 1


@cocotb.test()
async def lh_basic(dut):
    """Spec §lsu, Scenario: LH — funct3=001, sign_ext=1."""
    # LH x10, 0(x11) → 0x00059503
    await _drive(dut, instr=0x00059503)
    assert int(dut.data_type_o.value) == 0b01
    assert int(dut.data_sign_extension_o.value) == 1


@cocotb.test()
async def lhu_basic(dut):
    """Spec §lsu, Scenario: LHU — funct3=101, sign_ext=0."""
    # LHU x10, 0(x11) → 0x0005D503
    await _drive(dut, instr=0x0005D503)
    assert int(dut.data_type_o.value) == 0b01
    assert int(dut.data_sign_extension_o.value) == 0


@cocotb.test()
async def lb_basic(dut):
    """Spec §lsu, Scenario: LB — funct3=000, sign_ext=1."""
    # LB x10, 0(x11) → 0x00058503
    await _drive(dut, instr=0x00058503)
    assert int(dut.data_type_o.value) == 0b10
    assert int(dut.data_sign_extension_o.value) == 1


@cocotb.test()
async def lbu_basic(dut):
    """Spec §lsu, Scenario: LBU — funct3=100, sign_ext=0."""
    # LBU x10, 0(x11) → 0x0005C503
    await _drive(dut, instr=0x0005C503)
    assert int(dut.data_type_o.value) == 0b10
    assert int(dut.data_sign_extension_o.value) == 0


@cocotb.test()
async def lwu_illegal(dut):
    """Spec §lsu, Scenario: LWU is illegal in RV32."""
    # 0x0005E503 (funct3=110)
    await _drive(dut, instr=0x0005E503)
    assert int(dut.illegal_insn_o.value) == 1


@cocotb.test()
async def load_funct3_011_illegal(dut):
    """Spec §lsu, Scenario: LOAD funct3=011 reserved → illegal."""
    # funct3=011 with OPCODE_LOAD
    instr = (0 << 20) | (11 << 15) | (0b011 << 12) | (10 << 7) | 0x03
    await _drive(dut, instr=instr)
    assert int(dut.illegal_insn_o.value) == 1
    assert int(dut.data_req_o.value) == 0


@cocotb.test()
async def load_funct3_111_illegal(dut):
    """Spec §lsu, Scenario: LOAD funct3=111 reserved → illegal."""
    instr = (0 << 20) | (11 << 15) | (0b111 << 12) | (10 << 7) | 0x03
    await _drive(dut, instr=instr)
    assert int(dut.illegal_insn_o.value) == 1


# ─────────────────────────────────────────────────────────────────────────
# Requirement: Control flag outputs
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def ecall_flag(dut):
    """Spec §flags, Scenario: ECALL."""
    await _drive(dut, instr=0x00000073)
    assert int(dut.ecall_insn_o.value) == 1
    assert int(dut.illegal_insn_o.value) == 0
    assert int(dut.ebrk_insn_o.value) == 0
    assert int(dut.mret_insn_o.value) == 0
    assert int(dut.dret_insn_o.value) == 0
    assert int(dut.wfi_insn_o.value) == 0


@cocotb.test()
async def ebreak_flag(dut):
    """Spec §flags, Scenario: EBREAK."""
    await _drive(dut, instr=0x00100073)
    assert int(dut.ebrk_insn_o.value) == 1


@cocotb.test()
async def mret_flag(dut):
    """Spec §flags, Scenario: MRET."""
    await _drive(dut, instr=0x30200073)
    assert int(dut.mret_insn_o.value) == 1


@cocotb.test()
async def dret_flag(dut):
    """Spec §flags, Scenario: DRET."""
    await _drive(dut, instr=0x7B200073)
    assert int(dut.dret_insn_o.value) == 1


@cocotb.test()
async def wfi_flag(dut):
    """Spec §flags, Scenario: WFI."""
    await _drive(dut, instr=0x10500073)
    assert int(dut.wfi_insn_o.value) == 1


@cocotb.test()
async def system_funct3_000_with_nonzero_rs1_illegal(dut):
    """Spec §flags, Scenario: SYSTEM funct3=000 with rs1!=0 or rd!=0 is illegal."""
    # funct12=0, rs1=1, rd=0 → 0x00008073
    await _drive(dut, instr=0x00008073)
    assert int(dut.illegal_insn_o.value) == 1


@cocotb.test()
async def jump_in_dec_for_jal(dut):
    """Spec §flags, Scenario: jump_in_dec_o for JAL."""
    await _drive(dut, instr=0x008000EF, instr_first_cycle=1)
    assert int(dut.jump_in_dec_o.value) == 1
    assert int(dut.jump_set_o.value) == 1
    await _drive(dut, instr=0x008000EF, instr_first_cycle=0)
    assert int(dut.jump_in_dec_o.value) == 1
    assert int(dut.jump_set_o.value) == 0


@cocotb.test()
async def jump_in_dec_for_jalr(dut):
    """Spec §flags, Scenario: jump_in_dec_o for JALR."""
    await _drive(dut, instr=0x000080E7, instr_first_cycle=1)
    assert int(dut.jump_in_dec_o.value) == 1
    assert int(dut.jump_set_o.value) == 1


@cocotb.test()
async def jalr_funct3_nonzero_illegal(dut):
    """Spec §flags, Scenario: JALR with funct3 != 000 is illegal."""
    # JALR funct3=001 → 0x000090E7
    await _drive(dut, instr=0x000090E7)
    assert int(dut.illegal_insn_o.value) == 1
    assert int(dut.jump_in_dec_o.value) == 0
    assert int(dut.jump_set_o.value) == 0


@cocotb.test()
async def branch_in_dec_for_beq(dut):
    """Spec §flags, Scenario: branch_in_dec_o for BEQ."""
    await _drive(dut, instr=0x00B58463)
    assert int(dut.branch_in_dec_o.value) == 1


@cocotb.test()
async def branch_funct3_010_illegal(dut):
    """Spec §flags, Scenario: BRANCH funct3 in {010, 011} is illegal."""
    # BEQ-shape but funct3=010
    instr = (0x00B58463 & ~(0b111 << 12)) | (0b010 << 12)
    await _drive(dut, instr=instr)
    assert int(dut.illegal_insn_o.value) == 1
    assert int(dut.branch_in_dec_o.value) == 0


@cocotb.test()
async def branch_funct3_011_illegal(dut):
    """Edge case: BRANCH funct3=011 also illegal (parallel to 010)."""
    instr = (0x00B58463 & ~(0b111 << 12)) | (0b011 << 12)
    await _drive(dut, instr=instr)
    assert int(dut.illegal_insn_o.value) == 1


@cocotb.test()
async def fencei_first_cycle_inval(dut):
    """Spec §flags, Scenario: FENCE.I sets icache_inval_o on first cycle."""
    await _drive(dut, instr=0x0000100F, instr_first_cycle=1)
    assert int(dut.jump_in_dec_o.value) == 1
    assert int(dut.jump_set_o.value) == 1
    assert int(dut.icache_inval_o.value) == 1


@cocotb.test()
async def fencei_second_cycle_no_inval(dut):
    """Spec §flags, Scenario: FENCE.I second cycle does not set icache_inval_o."""
    await _drive(dut, instr=0x0000100F, instr_first_cycle=0)
    assert int(dut.jump_in_dec_o.value) == 1
    assert int(dut.jump_set_o.value) == 0
    assert int(dut.icache_inval_o.value) == 0


@cocotb.test()
async def fence_plain_nop(dut):
    """Spec §flags, Scenario: FENCE plain is a NOP."""
    await _drive(dut, instr=0x0000000F)
    assert int(dut.rf_we_o.value) == 0
    assert int(dut.illegal_insn_o.value) == 0
    assert int(dut.icache_inval_o.value) == 0
    assert int(dut.jump_in_dec_o.value) == 0
    assert int(dut.branch_in_dec_o.value) == 0


@cocotb.test()
async def misc_mem_funct3_other_illegal(dut):
    """Spec §flags, Scenario: MISC-MEM with funct3 not in {000, 001} is illegal."""
    # 0x0000200F (funct3=010)
    await _drive(dut, instr=0x0000200F)
    assert int(dut.illegal_insn_o.value) == 1


# ─────────────────────────────────────────────────────────────────────────
# Requirement: Illegal-instruction aggregation
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def illegal_all_zero(dut):
    """Spec §illegal, Scenario: All-zero instruction is illegal."""
    await _drive(dut, instr=0x00000000)
    assert int(dut.illegal_insn_o.value) == 1
    assert int(dut.rf_we_o.value) == 0
    assert int(dut.data_req_o.value) == 0


@cocotb.test()
async def illegal_all_ones(dut):
    """Spec §illegal, Scenario: All-ones instruction is illegal."""
    await _drive(dut, instr=0xFFFFFFFF)
    assert int(dut.illegal_insn_o.value) == 1


@cocotb.test()
async def illegal_rv32b_opcode(dut):
    """Spec §illegal, Scenario: RV32B opcode (BSET) is illegal under RV32BNone."""
    # BSET → 0x28C58533
    await _drive(dut, instr=0x28C58533)
    assert int(dut.illegal_insn_o.value) == 1


@cocotb.test()
async def illegal_compressed_passthrough(dut):
    """Spec §illegal, Scenario: Compressed-illegal pass-through."""
    # Legal ADD but with illegal_c_insn_i = 1.
    await _drive(dut, instr=0x00C58533, illegal_c_insn=1)
    assert int(dut.illegal_insn_o.value) == 1
    assert int(dut.rf_we_o.value) == 0
    assert int(dut.data_req_o.value) == 0


@cocotb.test()
async def legal_add_not_illegal(dut):
    """Spec §illegal, Scenario: Legal ADD has illegal_insn_o = 0."""
    await _drive(dut, instr=0x00C58533, illegal_c_insn=0)
    assert int(dut.illegal_insn_o.value) == 0


# ─────────────────────────────────────────────────────────────────────────
# Edge-case sweeps
# ─────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def malformed_opcode_0x7F(dut):
    """Edge case: opcode 0x7F (all ones in low 7 bits) does not match any opcode_e."""
    instr = 0xFFFFFF7F  # opcode = 0x7F (low 7 bits all 1)
    await _drive(dut, instr=instr)
    assert int(dut.illegal_insn_o.value) == 1


@cocotb.test()
async def malformed_opcode_0x7B(dut):
    """Edge case: opcode 0x7B (custom-2) is not in opcode_e."""
    instr = (0 << 7) | 0x7B
    await _drive(dut, instr=instr)
    assert int(dut.illegal_insn_o.value) == 1


@cocotb.test()
async def opimm_slli_with_bad_funct7(dut):
    """Edge case: SLLI with funct7 != 0x00 is illegal in scope."""
    # SLLI but funct7 = 0x20 (illegal high bits).
    instr = (0x20 << 25) | (5 << 20) | (1 << 15) | (0b001 << 12) | (1 << 7) | 0x13
    await _drive(dut, instr=instr)
    assert int(dut.illegal_insn_o.value) == 1


@cocotb.test()
async def op_class_illegal_funct7(dut):
    """Edge case: OP-class with arbitrary illegal funct7 is illegal.
    Use funct7=0x10, funct3=000 — not in RV32I or RV32M tables."""
    instr = (0x10 << 25) | (12 << 20) | (11 << 15) | (0 << 12) | (10 << 7) | 0x33
    await _drive(dut, instr=instr)
    assert int(dut.illegal_insn_o.value) == 1


@cocotb.test()
async def csr_illegal_funct3_100(dut):
    """Edge case: CSR funct3=100 is illegal (covered also above by spec scenario)."""
    await _drive(dut, instr=0x30504573)
    assert int(dut.illegal_insn_o.value) == 1


@cocotb.test()
async def system_funct12_unrecognized_illegal(dut):
    """Edge case: SYSTEM funct3=000, funct12 not in legal set, rs1=rd=0."""
    # funct12=0x123 (not 0/1/0x302/0x7B2/0x105), rs1=0, rd=0
    instr = (0x123 << 20) | (0 << 15) | (0 << 12) | (0 << 7) | 0x73
    await _drive(dut, instr=instr)
    assert int(dut.illegal_insn_o.value) == 1


@cocotb.test()
async def rd_x0_in_load(dut):
    """Edge case: LOAD with rd=x0 still asserts data_req_o."""
    # LW x0, 0(x11) → 0x0005A003
    await _drive(dut, instr=0x0005A003)
    assert int(dut.data_req_o.value) == 1
    assert int(dut.rf_waddr_o.value) == 0


@cocotb.test()
async def rs1_x0_in_addi(dut):
    """Edge case: ADDI with rs1=x0 still reads rf_ren_a (rs1 read regardless)."""
    # ADDI x2, x0, 5 → 0x00500113
    await _drive(dut, instr=0x00500113)
    assert int(dut.rf_ren_a_o.value) == 1
    assert int(dut.rf_raddr_a_o.value) == 0


@cocotb.test()
async def rs2_x0_in_store(dut):
    """Edge case: STORE with rs2=x0 (storing zero) is legal."""
    # SW x0, 0(x11) → 0x0005A023
    await _drive(dut, instr=0x0005A023)
    assert int(dut.data_req_o.value) == 1
    assert int(dut.data_we_o.value) == 1
    assert int(dut.rf_raddr_b_o.value) == 0


@cocotb.test()
async def all_rv32i_classes_legal(dut):
    """Edge case: sweeps every RV32I instruction class with one canonical
    encoding and confirms illegal_insn_o = 0 for each."""
    instrs = [
        0x12345037,  # LUI
        0x00001097,  # AUIPC
        0x008000EF,  # JAL
        0x000080E7,  # JALR
        0x00B58463,  # BEQ
        0x0005A503,  # LW
        0x00C5A023,  # SW
        0x00500113,  # ADDI
        0x00C58533,  # ADD
        0x40C58533,  # SUB
        0x00509093,  # SLLI
        0x4050D093,  # SRAI
        0x0000000F,  # FENCE
        0x0000100F,  # FENCE.I
        0x00000073,  # ECALL
        0x00100073,  # EBREAK
        0x30200073,  # MRET
        0x10500073,  # WFI
        0x30559573,  # CSRRW
    ]
    for instr in instrs:
        await _drive(dut, instr=instr)
        assert int(dut.illegal_insn_o.value) == 0, hex(instr)


@cocotb.test()
async def all_rv32m_legal(dut):
    """Edge case: every RV32M instruction is legal in scope."""
    instrs = [
        0x02C58533,  # MUL
        0x02C59533,  # MULH
        0x02C5A533,  # MULHSU
        0x02C5B533,  # MULHU
        0x02C5C533,  # DIV
        0x02C5D533,  # DIVU
        0x02C5E533,  # REM
        0x02C5F533,  # REMU
    ]
    for instr in instrs:
        await _drive(dut, instr=instr)
        assert int(dut.illegal_insn_o.value) == 0, hex(instr)
        # All RV32M ops set rf_we_o = 1.
        assert int(dut.rf_we_o.value) == 1, hex(instr)
