# IbexIdStage — basic-suite test inventory

The basic suite (`tests/cocotb_tests/test_ibex_id_stage_unit.py`,
collected by `tests/test_ibex_id_stage_unit.py`) runs one
`@cocotb.test()` coroutine per spec Requirement (16 tests). Each test
walks the single most representative scenario for that Requirement.
The full regression suite is intentionally omitted from this inventory
to keep it from being used as an overfitting target.

- `req1_reset_clears_state_and_outputs` — Spec §"Requirement 1: Reset
  behavior". While `rst_ni` is low, `lsu_req_o`, `mult_en_ex_o`,
  `div_en_ex_o`, `rf_we_id_o`, `pc_set_o` are all 0; after release,
  `id_fsm_q = FIRST_CYCLE` and both `imd_val_q[*]` lanes are 0.

- `req2_rf_ren_gated_by_invalid_and_illegal` — Spec §"Requirement 2:
  Read-enable gating". `rf_ren_a_o` / `rf_ren_b_o` are suppressed when
  `instr_valid_i = 0` and when `illegal_csr_insn_i = 1` (which makes
  the aggregate `illegal_insn_o = 1`).

- `req3_illegal_insn_aggregates_csr_and_dret` — Spec §"Requirement 3:
  Illegal-instruction aggregation". `illegal_insn_o = instr_valid_i &
  (illegal_insn_dec | illegal_csr_insn_i | illegal_dret_insn |
  illegal_umode_insn)`. Verifies the CSR-side and DRET-outside-debug
  arms aggregate into the top-level flag.

- `req4_alu_operand_a_mux_lsu_addr_incr_override` — Spec §"Requirement 4:
  ALU operand-A mux". For an ADD, `alu_operand_a_ex_o = rf_rdata_a_i`;
  asserting `lsu_addr_incr_req_i = 1` overrides the mux to OP_A_FWD,
  routing `lsu_addr_last_i` through.

- `req5_alu_operand_b_immediate_for_addi` — Spec §"Requirement 5: ALU
  operand-B mux". For ADDI x1, x0, 1 the decoder picks OP_B_IMM /
  IMM_B_I → `alu_operand_b_ex_o` = 1. Asserting `lsu_addr_incr_req_i`
  forces IMM_B_INCR_ADDR → operand-B = 4.

- `req6_rf_wdata_mux_csr_path` — Spec §"Requirement 6: RF write-data
  mux and write enable". CSRRS picks `rf_wdata_sel = RF_WD_CSR` →
  `rf_wdata_id_o = csr_rdata_i`. Switching to ADD picks RF_WD_EX →
  `rf_wdata_id_o = result_ex_i`.

- `req7_lsu_req_one_cycle_first_cycle_only` — Spec §"Requirement 7: LSU
  request derivation". For LW, `lsu_req_o = 1` in FIRST_CYCLE only;
  drops to 0 in MULTI_CYCLE while `expecting_load_resp_o = 1`.

- `req8_imd_val_q_per_lane_we` — Spec §"Requirement 8: Multdiv
  intermediate-value register pair". Each lane is independently
  write-enabled via `imd_val_we_ex_i[i]`; resets to 34'h0; lane 1 holds
  while only lane 0 is enabled, and vice versa.

- `req9_branch_taken_first_to_multi_to_first` — Spec §"Requirement 9:
  ID-FSM next-state and stall sources". Branch-taken FIRST_CYCLE →
  MULTI_CYCLE → FIRST_CYCLE round trip. `perf_branch_o` pulses in
  FIRST_CYCLE; `ex_valid_i` retires from MULTI_CYCLE.

- `req10_branch_set_raw_q_two_cycle_latency` — Spec §"Requirement 10:
  Branch-set / jump-set pulse generation". Verifies the 2-cycle path:
  cycle N (FIRST_CYCLE) sets `branch_set_raw_d`; cycle N+1
  (MULTI_CYCLE) reads `branch_set_raw_q = 1` and sees `pc_set_o = 1`
  with `pc_mux_o = PC_JUMP`.

- `req11_nt_branch_addr_constant_zero` — Spec §"Requirement 11:
  `branch_taken` and `nt_branch_addr_o` constants". Under
  BranchPredictor=0, `nt_branch_addr_o = 0` and `nt_branch_mispredict_o
  = 0` continuously, including across the FSM walk.

- `req12_instr_first_cycle_id_o_tracks_valid_and_state` — Spec
  §"Requirement 12: First-cycle signal". `instr_first_cycle_id_o =
  instr_valid_i & (id_fsm_q == FIRST_CYCLE)`. Verifies it tracks both
  valid and FSM state across an LW sequence.

- `req13_mult_en_ex_o_gated_by_instr_executing` — Spec §"Requirement 13:
  Multdiv enable gating". For MUL, `mult_en_ex_o = 0` while
  `instr_valid_i = 0`; rises to 1 once instr_valid_i is asserted (so
  `instr_executing = 1`). `multdiv_ready_id_o = 1` continuously under
  WB=0.

- `req14_csr_op_en_o_pulse_on_retire` — Spec §"Requirement 14: CSR
  pipe-flush + op-enable derivation". For a CSRRW with no stalls,
  `csr_op_en_o` pulses in the retire cycle (= FIRST_CYCLE here, since
  CSR ops have no LSU/multdiv/branch stalls).

- `req15_perf_branch_pulse_in_first_cycle` — Spec §"Requirement 15:
  Performance-counter outputs". `perf_branch_o` pulses high in the
  FIRST_CYCLE of `branch_in_dec`; `perf_dside_wait_o` is asserted in
  the FIRST_CYCLE of an LW that hasn't yet got `lsu_resp_valid_i`.

- `req16_writeback_stage_zero_tieoffs` — Spec §"Requirement 16:
  WritebackStage=0 tieoffs and absorbers". Verifies `instr_type_wb_o =
  WB_INSTR_OTHER`, `rf_rd_a_wb_match_o = 0`, `rf_rd_b_wb_match_o = 0`,
  `bt_a_operand_o = 0`, `bt_b_operand_o = 0` both right after reset
  and after walking the FSM into DECODE.
