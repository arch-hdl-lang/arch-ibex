# Decoder basic-suite test inventory

One bullet per `@cocotb.test` in `tests/cocotb_tests/test_ibex_decoder_unit.py`.
Mirrors the 12 Requirements in `specs/decoder/spec.md` exactly. The
arch agent reads this file; assertion bodies stay hidden.

- `immediate_extraction_canonical_set` — verifies the six fully-decoded immediate ports are fixed bit-string functions of `instr_rdata_i` independent of opcode.
- `register_addressing_slices` — verifies `rf_raddr_a_o` / `rf_raddr_b_o` / `rf_waddr_o` are fixed slices of `instr_rdata_i` regardless of opcode.
- `rf_we_asserted_for_arithmetic_and_cleared_on_illegal` — verifies `rf_we_o` is asserted for an instruction that produces an architectural register write and is forced low when illegal-instruction is detected.
- `rf_ren_per_opcode` — verifies `rf_ren_a_o` and `rf_ren_b_o` are asserted exactly when the active opcode arm enables them.
- `alu_operator_for_add` — verifies the per-opcode `alu_operator_o` mux for the canonical R-type ADD.
- `alu_operand_mux_for_op_class` — verifies operand-A and operand-B mux selectors for the OP-class instruction (register-register ALU).
- `bt_mux_constants_under_branch_target_alu_zero` — verifies branch-target mux selectors keep their block-level defaults under `BranchTargetALU = 0`.
- `multdiv_control_for_mul` — verifies the RV32M multdiv control word for canonical MUL plus the forced ALU_ADD operator.
- `csr_control_for_csrrw` — verifies CSRRW raises `csr_access_o`, drives `csr_addr_o` from `instr[31:20]`, and routes register-file write data from the CSR side.
- `lsu_control_for_sw` — verifies LSU request, write enable, and access-size selectors for canonical store-word.
- `control_flag_outputs_for_jal` — verifies `jump_in_dec_o` / `jump_set_o` strobe correctly on JAL first cycle and the SYSTEM trap flags stay low.
- `illegal_insn_aggregation_for_rv32b_opcode` — verifies an RV32B-only opcode flags illegal under RV32BNone and the illegal-mask machinery clears `rf_we_o` / `data_req_o` / jump / branch / csr flags.
