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
   ARCH-construct choice, **construct enumeration**, links to upstream
   `ibex_<module>.sv`). The orchestrator writes this directly —
   proposals are about ARCH-side choices, not bit-true behavior, so
   reading the SV header for the port list is fine.

   **Construct enumeration** *(REQUIRED subsection)* — list every
   first-class ARCH construct (`module`, `fsm`, `thread`, `fifo`,
   `ram`, `cam`, `linklist`, `regfile`, `arbiter`, `counter`,
   `pipeline`, `synchronizer`, `clkgate`) and for each one note one
   of: **picked** / **rejected (one-sentence reason)** / **N/A
   (out-of-shape)**. Reference: §8-§12 of
   `arch-com/doc/ARCH_HDL_Specification.md`; §12.10 ("linklist vs
   fifo vs ram — When to Use Which") is the triage cheat-sheet.

   This is a forcing function, not box-ticking. Without it the
   orchestrator (and the implementer agent dispatched downstream) defaults
   to "plain `module`" because that's what the prior swap used —
   even when a first-class construct would carry half the design for
   free. Methodology lesson from A7 IbexFetchFifo: the `fifo`
   construct didn't fit, but that conclusion was never written down,
   so a future reader can't tell "considered, doesn't fit" from "never
   considered." See
   [Proposal format](#proposal-format) for the canonical layout.

   **Spec ambiguity resolutions** *(REQUIRED subsection when the spec
   flags any ambiguity)* — for each item in the spec's
   `## Spec ambiguities flagged` (or `spec-notes.md` from a prior
   stage), the proposal MUST commit to one reading with rationale.
   Test author and arch implementer cite the proposal's resolution,
   not the spec's punt. Without this, tests get written under one
   reading and the implementation under another — both spec-conformant
   but incompatible. Methodology lesson from D1 IbexIcache:
   spec ambiguity #3 (R-LK-4 strengthened-vs-permissive) was left
   open in the spec; tests assumed strengthened, impl chose
   permissive, the integration silently broke at SoC boot. The
   ambiguity-resolution table makes both stages aim at the same
   target.

2. **Spec (isolated agent — SV-only)** — dispatch an `Agent` whose
   readable inputs are *only*:
   - `~/github/ibex/rtl/ibex_<module>.sv` plus any required package
     (`ibex_pkg.sv`, etc.) and `prim_*` it depends on.
   - **`~/github/ibex/doc/03_reference/<module>.rst`** (when one exists)
     and any related higher-level reference pages (e.g. `pipeline_details.rst`,
     `instruction_decode_execute.rst`). These capture upstream's intent
     and rationale at a level the SV alone doesn't, and are still
     "upstream documentation" — including them in the spec stage
     improves capture quality without breaking spec-first isolation.
   - **The immediate neighbor modules in both directions** —
     producer modules driving this module's input ports, and
     consumer modules sampling its output ports. The spec extractor
     reads these specifically to identify *integration constraints*:
     - **Consumer side**: "this output must be 0/1 in case X because
       the consumer does Y" (e.g. decoder's `rf_we_o` for LOAD must
       stay 0 because `wb_stage` OR-combines `rf_we_id` and
       `rf_we_lsu`; a stuck-1 corrupts loaded data).
     - **Producer side**: "this input is only meaningful when X"
       (e.g. decoder's `branch_taken_i` is only consumed on the
       second cycle of a BRANCH; on other cycles the value is
       don't-care and may glitch).
     The spec MUST capture these in a `## Integration constraints`
     section so downstream stages don't violate them. This is the
     methodology lesson from A4 — see
     `feedback_unit_tests_dont_catch_integration.md` in memory.
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
     **MUST include "cross-scenario interaction" tests** — explicit
     cocotb tests for combinations of two or more `#### Scenario:`
     sections that overlap in time (e.g. branch-during-cold-boot,
     lookup-during-fill-write, inval-during-output-drain). One
     test per Scenario is insufficient; integration bugs hide in
     the overlaps. Methodology lesson from D1 IbexIcache: the SoC
     boot path exercises §S1 (cold-boot walk) ∩ §S2 (first-branch
     miss-fill); no single-Scenario test caught the asymmetric
     `lookup_grant` bug because the unit suite always
     `_wait_until_idle()`'d before the first branch. A
     `test_<module>_boot_during_cold_init` that mirrors the SoC's
     reset → first-cycle branch → req sequence (no
     `_wait_until_idle()`) is REQUIRED for any module the CPU
     fetches through.
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

6a. **Two-stage review** *(conditional — opt-in for non-trivial swaps)* —
    if the module's spec has **≥ 3 Requirements**, the orchestrator
    MUST run two review subagents on the implementer's output BEFORE
    the basic gate (step 7). Adopted from
    [`superpowers:subagent-driven-development`](https://github.com/obra/superpowers).

    The threshold (≥ 3 Requirements) is the cost / payoff line: leaf
    modules with 1–2 Requirements (`IbexCounter`, `IbexAlu`) are
    cheap enough that runtime tests catch divergence faster than two
    review round-trips. Modules with 3+ Requirements (`IbexDecoder`,
    `IbexCompressedDecoder`, all of Phase B/C) have enough surface
    that an implementer can satisfy individual Requirements while
    silently violating an interaction between two of them — the A4
    `rf_we_o = 1` LOAD bug was exactly this shape.

    **Stage 1 — spec-compliance reviewer (isolated agent).** Inputs:
    - The change's `specs/<module>/spec.md`.
    - The implementer's `src/<Module>.arch` output.
    - `arch-com/doc/ARCH_HDL_Specification.md` (so it can identify
      construct-level mistakes; the reviewer does not need to know
      arch-com internals).

    The reviewer reads the `.arch` and verifies, line by line, that
    every spec Requirement is covered AND no behavior outside the
    spec was introduced. **AND** runs a **construct-compliance
    audit**: for each construct pinned in the proposal's `##
    Construct enumeration` table as **picked**, verify the `.arch`
    actually instantiates / uses it. If a pinned construct was
    silently substituted (e.g. reg-encoded SM in place of `fsm`,
    inline Vec arrays in place of `thread`), the reviewer MUST flag
    it as a *misinterpreted* issue with the proposal's choice as
    the spec section reference. Methodology lesson from D1
    IbexIcache: the implementer used a `UInt<2>` reg + comb
    next-state SM instead of `fsm InvalCtrl`, and inline Vec arrays
    instead of `thread fill` — both functionally equivalent SV but
    silent proposal-deviations that defeated Phase D's
    construct-exercise goal. The audit catches this before the
    basic gate.

    Returns:
    - **✅ spec compliant**, OR
    - **❌ issues found**: bullet list per issue, citing
      `spec.md §<Requirement>` AND `<Module>.arch:<line>`. Categories:
      *missing* (Requirement not implemented), *extra* (behavior the
      spec doesn't authorize), *misinterpreted* (Requirement covered
      with wrong semantics, OR pinned construct silently substituted).

    The reviewer MUST NOT modify the `.arch`. On `❌`, the
    orchestrator dispatches the implementer subagent again with the
    issue list as input, then re-runs Stage 1. Loop until ✅.

    **Stage 2 — design-quality reviewer (isolated agent).** Only
    runs after Stage 1 passes. Inputs:
    - The implementer's `src/<Module>.arch` output (now spec-compliant).
    - `~/.claude/projects/-Users-<user>-github-arch-ibex/memory/feedback_arch_syntax_pitfalls.md`
      (the pitfall list — the reviewer flags any matched anti-pattern).

    The reviewer verifies ARCH-side design quality:
    - Is each `let` / `wire` / `reg` named for its purpose, not
      its SV ancestor (no leaked `_q`/`_d` SV idiom unless the
      construct mandates it)?
    - Is the construct choice (`fsm` vs `thread` vs flat `seq`)
      appropriate for the spec's complexity? Flag obvious
      over-engineering.
    - Does the source carry `///` doc comments citing
      `specs/<module>/spec.md §<Requirement>` (not `ibex_*.sv:LINE`)?
    - Any matches against the syntax-pitfalls list?

    Returns:
    - **✅ design clean**, OR
    - **❌ issues found**: bullet list (Critical / Important / Minor)
      with `<Module>.arch:<line>` references.

    The reviewer MUST NOT modify the `.arch`. On `❌` for Critical
    or Important issues, orchestrator re-dispatches the implementer.
    Minor issues are noted but don't block the basic gate.

    Both reviewers MUST NOT read the failing test file (`test_<m>_unit.py`)
    or the cocotb assertion bodies — that's runtime verification's job.
    Reviewer-stage isolation prevents the orchestrator from accidentally
    feeding test-driven implementation hints back through the review loop.

    **Skip 6a entirely** if the spec has < 3 Requirements. Note the
    skip in the swap's `tasks.md` so future readers see the threshold
    decision was applied, not forgotten.

7. **Basic gate** *(blocking)* — `make build` then
   `pytest tests/test_<module>_unit.py tests/test_soc_lint.py tests/test_cpu_programs.py`.
   The basic-suite + SoC lint + 4 ISR programs must pass to continue.

   **On failure**, the orchestrator MUST NOT immediately fix the arch
   or work around the failure. Instead, dispatch a **failure-triager
   agent** (see step 7a) FIRST. The triager classifies the failure
   into compiler-bug / design-bug / unclear with a minimal repro.
   This rule exists because Phase A repeatedly burned hours on
   refactors-around-compiler-bugs that turned out to need an
   arch-com fix anyway — and after fixing arch-com, the refactor was
   wasted work.

7a. **Failure triage (isolated agent)** — when step 7 (or any later
    step) fails, dispatch an `Agent` whose readable inputs are *only*:
    - The failing `.arch` source file
    - The verbatim error / diagnostic message (compiler error, lint
      error, or cocotb assertion text + log tail)
    - The failing test (cocotb body) if the failure was at test stage
    - `arch-com/doc/ARCH_HDL_Specification.md`
    - `~/.claude/projects/-Users-<user>-github-arch-ibex/memory/feedback_arch_syntax_pitfalls.md`
      (known traps — first-pass match against this list)

    The agent has Bash + Read + Write to a scratch dir. It iteratively
    reduces the input by deleting unrelated declarations, simplifying
    expressions, and substituting smaller widths/types — re-running
    `arch build` (or whichever command failed) after each step — until
    further reduction makes the error go away. Floor: ≤ 20 LoC.

    The agent returns a structured report:
    1. **Minimal repro** — verbatim ≤ 20 LoC `.arch` source.
    2. **Error reproduced** — verbatim error text from running the
       failing command on the minimal repro.
    3. **Classification** — one of:
       - `compiler bug` — the minimal repro is legal ARCH per
         `ARCH_HDL_Specification.md` but compiler rejects it OR
         lowers it incorrectly. Cite the spec section.
       - `design bug` — the minimal repro violates a documented
         language rule. Cite the rule (spec section or
         feedback_arch_syntax_pitfalls.md item).
       - `unclear` — neither classification fits cleanly. State why.
    4. **Suggested next action** — one of:
       - `compiler bug` → file an arch-com issue with this minimal
         repro (orchestrator does the filing, not the triager).
       - `design bug` → which line of the original `.arch` to fix,
         and the corrected snippet (NOT applied — orchestrator
         applies after review).
       - `unclear` → ask user.

    The triager MUST NOT modify the original `.arch`. MUST NOT file
    issues itself. MUST NOT propose architectural refactors — only
    point fixes for `design bug`. Its single job is to compress the
    failure into a triage-ready artifact so the orchestrator can
    decide compiler-vs-design without iterating in main context.

    The orchestrator then either: files an arch-com issue (and pauses
    for fix), applies the suggested point fix (after spot-check), or
    escalates to user.

    **3-strike escalation rule** (adopted from
    [`superpowers:systematic-debugging`](https://github.com/obra/superpowers)):
    if three independent fix attempts on the same module have failed
    — each one revealing a new symptom in a different place rather
    than fully resolving the issue — STOP. Do not attempt a fourth
    fix. The pattern is *architectural*, not local. Question the
    construct choice (FSM vs thread, single-block vs split, this
    abstraction vs that one) and surface a discussion to the user
    before proceeding. This rule exists because A6 burned three
    refactor cycles (FSM → 4 threads → 1 thread + dispatch-rejoin)
    treating a structural problem as a sequence of local fixes.

8. **Background regression** *(non-blocking)* — once basic gate is
   green, dispatch a fourth `Agent` (run_in_background=true) tasked
   with running `pytest tests/test_<module>_unit_full.py` and
   triaging any failures. The orchestrator continues to step 9
   immediately. The regression agent reports back asynchronously:
   - **All green** → one-line acknowledgement, swap is fully verified.
   - **Failures** → the agent MUST return a structured report so the
     orchestrator can act without re-running tests. The report has
     **one block per failing test** containing exactly:
     1. **Test name** — fully-qualified pytest node ID, e.g.
        `tests/test_<module>_unit_full.py::test_decoder_full[ALU_ADD]`.
     2. **Failure mode** — one of `arch bug` / `spec ambiguity` /
        `test bug` / `unclear`, with one sentence on why.
     3. **Concrete repro** — the assertion text + the actual vs
        expected values (e.g. `assert int(dut.result_o.value) == 0xF800_0000 — got 0x0800_0000`).
     4. **Cocotb log tail** — last ~30 lines of the cocotb stderr
        for that test (the section between `running test ...` and
        the FAIL line). Do NOT paste the full log — only the tail
        starting at the test's own banner.
     5. **Suggested next action** — which file the orchestrator
        should look at first (arch source line, spec section, test
        line). One-liner.

     The regression agent MUST NOT propose fixes or attempt to edit
     files; its job is to compress the failure into a triage-ready
     report. Surface the report via `PushNotification` so the
     orchestrator can pause in-flight work.

     **When the regression agent reports multiple failures with
     unrelated root causes** (different requirements, different
     subsystems, no shared symptom), the orchestrator MUST dispatch
     one failure-triager subagent PER failure in a single message —
     not serially. Adopted from
     [`superpowers:dispatching-parallel-agents`](https://github.com/obra/superpowers):
     independent investigations should run concurrently. Sequential
     triage of independent failures is exactly the kind of waste
     that makes Phase B/C composite swaps slow.

     For each failure the regression agent classifies as `arch bug`
     or `unclear`, the orchestrator (on resume) dispatches the
     **failure-triager** (step 7a) to produce a minimal repro + final
     classification before deciding whether to file an arch-com
     issue or fix the design.

9. **Archive** — before archiving, the orchestrator MUST satisfy a
   **fresh-evidence gate** (adopted from
   [`superpowers:verification-before-completion`](https://github.com/obra/superpowers)):

   - Re-run `make test` *in the current message* and paste the tail
     showing total / pass / fail counts. Stale runs from earlier in
     the session don't count — the gate is about evidence the
     orchestrator can cite NOW, not "tests passed an hour ago."
   - The archive step's commit message MUST quote that fresh count
     (e.g. "26 passed, 5 errors (rdl2arch import; pre-existing)")
     so future readers see the verification evidence inline.

   Then move `changes/port-<module>/` to
   `changes/archive/YYYY-MM-DD-port-<module>/`; merge/append the
   change's `specs/<module>/spec.md` into the top-level
   `specs/<module>/spec.md`. The full-regression test file stays under
   `tests/cocotb_tests/` and runs as part of the standing gate going
   forward (i.e. `pytest tests/` is the post-archive verification).

## Proposal format

```markdown
# Proposal: Port `ibex_<module>` to ARCH

## Intent
One paragraph: what this swap replaces, what depth in the pipeline,
which prior swap (Aₙ) it follows.

## Scope
**In scope** — list parameter values fixed in the SoC, behaviors
covered. **Out of scope** — parameter modes / variants the swap
explicitly does not address.

## Construct enumeration
Tabular dismissal of every first-class construct. One row per
construct from §8-§12 of the ARCH HDL spec. Status is one of
**picked** / **rejected: <one-sentence reason>** / **N/A**.

| Construct      | Status | Reason |
|----------------|--------|--------|
| `module`       | picked | Bespoke output mux + state — handle directly. |
| `fsm`          | rejected | No multi-cycle state-machine sequencing. |
| `thread`       | rejected | No mid-walk yield / wait-cycle behavior. |
| `fifo`         | rejected | `pop_data` exposes only the head; this module reads head+next+bypass simultaneously and has no clear port. |
| `ram` / `cam`  | N/A | Not address-indexed access. |
| `linklist`     | N/A | Not pointer-chained storage. |
| `regfile`      | N/A | Not multi-port register array. |
| `arbiter`      | N/A | Not request-grant arbitration. |
| `counter`      | N/A | Not a freestanding count primitive. |
| `pipeline`     | rejected | Bespoke alignment shouldn't ride a generic stage chain. |
| `synchronizer` | N/A | Single clock domain. |
| `clkgate`      | N/A | No clock gating. |

(Adapt `picked` / `rejected` per swap. The point is to write down the
dismissal, not to use these specific reasons.)

## Spec ambiguity resolutions
*(REQUIRED when the spec flags any item under `## Spec ambiguities
flagged` or a prior stage produced `spec-notes.md`.)* For each
ambiguity, commit to one reading with rationale. Test author and arch
implementer cite this table, not the spec's punt.

| Ambiguity (spec §) | Picked reading | Rationale |
|---|---|---|
| `R-LK-4` strengthened-vs-permissive | strengthened: same-line lookups MUST coalesce via FillBufferCam | Tests bind to the strict contract; `cam` is the construct exercise. |
| ... | ... | ... |

## Approach
What ARCH constructs / regs / wires the implementer is expected to
use. Tentative — the implementer agent has the final call.

## Verification gate
Pass criteria for the basic gate + scope of the full regression.

## Verification gate caveats
Anything non-obvious about how to wire the testbench (e.g. shared-port
modules need an external mock driver, combinational outputs need
`Timer(1, "ns")` settle).

## Reference
Upstream path + LoC, neighbor producer + consumer module names + line
ranges, related reference doc.
```

## Spec format

Use RFC 2119 keywords (SHALL / MUST / SHOULD / MAY). Each requirement
gets one or more Given/When/Then scenarios. Cite upstream
`ibex_<module>.sv:LINE` as the bit-true reference inside scenario notes
where it disambiguates. The spec agent is the only stage that may cite
SV lines — `.arch` doc comments cite spec sections instead (see below).

When the spec lists items under `## Spec ambiguities flagged`, each
SHOULD include a `> Resolution: <picked reading or "punt to
proposal">` line so downstream stages cannot accidentally pick
opposite readings. If the spec agent cannot resolve, the proposal MUST
(see step 1's "Spec ambiguity resolutions" subsection). Methodology
lesson from D1 IbexIcache: punting an ambiguity all the way to the
implementer leaves the test author working under a different reading;
both stages produce locally-consistent output that fails to compose.

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
