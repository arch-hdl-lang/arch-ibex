# Proposal: redesign IbexIcacheOutputStage from scratch

## Intent

Replace the current `src/IbexIcacheOutputStage.arch` (507 lines, three
failed redesign attempts) with a fresh implementation that meets the
mandatory performance bar in
`changes/2026-05-09-icache-output-stage-redesign/specs/output_stage/spec.md`
(P-OUT-1 through P-OUT-7).

The current implementation is the cumulative result of PR #46 / #49 /
#50 / #51 plus three failed 2026-05-09 redesign attempts. It is
correct on functional invariants but stuck at **1.74× upstream**'s
cycle count on `icache_bench` (30,701 vs 17,680). Three patch-on-patch
attempts to close the gap each introduced new bug surfaces because the
existing structure (registered `valid_q` + priority-chain seq with 5+
arms writing `addr_out_q`) is fundamentally not the right shape for the
target performance.

This proposal is "fresh start, not refactor." The existing block is
preserved as a fallback in `src/IbexIcacheOutputStage.arch.legacy` (or
in git history) and the new design is written greenfield against the
spec.

## Scope

**In scope:**
- New `src/IbexIcacheOutputStage.arch` (greenfield, ~250-350 LoC est.).
- Optional widening of the parent's port surface to expose any FB-side
  signals the new design needs (specifically: per-FB busy/addr/data
  needed for cycle-N IC1-hit-now-and-FB-merge muxing — but minimal
  parent change).
- Per-loop-instr instrumentation already in
  `tests/cocotb_tests/test_icache_bench.py` provides the perf gate.

**Out of scope:**
- FB allocator / lookup pipeline / bus master / coalesce logic
  (parent's responsibility, unchanged).
- IF-stage / id_stage / SoC bus model (unchanged).

## Architecture

The reference is **upstream Ibex's `rtl/ibex_icache.sv:1100-1196`**.
Mirror its structure exactly. Key invariants:

### 1. `output_addr_q` is the single source of truth
- One register, one source for advance: `branch_i | (ready_i & valid_o)`.
- No other arm writes `output_addr_q`.
- Increment by 2 (compressed `rdata_o[1:0]!=11`) or 4 (uncompressed) on
  the consume edge.

### 2. `valid_o` and `rdata_o` are purely combinational

```
output_valid = skid_complete_instr
             OR (data_valid AND data-alignment-OK AND no-skid-needed)

data_valid   = ic1_hit_covers_aoq OR fb_covers_aoq

line_data    = ic1_hit_covers_aoq ? hit_data_ic1 : selected_fb_data

beat_data    = addr_out_q[2] ? line_data[63:32] : line_data[31:0]

rdata_o      = skid_complete_instr ? {16'd0, skid_data_q}
             : skid_valid_q ? {beat_data[15:0], skid_data_q}
             : beat_data
```

### 3. `data_valid` source-merge is per-cycle-comb, not register-and-arbitrate

For each FB: `fb_covers_aoq[fb] = fb_busy[fb] AND fb_addr[fb][31:3] ==
addr_out_q[31:3] AND fb_has_beat_for_aoq[fb][2]`.

`fb_has_beat_for_aoq` is derived from `beats_rcvd_q[fb]`: beat 0
available when ≥1 beat received OR fill_hit (cache hit captured the
whole line at IC1 edge); beat 1 available when ≥2 beats received OR
fill_hit.

### 4. NO valid_q register

This was the trap of all three prior attempts. The IF-stage does NOT
require `valid_o` to be registered — upstream Ibex proves it works
combinationally. The cy4255 cy6 bugs in earlier attempts came from
incorrect data muxing, NOT from comb timing. Rule out the data
muxing bug FIRST by faithfully porting upstream's `output_data_lo` /
`output_data_hi` / `line_data_muxed` slice equations bit-for-bit
(`ibex_icache.sv:1147-1162`, `ibex_icache.sv:1175-1191`).

### 5. NO `out_beat_pending_q`, `ic1_fast_data_q`, `fast_path_addr_q`

These were patches around the structural problem. With a comb data
path indexed by `addr_out_q[2]`, beat-1 of a within-line delivery
trivially follows beat-0's consume edge — `addr_out_q[2]` flips, mux
selects the upper half, valid_o stays high. No state to capture.

### 6. Skid logic ports from upstream

`ibex_icache.sv:1095-1114` (skid_data_d, skid_valid_d, skid_en) defines
the cross-beat misaligned-32 reassembly. Port the equations directly.
The arch-ibex test `test_r_out_5` requires a non-upstream `err_plus2`
arm for "beat-1 err on misaligned-allocated FB" — preserve that as an
additive override on the upstream form.

### 7. `fb*_out_done_pulse` semantics

Fires on the consume edge that completes the FB's contribution
(beat 1 if both beats from FB; beat 0 if FB only owes beat 0 because
beat 1 came via skid-load). When IC1-hit-comb sources delivery and no
FB matches `addr_out_q`'s line, all `fb*_out_done_pulse` are 0.

## Risk register (lessons from prior attempts)

### Risk 1: IF-stage compressed-decoder timing flip
**Failure mode** (attempt #1): comb `valid_o` causes if_stage's
compressed decoder to sample a transient halfword at the IF→ID latch
edge. Smallest reproducer: `test_ibex_if_stage_unit_full::req5_compressed_instruction_expansion`.

**Mitigation**: this is NOT a comb-output timing problem in the abstract
— upstream Ibex uses comb output and `req5` passes upstream.
The bug was data-mux corruption (cy4255: `rdata_o=0x97` instead of
`0x000f0097`). Fix: faithfully port upstream's slice equations and
add a unit test that drives a single compressed instruction and
asserts `rdata_o` matches expected EVERY cycle until consume. If the
new test passes and the SoC `req5` passes, the timing is fine.

### Risk 2: FB-side / IC1-side data-source race
**Failure mode** (attempt #3): on the cycle of IC1 hit, both
`ic1_hit_covers_aoq` and `fb_covers_aoq[fb]` may be true (for the FB
just-allocated whose `data_we_ic1_hit` fires the same edge). Their
`line_data` outputs ARE coherent (both are the line bytes), but other
signals tied to the FB (err flags, beat-availability) might race the
IC1-side equivalents.

**Mitigation**: the spec's R-OUT-DATA-2 source-priority order (skid >
IC1-hit > FB-side) gives a deterministic answer. Implement the priority
strictly. For err signals, prefer the FB-side err flags (which are
registered after writeback) over IC1-comb (which doesn't have err).

### Risk 3: `addr_out_q` rollback after consume
**Failure mode** (attempts #2, #3): after consume advances `addr_out_q`
to the next line, a stale `lookup_addr_ic1_q` matches the priority-arm
condition and rolls `addr_out_q` BACK to the just-consumed line.

**Mitigation**: this risk is structurally eliminated by R-OUT-ADDR-4
(only consume/branch can write `addr_out_q`). The new design has no
arm that can roll back.

### Risk 4: Bus-passthrough `icache_enable_i=0` path
**Failure mode** (attempt #1): 5/10 cpu_program tests hung
(timer_isr, sw_isr, etc.) because the wholesale-comb redesign missed
upstream's rvalid-bypass: `fill_data_rvd[fb] ? instr_rdata_i : line_data_muxed`.
Without it, every bus-served beat takes 1 extra cycle to propagate
through `fill_data_q`.

**Mitigation**: implement upstream's `fill_data_rvd` term explicitly.
Add a unit test that drives `icache_enable_i=0`, `branch_i` to addr A,
bus serves beat 0 with pattern X, asserts `valid_o=1, rdata_o=X` on
the SAME cycle as `instr_rvalid_i=1` (or N+1 latest).

### Risk 5: Skid arbitration during sustained delivery
Upstream advances `fill_out_cnt_q[fb]` on every accepted beat,
including skid-load cycles where `valid_o=0` but the FB beat is
"consumed" for skid storage. The sub-block must signal these
skid-loads to the parent via a separate strobe (currently called
`fb_beat_consume_skid` in the legacy code).

**Mitigation**: preserve the existing strobe semantics. Document in
the spec (R-OUT-FB-DONE).

## Test strategy

### Unit-level (focused, fast)
Add to `tests/cocotb_tests/test_ibex_icache_unit.py` a NEW set of
`test_p_out_*` tests that specifically exercise the perf contracts:
1. `test_p_out_1_steady_state_throughput`: pre-warm 4 sequential
   lines; branch to first; serve `ready_i=1` continuously; verify
   each cycle produces a consume edge once delivery starts.
2. `test_p_out_2_within_line_beat1_zero_bubble`: pre-warm one line;
   branch to its base; consume beat-0; assert beat-1 delivered next
   cycle (no bubble).
3. `test_p_out_3_cross_line_one_bubble`: pre-warm 2 sequential lines;
   branch to upper half of first; consume; assert next-line delivery
   ≤2 cycles later.
4. `test_p_out_4_branch_to_hit_two_cycles`: pre-warm; branch_i pulse;
   assert valid_o asserts within 2 cycles.
5. `test_p_out_6_passthrough_throughput`: icache_enable=0; branch +
   bus-rvalid; assert valid_o on same cycle as rvalid.

### Integration-level (correctness + perf gate)
- `tests/test_ibex_icache_unit.py`: full R-OUT-* + R-FB-* + open-thread
  suite. 53 PASS / 0 FAIL / 3 pre-existing skip.
- `tests/test_ibex_icache_unit_full.py`: 58 PASS / 0 FAIL / 0 SKIP.
- `tests/test_cpu_programs.py::test_cpu_program[icache_bench]`:
  **`result_cycles ≤ 19,000`** (the perf gate per spec).
- `tests/test_cpu_programs.py` (full): 130 passed / 0 failed / 74 skipped.

## Implementation strategy

### Phase 1: Spec freeze
This document + the spec are reviewed and approved before any code is
written. Any deviation from the perf contract during implementation
flags either (a) the spec is wrong, or (b) the implementation is. Both
require the implementer to STOP and surface the issue.

### Phase 2: Greenfield write
Single agent task with a strict gate. Implement
`src/IbexIcacheOutputStage.arch` from scratch, mirroring upstream's
shape. Iterate via `icache_bench result_cycles` at every step. If
result_cycles plateaus above 19,000 the agent reports + we replan.

### Phase 3: Validation
Full SoC gate. If green, PR.

## Diff size estimate
- New: `src/IbexIcacheOutputStage.arch` (~300 lines, greenfield).
- Old: `src/IbexIcacheOutputStage.arch` deleted (~507 lines).
- Net: ~-200 lines (the legacy patches go away).
- Test additions: ~150 lines for `test_p_out_*` unit tests.

## What we are NOT doing
- We are NOT changing the parent `IbexIcache.arch` lookup pipeline /
  FB allocator / coalesce / bus master.
- We are NOT touching the IF-stage / id_stage / SoC bus.
- We are NOT carrying forward any patch from PR #46/#49/#50/#51 inside
  this sub-block. Those patches were structural workarounds; they
  become unnecessary with the new shape.

## Approval gate

This proposal is approved when the user signs off on:
1. The spec's perf contract (P-OUT-1..7).
2. The architecture sketch (sections 1-7 of "Architecture").
3. The validation gate (`result_cycles ≤ 19,000` + 130/0/74 SoC).

Implementation does NOT begin until approval.
