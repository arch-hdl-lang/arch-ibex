# Tasks: Port `ibex_id_stage` to ARCH (B5)

Spec: `specs/id_stage/spec.md` — **16 Requirements**, so two-stage
review (WORKFLOW step 6a) is **MANDATORY**.

## Implementation checklist

- [x] **Proposal done.** Construct enumeration: outer `module`, no
      top-level `fsm` (the 2-state `id_fsm_q` is small enough to
      model as a plain `reg` with a `comb` next-state block; all
      surrounding logic is mux/handshake glue, not state-dependent).
- [x] **Spec done.** 16 Requirements + 15 Caller-side rules
      (CS-1..CS-15) + 12 Spec notes (N-1..N-12).
- [x] **Tests written** — basic + full cocotb suites + pytest collectors
      + tests-inventory.md.
- [ ] **Implementer agent dispatched** — produces `src/IbexIdStage.arch`.
- [ ] **Two-stage review (6a) — mandatory** (≥3 Requirements).
- [ ] **Basic gate (blocking)**: `make build && pytest tests/test_ibex_id_stage_unit.py tests/test_soc_lint.py tests/test_cpu_programs.py`.
- [ ] **Full gate**: `make test` (38+ tests).
- [ ] **Archive** to `changes/archive/2026-MM-DD-port-id_stage/`.

## Construct decisions (from proposal + spec)

- Outer: `module ibex_id_stage` (snake_case for SoC compat).
- **Two `inst` blocks** at module top: `decoder_i: ibex_decoder` and
  `controller_i: ibex_controller`. Both pulled in via `.archi`
  (already-ported A4 + B4) — leaf-first build order handled by
  `scripts/build.sh`.
- **No top-level `fsm`**. The `id_fsm_q ∈ {FIRST_CYCLE, MULTI_CYCLE}`
  state machine is 2 states with one state-dependent flag (`stall_*`).
  Modelling as a top-level `fsm` would force the ~250 LoC of
  non-state-dependent operand-mux logic into FSM `default`/state
  bodies — see proposal's construct enumeration.
- **Latched flops** (per spec §Latched state regs):
  - `id_fsm_q: UInt<1>` — enable = `instr_executing` (NOT
    `instr_executing_spec`; per spec N-4 + flag #4 from spec
    extractor)
  - `branch_set_raw_q: Bool` — always-write flop, no enable (per spec
    N-3 + flag #1)
  - `branch_jump_set_done_q: Bool` — clears via `instr_valid_clear_o`,
    no per-instruction reset path (per spec N-9 + flag #6)
  - `imd_val_q: Vec<UInt<34>, 2>` — multdiv intermediate-value pair,
    per-lane WE from `imd_val_we_ex_i`
  - `instr_first_cycle_q` — derived from `id_fsm_q == FIRST_CYCLE`,
    NOT a separate flop (per spec §"`instr_first_cycle` and friends")
- All other state lives in the sub-modules (`decoder_i` and
  `controller_i`).

## Spec-extractor flags (must read before implementing)

The spec extractor surfaced 8 things that will trip a naive implementer:

1. **`branch_set_q` is NOT what the proposal called it.** Actual upstream
   uses `branch_set_raw_q` + `branch_jump_set_done_q` — two separate
   flops. Don't collapse them.
2. **`flush_id` and `instr_valid_clear_o` are different.** Both come
   from controller, both fire on FLUSH, but `flush_id` blocks **this**
   cycle's retire (consumed locally as `instr_done = ~stall_id &
   ~flush_id & instr_executing`); `instr_valid_clear_o` clears the
   IF→ID register **next** cycle (passed through to IF). Conflating
   them silently breaks IRQ handling — exactly the B4-style bug.
3. **`lsu_req_done_i` is dead under WritebackStage=0.** Absorb it into
   a `let unused_lsu_req_done = lsu_req_done_i;` and use
   `lsu_resp_valid_i` for the multicycle-done test. Don't get tempted
   by the input's name.
4. **`id_fsm_q` enable vs. `instr_executing_spec` outer guard.** The
   reg-side enable is `instr_executing` (without `_spec`); the
   comb-block outer guard is `instr_executing_spec`. Under
   WritebackStage=0 they're equal but the structural separation must
   be preserved.
5. **The `FIRST_CYCLE` arm is one-hot priority.** Under decoder
   guarantee, exactly one of `lsu_req_dec`, `multdiv_en_dec`,
   `branch_in_dec`, `jump_in_dec` is high (or none). The default
   (none) keeps `id_fsm_d = FIRST_CYCLE` and zeros all stalls.
6. **`branch_jump_set_done_q` clears via `instr_valid_clear_o`.**
   No explicit per-instruction reset; the dedup flag clears
   combinationally when `instr_valid_clear_o` is high.
7. **2-cycle branch latency under BTALU=0 is load-bearing.** Cycle N:
   `branch_set_raw_d` high, FSM enters MULTI_CYCLE. Cycle N+1:
   `branch_set_raw_q` high → `branch_set` to controller, `pc_set_o`
   redirects IF. Cycle N+2: back to FIRST_CYCLE.
8. **`bt_a_operand_o` / `bt_b_operand_o` constant-0 tieoffs are
   required.** EX consumes them but ignores them under BTALU=0; don't
   drop the outputs from the port list.

## Caller-side rules (B4 lesson)

The spec includes 15 Caller-side rules (CS-1..CS-15) precisely because
B4's ISR-program gap was a caller-side cross-module bug that the
unit-only spec missed. The implementer **must** read each CS- rule and
ensure the implementation honors it. The `CS-8: flush_id ↔
instr_valid_clear_o` rule is the direct B5 analogue of the B4 bug —
do not conflate.

## ARCH-side notes for the implementer

- Two `inst` blocks. Connect every port of `decoder_i` and
  `controller_i` per spec §Sub-module instances connection tables.
  The build script orders leaves (decoder, controller `.archi`s) before
  composites (id_stage), so both interface stubs exist when id_stage
  builds.
- The `imd_val_q` `Vec<UInt<34>, 2>` shape worked in B1 IbexExBlock
  and A6 IbexMultdivFast under arch-com `main`. No new compiler issues
  expected.
- `icache_inval_o` is driven from a `fence.i` decode but our SoC has
  ICache off; the wire dangles externally. Drive it normally; SV emit
  will leave it unwired.
- `data_ind_timing_i` is wired through but never gates anything under
  `DataIndTiming=0` (spec N-6). Just wire it through.
- Per `feedback_arch_syntax_pitfalls`: ARCH's `port reg ... reset rst_ni`
  is async-low; rising-edge by default. No falling-edge regs in
  id_stage per spec N-(none flagged).
- Per `feedback_avoid_verilator_in_comments`: don't put the literal
  word "Verilator" in `///` doc comments.

## Verification gate

**Basic (blocking):**
```
make build
pytest tests/test_ibex_id_stage_unit.py tests/test_soc_lint.py tests/test_cpu_programs.py
```

**Full (background → archive):**
```
pytest tests/test_ibex_id_stage_unit_full.py
make test    # full SoC gate (38+ tests)
```

The 4 ISR programs (`timer_isr`, `sw_isr`, `ext_isr`, `multictx_isr`)
are the integration gate. They exercise the controller↔id_stage
handshake under real IRQ/MRET timing — the same regime where B4's
mepc-off-by-one bug surfaced. Any regression there means a CS- rule
was violated.
