# ALU Specification

## Purpose

The Ibex ALU is a purely combinational arithmetic / logic / shift /
comparison unit invoked from the EX stage of the Ibex pipeline. It
computes the result of a single RISC-V integer instruction (the
`result_o` output) and additionally exposes three side-band outputs
that are reused by other pipeline blocks:

- `adder_result_o` (32 b) and `adder_result_ext_o` (34 b) feed the LSU
  address generator and the multdiv unit, which share the ALU's adder
  rather than instantiating their own.
- `comparison_result_o` and `is_equal_result_o` feed the branch unit so
  that conditional branches can sample the comparator without going
  through the result mux.

This specification fixes the **`RV32B = RV32BNone`** configuration:
the bitmanip (RV32B) operators are part of the port contract for
completeness — the pipeline still presents them — but in this
configuration the result mux drives `result_o = 0` for any RV32B
operator. The adder, comparator, equality, and shifter outputs continue
to be valid (and are sampled unconditionally by downstream consumers
that share these structures), regardless of operator.

The module is purely combinational: there are no clocks, no resets, and
no internal state. Every output is a function of the current inputs.

## Port contract

| Direction | Name | Type | Description |
|---|---|---|---|
| param | `RV32B` | `rv32b_e` (enum, integer-encoded) | Bitmanip configuration. This spec covers only `RV32BNone` (= 0). |
| in  | `operator_i`           | `UInt<7>` (encodes `alu_op_e`) | Operation selector. See "ALU operator encoding" below. |
| in  | `operand_a_i`          | `UInt<32>` | Primary operand (rs1 in most cases). |
| in  | `operand_b_i`          | `UInt<32>` | Secondary operand (rs2 or immediate). |
| in  | `instr_first_cycle_i`  | `Bool`     | Held high on the first (and, for single-cycle ops, only) cycle of an instruction. Under `RV32BNone` it gates the shift-amount mux: see Requirement "Standard shifts". |
| in  | `multdiv_operand_a_i`  | `UInt<33>` | Multdiv-supplied A operand for the shared adder. |
| in  | `multdiv_operand_b_i`  | `UInt<33>` | Multdiv-supplied B operand for the shared adder. |
| in  | `multdiv_sel_i`        | `Bool`     | When asserted, the shared adder uses the multdiv operands instead of `operand_a_i`/`operand_b_i`. |
| in  | `imd_val_q_i[2]`       | array of 2 × `UInt<32>` | Intermediate-value register file (driven by EX-stage). Unused under `RV32BNone`. |
| out | `imd_val_d_o[2]`       | array of 2 × `UInt<32>` | Intermediate-value write-data. Tied to `0` under `RV32BNone`. |
| out | `imd_val_we_o`         | `UInt<2>`  | Intermediate-value write-enable. Tied to `2'b00` under `RV32BNone`. |
| out | `adder_result_o`       | `UInt<32>` | 32-bit sum of the shared adder. |
| out | `adder_result_ext_o`   | `UInt<34>` | 34-bit carry-extended sum (used by multdiv for the carry-out bit). |
| out | `result_o`             | `UInt<32>` | Operation result routed to the regfile / branch target adder / etc. |
| out | `comparison_result_o`  | `Bool`     | Branch / set-less-than comparator output. |
| out | `is_equal_result_o`    | `Bool`     | True iff the adder produced `32'h0000_0000`. |

### ALU operator encoding

`alu_op_e` is a 7-bit enum declared in `ibex_pkg.sv` whose members are
assigned sequentially starting at `0`. Spec uses the integer values
below (these are the bit patterns the implementation must decode on
`operator_i`):

| Op | Value | Op | Value | Op | Value |
|---|---|---|---|---|---|
| `ALU_ADD`        | 0  | `ALU_XPERM_H`     | 21 | `ALU_SLT`         | 43 |
| `ALU_SUB`        | 1  | `ALU_SH1ADD`      | 22 | `ALU_SLTU`        | 44 |
| `ALU_XOR`        | 2  | `ALU_SH2ADD`      | 23 | `ALU_CMOV`        | 45 |
| `ALU_OR`         | 3  | `ALU_SH3ADD`      | 24 | `ALU_CMIX`        | 46 |
| `ALU_AND`        | 4  | `ALU_LT`          | 25 | `ALU_FSL`         | 47 |
| `ALU_XNOR`       | 5  | `ALU_LTU`         | 26 | `ALU_FSR`         | 48 |
| `ALU_ORN`        | 6  | `ALU_GE`          | 27 | `ALU_BSET`        | 49 |
| `ALU_ANDN`       | 7  | `ALU_GEU`         | 28 | `ALU_BCLR`        | 50 |
| `ALU_SRA`        | 8  | `ALU_EQ`          | 29 | `ALU_BINV`        | 51 |
| `ALU_SRL`        | 9  | `ALU_NE`          | 30 | `ALU_BEXT`        | 52 |
| `ALU_SLL`        | 10 | `ALU_MIN`         | 31 | `ALU_BCOMPRESS`   | 53 |
| `ALU_SRO`        | 11 | `ALU_MINU`        | 32 | `ALU_BDECOMPRESS` | 54 |
| `ALU_SLO`        | 12 | `ALU_MAX`         | 33 | `ALU_BFP`         | 55 |
| `ALU_ROR`        | 13 | `ALU_MAXU`        | 34 | `ALU_CLMUL`       | 56 |
| `ALU_ROL`        | 14 | `ALU_PACK`        | 35 | `ALU_CLMULR`      | 57 |
| `ALU_GREV`       | 15 | `ALU_PACKU`       | 36 | `ALU_CLMULH`      | 58 |
| `ALU_GORC`       | 16 | `ALU_PACKH`       | 37 | `ALU_CRC32_B`     | 59 |
| `ALU_SHFL`       | 17 | `ALU_SEXTB`       | 38 | `ALU_CRC32C_B`    | 60 |
| `ALU_UNSHFL`     | 18 | `ALU_SEXTH`       | 39 | `ALU_CRC32_H`     | 61 |
| `ALU_XPERM_N`    | 19 | `ALU_CLZ`         | 40 | `ALU_CRC32C_H`    | 62 |
| `ALU_XPERM_B`    | 20 | `ALU_CTZ`         | 41 | `ALU_CRC32_W`     | 63 |
|                  |    | `ALU_CPOP`        | 42 | `ALU_CRC32C_W`    | 64 |

Operators in the **base set** (RV32I) under `RV32BNone`:

`ALU_ADD`, `ALU_SUB`, `ALU_XOR`, `ALU_OR`, `ALU_AND`, `ALU_SRA`,
`ALU_SRL`, `ALU_SLL`, `ALU_LT`, `ALU_LTU`, `ALU_GE`, `ALU_GEU`,
`ALU_EQ`, `ALU_NE`, `ALU_SLT`, `ALU_SLTU`.

Every other operator value above is an **RV32B operator** and falls
under the inert behavior in the requirement "RV32B-inert behavior".

## Requirements

### Requirement: Combinational behavior

The module SHALL compute every output as a pure combinational function
of its current inputs. No internal flip-flops, latches, clock, or reset
are present.

#### Scenario: Output stability with stable inputs
- GIVEN any combination of inputs held stable
- WHEN no input changes
- THEN every output is a deterministic function of those inputs and does not change
- (ref: ibex_alu.sv:1-1400 — entire module body uses `assign` and `always_comb`; no `always_ff`)

---

### Requirement: Adder produces unconditional sum of operands A and B

When `multdiv_sel_i = 0`, the shared adder SHALL produce
`adder_result_o = operand_a_i + operand_b_i` modulo 2³² for every
operator that does **not** select two's-complement subtraction (see
next requirement). The result MUST be available regardless of which
operator is selected — i.e., even on operators whose `result_o` does
not consume the adder, the adder output remains valid.

The 34-bit `adder_result_ext_o` SHALL equal the unsigned sum
`{operand_a_i, 1'b1} + {operand_b_i, 1'b0}` (the LSB-injection trick the
SV uses to share the adder for subtraction); `adder_result_o` is bits
`[32:1]` of `adder_result_ext_o`.

#### Scenario: ADD of two positives
- GIVEN `operator_i = ALU_ADD`, `operand_a_i = 32'h0000_0003`, `operand_b_i = 32'h0000_0005`, `multdiv_sel_i = 0`
- WHEN inputs settle
- THEN `adder_result_o = 32'h0000_0008`
- AND  `is_equal_result_o = 0`
- (ref: ibex_alu.sv:84-109)

#### Scenario: ADD that wraps modulo 2^32
- GIVEN `operator_i = ALU_ADD`, `operand_a_i = 32'hFFFF_FFFF`, `operand_b_i = 32'h0000_0001`
- WHEN inputs settle
- THEN `adder_result_o = 32'h0000_0000`
- AND  `is_equal_result_o = 1`
- AND  `adder_result_ext_o[33]` reflects the carry-out
- (ref: ibex_alu.sv:105-107)

#### Scenario: Adder valid even when operator does not consume it
- GIVEN `operator_i = ALU_AND`, `operand_a_i = 32'h0000_0010`, `operand_b_i = 32'h0000_0020`
- WHEN inputs settle
- THEN `adder_result_o = 32'h0000_0030` (regardless of `result_o`)
- (ref: ibex_alu.sv:84-109 — adder is always evaluated)

---

### Requirement: Subtraction and comparison operators drive the adder via two's-complement negation

For `operator_i ∈ { ALU_SUB, ALU_EQ, ALU_NE, ALU_GE, ALU_GEU, ALU_LT,
ALU_LTU, ALU_SLT, ALU_SLTU }` (under `RV32BNone`), the shared adder
SHALL compute `operand_a_i + ~operand_b_i + 1`, which equals
`operand_a_i - operand_b_i` modulo 2³². The mechanism is the LSB-1
injection on the A side combined with bitwise inversion of the
LSB-0-padded B side; the implementation MAY realise this by any
equivalent two's-complement construct.

#### Scenario: SUB of equal values
- GIVEN `operator_i = ALU_SUB`, `operand_a_i = 32'h1234_5678`, `operand_b_i = 32'h1234_5678`
- WHEN inputs settle
- THEN `adder_result_o = 32'h0000_0000`
- AND  `is_equal_result_o = 1`
- (ref: ibex_alu.sv:62-72, 95-99)

#### Scenario: SUB producing a negative (two's complement) result
- GIVEN `operator_i = ALU_SUB`, `operand_a_i = 32'h0000_0003`, `operand_b_i = 32'h0000_0005`
- WHEN inputs settle
- THEN `adder_result_o = 32'hFFFF_FFFE`
- AND  `is_equal_result_o = 0`
- (ref: ibex_alu.sv:62-72, 95-99)

#### Scenario: Comparison operators also drive the subtract path
- GIVEN `operator_i = ALU_LT`, `operand_a_i = 32'h0000_0001`, `operand_b_i = 32'h0000_0002`
- WHEN inputs settle
- THEN `adder_result_o = 32'hFFFF_FFFF` (i.e. `1 - 2 = -1`)
- AND  the comparator consumes that sign bit (see "Signed and unsigned comparator")
- (ref: ibex_alu.sv:64-68)

---

### Requirement: Multdiv mux on the shared adder

When `multdiv_sel_i = 1`, the adder SHALL ignore `operand_a_i`,
`operand_b_i`, and the operator-driven negate selector and SHALL
instead compute the unsigned sum
`multdiv_operand_a_i + multdiv_operand_b_i` (33-bit operands → 34-bit
extended result). `adder_result_ext_o` then carries the full 34-bit
sum and `adder_result_o = adder_result_ext_o[32:1]`.

#### Scenario: Multdiv 33-bit add with carry into bit 33
- GIVEN `multdiv_sel_i = 1`, `multdiv_operand_a_i = 33'h1_FFFF_FFFF`, `multdiv_operand_b_i = 33'h0_0000_0001`, any `operator_i`, any `operand_a_i`/`operand_b_i`
- WHEN inputs settle
- THEN `adder_result_ext_o = 34'h2_0000_0000`
- AND  `adder_result_o = adder_result_ext_o[32:1] = 32'h0000_0000`
- (ref: ibex_alu.sv:85-105)

#### Scenario: Multdiv path overrides operand inputs
- GIVEN `multdiv_sel_i = 1`, `multdiv_operand_a_i = 33'h0_0000_000A`, `multdiv_operand_b_i = 33'h0_0000_0014`, `operand_a_i = 32'hDEAD_BEEF`, `operand_b_i = 32'hCAFE_BABE`, `operator_i = ALU_ADD`
- WHEN inputs settle
- THEN `adder_result_ext_o[32:0] = 33'h0000_001E` (`0xA + 0x14 = 0x1E`)
- AND  `adder_result_o = adder_result_ext_o[32:1] = 32'h0000_000F`
- NOTE The downstream multdiv unit drives `multdiv_operand_*_i` already left-shifted by 1 when it wants the LSB-1 trick; this spec only fixes that the mux replaces both adder inputs.
- (ref: ibex_alu.sv:86, 98)

---

### Requirement: Equality flag

`is_equal_result_o` SHALL be `1` iff `adder_result_o == 32'h0000_0000`,
and `0` otherwise. It is computed unconditionally — it does not depend
on `operator_i`. When the caller wants RISC-V `BEQ`/`BNE` semantics it
must select an operator that drives the subtract path (e.g. `ALU_EQ` or
`ALU_NE`) so that the adder computes `a - b` rather than `a + b`.

#### Scenario: EQ with equal operands
- GIVEN `operator_i = ALU_EQ`, `operand_a_i = 32'hAAAA_5555`, `operand_b_i = 32'hAAAA_5555`
- WHEN inputs settle
- THEN `is_equal_result_o = 1`
- AND  `comparison_result_o = 1`
- AND  `result_o = 32'h0000_0001`
- (ref: ibex_alu.sv:132-133, 161, 1346-1350)

#### Scenario: NE with equal operands
- GIVEN `operator_i = ALU_NE`, `operand_a_i = 32'h0000_0042`, `operand_b_i = 32'h0000_0042`
- WHEN inputs settle
- THEN `is_equal_result_o = 1`
- AND  `comparison_result_o = 0`
- AND  `result_o = 32'h0000_0000`
- (ref: ibex_alu.sv:162)

#### Scenario: ADD that happens to yield zero
- GIVEN `operator_i = ALU_ADD`, `operand_a_i = 32'hFFFF_FFFF`, `operand_b_i = 32'h0000_0001`
- WHEN inputs settle
- THEN `is_equal_result_o = 1` (because `adder_result_o == 0`)
- (ref: ibex_alu.sv:132 — unconditional)

---

### Requirement: Signed and unsigned comparator

The comparator SHALL implement signed semantics for
`operator_i ∈ { ALU_GE, ALU_LT, ALU_SLT }` and unsigned semantics for
`operator_i ∈ { ALU_GEU, ALU_LTU, ALU_SLTU }`. Equality operators
(`ALU_EQ`, `ALU_NE`) bypass the magnitude comparator and consume only
`is_equal_result_o`.

A "greater-or-equal" predicate `is_greater_equal` SHALL be computed as:

- If `operand_a_i[31] == operand_b_i[31]`: `is_greater_equal = ~adder_result_o[31]`
  (i.e. the sign bit of `a - b`; cleared when a ≥ b).
- Else if signed: `is_greater_equal = ~operand_a_i[31]`
  (positive a is greater than negative b).
- Else (unsigned, sign bits differ): `is_greater_equal = operand_a_i[31]`
  (a's MSB set means a is the larger unsigned value).

Then:

- `ALU_GE` / `ALU_GEU` → `comparison_result_o = is_greater_equal`
- `ALU_LT` / `ALU_LTU` / `ALU_SLT` / `ALU_SLTU` → `comparison_result_o = ~is_greater_equal`
- `ALU_EQ` → `comparison_result_o = is_equal_result_o`
- `ALU_NE` → `comparison_result_o = ~is_equal_result_o`
- Any other operator under `RV32BNone` → `comparison_result_o = is_equal_result_o`
  (the SV `default` case; downstream consumers do not sample it for
  non-comparison operators).

For `ALU_SLT` and `ALU_SLTU`, `result_o` SHALL equal
`{31'b0, comparison_result_o}` (zero-extended boolean).

#### Scenario: Unsigned LTU when MSBs differ
- GIVEN `operator_i = ALU_LTU`, `operand_a_i = 32'h8000_0000`, `operand_b_i = 32'h0000_0001`
- WHEN inputs settle
- THEN `comparison_result_o = 0` (a is the larger unsigned value, so a < b is false)
- AND  `result_o = 32'h0000_0000` (LTU's result-mux fan-in *is* `{31'h0, cmp_result}`, so `result_o = 0` here matches)
- (ref: ibex_alu.sv:140, 165-167, 1346-1350)

#### Scenario: Signed LT when MSBs differ
- GIVEN `operator_i = ALU_LT`, `operand_a_i = 32'h8000_0000`, `operand_b_i = 32'h0000_0001`
- WHEN inputs settle
- THEN `comparison_result_o = 1` (a is negative, b is positive → a < b)
- AND  `result_o = 32'h0000_0001`
- (ref: ibex_alu.sv:140 — `cmp_signed = 1`)

#### Scenario: SLTU sets result to {31'b0, comparison_result_o}
- GIVEN `operator_i = ALU_SLTU`, `operand_a_i = 32'h0000_0001`, `operand_b_i = 32'h0000_0002`
- WHEN inputs settle
- THEN `comparison_result_o = 1`
- AND  `result_o = 32'h0000_0001`
- (ref: ibex_alu.sv:1346-1350)

#### Scenario: SLT with negative a, positive b
- GIVEN `operator_i = ALU_SLT`, `operand_a_i = 32'hFFFF_FFFF`, `operand_b_i = 32'h0000_0001`
- WHEN inputs settle
- THEN `comparison_result_o = 1` (a = -1 < b = 1)
- AND  `result_o = 32'h0000_0001`
- (ref: ibex_alu.sv:140, 167)

#### Scenario: GEU when MSBs differ and a is the larger unsigned value
- GIVEN `operator_i = ALU_GEU`, `operand_a_i = 32'hFFFF_FFFE`, `operand_b_i = 32'h0000_0010`
- WHEN inputs settle
- THEN `comparison_result_o = 1` (different MSBs, unsigned: returns `operand_a_i[31] = 1`)
- (ref: ibex_alu.sv:140-142)

#### Scenario: GE when MSBs equal
- GIVEN `operator_i = ALU_GE`, `operand_a_i = 32'h0000_0010`, `operand_b_i = 32'h0000_0010`
- WHEN inputs settle
- THEN `adder_result_o = 0`, so `is_greater_equal = ~adder_result_o[31] = 1`
- AND  `comparison_result_o = 1`
- (ref: ibex_alu.sv:138)

---

### Requirement: Bitwise logic operators

For `operator_i ∈ { ALU_XOR, ALU_OR, ALU_AND }` under `RV32BNone`,
`result_o` SHALL equal the bitwise XOR / OR / AND of `operand_a_i` and
`operand_b_i` respectively. (RV32B variants `ALU_XNOR`, `ALU_ORN`,
`ALU_ANDN` and `ALU_CMIX` engage operand-B inversion only when
`RV32B != RV32BNone`; under `RV32BNone` they are inert — see
"RV32B-inert behavior".)

#### Scenario: AND mask
- GIVEN `operator_i = ALU_AND`, `operand_a_i = 32'hFFFF_FFFF`, `operand_b_i = 32'h0F0F_0F0F`
- WHEN inputs settle
- THEN `result_o = 32'h0F0F_0F0F`
- (ref: ibex_alu.sv:385, 389, 393, 1326)

#### Scenario: OR
- GIVEN `operator_i = ALU_OR`, `operand_a_i = 32'h0000_FF00`, `operand_b_i = 32'h00FF_0000`
- WHEN inputs settle
- THEN `result_o = 32'h00FF_FF00`
- (ref: ibex_alu.sv:384, 388, 393)

#### Scenario: XOR
- GIVEN `operator_i = ALU_XOR`, `operand_a_i = 32'hFFFF_FFFF`, `operand_b_i = 32'hAAAA_5555`
- WHEN inputs settle
- THEN `result_o = 32'h5555_AAAA`
- (ref: ibex_alu.sv:386, 395)

#### Scenario: AND with all-zero mask
- GIVEN `operator_i = ALU_AND`, `operand_a_i = 32'hDEAD_BEEF`, `operand_b_i = 32'h0000_0000`
- WHEN inputs settle
- THEN `result_o = 32'h0000_0000`
- (ref: ibex_alu.sv:385, 389, 393)

---

### Requirement: Standard shifts (SLL, SRL, SRA)

For `operator_i ∈ { ALU_SLL, ALU_SRL, ALU_SRA }` and
`instr_first_cycle_i = 1` (the only mode in which Ibex issues
single-cycle ALU shifts under `RV32BNone`), the shifter SHALL produce:

- `ALU_SLL`: `result_o = operand_a_i << shamt`, zero-filled from the
  right.
- `ALU_SRL`: `result_o = operand_a_i >> shamt`, zero-filled from the
  left (logical right shift).
- `ALU_SRA`: `result_o` is the arithmetic right shift of
  `operand_a_i` by `shamt`, sign-filled from `operand_a_i[31]`.

where `shamt = operand_b_i[4:0]` (bits `[31:5]` of `operand_b_i` are
ignored for the shift amount). Implementations MAY use the SV-style
trick of bit-reversing the operand for left shifts and re-reversing
the result; only the observable behavior above is required.

#### Scenario: SLL by 4
- GIVEN `operator_i = ALU_SLL`, `operand_a_i = 32'h1234_5678`, `operand_b_i = 32'h0000_0004`, `instr_first_cycle_i = 1`
- WHEN inputs settle
- THEN `result_o = 32'h2345_6780`
- (ref: ibex_alu.sv:306, 333, 343, 350-353, 1335-1338)

#### Scenario: SRL by 8
- GIVEN `operator_i = ALU_SRL`, `operand_a_i = 32'h1234_5678`, `operand_b_i = 32'h0000_0008`, `instr_first_cycle_i = 1`
- WHEN inputs settle
- THEN `result_o = 32'h0012_3456`
- (ref: ibex_alu.sv:333, 342-346)

#### Scenario: SRA of negative value
- GIVEN `operator_i = ALU_SRA`, `operand_a_i = 32'h8000_0000`, `operand_b_i = 32'h0000_0004`, `instr_first_cycle_i = 1`
- WHEN inputs settle
- THEN `result_o = 32'hF800_0000`
- (ref: ibex_alu.sv:322, 343)

#### Scenario: Shift amount upper bits ignored
- GIVEN `operator_i = ALU_SLL`, `operand_a_i = 32'h0000_0001`, `operand_b_i = 32'hFFFF_FFE1`, `instr_first_cycle_i = 1`
- WHEN inputs settle
- THEN `shamt = operand_b_i[4:0] = 5'h01`
- AND  `result_o = 32'h0000_0002` (upper `operand_b_i` bits had no effect)
- (ref: ibex_alu.sv:286-288 — only `[4:0]` consumed)

#### Scenario: Shift by zero is identity
- GIVEN `operator_i = ALU_SRL`, `operand_a_i = 32'hDEAD_BEEF`, `operand_b_i = 32'h0000_0000`, `instr_first_cycle_i = 1`
- WHEN inputs settle
- THEN `result_o = 32'hDEAD_BEEF`
- (ref: ibex_alu.sv:343 — shift by 0)

#### Scenario: SRA by 31 of negative input
- GIVEN `operator_i = ALU_SRA`, `operand_a_i = 32'h8000_0000`, `operand_b_i = 32'h0000_001F`, `instr_first_cycle_i = 1`
- WHEN inputs settle
- THEN `result_o = 32'hFFFF_FFFF`
- (ref: ibex_alu.sv:322, 343)

#### Scenario: SRA by 31 of positive input
- GIVEN `operator_i = ALU_SRA`, `operand_a_i = 32'h7FFF_FFFF`, `operand_b_i = 32'h0000_001F`, `instr_first_cycle_i = 1`
- WHEN inputs settle
- THEN `result_o = 32'h0000_0000` (sign bit was 0)
- (ref: ibex_alu.sv:322, 343)

---

### Requirement: RV32B-inert behavior

Under `RV32B = RV32BNone`, when `operator_i` selects any RV32B-only
operator (any encoding listed in the operator-encoding table that is
not in the base set), the module SHALL:

1. Drive `result_o = 32'h0000_0000`. The RV32B result-mux fan-ins
   (`bitcnt_result`, `minmax_result`, `pack_result`, `sext_result`,
   `singlebit_result`, `rev_result`, `shuffle_result`, `xperm_result`,
   `butterfly_result`, `invbutterfly_result`, `clmul_result`,
   `multicycle_result`, `bfp_result`) are all hard-tied to `0` in this
   configuration, so the mux output is `0` for the corresponding
   operators.
2. Drive `imd_val_d_o[0] = 32'h0` and `imd_val_d_o[1] = 32'h0`.
3. Drive `imd_val_we_o = 2'b00` (no intermediate-value writeback).
4. Continue to produce valid `adder_result_o`, `adder_result_ext_o`,
   `is_equal_result_o`, and `comparison_result_o` exactly as for the
   `default` paths of the operator-decode `case` blocks.

In particular: address-calc operators `ALU_SH1ADD` / `ALU_SH2ADD` /
`ALU_SH3ADD` do **not** apply the operand-A pre-shift under
`RV32BNone` — the adder still sees `operand_a_i + operand_b_i`. (Their
`result_o` under `RV32BNone` is `0` from the result mux, but the adder
side-band is the unshifted sum.)

#### Scenario: RV32B operator yields zero result
- GIVEN `operator_i = ALU_CLZ` (value 40), `operand_a_i = 32'h0000_FFFF`, `operand_b_i = 32'h0`
- WHEN inputs settle
- THEN `result_o = 32'h0000_0000`
- AND  `imd_val_d_o[0] = 0`, `imd_val_d_o[1] = 0`
- AND  `imd_val_we_o = 2'b00`
- (ref: ibex_alu.sv:1290-1313 — `g_no_alu_rvb` block)

#### Scenario: RV32B operator still drives valid adder side-band
- GIVEN `operator_i = ALU_MIN` (value 31), `operand_a_i = 32'h0000_000A`, `operand_b_i = 32'h0000_0003`, `multdiv_sel_i = 0`
- WHEN inputs settle
- THEN `result_o = 32'h0000_0000` (RV32B-inert)
- AND  `adder_result_o = 32'h0000_0007` (`MIN` is in the comparison `op_b_negate` group → adder computes `a - b = 7`)
- AND  `comparison_result_o` follows the signed `~is_greater_equal` rule (downstream may sample it but the EX stage does not under `RV32BNone`)
- (ref: ibex_alu.sv:62-72, 122-126, 165-167, 1290-1313)

#### Scenario: SH1ADD does not pre-shift operand A under RV32BNone
- GIVEN `operator_i = ALU_SH1ADD`, `operand_a_i = 32'h0000_0001`, `operand_b_i = 32'h0000_0002`
- WHEN inputs settle
- THEN `result_o = 32'h0000_0000` (RV32B-inert)
- AND  `adder_result_o = 32'h0000_0003` (operand A is **not** shifted: the SH-shift selectors are guarded by `if (RV32B != RV32BNone)`)
- (ref: ibex_alu.sv:75-77)

---

### Requirement: ADD / SUB operator exposes adder result on result_o

For `operator_i ∈ { ALU_ADD, ALU_SUB }`, `result_o` SHALL equal
`adder_result_o`. (`ALU_SH1ADD`, `ALU_SH2ADD`, `ALU_SH3ADD` are also
mapped to the adder fan-in by the result mux but are RV32B-inert under
`RV32BNone`.)

#### Scenario: ADD wires adder to result
- GIVEN `operator_i = ALU_ADD`, `operand_a_i = 32'h0000_0007`, `operand_b_i = 32'h0000_0008`
- WHEN inputs settle
- THEN `result_o = 32'h0000_000F`
- AND  `adder_result_o = 32'h0000_000F`
- (ref: ibex_alu.sv:1329-1332)

#### Scenario: SUB wires adder to result
- GIVEN `operator_i = ALU_SUB`, `operand_a_i = 32'h0000_0010`, `operand_b_i = 32'h0000_0004`
- WHEN inputs settle
- THEN `result_o = 32'h0000_000C`
- AND  `adder_result_o = 32'h0000_000C`
- (ref: ibex_alu.sv:1329-1332)

---

### Requirement: Comparison operators expose boolean result

For `operator_i ∈ { ALU_EQ, ALU_NE, ALU_GE, ALU_GEU, ALU_LT, ALU_LTU,
ALU_SLT, ALU_SLTU }`, `result_o` SHALL equal
`{31'h0, comparison_result_o}` — i.e., a zero-extended boolean.

(`SLT` / `SLTU` are the two instructions that semantically need this
integer form; `EQ`/`NE`/`GE`/`GEU`/`LT`/`LTU` are sampled by the branch
unit through `comparison_result_o` directly, but the result mux still
drives the same pattern on `result_o`.)

#### Scenario: EQ result is 1 on equal operands
- GIVEN `operator_i = ALU_EQ`, `operand_a_i = 32'hCAFE_BABE`, `operand_b_i = 32'hCAFE_BABE`
- WHEN inputs settle
- THEN `result_o = 32'h0000_0001`
- (ref: ibex_alu.sv:1346-1350)

#### Scenario: GE on unequal operands
- GIVEN `operator_i = ALU_GE`, `operand_a_i = 32'h0000_0005`, `operand_b_i = 32'h0000_0003`
- WHEN inputs settle
- THEN `comparison_result_o = 1` (`5 ≥ 3`)
- AND  `result_o = 32'h0000_0001`
- (ref: ibex_alu.sv:163-164, 1346-1350)

---

### Requirement: imd_val_d_o and imd_val_we_o under RV32BNone

`imd_val_d_o[0]` and `imd_val_d_o[1]` SHALL be driven to
`32'h0000_0000` and `imd_val_we_o` SHALL be driven to `2'b00` for all
values of `operator_i` in this configuration. The intermediate-value
file is unused.

#### Scenario: Intermediate-value outputs are zero for any operator
- GIVEN any `operator_i`, any `operand_a_i`, any `operand_b_i`, with `RV32B = RV32BNone`
- WHEN inputs settle
- THEN `imd_val_d_o[0] = 32'h0`, `imd_val_d_o[1] = 32'h0`, `imd_val_we_o = 2'b00`
- (ref: ibex_alu.sv:1311-1312)

## Notes

- **Combinational only.** There are no registers or clocks in this
  module. All `always_comb` blocks in the SV source are pure
  combinational descriptions; the implementation MAY mirror that style
  or use any equivalent ARCH construct that produces the same
  function.

- **`instr_first_cycle_i` under `RV32BNone`.** The pipeline drives
  `instr_first_cycle_i = 1` for every single-cycle ALU operation; this
  is the value under which the shift requirement above holds. The SV
  source still references `instr_first_cycle_i` inside the
  shift-amount mux even when `RV32B = RV32BNone`: with
  `instr_first_cycle_i = 0` the shift amount becomes
  `32 - operand_b_i[4:0]` instead of `operand_b_i[4:0]`. Spec-conformant
  implementations MAY either faithfully replicate this conditional (for
  forward-compatibility with multi-cycle RV32B shifts) or fix
  `shamt = operand_b_i[4:0]` for standard shifts; under `RV32BNone`
  with the pipeline's actual usage pattern (`instr_first_cycle_i = 1`
  on every shift) the two are observationally equivalent. `imd_val_q_i`
  is similarly unused under `RV32BNone`.

- **Shared adder.** The adder is reused by the LSU for address
  generation and by the multdiv unit (via `multdiv_sel_i`). The
  contract is that `adder_result_o` and `adder_result_ext_o` are valid
  every cycle, not only on operators that the result mux routes
  through the adder.

- **Shared comparator.** The branch unit samples
  `comparison_result_o` and `is_equal_result_o` on operators it issued
  (e.g. `ALU_EQ` for a `BEQ`). The fact that those signals are also
  defined for non-comparison operators is harmless — downstream simply
  does not look at them in that case.

- **Phase D (future).** Adding RV32B support is out of scope for this
  spec. A later port-change will replace the inert RV32B paths with
  full implementations and refresh this spec accordingly.
