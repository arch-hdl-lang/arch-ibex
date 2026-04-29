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
    │   ├── design.md              # OPTIONAL — only when an ARCH design
    │   │                          # decision needs justification
    │   └── tasks.md               # implementation checklist
    └── archive/                   # completed swaps, preserved for history
        └── YYYY-MM-DD-port-<module>/
```

## Per-swap workflow

The flow uses two **isolated agent invocations** to keep the spec honest:
the spec is written by an agent that sees only upstream SV; the `.arch`
is written by an agent that sees only the spec. The orchestrator (the
main session) wires the two together but never pastes SV snippets into
the arch agent's prompt.

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
   prefix). Subsequent revisions use delta format
   (ADDED/MODIFIED/REMOVED Requirements).
3. **Design** (optional) — only when a non-trivial ARCH design choice is
   made (e.g., "use `thread` not `fsm` for multdiv"). Skip for trivial swaps.
4. **Tasks** — write `changes/port-<module>/tasks.md` with hierarchical
   checkboxes.
5. **Implement (isolated agent — spec-only)** — dispatch a second `Agent`
   whose readable inputs are *only* the change spec from step 2,
   `arch-com/doc/ARCH_HDL_Specification.md`, and
   `arch-com/doc/Arch_AI_Reference_Card.md`. The agent **must not** read
   `ibex_*.sv`. It produces `src/<Module>.arch`. The orchestrator then
   builds, lints, and runs the gate.
6. **Gate** — `make build && make lint && make test` green; ISR cocotb
   suite + module-specific scenario tests pass.
7. **Archive** — move `changes/port-<module>/` to
   `changes/archive/YYYY-MM-DD-port-<module>/`; merge/append the change's
   `specs/<module>/spec.md` into the top-level `specs/<module>/spec.md`.

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
