# EX Block basic-suite test inventory

One bullet per `@cocotb.test` in
`tests/cocotb_tests/test_ibex_ex_block_unit.py`.
Mirrors the Requirements in
`changes/port-ex_block/specs/ex_block/spec.md` exactly.
The arch agent reads this file; assertion bodies stay hidden.

- `multdiv_sel_or_of_mult_and_div_selectors` — verifies `multdiv_sel = mult_sel_i | div_sel_i` with both selectors low; confirms the ALU path is active (result_ex_o = alu_result) and `ex_valid_o = 1`.

- `result_ex_o_selects_alu_result_when_multdiv_sel_low` — drives `multdiv_sel = 0` (both sel inputs low) and an ALU ADD; verifies `result_ex_o` equals the ALU's combinational result.

- `result_ex_o_selects_multdiv_result_when_multdiv_sel_high` — drives a 3-cycle MUL (MD_OP_MULL) with `mult_sel_i = 1`; verifies `result_ex_o` equals the multdiv's result when `ex_valid_o` asserts.

- `imd_val_d_o_mux_selects_alu_path_with_zero_extension` — with `multdiv_sel = 0` (ALU path), verifies `imd_val_d_o[0]` and `imd_val_d_o[1]` are both `34'h0` and `imd_val_we_o = 2'b00` (ALU drives zeros under RV32BNone).

- `imd_val_we_o_mux_selects_multdiv_we_when_multdiv_sel_high` — during an active multiply operation (`mult_sel_i = 1`), verifies that `imd_val_we_o` is non-zero on at least one cycle (reflecting the multdiv's write-enables rather than the ALU's constant `2'b00`).

- `imd_val_q_slice_routing_to_alu` — plants a non-zero upper-2-bits pattern in `imd_val_q_i[0]`; verifies the ALU still functions correctly (indicating the ex_block slices to `[31:0]` before the ALU port) via a known-result ALU_EQ operation.

- `branch_decision_o_wired_from_alu_comparator` — drives ALU_EQ with equal and then unequal operands; verifies `branch_decision_o` tracks `comparison_result_o` in both cases.

- `branch_target_o_equals_alu_adder_result` — drives an ALU_ADD with predictable operands; verifies `branch_target_o == alu_adder_result_ex_o` (BranchTargetALU = 0 path).

- `ex_valid_o_is_one_for_all_alu_only_operations` — exercises a sweep of ALU operators under RV32BNone; verifies `ex_valid_o = 1` for each (since `alu_imd_val_we = 2'b00` always, `~(|2'b00) = 1`).

- `ex_valid_o_tracks_multdiv_valid_when_multdiv_sel_high` — drives a MUL; verifies `ex_valid_o = 0` on the first cycle (ALBL state, not yet done) and `ex_valid_o = 1` when the multdiv reaches its terminal state.

- `combinational_cross_coupling_resolves_within_netlist` — runs a full MUL (100 × 7 = 700) and a full DIVU (700 / 7 = 100) through the ex_block; both sub-modules must be present in the Verilator netlist for the comb cross-coupling loop (multdiv ↔ ALU adder) to close correctly and produce the right result.
