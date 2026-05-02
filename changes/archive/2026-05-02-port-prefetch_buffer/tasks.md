# Tasks: Port ibex_prefetch_buffer (A8)

## Status: In progress

- [x] Step 1 — Write proposal.md (orchestrator, 2026-05-02)
- [ ] Step 2 — Spec extraction (SV-only isolated agent)
- [ ] Step 3 — Test authoring (spec-only isolated agent)
- [ ] Step 4 — Triage spec-notes.md (if generated)
- [ ] Step 5 — Finalize tasks.md
- [ ] Step 6 — Arch implementation (spec + inventory isolated agent)
- [ ] Step 6a — Two-stage review (mandatory: spec has ≥3 Requirements)
  - [ ] Stage 1: spec-compliance reviewer
  - [ ] Stage 2: design-quality reviewer
- [ ] Step 7 — Basic gate: `pytest tests/test_prefetch_buffer_unit.py tests/test_soc_lint.py tests/test_cpu_programs.py`
- [ ] Step 8 — Background regression: `pytest tests/test_prefetch_buffer_unit_full.py`
- [ ] Write READY.md

## Key constraints

- Two-stage review (step 6a) is MANDATORY — prefetch buffer spec will have ≥3 Requirements.
- Compiler bugs: stop and write BLOCKED.md if arch-com is the root cause.
- 3-strike rule: stop after 3 failed fix attempts revealing new symptoms each time.
- Do NOT archive (step 9) — parent orchestrator handles archive after A8 and A9 both finish.
- `HANDOFF.md` must NOT be committed (it's .gitignored).
