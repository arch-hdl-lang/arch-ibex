# arch-ibex spec-driven workflow

Adapted from [OpenSpec](https://github.com/Fission-AI/OpenSpec) — structure
and format adopted, CLI tooling skipped.

## Directory structure

```
arch-ibex/
├── specs/                         # source of truth — port-contract behavior
│   └── <module>/
│       └── spec.md                # populated when a swap archives
└── changes/
    ├── port-<module>/             # active swap-in-progress
    │   ├── proposal.md            # intent, scope, ARCH constructs chosen
    │   ├── specs/                 # full or delta spec for this change
    │   │   └── <module>/
    │   │       └── spec.md
    │   ├── tests-inventory.md     # per-test names + docstrings (arch agent reads this)
    │   ├── spec-notes.md          # OPTIONAL — flagged spec ambiguities from test stage
    │   ├── design.md              # OPTIONAL — only when an ARCH design
    │   │                          # decision needs justification
    │   └── tasks.md               # implementation checklist
    └── archive/                   # completed swaps, preserved for history
        └── YYYY-MM-DD-port-<module>/
```

## Per-swap workflow

The flow uses **three isolated agent invocations** chained spec → tests →
arch, plus a fourth **background regression agent** that runs the full
test suite asynchronously after arch lands. The spec is written by an
agent that sees only upstream SV. The unit-test suite is written by an
agent that sees only the spec. The `.arch` is written by an agent that
sees only the spec plus the test **inventory** (function names +
docstrings, NOT assertion bodies). The orchestrator chains these stages
and never pastes upstream SV into stages 2/3 or test assertion code into
stage 3.

1. **Propose** — write `changes/port-<module>/proposal.md` (intent, scope,
   ARCH-construct choice, links to upstream `ibex_<module>.sv`). The
   orchestrator writes this directly — proposals are about ARCH-side
   choices, not bit-true behavior, so reading the SV header for the
   port list is fine.

2. **Spec (isolated agent — SV-only)** — dispatch an `Agent` whose
   readable inputs are *only* `~/github/ibex/rtl/ibex_<module>.sv` plus
   any required package (`ibex_pkg.sv`, etc.) and `prim_*` it depends on.
   The agent produces `changes/port-<module>/specs/<module>/spec.md`.
   First creation is just `## Requirements` (no ADDED/MODIFIED/REMOVED
   prefix). Subsequent revisions use delta format.

3. **Tests (isolated agent — spec-only, TDD stage)** — dispatch an
   `Agent` whose readable inputs are *only* the change spec from step 2
   plus the existing arch-ibex test infrastructure (`tests/test_alu_unit.py`
   etc. as a pattern reference). The agent produces:
   - `tests/cocotb_tests/test_<module>_unit.py` — **basic** suite, one
     `@cocotb.test` coroutine per spec **Requirement**, walking the
     single most representative scenario from the spec. Optimized for
     fast feedback: typical runtime ≤ 30 s for the full pytest
     collector.
   - `tests/cocotb_tests/test_<module>_unit_full.py` — **full
     regression** suite, walking *every* `#### Scenario:` from the
     spec plus edge cases the test agent identifies (boundary widths,
     all-zero / all-one operands, parameter sweeps when feasible).
   - `tests/test_<module>_unit.py` and `tests/test_<module>_unit_full.py`
     — pytest collectors that build Verilator on `build/<module>.sv`
     and invoke the matching cocotb module.
   - `changes/port-<module>/tests-inventory.md` — for the **basic**
     suite only: bullet list of test names + one-line docstring
     summaries. The arch agent reads this file. Assertion bodies stay
     hidden. The full-regression file is *not* listed here — keeping
     it out of the inventory means the implementer cannot accidentally
     overfit to it.
   - `changes/port-<module>/spec-notes.md` *(only if needed)* — flags
     spec ambiguities, contradictions, or under-specified scenarios
     the test agent could not resolve from spec alone. Orchestrator
     reviews this before stage 6.
   The tests run but fail at this stage (no `.sv` yet); they become
   the regression net once arch lands.

4. **Triage** *(only if step 3 produced `spec-notes.md`)* — orchestrator
   refines the spec, optionally reruns the test agent. Goal: enter
   step 6 with a spec the implementer cannot misinterpret.

5. **Tasks** — write `changes/port-<module>/tasks.md` checklist.

6. **Implement (isolated agent — spec + test-inventory only)** —
   dispatch a third `Agent` whose readable inputs are *only* the
   change spec from step 2, the **basic** test inventory from step 3,
   `arch-com/doc/ARCH_HDL_Specification.md`, and
   `arch-com/doc/Arch_AI_Reference_Card.md`. The agent **must not**
   read `ibex_*.sv`, the test files (`tests/cocotb_tests/test_<module>_unit*.py`),
   or any other `.arch` file. It produces `src/<Module>.arch`.

7. **Basic gate** *(blocking)* — `make build` then
   `pytest tests/test_<module>_unit.py tests/test_soc_lint.py tests/test_cpu_programs.py`.
   The basic-suite + SoC lint + 4 ISR programs must pass to continue.
   On failure: fix the arch (or escalate to spec triage if the test
   reveals genuine ambiguity).

8. **Background regression** *(non-blocking)* — once basic gate is
   green, dispatch a fourth `Agent` (run_in_background=true) tasked
   with running `pytest tests/test_<module>_unit_full.py` and
   triaging any failures. The orchestrator continues to step 9
   immediately. The regression agent reports back asynchronously:
   - **All green** → quiet acknowledgement, swap is fully verified.
   - **Failures** → the agent classifies each failure (arch bug
     vs. spec ambiguity vs. test bug), produces a focused report, and
     surfaces a `PushNotification`. The orchestrator pauses any
     in-flight work to triage.

9. **Archive** — move `changes/port-<module>/` to
   `changes/archive/YYYY-MM-DD-port-<module>/`; merge/append the
   change's `specs/<module>/spec.md` into the top-level
   `specs/<module>/spec.md`. The full-regression test file stays under
   `tests/cocotb_tests/` and runs as part of the standing gate going
   forward (i.e. `pytest tests/` is the post-archive verification).

## Spec format

Use RFC 2119 keywords (SHALL / MUST / SHOULD / MAY). Each requirement
gets one or more Given/When/Then scenarios. Cite upstream
`ibex_<module>.sv:LINE` as the bit-true reference inside scenario notes
where it disambiguates. The spec agent is the only stage that may cite
SV lines — `.arch` doc comments cite spec sections instead (see below).

```markdown
# <Module> Specification

## Purpose
One-paragraph description of what this module does in the Ibex pipeline.

## Port contract
| Direction | Name | Type | Description |
|---|---|---|---|
| in  | foo_i  | UInt<32> | Input foo |
| out | bar_o  | UInt<32> | Output bar |

## Requirements

### Requirement: <Name>
The module SHALL/MUST <observable behavior>.

#### Scenario: <Concrete case>
- GIVEN <inputs / state>
- WHEN <event>
- THEN <observable output>
- (ref: ibex_<module>.sv:LINE)
```

## Why this and not the upstream code as the spec

Upstream `.sv` is the bit-true reference but is implementation-shaped.
The port-contract spec captures **what behavior must hold across the
SV→ARCH swap** in a form that:

- A new contributor can read without first parsing 800 LoC of SV.
- A future ARCH refactor (e.g., switching `fsm` → `thread`) can be
  validated against without re-deriving intent from RTL.
- Test scenarios derive from directly (each `#### Scenario:` is a
  potential cocotb assertion).

The `.arch` source carries `///` front-matter doc comments for the
ARCH-side design rationale, citing **spec sections** (e.g.
`//! ref: specs/<module>/spec.md §"Adder always produces unconditional sum"`).
It must **not** cite `ibex_*.sv:LINE` — those references belong only in
the spec. This separation lets a future ARCH refactor work from the
spec alone without re-reading upstream SV. Different audiences, no
duplication.
