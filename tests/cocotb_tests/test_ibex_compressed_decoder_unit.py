"""Standalone cocotb scenarios for `ibex_compressed_decoder` (basic suite).

Each `@cocotb.test` covers one Requirement from
`specs/compressed_decoder/spec.md`, walking the single most
representative scenario from the spec for that requirement with a
real RVC encoding (hex pulled directly from the spec scenarios).

The decoder is mostly combinational; the only stateful slice is the
Zcmp FSM. Non-Zcmp tests pin `clk_i = 0`, `rst_ni = 1` and never
toggle the clock — the inputs settle with `Timer(1, "ns")`. The Zcmp
multi-cycle tests run a real 10ns clock, hold reset for two cycles,
then walk the FSM step by step with `RisingEdge(clk_i)`, sampling
`instr_o` and `gets_expanded_o` between edges.

In-scope parameters (per `proposal.md`): `RV32ZC = RV32ZcaZcbZcmp`
(=3), `ResetAll = 0`.

Enum integer encodings (from spec §"Enum encodings"):
  - `INSTR_NOT_EXPANDED  = 2'd0`
  - `INSTR_EXPANDED      = 2'd1`
  - `INSTR_EXPANDED_LAST = 2'd2`
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


# ── Enum encodings ───────────────────────────────────────────────────────

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
    """Apply combinational inputs and settle.

    Defaults: `clk_i = 0`, `rst_ni = 1` (SVA-only, never toggled in
    non-Zcmp tests), `valid_i = 1`, `id_in_ready_i = 1`. Each call
    overrides only what it needs.
    """
    dut.clk_i.value = 0
    dut.rst_ni.value = 1
    dut.valid_i.value = valid
    dut.id_in_ready_i.value = id_in_ready
    dut.instr_i.value = instr & 0xFFFF_FFFF
    await Timer(1, "ns")


async def _zcmp_reset(dut, *, instr: int):
    """Bring up a real clock and put the FSM in a known idle state.

    Used by the Zcmp multi-cycle tests. Starts the 10 ns clock, holds
    `rst_ni = 0` for two cycles, then deasserts reset with valid input
    on `instr_i`. After this, the caller advances one
    `RisingEdge(clk_i)` per FSM sub-step.
    """
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
    # Settle combinational outputs at the current FSM state (CmIdle).
    await Timer(1, "ns")


# ── Tests: one per spec Requirement ──────────────────────────────────────

@cocotb.test()
async def pass_through_uncompressed(dut):
    """Spec §"32-bit pass-through" — verifies that an uncompressed RV32
    word (low two bits `2'b11`) flows through unmodified: `instr_o ==
    instr_i`, `is_compressed_o = 0`, `illegal_instr_o = 0`,
    `gets_expanded_o = INSTR_NOT_EXPANDED`. Picks a canonical RV32 ADDI
    as the representative scenario."""
    await _drive(dut, instr=0x00100093)
    assert int(dut.instr_o.value) == 0x00100093
    assert int(dut.is_compressed_o.value) == 0
    assert int(dut.illegal_instr_o.value) == 0
    assert int(dut.gets_expanded_o.value) == INSTR_NOT_EXPANDED


@cocotb.test()
async def q0_c_addi4spn(dut):
    """Spec §"Zca quadrant 0 — c.addi4spn" — verifies the q0/funct3=000
    encoding expands to `addi rd', x2, nzuimm`. Walks the canonical
    `c.addi4spn x8, sp, 4` representative scenario and confirms
    `is_compressed_o = 1` and `illegal_instr_o = 0`. The reserved
    zero-immediate sub-case is in the full suite."""
    await _drive(dut, instr=0x00000040)
    assert int(dut.instr_o.value) == 0x00410413
    assert int(dut.is_compressed_o.value) == 1
    assert int(dut.illegal_instr_o.value) == 0
    assert int(dut.gets_expanded_o.value) == INSTR_NOT_EXPANDED


@cocotb.test()
async def q0_c_lw(dut):
    """Spec §"Zca quadrant 0 — c.lw" — verifies q0/funct3=010 expands
    to `lw rd', uimm(rs1')` with the RVC word-immediate scrambling.
    Walks the canonical `c.lw x8, 0(x9)` representative scenario; max
    immediate boundary is in the full suite."""
    await _drive(dut, instr=0x00004080)
    assert int(dut.instr_o.value) == 0x0004A403
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q0_c_sw(dut):
    """Spec §"Zca quadrant 0 — c.sw" — verifies q0/funct3=110 expands
    to `sw rs2', uimm(rs1')` with the RVC word-immediate scrambling.
    Walks `c.sw x8, 0(x9)` as the representative scenario."""
    await _drive(dut, instr=0x0000C080)
    assert int(dut.instr_o.value) == 0x0084A023
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q0_zcb_loads_stores(dut):
    """Spec §"Zcb quadrant 0 — c.lbu / c.lh / c.lhu / c.sb / c.sh" —
    verifies the Zcb byte/half load-store sub-quadrant
    (q0/funct3=100). Walks the representative `c.lbu x8, 0(x9)` and
    confirms the load expansion fires under `RV32ZC =
    RV32ZcaZcbZcmp`. Reserved sub-encodings (`instr_i[12:10]=110`,
    `c.sh` with `instr_i[6]=1`) are walked in the full suite."""
    await _drive(dut, instr=0x00008080)
    assert int(dut.instr_o.value) == 0x0004C403
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q0_reserved_funct3(dut):
    """Spec §"Zca quadrant 0 reserved funct3 codes" — verifies that
    q0/funct3=001 (reserved for c.fld) raises `illegal_instr_o = 1`.
    Other reserved funct3 codes (011, 101, 111) walk in the full
    suite. Per spec-notes item 2, `instr_o` is don't-care on the
    illegal path."""
    # funct3 = 001, q0
    await _drive(dut, instr=0x00002000)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def q1_c_addi(dut):
    """Spec §"Zca quadrant 1 — c.addi / c.nop" — verifies the
    q1/funct3=000 encoding expands to `addi rd, rd, sext(imm)`. Walks
    the canonical `c.nop` (`addi x0, x0, 0`) representative scenario.
    Sign-extension boundaries are in the full suite."""
    await _drive(dut, instr=0x00000001)
    assert int(dut.instr_o.value) == 0x00000013
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q1_c_j(dut):
    """Spec §"Zca quadrant 1 — c.jal / c.j" — verifies q1/funct3=101
    expands to `jal x0, sext(imm)`. Walks the canonical `c.j +0`
    representative scenario; the c.jal RV32 sibling is in the full
    suite."""
    await _drive(dut, instr=0x0000A001)
    assert int(dut.instr_o.value) == 0x0000006F


@cocotb.test()
async def q1_c_li(dut):
    """Spec §"Zca quadrant 1 — c.li" — verifies q1/funct3=010 expands
    to `addi rd, x0, sext(imm)`. Walks the canonical `c.li x1, 0`
    representative scenario; negative-immediate boundary is in the
    full suite."""
    await _drive(dut, instr=0x00004081)
    assert int(dut.instr_o.value) == 0x00000093
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q1_c_lui(dut):
    """Spec §"Zca quadrant 1 — c.lui / c.addi16sp" — verifies q1/
    funct3=011 with `rd != x2` expands to `lui rd, sext(imm)`. Walks
    the canonical `c.lui x3, 1` representative scenario. The
    `rd == x2` re-interpretation as `c.addi16sp` and the zero-imm
    reserved encoding are in the full suite."""
    await _drive(dut, instr=0x00006185)
    assert int(dut.instr_o.value) == 0x000011B7
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q1_c_srli(dut):
    """Spec §"Zca quadrant 1 — c.srli / c.srai" — verifies q1/
    funct3=100 with `instr_i[11:10] = 2'b00` expands to
    `srli rsd', rsd', shamt`. Walks the canonical `c.srli x8, x8, 1`
    representative scenario. The `shamt[5]=1` reserved encoding and
    the c.srai sibling are in the full suite."""
    await _drive(dut, instr=0x00008005)
    assert int(dut.instr_o.value) == 0x00145413
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q1_c_andi(dut):
    """Spec §"Zca quadrant 1 — c.andi" — verifies q1/funct3=100 with
    `instr_i[11:10] = 2'b10` expands to `andi rsd', rsd', sext(imm)`.
    Walks the canonical `c.andi x8, x8, -1` representative scenario;
    the zero-imm sibling is in the full suite."""
    await _drive(dut, instr=0x0000987D)
    assert int(dut.instr_o.value) == 0xFFF47413
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q1_c_sub(dut):
    """Spec §"Zca quadrant 1 — c.sub / c.xor / c.or / c.and" —
    verifies the q1/funct3=100, `instr_i[11:10]=11`, `instr_i[12]=0`
    sub-quadrant. Walks the canonical `c.sub x8, x8, x9`
    representative scenario; xor/or/and siblings and the RV64-only
    c.subw/c.addw reserved cases are in the full suite."""
    await _drive(dut, instr=0x00008C05)
    assert int(dut.instr_o.value) == 0x40940433
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q1_c_mul(dut):
    """Spec §"Zcb quadrant 1 — c.mul" — verifies the
    `{instr_i[12], instr_i[6:5]} == 3'b110` sub-encoding (q1/
    funct3=100/funct2=11) expands to `mul rsd', rsd', rs2'`. Only
    fires under `RV32ZC ∈ {RV32ZcaZcb, RV32ZcaZcbZcmp}` (locked port
    value enables it). Walks `c.mul x8, x8, x9` as the representative
    scenario."""
    await _drive(dut, instr=0x00009C45)
    assert int(dut.instr_o.value) == 0x02940433
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q1_zcb_extends_and_not(dut):
    """Spec §"Zcb quadrant 1 — zext.b / sext.b / zext.h / sext.h /
    not" — verifies the `{instr_i[12], instr_i[6:5]} == 3'b111`
    sub-encoding dispatches on `instr_i[4:2]`. Walks the canonical
    `c.zext.b x8` scenario (`andi x8, x8, 0xff`). The remaining
    siblings (sext.b, zext.h, sext.h, c.not) and the c.zext.w
    RV64-only reserved case are in the full suite. Per spec-notes
    item 3, these expansions were derived algebraically from the RTL
    and are pinned bit-true in the full suite."""
    await _drive(dut, instr=0x00009C61)
    assert int(dut.instr_o.value) == 0x0FF47413
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q1_c_beqz(dut):
    """Spec §"Zca quadrant 1 — c.beqz / c.bnez" — verifies
    q1/funct3=110 expands to `beq rs1', x0, sext(imm)`. Walks the
    canonical `c.beqz x8, 0` representative scenario; the c.bnez
    sibling and a non-zero offset are in the full suite."""
    await _drive(dut, instr=0x0000C001)
    assert int(dut.instr_o.value) == 0x00040063
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q2_c_slli(dut):
    """Spec §"Zca quadrant 2 — c.slli" — verifies q2/funct3=000
    expands to `slli rd, rd, shamt`. Walks the canonical
    `c.slli x1, x1, 1` representative scenario. The `shamt[5]=1`
    reserved encoding is in the full suite."""
    await _drive(dut, instr=0x00000086)
    assert int(dut.instr_o.value) == 0x00109093
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q2_c_lwsp(dut):
    """Spec §"Zca quadrant 2 — c.lwsp" — verifies q2/funct3=010
    expands to `lw rd, uimm(x2)`. Walks the canonical `c.lwsp x1, 0`
    representative scenario. The `rd == x0` reserved encoding is in
    the full suite."""
    await _drive(dut, instr=0x00004082)
    assert int(dut.instr_o.value) == 0x00012083
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q2_c_mv(dut):
    """Spec §"Zca quadrant 2 — c.mv / c.jr / c.add / c.jalr /
    c.ebreak" — verifies the q2/funct3=100 nested dispatch. Walks the
    canonical `c.mv x8, x9` representative scenario (`add x8, x0,
    x9`). The c.jr / c.add / c.jalr / c.ebreak siblings and the
    `c.jr x0` reserved encoding are in the full suite."""
    await _drive(dut, instr=0x00008426)
    assert int(dut.instr_o.value) == 0x00900433
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q2_c_swsp(dut):
    """Spec §"Zca quadrant 2 — c.swsp" — verifies q2/funct3=110
    expands to `sw rs2, uimm(x2)`. Walks the canonical
    `c.swsp x1, 0` representative scenario. Never raises
    `illegal_instr_o`."""
    await _drive(dut, instr=0x0000C006)
    assert int(dut.instr_o.value) == 0x00112023
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def q2_reserved_funct3(dut):
    """Spec §"Zca quadrant 2 reserved funct3 codes" — verifies that
    q2/funct3=011 (reserved for c.fldsp/c.lqsp) raises
    `illegal_instr_o = 1`. Other reserved funct3 codes (001, 111)
    walk in the full suite."""
    # funct3 = 011, q2
    await _drive(dut, instr=0x00006002)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def zcmp_cm_push_full_walk(dut):
    """Spec §"Zcmp — cm.push multi-cycle expansion" — verifies the
    multi-cycle FSM walk for `cm.push {ra}, -16` (rlist=4, spimm=0).
    Drives a real clock, holds reset, then drives the cm.push
    encoding stable for two cycles; samples `instr_o` and
    `gets_expanded_o` at each FSM sub-step. Sub-step 1 (CmIdle): emit
    `sw x1, -4(x2)` with `gets_expanded_o = INSTR_EXPANDED`. Sub-step
    2 (CmPushDecrSp): emit `addi x2, x2, -16` with
    `gets_expanded_o = INSTR_EXPANDED_LAST`. Reserved rlist values
    (0..3) and longer rlists are in the full suite."""
    await _zcmp_reset(dut, instr=0x0000B842)
    # Sub-step 1: store top reg.
    assert int(dut.instr_o.value) == 0xFE112E23
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED
    assert int(dut.illegal_instr_o.value) == 0
    # Advance FSM: CmIdle -> CmPushDecrSp on the next rising edge.
    await RisingEdge(dut.clk_i)
    await Timer(1, "ns")
    # Sub-step 2: addi x2, x2, -16, last sub-step.
    assert int(dut.instr_o.value) == 0xFF010113
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED_LAST
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def zcmp_cm_pop_first_step(dut):
    """Spec §"Zcmp — cm.pop / cm.popret / cm.popretz multi-cycle
    expansion" — verifies the first sub-step of `cm.pop {ra}, +16`
    (rlist=4, spimm=0). From `CmIdle` with valid input, the decoder
    emits `lw x1, 12(x2)` and `gets_expanded_o = INSTR_EXPANDED`,
    advancing to `CmPopIncrSp` next cycle. The full pop/popret/
    popretz walks (including a0 zeroing and the trailing jalr) are in
    the full suite."""
    await _zcmp_reset(dut, instr=0x0000BA42)
    assert int(dut.instr_o.value) == 0x00C12083
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def zcmp_cm_mvsa01_first_step(dut):
    """Spec §"Zcmp — cm.mvsa01 / cm.mva01s" — verifies the first
    sub-step of `cm.mvsa01` with `r1s' = r2s' = 000` (both -> x8/s0).
    From `CmIdle` with valid input, the decoder emits `addi x8, x10,
    0` and `gets_expanded_o = INSTR_EXPANDED`, advancing to
    `CmMvSecondReg` next cycle. The cm.mva01s sibling and the
    reserved `instr_i[6:5] ∈ {00,10}` cases are in the full suite.
    Per spec-notes item 3, the `cm_mvsa01`/`cm_mva01s` register
    mapping was derived algebraically from the RTL and is pinned
    bit-true in the full suite."""
    await _zcmp_reset(dut, instr=0x0000AC22)
    assert int(dut.instr_o.value) == 0x00050413
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED
    assert int(dut.illegal_instr_o.value) == 0


@cocotb.test()
async def zcmp_default_reserved(dut):
    """Spec §"Zcmp default reserved encodings" — verifies that a
    q2/funct3=101 encoding whose `instr_i[12:8]` does not match any
    of the cm.* funct5 patterns raises `illegal_instr_o = 1`. Walks
    `instr_i[12:8] = 5'b00000` as the representative unmapped
    encoding."""
    # funct3=101, q2, funct5=00000, anything else zero.
    await _drive(dut, instr=0x0000A002)
    assert int(dut.illegal_instr_o.value) == 1


@cocotb.test()
async def is_compressed_pure_lsb_decode(dut):
    """Spec §"`is_compressed_o` is a pure LSB decode" — verifies
    `is_compressed_o = (instr_i[1:0] != 2'b11)` independent of any
    other input. Walks one compressed encoding (LSBs=00) and confirms
    `is_compressed_o = 1`; the LSBs=11 case is already covered by the
    pass-through requirement."""
    await _drive(dut, instr=0x00000040)
    assert int(dut.is_compressed_o.value) == 1


@cocotb.test()
async def gets_expanded_gated_by_valid(dut):
    """Spec §"`gets_expanded_o` gating on `valid_i`" — verifies that
    when Zcmp is enabled and `valid_i = 0`, `gets_expanded_o` is
    forced to `INSTR_NOT_EXPANDED` even when `instr_i` looks like a
    Zcmp expansion. Drives a cm.push pattern with `valid_i = 0` and
    confirms the output is gated to `INSTR_NOT_EXPANDED`. Companion
    `valid_i = 1` cm.push case in the full suite."""
    await _drive(dut, instr=0x0000B842, valid=0)
    assert int(dut.gets_expanded_o.value) == INSTR_NOT_EXPANDED


@cocotb.test()
async def zcmp_fsm_stable_when_valid_low(dut):
    """Spec §"Zcmp FSM stability when `valid_i = 0`" — verifies that
    the Zcmp FSM does not advance across a clock edge when
    `valid_i = 0`, even with `id_in_ready_i = 1` and a stable cm.push
    pattern on `instr_i`. The test brings the FSM out of reset, drops
    `valid_i` for a clock cycle, and confirms `gets_expanded_o`
    returns to `INSTR_NOT_EXPANDED` (gating proxy for FSM-frozen);
    re-asserting `valid_i = 1` then yields the first cm.push
    sub-step's `INSTR_EXPANDED`. Per spec-notes item 1, both
    "gate non-idle on `id_in_ready_i` only" and "gate non-idle on
    `valid_i && id_in_ready_i`" satisfy the requirement; this test
    only checks the externally observable state at idle."""
    await _zcmp_reset(dut, instr=0x0000B842)
    # FSM is in CmIdle with valid input — emits INSTR_EXPANDED.
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED
    # Drop valid_i: gets_expanded_o gates to INSTR_NOT_EXPANDED, FSM
    # held stable.
    dut.valid_i.value = 0
    await Timer(1, "ns")
    assert int(dut.gets_expanded_o.value) == INSTR_NOT_EXPANDED
    # Cross a clock edge with valid_i still low; FSM must remain in
    # CmIdle (i.e. re-asserting valid_i still produces sub-step 1).
    await RisingEdge(dut.clk_i)
    dut.valid_i.value = 1
    await Timer(1, "ns")
    assert int(dut.gets_expanded_o.value) == INSTR_EXPANDED
    assert int(dut.instr_o.value) == 0xFE112E23


@cocotb.test()
async def pass_through_default_outputs(dut):
    """Spec §"Pure pass-through when `instr_i[1:0]` is unknown / any"
    — verifies that for `instr_i[1:0] == 2'b11` the default-arm
    outputs hold: `instr_o = instr_i`, `illegal_instr_o = 0`,
    `gets_expanded_o = INSTR_NOT_EXPANDED`. This is the same default
    arm exercised by the pass-through requirement; here we sample a
    non-canonical RV32 word (`ebreak`) to confirm the default holds
    independent of the instruction value."""
    await _drive(dut, instr=0x00100073)
    assert int(dut.instr_o.value) == 0x00100073
    assert int(dut.illegal_instr_o.value) == 0
    assert int(dut.gets_expanded_o.value) == INSTR_NOT_EXPANDED
    assert int(dut.is_compressed_o.value) == 0
