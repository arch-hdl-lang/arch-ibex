# Multdiv (fast variant) Specification

## Purpose

The Ibex fast multiplier/divider (`ibex_multdiv_fast`, RV32M = RV32MFast)
is the multi-cycle execution unit that implements the eight RV32M
instructions — `MUL`, `MULH`, `MULHSU`, `MULHU`, `DIV`, `DIVU`, `REM`,
`REMU` — by walking a small finite-state machine across several clocks
and accumulating partial state in two 34-bit intermediate-value
registers (`imd_val_q_i[0]`, `imd_val_q_i[1]`) that physically live in
the EX block and are gated by the unit's `imd_val_we_o`.

The unit is unusual in that it does **not** instantiate its own adder
or zero-comparator. Instead it co-opts the EX-block ALU's adder by
driving 33-bit operands out on `alu_operand_a_o` / `alu_operand_b_o`
and consuming the ALU's combinational sum back on `alu_adder_ext_i`
(34 b) / `alu_adder_i` (32 b) and `equal_to_zero_i` the **same cycle**.
Per cycle of the FSM the unit decides which operands the adder shall
produce, samples the result combinationally, and decides the next
state — there is no flip-flop in the loop between operand drive and
adder consumption. (See "ALU operand exchange" requirement below and
cross-reference the ALU spec, requirement "Adder uses multdiv operands
when `multdiv_sel_i = 1`".)

The fast multiplier has a 16×16 kernel (`(sign_a,op_a) * (sign_b,op_b)
+ accum`, all sign-extended to 17 b on each side) and produces partial
products that are accumulated in `imd_val_q_i[0]` over 3 cycles for
`MUL` and 4 cycles for `MULH` family. The divider uses a long-division
shift-and-subtract scheme: numerator and denominator are absolute-
valued through the ALU adder, then 32 conditional-subtract iterations
shift the partial remainder one bit at a time while the quotient bit
is OR'd into `op_quotient_q`. Sign correction at the end runs another
ALU-adder negation. With `data_ind_timing_i = 1` the divider always
takes the worst-case schedule regardless of operand magnitude or a
zero divisor, eliminating timing side-channels.

This spec covers `RV32M = RV32MFast` exclusively. The `RV32MSingleCycle`
branch (`gen_mult_single_cycle`) of the same SV file uses three
parallel 17-bit multipliers and a different mult-FSM and is **out of
scope**.

## Port contract

| Direction | Name | ARCH type | Width | Description |
|---|---|---|---|---|
| param | `RV32M` | `rv32m_e` (enum, integer-encoded) | — | Multiplier configuration. This spec covers only `RV32MFast` (= 2). The implementation MAY ignore the parameter (it is fixed by the surrounding port-list). |
| in  | `clk_i`              | `Clock`     | 1  | Positive-edge clock for all flip-flops. |
| in  | `rst_ni`             | `AsyncResetN` | 1 | Active-low asynchronous reset. |
| in  | `mult_en_i`          | `Bool`      | 1  | Dynamic enable for multiplier FSM advancement. Held high by the ID stage for the **entire** multi-cycle MUL/MULH (including its hold cycle). |
| in  | `div_en_i`           | `Bool`      | 1  | Dynamic enable for divider FSM advancement. Held high by the ID stage for the **entire** multi-cycle DIV/REM. |
| in  | `mult_sel_i`         | `Bool`      | 1  | Static decoder output. Used externally by the EX block's mux (`multdiv_sel = mult_sel_i \| div_sel_i`). The multdiv unit itself ignores this signal (assigned to `unused_mult_sel_i`). |
| in  | `div_sel_i`          | `Bool`      | 1  | Static decoder output. Selects the divide path inside the multdiv: gates `imd_val_d_o[0]` between `op_remainder_d` (div) and `mac_res_d` (mult), and gates `multdiv_result_o` between `imd_val_q_i[0][31:0]` (div) and `mac_res_d[31:0]` (mult). |
| in  | `operator_i`         | `UInt<2>` (encodes `md_op_e`) | 2 | One of `MD_OP_MULL`, `MD_OP_MULH`, `MD_OP_DIV`, `MD_OP_REM`. See "Enum encodings". |
| in  | `signed_mode_i`      | `UInt<2>`   | 2  | Per-operand signedness: `signed_mode_i[0]` for `op_a`, `signed_mode_i[1]` for `op_b`. The four values `2'b00 / 2'b11 / 2'b01 / 2'b10` correspond to MULHU/DIVU/REMU, MULH/DIV/REM, MULHSU, and (unused for mult, used for div mixed-sign) respectively. |
| in  | `op_a_i`             | `UInt<32>`  | 32 | Source operand A (numerator for DIV/REM). |
| in  | `op_b_i`             | `UInt<32>`  | 32 | Source operand B (denominator for DIV/REM). |
| in  | `alu_adder_ext_i`    | `UInt<34>`  | 34 | The ALU's 34-bit extended adder result, sampled combinationally same cycle the unit drives `alu_operand_*_o`. Bits `[32:1]` form `res_adder_h` used as the divider's next-remainder candidate. Bits `[33]` and `[0]` are unused inside the multdiv (`unused_alu_adder_ext`). |
| in  | `alu_adder_i`        | `UInt<32>`  | 32 | The ALU's 32-bit adder result. Used by the divider for absolute-value computation (`MD_ABS_A`, `MD_ABS_B`) and final sign change (`MD_CHANGE_SIGN`). |
| in  | `equal_to_zero_i`    | `Bool`      | 1  | The ALU's zero-comparator output. Sampled in `MD_IDLE` to detect divide-by-zero and force the FSM to skip directly to `MD_FINISH` (only when `data_ind_timing_i = 0`). |
| in  | `data_ind_timing_i`  | `Bool`      | 1  | When `1`, suppress the early-out for divide-by-zero so DIV/REM always take the full schedule; eliminates operand-magnitude timing leakage. |
| out | `alu_operand_a_o`    | `UInt<33>`  | 33 | A operand to the EX-block ALU's shared adder. The unit's combinational logic sets this every cycle. (See "ALU operand exchange".) |
| out | `alu_operand_b_o`    | `UInt<33>`  | 33 | B operand to the EX-block ALU's shared adder, same-cycle pairing with `alu_operand_a_o`. |
| in  | `imd_val_q_i[2]`     | unpacked array of 2 × `UInt<34>` | 2×34 | Intermediate-value register file fed back from the EX-stage flop bank. Lane 0 holds the partial product (mult) or partial remainder (div). Lane 1 holds the absolute-valued denominator (div only). |
| out | `imd_val_d_o[2]`     | unpacked array of 2 × `UInt<34>` | 2×34 | Intermediate-value write-data driven back to the EX-stage flop bank. |
| out | `imd_val_we_o`       | `UInt<2>`   | 2  | Per-lane write-enable for the intermediate-value flops. Lane 0 enabled whenever the multdiv FSM is advancing (`multdiv_en`); lane 1 enabled only on divider advancement (`div_en_internal`). |
| in  | `multdiv_ready_id_i` | `Bool`      | 1  | Back-pressure from the ID stage. When the unit reaches its terminal cycle (final mult cycle, or `MD_FINISH`) and `multdiv_ready_id_i = 0`, the FSM **holds** in that state with `valid_o = 1` until the ID stage acknowledges. |
| out | `multdiv_result_o`   | `UInt<32>`  | 32 | Final result word. For mult: `mac_res_d[31:0]`. For div: `imd_val_q_i[0][31:0]` (which holds the post-sign-correction quotient or remainder). Combinational and only meaningful when `valid_o = 1`. |
| out | `valid_o`            | `Bool`      | 1  | One-cycle pulse (held until acknowledged via `multdiv_ready_id_i`) signalling the result on `multdiv_result_o` is valid. Equals `mult_valid \| div_valid`. |

### Width notes (load-bearing)

- `alu_operand_a_o` / `alu_operand_b_o` are **33 bits**, not 32. The
  extra bit is the LSB-injected "1" used by the ALU adder to materialise
  `~B + 1` style two's-complement subtractions without dedicating a
  carry-in. Every drive of these ports follows the form
  `{<32-bit value>, 1'b1}` or `{~<32-bit value>, 1'b1}` (ref:
  ibex_multdiv_fast.sv:419-420, 448-449, 461-462, 473-474, 482-483,
  496-497, 510-511).
- `alu_adder_ext_i` is **34 bits** because the ALU produces
  `{a,1'b1} + {b,1'b1}`-style 34-bit sums; the multdiv reads bits
  `[32:1]` as the meaningful 32-bit difference (`res_adder_h`).
- `imd_val_q_i[i]` and `imd_val_d_o[i]` are **34 bits each** so the
  multiplier's accumulator can hold the partial-product carry-out plus
  signed-MSB extension (bits `[33:32]` of lane 0). Lane 1 only needs
  32 bits for the divisor; bits `[33:32]` are forced to `2'b00` on
  write (line 127) and the unit declares the read-side bits unused.

## Enum encodings

### `md_op_e` (operator selector — input `operator_i`)

`md_op_e` is a 2-bit enum declared in `ibex_pkg.sv` whose members are
assigned sequentially starting at 0 (ref: ibex_pkg.sv:194-200):

| Member         | Integer value | Bit pattern |
|----------------|---------------|-------------|
| `MD_OP_MULL`   | 0             | `2'b00` |
| `MD_OP_MULH`   | 1             | `2'b01` |
| `MD_OP_DIV`    | 2             | `2'b10` |
| `MD_OP_REM`    | 3             | `2'b11` |

The eight RISC-V RV32M instructions are dispatched onto these four
operators by combining `operator_i` with `signed_mode_i`:

| RISC-V mnemonic | `operator_i`  | `signed_mode_i` |
|-----------------|---------------|-----------------|
| `MUL`           | `MD_OP_MULL`  | `2'b00`         |
| `MULH`          | `MD_OP_MULH`  | `2'b11`         |
| `MULHSU`        | `MD_OP_MULH`  | `2'b01` (a signed, b unsigned) |
| `MULHU`         | `MD_OP_MULH`  | `2'b00`         |
| `DIV`           | `MD_OP_DIV`   | `2'b11`         |
| `DIVU`          | `MD_OP_DIV`   | `2'b00`         |
| `REM`           | `MD_OP_REM`   | `2'b11`         |
| `REMU`          | `MD_OP_REM`   | `2'b00`         |

(`MD_OP_MULL` ignores `signed_mode_i` because the low 32 bits of an
A×B product are identical regardless of whether the operands are
treated as signed or unsigned.)

### Multiplier internal state — `mult_fsm_e` (fast variant)

Declared inside `gen_mult_fast` (ref: ibex_multdiv_fast.sv:268-271).
2-bit enum, sequentially assigned:

| State  | Integer value | Meaning |
|--------|---------------|---------|
| `ALBL` | 0 | Compute `op_a[15:0] * op_b[15:0]`. Idle/start state. |
| `ALBH` | 1 | Compute `op_a[15:0] * op_b[31:16]` plus accumulator. |
| `AHBL` | 2 | Compute `op_a[31:16] * op_b[15:0]` plus accumulator. For `MD_OP_MULL` this is the terminal state. |
| `AHBH` | 3 | Compute `op_a[31:16] * op_b[31:16]` plus accumulator. Terminal state for `MD_OP_MULH`. |

### Divider internal state — `md_fsm_e`

Declared at module scope (ref: ibex_multdiv_fast.sv:90-92). 3-bit enum,
sequentially assigned:

| State           | Integer value | Meaning |
|-----------------|---------------|---------|
| `MD_IDLE`       | 0 | Reset / quiescent. Captures divide-by-zero and seeds initial remainder. |
| `MD_ABS_A`      | 1 | Compute `|op_a|` via ALU adder (`0 - op_a` if `div_sign_a`). |
| `MD_ABS_B`      | 2 | Compute `|op_b|` via ALU adder; seed `op_remainder_d` with the high bit of the numerator. |
| `MD_COMP`       | 3 | Long-division iteration: 31 cycles of conditional shift-and-subtract. |
| `MD_LAST`       | 4 | Final iteration: write the result (quotient for DIV, remainder for REM) into lane 0. |
| `MD_CHANGE_SIGN`| 5 | Conditionally negate the result via the ALU adder. |
| `MD_FINISH`     | 6 | Hold `valid_o = 1` until the ID stage acknowledges via `multdiv_ready_id_i`. |

Total non-`MD_IDLE` cycles for a non-zero divide: 1 + 1 + 31 + 1 + 1 + 1 = 36 cycles of FSM advancement plus the `MD_IDLE` setup cycle = 37 cycles of stall observed by the ID stage (consistent with `pipeline_details.rst` "1 or 37" for division).

## Requirements

### Requirement: Multiplier FSM walks ALBL → ALBH → AHBL for MUL (3 cycles)

When `mult_en_i = 1` and `operator_i = MD_OP_MULL`, the multiplier FSM
SHALL traverse states `ALBL → ALBH → AHBL → ALBL` over three rising
clock edges. `mult_valid` MUST be asserted only in state `AHBL`. The
final result word `mac_res_d[31:0]` is the low 32 bits of the
unsigned product `op_a × op_b` regardless of `signed_mode_i` (the low
half is sign-agnostic).

The state register only advances when `mult_en_internal = mult_en_i &
~mult_hold` (line 98) is high. `mult_hold` is set by the FSM in the
terminal state if `multdiv_ready_id_i = 0`, freezing the FSM at the
final state with `mult_valid = 1` until the ID stage drains.

The accumulator chain across the three cycles writes
`imd_val_d_o[0]` every cycle (lane-0 write-enable = `multdiv_en`,
line 125). Per-cycle behaviour:

- **Cycle 1 (`ALBL`)**: `accum = 0`; multiplier inputs are
  `(0, op_a[15:0]) × (0, op_b[15:0])`. `mac_res_d = mac_res` (the raw
  unsigned 32-bit kernel result, zero-extended to 34 b) is written to
  `imd_val_d_o[0]`. Next state = `ALBH`.
- **Cycle 2 (`ALBH`)**: `accum = {18'b0, imd_val_q_i[0][31:16]}` (the
  upper 16 bits of the AL×BL product); multiplier inputs are
  `(0, op_a[15:0]) × (signed_mode_i[1] & op_b[31], op_b[31:16])`.
  Because `operator_i = MD_OP_MULL`, `mac_res_d = {2'b0,
  mac_res[15:0], imd_val_q_i[0][15:0]}` — i.e., the low 16 bits of
  `(al×bh + (al×bl)>>16)` are concatenated with the saved low 16 bits
  of AL×BL to form the bottom half of the running product. Next state
  = `AHBL`.
- **Cycle 3 (`AHBL`)**: `accum = {18'b0, imd_val_q_i[0][31:16]}` (the
  upper 16 bits of the running product from cycle 2); multiplier
  inputs are `(signed_mode_i[0] & op_a[31], op_a[31:16]) × (0,
  op_b[15:0])`. `mac_res_d = {2'b0, mac_res[15:0], imd_val_q_i[0][15:0]}`.
  `mult_valid = 1`. `mult_hold = ~multdiv_ready_id_i`. Next state =
  `ALBL` (only if `mult_hold = 0`).

#### Scenario: MUL with two unsigned operands

- GIVEN `operator_i = MD_OP_MULL`, `signed_mode_i = 2'b00`, `op_a_i = 32'h0000_1234`, `op_b_i = 32'h0000_5678`, `mult_en_i = 1`, `multdiv_ready_id_i = 1`, FSM in `ALBL`
- WHEN three rising clock edges elapse
- THEN at cycle 3 (state `AHBL`) `valid_o = 1` and `multdiv_result_o = 32'h06A4_1C80` (= `0x1234 * 0x5678`)
- (ref: ibex_multdiv_fast.sv:295-342, 529)

#### Scenario: MUL with negative signed multiplicand returns same low 32 bits

- GIVEN `operator_i = MD_OP_MULL`, `signed_mode_i = 2'b11`, `op_a_i = 32'hFFFF_FFFF` (= -1), `op_b_i = 32'h0000_0007`, `mult_en_i = 1`, `multdiv_ready_id_i = 1`
- WHEN three rising clock edges elapse
- THEN `multdiv_result_o = 32'hFFFF_FFF9` (= -7 in two's complement = low 32 b of unsigned `0xFFFF_FFFF * 7 = 0x6_FFFF_FFF9`)
- (ref: ibex_multdiv_fast.sv:295-342)

#### Scenario: MUL backpressured by the ID stage

- GIVEN the multiplier has reached `AHBL` with `mult_valid = 1` and `multdiv_ready_id_i = 0` for two extra cycles
- WHEN those two extra cycles elapse
- THEN the FSM SHALL remain in `AHBL`, `mult_valid` SHALL stay `1`, and `multdiv_result_o` SHALL stay constant. State advances to `ALBL` only on the cycle when `multdiv_ready_id_i = 1`.
- (ref: ibex_multdiv_fast.sv:336, 359)

---

### Requirement: Multiplier FSM walks ALBL → ALBH → AHBL → AHBH for MULH/MULHSU/MULHU (4 cycles)

When `mult_en_i = 1` and `operator_i = MD_OP_MULH`, the multiplier FSM
SHALL traverse states `ALBL → ALBH → AHBL → AHBH → ALBL` over four
rising clock edges. `mult_valid` MUST be asserted only in state
`AHBH`. The final result word `mac_res_d[31:0]` is the high 32 bits of
the (signed-or-unsigned-as-decoded) product `op_a × op_b`.

Per-cycle behaviour differs from `MD_OP_MULL` in cycles 2 and 3:

- **Cycle 2 (`ALBH`, `MD_OP_MULH`)**: `mac_res_d = mac_res` (the raw
  34-bit kernel sum, no shift+concatenate trick). The full 34-bit
  partial sum `(al×bh) + (al×bl)>>16` is preserved in lane 0.
- **Cycle 3 (`AHBL`, `MD_OP_MULH`)**: `accum = imd_val_q_i[0]` (full
  34 b, signed); multiplier is `(signed_mode_i[0] & op_a[31],
  op_a[31:16]) × (0, op_b[15:0])`. `mac_res_d = mac_res`. Next state
  = `AHBH`.
- **Cycle 4 (`AHBH`)**: multiplier is `(signed_mode_i[0] & op_a[31],
  op_a[31:16]) × (signed_mode_i[1] & op_b[31], op_b[31:16])`. `accum`
  is built from `imd_val_q_i[0][33:16]` placed in `accum[17:0]` and a
  16-bit sign extension of `imd_val_q_i[0][33]` (gated by
  `signed_mult`) placed in `accum[33:18]`. `mac_res_d = mac_res`.
  `mult_valid = 1`. `mult_hold = ~multdiv_ready_id_i`. Next state =
  `ALBL`.

The 16-bit right-shift between cycle 3 and cycle 4 is implicit in the
`accum` slice: by reading `imd_val_q_i[0][33:16]` into `accum[17:0]`
the implementation effectively divides the running product by 2^16
before adding the AH×BH partial that itself contributes the bits
weighted at 2^32.

#### Scenario: MULHU produces upper 32 bits of unsigned product

- GIVEN `operator_i = MD_OP_MULH`, `signed_mode_i = 2'b00`, `op_a_i = 32'hFFFF_FFFF`, `op_b_i = 32'hFFFF_FFFF`, `mult_en_i = 1`, `multdiv_ready_id_i = 1`
- WHEN four rising clock edges elapse
- THEN at cycle 4 (state `AHBH`) `valid_o = 1` and `multdiv_result_o = 32'hFFFF_FFFE` (= upper 32 b of `0xFFFF_FFFF * 0xFFFF_FFFF = 0xFFFF_FFFE_0000_0001`)
- (ref: ibex_multdiv_fast.sv:344-360)

#### Scenario: MULH with two negatives produces positive upper word

- GIVEN `operator_i = MD_OP_MULH`, `signed_mode_i = 2'b11`, `op_a_i = 32'h8000_0000` (= -2^31), `op_b_i = 32'hFFFF_FFFF` (= -1), `mult_en_i = 1`, `multdiv_ready_id_i = 1`
- WHEN four rising clock edges elapse
- THEN `multdiv_result_o = 32'h0000_0000` (signed product = `0x8000_0000_0000_0000`; upper word is `0x0000_0000`)
- AND  the low word that *would* be produced by `MD_OP_MULL` is `0x8000_0000` — but that path is not taken because `operator_i = MD_OP_MULH`
- (ref: ibex_multdiv_fast.sv:344-360)

#### Scenario: MULHSU mixes signed-A with unsigned-B

- GIVEN `operator_i = MD_OP_MULH`, `signed_mode_i = 2'b01` (A signed, B unsigned), `op_a_i = 32'hFFFF_FFFF` (= -1), `op_b_i = 32'h0000_0002`, `mult_en_i = 1`, `multdiv_ready_id_i = 1`
- WHEN four rising clock edges elapse
- THEN `multdiv_result_o = 32'hFFFF_FFFF` (-1 as unsigned-`a` × signed-`b` interpretation: -1 × 2 = -2; upper word of -2 is `0xFFFF_FFFF`)
- (ref: ibex_multdiv_fast.sv:344-360, 168-169 sign-bit derivation, 311 / 327 / 349-350 per-state usage)

---

### Requirement: 16×16 kernel multiplier with sign-extension to 17 b each side

The kernel multiplier SHALL implement
`mac_res_signed = $signed({sign_a, mult_op_a}) * $signed({sign_b, mult_op_b}) + $signed(accum)`
where `mult_op_a`/`mult_op_b` are 16-bit slices of `op_a_i`/`op_b_i`,
`sign_a`/`sign_b` are single-bit sign-extension bits, and `accum` is
the 34-bit accumulator. The kernel produces `mac_res_signed` of
35 bits; the unit zero-extends it to 35 b on `mac_res_ext` and
truncates to bits `[33:0]` for the consumer (`mac_res = mac_res_ext[33:0]`).
The dropped bit `mac_res_ext[34]` is documented as redundant in the SV
(ref: ibex_multdiv_fast.sv:273-280): the 2 MSBs of the multiplicants
are always equal (because we sign-extend to 17 b) and the 16 MSBs of
`accum` are always equal, so `mac_res_ext[34] == mac_res_ext[33]` and
discarding the top bit is safe.

`sign_a` is set to `signed_mode_i[0] & op_a_i[31]` only on cycles where
`op_a[31:16]` is the active multiplicand (states `AHBL`, `AHBH`),
otherwise `0`. Symmetrically, `sign_b = signed_mode_i[1] & op_b_i[31]`
only on states `ALBH`, `AHBH`.

#### Scenario: 17-bit sign extension of `0x8000` slice

- GIVEN `mult_op_a = 16'h8000`, `sign_a = 1`, `mult_op_b = 16'h0001`, `sign_b = 0`, `accum = 0`
- WHEN the kernel evaluates
- THEN `mac_res_signed = $signed(17'h1_8000) * $signed(17'h0_0001) + 0 = -32768`
- AND  `mac_res = 34'h3_FFFF_8000` (sign-extended -32768 in 34 b)
- (ref: ibex_multdiv_fast.sv:277-280)

---

### Requirement: Result mux gates between divide and multiply paths via `div_sel_i`

`multdiv_result_o` SHALL equal `imd_val_q_i[0][31:0]` when `div_sel_i = 1`
and `mac_res_d[31:0]` when `div_sel_i = 0`. This is a pure combinational
mux on `div_sel_i` (ref: ibex_multdiv_fast.sv:136). It is the
caller's responsibility to assert `valid_o` only on the cycle the
correct operand has been selected; the multdiv unit asserts `valid_o`
internally as `mult_valid | div_valid` and the EX block forwards.

Lane-0 writeback follows the same pattern: `imd_val_d_o[0] =
op_remainder_d` when `div_sel_i = 1`, else `mac_res_d` (ref: line 124).

#### Scenario: Mid-divide multdiv_result_o is undefined-but-stable

- GIVEN a divide is in progress in state `MD_COMP` with `div_sel_i = 1`
- WHEN `multdiv_result_o` is sampled
- THEN it equals `imd_val_q_i[0][31:0]` (the partial remainder), but `valid_o = 0` so the consumer MUST NOT use it
- (ref: ibex_multdiv_fast.sv:136, 529)

---

### Requirement: Divider FSM sequence for non-zero non-overflow operands (37 cycles)

When `div_en_i = 1`, `operator_i ∈ {MD_OP_DIV, MD_OP_REM}`, and
`equal_to_zero_i = 0`, the divider FSM SHALL traverse:

```
MD_IDLE → MD_ABS_A → MD_ABS_B → MD_COMP × 31 → MD_LAST → MD_CHANGE_SIGN → MD_FINISH → (MD_IDLE)
```

with `div_valid = 1` only in `MD_FINISH`. The FSM state register only
advances when `div_en_internal = div_en_i & ~div_hold` (line 99) is
high; `div_hold` is set in `MD_FINISH` if `multdiv_ready_id_i = 0`,
freezing the FSM with `div_valid = 1`.

Per-state behaviour:

- **`MD_IDLE`** (line 426): `div_counter_d = 31`. Drive
  `alu_operand_a_o = {32'h0, 1'b1}` and `alu_operand_b_o = {~op_b_i,
  1'b1}` so the ALU computes `0 - op_b_i` which, combined with
  `equal_to_zero_i`, signals divide-by-zero. For `MD_OP_DIV`: seed
  `op_remainder_d = '1` (all-ones, will become `-1` after sign
  correction is suppressed). For `MD_OP_REM`: seed `op_remainder_d =
  {2'b0, op_a_i}`. Always advance to `MD_ABS_A` unless
  `data_ind_timing_i = 0 && equal_to_zero_i = 1` (then jump to
  `MD_FINISH`). `div_by_zero_d = equal_to_zero_i` is captured for
  later sign-suppression in `MD_CHANGE_SIGN`.
- **`MD_ABS_A`** (line 453): drive
  `alu_operand_a_o = {32'h0, 1'b1}` and `alu_operand_b_o = {~op_a_i,
  1'b1}` so the ALU computes `0 - op_a_i = -op_a_i` (= `|op_a_i|` if
  signed and negative). Capture `op_numerator_d = div_sign_a ?
  alu_adder_i : op_a_i`. Reset `op_quotient_d = 0`. `div_counter_d =
  31`. Advance to `MD_ABS_B`.
- **`MD_ABS_B`** (line 465): drive
  `alu_operand_a_o = {32'h0, 1'b1}` and `alu_operand_b_o = {~op_b_i,
  1'b1}` so the ALU computes `-op_b_i`. Capture `op_denominator_d =
  div_sign_b ? alu_adder_i : op_b_i`. Seed `op_remainder_d = {33'h0,
  op_numerator_q[31]}` — i.e., the partial remainder starts with the
  MSB of the absolute-valued numerator preloaded as the bit being
  shifted in. `div_counter_d = 31`. Advance to `MD_COMP`.
- **`MD_COMP`** (line 477): the long-division step. Drive
  `alu_operand_a_o = {imd_val_q_i[0][31:0], 1'b1}` (the partial
  remainder) and `alu_operand_b_o = {~op_denominator_q[31:0], 1'b1}`
  (two's-complement of the divisor) so the ALU computes
  `partial_remainder - divisor`. Compute `is_greater_equal` from
  `alu_adder_ext_i[32:1] == res_adder_h` and the sign rule below.
  Update:
  - `next_remainder = is_greater_equal ? res_adder_h[31:0] : imd_val_q_i[0][31:0]`
  - `next_quotient = is_greater_equal ? op_quotient_q | one_shift : op_quotient_q`
    where `one_shift = 32'h1 << div_counter_q`
  - `op_remainder_d = {1'b0, next_remainder[31:0], op_numerator_q[div_counter_d]}`
    (shift left, inject next numerator bit at LSB)
  - `op_quotient_d = next_quotient[31:0]`
  - `div_counter_d = div_counter_q - 1`
  - Stay in `MD_COMP` until `div_counter_q == 5'd1`, then advance to
    `MD_LAST`.
  
  This iterates 31 times (counter values 31 down to 1).
- **`MD_LAST`** (line 486): one more conditional-subtract using the
  same adder operands as `MD_COMP`. For `MD_OP_DIV`: write
  `op_remainder_d = {1'b0, next_quotient}` (the quotient is the result
  to expose). For `MD_OP_REM`: write `op_remainder_d = {2'b0,
  next_remainder[31:0]}` (the remainder is the result to expose).
  Advance to `MD_CHANGE_SIGN`.
- **`MD_CHANGE_SIGN`** (line 502): drive
  `alu_operand_a_o = {32'h0, 1'b1}` and
  `alu_operand_b_o = {~imd_val_q_i[0][31:0], 1'b1}` so the ALU
  computes `-imd_val_q_i[0][31:0]`. For `MD_OP_DIV`, change sign iff
  `div_change_sign = (div_sign_a ^ div_sign_b) & ~div_by_zero_q`. For
  `MD_OP_REM`, change sign iff `rem_change_sign = div_sign_a` (the
  remainder takes the sign of the dividend). Otherwise keep
  `imd_val_q_i[0]` unchanged. Advance to `MD_FINISH`.
- **`MD_FINISH`** (line 514): assert `div_valid = 1`. If
  `multdiv_ready_id_i = 1`, advance to `MD_IDLE`; otherwise hold via
  `div_hold = 1`.

The `is_greater_equal` rule (line 398) handles the case where the
partial remainder has overflowed the 32-bit field by checking the
XOR of MSBs:

```
if (imd_val_q_i[0][31] ^ op_denominator_q[31]) == 0:
    is_greater_equal = ~res_adder_h[31]    // same sign: subtract worked iff result non-negative
else:
    is_greater_equal = imd_val_q_i[0][31]  // mixed sign: trust the partial remainder MSB
```

Internally `op_denominator_q` is sourced from `imd_val_q_i[1][31:0]`
(line 129) — i.e. the divisor lives in lane 1 of the intermediate-value
register file, written from `op_denominator_d = {2'b0, /*32 b*/}`
(line 127). Lane-1 write-enable is `div_en_internal` (line 128), so
once the divide enters `MD_ABS_B` the divisor is captured and stays
stable for the remainder of the operation.

`op_numerator_q` and `op_quotient_q` are dedicated registers internal
to the multdiv unit (not part of the shared `imd_val` file), updated
under `div_en_internal` (line 108-115).

#### Scenario: DIVU 100 / 7 = 14 rem 2

- GIVEN `operator_i = MD_OP_DIV`, `signed_mode_i = 2'b00`, `op_a_i = 32'h0000_0064` (100), `op_b_i = 32'h0000_0007`, `div_en_i = 1`, `data_ind_timing_i = 0`, `equal_to_zero_i = 0`, `multdiv_ready_id_i = 1`
- WHEN 37 clock edges elapse from `MD_IDLE`
- THEN `valid_o = 1` and `multdiv_result_o = 32'h0000_000E` (= 14)
- (ref: ibex_multdiv_fast.sv:425-520)

#### Scenario: DIV -100 / 7 = -14

- GIVEN `operator_i = MD_OP_DIV`, `signed_mode_i = 2'b11`, `op_a_i = 32'hFFFF_FF9C` (-100), `op_b_i = 32'h0000_0007`, `div_en_i = 1`, `data_ind_timing_i = 0`, `multdiv_ready_id_i = 1`
- WHEN 37 clock edges elapse from `MD_IDLE`
- THEN `multdiv_result_o = 32'hFFFF_FFF2` (= -14, after `MD_CHANGE_SIGN` flips because `div_sign_a ^ div_sign_b = 1`)
- (ref: ibex_multdiv_fast.sv:406-409, 502-512)

#### Scenario: REM 7 % -3 = 1 (remainder takes sign of dividend)

- GIVEN `operator_i = MD_OP_REM`, `signed_mode_i = 2'b11`, `op_a_i = 32'h0000_0007`, `op_b_i = 32'hFFFF_FFFD` (-3), `div_en_i = 1`, `data_ind_timing_i = 0`, `multdiv_ready_id_i = 1`
- WHEN 37 clock edges elapse
- THEN `multdiv_result_o = 32'h0000_0001` (= 1; `div_sign_a = 0` so `rem_change_sign = 0`)
- (ref: ibex_multdiv_fast.sv:409, 506-507)

---

### Requirement: Divide-by-zero short-circuit (when `data_ind_timing_i = 0`)

When `operator_i ∈ {MD_OP_DIV, MD_OP_REM}`, `equal_to_zero_i = 1`,
and `data_ind_timing_i = 0` at the time the FSM is in `MD_IDLE`, the
FSM SHALL transition directly from `MD_IDLE → MD_FINISH`, skipping
`MD_ABS_A`, `MD_ABS_B`, `MD_COMP`, `MD_LAST`, `MD_CHANGE_SIGN`. The
result lane is seeded as:

- `MD_OP_DIV`: `op_remainder_d = '1` (= `34'h3_FFFF_FFFF`; bottom 32 b = `0xFFFF_FFFF` = -1).
- `MD_OP_REM`: `op_remainder_d = {2'b0, op_a_i}` (= the dividend).
- `MD_OP_DIV` with `signed_mode_i = 2'b00` (DIVU): same `'1` seed, lower 32 b = `0xFFFF_FFFF` = `2^32 - 1` (all-ones, the unsigned interpretation of the RISC-V required result).
- `MD_OP_REM` with `signed_mode_i = 2'b00` (REMU): same dividend seed.

`div_by_zero_d = equal_to_zero_i = 1` is captured (line 437) so that
when `data_ind_timing_i = 1` and the FSM does take the long path,
`MD_CHANGE_SIGN` will not flip the sign of the seeded `'1`
(see line 408: `div_change_sign = (div_sign_a ^ div_sign_b) &
~div_by_zero_q`). This prevents `'1` from becoming `0x0000_0001` in
the constant-time mode.

This corresponds to the "1 stall cycle" path in
`pipeline_details.rst` for divide-by-zero: 1 cycle in `MD_IDLE` + 1
cycle in `MD_FINISH` = the result is presented one cycle later than a
single-cycle ALU op. (One stall cycle = 2 total cycles.)

#### Scenario: DIVU x / 0 = 0xFFFF_FFFF (1 stall cycle)

- GIVEN `operator_i = MD_OP_DIV`, `signed_mode_i = 2'b00`, `op_a_i = 32'h1234_5678`, `op_b_i = 32'h0000_0000`, `div_en_i = 1`, `data_ind_timing_i = 0`, `equal_to_zero_i = 1`
- WHEN two clock edges elapse
- THEN `multdiv_result_o = 32'hFFFF_FFFF` and `valid_o = 1`
- (ref: ibex_multdiv_fast.sv:427-446)

#### Scenario: REMU x / 0 = x (1 stall cycle)

- GIVEN `operator_i = MD_OP_REM`, `signed_mode_i = 2'b00`, `op_a_i = 32'h1234_5678`, `op_b_i = 32'h0000_0000`, `div_en_i = 1`, `data_ind_timing_i = 0`, `equal_to_zero_i = 1`
- WHEN two clock edges elapse
- THEN `multdiv_result_o = 32'h1234_5678`
- (ref: ibex_multdiv_fast.sv:438-446)

#### Scenario: DIV x / 0 = -1 (signed)

- GIVEN `operator_i = MD_OP_DIV`, `signed_mode_i = 2'b11`, `op_a_i = 32'hFFFF_FF9C` (-100), `op_b_i = 32'h0000_0000`, `div_en_i = 1`, `data_ind_timing_i = 0`, `equal_to_zero_i = 1`
- WHEN two clock edges elapse
- THEN `multdiv_result_o = 32'hFFFF_FFFF` (= -1; sign correction is suppressed because `div_by_zero_q = 1`)
- (ref: ibex_multdiv_fast.sv:432-437, 408)

---

### Requirement: Constant-time mode forces full 37-cycle divide (`data_ind_timing_i = 1`)

When `data_ind_timing_i = 1`, the `MD_IDLE → MD_FINISH` short-circuit
SHALL NOT fire even if `equal_to_zero_i = 1`. The FSM proceeds through
`MD_ABS_A → MD_ABS_B → MD_COMP × 31 → MD_LAST → MD_CHANGE_SIGN →
MD_FINISH` for **all** operand pairs, including divide-by-zero. The
seeded `op_remainder_d` value (`'1` for DIV/DIVU, `{2'b0, op_a_i}` for
REM/REMU) propagates through the long-division iterations and emerges
unchanged because subtracting `0` (the absolute value of the zero
divisor) never changes the partial remainder. The `div_by_zero_q`
register is still captured in `MD_IDLE` (line 437) so
`MD_CHANGE_SIGN` will skip the sign flip and preserve the `-1` /
dividend convention.

#### Scenario: DIV by zero in constant-time mode still yields -1 after 37 cycles

- GIVEN `operator_i = MD_OP_DIV`, `signed_mode_i = 2'b11`, `op_a_i = 32'h0000_002A` (42), `op_b_i = 32'h0000_0000`, `div_en_i = 1`, `data_ind_timing_i = 1`, `equal_to_zero_i = 1`, `multdiv_ready_id_i = 1`
- WHEN 37 clock edges elapse
- THEN `multdiv_result_o = 32'hFFFF_FFFF` (-1)
- AND  the FSM visited every state including 31 cycles of `MD_COMP`
- (ref: ibex_multdiv_fast.sv:434, 445, 408)

#### Scenario: Constant-time DIV with non-zero divisor matches normal-mode result

- GIVEN any `operator_i ∈ {MD_OP_DIV, MD_OP_REM}`, any operands with `op_b_i != 0`, `data_ind_timing_i = 1`
- WHEN 37 clock edges elapse
- THEN `multdiv_result_o` equals the value produced by the same operands with `data_ind_timing_i = 0` (the FSM walks identically in either mode when `equal_to_zero_i = 0`)
- (ref: ibex_multdiv_fast.sv:434 — `data_ind_timing_i` is only consulted when `equal_to_zero_i = 1`)

---

### Requirement: Signed overflow on `INT_MIN / -1` returns `INT_MIN` (DIV) or `0` (REM)

The RISC-V spec mandates that `DIV(-2^31, -1) = -2^31` and
`REM(-2^31, -1) = 0` (no trap). The multdiv unit achieves this
naturally (no special case in the SV) because:

- The absolute-value passes turn `op_a_i = 0x8000_0000` into
  `op_numerator_q = 0 - 0x8000_0000 = 0x8000_0000` (32-bit two's
  complement is symmetric at `INT_MIN`); divisor `op_b_i = 0xFFFF_FFFF`
  becomes `op_denominator_q = 0x0000_0001`.
- Long division of `0x8000_0000 / 1 = 0x8000_0000`. Quotient =
  `0x8000_0000`, remainder = `0`.
- For DIV: `div_sign_a ^ div_sign_b = 1 ^ 1 = 0`, so
  `MD_CHANGE_SIGN` does not flip → result = `0x8000_0000` = `-2^31`.
  ✓
- For REM: `div_sign_a = 1` so `rem_change_sign = 1`, but the
  remainder is `0` and `0 - 0 = 0`, so the result is still `0`. ✓

#### Scenario: DIV(-2^31, -1) = -2^31

- GIVEN `operator_i = MD_OP_DIV`, `signed_mode_i = 2'b11`, `op_a_i = 32'h8000_0000`, `op_b_i = 32'hFFFF_FFFF`, `div_en_i = 1`, `multdiv_ready_id_i = 1`
- WHEN 37 clock edges elapse
- THEN `multdiv_result_o = 32'h8000_0000`
- (ref: ibex_multdiv_fast.sv:406-409, 502-512)

#### Scenario: REM(-2^31, -1) = 0

- GIVEN `operator_i = MD_OP_REM`, `signed_mode_i = 2'b11`, `op_a_i = 32'h8000_0000`, `op_b_i = 32'hFFFF_FFFF`, `div_en_i = 1`, `multdiv_ready_id_i = 1`
- WHEN 37 clock edges elapse
- THEN `multdiv_result_o = 32'h0000_0000`
- (ref: ibex_multdiv_fast.sv:486-500)

---

### Requirement: ALU operand exchange (cross-module same-cycle contract)

Every cycle the multdiv FSM is active, it SHALL drive
`alu_operand_a_o` and `alu_operand_b_o` to the values its current
state demands and SHALL consume `alu_adder_i` / `alu_adder_ext_i` /
`equal_to_zero_i` **the same cycle** (purely combinationally — no
flip-flop is in the path between the multdiv driving `alu_operand_*_o`
and reading `alu_adder_*_i`). The multdiv's FSM always-comb block
both writes `alu_operand_*_o` AND reads `alu_adder_*_i` /
`equal_to_zero_i` in the same `always_comb` (lines 412-526), so the
ALU MUST present the result combinationally with `multdiv_sel_i = 1`.

The companion ALU spec ("Adder uses multdiv operands when
`multdiv_sel_i = 1`") provides the producer-side guarantee:
`adder_result_ext_o = multdiv_operand_a_i + multdiv_operand_b_i`,
combinational. Cross-reference: `arch-ibex/specs/alu/spec.md` →
"Adder uses multdiv operands when `multdiv_sel_i = 1`" and "Equality
detector".

Per-state ALU operand drives:

| State            | `alu_operand_a_o`             | `alu_operand_b_o`                     | What the ALU computes       | What the multdiv reads back |
|------------------|-------------------------------|---------------------------------------|-----------------------------|------------------------------|
| `MD_IDLE`        | `{32'h0, 1'b1}`               | `{~op_b_i, 1'b1}`                     | `0 - op_b_i`                | `equal_to_zero_i` (zero divisor) |
| `MD_ABS_A`       | `{32'h0, 1'b1}`               | `{~op_a_i, 1'b1}`                     | `0 - op_a_i = -op_a_i`      | `alu_adder_i` → `op_numerator_d` |
| `MD_ABS_B`       | `{32'h0, 1'b1}`               | `{~op_b_i, 1'b1}`                     | `0 - op_b_i = -op_b_i`      | `alu_adder_i` → `op_denominator_d` |
| `MD_COMP`        | `{imd_val_q_i[0][31:0], 1'b1}`| `{~op_denominator_q[31:0], 1'b1}`    | partial_rem - divisor       | `alu_adder_ext_i[32:1]` = `res_adder_h` |
| `MD_LAST`        | `{imd_val_q_i[0][31:0], 1'b1}`| `{~op_denominator_q[31:0], 1'b1}`    | partial_rem - divisor (final)| `alu_adder_ext_i[32:1]`     |
| `MD_CHANGE_SIGN` | `{32'h0, 1'b1}`               | `{~imd_val_q_i[0][31:0], 1'b1}`       | `0 - result = -result`      | `alu_adder_i` → conditionally → `op_remainder_d` |
| `MD_FINISH`      | `{32'h0, 1'b1}`               | `{~op_b_i, 1'b1}` (default; unused)   | (ignored)                   | nothing                      |

Note the `1'b1` LSB on both operands in every drive: this is the
LSB-injection trick (the same one the ALU's standalone-mode adder
uses) to materialise `0 - X = ~X + 1` without dedicating a carry-in.
The two LSB-1 bits cancel: `(A << 1 | 1) + (~B << 1 | 1)` carries the
`+1+1` into bit 1, which is the actual subtraction's `+1`. This is
why `res_adder_h = alu_adder_ext_i[32:1]` (line 385): bit 0 of the
extended result is the unwanted LSB carry-out, bits `[32:1]` are the
real 32-bit difference, and bit `[33]` is the unused carry-out.

#### Scenario: `MD_COMP` cycle dataflow

- GIVEN the multdiv is in `MD_COMP` with `imd_val_q_i[0][31:0] = 32'h0000_001E` (partial remainder = 30), `op_denominator_q = 32'h0000_0007` (divisor = 7), `div_counter_q = 5'd5`
- WHEN the cycle elapses with the ALU computing the sum
- THEN `alu_operand_a_o = 33'h0000_003D` (`= 32'h0000_001E << 1 | 1`)
- AND  `alu_operand_b_o = 33'h1FFFF_FFF1` (`= ~32'h0000_0007 << 1 | 1`)
- AND  the ALU sums to `alu_adder_ext_i = 34'h0_0000_002E` (carry-out 0, `0x3D + 0x1FFF_FFF1 = 0x2_0000_002E` truncated to 34 b → `0x0_0000_002E`; in subtraction terms `30 - 7 = 23 = 0x17`, doubled by the LSB trick: bits `[32:1] = 0x17`, bits `[0]` and `[33]` are the noise)
- AND  `res_adder_h = 32'h0000_0017` (= 23)
- AND  `is_greater_equal = 1` (because both MSBs are 0 and `res_adder_h[31] = 0`)
- AND  the next-cycle `imd_val_q_i[0][31:0]` becomes `{1'b0, 23, op_numerator_q[4]}` shifted in
- (ref: ibex_multdiv_fast.sv:385-404, 477-484)

---

### Requirement: Intermediate-value lane assignment

`imd_val_d_o[0]` SHALL carry:

- `op_remainder_d` when `div_sel_i = 1`
- `mac_res_d` when `div_sel_i = 0`

with write-enable `imd_val_we_o[0] = multdiv_en = mult_en_internal |
div_en_internal` (line 121, 125).

`imd_val_d_o[1]` SHALL carry `{2'b0, op_denominator_d}` with
write-enable `imd_val_we_o[1] = div_en_internal` (line 127-128). The
top two bits of lane 1 are always written `2'b00`.

`op_denominator_q` is sourced from `imd_val_q_i[1][31:0]` (line 129).
The top two bits `imd_val_q_i[1][33:32]` are unused (line 130-131) and
the consumer (the EX block) MUST be tolerant of them being garbage on
read — though in practice they will always be `2'b00` because the
multdiv is the only writer when `div_en_internal` is high.

#### Scenario: Lane 1 captured at `MD_ABS_B`, held thereafter

- GIVEN the divider is entering `MD_ABS_B` with `op_b_i = 32'h0000_0007`, `div_sign_b = 0`
- WHEN the cycle elapses
- THEN `imd_val_d_o[1] = 34'h0_0000_0007` (= `{2'b0, op_b_i}` because `div_sign_b = 0` selects `op_b_i` not `alu_adder_i`)
- AND  `imd_val_we_o[1] = 1`
- AND on subsequent cycles in `MD_COMP`/`MD_LAST`/`MD_CHANGE_SIGN`/`MD_FINISH`, `op_denominator_d = op_denominator_q` (default at line 418), so the value is held stable
- (ref: ibex_multdiv_fast.sv:412-418, 465-475)

---

### Requirement: Reset behaviour

On `rst_ni = 0` (asynchronous), the unit SHALL reset:

- `div_counter_q ← 5'b0`
- `md_state_q ← MD_IDLE`
- `op_numerator_q ← 32'h0`
- `op_quotient_q ← 32'h0`
- `div_by_zero_q ← 1'b0`
- `mult_state_q ← ALBL`

Note: the divider state register `md_state_q` and the multiplier state
register `mult_state_q` are independent and live in separate
`always_ff` blocks. Other internal/external state (`imd_val_q_i`,
which is owned by the EX block) is **not** reset by this module.

#### Scenario: Cold reset puts FSM in idle

- GIVEN `rst_ni = 0` for one or more clock edges
- WHEN reset is released
- THEN `md_state_q = MD_IDLE`, `mult_state_q = ALBL`, `div_counter_q = 0`, `op_numerator_q = 0`, `op_quotient_q = 0`, `div_by_zero_q = 0`
- (ref: ibex_multdiv_fast.sv:101-115, 367-375)

---

### Requirement: `valid_o` is the OR of mult_valid and div_valid

`valid_o = mult_valid | div_valid` (line 529). The multdiv MUST NOT
assert both simultaneously: at any given moment at most one of
`mult_en_i` / `div_en_i` is high (this is a producer-side guarantee
documented in Integration constraints; the SV asserts no internal
mutex but relies on the surrounding decoder). When the multdiv is
quiescent (no operation in flight) `valid_o = 0`.

#### Scenario: Quiescent state has `valid_o = 0`

- GIVEN `mult_en_i = 0` AND `div_en_i = 0` for an extended interval
- WHEN any clock edge fires
- THEN `valid_o = 0` and the FSM stays in `MD_IDLE` / `ALBL`
- (ref: ibex_multdiv_fast.sv:282-365 with `mult_state_q = ALBL` default → `mult_valid = 0`; lines 412-526 with `md_state_q = MD_IDLE` → `div_valid = 0`)

## Integration constraints

### Consumer-side (what the EX block / ID stage does with multdiv outputs)

1. **`multdiv_result_o` is muxed at the EX block, not gated**. The EX
   block routes `multdiv_result` into `result_ex_o` only when
   `multdiv_sel = mult_sel_i | div_sel_i = 1` (ref:
   `ibex_ex_block.sv:89`). Outside that window the value on
   `multdiv_result_o` is ignored. The multdiv unit therefore does NOT
   need to drive a particular value when idle — the consumer's mux
   handles it.
2. **`valid_o` is forwarded as `ex_valid_o` only when `multdiv_sel = 1`**:
   `ex_valid_o = multdiv_sel ? multdiv_valid : ~(|alu_imd_val_we)`
   (ref: `ibex_ex_block.sv:197`). The multdiv must therefore raise
   `valid_o` exactly once per operation; the consumer does not gate
   it further. Holding `valid_o` high across multiple cycles via
   `mult_hold` / `div_hold` is allowed and indicates back-pressure.
3. **`imd_val_d_o[0]` and `imd_val_d_o[1]` are OR-muxed with the
   ALU's `imd_val_d_o[*]` upstream**: the EX block selects between
   them via `multdiv_sel`. Lane 0 from the multdiv is the full 34 b;
   lane 0 from the ALU is `{2'b0, alu_imd_val_d[0]}` — i.e. the EX
   block zero-extends the ALU's 32-bit lane to 34 b before the mux
   (ref: `ibex_ex_block.sv:83-84`). The multdiv unit's lane 0 may
   carry meaningful content in bits `[33:32]` (it does, for MULH
   accumulation), and the EX block forwards it transparently.
4. **`imd_val_we_o` is OR-muxed similarly**: `imd_val_we_o = multdiv_sel
   ? multdiv_imd_val_we : alu_imd_val_we` (ref:
   `ibex_ex_block.sv:85`). Per-lane write-enable is honoured exactly.
5. **`alu_operand_a_o` / `alu_operand_b_o` are routed directly into
   the ALU's `multdiv_operand_a_i` / `multdiv_operand_b_i` ports**
   (ref: `ibex_ex_block.sv:179-180, 126-127`). The ALU then drives
   its shared adder with these operands when its `multdiv_sel_i = 1`,
   producing the same-cycle `adder_result_ext_o` and `is_equal_result_o`
   the multdiv samples back. **There is no flip-flop in this loop**;
   the EX block instantiates ALU and multdiv as siblings and the
   combinational path is closed through the EX block's wiring.

### Producer-side (what the EX block / ID stage guarantees on multdiv inputs)

1. **`mult_en_i` is held stable at 1 for the entire MUL/MULH operation**,
   from the cycle the operation enters EX through the cycle the multdiv
   raises `valid_o = 1` and is acknowledged via `multdiv_ready_id_i`.
   The multdiv's state register only advances on
   `mult_en_internal = mult_en_i & ~mult_hold`; if `mult_en_i` were to
   glitch low mid-operation, the FSM would freeze (which would
   deadlock the operation, not corrupt it).
2. **`div_en_i` is held stable at 1 for the entire DIV/REM operation**,
   symmetric to (1).
3. **`mult_en_i` and `div_en_i` are mutually exclusive**. The
   surrounding ID-stage decoder ensures only one is high per
   operation. Both being high simultaneously is undefined behaviour
   from the multdiv's perspective: `multdiv_en = mult_en_internal |
   div_en_internal` would write both intermediate-value lanes
   simultaneously and the FSMs would both advance.
4. **`operator_i`, `signed_mode_i`, `op_a_i`, `op_b_i` are held stable
   for the duration of the operation**. The multdiv resamples them
   every cycle (e.g. line 311's `signed_mode_i[1]` in `ALBH`,
   line 327's `signed_mode_i[0]` in `AHBL`, lines 406-407 for sign
   capture, line 487's `operator_i` in `MD_LAST`). If any input
   changes mid-operation the result is not guaranteed.
5. **`mult_sel_i` and `div_sel_i` track `mult_en_i` and `div_en_i`**.
   The static decoder outputs feed the EX-block multiplexers; while
   the multdiv unit ignores `mult_sel_i` (line 96, declared unused),
   `div_sel_i` is consumed as a data-mux selector and must be high
   during a divide.
6. **`multdiv_ready_id_i` may be 0 at any time** (back-pressure). The
   multdiv handles back-pressure correctly only in the terminal
   states (`AHBL` for MUL, `AHBH` for MULH, `MD_FINISH` for div). In
   non-terminal states the value of `multdiv_ready_id_i` is ignored.
7. **`alu_adder_i`, `alu_adder_ext_i`, `equal_to_zero_i` MUST be
   combinational functions of `alu_operand_a_o`, `alu_operand_b_o`,
   and `op_b_i` (for the IDLE-state zero check)** — i.e. the ALU side
   does not flop the multdiv operands. The ALU spec guarantees this
   under `multdiv_sel_i = 1`.
8. **`data_ind_timing_i` is sampled in `MD_IDLE` only** (line 434). It
   may change between operations, but during a divide it is consulted
   exactly once. The ID stage sources it from a CSR.
9. **`imd_val_q_i[0]` and `imd_val_q_i[1]` reflect the value the
   multdiv wrote on the previous cycle** (the EX block's intermediate-
   value flop bank is updated each cycle from `imd_val_d_o` / `we`).
   The unit relies on this single-cycle latency.

## Notes

- The `mult_sel_i` input is structurally unused inside the multdiv
  (assigned to `unused_mult_sel_i` at line 96). It exists in the port
  list for symmetry with the slow variant and the EX-block plumbing.
- The two MSBs of `mac_res_ext` are formally redundant by the
  proof sketch in lines 273-276; the implementation MAY drop or keep
  bit `[34]` of the kernel result — the result observable at
  `multdiv_result_o` is unchanged.
- `op_numerator_q` and `op_quotient_q` are NOT part of the
  intermediate-value register file; they are dedicated 32-bit
  registers internal to the multdiv module and are only updated under
  `div_en_internal`. An ARCH port of this module SHOULD model them as
  internal `reg`s, not external state.
- The 5-bit `div_counter_q` reset value of `5'd31` (= 31) at every
  state transition (`MD_IDLE`, `MD_ABS_A`, `MD_ABS_B`) is redundant
  — only the `MD_IDLE` reset is load-bearing. Implementations MAY
  collapse the redundant resets.
- The 31-iteration `MD_COMP` loop count differs from the more obvious
  "32-bit operand → 32 iterations" intuition: the unit performs the
  first iteration's bit-injection in `MD_ABS_B` (seeding
  `op_remainder_d` with the numerator's MSB) and the last iteration
  in `MD_LAST`, accounting for two of the 32 bits and leaving 30
  in `MD_COMP`. (Wait — actually `MD_COMP` runs for 31 iterations as
  counted from `div_counter_q` going 31, 30, ..., 1; `MD_LAST` is the
  32nd iteration; `MD_ABS_B` injects the seed bit but does not perform
  a subtract. Total subtracts = 32, matching the 32 quotient bits.)
- The `equal_to_zero_i` input is **only meaningful in `MD_IDLE`** —
  in every other state the ALU's adder output is what the multdiv
  needs, not the equality flag. Implementations need not register
  `equal_to_zero_i` outside `MD_IDLE`.
- `unused_alu_adder_ext` (lines 386-387) drops bit `[33]` and bit `[0]`
  of the 34-bit ALU adder result. Bit `[0]` is the cancellation bit
  from the LSB-1 trick (always `0` after the two `1`s carry); bit
  `[33]` is an extra carry-out beyond the meaningful 32-bit difference.
  Both are safely discarded.
- The `mult_sel_i` permissive read (the multdiv ignores it) means an
  ARCH implementation does not need to model it as an active input;
  it can be a top-level no-op.
- The data-independent timing mode is documented as a security
  feature (CORE.DATA_REG_SW.SCA, line 433). The behavioural contract
  is just "always 37 cycles regardless of operands"; the security
  property (constant power profile, no operand-dependent
  microarchitectural side-effects) is out of scope of this functional
  spec.
