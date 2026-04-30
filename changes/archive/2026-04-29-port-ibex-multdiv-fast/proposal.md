# Proposal: Port `ibex_multdiv_fast` to ARCH

## Intent

Replace upstream `ibex_multdiv_fast.sv` (556 LoC) — the multi-cycle
RV32M multiplier / divider — with an ARCH equivalent. Sits in the
EX block, **shares the ALU's adder and comparator** through external
ports (`alu_adder_ext_i`, `alu_adder_i`, `equal_to_zero_i` come back;
`alu_operand_a_o` / `alu_operand_b_o` go out to drive the ALU). The
multdiv unit drives a multi-cycle FSM that walks each `MUL`/`DIV`
instruction across several cycles, accumulating partial products in
two 34-bit intermediate-value registers (`imd_val_q`/`imd_val_d`) the
ALU/`ibex_ex_block` carries between cycles.

Sixth leaf-module swap (A6). **First swap potentially using ARCH's
`thread` construct** — the multi-cycle MUL/DIV sequencing is a
natural fit for a thread that yields between sub-steps; the
implementer agent picks the final form (could also be `fsm` over the
states upstream defines).

The slow variant `ibex_multdiv_slow.sv` (390 LoC) is **out of scope**
— our SoC binds `RV32M = RV32MFast` (`soc/ibex_mini_soc.sv:46`), and
upstream's `ibex_ex_block.sv:166` selects `ibex_multdiv_fast` for
both `RV32MFast` and `RV32MSingleCycle`.

## Scope

**In scope** — `RV32M = RV32MFast` (= 2):

- All 8 RV32M instructions: `MUL`, `MULH`, `MULHSU`, `MULHU`, `DIV`,
  `DIVU`, `REM`, `REMU`.
- Multi-cycle multiplier (16×16 kernel iterated in MD_FAST_MULL state
  family — typically 3 cycles for MUL/MULH).
- Long-division algorithm for DIV/REM (typically 33 cycles).
- Signed/unsigned dispatch via `signed_mode_i[1:0]` (one bit per
  operand).
- Divide-by-zero / signed-overflow handling per RISC-V spec.
- 34-bit unpacked-array intermediate-value ports (`imd_val_q_i [2]`,
  `imd_val_d_o [2]`, `imd_val_we_o [1:0]`) — same `unpacked Vec` port
  modifier the ALU uses.
- `data_ind_timing_i` constant-time mode: when high, divides take a
  fixed maximum number of cycles regardless of operand magnitude
  (defends against SCA timing leaks).
- ALU-shared paths: the multdiv issues operands on
  `alu_operand_a_o` / `alu_operand_b_o` and consumes the ALU's adder
  output `alu_adder_ext_i` (34-bit) / `alu_adder_i` (32-bit) and
  comparator `equal_to_zero_i`.

**Out of scope**:

- `RV32M = RV32MSingleCycle` (= 3) — uses a different internal
  multiplier kernel. Defer to a future swap.
- `RV32M ∈ {RV32MNone, RV32MSlow}` — Slow variant is an entirely
  different module; None disables the M extension.
- The Phase D opentitan-config security hardening additions
  (lockstep, tracing).

## Approach

Tentative ARCH constructs (the implementer agent picks final shapes):

- `module` with clk + rst + a multi-cycle FSM. Likely `fsm` over the
  upstream state enum (`MD_IDLE`, `MD_ABS_A`, `MD_ABS_B`, `MD_COMP`,
  `MD_LAST`, `MD_CHANGE_SIGN`, `MD_FINISH`) OR a `thread` over the
  same logical sequence. The ALU-shared adder is sequenced: the
  multdiv drives operands and reads the result the next cycle, so the
  thread yields between drive and read. **Implementer's call.**
- 16×16 kernel multiplier as combinational arithmetic.
- Long-division shift-register kernel as `reg`-typed accumulator
  updated per cycle.
- 34-bit `imd_val` shared with `ibex_ex_block` via `unpacked Vec` ports
  (same pattern as `IbexAlu.arch`).
- `data_ind_timing` predicate gates the early-exit so DIV/REM always
  takes 33 cycles when set.

## Verification gate

Per the TDD-first / split-gate flow:

1. **Basic suite** (blocking) — one cocotb scenario per spec
   Requirement (~10–15 tests). Drive each M instruction with
   representative operand pairs, walk the FSM cycle-by-cycle,
   sample `valid_o` at the final cycle, assert `multdiv_result_o`.
2. **Full regression** (background) — every M instruction × every
   sign combination × boundary cases (−2³¹ × −1 = signed overflow;
   x / 0 = quotient `−1`, remainder `dividend`; constant-time mode
   on/off; data_ind_timing on/off).

The existing 4 ISR programs are already RV32IM (built with
`-march=rv32im_zicsr`) and execute MUL/DIV inside the trap handlers'
arithmetic. They are the end-to-end sanity check.

## Verification gate caveats

- The multdiv module exchanges operands with the ALU. The unit-test
  harness has two options: instantiate the real ARCH-emitted ALU
  alongside multdiv, OR drive the multdiv's `alu_*_i` inputs
  synthetically per a reference model. The latter is simpler and
  scope-aligned (we already verified the ALU at A1) — go with it.

## Reference

Upstream: `$IBEX_ROOT/rtl/ibex_multdiv_fast.sv` (Apache-2.0, 556 LoC).
Producer / consumer: `ibex_ex_block.sv:166` instantiates the unit and
wires the ALU-shared paths. The ID stage drives `multdiv_operator_i`
/ `multdiv_signed_mode_i` (the decoder we ported in A4 generates these).
Reference doc: `~/github/ibex/doc/03_reference/pipeline_details.rst`
covers multi-cycle execution at a high level.
