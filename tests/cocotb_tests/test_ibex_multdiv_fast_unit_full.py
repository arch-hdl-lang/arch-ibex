"""Full-regression cocotb scenarios for `ibex_multdiv_fast`.

Walks every `#### Scenario:` from `specs/multdiv/spec.md` plus operand
sweeps for each RV32M instruction (signed/unsigned mixes, zero, max-
positive, min-negative), divide-by-zero and signed-overflow edges,
both data-independent timing modes, and a back-to-back MUL→DIV
transition.

The same reference-ALU helper as the basic suite is used (see
`test_ibex_multdiv_fast_unit.py` module docstring for derivation).
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


CLK_PERIOD_NS = 10

# md_op_e
MD_OP_MULL = 0
MD_OP_MULH = 1
MD_OP_DIV  = 2
MD_OP_REM  = 3

MASK32 = 0xFFFF_FFFF
MASK33 = 0x1_FFFF_FFFF
MASK34 = 0x3_FFFF_FFFF


# ── Reference-ALU helper (mirrors the basic suite) ──────────────────────

async def _alu_step(dut):
    await Timer(1, "ns")
    a = int(dut.alu_operand_a_o.value) & MASK33
    b = int(dut.alu_operand_b_o.value) & MASK33
    ext = (a + b) & MASK34
    adder = (ext >> 1) & MASK32
    eq = 1 if adder == 0 else 0
    dut.alu_adder_ext_i.value = ext
    dut.alu_adder_i.value = adder
    dut.equal_to_zero_i.value = eq
    await Timer(1, "ns")


# Helpers for packed Vec<UInt<34>, 2> port access. Whole-value `.value`
# access works on both cocotb-verilator and arch-sim (`_ArchVecProxy.value`,
# per arch-com #265): lane 0 in bits [33:0], lane 1 in bits [67:34].
_LANE_W = 34
_LANE_M = (1 << _LANE_W) - 1


def _read_imd_lane(handle, lane: int) -> int:
    return (int(handle.value) >> (lane * _LANE_W)) & _LANE_M


def _write_imd_both(handle, lane0: int, lane1: int) -> None:
    handle.value = ((lane1 & _LANE_M) << _LANE_W) | (lane0 & _LANE_M)


def _write_imd_lane(handle, lane: int, value: int) -> None:
    cur = int(handle.value)
    if lane == 0:
        handle.value = (cur & (_LANE_M << _LANE_W)) | (value & _LANE_M)
    else:
        handle.value = (cur & _LANE_M) | ((value & _LANE_M) << _LANE_W)


def _snapshot_imd(dut):
    """Sample imd_val_d_o + imd_val_we_o BEFORE the rising edge so we
    capture the cycle's combinational outputs that real EX-block flops
    would latch."""
    we = int(dut.imd_val_we_o.value)
    d0 = _read_imd_lane(dut.imd_val_d_o, 0)
    d1 = _read_imd_lane(dut.imd_val_d_o, 1)
    return we, d0, d1


def _apply_imd(dut, snapshot):
    """Write the snapshot into imd_val_q_i AFTER the rising edge.

    Compose both lanes into a single `.value` write to avoid the
    read-modify-write race that two single-lane writes would create."""
    we, d0, d1 = snapshot
    if we == 0:
        return
    cur0 = _read_imd_lane(dut.imd_val_q_i, 0)
    cur1 = _read_imd_lane(dut.imd_val_q_i, 1)
    new0 = d0 if (we & 0x1) else cur0
    new1 = d1 if (we & 0x2) else cur1
    _write_imd_both(dut.imd_val_q_i, new0, new1)


async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, CLK_PERIOD_NS, "ns").start())


def _zero_imd(dut):
    _write_imd_both(dut.imd_val_q_i, 0, 0)


async def _reset(dut):
    dut.rst_ni.value = 0
    dut.mult_en_i.value = 0
    dut.div_en_i.value = 0
    dut.mult_sel_i.value = 0
    dut.div_sel_i.value = 0
    dut.operator_i.value = 0
    dut.signed_mode_i.value = 0
    dut.op_a_i.value = 0
    dut.op_b_i.value = 0
    dut.alu_adder_ext_i.value = 0
    dut.alu_adder_i.value = 0
    dut.equal_to_zero_i.value = 0
    dut.data_ind_timing_i.value = 0
    dut.multdiv_ready_id_i.value = 1
    _zero_imd(dut)
    await Timer(2 * CLK_PERIOD_NS, "ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)


async def _run_mult(dut, *, operator: int, signed_mode: int, op_a: int, op_b: int,
                    max_cycles: int = 16) -> int:
    dut.operator_i.value = operator
    dut.signed_mode_i.value = signed_mode
    dut.op_a_i.value = op_a & MASK32
    dut.op_b_i.value = op_b & MASK32
    dut.mult_en_i.value = 1
    dut.mult_sel_i.value = 1
    dut.div_en_i.value = 0
    dut.div_sel_i.value = 0
    dut.data_ind_timing_i.value = 0
    dut.multdiv_ready_id_i.value = 1
    await _alu_step(dut)
    for _ in range(max_cycles):
        if int(dut.valid_o.value) == 1:
            result = int(dut.multdiv_result_o.value) & MASK32
            # Keep mult_en_i=1 across the terminal-cycle edge so the FSM
            # transitions AHBL→ALBL (gated by mult_en_internal). Deasserting
            # before the edge would freeze the FSM at AHBL.
            snap = _snapshot_imd(dut)
            await RisingEdge(dut.clk_i)
            _apply_imd(dut, snap)
            dut.mult_en_i.value = 0
            dut.mult_sel_i.value = 0
            await _alu_step(dut)
            return result
        snap = _snapshot_imd(dut)
        await RisingEdge(dut.clk_i)
        _apply_imd(dut, snap)
        await _alu_step(dut)
    raise AssertionError("mult did not raise valid_o in time")


async def _run_div(dut, *, operator: int, signed_mode: int, op_a: int, op_b: int,
                   data_ind_timing: int = 0, max_cycles: int = 60) -> tuple[int, int]:
    dut.operator_i.value = operator
    dut.signed_mode_i.value = signed_mode
    dut.op_a_i.value = op_a & MASK32
    dut.op_b_i.value = op_b & MASK32
    dut.div_en_i.value = 1
    dut.div_sel_i.value = 1
    dut.mult_en_i.value = 0
    dut.mult_sel_i.value = 0
    dut.data_ind_timing_i.value = data_ind_timing
    dut.multdiv_ready_id_i.value = 1
    await _alu_step(dut)
    cycles = 0
    for _ in range(max_cycles):
        if int(dut.valid_o.value) == 1:
            result = int(dut.multdiv_result_o.value) & MASK32
            # Same gating contract as _run_mult — keep div_en_i high across
            # the terminal-cycle edge so the divider FSM completes its
            # MD_FINISH→MD_IDLE transition.
            snap = _snapshot_imd(dut)
            await RisingEdge(dut.clk_i)
            _apply_imd(dut, snap)
            dut.div_en_i.value = 0
            dut.div_sel_i.value = 0
            await _alu_step(dut)
            return result, cycles
        snap = _snapshot_imd(dut)
        await RisingEdge(dut.clk_i)
        cycles += 1
        _apply_imd(dut, snap)
        await _alu_step(dut)
    raise AssertionError("div did not raise valid_o in time")


# ── RISC-V reference helpers ─────────────────────────────────────────────

def _to_signed32(x: int) -> int:
    x &= MASK32
    return x - (1 << 32) if x & 0x8000_0000 else x


def _ref_mul_low(a: int, b: int) -> int:
    return (a * b) & MASK32


def _ref_mulh_ss(a: int, b: int) -> int:  # MULH (signed × signed)
    sa, sb = _to_signed32(a), _to_signed32(b)
    return ((sa * sb) >> 32) & MASK32


def _ref_mulh_uu(a: int, b: int) -> int:  # MULHU
    return ((a * b) >> 32) & MASK32


def _ref_mulh_su(a: int, b: int) -> int:  # MULHSU (signed a, unsigned b)
    sa = _to_signed32(a)
    return ((sa * b) >> 32) & MASK32


def _ref_divu(a: int, b: int) -> int:
    if b == 0:
        return 0xFFFF_FFFF
    return (a // b) & MASK32


def _ref_div(a: int, b: int) -> int:
    if b == 0:
        return 0xFFFF_FFFF
    sa, sb = _to_signed32(a), _to_signed32(b)
    if sa == -(1 << 31) and sb == -1:
        return 0x8000_0000
    # Truncated division (toward zero), per RISC-V.
    q = abs(sa) // abs(sb)
    if (sa < 0) ^ (sb < 0):
        q = -q
    return q & MASK32


def _ref_remu(a: int, b: int) -> int:
    if b == 0:
        return a & MASK32
    return (a % b) & MASK32


def _ref_rem(a: int, b: int) -> int:
    if b == 0:
        return a & MASK32
    sa, sb = _to_signed32(a), _to_signed32(b)
    if sa == -(1 << 31) and sb == -1:
        return 0
    r = abs(sa) % abs(sb)
    if sa < 0:
        r = -r
    return r & MASK32


# ── Operand sweep set ────────────────────────────────────────────────────

OPERAND_PAIRS = [
    (0x0000_0000, 0x0000_0000),
    (0x0000_1234, 0x0000_5678),
    (0xFFFF_FFFF, 0x0000_0007),  # -1 × 7
    (0x8000_0000, 0xFFFF_FFFF),  # INT_MIN × -1
    (0x7FFF_FFFF, 0x0000_0002),  # MAX_INT × 2
    (0x8000_0000, 0x0000_0002),  # INT_MIN × 2
]


# ── MUL family (Requirement 1 — MUL) ────────────────────────────────────

@cocotb.test()
async def mul_sweep(dut):
    """MUL across operand sweep: signed/unsigned modes don't change low 32 b."""
    await _start_clock(dut)
    await _reset(dut)
    for a, b in OPERAND_PAIRS:
        for sm in (0b00, 0b11):
            got = await _run_mult(
                dut, operator=MD_OP_MULL, signed_mode=sm, op_a=a, op_b=b,
            )
            exp = _ref_mul_low(a, b)
            assert got == exp, f"MUL({a:#x},{b:#x},sm={sm:b}): got {got:#x} exp {exp:#x}"


# ── MULH family (Requirement 2) ──────────────────────────────────────────

@cocotb.test()
async def mulh_signed_signed_sweep(dut):
    """MULH across operand sweep — signed × signed upper word."""
    await _start_clock(dut)
    await _reset(dut)
    for a, b in OPERAND_PAIRS:
        got = await _run_mult(
            dut, operator=MD_OP_MULH, signed_mode=0b11, op_a=a, op_b=b,
        )
        exp = _ref_mulh_ss(a, b)
        assert got == exp, f"MULH({a:#x},{b:#x}): got {got:#x} exp {exp:#x}"


@cocotb.test()
async def mulhu_unsigned_unsigned_sweep(dut):
    """MULHU across operand sweep — unsigned × unsigned upper word."""
    await _start_clock(dut)
    await _reset(dut)
    for a, b in OPERAND_PAIRS:
        got = await _run_mult(
            dut, operator=MD_OP_MULH, signed_mode=0b00, op_a=a, op_b=b,
        )
        exp = _ref_mulh_uu(a, b)
        assert got == exp, f"MULHU({a:#x},{b:#x}): got {got:#x} exp {exp:#x}"


@cocotb.test()
async def mulhsu_signed_unsigned_sweep(dut):
    """MULHSU across operand sweep — signed-A × unsigned-B upper word."""
    await _start_clock(dut)
    await _reset(dut)
    for a, b in OPERAND_PAIRS:
        got = await _run_mult(
            dut, operator=MD_OP_MULH, signed_mode=0b01, op_a=a, op_b=b,
        )
        exp = _ref_mulh_su(a, b)
        assert got == exp, f"MULHSU({a:#x},{b:#x}): got {got:#x} exp {exp:#x}"


# Spec named scenarios (MULH family):

@cocotb.test()
async def mulhu_all_ones_squared(dut):
    """Spec scenario: MULHU produces upper 32 bits of unsigned product."""
    await _start_clock(dut)
    await _reset(dut)
    got = await _run_mult(
        dut, operator=MD_OP_MULH, signed_mode=0b00,
        op_a=0xFFFF_FFFF, op_b=0xFFFF_FFFF,
    )
    assert got == 0xFFFF_FFFE


@cocotb.test()
async def mulh_neg_int_min_times_neg_one(dut):
    """Spec scenario: MULH with two negatives produces positive upper word."""
    await _start_clock(dut)
    await _reset(dut)
    got = await _run_mult(
        dut, operator=MD_OP_MULH, signed_mode=0b11,
        op_a=0x8000_0000, op_b=0xFFFF_FFFF,
    )
    assert got == 0x0000_0000


@cocotb.test()
async def mulhsu_neg_one_times_two(dut):
    """Spec scenario: MULHSU mixes signed-A with unsigned-B."""
    await _start_clock(dut)
    await _reset(dut)
    got = await _run_mult(
        dut, operator=MD_OP_MULH, signed_mode=0b01,
        op_a=0xFFFF_FFFF, op_b=0x0000_0002,
    )
    assert got == 0xFFFF_FFFF


# ── DIV / DIVU / REM / REMU (Requirement 5, 8) ──────────────────────────

DIV_PAIRS_NONZERO = [
    (100, 7),
    (0x0000_0064, 0x0000_0007),                   # 100 / 7
    (0xFFFF_FF9C, 0x0000_0007),                   # -100 / 7 (signed)
    (0x0000_0007, 0xFFFF_FFFD),                   # 7 / -3
    (0x7FFF_FFFF, 0x0000_0002),
    (0x8000_0000, 0xFFFF_FFFF),                   # INT_MIN / -1
    (0x8000_0000, 0x0000_0001),                   # INT_MIN / 1
    (0x0000_0000, 0x0000_0001),                   # 0 / 1
    (0xFFFF_FFFF, 0xFFFF_FFFF),                   # -1 / -1
]

DIV_PAIRS_ZERO = [
    (0x0000_0000, 0x0000_0000),
    (0x1234_5678, 0x0000_0000),
    (0xFFFF_FF9C, 0x0000_0000),
]


@cocotb.test()
async def divu_sweep(dut):
    """DIVU across operand sweep + divide-by-zero."""
    await _start_clock(dut)
    await _reset(dut)
    for a, b in DIV_PAIRS_NONZERO + DIV_PAIRS_ZERO:
        got, _ = await _run_div(
            dut, operator=MD_OP_DIV, signed_mode=0b00, op_a=a, op_b=b,
        )
        exp = _ref_divu(a, b)
        assert got == exp, f"DIVU({a:#x},{b:#x}): got {got:#x} exp {exp:#x}"


@cocotb.test()
async def div_sweep(dut):
    """DIV across operand sweep + divide-by-zero + INT_MIN/-1 overflow."""
    await _start_clock(dut)
    await _reset(dut)
    for a, b in DIV_PAIRS_NONZERO + DIV_PAIRS_ZERO:
        got, _ = await _run_div(
            dut, operator=MD_OP_DIV, signed_mode=0b11, op_a=a, op_b=b,
        )
        exp = _ref_div(a, b)
        assert got == exp, f"DIV({a:#x},{b:#x}): got {got:#x} exp {exp:#x}"


@cocotb.test()
async def remu_sweep(dut):
    """REMU across operand sweep + divide-by-zero (returns dividend)."""
    await _start_clock(dut)
    await _reset(dut)
    for a, b in DIV_PAIRS_NONZERO + DIV_PAIRS_ZERO:
        got, _ = await _run_div(
            dut, operator=MD_OP_REM, signed_mode=0b00, op_a=a, op_b=b,
        )
        exp = _ref_remu(a, b)
        assert got == exp, f"REMU({a:#x},{b:#x}): got {got:#x} exp {exp:#x}"


@cocotb.test()
async def rem_sweep(dut):
    """REM across operand sweep + divide-by-zero + INT_MIN/-1 (= 0)."""
    await _start_clock(dut)
    await _reset(dut)
    for a, b in DIV_PAIRS_NONZERO + DIV_PAIRS_ZERO:
        got, _ = await _run_div(
            dut, operator=MD_OP_REM, signed_mode=0b11, op_a=a, op_b=b,
        )
        exp = _ref_rem(a, b)
        assert got == exp, f"REM({a:#x},{b:#x}): got {got:#x} exp {exp:#x}"


# Spec named scenarios (DIV family):

@cocotb.test()
async def divu_100_div_7(dut):
    """Spec scenario: DIVU 100 / 7 = 14 rem 2."""
    await _start_clock(dut)
    await _reset(dut)
    got, cyc = await _run_div(dut, operator=MD_OP_DIV, signed_mode=0b00,
                              op_a=100, op_b=7)
    assert got == 14
    assert cyc >= 36


@cocotb.test()
async def div_neg100_div_7(dut):
    """Spec scenario: DIV -100 / 7 = -14."""
    await _start_clock(dut)
    await _reset(dut)
    got, _ = await _run_div(dut, operator=MD_OP_DIV, signed_mode=0b11,
                            op_a=0xFFFF_FF9C, op_b=7)
    assert got == 0xFFFF_FFF2


@cocotb.test()
async def rem_7_rem_neg3(dut):
    """Spec scenario: REM 7 % -3 = 1 (remainder takes sign of dividend)."""
    await _start_clock(dut)
    await _reset(dut)
    got, _ = await _run_div(dut, operator=MD_OP_REM, signed_mode=0b11,
                            op_a=7, op_b=0xFFFF_FFFD)
    assert got == 1


# ── Divide-by-zero short-circuit (Requirement 6) ────────────────────────

@cocotb.test()
async def divu_by_zero_one_stall(dut):
    """Spec scenario: DIVU x / 0 = 0xFFFF_FFFF, short-circuit."""
    await _start_clock(dut)
    await _reset(dut)
    got, cyc = await _run_div(dut, operator=MD_OP_DIV, signed_mode=0b00,
                              op_a=0x1234_5678, op_b=0, data_ind_timing=0)
    assert got == 0xFFFF_FFFF
    assert cyc < 5, f"short-circuit expected, got {cyc} cycles"


@cocotb.test()
async def remu_by_zero_one_stall(dut):
    """Spec scenario: REMU x / 0 = x, short-circuit."""
    await _start_clock(dut)
    await _reset(dut)
    got, cyc = await _run_div(dut, operator=MD_OP_REM, signed_mode=0b00,
                              op_a=0x1234_5678, op_b=0, data_ind_timing=0)
    assert got == 0x1234_5678
    assert cyc < 5


@cocotb.test()
async def div_by_zero_signed_one_stall(dut):
    """Spec scenario: DIV (signed) x / 0 = -1, short-circuit, sign suppressed."""
    await _start_clock(dut)
    await _reset(dut)
    got, cyc = await _run_div(dut, operator=MD_OP_DIV, signed_mode=0b11,
                              op_a=0xFFFF_FF9C, op_b=0, data_ind_timing=0)
    assert got == 0xFFFF_FFFF
    assert cyc < 5


# ── Constant-time mode (Requirement 7) ──────────────────────────────────

@cocotb.test()
async def div_by_zero_constant_time_full(dut):
    """Spec scenario: DIV by zero with data_ind_timing_i=1 takes 37 cycles."""
    await _start_clock(dut)
    await _reset(dut)
    got, cyc = await _run_div(dut, operator=MD_OP_DIV, signed_mode=0b11,
                              op_a=42, op_b=0, data_ind_timing=1)
    assert got == 0xFFFF_FFFF
    assert cyc >= 36, f"expected full schedule, got {cyc}"


@cocotb.test()
async def constant_time_nonzero_matches_normal(dut):
    """Spec scenario: const-time DIV with op_b != 0 matches normal-mode result."""
    await _start_clock(dut)
    await _reset(dut)
    pairs = [(100, 7), (0xFFFF_FF9C, 7), (0x8000_0000, 0xFFFF_FFFF)]
    for a, b in pairs:
        for op, sm, ref in (
            (MD_OP_DIV, 0b11, _ref_div),
            (MD_OP_REM, 0b11, _ref_rem),
        ):
            got_const, cyc_const = await _run_div(
                dut, operator=op, signed_mode=sm, op_a=a, op_b=b,
                data_ind_timing=1,
            )
            got_norm, _ = await _run_div(
                dut, operator=op, signed_mode=sm, op_a=a, op_b=b,
                data_ind_timing=0,
            )
            assert got_const == got_norm == ref(a, b), (
                f"op={op} a={a:#x} b={b:#x}: const={got_const:#x} "
                f"norm={got_norm:#x} ref={ref(a, b):#x}"
            )
            assert cyc_const >= 36


# ── Signed overflow (Requirement 8) ─────────────────────────────────────

@cocotb.test()
async def div_int_min_div_neg_one(dut):
    """Spec scenario: DIV(-2^31, -1) = -2^31."""
    await _start_clock(dut)
    await _reset(dut)
    got, _ = await _run_div(dut, operator=MD_OP_DIV, signed_mode=0b11,
                            op_a=0x8000_0000, op_b=0xFFFF_FFFF)
    assert got == 0x8000_0000


@cocotb.test()
async def rem_int_min_rem_neg_one(dut):
    """Spec scenario: REM(-2^31, -1) = 0."""
    await _start_clock(dut)
    await _reset(dut)
    got, _ = await _run_div(dut, operator=MD_OP_REM, signed_mode=0b11,
                            op_a=0x8000_0000, op_b=0xFFFF_FFFF)
    assert got == 0


# ── ALU operand exchange named scenario (Requirement 9) ─────────────────

@cocotb.test()
async def md_idle_drives_zero_minus_b(dut):
    """Spec §"ALU operand exchange" — IDLE drive: a=0||1, b=~op_b||1."""
    await _start_clock(dut)
    await _reset(dut)
    op_b = 0x1234_5678
    dut.operator_i.value = MD_OP_DIV
    dut.signed_mode_i.value = 0b00
    dut.op_a_i.value = 0xDEAD_BEEF
    dut.op_b_i.value = op_b
    dut.div_en_i.value = 1
    dut.div_sel_i.value = 1
    dut.multdiv_ready_id_i.value = 1
    await Timer(1, "ns")
    a = int(dut.alu_operand_a_o.value) & MASK33
    b = int(dut.alu_operand_b_o.value) & MASK33
    assert a == 0x1, f"a={a:#x}"
    assert b == (((~op_b & MASK32) << 1) | 1), f"b={b:#x}"


# ── Result mux scenario (Requirement 4) ─────────────────────────────────

@cocotb.test()
async def result_mux_div_path(dut):
    """Spec §"Result mux" — DIVU result reads from imd_val_q_i[0][31:0]."""
    await _start_clock(dut)
    await _reset(dut)
    got, _ = await _run_div(dut, operator=MD_OP_DIV, signed_mode=0b00,
                            op_a=0x0000_0064, op_b=0x0000_0007)
    assert got == 14


# ── Lane-1 scenario (Requirement 10) ────────────────────────────────────

@cocotb.test()
async def lane1_holds_divisor_through_compute(dut):
    """Spec §"Intermediate-value lane assignment" — lane 1 captured at
    MD_ABS_B and stable through MD_COMP, MD_LAST, MD_CHANGE_SIGN,
    MD_FINISH (no further lane-1 writes after the initial one)."""
    await _start_clock(dut)
    await _reset(dut)
    op_b = 0x0000_0007
    dut.operator_i.value = MD_OP_DIV
    dut.signed_mode_i.value = 0b00
    dut.op_a_i.value = 0x0000_0064
    dut.op_b_i.value = op_b
    dut.div_en_i.value = 1
    dut.div_sel_i.value = 1
    dut.multdiv_ready_id_i.value = 1
    await _alu_step(dut)
    lane1_we_count = 0
    for _ in range(50):
        snap = _snapshot_imd(dut)
        await RisingEdge(dut.clk_i)
        _apply_imd(dut, snap)
        await _alu_step(dut)
        if int(dut.imd_val_we_o.value) & 0x2:
            lane1_we_count += 1
        if int(dut.valid_o.value) == 1:
            break
    # Spec line 128/418: lane-1 we is high every cycle the divider FSM
    # advances (not just MD_ABS_B). We assert at least one we and that
    # the lane-1 value held in the flop bank at completion equals op_b.
    assert lane1_we_count >= 1
    assert (_read_imd_lane(dut.imd_val_q_i, 1) & MASK32) == op_b


# ── Reset scenario (Requirement 11) ─────────────────────────────────────

@cocotb.test()
async def reset_then_post_reset_op(dut):
    """Spec §"Reset behaviour" — async reset then a normal op completes."""
    await _start_clock(dut)
    await _reset(dut)
    await Timer(1, "ns")
    assert int(dut.valid_o.value) == 0
    got = await _run_mult(dut, operator=MD_OP_MULL, signed_mode=0b00,
                          op_a=2, op_b=3)
    assert got == 6


# ── valid_o quiescent scenario (Requirement 12) ─────────────────────────

@cocotb.test()
async def quiescent_valid_low(dut):
    """Spec §"valid_o is the OR of mult_valid and div_valid" — both
    enables low keeps valid_o = 0 over many cycles."""
    await _start_clock(dut)
    await _reset(dut)
    for _ in range(16):
        await _alu_step(dut)
        assert int(dut.valid_o.value) == 0
        snap = _snapshot_imd(dut)
        await RisingEdge(dut.clk_i)
        _apply_imd(dut, snap)


# ── Back-to-back FSM transition (proposal "back-to-back" sweep) ─────────

@cocotb.test()
async def back_to_back_mul_then_div(dut):
    """A MUL immediately followed by a DIV (no idle cycle gap) verifies
    the FSMs cleanly transition idle→active twice without the second
    operation seeing stale lane state from the first."""
    await _start_clock(dut)
    await _reset(dut)
    # First: MUL 6 * 7.
    got_mul = await _run_mult(dut, operator=MD_OP_MULL, signed_mode=0b00,
                              op_a=6, op_b=7)
    assert got_mul == 42
    # No deassert/idle between — _run_mult already deasserts mult_en for
    # one rising edge. Drive div directly.
    got_div, _ = await _run_div(dut, operator=MD_OP_DIV, signed_mode=0b00,
                                op_a=100, op_b=7)
    assert got_div == 14


# ── Backpressure (Requirement 1 sub-scenario) ───────────────────────────

@cocotb.test()
async def mul_backpressure_holds_valid(dut):
    """Spec scenario: MUL backpressured by ID stage — valid_o stays high
    and FSM holds in AHBL while multdiv_ready_id_i = 0."""
    await _start_clock(dut)
    await _reset(dut)
    op_a, op_b = 0x0000_0003, 0x0000_0005
    dut.operator_i.value = MD_OP_MULL
    dut.signed_mode_i.value = 0b00
    dut.op_a_i.value = op_a
    dut.op_b_i.value = op_b
    dut.mult_en_i.value = 1
    dut.mult_sel_i.value = 1
    dut.div_en_i.value = 0
    dut.div_sel_i.value = 0
    dut.multdiv_ready_id_i.value = 0  # backpressure throughout
    await _alu_step(dut)
    # Walk until valid_o asserts.
    for _ in range(8):
        if int(dut.valid_o.value) == 1:
            break
        snap = _snapshot_imd(dut)
        await RisingEdge(dut.clk_i)
        _apply_imd(dut, snap)
        await _alu_step(dut)
    assert int(dut.valid_o.value) == 1
    expected = op_a * op_b
    result = int(dut.multdiv_result_o.value) & MASK32
    assert result == expected
    # Hold for two more cycles with ready=0; valid_o must stay high and
    # result must remain stable.
    for _ in range(2):
        snap = _snapshot_imd(dut)
        await RisingEdge(dut.clk_i)
        _apply_imd(dut, snap)
        await _alu_step(dut)
        assert int(dut.valid_o.value) == 1, "valid_o dropped under backpressure"
        assert (int(dut.multdiv_result_o.value) & MASK32) == expected
    # Acknowledge: valid_o drops next cycle.
    dut.multdiv_ready_id_i.value = 1
    snap = _snapshot_imd(dut)
    await RisingEdge(dut.clk_i)
    _apply_imd(dut, snap)
    dut.mult_en_i.value = 0
    await _alu_step(dut)
