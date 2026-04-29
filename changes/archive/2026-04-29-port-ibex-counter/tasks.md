# Tasks: Port `ibex_counter` to ARCH

A3 swap. First swap under the **TDD-first / split-gate** flow.

## Spec extraction (SV-only agent) — DONE
- [x] `specs/counter/spec.md` — 6 Requirements covering reset / increment /
      tied-zero high bits / write priority / half-word semantics /
      `ProvideValUpd` gating.

## Test authoring (spec-only agent) — DONE
- [x] `tests/cocotb_tests/test_ibex_counter_unit.py` — basic suite, 6 tests
      (one per Requirement), `CounterWidth=32, ProvideValUpd=1`.
- [x] `tests/cocotb_tests/test_ibex_counter_unit_full.py` — full regression,
      28 tests parametrized over the six `CounterWidth × ProvideValUpd` combos.
- [x] `tests/test_ibex_counter_unit.py` and `tests/test_ibex_counter_unit_full.py`
      — pytest collectors. 7 cases collected (1 basic + 6 parametrized full).
- [x] `tests-inventory.md` — basic-suite names + docstring summaries for the
      arch agent.
- [x] No `spec-notes.md` produced — spec is unambiguous.

## Arch implementation (spec + basic-inventory only)
- [ ] Read spec + tests-inventory + ARCH HDL Spec only. Forbidden: `*.sv`,
      test files, other `*.arch`.
- [ ] Author `src/IbexCounter.arch`.
- [ ] Build clean: `make build` produces `build/ibex_counter.sv`.

## Basic gate (blocking)
- [ ] `pytest tests/test_ibex_counter_unit.py tests/test_soc_lint.py tests/test_cpu_programs.py -q`
      must pass: 1 basic + 1 SoC lint + 4 ISR programs = 6 tests.

## Background regression (non-blocking, dispatched after basic gate)
- [ ] Background agent runs `pytest tests/test_ibex_counter_unit_full.py`
      and classifies any failures.

## Archive
- [ ] Move `changes/port-ibex-counter/` to
      `changes/archive/2026-04-29-port-ibex-counter/`.
- [ ] Materialize top-level `specs/counter/spec.md` from the change spec.
- [ ] Single feature commit: `feat(A3): port ibex_counter to ARCH`.
