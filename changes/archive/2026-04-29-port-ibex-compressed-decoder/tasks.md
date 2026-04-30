# Tasks: Port `ibex_compressed_decoder` to ARCH

A5 swap. First swap fully under the **elaborated methodology** —
spec extractor reads neighbor blocks in BOTH directions
(see `feedback_unit_tests_dont_catch_integration.md`).

## Spec extraction (SV-only + neighbors agent) — DONE
- [x] `specs/compressed_decoder/spec.md` (6598 words, 30 Requirements)
      including a `## Integration constraints` section split into
      `### Consumer-side` and `### Producer-side`.
- [x] Spec-notes.md flags 3 permissive choices, none blocking:
      Zcmp FSM stability gating, illegal-path `instr_o` don't-care,
      Zcb/Zcmp helper-derived hex confidence (full-suite is the
      regression net).

## Test authoring (spec-only agent) — DONE
- [x] `tests/cocotb_tests/test_ibex_compressed_decoder_unit.py`
      — basic, 29 tests (one per Requirement).
- [x] `tests/cocotb_tests/test_ibex_compressed_decoder_unit_full.py`
      — full, ~80 tests (every spec scenario + parametric edges,
      especially explicit hex-pinning for Zcb/Zcmp encodings per
      spec-notes item 3).
- [x] Pytest collectors for both (built by orchestrator after the
      test agent ran out of API quota mid-run; collectors are
      mechanical mirrors of the basic-suite collector).
- [x] `tests-inventory.md` — derived from the basic-suite cocotb
      docstrings; arch agent reads this file only.

## Arch implementation (spec + basic-inventory only)
- [ ] Read spec + tests-inventory + ARCH HDL Spec only. Forbidden:
      `*.sv`, test files, other `*.arch`.
- [ ] Author `src/IbexCompressedDecoder.arch`.
- [ ] **Per spec-notes item 1**: pick option (a) — gate non-idle
      Zcmp FSM advance on `id_in_ready_i` alone (mirrors upstream RTL).
- [ ] Build clean: `make build` produces `build/ibex_compressed_decoder.sv`.

## Basic gate (blocking)
- [ ] `make test` — 16 existing + 1 basic + 1 full = 18 cases.
- [ ] All ISR programs stay green.

## Background regression (non-blocking)
- [ ] Background agent runs the full-suite + classifies failures.

## Archive
- [ ] Move `changes/port-ibex-compressed-decoder/` to
      `changes/archive/2026-04-29-port-ibex-compressed-decoder/`.
- [ ] Materialize top-level `specs/compressed_decoder/spec.md`.
- [ ] Single feature commit: `feat(A5): port ibex_compressed_decoder to ARCH`.
