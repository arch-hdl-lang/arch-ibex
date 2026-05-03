# Tasks: Port `ibex_if_stage` to ARCH (B3)

Spec: `specs/if_stage/spec.md` — **10 Requirements**, so two-stage
review (WORKFLOW step 6a) is **MANDATORY**.

## Implementation checklist

- [ ] **Spec done.** 10 Requirements + Integration constraints. No
      ambiguities flagged.
- [ ] **Tests written** — basic `tests/cocotb_tests/test_ibex_if_stage_unit.py`
      (one `@cocotb.test` per Requirement, ≤30 s) + full
      `tests/cocotb_tests/test_ibex_if_stage_unit_full.py` (every
      Scenario + edge cases) + pytest collectors + tests-inventory.md.
- [ ] **Implementer agent dispatched** (spec + basic test inventory +
      ARCH HDL spec doc + AI reference card only). Forbidden inputs:
      upstream SV, test files, other `.arch` files. Output:
      `src/IbexIfStage.arch`.
- [ ] **Two-stage review (6a) — mandatory.** ≥3 Requirements triggers it.
  - [ ] Stage 1 spec-compliance reviewer. Loop until ✅.
  - [ ] Stage 2 design-quality reviewer. Critical/Important block,
        Minor noted only.
- [ ] **Basic gate (blocking).** `rm -rf build/ && make build` then
      `pytest tests/test_ibex_if_stage_unit.py tests/test_soc_lint.py
      tests/test_cpu_programs.py`. On failure → failure-triager (7a)
      first, NOT direct fixes.
- [ ] **Background regression.** `pytest tests/test_ibex_if_stage_unit_full.py`
      with structured failure report (one block per failing test).
- [ ] **Archive.** Fresh-evidence gate (`make test` in current message,
      paste tail). Move `changes/port-if_stage/` → archive.

## Construct decisions (from proposal)

- Outer: `module IbexIfStage`.
- 2 sub-instances: `IbexPrefetchBuffer` (A8), `IbexCompressedDecoder` (A5).
- IF→ID pipeline registers: ARCH `port reg ... guard if_id_pipe_reg_we`
  pattern (mirrors upstream `if (if_id_pipe_reg_we)` write enable; no
  reset under ResetAll=0).
- State regs `instr_valid_id_q`, `instr_new_id_q`: regular `reg` with
  async-low reset.
- All other logic in one `comb` block.

## ARCH-side notes for the implementer

- The IF→ID pipe regs must lower to `always_ff @(posedge clk_i)` with
  `if (if_id_pipe_reg_we)` only — no `if (!rst_ni)` arm (matches upstream
  `g_instr_rdata_nr` branch under ResetAll=0). The `port reg ... guard
  if_id_pipe_reg_we` form should produce this.
- `instr_gets_expanded_o`/`_id_o` are `InstrExp` enum (3-valued); preserve
  the type through the pipe reg.
- Tieoff outputs (ICache, branch-predictor, dummy-instr) drive `0`
  combinationally — no register storage.
- `unused_*` absorbers for unused inputs to satisfy SoC lint.
