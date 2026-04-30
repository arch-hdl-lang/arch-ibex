# Spec notes from the test-authoring stage

Items the test agent had to choose an interpretation for while writing
the basic + full suites. Orchestrator: please review before the
implementer stage.

## 1. Reference-ALU model: relationship between `alu_adder_i` and `alu_adder_ext_i`

The spec port table (lines 56–58) lists `alu_adder_ext_i` (34 b) and
`alu_adder_i` (32 b) as **independent** inputs from the ALU. Inside
the multdiv:

- `res_adder_h = alu_adder_ext_i[32:1]` (spec line 587, 596).
- `op_numerator_d = div_sign_a ? alu_adder_i : op_a_i` (spec MD_ABS_A
  description, lines 343–348).

The spec does not state outright that `alu_adder_i == alu_adder_ext_i[32:1]`
in all states. Reading line 587 ("bit 0 is the unwanted LSB carry-out,
bits [32:1] are the real 32-bit difference") and line 575 (`MD_ABS_A`
captures `alu_adder_i` to get `-op_a_i = |op_a_i|`), the intent is:
both signals are different views of the same combinational ALU adder
output, and the multdiv consumer uses bits [32:1] of the 34-bit
extended sum as its 32-bit "difference" view, which matches what
`alu_adder_i` produces in the upstream ALU (since the LSB-1 injection
trick converts `+1+1` into a carry-in at bit 1).

**Resolution chosen by the test agent**: drive
`alu_adder_i = (alu_adder_ext_i >> 1) & 0xFFFFFFFF`. This is the
minimal ALU surface multdiv needs and matches the reading above.

If the implementer agent / ALU-side spec disagrees (e.g. the ALU spec
defines `alu_adder_i` differently from "[32:1] of ext"), the harness
helper `_alu_step` in both test files needs to be updated.

## 2. `equal_to_zero_i` semantics

The spec says (line 59): "The ALU's zero-comparator output. Sampled
in `MD_IDLE` to detect divide-by-zero". Combined with the integration
constraint (line 745–749) that `equal_to_zero_i` is a combinational
function of `alu_operand_a_o`, `alu_operand_b_o`, and `op_b_i`, but
no exact formula is given.

The brief from the orchestrator told the test agent "Equality is
`a == b`", interpreting the 33-bit operand wires literally. That
reading produces incorrect divide-by-zero detection in `MD_IDLE`
(where `a = {0, 1}` and `b = {~op_b, 1}`, which are equal only when
`op_b = 0xFFFFFFFF`).

**Resolution chosen by the test agent**: drive
`equal_to_zero_i = (alu_adder_i == 0)`. Because both operands carry
an LSB-1, the 32-bit difference `alu_adder_i = A + ~B + 1 = A − B`,
so `alu_adder_i == 0 <=> A == B` for the underlying 32-bit operands
the multdiv intends to compare. In `MD_IDLE` with `A = 0, B = op_b_i`,
this correctly fires `equal_to_zero_i = 1` iff `op_b_i = 0`.

This matches the hardware semantics (the upstream ALU's
`is_equal_result_o` is the equality-of-`A`-and-`B` flag derived from
the same adder, not a bit-level operand equality). If the
implementer / ALU-side spec uses a different formula, the harness
helper needs updating.

## 3. Lane-1 write-enable pulsing

The spec (lines 64, 405–407) says lane 1 write-enable is
`div_en_internal` — "high every cycle the divider FSM advances". The
named scenario "Lane 1 captured at MD_ABS_B" (lines 624–631) only
asserts that lane 1 captures the divisor at `MD_ABS_B` and "the value
is held stable" thereafter via `op_denominator_d = op_denominator_q`
default.

The full-suite test `lane1_holds_divisor_through_compute` therefore
asserts (a) at least one lane-1 we pulse and (b) the final lane-1
value equals `op_b_i`, rather than asserting we is high *every*
divider cycle (which the spec does say but is implementation-detail-
heavy). The basic-suite test `imd_lane1_captured_at_abs_b` only
asserts the first we pulse + value, which is the load-bearing
behaviour.

No follow-up needed unless the implementer optimises lane-1 we to
fire only at `MD_ABS_B` (which would still be spec-compliant by the
"held stable" wording, but stricter than the line-128 description).
