# 12 — The icache arbiter handshake violation (TASK2 Phase 2)

**Status: diagnosis complete (§1–6); fix and follow-ups approved and applied (§7); gate green on the design suites with assertions on (§8).**

## 1. What fires

With assertions enabled (Verilator 5.048 default), every CPU program
stops at 140 ns:

```
%Fatal: fb_age_arb.sv:75: Assertion failed in
  ibex_mini_soc.u_ibex.u_ibex_top.u_ibex_core.if_stage_i.icache.bus_arb.g_auto_hs_request[2]._auto_hs_request__lane_valid_stable:
  HANDSHAKE VIOLATION (valid must stay asserted until ready)
```

The assertion is the compiler's Tier-2 property for a `valid_ready`
channel, `(valid && !ready) |=> valid` (arch-com spec §18a.4). It is
attached to lane 2 of `FbAgeArb bus_arb`, the age-ordered arbiter that
picks which fill buffer (FB) may drive the instruction bus
(`src/IbexIcache.arch:707-720`; lane *i* = FB *i*). The arbiter's
request port is declared `handshake_channel request[NUM_REQ]: receive
kind: valid_ready` (`src/FbAgeArb.arch:55`), `request[i].valid` is wired
to `fb_wants_bus[i]`, and the `ready` outputs are wired to
`bus_ready_0..3` wires that nothing reads — the port uses the arbiter's
`grant_valid` / `grant_requester` outputs instead.

## 2. Cycle-level trace of the event

Captured from a traced build of the SoC running `timer_isr`
(`<scratch>/wave/dump.vcd`, 10 ns clock, icache signals under
`…if_stage_i.icache`):

| t (ns) | `branch_i` | `icache_enable_i` | busy FBs | `fb_wants_bus` | arbiter pick | `stale_q` | `alloc_q` | note |
|---|---|---|---|---|---|---|---|---|
| 80 | 1 | 0 | – | 0000 | – | 0000 | 0000 | boot branch to 0x0010_0080 |
| 90–110 | 0 | 0 | FB0, FB1, FB2 | 0001 → 0011 | FB0 | 0000 | 0000 | sequential prefetch allocates one FB per cycle; FB0 fetching |
| 120 | **1** | 0 | FB0–FB3 | 0110 (FB1, FB2) | FB1 (granted, `instr_gnt_i`=1) | 0000 | 0000 | first instruction is a jump → `branch_i` to 0x0010_0100; FB3 allocated for the target; **FB2 has valid=1, ready=0** |
| 130 | 0 | 0 | FB0–FB3 | **1000** (FB3 only) | FB3 | 0111 | 0000 | FB0–FB2 marked stale; **FB2 withdrew its request without ever being granted** |
| 140 | | | | | | | | assertion evaluates `|=>` and fails for lane 2 |

Two facts decide the classification: the cache is **disabled** at
boot (`icache_enable_i = 0` throughout, so `alloc_q = 0000`: no FB is
allocating into the cache), and the retraction is caused by
`stale_q[2]` being set by the branch. In the port,
`wants_bus_v[fb] = (phase == 3) and not hit and (beats_sent != total)
and not stale and not err` (`src/IbexIcache.arch:845-847`).

## 3. Does upstream do the same?

Yes. Upstream Ibex (`~/github/ibex/rtl/ibex_icache.sv`, commit
`eede2fb`):

- The per-FB bus request is a combinational level, re-evaluated every
  cycle: `fill_ext_req[fb] = fill_busy_q[fb] & ~fill_ext_done_d[fb]`
  (line 755).
- It is cancelled by a branch when the line is not being cached:
  `fill_ext_done_d[fb] = (… | (~fill_cache_q[fb] & (branch_i |
  fill_stale_q[fb] | …))) & ~fill_ext_hold_q[fb] & fill_busy_q[fb]`
  (lines 766-774, comment: "cancel if the line won't be cached and it
  is stale"). With the cache disabled `fill_cache_q = 0`, so in the
  traced scenario upstream drops FB2's request **in the same cycle as
  `branch_i`** (one cycle earlier than the port, which waits for the
  registered `stale_q`).
- Arbitration among FBs is a pure priority pick with no handshake:
  `fill_ext_arb[fb] = fill_ext_req[fb] & ~|(fill_ext_req &
  fill_older_q[fb])` (line 841). A request that disappears before being
  picked is simply never served. Nothing in upstream requires
  `fill_ext_req[fb]` to persist until `fill_ext_arb[fb]`.
- Only the **external** request is held: `fill_ext_hold_d[fb] =
  (fill_alloc & fill_spec_hold) | (fill_ext_arb[fb] & ~instr_gnt_i)`
  (763-764) and the `~fill_ext_hold_q` term above forbid cancelling the
  FB that is currently waiting for `instr_gnt_i`. This implements the
  bus rule in `doc/03_reference/instruction_fetch.rst:53-55`
  ("`instr_req_o` must stay high until `instr_gnt_i`"). The port's spec
  carries this as R-EXT-2 and, for the internal cancellation, R-FB-6
  ("remaining external requests MAY be cancelled early when the FB is
  stale and non-allocating, or on an IC1 hit", `specs/icache/spec.md:249-252`).

## 4. Classification

**(a)** — the port faithfully reproduces upstream behaviour at this
interface. Upstream's FB→bus arbitration is a level-sensitive request
mask with a priority pick; requests are legitimately withdrawn (stale +
non-cacheable, IC1 hit, error). The compiler's `valid_ready` Tier-2
contract ("valid must stay asserted until ready") describes AMBA-style
streaming with backpressure, which is not the protocol this design
uses. The `ready` outputs are not even consumed by the port.

Consequence for the reviewer package: the 0/10 result in
`02-functional.md` is an interface-declaration mismatch, not a
functional bug; with the checker disabled the port matches upstream on
all 74 architectural tests.

## 5. Two related observations (not the trigger; recorded for follow-up)

1. **Stale but cacheable lines.** Upstream cancels a stale FB's
   remaining bus beats only when the line will *not* be cached
   (`~fill_cache_q`); a cacheable stale line is fetched to completion
   and written back, so a branch does not waste the prefetch. The port's
   `wants_bus_v` drops on `stale_q` regardless of `alloc_q`, and its
   write-back needs all beats, so a cacheable line interrupted by a
   branch is never installed. This does not affect architectural
   results (arch tests pass) but changes bus traffic and hit rate with
   the cache enabled. R-FB-6 permits early cancel only for
   "stale **and non-allocating**". Candidate for a separate fix; not part
   of Phase 2 unless requested.
2. **External hold.** Upstream refuses to cancel the FB that is holding
   an ungranted `instr_req_o` (`~fill_ext_hold_q`). The port has no such
   guard (`instr_req_o = bus_grant_valid`, `src/IbexIcache.arch:1102`),
   so if the granted FB went stale while `instr_gnt_i` was low,
   `instr_req_o` would drop before grant — an R-EXT-2 violation. Not
   exercised here (`soc/ibex_mini_soc.sv:127` grants every request in
   the same cycle) and not caught by the existing unit test
   `test_r_ext_2_instr_req_addr_stable_until_gnt`, which holds `gnt` low
   without a branch. Latent; candidate for a unit test plus fix.

## 6. Proposed fix for (a), and what the trial found

Per TASK2, the fix for (a) is to declare the arbiter's request channel
with the variant that matches the real protocol. The spec's catalog
(§18a.2) has `valid_only` — "every cycle with valid = H is a transfer",
no ready, and (§18a.4) no Tier-2 assertion — which is exactly a
level-sensitive request that may be withdrawn.

Proposed source change (not applied):

```diff
--- a/src/FbAgeArb.arch
-  handshake_channel request[NUM_REQ]: receive kind: valid_ready
+  handshake_channel request[NUM_REQ]: receive kind: valid_only
--- a/src/IbexIcache.arch
-  wire bus_ready_0: Bool; wire bus_ready_1: Bool;
-  wire bus_ready_2: Bool; wire bus_ready_3: Bool;
-  wire wb_ready_0:  Bool; wire wb_ready_1:  Bool;
-  wire wb_ready_2:  Bool; wire wb_ready_3:  Bool;
   (and the eight `request[i].ready -> …_ready_i;` connections in
    `inst bus_arb` and `inst wb_arb`)
```

`RamPortArb` (`src/RamPortArb.arch:13`) keeps `valid_ready`; its
assertion never fired.

Trial on a scratch copy with the pinned compiler
(`<scratch>/trial2`): the port compiles (23/23), the generated
`fb_age_arb.sv` has no assertion and no `request_ready` port — but it
still contains `request_ready = grant_onehot;` in its `always_comb`
(`<scratch>/trial2/build/fb_age_arb.sv:63`), so Verilator fails with
`Can't find definition of variable: 'request_ready'`. **That is a second
arch-com bug**: the `arbiter` lowering emits the ready assignment
unconditionally instead of only for variants that have a ready signal.
It is internal (no language-surface change) and blocks the intended
fix on the current pin.

Options for the go-ahead:

| # | Path | What changes | Pin |
|---|---|---|---|
| A | Fix arch-com's arbiter lowering (skip the `request_ready` assignment for `valid_only`), add a regression test, PR it, and fold the patch into the pinned build like the stub fix | arch-com + the 2-file port change above | v0.71.0 + 2 patches |
| B | Keep `valid_ready` on the port and document the assertion as a known false positive of the compiler's contract | nothing in `src/`; the full gate in Phase 2.4 then cannot run with assertions on, which TASK2 forbids | unchanged |
| C | Restructure the port so `wants_bus` is held until the arbiter picks it (a "sticky request" register per FB) | port logic diverges from upstream (delays cancellation by up to the arbitration latency); not (a)-appropriate | unchanged |

Recommendation: **A**.

## 7. Decision and implementation (2026-09-04)

Repo owner chose **A**, and asked that both §5 items be fixed too,
with diffs shown before applying and the icache unit suites rerun
before the full gate.

### 7.1 Compiler side

arch-com PR [#994](https://github.com/arch-hdl-lang/arch-com/pull/994)
(branch `fix/arbiter-valid-only-ready`, CI green): when the request
channel exposes no ready signal, the arbiter emitter declares the
per-requester ready one-hot as an internal `logic [N-1:0]` wire, so the
existing grant emitters stay uniform and the SV elaborates. Regression
test `test_arbiter_valid_only_request_channel_keeps_internal_ready`
(no ready port, internal wire, no Tier-2 SVA, Verilator lint clean).
The same fix is folded into the pinned build
(`reports/arch_com_v0.71.0_arbiter_valid_only_fix.patch`); the pin is
now arch-com `fa4c864f` = v0.71.0 + 2 patches (`10-toolchain.md`).

### 7.2 Port side — what the trial runs found

All work was done on a scratch copy of `src/` and `tests/`
(`<scratch>/trial3`) and validated there before anything touched the
repo. Diffs of record: `reports/phase2_port_changes.diff` (source) and
`reports/phase2_test_changes.diff` (unit tests).

| Step | Change | Icache unit suites (basic 63 + full 58, plus new tests) |
|---|---|---|
| T2b | `valid_only` lanes only | all pass |
| T3b | + §5(1) stale-but-allocating lines complete their fill | all pass; new test `test_r_fb_6b_stale_allocating_fb_completes_fill` passes |
| T3 (first cut) | + §5(2) hold guard | **6 failures**, all attributable to the hold, see below |
| T3 (final) | + two consequential fixes + five tests re-stimulated | **all pass**; 10/10 CPU programs and 74/74 arch tests with assertions **on** |

What the hold guard uncovered (both are pre-existing holes that the
hold merely makes reachable in the unit-test bus model, which withholds
`instr_gnt_i` until the test decides to serve one request):

1. **Release race.** At the cycle the held request is finally granted,
   a stale non-allocating FB also met its release condition
   (`beats_rcvd == beats_sent`, evaluated before the grant lands). It
   released and was re-allocated for the new lookup while its beat was
   still in flight; the returning beat then landed on the new occupant
   (`<scratch>/trial3/dbg.log`, cycles C016–C018). Upstream cannot do
   this because `fill_rvd_done` counts *granted* beats
   (`ibex_icache.sv:782-783`). Fix: an FB that is the current bus pick
   never releases (`releasing_v[fb] … and (not bus_grant_v[fb])`).
2. **Live-overlay leak.** The parent made an FB an output candidate on
   any returning beat (`fb*_wants_out_live = wants_out or rvalid …`)
   with no stale check, so the stale FB's now-complete line was served
   for the re-branched address with the *old* first word
   (`test_e2e_branch_to_same_addr_during_stall`: "valid_o delivered OLD
   bus pattern"). With the cache disabled that is exactly the stale
   data the test guards against; the same leak was reachable before
   whenever a beat was in flight across a branch. Fix: the overlay
   candidate is gated on `not fb*_stale`.

3. **Coalescing onto a stale FB** (found by the full gate, not by the
   icache suites: `test_ibex_core_unit_full::req3_instr_valid_clear_drops_register`).
   With the hold, a prefetch FB whose line is the branch target keeps
   its granted beat instead of vanishing; the branch makes it stale
   (cache disabled), and the new lookup for the same line then
   coalesced onto it (`inflight_line_match_ic0`) — but a stale FB never
   outputs, so the core saw no re-fetch (`<scratch>/trial3/dbg_req3.log`).
   Upstream does not coalesce at all (`ibex_icache.sv:701-702`). Fix:
   stale FBs are excluded from the in-flight match; a fresh FB
   re-fetches the target while the stale one finishes or drains.

Five existing tests assumed the pre-hold behaviour and were changed
only in their **bus stimulus**, not in what they assert:

| Test | Old assumption | Change |
|---|---|---|
| `test_r_ext_5_no_further_req_after_recorded_bus_error`, `s9_bus_error_on_fill_beat` | the beat-1 request already presented on the bus when the error returns can vanish | grant that presented request once (R-EXT-2), then assert no further request — the spec's "no further `instr_req_o` after cancellation" |
| `test_e2e_branch_during_ready_stall_passthrough`, `test_e2e_repeated_branch_during_long_stall`, `test_e2e_branch_to_same_addr_during_stall` | the first grant after a branch serves the branch target | new helper `_bus_serve_line` grants every presented request (the held one first, answered with a filler word) until the target line/word is served; assertions unchanged |

A second new test, `test_r_ext_2b_req_held_across_branch_until_gnt`,
pins the hold itself (delayed `gnt`, branch during the hold: `instr_req_o`
and `instr_addr_o` stable until the grant; the new target is fetched
afterwards; no re-request by the stale FB).

## 8. Phase 2.4 gate — applied changes, final pinned compiler, assertions ON (no `--no-assert` anywhere)

Run 2026-09-04 on branch `review-package` after applying §7, **with the
final pin** (arch-com `89ec0522` = main `f4569890` + PR #993 + PR #994;
see `10-toolchain.md` for why the earlier v0.71.0-based pin was
replaced). Logs and junit under `reports/gate_*`. `ARCH_BIN` = pin;
pytest from the anaconda environment; `PYTEST_ADDOPTS` used only to
add `--junitxml`. (The same gate on the v0.71.0-based pin gave the same
design-suite results: 166 passed / 8 failed / 75 skipped, 74/74 arch
tests, CoreMark 1.0108; only the arch-sim count differs, see below.)

| Suite (command) | Result | Wall time | Lane | Files |
|---|---|---|---|---|
| `make lint` | **FAIL** — 3 warnings, all known from the first package: 2 × `PROCASSINIT` (`build/ibex_multdiv_fast.sv`, thread-state emitter, arch-com#995), 1 × `SYNCASYNCNET` (`soc/ibex_mini_soc.sv:67` / `build/ibex_top.sv`, guard-register tracking flops with a synchronous reset) | 1.4 s | Arch (SoC) | `gate_make_lint.log`, `.junit.xml` |
| `make test` (`pytest tests/ -n auto --dist=loadfile`, 249 items) | **162 passed, 12 failed, 75 skipped** | 71 s | Arch | `gate_make_test.log`, `.junit.xml` |
| — of which every per-module unit suite (`test_<m>_unit*.py`, 34 collectors incl. icache/core) | all pass | (in above) | Arch | |
| — `tests/test_cpu_programs.py` (10) | 10 / 10 | (in above) | Arch | |
| `tests/test_arch_tests.py` (74 signatures vs upstream references) | **74 / 74 pass**, 74 reference-generation variants skipped by design | 69 s | Arch vs SV references | `gate_arch_tests.log`, `.junit.xml` |
| `RUN_COREMARK_COMPARE=1 pytest tests/test_coremark_compare.py` | **pass, validated**: Arch 112,855 ticks vs upstream 111,651 (ratio 1.0108; 8.861 vs 8.956 CoreMark/MHz) | 50 s | both lanes | `gate_coremark.log`, `.junit.xml` |

The 12 `make test` failures, none in the design suites:

| Test | Cause | Class |
|---|---|---|
| `test_soc_lint.py::test_ibex_mini_soc_lints` | the three `make lint` warnings above | Verilator 5.048 classes vs the harness's waiver list (Phase 3; `PROCASSINIT` filed as arch-com#995) |
| `test_archsim_units.py` — 6 of 6 modules (`IbexAlu`, `IbexCompressedDecoder`, `IbexCounter`, `IbexDecoder`, `IbexMultdivFast`, `IbexRegisterFileFf`) | `arch sim --pybind` generates a pybind11 wrapper that fails to compile (`cannot form a pointer-to-member to member … of reference type`, filed as arch-com#996). On the v0.71.0-based pin only the two modules with `Vec` ports failed; on main all six do. Passes with the 2026-05-14 compiler (`<scratch>/drift-check-B.log`) | arch-com regression in the simulator backend; unrelated to the port sources |
| `test_harc_phase1_canaries.py` (4 canaries) | in the gate: "HARC binary not found" (the runner's default path is `<repo parent>/harc-com`, wrong inside a git worktree); with `HARC_BIN` set to the real binary: "HARC runner forbids --codegen; use default TBIR" — HARC 0.2.0 (2026-08-31) rejects a flag the checked-in runner passes (`gate_harc_with_harc_bin.log`) | HARC tool drift; fails identically with the older compiler |
| `test_harc_runner.py::test_checked_in_compressed_decoder_coverage_status_is_complete` | reads `tests/harc/plans/ibex_compressed_decoder_full_bins.md` / `_coverage_status.md`, which were never committed (`git ls-files tests/harc/plans` lists five other files; test added in `8c4b3ca`) | pre-existing repo defect |

Both lanes for the suites that apply to both: the SV lane's own result on this
toolchain is in `02-functional.md` (10/10 CPU programs; SoC lint fails on the
same `SYNCASYNCNET`); the arch tests compare the Arch lane against
SV-lane-generated references by construction; CoreMark runs both lanes in one
test.

Observation for the spec, not acted on: R-EXT-5 cites
`ibex_icache.sv:766-774, 814-818`, but upstream's `fill_ext_done_d` has
no bus-error term — a bus error stops the cache *write-back*
(`fill_ram_req`, line 814-818), not the remaining external requests.
The port cancels remaining requests on error (`not err_q`) and the
tests keep asserting that; it is stricter than upstream, not looser.
