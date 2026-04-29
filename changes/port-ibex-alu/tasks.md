# Tasks: Port `ibex_alu` to ARCH

## 1. ARCH source

- [ ] 1.1 Call `get_construct_syntax("module")` and `get_construct_syntax("doc_comments")` to refresh on schema before writing.
- [ ] 1.2 Write `src/IbexAlu.arch` covering the in-scope operator set from the spec:
  - [ ] 1.2.1 Module header + ports matching upstream signature (operator_i, operand_a/b_i, multdiv_*, imd_val_*, adder_result_*, result_o, comparison_result_o, is_equal_result_o)
  - [ ] 1.2.2 Adder block — 33-bit signed sum with multdiv operand mux
  - [ ] 1.2.3 `is_equal_result_o` derived directly from `operand_a == operand_b`
  - [ ] 1.2.4 Comparator block — signed/unsigned LT, EQ, NE, GE/GEU dispatch
  - [ ] 1.2.5 Logic block — XOR/OR/AND
  - [ ] 1.2.6 Shift block — SLL/SRL/SRA with shamt = operand_b[4:0]
  - [ ] 1.2.7 SLT/SLTU result-from-comparison wiring
  - [ ] 1.2.8 RV32B operators dispatched to result=0; imd_val_d/we tied to 0
- [ ] 1.3 `///` front-matter doc comment referencing the spec and citing `ibex_alu.sv` line ranges per construct.

## 2. Build & lint

- [ ] 2.1 `arch_build_and_lint` clean (no warnings, no Verilator lint hits).
- [ ] 2.2 Add `"ibex_alu"` to `scripts/gen_filelist.py` SWAPPED set.
- [ ] 2.3 `make filelist && make lint` clean against the SoC.

## 3. Verification

- [ ] 3.1 Write `tests/cocotb_tests/test_ibex_alu_unit.py` — VPI-driven standalone instance, walks the per-operator scenarios from `specs/alu/spec.md`, asserts each output (`result_o`, `adder_result_o`, `comparison_result_o`, `is_equal_result_o`).
- [ ] 3.2 `pytest tests/cocotb_tests/test_ibex_alu_unit.py` green (signed/unsigned, SRA sign-fill, SLL shamt-mask, multdiv operand override, RV32B-disabled inert).
- [ ] 3.3 `pytest tests/test_cpu_programs.py` — all 4 ISR programs (timer/sw/ext/multictx) still pass.
- [ ] 3.4 `pytest tests/test_soc_lint.py` — SoC lint still clean.

## 4. Archive

- [ ] 4.1 Move `changes/port-ibex-alu/` → `changes/archive/YYYY-MM-DD-port-ibex-alu/`.
- [ ] 4.2 Materialize `specs/alu/spec.md` from the archived change's spec (first creation, no prior content to merge).
- [ ] 4.3 Update README "Status" line: A1 ✅, A2 next.
- [ ] 4.4 Single git commit with all the above; commit message references the proposal.
