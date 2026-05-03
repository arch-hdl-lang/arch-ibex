# READY — B2 IbexWbStage

## Status: READY TO ARCHIVE

All steps 1–8 of WORKFLOW.md are complete for Phase B swap B2 (IbexWbStage).

## What was done

1. **Proposal** (`changes/port-wb_stage/proposal.md`) — construct enumeration table,
   scope (WritebackStage=0 only), approach (module + comb only).

2. **Spec** (`changes/port-wb_stage/specs/wb_stage/spec.md`) — 9 Requirements extracted
   from upstream ibex_wb_stage.sv, with integration constraints (IC-1 through IC-6).

3. **Tests** — basic suite (`tests/cocotb_tests/test_wb_stage_unit.py` + collector),
   full regression suite (`tests/cocotb_tests/test_wb_stage_unit_full.py` + collector),
   and `changes/port-wb_stage/tests-inventory.md`.

4. **Implementation** (`src/IbexWbStage.arch`) — purely combinational ARCH module
   using `module` + `comb` blocks only. No seq, no thread, no fsm.

5. **Two-stage review** — Stage 1 (spec compliance): all 9 REQs covered, no extra
   behavior. Stage 2 (design quality): naming, construct choice, doc comments, pitfalls
   all clean. Both stages passed.

6. **Basic gate** — `pytest tests/test_wb_stage_unit.py tests/test_soc_lint.py tests/test_cpu_programs.py` → **6 passed**.

7. **Full regression** — `pytest tests/test_wb_stage_unit_full.py` → **1 passed** (11 cocotb scenarios inside).

## Key design decisions

- `WritebackStage=0` is purely combinational — no registers, no seq, no thread.
- The masked-OR combiner for `rf_wdata_wb_o` relies on the upstream one-hot guarantee
  (`RFWriteFromOneSourceOnly` assertion, IC-1): `rf_we_id_i` and `rf_we_lsu_i` are
  mutually exclusive.
- `clk_i` and `rst_ni` are declared for port-boundary compatibility but unused.
  They cannot be sunk via `let` (Clock/Reset types), suppressed via `-Wno-UNUSEDSIGNAL`.
- One fix pass was needed: a comment containing the word "Verilator" was emitted as
  a block comment by the ARCH compiler, which Verilator parsed as a directive. Fixed
  by rewording the comment to remove the offending word.

## Files produced

- `src/IbexWbStage.arch`
- `build/ibex_wb_stage.sv` (compiler-emitted, not committed)
- `changes/port-wb_stage/proposal.md`
- `changes/port-wb_stage/tasks.md`
- `changes/port-wb_stage/specs/wb_stage/spec.md`
- `changes/port-wb_stage/tests-inventory.md`
- `tests/cocotb_tests/test_wb_stage_unit.py`
- `tests/cocotb_tests/test_wb_stage_unit_full.py`
- `tests/test_wb_stage_unit.py`
- `tests/test_wb_stage_unit_full.py`

## Not done (stop before step 9)

Archive step (step 9) is intentionally NOT done — the parent orchestrator
will serialize archive commits across B1 and B2 to avoid conflicts.
