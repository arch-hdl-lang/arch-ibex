# ALU Specification

## Purpose

The Ibex ALU is the combinational arithmetic / logic / shift /
comparison datapath. It serves three callers in a single cycle:

1. **EX-stage operations** — `result_o` returns the ALU result for the
   committed integer instruction (driven from `ex_block`).
2. **Adder reuse for address generation** — `adder_result_o` provides
   `op_a + op_b` for LSU effective-address calculation and for branch
   target computation, regardless of `operator_i`.
3. **Comparator reuse for branch resolution** — `comparison_result_o`
   and `is_equal_result_o` are consumed by the controller / branch unit
   to decide branch taken/not-taken in the same cycle as decode.

A `multdiv_sel_i` input multiplexes a 33-bit operand pair from the
multdiv unit into the shared adder so the multiplier/divider need not
duplicate a 33-bit adder.

This specification covers the `RV32B = RV32BNone` configuration. RV32B
bitmanip operators are listed in the port contract but produce
`result_o = 0` and do not affect adder / comparator outputs in this
configuration.

## Port contract

| Direction | Name | Type | Description |
|---|---|---|---|
| param | `RV32B` | `rv32b_e` | Bitmanip extension level. `RV32BNone` for this spec. |
| in  | `operator_i`            | `alu_op_e`     | Selects the ALU operation. |
| in  | `operand_a_i`           | `UInt<32>`     | First operand (rs1 in EX, or branch PC, or LSU base). |
| in  | `operand_b_i`           | `UInt<32>`     | Second operand (rs2 / immediate / branch offset / LSU offset). |
| in  | `instr_first_cycle_i`   | `Bool`         | First-cycle indicator (RV32B multi-cycle ops; unused when `RV32B=None`). |
| in  | `multdiv_operand_a_i`   | `UInt<33>`     | Multdiv adder source A (when `multdiv_sel_i`). |
| in  | `multdiv_operand_b_i`   | `UInt<33>`     | Multdiv adder source B (when `multdiv_sel_i`). |
| in  | `multdiv_sel_i`         | `Bool`         | When asserted, route multdiv operands into the shared adder. |
| in  | `imd_val_q_i[2]`        | `UInt<32>`     | Intermediate-value flop pair (RV32B multi-cycle state; tied to 0 in this config). |
| out | `imd_val_d_o[2]`        | `UInt<32>`     | Intermediate-value next state (held at 0 in this config). |
| out | `imd_val_we_o[2]`       | `UInt<2>`      | Per-flop write-enable (held at 0 in this config). |
| out | `adder_result_o`        | `UInt<32>`     | 32-bit `operand_a_i + operand_b_i`, regardless of `operator_i`. Used by LSU + branch. |
| out | `adder_result_ext_o`    | `UInt<34>`     | 34-bit extended adder result (carry-extended). Used by multdiv accumulate. |
| out | `result_o`              | `UInt<32>`     | Operator-selected result. Returns 0 for any operator not enabled by `RV32B`. |
| out | `comparison_result_o`   | `Bool`         | Single-bit result of the selected comparison (LT/LTU/GE/GEU/EQ/NE/SLT/SLTU). |
| out | `is_equal_result_o`     | `Bool`         | Asserted when `operand_a_i == operand_b_i`, regardless of `operator_i` (used independently of comparison_result by branch logic). |

## Requirements

### Requirement: Adder always produces unconditional sum

The module SHALL drive `adder_result_o` with the unsigned 32-bit sum of
`operand_a_i` and `operand_b_i` in every cycle, irrespective of
`operator_i`, EXCEPT when `multdiv_sel_i` is asserted, in which case the
sum SHALL be `multdiv_operand_a_i + multdiv_operand_b_i` (33-bit
unsigned, with `adder_result_ext_o` carrying the full 34-bit extended
result).

For any subtractive or comparison operator (`ALU_SUB`, `ALU_EQ`, `ALU_NE`,
`ALU_GE`, `ALU_GEU`, `ALU_LT`, `ALU_LTU`, `ALU_SLT`, `ALU_SLTU`), the
adder SHALL compute `operand_a_i - operand_b_i` (two's-complement) and
expose the result on `adder_result_o`. (ref: `ibex_alu.sv:60-109`)

#### Scenario: Plain ADD
- GIVEN `operator_i = ALU_ADD`, `operand_a_i = 0x0000_0001`, `operand_b_i = 0x0000_0002`, `multdiv_sel_i = 0`
- WHEN inputs are stable
- THEN `adder_result_o == 0x0000_0003`
- AND  `result_o == 0x0000_0003`

#### Scenario: SUB via two's-complement
- GIVEN `operator_i = ALU_SUB`, `operand_a_i = 0x0000_0005`, `operand_b_i = 0x0000_0003`
- WHEN inputs are stable
- THEN `adder_result_o == 0x0000_0002`
- AND  `result_o == 0x0000_0002`

#### Scenario: Adder reused by LSU during a load (operator irrelevant)
- GIVEN `operator_i = ALU_OR` (any non-arithmetic op), `operand_a_i = 0x1000_0000`, `operand_b_i = 0x0000_0010`
- WHEN inputs are stable
- THEN `adder_result_o == 0x1000_0010`
- AND  `result_o` is the OR result (0x1000_0010 in this case happens to coincide; verified independently in the OR scenario)
- (ref: LSU consumes `adder_result_o` regardless of `operator_i`; `ibex_load_store_unit.sv` reads only this port.)

#### Scenario: Multdiv path overrides the operand mux
- GIVEN `multdiv_sel_i = 1`, `multdiv_operand_a_i = 33'h0_0000_0007`, `multdiv_operand_b_i = 33'h0_0000_0008`
- WHEN inputs are stable
- THEN `adder_result_ext_o == 34'h0_0000_000F` (with carry bit) AND `adder_result_o == 32'h0000_000F`
- AND  the value of `operand_a_i`/`operand_b_i` is ignored by the adder

### Requirement: Logic operators

The module SHALL drive `result_o` with the bitwise result of the
selected logic operator: `operand_a_i ^ operand_b_i` for `ALU_XOR`,
`operand_a_i | operand_b_i` for `ALU_OR`, `operand_a_i & operand_b_i`
for `ALU_AND`. (ref: `ibex_alu.sv:204-217`)

#### Scenario: XOR
- GIVEN `operator_i = ALU_XOR`, `operand_a_i = 0xFFFF_0000`, `operand_b_i = 0x00FF_FF00`
- THEN `result_o == 0xFF00_FF00`

#### Scenario: OR
- GIVEN `operator_i = ALU_OR`, `operand_a_i = 0x0000_FF00`, `operand_b_i = 0x00FF_0000`
- THEN `result_o == 0x00FF_FF00`

#### Scenario: AND
- GIVEN `operator_i = ALU_AND`, `operand_a_i = 0xFF0F_FFFF`, `operand_b_i = 0x0FFF_FF0F`
- THEN `result_o == 0x0F0F_FF0F`

### Requirement: Shift operators

The module SHALL implement RISC-V shifts taking `operand_b_i[4:0]` as
the shift amount, ignoring the upper bits of `operand_b_i`:

- `ALU_SLL` — logical left shift, zero-fill
- `ALU_SRL` — logical right shift, zero-fill
- `ALU_SRA` — arithmetic right shift, sign-bit fill from `operand_a_i[31]`

(ref: `ibex_alu.sv:248-385`)

#### Scenario: SLL with shamt 4
- GIVEN `operator_i = ALU_SLL`, `operand_a_i = 0x0000_000F`, `operand_b_i[4:0] = 5'd4`
- THEN `result_o == 0x0000_00F0`

#### Scenario: SRL with shamt 1
- GIVEN `operator_i = ALU_SRL`, `operand_a_i = 0x8000_0002`, `operand_b_i[4:0] = 5'd1`
- THEN `result_o == 0x4000_0001`

#### Scenario: SRA preserves sign on negative input
- GIVEN `operator_i = ALU_SRA`, `operand_a_i = 0x8000_0000`, `operand_b_i[4:0] = 5'd1`
- THEN `result_o == 0xC000_0000`

#### Scenario: Shift amount upper bits ignored
- GIVEN `operator_i = ALU_SLL`, `operand_a_i = 0x0000_0001`, `operand_b_i = 0x0000_FFE4` (upper bits set; lower 5 bits = 5'd4)
- THEN `result_o == 0x0000_0010` (shamt = 4)

### Requirement: Equality output

The module SHALL drive `is_equal_result_o = (operand_a_i == operand_b_i)`
in every cycle, regardless of `operator_i`. This output is used by the
branch unit independently of the comparator. (ref: `ibex_alu.sv:115-141`)

#### Scenario: Equal
- GIVEN `operand_a_i == operand_b_i == 0xDEAD_BEEF`, `operator_i = ALU_ADD`
- THEN `is_equal_result_o == 1`

#### Scenario: Not equal
- GIVEN `operand_a_i = 0x0000_0001`, `operand_b_i = 0x0000_0002`, `operator_i = ALU_ADD`
- THEN `is_equal_result_o == 0`

### Requirement: Comparison operators

The module SHALL drive `comparison_result_o` according to the selected
comparison operator, with signed semantics for `LT/GE/SLT` and unsigned
for `LTU/GEU/SLTU/EQ/NE`. (ref: `ibex_alu.sv:115-180`)

| Operator | comparison_result_o |
|---|---|
| `ALU_EQ`   | `operand_a_i == operand_b_i` |
| `ALU_NE`   | `operand_a_i != operand_b_i` |
| `ALU_LT`,  `ALU_SLT`  | `signed(operand_a_i) < signed(operand_b_i)` |
| `ALU_LTU`, `ALU_SLTU` | `unsigned(operand_a_i) < unsigned(operand_b_i)` |
| `ALU_GE`   | `signed(operand_a_i) >= signed(operand_b_i)` |
| `ALU_GEU`  | `unsigned(operand_a_i) >= unsigned(operand_b_i)` |

For `ALU_SLT` / `ALU_SLTU`, `result_o` SHALL be `{31'b0, comparison_result_o}`
(zero-extended to 32 bits).

#### Scenario: Signed LT, negative vs positive
- GIVEN `operator_i = ALU_LT`, `operand_a_i = 0xFFFF_FFFF` (-1), `operand_b_i = 0x0000_0001` (+1)
- THEN `comparison_result_o == 1`

#### Scenario: Unsigned LTU same operands
- GIVEN `operator_i = ALU_LTU`, `operand_a_i = 0xFFFF_FFFF`, `operand_b_i = 0x0000_0001`
- THEN `comparison_result_o == 0` (0xFFFFFFFF unsigned > 1)

#### Scenario: SLT writes 1 to result on true
- GIVEN `operator_i = ALU_SLT`, `operand_a_i = 0xFFFF_FFFE` (-2), `operand_b_i = 0x0000_0000`
- THEN `comparison_result_o == 1` AND `result_o == 0x0000_0001`

#### Scenario: SLTU writes 0 to result on false
- GIVEN `operator_i = ALU_SLTU`, `operand_a_i = 0x0000_0010`, `operand_b_i = 0x0000_0010`
- THEN `comparison_result_o == 0` AND `result_o == 0x0000_0000`

#### Scenario: GE on equal operands
- GIVEN `operator_i = ALU_GE`, `operand_a_i = 0x0000_0007`, `operand_b_i = 0x0000_0007`
- THEN `comparison_result_o == 1` AND `is_equal_result_o == 1`

### Requirement: RV32B operators are inert when disabled

In configurations with `RV32B = RV32BNone`, the module SHALL drive
`result_o = 0` for any RV32B-only operator (the full list is in the
proposal). The adder and comparator outputs SHALL remain valid for
these operators (i.e., `adder_result_o` is still `op_a + op_b`,
`is_equal_result_o` still reflects equality), since downstream blocks
sample those ports unconditionally.

The module SHALL drive `imd_val_d_o[i] = 0` and `imd_val_we_o = 2'b00`
for all `i` in this configuration. (ref: `ibex_alu.sv:1370-1380`
default arms.)

#### Scenario: Disabled RV32B operator selected
- GIVEN `RV32B = RV32BNone`, `operator_i = ALU_CLZ`, `operand_a_i = 0x0000_F000`, `operand_b_i = 0x0000_0000`
- THEN `result_o == 0x0000_0000`
- AND  `adder_result_o == 0x0000_F000`
- AND  `imd_val_we_o == 2'b00`

## Notes

- `instr_first_cycle_i` is unused when `RV32B = RV32BNone`; the ARCH
  module still declares the port to keep its SV signature compatible.
- The `imd_val_*` ports are similarly carried at the boundary so the
  same module can later be extended to RV32B without changing every
  caller.
- All scenarios above are pure-combinational: same-cycle inputs →
  same-cycle outputs. There are no clock or reset ports on this module.
