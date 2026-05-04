# Tasks: Port `ibex_controller` to ARCH (B4)

Spec: `specs/controller/spec.md` — **12 Requirements**, so two-stage
review (WORKFLOW step 6a) is **MANDATORY**.

## Implementation checklist

- [x] **Spec done.** 12 Requirements + 9 Integration constraints +
      7 Spec notes (incl. corrections to the proposal's caveats).
- [ ] **Tests written** — basic + full cocotb suites + pytest collectors
      + tests-inventory.md.
- [ ] **Implementer agent dispatched** — produces `src/IbexController.arch`.
- [ ] **Two-stage review (6a) — mandatory** (≥3 Requirements).
- [ ] **Basic gate (blocking).**
- [ ] **Background regression.**
- [ ] **Archive.**

## Construct decisions (from proposal + spec)

- Outer: `module ibex_controller` (snake_case for SoC compat).
- **`fsm` construct** for the 9-active-state machine: `RESET`,
  `BOOT_SET`, `FIRST_FETCH`, `DECODE`, `IRQ_TAKEN`, `DBG_TAKEN_IF`,
  `DBG_TAKEN_ID`, `FLUSH`, `WAIT_SLEEP`, `SLEEP`. Per spec §"FSM
  transition table".
- **Rejected `thread`**: controller is reactive (state-and-input
  dependent transitions every cycle), not a sequential walker with
  `wait until cond;` — see proposal's construct enumeration.
- Latched flops (4): `illegal_insn_q`, `exc_req_q`, `load_err_q`,
  `store_err_q` per spec Requirement 9. **NOT** `mret_insn_q`,
  `dret_insn_q`, `wfi_insn_q`, `ebrk_insn_q`, `ecall_insn_q`,
  `csr_pipe_flush_q`, `instr_fetch_err_q`, `instr_fetch_err_plus2_q` —
  these are comb-qualified `& instr_valid_i`, NOT flopped (per spec
  N-correction; introducing a flop here would break Requirement 2's
  DECODE→FLUSH timing).
- Mode regs: `debug_mode_q`, `nmi_mode_q`, `enter_debug_mode_prio_q`,
  `do_single_step_q` — all rising-edge async-low-reset (per spec N-1:
  no falling-edge state).
- All `csr_save_*_o`, `csr_restore_*_o`, output-gate signals are
  combinational (per spec Requirement 8 matrix).

## ARCH-side notes for the implementer

- The `mfip_id` priority encoder uses ARCH's `find_first` Vec method
  on the 15-bit `irqs_i.irq_fast` (per spec N-2, lowest-set-bit wins).
- `exc_cause_o` is the packed struct `ExcCause {irq_int, irq_ext,
  lower_cause}`. Use struct-literal expressions consistent with the
  IF stage's port shape (B3's `IbexIfStage.arch` has the same struct
  defined).
- `unique case (1'b1)` for the FLUSH exception-priority encoder lowers
  to a `match` with concrete priority. Keep the priority order: bus
  fault > illegal > ecall > ebreak > store err > load err.
- The `default:` arm of the FSM is unreachable but must be emitted
  per spec N-7. Use a single safe transition (e.g. back to `RESET`).
- No literal `Verilator` in `///` comments (B2 lesson).
- `port reg ... guard` is deprecated; use `pipe_reg<T, 1>` with a
  conditional `seq` block when registered outputs are needed (B3
  lesson — fixes SYNCASYNCNET warnings).
- Module name MUST be `ibex_controller` (snake_case) so the SoC's
  `controller_i` instantiation site finds it (B3 lesson).
- Declare every parameter the upstream `ibex_top.sv` instantiation
  passes through, even unused ones, so Verilator `--lint-only`
  doesn't trip PINNOTFOUND (B3 lesson).
