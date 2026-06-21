# ibex_alu HARC Verification Plan

## Sources Reused

- Spec: `specs/alu/spec.md`
- Current cocotb: `tests/cocotb_tests/test_ibex_alu_unit.py`
- Pytest runner: `tests/test_alu_unit.py`

## Reusable Components

- `AluOpTxn`: semantic ALU operation containing operator, operands, optional
  multdiv operands, and expected result class.
- ALU driver/helper: drives one transaction and samples combinational outputs
  after settle.
- Passive monitor: observes operator, operands, adder result, comparison
  result, equality, `result_o`, and intermediate-value write enables.
- Scoreboard/reference helpers: compute expected add/sub, logic, shifts,
  signed/unsigned comparisons, RV32B-disabled behavior, and multdiv adder path.
- Coverage collector: samples operation class, shift class, comparison class,
  equality class, multdiv select, RV32B-disabled selection, and boundary
  operands.

## Required Scenarios

- Unconditional adder output for ADD, SUB, and non-arithmetic operators.
- Multdiv operand mux overrides normal operands and drives extended result.
- XOR, OR, AND logic operators.
- SLL, SRL, SRA, including ignored upper shift amount bits.
- Equality true and false independent of operator.
- Signed and unsigned comparison differences.
- All base comparison operators: `EQ`, `NE`, `LT`, `LTU`, `GE`, `GEU`, `SLT`,
  and `SLTU`.
- `result_o` behavior for comparison operators that do not write the boolean
  result (`EQ`, `NE`, `LT`, `LTU`, `GE`, `GEU`) must be checked against the
  spec-defined selected result/default behavior.
- SLT/SLTU result zero-extension.
- Representative RV32B-only inert cases when `RV32BNone`: at least `CLZ`,
  `MIN`, and `SH1ADD`.
- `imd_val_we_o` remains zero and `imd_val_d_o[0]`/`imd_val_d_o[1]` remain
  zero for RV32B-disabled scope.
- `instr_first_cycle_i=1` shift behavior is covered explicitly.
- Additional full-verification cases beyond current cocotb parity: ADD
  wraparound, multdiv carry into the extended result, shift-by-zero,
  arithmetic shift by 31, output stability under back-to-back operation
  changes, and stronger `imd_val_d_o` tied-zero coverage.

## Functional Coverage Goals

- Hit every in-scope ALU operator class and each base comparison operator.
- Hit add, subtract, logic, shift, comparison, disabled-RV32B, and multdiv
  paths.
- Hit equality true and false.
- Hit signed-negative-vs-positive and unsigned-high-vs-low comparisons.
- Hit shift amounts `0`, `1`, typical nonzero, and upper-bits-ignored cases.
- Hit `instr_first_cycle_i=1` for standard shift scenarios.
- Hit zero, one, all-ones, sign-bit-set, and mixed-pattern operands.
- Hit back-to-back operation changes without an intervening clock because the
  DUT is combinational.
- Hit representative disabled-RV32B opcodes `CLZ`, `MIN`, and `SH1ADD`.
- Hit both intermediate-value lanes for tied-zero data and write-enable checks.

## Code Coverage Goal

Reach 100% generated-SV code coverage for the `RV32BNone` configuration.
Unhit RV32B-enabled code is eligible for exclusion only if the generated DUT
contains configuration-dead logic for disabled bitmanip features.
