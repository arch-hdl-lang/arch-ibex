# Tasks: Port `ibex_decoder` to ARCH

A4 swap. Largest leaf-module swap so far (1212 LoC SV). Authored under
the TDD-first / split-gate flow.

## Spec extraction (SV-only agent) — DONE
- [x] `specs/decoder/spec.md` (7140 words, 12 Requirements + Defaults
      subsection, full enum encoding tables for `alu_op_e`, `op_a_sel_e`,
      `op_b_sel_e`, `imm_a_sel_e`, `imm_b_sel_e`, `rf_wd_sel_e`,
      `csr_op_e`, `md_op_e`, `opcode_e`).
- [x] Two cosmetic prose-vs-hex inconsistencies fixed in triage
      (BCLR mnemonic at line 1239; CSRRW rd=0 hex at line 937).

## Test authoring (spec-only agent) — DONE
- [x] `tests/cocotb_tests/test_ibex_decoder_unit.py` — basic, 12 tests.
- [x] `tests/cocotb_tests/test_ibex_decoder_unit_full.py` — full, 135 tests.
- [x] Pytest collectors for both.
- [x] `tests-inventory.md` — basic-suite names + docstrings (no hex,
      no expected values).

## Arch implementation (spec + basic-inventory only)
- [ ] Read spec + tests-inventory + ARCH HDL Spec only. Forbidden: SV,
      test files, other arch files.
- [ ] Author `src/IbexDecoder.arch`.
- [ ] Build clean: `make build` produces `build/ibex_decoder.sv`.

## Basic gate (blocking)
- [ ] `pytest tests/test_ibex_decoder_unit.py tests/test_soc_lint.py tests/test_cpu_programs.py -q`
      must pass: 1 basic + 1 SoC lint + 4 ISR programs = 6 tests.
- [ ] Existing A1-A3 unit suites stay green
      (`pytest tests/test_alu_unit.py tests/test_register_file_ff_unit.py tests/test_ibex_counter_unit.py -q`).

## Background regression (non-blocking, dispatched after basic gate)
- [ ] Background agent runs `pytest tests/test_ibex_decoder_unit_full.py`
      and classifies any failures.

## Archive
- [ ] Move `changes/port-ibex-decoder/` to
      `changes/archive/2026-04-29-port-ibex-decoder/`.
- [ ] Materialize top-level `specs/decoder/spec.md` from the change spec.
- [ ] Single feature commit: `feat(A4): port ibex_decoder to ARCH`.
