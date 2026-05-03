# IbexIfStage — basic-suite test inventory

The basic suite (`tests/cocotb_tests/test_ibex_if_stage_unit.py`,
collected by `tests/test_ibex_if_stage_unit.py`) runs one
`@cocotb.test()` coroutine per spec Requirement (10 tests). Each test
walks the single most representative scenario for that Requirement.
The full regression suite is intentionally omitted from this inventory
to keep it from being used as an overfitting target.

- `req1_exception_pc_mux_irq_vector` — Spec §"Requirement 1: Exception
  PC mux", Scenario "vectorised external IRQ". Drives `EXC_PC_IRQ`
  with `lower_cause=11`, observes `instr_addr_o` after a `PC_EXC`
  branch and expects `0x1000_202C`.

- `req2_fetch_address_mux_boot_pc` — Spec §"Requirement 2: Fetch
  address mux", Scenario "boot PC". `PC_BOOT` with
  `boot_addr_i = 0x0010_0000` must produce a fetch address of
  `0x0010_0080`.

- `req3_branch_request_synthesis_aligns_to_halfword` — Spec
  §"Requirement 3: Branch request synthesis", Scenario "regular
  pc_set_i". Drives `pc_set_i = 1` with `fetch_addr_n = 0x0010_0083`
  and verifies `instr_addr_o = 0x0010_0082` (bit 0 forced to 0).

- `req4_prefetch_buffer_clean_fetch_passes_through` — Spec
  §"Requirement 4: Prefetch buffer wiring + valid squash", Scenario
  "clean fetch passes through". Lands a clean instruction via the OBI
  handshake and expects `instr_valid_id_o` to assert.

- `req5_compressed_decoder_uncompressed_passthrough` — Spec
  §"Requirement 5: Compressed decoder wiring". Lands an RV32 ADDI
  (`0x00100093`) and verifies `instr_is_compressed_id_o = 0` and
  `illegal_c_insn_id_o = 0`.

- `req6_instruction_error_pmp_first_half_overrides_plus2` — Spec
  §"Requirement 6: Instruction-error combination", Scenario
  "PMP first-half overrides plus2". With both PMP errors high,
  `instr_fetch_err_o = 1` and `instr_fetch_err_plus2_o = 0`.

- `req7_pipe_reg_we_clean_register_write` — Spec §"Requirement 7:
  IF→ID pipeline-register write enable", Scenario "clean register
  write". Verifies `pc_id_o`, `instr_rdata_id_o`, and
  `instr_fetch_err_o` latch correctly on a normal write.

- `req8_instr_valid_state_holds_across_stalls` — Spec §"Requirement
  8: instr_valid_id_q / instr_new_id_q state register", Scenario
  "valid latches and holds across stalls". After landing an
  instruction, `instr_valid_id_o` stays 1 and `instr_new_id_o` drops
  to 0 on subsequent cycles.

- `req9_csr_mtvec_init_pulses_on_pc_boot` — Spec §"Requirement 9:
  csr_mtvec_init_o", Scenario "boot pulse". Confirms
  `csr_mtvec_init_o = (pc_mux_i == PC_BOOT) & pc_set_i` for the three
  combinations (boot+set, jump+set, boot+no-set).

- `req10_tieoffs_constants` — Spec §"Requirement 10: ICache +
  branch-predictor + dummy-instruction tieoffs". After reset, every
  tieoff output (`ic_*_o`, `dummy_instr_id_o`, `instr_bp_taken_o`,
  `pc_mismatch_alert_o`, `instr_intg_err_o`) reads 0.
