# IbexController — basic-suite test inventory

The basic suite (`tests/cocotb_tests/test_ibex_controller_unit.py`,
collected by `tests/test_ibex_controller_unit.py`) runs one
`@cocotb.test()` coroutine per spec Requirement (12 tests). Each test
walks the single most representative scenario for that Requirement.
The full regression suite is intentionally omitted from this inventory
to keep it from being used as an overfitting target.

- `req1_cold_reset_startup_sequence` — Spec §"Requirement 1: Reset →
  Boot → First-fetch startup sequence". Validates the deterministic
  3-state startup (RESET → BOOT_SET → FIRST_FETCH) by sampling
  `pc_mux_o`, `pc_set_o`, `instr_req_o`, `ctrl_busy_o` on each cycle.

- `req2_decode_plain_alu_instruction` — Spec §"Requirement 2: DECODE-state
  behavior". DECODE with a valid simple instruction: `pc_set_o=0`,
  `controller_run_o=1`, `instr_valid_clear_o=1`, `id_in_ready_o=1`,
  `pc_mux_o=PC_JUMP`.

- `req3_external_irq_priority_and_entry` — Spec §"Requirement 3: IRQ
  priority". DECODE + `irq_external` pending → IRQ_TAKEN with
  `pc_mux_o=PC_EXC`, `exc_pc_mux_o=EXC_PC_IRQ`,
  `exc_cause_o = ExcCauseIrqExternalM`, `csr_save_if_o`/`cause_o = 1`.

- `req4_external_debug_req_enters_dbg_taken_if` — Spec §"Requirement 4:
  Debug entry". DECODE + `debug_req_i=1` → DBG_TAKEN_IF with
  `exc_pc_mux_o=EXC_PC_DBD`, `debug_csr_save_o=1`,
  `debug_mode_entering_o=1`.

- `req5_illegal_instruction_flushes` — Spec §"Requirement 5: Exception
  handling in FLUSH". DECODE + `illegal_insn_i=1` pulse → FLUSH with
  `illegal_insn_q=1`, `exc_req_q=1`, `csr_save_cause_o=1`,
  `pc_mux_o=PC_EXC`, `exc_pc_mux_o=EXC_PC_EXC`.

- `req6_wfi_then_irq_wake` — Spec §"Requirement 6: WFI / sleep cycle".
  DECODE WFI → FLUSH → WAIT_SLEEP → SLEEP → (IRQ wake) → FIRST_FETCH.
  Verifies `ctrl_busy_o` drops in WAIT_SLEEP/SLEEP and rises again on
  IRQ-driven wake.

- `req7_mret_return` — Spec §"Requirement 7: MRET / DRET return".
  DECODE MRET → FLUSH(mret) with `csr_restore_mret_id_o=1` and
  `pc_mux_o=PC_ERET`.

- `req8_csr_save_strobes_only_in_their_states` — Spec §"Requirement 8:
  csr_save matrix". In DECODE, all save/restore strobes are 0;
  `csr_save_wb_o` is constant 0 under WritebackStage=0.

- `req9_illegal_insn_latches_then_clears_in_flush` — Spec §"Requirement 9:
  Latched state regs". `illegal_insn_q` latches in DECODE, holds for the
  FLUSH cycle, clears on FLUSH→DECODE return (because `illegal_insn_d`
  gates on `ctrl_fsm_cs != FLUSH`).

- `req10_debug_mode_q_sets_in_dbg_taken_if` — Spec §"Requirement 10:
  debug_mode_q / nmi_mode_q". After DBG_TAKEN_IF, `debug_mode_q=1`.

- `req11_mfip_id_fast_irq_zero` — Spec §"Requirement 11: mfip_id
  encoder". Single fast-IRQ at index 0 → `lower_cause = 5'd16` (=
  ExcCauseIrqFast0).

- `req12_pc_mux_per_state_smoke` — Spec §"Requirement 12: pc_mux_o per
  state". Smoke-checks PC_BOOT in RESET, PC_JUMP in DECODE, PC_EXC in
  IRQ_TAKEN; verifies `nt_branch_mispredict_o` is constant 0.
