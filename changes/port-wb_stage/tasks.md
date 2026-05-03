# Tasks: Port ibex_wb_stage → IbexWbStage.arch (B2)

## Status legend
- [ ] = todo
- [x] = done
- [!] = blocked

## Step 1: Propose
- [x] Write `changes/port-wb_stage/proposal.md` with construct enumeration.

## Step 2: Spec (isolated sub-agent — SV-only)
- [x] Dispatch spec-extractor sub-agent.
- [x] Agent produces `changes/port-wb_stage/specs/wb_stage/spec.md`.
- [x] Count requirements → 9 Requirements → two-stage review (step 6a) is MANDATORY.

## Step 3: Tests (isolated sub-agent — spec-only)
- [x] Dispatch test-author sub-agent (reads spec only, not SV).
- [x] Agent produces:
  - `tests/cocotb_tests/test_wb_stage_unit.py` (basic suite)
  - `tests/cocotb_tests/test_wb_stage_unit_full.py` (full regression suite)
  - `tests/test_wb_stage_unit.py` (pytest collector, basic)
  - `tests/test_wb_stage_unit_full.py` (pytest collector, full)
  - `changes/port-wb_stage/tests-inventory.md` (basic suite only: names + docstrings)
- [x] Verify tests fail gracefully (no SV yet — expect skip, build/ibex_wb_stage.sv missing).

## Step 4: Triage spec-notes (if spec-notes.md produced)
- [x] No spec-notes.md produced — spec was clean, no triage needed.

## Step 5: Tasks update
- [x] This file (tasks.md) created.

## Step 6: Implement (isolated sub-agent — spec + test-inventory only)
- [x] Dispatch arch-implementer sub-agent.
- [x] Agent produces `src/IbexWbStage.arch`.
- [x] One fix pass needed: comment contained word "Verilator" which Verilator
      parsed as a directive in emitted block comment. Rewording fixed it.

## Step 6a: Two-stage review (conditional on ≥ 3 Requirements)
- [x] Stage 1: spec-compliance reviewer — all 9 Requirements covered, no extra behavior. PASS.
- [x] Stage 2: design-quality reviewer — naming correct, module+comb, doc refs, pitfalls clean. PASS.

## Step 7: Basic gate
- [x] `rm -rf build/ && ARCH_BIN=~/github/arch-com-thread-skid/target/release/arch make build` → all 9 modules built.
- [x] `pytest tests/test_wb_stage_unit.py tests/test_soc_lint.py tests/test_cpu_programs.py` → 6 passed.
- [x] All pass.

## Step 8: Background regression
- [x] `pytest tests/test_wb_stage_unit_full.py` → 1 passed.
- [x] All pass.

## Key design notes (WritebackStage == 0 in-scope)
- With `WritebackStage == 0`, the module is a passthrough:
  - `rf_waddr_wb_o = rf_waddr_id_i`
  - `rf_wdata_wb_o = masked OR of rf_wdata_id + rf_wdata_lsu`
  - `rf_we_wb_o = rf_we_id_i | rf_we_lsu_i`
  - `ready_wb_o = 1'b1` (always ready)
  - `outstanding_load_wb_o = 0`, `outstanding_store_wb_o = 0`
  - `rf_write_wb_o = 0`
  - `pc_wb_o = 0`
  - `rf_wdata_fwd_wb_o = 0`
  - `instr_done_wb_o = 0`
  - `perf_instr_ret_wb_spec_o = 0`, `perf_instr_ret_compressed_wb_spec_o = 0`
  - `perf_instr_ret_wb_o = instr_perf_count_id_i & en_wb_i & ~(lsu_resp_valid_i & lsu_resp_err_i)`
  - `perf_instr_ret_compressed_wb_o = perf_instr_ret_wb_o & instr_is_compressed_id_i`
  - `dummy_instr_wb_o = dummy_instr_id_i`
- `rf_wdata_wb_o` is the OR-mask combiner: `(mux_we[0] ? wdata_id : 0) | (mux_we[1] ? wdata_lsu : 0)`
- No flopped state in the passthrough path (WritebackStage=1 path is out of scope).
- Integration constraint: `rf_we_id_i` and `rf_we_lsu_i` are mutually exclusive (LOAD instructs decoder not to set rf_we_id).

## 3-strike rule counter
Attempts on .arch: 1 (Verilator-comment fix; root cause = compiler emits block
comments, and word "Verilator" in block comments is parsed as a directive)
