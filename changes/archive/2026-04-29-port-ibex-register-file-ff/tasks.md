# Tasks: Port `ibex_register_file_ff` to ARCH

Tracking checklist for the A2 swap. Spec → implementation flow per
WORKFLOW.md (spec extracted by SV-only agent; arch implemented by
spec-only agent).

## Spec extraction (SV-only agent)
- [ ] Read `ibex_register_file_ff.sv` end-to-end.
- [ ] Author `changes/port-ibex-register-file-ff/specs/register_file_ff/spec.md`
      (Purpose / Port contract / Requirements / Notes).
- [ ] Cover all four parameters in the port contract; constrain in-scope
      requirements to default config (RV32E=0, DummyInstructions=0).
- [ ] Capture x0 hardwired-zero behaviour, async-active-low reset,
      concurrent read/write returning old value (no forwarding).

## Arch implementation (spec-only agent)
- [ ] Read the change spec + ARCH HDL spec only. Forbidden: any `*.sv`.
- [ ] Author `src/IbexRegisterFileFf.arch`. Module name `ibex_register_file_ff`.
- [ ] Doc comments cite spec sections, not SV lines.
- [ ] Build clean: `arch build` produces `build/ibex_register_file_ff.sv`.

## Integration
- [ ] `make build` — both `ibex_alu.sv` and `ibex_register_file_ff.sv` land
      under `build/`.
- [ ] conftest auto-shadow picks up the new swap (no conftest edits).
- [ ] Verilator lint stays clean: `pytest tests/test_soc_lint.py`.

## Gate
- [ ] `pytest tests/ -q` — 5 passed (1× lint + 4× CPU programs).

## Archive
- [ ] Move `changes/port-ibex-register-file-ff/` to
      `changes/archive/2026-04-29-port-ibex-register-file-ff/`.
- [ ] Materialize top-level `specs/register_file_ff/spec.md` from the
      change spec.
- [ ] Single commit: `feat(A2): port ibex_register_file_ff to ARCH`.

## Carry-overs / known gotchas
- `arch build` writes `.sv` next to source unless `-o` is set; Makefile
  handles this. Ad-hoc invocations need `-o build/`.
- Verilator UNUSED on `test_en_i` / `dummy_instr_*` is expected under
  the in-scope parameter values — match upstream's `unused_*` pattern
  in the spec so the implementer can carry it through.
