# Basic-suite test inventory — `ibex_multdiv_fast`

One test per spec Requirement; assertion bodies kept hidden so the
implementer cannot overfit to expected register values. The full
regression (`test_ibex_multdiv_fast_unit_full.py`) is intentionally
*not* listed.

- `mul_three_cycle_walk` — Drives `MD_OP_MULL` with two unsigned operands and verifies `multdiv_result_o` matches Python's unsigned-low-32 product after the FSM walk.
- `mulh_four_cycle_walk` — Drives `MD_OP_MULH` (MULHU mode) with all-ones × all-ones and verifies the upper 32 bits of the unsigned 64-bit product.
- `kernel_signed_mul_lower_word` — Smoke-tests the 16×16 kernel's 17-bit sign extension by running a signed-mode `MD_OP_MULL` with a negative operand and confirming the low 32 bits match the unsigned-product low half.
- `result_mux_selects_mac_when_div_sel_low` — Verifies the result mux routes `mac_res_d[31:0]` (not `imd_val_q_i[0][31:0]`) on a multiply, exercising the `div_sel_i = 0` arm.
- `divu_full_walk_non_zero_divisor` — Drives a non-zero-divisor DIVU and verifies both the quotient (matches Python's `//`) and that the cycle count is the spec-prescribed full schedule.
- `divu_by_zero_short_circuits` — Drives DIVU with `op_b_i = 0` in default timing and verifies the all-ones sentinel result and that `valid_o` rises in only a few cycles.
- `divu_by_zero_constant_time_full_schedule` — Drives DIV by zero with `data_ind_timing_i = 1` and verifies the all-ones sentinel still appears AND the cycle count is the full long-division schedule.
- `signed_div_overflow_int_min_div_neg_one` — Drives `DIV(0x8000_0000, 0xFFFF_FFFF)` and verifies the no-trap RISC-V overflow result naturally falls out of the abs/sign-correction sequence.
- `alu_operand_exchange_idle_drives_zero_minus_b` — With the FSM in `MD_IDLE` and a divide pending, verifies the spec-prescribed encoding `alu_operand_a_o = {32'h0, 1'b1}` and `alu_operand_b_o = {~op_b_i, 1'b1}` is on the wires.
- `imd_lane1_captured_at_abs_b` — Drives a divide and verifies the unit pulses `imd_val_we_o[1] = 1` while writing the absolute-valued divisor with the top two bits forced to zero.
- `reset_puts_fsm_in_idle` — Asserts async-low reset, deasserts, verifies `valid_o = 0` immediately, then runs a normal MUL to confirm the FSM resumed from a clean state.
- `valid_low_when_idle` — Holds both `mult_en_i = 0` and `div_en_i = 0` across many clock edges after reset and verifies `valid_o` never rises spuriously.
