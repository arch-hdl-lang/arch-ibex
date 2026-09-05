# 11 — Port changes for the compiler pin (TASK2 Phase 1)

Pin: `arch 0.71.0` @ arch-com `1a7d9fd7` (release v0.71.0, 2026-07-26).
Every change to `src/` is listed here with its diff and a one-line
rationale. Status of each entry is explicit; nothing is applied
without approval.

## Change 1 — `src/IbexIcache.arch`: bind pipe-register taps before combining them

**Status: APPROVED by repo owner and APPLIED (2026-09-03).**

Diagnostic from the pinned compiler (`arch check src/IbexIcache.arch`,
`<scratch>/check2-v0.71.0-IbexIcache.log`):

```
Error:   × 4 errors
  × operands at cycle 0 and cycle 1    (src/IbexIcache.arch:551:5)
  × operands at cycle 0 and cycle 2
  × operands at cycle 0 and cycle 3
  × operands at cycle 0 and cycle 4
```

Cause: `typecheck.rs::check_operand_latency_alignment` (v0.71.0
`src/typecheck.rs:3671`, invoked for every binary operator at `:3954`)
rejects an expression whose operands carry different `@N` cycle
offsets. The icache ORs the cycle-0 signal `fb_busy_mask` with the
`@1..@4` taps of the 4-stage `pipe_reg fb_busy_prev`. The rule was
added in arch-com `2aab897a` (2026-07-12, first released in v0.70.8)
for `<pipelined, N>` operators; it also catches plain delay-line tap
reads. Note: the same v0.71.0 spec still documents tap reads such as
`prod1 = sample_pipe@1 * coeff1;` as legal (`doc/ARCH_HDL_Specification.md:1366`),
and that example fails under v0.71.0 with the same error
(`<scratch>/smoke/fir-v0.71.0.log`). That is an arch-com spec/compiler
inconsistency to file; it is not fixed here.

Minimal source change (12 lines, one hunk):

```diff
--- a/src/IbexIcache.arch
+++ b/src/IbexIcache.arch
@@ -549,6 +549,16 @@
   pipe_reg fb_busy_prev: fb_busy_mask stages 4;
+  // Each tap is bound to its own `let` before being combined: arch-com
+  // >= 0.70.8 rejects mixing `@N` taps of different N in one expression
+  // ("operands at cycle 0 and cycle N"). The bound names are plain
+  // cycle-0 signals, so the OR below is unchanged in meaning and lowers
+  // to the same SV (`assign` aliases of `fb_busy_prev_stg{1,2,3}` /
+  // `fb_busy_prev`).
+  let fb_busy_prev1: UInt<4> = fb_busy_prev@1;
+  let fb_busy_prev2: UInt<4> = fb_busy_prev@2;
+  let fb_busy_prev3: UInt<4> = fb_busy_prev@3;
+  let fb_busy_prev4: UInt<4> = fb_busy_prev@4;
   let fb_busy_recent_mask: UInt<4> =
-    fb_busy_mask | fb_busy_prev@1 | fb_busy_prev@2
-                 | fb_busy_prev@3 | fb_busy_prev@4;
+    fb_busy_mask | fb_busy_prev1 | fb_busy_prev2
+                 | fb_busy_prev3 | fb_busy_prev4;
```

Rationale: a `let` bound to a single tap has no mixed operands, and a
`let` name is a cycle-0 signal to the checker, so the OR compiles; the
`pipe_reg` construct and the 4-cycle window are preserved.

Evidence (all from a scratch copy of `src/`, repo untouched):

| Check | Result | Where |
|---|---|---|
| Smoke module, direct form, v0.70.6 / v0.71.0 | OK / **error** | `<scratch>/smoke/direct-*.log` |
| Smoke module, let-bound form, v0.70.6 / v0.71.0 | OK / OK, emitted SV identical between compilers | `<scratch>/smoke/letbound-*.sv` |
| Full port with this change, v0.71.0: `make build` | 23 / 23 `.sv` | `<scratch>/trial/make-build.log` |
| Full port with this change, v0.71.0: `arch check` per file | 23 / 23 pass | (same run) |
| `build/ibex_icache.sv` vs the compiler-B output, comments stripped | 12 changed lines: 4 new `logic [3:0] fb_busy_prevN;` wires, 4 `assign fb_busy_prevN = fb_busy_prev_stgN;` aliases, the OR rewritten over the aliases; plus one compiler-side change to an auto-generated bounds assertion (now guarded by `lookup_alloc_ic1_q`) that is unrelated to this edit | `diff <scratch>/build-B/ibex_icache.sv <scratch>/trial/build/ibex_icache.sv` |

Alternative considered: reverting to the four explicit `reg`
declarations from before commit `dcdbbc8`. Rejected as larger (drops
the `pipe_reg` construct the port deliberately exercises) with no
functional gain.

## Change 2 — the `prim_ram_1p` interface-stub variant mangling

**Status: DECIDED — option A (compiler fix), APPLIED as a patched pin
build; no change to `src/*.arch` or `scripts/`.**

Resolution: the repo owner chose option A only. The fix is a 12-line
change in arch-com's variant discovery: an interface stub keeps a
single variant under its original name (`src/elaborate.rs`, function
`compute_all_variants`; at arch-com HEAD the same function lives in
`src/elaborate/params.rs`).

- **Pin used for Phases 1–3 measurements:** `arch 0.71.0` @ arch-com
  `ead3aa8f` = tag `v0.71.0` (`1a7d9fd7`) + that fix (later `fa4c864f`
  with the Phase 2 arbiter fix). **Final pin (Phase 4 on, and all Phase 2/3
  numbers re-run on it):** arch-com main `f4569890` + PR #993 + PR #994 =
  `89ec0522`, released as `v0.72.0` on 2026-09-05 (byte-identical SV);
  patches in `reports/arch_com_pin_000{1,2}-*.patch`. See
  `10-toolchain.md` for the reason (release v0.71.0's emitter still produces
  Yosys/sv2v-unparsable index shapes that main fixed in August).
- **Upstream:** the same fix plus a regression test
  (`tests/integration_test.rs::test_interface_stub_not_variant_mangled`,
  a two-file `.archi` stub instantiated with `Width=16` and `Width=32`)
  is on arch-com branch `fix/stub-variant-mangling` off `origin/main`
  `f4569890`; the test fails without the fix and passes with it
  (`<scratch>/arch-com-gate.log`). PR status is recorded in
  `10-toolchain.md` once opened.
- **Verification on the port with the pin:** `make build` 23 / 23,
  `arch check` 23 / 23 (`reports/arch_check_pinned.log`),
  `build/ibex_top.sv` instantiates `prim_ram_1p` by name, and the SoC
  elaborates under Verilator (the SoC lint test still fails on the three
  warnings already known from the first package — 2 × `PROCASSINIT`,
  1 × `SYNCASYNCNET` — which is Phase 3's subject).

With any compiler from arch-com `9ba64352` (2026-05-23) onward,
including the pin, `build/ibex_top.sv` instantiates
`prim_ram_1p__DataBitsPerMask_22_Width_22` and
`prim_ram_1p__DataBitsPerMask_64_Width_64` instead of `prim_ram_1p`
(`<scratch>/trial/build/ibex_top.sv`). No `.arch` source is at fault:
`src/prim_ram_1p.archi` is a committed hand-written interface stub for
the upstream SV cell, `IbexTop.arch` instantiates it twice with
different `Width`/`DataBitsPerMask` values, and
`elaborate.rs::compute_all_variants` (v0.70.6 `src/elaborate.rs:455-521`)
mangles a module's name whenever it sees two distinct effective
parameter sets — without exempting interface stubs, for which the
compiler emits no definition. The SoC therefore fails to elaborate
(`Can't resolve module reference`). Verified identical on every release
from v0.70.0 to v0.70.7 and on the pin (`10-toolchain.md`).

Options, in order of how faithfully they keep "what is measured"
unchanged:

| # | Where | Change | Effect on measured design | Notes |
|---|---|---|---|---|
| A | arch-com | In `compute_all_variants`, skip items whose `common.is_interface` is set (keep the base name). ~3 lines, internal, no language-surface change. | none | Needs a patched build of v0.71.0 (or a v0.71.1). Per this repo's rules an internal codegen fix may be done autonomously with a PR; the pin would then be "v0.71.0 + that PR". |
| B | `scripts/build.sh` | After `arch build`, rename `prim_ram_1p__[A-Za-z0-9_]*` → `prim_ram_1p` in the emitted `.sv` (the `#(...)` parameter list is already correct). | none (same SV as pre-`9ba64352` compilers) | Flow-script workaround of a compiler bug; TASK2 asks before any `flow/`-type change, hence listed, not applied. |
| C | `src/` + `soc/` | Split the stub into `prim_ram_1p_tag.archi` / `prim_ram_1p_data.archi` with fixed parameters, and add two hand-written SV wrapper modules of those names that instantiate `prim_ram_1p`. | adds 2 tiny SV wrappers to the Arch lane (flattened away in synthesis; visible in LOC/lint) | Pure repo-side, no compiler patch, no flow hack. |

Recommendation: A (correct fix, filed upstream) with B as the stopgap
so the package is not blocked on an arch-com release; C only if a
patched compiler is unacceptable for the pin.

## Phase 2 changes (icache handshake and its follow-ups) — see `12-icache-handshake.md` §7

**Status: APPROVED and APPLIED (Phase 2 commit `11cd655`), validated on a
scratch copy first.** Full diffs: `reports/phase2_port_changes.diff` (source, 180
lines) and `reports/phase2_test_changes.diff` (unit tests, 233 lines).
One-line rationale per hunk:

| # | File / hunk | Rationale |
|---|---|---|
| 3 | `src/FbAgeArb.arch`: `handshake_channel request[NUM_REQ]: receive kind: valid_ready` → `valid_only` (+ comment) | The request lanes are a level-sensitive mask that may be withdrawn (upstream `fill_ext_req`, `ibex_icache.sv:755`); `valid_only` is the matching contract and emits no Tier-2 `valid_stable` property. |
| 3 | `src/IbexIcache.arch`: delete the eight `bus_ready_*` / `wb_ready_*` wires and the eight `request[i].ready -> …` connections | `valid_only` has no ready signal; nothing read those wires. |
| 4 | `src/IbexIcache.arch`: `wants_bus_v[fb]` — `not stale_q` → `not (stale_q and not alloc_q)` | §5(1): remaining beats are cancelled only for stale **non-allocating** lines (upstream `~fill_cache_q & (branch_i \| fill_stale_q)`, lines 766-774; spec R-FB-6); an allocating line is fetched to completion and written back. |
| 4 | `src/IbexIcache.arch`: `releasing_v[fb]` early-release alternative — `stale_q` → `stale_q and not alloc_q` | Same rule on the release side: an allocating stale FB waits for all beats and the write-back. |
| 4 | `src/IbexIcache.arch`: branch handler — remove `if beats_sent != beats_total: alloc_q <= false` | `alloc_q` is kept across a branch exactly as upstream keeps `fill_cache_q`; only inval / disable clear it. |
| 5 | `src/IbexIcache.arch`: new `bus_hold_valid_q` / `bus_hold_fb_q`, `bus_pick_*` renamed, `bus_grant_*` = hold override | §5(2), R-EXT-2: a presented request is held (same FB, same address) until `instr_gnt_i`, overriding age order and demand bias (upstream `fill_ext_hold_q`, lines 763-774). |
| 5 | `src/IbexIcache.arch`: `bus_inflight_fb_q` gains `guard bus_inflight_valid_q` | Annotation only (the comment already stated the gating); required by the compiler's reset-domain check once the hold register feeds this capture. |
| 5a | `src/IbexIcache.arch`: `releasing_v[fb]` gains `and (not bus_grant_v[fb])` | Consequential: never release the FB that owns the bus pick — its held request may be granted this cycle and the beat must return to it (upstream `fill_rvd_done` counts granted beats, lines 782-783). |
| 5b | `src/IbexIcache.arch`: `fb*_wants_out_live` — the rvalid / IC1-hit overlay term gated on `not fb*_stale` | Consequential: a beat returning to a stale FB must not make its abandoned line an output candidate (stale-data leak with the cache disabled). Pre-existing hole, reachable before whenever a beat was in flight across a branch. |
| 5c | `src/IbexIcache.arch`: `inflight_line_match_ic0` — each FB term gated on `not stale_q[fb]` | Consequential, found by the full gate (`test_ibex_core_unit_full::req3`): a branch whose target line a now-stale prefetch FB was fetching coalesced the lookup onto that FB, which can never deliver, so no re-fetch appeared. Upstream never coalesces (`ibex_icache.sv:701-702`); a stale FB now finishes or drains while a fresh FB re-fetches the target. |
| T | `tests/cocotb_tests/test_ibex_icache_unit.py`: new helper `_bus_serve_line`; five tests re-stimulated (grant the already-presented request before expecting the next one); two new tests `test_r_fb_6b_stale_allocating_fb_completes_fill`, `test_r_ext_2b_req_held_across_branch_until_gnt` | The old stimulus assumed a presented request can vanish; under R-EXT-2 it must be granted first. Assertions are unchanged. |
| T | `tests/cocotb_tests/test_ibex_icache_unit_full.py`: `s9_bus_error_on_fill_beat` grants the presented beat-1 request before asserting no further request | Same reason. |

Validation on the scratch copy with the pinned compiler (assertions on):
icache basic + full suites all pass; `tests/test_cpu_programs.py` 10/10;
`tests/test_arch_tests.py` 74/74 (84 passed, 74 skipped in 26 s).

## Compiler-side codegen differences, v0.71.0 vs the 2026-05-14 compiler (no source change involved)

From `diff <scratch>/build-B/*.sv <scratch>/trial/build/*.sv` with
comments stripped; recorded so Phase 3 can attribute lint deltas
correctly.

| File | Difference | Kind |
|---|---|---|
| `ibex_icache.sv`, `ibex_icache_output_stage.sv`, `ibex_register_file_ff.sv` | auto-generated `_auto_bound_vec_*` index-bound assertions are now guarded by the enabling condition (`cond |-> idx < N`) instead of unconditional | assertion emission |
| `inval_ctrl.sv` | the auto-generated `_auto_legal_state` FSM assertion is no longer emitted | assertion emission |
| `ibex_multdiv_fast.sv` | thread loop counter renamed `_t0_loop_cnt` → `_t0_loop_cnt_0`; the `_threads` helper now receives `#(.RV32M(RV32M))`; three output regs declared in a different position; `_t0_state` / `_t0_loop_cnt_0` still declared with an initial value and assigned procedurally (the `PROCASSINIT` pattern from the first package persists) | thread lowering |
| `ibex_top.sv` | `prim_ram_1p` instances renamed to the mangled variant names (Change 2) | variant elaboration |

## Change log

| # | Where | Status | Commit |
|---|---|---|---|
| 1 | `src/IbexIcache.arch` (+12 / −2 lines, one hunk) | applied | Phase 1 commit on `review-package` |
| 2 | arch-com (compiler), not this repo | applied as patched pin; PR upstream | `reports/arch_com_v0.71.0_stub_variant_fix.patch` |
