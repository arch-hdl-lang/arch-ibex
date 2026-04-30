# Tasks: Port `ibex_multdiv_fast` to ARCH

A6 swap. First Phase A swap with a non-trivial multi-cycle FSM.

## Spec extraction (SV-only + neighbors agent) — DONE
- [x] `specs/multdiv/spec.md` (6528 words, 12 Requirements + Integration
      constraints + Enum encodings).
- [x] No spec-notes from extractor (5 permissive choices documented inline).

## Test authoring (spec-only agent) — DONE
- [x] `tests/cocotb_tests/test_ibex_multdiv_fast_unit.py` — basic, 12 tests.
- [x] `tests/cocotb_tests/test_ibex_multdiv_fast_unit_full.py` — full, 27 tests.
- [x] Pytest collectors for both.
- [x] `tests-inventory.md` — 12 bullets.
- [x] `spec-notes-tests.md` — 3 implementer-relevant interpretations
      (ALU adder views, equal-to-zero formula, lane-1 we strictness).

## Arch implementation (spec + basic-inventory only)
- [ ] Read spec + tests-inventory + spec-notes + spec-notes-tests + ARCH HDL
      Spec only. Forbidden: SV, test files, other arch files.
- [ ] Author `src/IbexMultdivFast.arch`.
- [ ] **Construct choice**: the FSM is well-defined; `fsm` is the natural
      fit. `thread` is also acceptable if the implementer prefers explicit
      yield points. Either way, the kernel datapath stays combinational.
- [ ] Use `unpacked Vec<UInt<34>, 2>` for `imd_val_q_i` / `imd_val_d_o`
      (mirrors A1's pattern for the same upstream port shape).
- [ ] Build clean: `make build` produces `build/ibex_multdiv_fast.sv`.

## Basic gate (blocking)
- [ ] `make test` — 18 existing + 1 basic + 1 full = 20 cases.
- [ ] All 4 ISR programs stay green (they use MUL/DIV in trap handlers).

## Background regression (non-blocking)
- [ ] Background agent runs `tests/test_ibex_multdiv_fast_unit_full.py`
      and classifies failures.

## Archive
- [ ] Move `changes/port-ibex-multdiv-fast/` to
      `changes/archive/2026-04-29-port-ibex-multdiv-fast/`.
- [ ] Materialize top-level `specs/multdiv/spec.md`.
- [ ] Single feature commit: `feat(A6): port ibex_multdiv_fast to ARCH`.
