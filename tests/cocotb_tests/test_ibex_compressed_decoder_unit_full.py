"""Full-regression cocotb scenarios for `ibex_compressed_decoder`.

Walks every `#### Scenario:` from `specs/compressed_decoder/spec.md`
plus edge cases the spec implies but does not enumerate
exhaustively:

  * Every Zca compressed instruction class in q0 / q1 / q2.
  * Every Zcb compressed instruction class (c.lbu/c.lh/c.lhu/c.sb/
    c.sh/c.zext.b/c.sext.b/c.zext.h/c.sext.h/c.not/c.mul). Per
    `spec-notes.md` item 3, the Zcb expansions (c.zext.b, c.sext.b,
    c.zext.h, c.sext.h, c.not, c.lh half-imm) and the Zcmp
    `cm.mvsa01`/`cm.mva01s` register mapping were derived
    algebraically from the RTL formulas WITHOUT external
    cross-check; this file pins their exact 32-bit hex so a
    formula-side bug surfaces as a test failure.
  * Every Zcmp multi-cycle expansion: cm.push (rlist=4..15),
    cm.pop, cm.popret, cm.popretz, cm.mvsa01, cm.mva01s.
  * 32-bit pass-through with multiple distinct uncompressed
    instructions.
  * Reserved compressed encodings on every quadrant.
  * Sign-extension boundaries on c.addi (positive max, negative max).

The non-Zcmp tests pin `clk_i = 0`, `rst_ni = 1` and never toggle
the clock; the Zcmp multi-cycle tests run a real 10 ns clock,
hold reset for two cycles, then walk the FSM step by step with
`RisingEdge(clk_i)`, sampling `instr_o` and `gets_expanded_o`
between edges.

In-scope parameters (per `proposal.md`): `RV32ZC = RV32ZcaZcbZcmp`
(=3), `ResetAll = 0`.
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


# ── Enum encodings (from spec §"Enum encodings") ─────────────────────────

INSTR_NOT_EXPANDED = 0
INSTR_EXPANDED = 1
INSTR_EXPANDED_LAST = 2


# ── Driver ───────────────────────────────────────────────────────────────
async def _drive(
    dut,
    *,
    instr: int,
    valid: int = 1,
    id_in_ready: int = 1,
):
    """Apply combinational inputs and settle. `clk_i = 0`, `rst_ni = 1`."""
    dut.clk_i.value = 0
    dut.rst_ni.value = 1
    dut.valid_i.value = valid
    dut.id_in_ready_i.value = id_in_ready
    dut.instr_i.value = instr & 0xFFFF_FFFF
    await Timer(1, "ns")


async def _zcmp_reset(dut, *, instr: int):
    """Bring up a real clock, hold reset, then drive instr stable."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    dut.rst_ni.value = 0
    dut.valid_i.value = 0
    dut.id_in_ready_i.value = 0
    dut.instr_i.value = 0
    await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    dut.valid_i.value = 1
    dut.id_in_ready_i.value = 1
    dut.instr_i.value = instr & 0xFFFF_FFFF
    await Timer(1, "ns")


async def _zcmp_step(dut):
    """Advance one FSM sub-step and settle."""
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")


# ── Pass-through ─────────────────────────────────────────────────────────

@cocotb.test()
async def passthrough_addi(dut):
    """Pass-through of canonical RV32 ADDI."""
    await _drive(dut, instr=0x00100093)
    assert int(dut.instr_o.value) == 0x00100093
    assert int(dut.is_compressed_o.value) == 0
    assert int(dut.illegal_instr_o.value) == 0
    assert int(dut.gets_expanded_o.value) == INSTR_NOT_EXPANDED


@cocotb.test()
async def passthrough_ebreak(dut):
    """Pass-through of canonical RV32 EBREAK."""
    await _drive(dut, instr=0x00100073)
    assert int(dut.instr_o.value) == 0x00100073
    assert int(dut.is_compressed_o.value) == 0
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def passthrough_random_rv32(dut):
    """Pass-through with two distinct uncompressed words; output mirrors input."""
    for word in (0xFFFFFFFF, 0xDEADBEEF | 0x3, 0x00000003):
        await _drive(dut, instr=word)
        assert int(dut.instr_o.value) == (word & 0xFFFF_FFFF)
        assert int(dut.is_compressed_o.value) == 0
        assert int(dut.illegal_instr_o.value) == 0


# ── q0 ───────────────────────────────────────────────────────────────────

@cocotb.test()
async def q0_c_addi4spn(dut):
    """c.addi4spn x8, sp, 4 -> addi x8, x2, 4."""
    await _drive(dut, instr=0x00000040)
    assert int(dut.instr_o.value) == 0x00410413
    assert int(dut.is_compressed_o.value) == 1
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q0_c_addi4spn_reserved_zero_imm(dut):
    """c.addi4spn with all-zero immediate -> illegal."""
    await _drive(dut, instr=0x00000000)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def q0_c_lw_zero(dut):
    """c.lw x8, 0(x9)."""
    await _drive(dut, instr=0x00004080)
    assert int(dut.instr_o.value) == 0x0004A403
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q0_c_lw_max(dut):
    """c.lw x15, 124(x14) — max immediate sub-encoding."""
    await _drive(dut, instr=0x00005F7C)
    assert int(dut.instr_o.value) == 0x07C72783
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q0_c_sw_zero(dut):
    """c.sw x8, 0(x9)."""
    await _drive(dut, instr=0x0000C080)
    assert int(dut.instr_o.value) == 0x0084A023


@cocotb.test()
async def q0_c_sw_off4(dut):
    """c.sw x14, 4(x14)."""
    await _drive(dut, instr=0x0000C358)
    assert int(dut.instr_o.value) == 0x00E72223


@cocotb.test()
async def q0_zcb_c_lbu(dut):
    """c.lbu x8, 0(x9) — q0/funct3=100, instr_i[12:10]=000."""
    await _drive(dut, instr=0x00008080)
    assert int(dut.instr_o.value) == 0x0004C403
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q0_zcb_c_lh_imm2(dut):
    """c.lh x8, 2(x9) — half-immediate via instr_i[5].
    Per spec-notes item 3, the c.lh half-imm logic was
    derived from the RTL formula without an external assembler
    cross-check; this pin guards against a formula-side bug."""
    await _drive(dut, instr=0x000084E0)
    assert int(dut.instr_o.value) == 0x00249403


@cocotb.test()
async def q0_zcb_c_sh_reserved_bit6(dut):
    """c.sh with instr_i[6]=1 -> illegal (defensive per RTL)."""
    # funct3=100 q0, instr_i[12:10]=011, instr_i[6]=1.
    instr = (0b100 << 13) | (0b011 << 10) | (1 << 6) | 0b00
    await _drive(dut, instr=instr)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def q0_zcb_unmapped_funct3sub(dut):
    """q0/funct3=100 with instr_i[12:10]=110 -> illegal."""
    instr = (0b100 << 13) | (0b110 << 10) | 0b00
    await _drive(dut, instr=instr)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def q0_reserved_funct3_001(dut):
    """q0/funct3=001 (c.fld) -> illegal."""
    await _drive(dut, instr=(0b001 << 13))
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def q0_reserved_funct3_111(dut):
    """q0/funct3=111 (c.fsd) -> illegal."""
    await _drive(dut, instr=(0b111 << 13))
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def q0_reserved_funct3_011(dut):
    """q0/funct3=011 -> illegal."""
    await _drive(dut, instr=(0b011 << 13))
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def q0_reserved_funct3_101(dut):
    """q0/funct3=101 -> illegal."""
    await _drive(dut, instr=(0b101 << 13))
    assert int(dut.illegal_instr_o.value) == 1


# ── q1 ───────────────────────────────────────────────────────────────────

@cocotb.test()
async def q1_c_nop(dut):
    """c.nop -> addi x0, x0, 0."""
    await _drive(dut, instr=0x00000001)
    assert int(dut.instr_o.value) == 0x00000013


@cocotb.test()
async def q1_c_addi_neg1(dut):
    """c.addi x1, x1, -1 — sign-bit set, imm = -1."""
    await _drive(dut, instr=0x000010FD)
    assert int(dut.instr_o.value) == 0xFFF08093


@cocotb.test()
async def q1_c_addi_pos_max(dut):
    """c.addi x1, x1, +31 — positive maximum 6-bit immediate."""
    # imm = 6'b011111 = 31, rd = x1, q1 funct3=000.
    # instr_i = {000, 0, 00001, 11111, 01} = 0x017D
    await _drive(dut, instr=0x000000FD)
    assert int(dut.instr_o.value) == 0x01F08093


@cocotb.test()
async def q1_c_addi_neg_max(dut):
    """c.addi x1, x1, -32 — negative maximum 6-bit immediate."""
    # imm = 6'b100000 = -32. instr_i = {000, 1, 00001, 00000, 01} = 0x1081
    await _drive(dut, instr=0x00001081)
    assert int(dut.instr_o.value) == 0xFE008093


@cocotb.test()
async def q1_c_jal_zero(dut):
    """c.jal +0 -> jal x1, 0 (RV32-only)."""
    await _drive(dut, instr=0x00002001)
    assert int(dut.instr_o.value) == 0x000000EF


@cocotb.test()
async def q1_c_j_zero(dut):
    """c.j +0 -> jal x0, 0."""
    await _drive(dut, instr=0x0000A001)
    assert int(dut.instr_o.value) == 0x0000006F


@cocotb.test()
async def q1_c_li_zero(dut):
    """c.li x1, 0 -> addi x1, x0, 0."""
    await _drive(dut, instr=0x00004081)
    assert int(dut.instr_o.value) == 0x00000093


@cocotb.test()
async def q1_c_li_neg1(dut):
    """c.li x2, -1 -> addi x2, x0, -1."""
    await _drive(dut, instr=0x0000517D)
    assert int(dut.instr_o.value) == 0xFFF00113


@cocotb.test()
async def q1_c_lui(dut):
    """c.lui x3, 1 -> lui x3, 1."""
    await _drive(dut, instr=0x00006185)
    assert int(dut.instr_o.value) == 0x000011B7


@cocotb.test()
async def q1_c_addi16sp(dut):
    """c.addi16sp +16 -> addi x2, x2, 16."""
    await _drive(dut, instr=0x00006141)
    assert int(dut.instr_o.value) == 0x01010113


@cocotb.test()
async def q1_c_lui_zero_imm_reserved(dut):
    """c.lui with zero imm -> illegal."""
    await _drive(dut, instr=0x00006181)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def q1_c_srli(dut):
    """c.srli x8, x8, 1."""
    await _drive(dut, instr=0x00008005)
    assert int(dut.instr_o.value) == 0x00145413


@cocotb.test()
async def q1_c_srai(dut):
    """c.srai x9, x9, 31."""
    await _drive(dut, instr=0x000084FD)
    assert int(dut.instr_o.value) == 0x41F4D493


@cocotb.test()
async def q1_c_srli_shamt5_reserved(dut):
    """c.srli with shamt[5]=1 -> illegal."""
    # funct3=100, instr_i[12]=1, instr_i[11:10]=00, q=01
    instr = (0b100 << 13) | (1 << 12) | (0b00 << 10) | 0b01
    await _drive(dut, instr=instr)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def q1_c_andi_neg1(dut):
    """c.andi x8, x8, -1."""
    await _drive(dut, instr=0x0000987D)
    assert int(dut.instr_o.value) == 0xFFF47413


@cocotb.test()
async def q1_c_andi_zero(dut):
    """c.andi x15, x15, 0."""
    await _drive(dut, instr=0x00008B81)
    assert int(dut.instr_o.value) == 0x0007F793


@cocotb.test()
async def q1_c_sub(dut):
    """c.sub x8, x8, x9."""
    await _drive(dut, instr=0x00008C05)
    assert int(dut.instr_o.value) == 0x40940433


@cocotb.test()
async def q1_c_xor(dut):
    """c.xor x8, x8, x9."""
    await _drive(dut, instr=0x00008C25)
    assert int(dut.instr_o.value) == 0x00944433


@cocotb.test()
async def q1_c_or(dut):
    """c.or x8, x8, x9."""
    await _drive(dut, instr=0x00008C45)
    assert int(dut.instr_o.value) == 0x00946433


@cocotb.test()
async def q1_c_and(dut):
    """c.and x8, x8, x9."""
    await _drive(dut, instr=0x00008C65)
    assert int(dut.instr_o.value) == 0x00947433


@cocotb.test()
async def q1_c_subw_reserved_rv32(dut):
    """c.subw (RV64-only) -> illegal in RV32."""
    # funct3=100, instr_i[12]=1, instr_i[11:10]=11, instr_i[6:5]=00, q=01.
    instr = (0b100 << 13) | (1 << 12) | (0b11 << 10) | (0b00 << 5) | 0b01
    await _drive(dut, instr=instr)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def q1_c_mul(dut):
    """c.mul x8, x8, x9 (Zcb).
    Per spec-notes item 3, the Zcb expansions were RTL-formula-derived
    without external assembler cross-check; this pins the hex."""
    await _drive(dut, instr=0x00009C45)
    assert int(dut.instr_o.value) == 0x02940433


@cocotb.test()
async def q1_c_zext_b(dut):
    """c.zext.b x8 -> andi x8, x8, 0xff. Spec-notes item 3 pin."""
    await _drive(dut, instr=0x00009C61)
    assert int(dut.instr_o.value) == 0x0FF47413


@cocotb.test()
async def q1_c_sext_b(dut):
    """c.sext.b x8 -> sext.b x8, x8 (Zbb). Spec-notes item 3 pin."""
    # funct3=100, instr_i[12]=1, instr_i[11:10]=11, instr_i[9:7]=000,
    # instr_i[6:5]=11, instr_i[4:2]=001, q=01.
    instr = (
        (0b100 << 13) | (1 << 12) | (0b11 << 10) | (0b000 << 7)
        | (0b11 << 5) | (0b001 << 2) | 0b01
    )
    await _drive(dut, instr=instr)
    # Expansion formula: {7'b0110000, 5'b00100, 2'b01, instr_i[9:7]=000,
    #                     3'b001, 2'b01, instr_i[9:7]=000, OPCODE_OP_IMM}
    # = 0110000 00100 01000 001 01000 0010011 = 0x60441413
    assert int(dut.instr_o.value) == 0x60441413


@cocotb.test()
async def q1_c_zext_h(dut):
    """c.zext.h x8 -> zext.h x8, x8 (Zbb). Spec-notes item 3 pin."""
    # funct3=100, [12]=1, [11:10]=11, [9:7]=000, [6:5]=11, [4:2]=010, q=01.
    instr = (
        (0b100 << 13) | (1 << 12) | (0b11 << 10) | (0b000 << 7)
        | (0b11 << 5) | (0b010 << 2) | 0b01
    )
    await _drive(dut, instr=instr)
    # {7'b0000100, 5'b0, 2'b01, 000, 3'b100, 2'b01, 000, OPCODE_OP}
    # = 0000100 00000 01000 100 01000 0110011 = 0x08044433
    assert int(dut.instr_o.value) == 0x08044433


@cocotb.test()
async def q1_c_sext_h(dut):
    """c.sext.h x8 -> sext.h x8, x8 (Zbb). Spec-notes item 3 pin."""
    # [4:2]=011.
    instr = (
        (0b100 << 13) | (1 << 12) | (0b11 << 10) | (0b000 << 7)
        | (0b11 << 5) | (0b011 << 2) | 0b01
    )
    await _drive(dut, instr=instr)
    # {7'b0110000, 5'b00101, 2'b01, 000, 3'b001, 2'b01, 000, OPCODE_OP_IMM}
    # = 0110000 00101 01000 001 01000 0010011 = 0x60541413
    assert int(dut.instr_o.value) == 0x60541413


@cocotb.test()
async def q1_c_not(dut):
    """c.not x8 -> xori x8, x8, -1. Spec-notes item 3 pin."""
    await _drive(dut, instr=0x00009C75)
    assert int(dut.instr_o.value) == 0xFFF44413


@cocotb.test()
async def q1_c_zext_w_reserved(dut):
    """c.zext.w (RV64-only, instr_i[4:2]=100) -> illegal."""
    instr = (
        (0b100 << 13) | (1 << 12) | (0b11 << 10) | (0b000 << 7)
        | (0b11 << 5) | (0b100 << 2) | 0b01
    )
    await _drive(dut, instr=instr)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def q1_c_zcb_reserved_110(dut):
    """Zcb sub-quadrant instr_i[4:2]=110 -> illegal."""
    instr = (
        (0b100 << 13) | (1 << 12) | (0b11 << 10) | (0b000 << 7)
        | (0b11 << 5) | (0b110 << 2) | 0b01
    )
    await _drive(dut, instr=instr)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def q1_c_beqz_zero(dut):
    """c.beqz x8, 0 -> beq x8, x0, 0."""
    await _drive(dut, instr=0x0000C001)
    assert int(dut.instr_o.value) == 0x00040063


@cocotb.test()
async def q1_c_bnez_off4(dut):
    """c.bnez x8, +4 -> bne x8, x0, 4."""
    await _drive(dut, instr=0x0000E011)
    assert int(dut.instr_o.value) == 0x00041263


# ── q2 ───────────────────────────────────────────────────────────────────

@cocotb.test()
async def q2_c_slli(dut):
    """c.slli x1, x1, 1 -> slli x1, x1, 1."""
    await _drive(dut, instr=0x00000086)
    assert int(dut.instr_o.value) == 0x00109093


@cocotb.test()
async def q2_c_slli_shamt5_reserved(dut):
    """c.slli with shamt[5]=1 -> illegal."""
    # funct3=000, [12]=1, q=10.
    instr = (0b000 << 13) | (1 << 12) | 0b10
    await _drive(dut, instr=instr)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def q2_c_lwsp(dut):
    """c.lwsp x1, 0 -> lw x1, 0(x2)."""
    await _drive(dut, instr=0x00004082)
    assert int(dut.instr_o.value) == 0x00012083


@cocotb.test()
async def q2_c_lwsp_rd_zero_reserved(dut):
    """c.lwsp with rd=x0 -> illegal."""
    # funct3=010, [11:7]=00000, q=10.
    instr = (0b010 << 13) | 0b10
    await _drive(dut, instr=instr)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def q2_c_mv(dut):
    """c.mv x8, x9 -> add x8, x0, x9."""
    await _drive(dut, instr=0x00008426)
    assert int(dut.instr_o.value) == 0x00900433


@cocotb.test()
async def q2_c_jr(dut):
    """c.jr x1 -> jalr x0, x1, 0."""
    await _drive(dut, instr=0x00008082)
    assert int(dut.instr_o.value) == 0x00008067


@cocotb.test()
async def q2_c_jr_x0_reserved(dut):
    """c.jr x0 -> illegal."""
    await _drive(dut, instr=0x00008002)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def q2_c_add(dut):
    """c.add x8, x8, x9 -> add x8, x8, x9."""
    await _drive(dut, instr=0x00009426)
    assert int(dut.instr_o.value) == 0x00940433


@cocotb.test()
async def q2_c_ebreak(dut):
    """c.ebreak -> 0x00100073."""
    await _drive(dut, instr=0x00009002)
    assert int(dut.instr_o.value) == 0x00100073


@cocotb.test()
async def q2_c_jalr(dut):
    """c.jalr x1 -> jalr x1, x1, 0."""
    await _drive(dut, instr=0x00009082)
    assert int(dut.instr_o.value) == 0x000080E7


@cocotb.test()
async def q2_c_swsp(dut):
    """c.swsp x1, 0 -> sw x1, 0(x2)."""
    await _drive(dut, instr=0x0000C006)
    assert int(dut.instr_o.value) == 0x00112023


@cocotb.test()
async def q2_reserved_funct3_001(dut):
    """q2/funct3=001 -> illegal."""
    await _drive(dut, instr=(0b001 << 13) | 0b10)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def q2_reserved_funct3_011(dut):
    """q2/funct3=011 -> illegal."""
    await _drive(dut, instr=(0b011 << 13) | 0b10)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def q2_reserved_funct3_111(dut):
    """q2/funct3=111 -> illegal."""
    await _drive(dut, instr=(0b111 << 13) | 0b10)
    assert int(dut.illegal_instr_o.value) == 1


# ── Zcmp: cm.push ────────────────────────────────────────────────────────

@cocotb.test()
async def zcmp_cm_push_rlist4_full(dut):
    """cm.push {ra}, -16 — full FSM walk: store + addi."""
    await _zcmp_reset(dut, instr=0x0000B842)
    # CmIdle: store top reg.
    assert int(dut.instr_o.value) == 0xFE112E23
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED
    await _zcmp_step(dut)
    # CmPushDecrSp: addi x2, x2, -16.
    assert int(dut.instr_o.value) == 0xFF010113
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED_LAST


@cocotb.test()
async def zcmp_cm_push_rlist15_first_step(dut):
    """cm.push rlist=15 (boundary): first sub-step stores top reg.

    rlist=15 promotes internally to 5'd16, top reg = x27,
    stack_adj_base = 64. First store offset = -4 -> sw x27, -4(x2).
    """
    # funct3=101, [12:8]=11000, [7:4]=1111, [3:2]=00, q=10.
    instr = (
        (0b101 << 13) | (0b11000 << 8) | (0b1111 << 4) | (0b00 << 2) | 0b10
    )
    await _zcmp_reset(dut, instr=instr)
    # sw x27, -4(x2): {imm[11:5]=1111111, rs2=11011, rs1=00010, 010, imm[4:0]=11100, 0100011}
    # = 1111111 11011 00010 010 11100 0100011 = 0xFFB12E23
    assert int(dut.instr_o.value) == 0xFFB12E23
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED


@cocotb.test()
async def zcmp_cm_push_reserved_rlist2(dut):
    """cm.push rlist=2 -> illegal."""
    # funct3=101, [12:8]=11000, [7:4]=0010, q=10.
    instr = (0b101 << 13) | (0b11000 << 8) | (0b0010 << 4) | 0b10
    await _zcmp_reset(dut, instr=instr)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def zcmp_cm_push_reserved_rlist0(dut):
    """cm.push rlist=0 -> illegal."""
    instr = (0b101 << 13) | (0b11000 << 8) | (0b0000 << 4) | 0b10
    await _zcmp_reset(dut, instr=instr)
    assert int(dut.illegal_instr_o.value) == 1


# ── Zcmp: cm.pop / cm.popret / cm.popretz ───────────────────────────────

@cocotb.test()
async def zcmp_cm_pop_rlist4_full(dut):
    """cm.pop {ra}, +16 — full walk: lw, addi, last."""
    await _zcmp_reset(dut, instr=0x0000BA42)
    # CmIdle: lw x1, 12(x2).
    assert int(dut.instr_o.value) == 0x00C12083
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED
    await _zcmp_step(dut)
    # CmPopIncrSp: addi x2, x2, +16, INSTR_EXPANDED_LAST for cm.pop.
    assert int(dut.instr_o.value) == 0x01010113
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED_LAST


@cocotb.test()
async def zcmp_cm_popret_full(dut):
    """cm.popret {ra}, +16 — full walk includes jalr x0, x1, 0 last."""
    await _zcmp_reset(dut, instr=0x0000BE42)
    # CmIdle: lw x1, 12(x2).
    assert int(dut.instr_o.value) == 0x00C12083
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED
    await _zcmp_step(dut)
    # CmPopIncrSp: addi x2, x2, +16.
    assert int(dut.instr_o.value) == 0x01010113
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED
    await _zcmp_step(dut)
    # CmPopRetRa: jalr x0, x1, 0 — last.
    assert int(dut.instr_o.value) == 0x00008067
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED_LAST


@cocotb.test()
async def zcmp_cm_popretz_full(dut):
    """cm.popretz — full walk: lw, addi, addi a0 0, jalr."""
    await _zcmp_reset(dut, instr=0x0000BC42)
    # CmIdle: lw x1, 12(x2).
    assert int(dut.instr_o.value) == 0x00C12083
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED
    await _zcmp_step(dut)
    # CmPopIncrSp: addi x2, x2, +16.
    assert int(dut.instr_o.value) == 0x01010113
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED
    await _zcmp_step(dut)
    # CmPopZeroA0: addi a0, x0, 0.
    assert int(dut.instr_o.value) == 0x00000513
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED
    await _zcmp_step(dut)
    # CmPopRetRa: jalr x0, x1, 0 — last.
    assert int(dut.instr_o.value) == 0x00008067
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED_LAST


@cocotb.test()
async def zcmp_cm_pop_reserved_rlist3(dut):
    """cm.pop rlist=3 -> illegal."""
    instr = (0b101 << 13) | (0b11010 << 8) | (0b0011 << 4) | 0b10
    await _zcmp_reset(dut, instr=instr)
    assert int(dut.illegal_instr_o.value) == 1


# ── Zcmp: cm.mvsa01 / cm.mva01s ─────────────────────────────────────────

@cocotb.test()
async def zcmp_cm_mvsa01_full(dut):
    """cm.mvsa01 a0->s0, a1->s0 — both steps walked.
    Per spec-notes item 3, the cm_mvsa01 / cm_mva01s register
    mapping was derived algebraically from RTL formulas without
    external assembler cross-check; pinning hex here guards the
    formula."""
    await _zcmp_reset(dut, instr=0x0000AC22)
    # Step 1: addi x8, x10, 0.
    assert int(dut.instr_o.value) == 0x00050413
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED
    await _zcmp_step(dut)
    # Step 2: addi x8, x11, 0 (r2s'=000 -> x8, src=a1=x11).
    # {12'b0, x11=01011, 000, x8=01000, OPCODE_OP_IMM}
    # = 000000000000 01011 000 01000 0010011 = 0x00058413
    assert int(dut.instr_o.value) == 0x00058413
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED_LAST


@cocotb.test()
async def zcmp_cm_mva01s_full(dut):
    """cm.mva01s s0->a0, s0->a1 — both steps walked. Spec-notes item 3 pin."""
    await _zcmp_reset(dut, instr=0x0000AC62)
    # Step 1: addi a0=x10, x8, 0 = {12'b0, x8=01000, 000, x10=01010, 0010011}
    # = 000000000000 01000 000 01010 0010011 = 0x00040513
    assert int(dut.instr_o.value) == 0x00040513
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED
    await _zcmp_step(dut)
    # Step 2: addi a1=x11, x8, 0.
    assert int(dut.instr_o.value) == 0x00040593
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED_LAST


@cocotb.test()
async def zcmp_011_subq_reserved_00(dut):
    """Zcmp 011 sub-quadrant instr_i[6:5]=00 -> illegal."""
    # funct3=101, [12:10]=011, [6:5]=00, q=10.
    instr = (0b101 << 13) | (0b011 << 10) | (0b00 << 5) | 0b10
    await _zcmp_reset(dut, instr=instr)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def zcmp_011_subq_reserved_10(dut):
    """Zcmp 011 sub-quadrant instr_i[6:5]=10 -> illegal."""
    instr = (0b101 << 13) | (0b011 << 10) | (0b10 << 5) | 0b10
    await _zcmp_reset(dut, instr=instr)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def zcmp_unmapped_funct5(dut):
    """Zcmp default arm: q2/funct3=101, funct5=00000 -> illegal."""
    await _drive(dut, instr=0x0000A002)
    assert int(dut.illegal_instr_o.value) == 1


# ── Cross-cutting outputs ───────────────────────────────────────────────

@cocotb.test()
async def is_compressed_q0(dut):
    """is_compressed_o = 1 for compressed (LSBs != 11)."""
    await _drive(dut, instr=0x00000000)
    assert int(dut.is_compressed_o.value) == 1


@cocotb.test()
async def is_compressed_q1(dut):
    """is_compressed_o = 1 for q1 LSBs."""
    await _drive(dut, instr=0x00000001)
    assert int(dut.is_compressed_o.value) == 1


@cocotb.test()
async def is_compressed_q2(dut):
    """is_compressed_o = 1 for q2 LSBs."""
    await _drive(dut, instr=0x00000002)
    assert int(dut.is_compressed_o.value) == 1


@cocotb.test()
async def is_compressed_uncompressed(dut):
    """is_compressed_o = 0 for LSBs == 11."""
    await _drive(dut, instr=0x00000003)
    assert int(dut.is_compressed_o.value) == 0


@cocotb.test()
async def gets_expanded_gated_by_valid_low(dut):
    """gets_expanded_o forced to NOT_EXPANDED when valid_i=0 even on
    a cm.push pattern."""
    await _drive(dut, instr=0x0000B842, valid=0)
    assert int(dut.gets_expanded_o.value) == INSTR_NOT_EXPANDED


@cocotb.test()
async def gets_expanded_active_when_valid_high(dut):
    """gets_expanded_o = INSTR_EXPANDED on cm.push first sub-step
    with valid_i=1."""
    await _zcmp_reset(dut, instr=0x0000B842)
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED


@cocotb.test()
async def zcmp_fsm_stable_no_advance_when_valid_low(dut):
    """FSM held stable across a clock edge when valid_i=0."""
    await _zcmp_reset(dut, instr=0x0000B842)
    # In CmIdle. Drop valid_i and cross a clock edge.
    dut.valid_i.value = 0
    await Timer(1, "ns")
    assert int(dut.gets_expanded_o.value) == INSTR_NOT_EXPANDED
    await RisingEdge(dut.clk_i)
    # Restore valid_i — FSM should still be in CmIdle (sub-step 1
    # output, not sub-step 2's addi).
    dut.valid_i.value = 1
    await Timer(1, "ns")
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED
    assert int(dut.instr_o.value) == 0xFE112E23
