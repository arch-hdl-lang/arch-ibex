# EX Block Specification

## Purpose

`ibex_ex_block` is the **execute-stage container** of the Ibex pipeline.
It hosts two sub-modules — `ibex_alu` (the combinational ALU, A1) and
`ibex_multdiv_fast` (the fast multiplier/divider, A6) — and wires their
combinational cross-coupling loop and output muxes.

The block is a thin structural module with no logic of its own except:

1. A selector `multdiv_sel = mult_sel_i | div_sel_i` that signals which
   sub-module's outputs are live this cycle.
2. Three output muxes (for `result_ex_o`, `imd_val_d_o[*]`, and
   `imd_val_we_o`) that select between the ALU and multdiv outputs based on
   `multdiv_sel`.
3. Routing of the branch outputs (`branch_decision_o`,
   `branch_target_o`).
4. The `ex_valid_o` combinational flag.

This spec covers the fixed SoC configuration:
- `RV32M = RV32MFast` (= 2) — fast multdiv variant
- `RV32B = RV32BNone` (= 0) — no bitmanip extension
- `BranchTargetALU = 0` — no dedicated branch-target adder

## Port contract

| Direction | Name | Type | Description |
|---|---|---|---|
| param | `RV32M` | `const` | RV32M mode. Fixed to `2` (RV32MFast). |
| param | `RV32B` | `const` | RV32B mode. Fixed to `0` (RV32BNone). |
| param | `BranchTargetALU[0:0]` | `const` | 1-bit. Fixed to `1'b0`. No dedicated BTA adder. |
| in  | `clk_i`                    | `Clock<SysDomain>` | Pipeline clock. |
| in  | `rst_ni`                   | `Reset<Async, Low>` | Active-low asynchronous reset. |
| in  | `alu_operator_i`           | `UInt<7>` (encodes `alu_op_e`) | ALU operation selector. |
| in  | `alu_operand_a_i`          | `UInt<32>` | ALU primary operand (rs1). |
| in  | `alu_operand_b_i`          | `UInt<32>` | ALU secondary operand (rs2 or immediate). |
| in  | `alu_instr_first_cycle_i`  | `Bool` | High on the first cycle of an instruction. Passed through to the ALU. |
| in  | `bt_a_operand_i`           | `UInt<32>` | Branch-target adder A operand. Unused when `BranchTargetALU = 0`; connected to a dummy to suppress lint warnings. |
| in  | `bt_b_operand_i`           | `UInt<32>` | Branch-target adder B operand. Same. |
| in  | `multdiv_operator_i`       | `UInt<2>` (encodes `md_op_e`) | Multdiv operation: `MD_OP_MULL`=0, `MD_OP_MULH`=1, `MD_OP_DIV`=2, `MD_OP_REM`=3. |
| in  | `mult_en_i`                | `Bool` | Dynamic multiplier enable (held high for full multi-cycle MUL). |
| in  | `div_en_i`                 | `Bool` | Dynamic divider enable (held high for full multi-cycle DIV/REM). |
| in  | `mult_sel_i`               | `Bool` | Static decoder output. Used (with `div_sel_i`) to form `multdiv_sel`. |
| in  | `div_sel_i`                | `Bool` | Static decoder output. Drives the output muxes and multdiv's internal path selector. |
| in  | `multdiv_signed_mode_i`    | `UInt<2>` | Per-operand signedness for multdiv. |
| in  | `multdiv_operand_a_i`      | `UInt<32>` | Multdiv source operand A (numerator for DIV/REM). |
| in  | `multdiv_operand_b_i`      | `UInt<32>` | Multdiv source operand B (denominator for DIV/REM). |
| in  | `multdiv_ready_id_i`       | `Bool` | Back-pressure from ID stage; held high to acknowledge the multdiv result. |
| in  | `data_ind_timing_i`        | `Bool` | When 1, force constant-time divide schedule. |
| in  | `imd_val_q_i`              | `unpacked Vec<UInt<34>, 2>` | 34-bit intermediate-value register file fed back from EX-stage flop bank. Element [0] is the multiplier/divider accumulator; element [1] is the divisor. |
| out | `imd_val_we_o`             | `UInt<2>` | Per-lane write-enables for the intermediate-value flop bank. Selects between ALU (both 0 under RV32BNone) and multdiv write-enables. |
| out | `imd_val_d_o`              | `unpacked Vec<UInt<34>, 2>` | Intermediate-value write-data. Selects between `{2'b0, alu_imd_val_d[i]}` and `multdiv_imd_val_d[i]`. |
| out | `alu_adder_result_ex_o`    | `UInt<32>` | The ALU's adder result. Forwarded to the LSU for address computation and used as `branch_target_o` when `BranchTargetALU = 0`. |
| out | `result_ex_o`              | `UInt<32>` | Execute-stage result: `multdiv_sel ? multdiv_result : alu_result`. |
| out | `branch_target_o`          | `UInt<32>` | Branch target address. Equal to `alu_adder_result_ex_o` when `BranchTargetALU = 0`. |
| out | `branch_decision_o`        | `Bool` | Branch taken/not-taken comparator result. Wired from ALU's `comparison_result_o`. |
| out | `ex_valid_o`               | `Bool` | EX stage has a valid result: `multdiv_sel ? multdiv_valid : ~(|alu_imd_val_we)`. |

### Intermediate-value array width notes

- `imd_val_q_i[2]` and `imd_val_d_o[2]` are 34-bit unpacked arrays at
  the ex_block boundary (matching upstream `logic [33:0] imd_val_q_i [2]`).
- The **ALU sub-module** uses 32-bit intermediate values:
  `alu_imd_val_q[i] = imd_val_q_i[i][31:0]` (the upper 2 bits are sliced off
  before passing to the ALU).
- The **multdiv sub-module** uses the full 34 bits:
  `multdiv_imd_val_q = imd_val_q_i` (direct pass-through).
- On the write side:
  - Multdiv's `imd_val_d_o[i]` is already 34 bits → forwarded directly.
  - ALU's `imd_val_d_o[i]` is 32 bits → zero-extended to 34 bits:
    `{2'b0, alu_imd_val_d[i]}`.

## Internal signal summary

These are the combinational wires that exist inside the block:

| Name | Type | Source |
|---|---|---|
| `multdiv_sel` | `Bool` | `mult_sel_i \| div_sel_i` |
| `alu_result` | `UInt<32>` | ALU `result_o` |
| `multdiv_result` | `UInt<32>` | MultdivFast `multdiv_result_o` |
| `multdiv_alu_operand_a` | `UInt<33>` | MultdivFast `alu_operand_a_o` |
| `multdiv_alu_operand_b` | `UInt<33>` | MultdivFast `alu_operand_b_o` |
| `alu_adder_result_ext` | `UInt<34>` | ALU `adder_result_ext_o` |
| `alu_cmp_result` | `Bool` | ALU `comparison_result_o` |
| `alu_is_equal_result` | `Bool` | ALU `is_equal_result_o` |
| `multdiv_valid` | `Bool` | MultdivFast `valid_o` |
| `alu_imd_val_q` | `unpacked Vec<UInt<32>, 2>` | `imd_val_q_i[i][31:0]` slices |
| `alu_imd_val_d` | `unpacked Vec<UInt<32>, 2>` | ALU `imd_val_d_o` |
| `alu_imd_val_we` | `UInt<2>` | ALU `imd_val_we_o` |
| `multdiv_imd_val_d` | `unpacked Vec<UInt<34>, 2>` | MultdivFast `imd_val_d_o` |
| `multdiv_imd_val_we` | `UInt<2>` | MultdivFast `imd_val_we_o` |

## Sub-module instantiation

### `alu_i: IbexAlu`

Ports connected:

| IbexAlu port | Connected to |
|---|---|
| `operator_i` | `alu_operator_i` |
| `operand_a_i` | `alu_operand_a_i` |
| `operand_b_i` | `alu_operand_b_i` |
| `instr_first_cycle_i` | `alu_instr_first_cycle_i` |
| `imd_val_q_i` | `alu_imd_val_q` (32-bit slice of the 34-bit `imd_val_q_i`) |
| `imd_val_we_o` | `alu_imd_val_we` |
| `imd_val_d_o` | `alu_imd_val_d` |
| `multdiv_operand_a_i` | `multdiv_alu_operand_a` (from multdiv) |
| `multdiv_operand_b_i` | `multdiv_alu_operand_b` (from multdiv) |
| `multdiv_sel_i` | `multdiv_sel` |
| `adder_result_o` | `alu_adder_result_ex_o` (also output of ex_block) |
| `adder_result_ext_o` | `alu_adder_result_ext` |
| `result_o` | `alu_result` |
| `comparison_result_o` | `alu_cmp_result` |
| `is_equal_result_o` | `alu_is_equal_result` |

Note: `IbexAlu` is purely combinational (no clock, no reset).

### `multdiv_i: IbexMultdivFast`

Ports connected:

| IbexMultdivFast port | Connected to |
|---|---|
| `clk_i` | `clk_i` |
| `rst_ni` | `rst_ni` |
| `mult_en_i` | `mult_en_i` |
| `div_en_i` | `div_en_i` |
| `mult_sel_i` | `mult_sel_i` |
| `div_sel_i` | `div_sel_i` |
| `operator_i` | `multdiv_operator_i` |
| `signed_mode_i` | `multdiv_signed_mode_i` |
| `op_a_i` | `multdiv_operand_a_i` |
| `op_b_i` | `multdiv_operand_b_i` |
| `alu_operand_a_o` | `multdiv_alu_operand_a` |
| `alu_operand_b_o` | `multdiv_alu_operand_b` |
| `alu_adder_ext_i` | `alu_adder_result_ext` (from ALU) |
| `alu_adder_i` | `alu_adder_result_ex_o` (from ALU) |
| `equal_to_zero_i` | `alu_is_equal_result` (from ALU) |
| `data_ind_timing_i` | `data_ind_timing_i` |
| `imd_val_q_i` | `imd_val_q_i` (full 34-bit unpacked array) |
| `imd_val_d_o` | `multdiv_imd_val_d` |
| `imd_val_we_o` | `multdiv_imd_val_we` |
| `multdiv_ready_id_i` | `multdiv_ready_id_i` |
| `valid_o` | `multdiv_valid` |
| `multdiv_result_o` | `multdiv_result` |

## Requirements

### Requirement: multdiv_sel is the OR of mult_sel_i and div_sel_i

`multdiv_sel` SHALL be the combinational OR of `mult_sel_i` and
`div_sel_i`. `multdiv_sel = 1` indicates a multiply or divide operation
is currently occupying the EX stage; `multdiv_sel = 0` indicates an
ALU-only operation.

For `RV32MFast`, this assignment is unconditional (the `RV32MNone`
branch that forces `multdiv_sel = 0` does not apply).

(ref: ibex_ex_block.sv:77)

#### Scenario: Both selectors low → multdiv_sel = 0
- GIVEN `mult_sel_i = 0`, `div_sel_i = 0`
- WHEN inputs settle
- THEN `multdiv_sel = 0`

#### Scenario: mult_sel_i high → multdiv_sel = 1
- GIVEN `mult_sel_i = 1`, `div_sel_i = 0`
- WHEN inputs settle
- THEN `multdiv_sel = 1`

#### Scenario: div_sel_i high → multdiv_sel = 1
- GIVEN `mult_sel_i = 0`, `div_sel_i = 1`
- WHEN inputs settle
- THEN `multdiv_sel = 1`

---

### Requirement: result_ex_o mux

`result_ex_o` SHALL be selected combinationally from:
- `multdiv_result` (MultdivFast `multdiv_result_o`) when `multdiv_sel = 1`
- `alu_result` (ALU `result_o`) when `multdiv_sel = 0`

(ref: ibex_ex_block.sv:89)

#### Scenario: ALU operation result selected when multdiv_sel = 0
- GIVEN `multdiv_sel = 0`, ALU performs `ADD(3, 5)` → `alu_result = 8`
- WHEN inputs settle
- THEN `result_ex_o = 8`

#### Scenario: Multdiv result selected when multdiv_sel = 1
- GIVEN `multdiv_sel = 1`, multdiv presents `multdiv_result = 0x0000_006E` (110)
- WHEN `valid_o = 1`
- THEN `result_ex_o = 0x0000_006E`

---

### Requirement: imd_val_d_o mux (per-lane, 34-bit output)

Each lane of `imd_val_d_o` SHALL be selected combinationally:

```
imd_val_d_o[0] = multdiv_sel ? multdiv_imd_val_d[0] : {2'b0, alu_imd_val_d[0]}
imd_val_d_o[1] = multdiv_sel ? multdiv_imd_val_d[1] : {2'b0, alu_imd_val_d[1]}
```

When `multdiv_sel = 0`, the ALU's 32-bit lane is zero-extended to 34 bits
(the upper 2 bits are forced to `2'b00`). Under `RV32BNone`, the ALU drives
`alu_imd_val_d[i] = 32'h0` and `alu_imd_val_we = 2'b00`, so in practice
`imd_val_d_o[i] = 34'h0` and write-enable is 0 during ALU-only operations.

(ref: ibex_ex_block.sv:83-84)

#### Scenario: ALU path produces zero-extended 34-bit output (RV32BNone)
- GIVEN `multdiv_sel = 0`
- WHEN ALU drives `alu_imd_val_d[0] = 32'h0`, `alu_imd_val_d[1] = 32'h0`
- THEN `imd_val_d_o[0] = 34'h0`, `imd_val_d_o[1] = 34'h0`

#### Scenario: Multdiv path preserves full 34-bit lane content
- GIVEN `multdiv_sel = 1`, `multdiv_imd_val_d[0] = 34'h3_FFFF_FFFE`, `multdiv_imd_val_d[1] = 34'h0_0000_0007`
- WHEN inputs settle
- THEN `imd_val_d_o[0] = 34'h3_FFFF_FFFE`, `imd_val_d_o[1] = 34'h0_0000_0007`
- NOTE The upper 2 bits of lane 0 may be non-zero during MULH accumulation.

---

### Requirement: imd_val_we_o mux

`imd_val_we_o` SHALL be selected combinationally:

```
imd_val_we_o = multdiv_sel ? multdiv_imd_val_we : alu_imd_val_we
```

Under `RV32BNone`, `alu_imd_val_we = 2'b00` always, so when
`multdiv_sel = 0`, `imd_val_we_o = 2'b00`.

(ref: ibex_ex_block.sv:85)

#### Scenario: ALU path → imd_val_we_o = 0 (RV32BNone)
- GIVEN `multdiv_sel = 0`
- WHEN inputs settle
- THEN `imd_val_we_o = 2'b00`

#### Scenario: Multdiv path forwards multdiv's write-enables
- GIVEN `multdiv_sel = 1`, `multdiv_imd_val_we = 2'b01`
- WHEN inputs settle
- THEN `imd_val_we_o = 2'b01`

---

### Requirement: imd_val_q slice routing to ALU

The 32-bit ALU sub-module requires 32-bit intermediate values. The EX
block SHALL slice the lower 32 bits of each 34-bit `imd_val_q_i` element
before passing them to the ALU:

```
alu_imd_val_q[i] = imd_val_q_i[i][31:0]  for i in {0, 1}
```

The upper 2 bits `imd_val_q_i[i][33:32]` are discarded (the ALU ignores
them under `RV32BNone`). The multdiv sub-module receives the full 34-bit
`imd_val_q_i` directly (no slicing).

(ref: ibex_ex_block.sv:87)

#### Scenario: Upper 2 bits of imd_val_q_i are stripped for ALU
- GIVEN `imd_val_q_i[0] = 34'h3_DEAD_BEEF` (upper 2 bits = `2'b11`)
- WHEN the ALU sub-module's `imd_val_q_i[0]` is observed
- THEN it equals `32'hDEAD_BEEF` (lower 32 bits only)

---

### Requirement: branch_decision_o is wired from the ALU comparator

`branch_decision_o` SHALL be combinationally wired from the ALU's
`comparison_result_o` output. This is unconditional — it does not depend
on `multdiv_sel`. The branch unit samples this every cycle to determine
whether a conditional branch is taken.

(ref: ibex_ex_block.sv:92)

#### Scenario: ALU comparison result forwarded as branch decision
- GIVEN `alu_operator_i = ALU_EQ`, `alu_operand_a_i = 32'h42`, `alu_operand_b_i = 32'h42`
- WHEN inputs settle (ALU computes `alu_cmp_result = 1`)
- THEN `branch_decision_o = 1`

#### Scenario: Not-taken branch
- GIVEN `alu_operator_i = ALU_EQ`, `alu_operand_a_i = 32'h1`, `alu_operand_b_i = 32'h2`
- WHEN inputs settle (ALU computes `alu_cmp_result = 0`)
- THEN `branch_decision_o = 0`

---

### Requirement: branch_target_o is wired from alu_adder_result_ex_o (BranchTargetALU = 0)

When `BranchTargetALU = 0` (the SoC configuration), `branch_target_o`
SHALL be combinationally wired from `alu_adder_result_ex_o` — i.e. the
ALU's 32-bit adder result. There is no dedicated branch-target adder in
this configuration.

The `bt_a_operand_i` and `bt_b_operand_i` inputs SHALL be connected to
unused dummy signals (ARCH `let` bindings) to suppress Verilator UNUSED
warnings, matching upstream's `unused_bt_a_operand` / `unused_bt_b_operand`
pattern.

(ref: ibex_ex_block.sv:102-110)

#### Scenario: branch_target_o = adder result (ADD instruction)
- GIVEN `alu_operator_i = ALU_ADD`, `alu_operand_a_i = 32'h1000_0000`, `alu_operand_b_i = 32'h0000_0008`
- WHEN inputs settle
- THEN `alu_adder_result_ex_o = 32'h1000_0008`
- AND  `branch_target_o = 32'h1000_0008`

---

### Requirement: ex_valid_o combinational validity signal

`ex_valid_o` SHALL be driven combinationally:

```
ex_valid_o = multdiv_sel ? multdiv_valid : ~(|alu_imd_val_we)
```

When `multdiv_sel = 1`, the multdiv's `valid_o` signal gates the output.
When `multdiv_sel = 0`, the ALU result is valid iff it is not mid-operation
(the ALU has no multi-cycle ops under `RV32BNone`, so `alu_imd_val_we =
2'b00` always, meaning `ex_valid_o = ~(|2'b00) = 1` for all ALU-only
operations).

(ref: ibex_ex_block.sv:197)

#### Scenario: ALU-only operation → ex_valid_o = 1 (RV32BNone)
- GIVEN `multdiv_sel = 0` (any ALU operation under RV32BNone)
- WHEN inputs settle (ALU drives `alu_imd_val_we = 2'b00`)
- THEN `ex_valid_o = 1`

#### Scenario: Multdiv in-progress → ex_valid_o = multdiv_valid
- GIVEN `multdiv_sel = 1`, `multdiv_valid = 0` (multdiv FSM not in terminal state)
- WHEN inputs settle
- THEN `ex_valid_o = 0`

#### Scenario: Multdiv finishes → ex_valid_o = 1
- GIVEN `multdiv_sel = 1`, `multdiv_valid = 1` (multdiv reached AHBL/MD_FINISH)
- WHEN inputs settle
- THEN `ex_valid_o = 1`

---

### Requirement: Combinational cross-coupling loop between ALU and multdiv

The ALU and multdiv form a **same-cycle combinational loop**:

1. The multdiv drives `alu_operand_a_o` / `alu_operand_b_o` (33 bits each)
   → wired to ALU's `multdiv_operand_a_i` / `multdiv_operand_b_i`.
2. The ALU (when `multdiv_sel = 1`) computes the sum and presents:
   - `adder_result_ext_o` (34 bits) → wired to multdiv's `alu_adder_ext_i`
   - `adder_result_o` (32 bits) → wired to multdiv's `alu_adder_i`
   - `is_equal_result_o` → wired to multdiv's `equal_to_zero_i`
3. The multdiv consumes these same-cycle, with no flip-flop in the loop.

The EX block SHALL wire these signals as siblings — the ex_block does
NOT pipeline or register any of these cross-coupling signals. The
module must be tested as a unit (not by driving sub-modules separately)
so that the comb loop resolves correctly through the combined netlist.

(ref: ibex_ex_block.sv:116-134, 165-192; multdiv spec "ALU operand exchange")

#### Scenario: Multdiv ALU operands flow through the EX block to the ALU
- GIVEN multdiv drives `alu_operand_a_o = 33'h0_0000_0001`, `alu_operand_b_o = 33'h1_FFFF_FFFF` (LSB-1 subtraction operands)
- WHEN `multdiv_sel = 1` and inputs settle
- THEN the ALU receives these as `multdiv_operand_a_i` / `multdiv_operand_b_i` and the multdiv receives back `alu_adder_ext_i = 34'h2_0000_0000`

---

## Integration constraints (EX block perspective)

1. **Multdiv and ALU never simultaneously active**: the ID-stage decoder
   guarantees at most one of `mult_sel_i`, `div_sel_i` is high at a time.
   Both being low means an ALU-only operation. Both high simultaneously
   is undefined behaviour.

2. **imd_val_q_i is the flop bank output updated by the ID/WB stage**:
   on every cycle where `imd_val_we_o[i] = 1`, the EX block's caller
   latches `imd_val_d_o[i]` and feeds it back on `imd_val_q_i[i]` the
   next cycle. The ex_block itself does not own these registers.

3. **ALU is always active** (combinationally): even during a multdiv
   operation, the ALU processes the multdiv's `alu_operand_*_o` with
   `multdiv_sel_i = 1`. The ALU's `result_o` (i.e. `alu_result`) is
   ignored in this case (it is not selected by `result_ex_o`), but its
   adder outputs (`adder_result_o`, `adder_result_ext_o`,
   `is_equal_result_o`) are consumed by the multdiv.

4. **branch_decision_o is always valid**: the ID stage samples it on
   every branch instruction. It always reflects the ALU's current
   comparison. During a multdiv operation the branch instruction has
   already left the EX stage, so the value on `branch_decision_o` is
   harmless.

5. **alu_adder_result_ex_o is forwarded to the LSU**: the LSU samples
   this every cycle for address computation. It is the ALU's adder
   result regardless of `multdiv_sel`.

## Notes

- `bt_a_operand_i` and `bt_b_operand_i` are unused in the SoC
  (`BranchTargetALU = 0`). The ARCH implementation SHALL connect them
  to dummy let-bound variables (not leave them undriven) to match
  upstream's lint-clean pattern.

- Under `RV32BNone`, `alu_imd_val_we = 2'b00` always (see ALU spec,
  "imd_val_d_o and imd_val_we_o under RV32BNone"). Therefore:
  - `imd_val_we_o = 2'b00` during any ALU-only operation.
  - `ex_valid_o = 1` during any ALU-only operation.
  - `imd_val_d_o[i] = 34'h0` during any ALU-only operation.

- The `multdiv_sel` signal is static (driven by the decoder) for the
  duration of any given instruction. It does not pulse within an
  instruction.
