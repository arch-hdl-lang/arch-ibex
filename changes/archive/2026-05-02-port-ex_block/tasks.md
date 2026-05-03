# Tasks: Port `ibex_ex_block` → `src/IbexExBlock.arch` (B1)

## Checklist

- [x] Read HANDOFF.md, WORKFLOW.md, memory feedback files
- [x] Read upstream `ibex_ex_block.sv` (217 LoC), `specs/alu/spec.md`, `specs/multdiv/spec.md`
- [x] Read neighbor modules (ibex_id_stage.sv, ibex_wb_stage.sv) — to be done by spec-extractor agent
- [ ] **Step 1** — Write `changes/port-ex_block/proposal.md` (construct enumeration + approach)
- [ ] **Step 2** — Dispatch spec-extractor agent (SV-only; reads ibex_ex_block.sv, ibex_pkg.sv, ibex_id_stage.sv, ibex_wb_stage.sv, pipeline_details.rst)
- [ ] **Step 3** — Dispatch test-author agent (spec-only; writes test_ex_block_unit.py + full + inventory)
- [ ] **Step 4** — Triage spec-notes.md if it appears (review, possibly rerun spec agent)
- [ ] **Step 5** — This tasks.md (done)
- [ ] **Step 6** — Dispatch implementer agent (spec + test-inventory + ARCH spec + pitfalls)
- [ ] **Step 6a** — Two-stage review (mandatory: ex_block has ≥ 3 Requirements)
  - [ ] Stage 1: spec-compliance reviewer
  - [ ] Stage 2: design-quality reviewer
- [ ] **Step 7** — Basic gate: `make build && pytest tests/test_ex_block_unit.py tests/test_soc_lint.py tests/test_cpu_programs.py`
- [ ] **Step 7a** — Failure-triager (if step 7 fails)
- [ ] **Step 8** — Background regression: `pytest tests/test_ex_block_unit_full.py`
- [ ] Write `READY.md` (definition of done)

## Key design decisions to document

1. **Construct choice**: `module` with `inst` of `ibex_alu` and `ibex_multdiv_fast`.
2. **No `.archi` stubs exist for alu/multdiv** — the impl uses the `.arch` source files directly through the build system. The implementer instantiates via ARCH `inst` of the sub-modules that were already ported.
3. **unpacked Vec ports**: `imd_val_d_o[2]` and `imd_val_q_i[2]` are unpacked arrays in upstream SV; use `unpacked Vec<UInt<34>, 2>` on the ex_block boundary.
4. **BranchTargetALU param**: Fixed to 0 in SoC (no dedicated branch-target adder); `branch_target_o = alu_adder_result_ex_o`.
5. **RV32M param**: Fixed to RV32MFast (= 2); the slow variant is out of scope.
6. **multdiv_sel** comb logic: `multdiv_sel = mult_sel_i | div_sel_i`.
7. **ex_valid_o**: `multdiv_sel ? multdiv_valid : ~(|alu_imd_val_we)` — comb from sub-module outputs.
8. **imd_val_q routing**: `alu_imd_val_q[i] = imd_val_q_i[i][31:0]` (slice to 32 bits for ALU).
9. **imd_val_d mux**: `imd_val_d_o[i] = multdiv_sel ? multdiv_imd_val_d[i] : {2'b0, alu_imd_val_d[i]}`.

## Notes
- B1 is parallel with B2 (IbexWbStage) in worktree `arch-ibex-b2`. Do not interact.
- ARCH_BIN must be `~/github/arch-com-thread-skid/target/release/arch` (see HANDOFF.md).
- After non-trivial changes: `rm -rf build/ && make build` before claiming green.
- 3-strike rule applies. Compiler bugs go to failure-triager, not workaround.
