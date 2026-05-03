# A9 IbexLoadStoreUnit — implementation tasks

## Workflow steps

- [x] Step 1: Write `proposal.md` (construct enumeration: thread + bus + module picked)
- [x] Step 2: Dispatch spec-extractor agent → `specs/load_store_unit/spec.md` (13 Requirements)
- [x] Step 3: Dispatch test-author agent → basic + full cocotb suites, inventory
- [x] Step 4: Triage spec-notes — N/A (no spec ambiguities, agent did not create spec-notes.md)
- [x] Step 5: Write this tasks.md
- [x] Step 6: Write `src/IbexLoadStoreUnit.arch` (direct, spec-compliant; compiled OK with warnings only)
- [BLOCKED] Step 6a: Two-stage review (MANDATORY — 13 Requirements >> 3 threshold)
  - [x] Stage 1: spec-compliance reviewer — ran; found 3 FAIL (all design-bug root cause)
  - [x] Stage 2: design-quality reviewer — ran; confirmed 3 blocking design bugs
  - Step 6 complete; gating on arch-com PR fix for §7a.2 inter-yield dead-skid lowering.
- [BLOCKED] Step 7: Basic gate — blocked on step 6a restructure
- [BLOCKED] Step 8: Background regression — blocked on step 6a restructure

## Implementer agent constraints (spec-isolation rules)

The implementer agent MUST NOT read:
- `ibex_*.sv` files (SV isolation)
- `tests/cocotb_tests/test_load_store_unit_unit*.py` (test isolation)
- Any other `src/*.arch` files (spec-only)

The implementer MUST read:
- `changes/port-load_store_unit/specs/load_store_unit/spec.md`
- `changes/port-load_store_unit/tests-inventory.md`
- `arch-com/doc/ARCH_HDL_Specification.md` (§10 Bus, §11 Thread)
- `arch-com/doc/Arch_AI_Reference_Card.md`

## Key implementation notes (from proposal)

- Outer container: `module IbexLoadStoreUnit`
- Bus: define `BusObi` with OBI signals; LSU is initiator
- Thread: `LsuReq` implements req→gnt→rvalid sequencing with
  conditional misaligned split (dispatch-and-rejoin)
- Comb section: address alignment, byte-enable, write-data, read-data

## Syntax pitfalls to bake into implementer prompt

From `feedback_arch_syntax_pitfalls.md`:
1. Vec reset: `reset rst_ni => 0` (NOT `Vec::splat(...)`)
2. No `let LHS[idx] = ...`; use `comb` block for indexed LHS
3. Reset polarity on PORT TYPE: `port rst_ni: in Reset<Sync, Low>`
4. `domain SysDomain` block required at file scope
5. `counter` is a reserved keyword — use `cnt_q` etc.
6. `thread` dead-skid: output ports that thread drives drop to 0 during dead-skid cycles
7. `shared(or)` required on any port driven by multiple threads (or by thread + comb block)
8. `wait until cond; x <= expr;` merges `x <= expr` into the wait state guarded by `cond` (intentional compiler behaviour per elaborate.rs:2759). Use `do { if cond { x <= expr; } end if } until cond;` if the capture must fire at THIS condition's edge, not the next one.

## Two-stage review criteria

Step 6a is MANDATORY (13 Requirements). Review will check:
- Every Requirement in spec has coverage in the .arch
- `BusObi` bus definition is correct for OBI protocol signals
- `thread` wait-until conditions match spec scenarios
- Byte-enable/write-data/read-data comb logic matches spec tables
- No SV variable names leaked (`_q`/`_d` pattern is fine where register semantics require it)
- Doc comments cite `specs/load_store_unit/spec.md §<Requirement>` not `ibex_*.sv:LINE`
