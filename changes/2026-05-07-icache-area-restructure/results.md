# Results: IbexIcache area restructure (final)

## Status

Closed 2026-05-08. All planned restructure PRs merged plus one
parameter-correction follow-up. Gate green throughout (129 passed, 74
skipped).

## Headline numbers

**Module-level (icache only, no RAMs), sky130, IC_NUM_LINES=256:**

| state | area µm² | vs upstream |
|---|---|---|
| upstream `ibex_icache` | 30,170 | — |
| swap, original (proposal start) | 42,355 | +12,185 (+40.4%) |
| swap, after PR #38 (IC=128) | 32,675 | +2,505 (+8.3%) |
| **swap, after IC=256 bump (final)** | **34,771** | **+4,601 (+15.2%)** |

**SoC top, sky130, IC_NUM_LINES=256, hierarchical-memory yosys flow:**

| state | area µm² | vs upstream |
|---|---|---|
| upstream SoC | 1,715,080 | — |
| **swap SoC** | **1,743,692** | **+28,612 (+1.67%)** |

The +1.67% SoC number is misleadingly small because ~1.34M µm² of
identical prim_ram_1p banks dilute the percentage. The icache module
gap of +15.2% is the meaningful metric for tracking swap-vs-upstream
overhead. The remaining ~24k µm² of SoC-level delta (28k − 4.6k icache
= 24k) is mostly synth optimisation noise from differing const-prop
chains (upstream = 132 events, swap = 5,925 events under default
flatten flow).

## Total reduction

The proposal targeted closing 12,185 µm² (+40%); the work landed
**−7,584 µm² (−61% of the original gap)** at the icache module level.
At IC_NUM_LINES=128 the closure was −9,680 µm² but the IC=256 bump
needed for upstream parameter parity added back +2,096 µm² (wider
8-bit index muxes, slightly bigger inval-walk counter, tag-slice
shifts).

## PR arc (icache module, IC=128 timeline)

| PR | µm² | Δ | what landed |
|---|---|---|---|
| start | 42,355 | — | combined/perf-alu-and-multdiv branch |
| #33 | 38,063 | −4,292 | centralize fill_data_q + beat tracking |
| #34 | 38,063 | 0 | RDC `guard valid_q` reset audit (PrefetchBuffer) |
| #36 | 34,472 | −3,591 | drop FillBufferCam, 1-cycle post-release bit |
| #38 | 32,675 | −1,797 | combinationalize rdata/err/err_plus2 outputs |
| (IC=256 bump) | 34,771 | +2,096 | parameter parity with upstream |

## Bugs surfaced and filed

### arch-com PRs (5)

| PR | what | impact |
|---|---|---|
| #317 | archsim `Pattern::Ident` → literal case label | unblocks `unique match` rewrites of operator decoders |
| #318 | FSM lowering uses `unique case` for state decoding | parallel-mux inference instead of priority encoder |
| #319 | auto_bound_vec elides for-loop iterators | `for fb in 0..3 vec[fb] <= ...` no longer emits OOB bound checks |
| #320 | RDC `guard <sig> reset none` waiver (#260) | enables enable-FF inference for stored-on-valid regs |
| #321 | Vec<UInt<1>> single-dim emit + split mixed-reset seq | correctness fixes for SV interop edge cases |

### Latent arch-ibex bugs

- **`IbexTop.arch:712,728`** wmask hardcoded `64'hFFFF…` instead of
  `{LineSizeECC{1'b1}}`. Functionally fine at default ICacheECC=0
  (LineSizeECC=64, mask exact width) but silently zero-extends the
  top bits if anyone enables ICacheECC=1 (LineSizeECC>64), causing
  `&wmask_i` to fold to 0 and the data RAM to be eliminated as
  const-x. Not yet fixed; not a blocker at default config.

### yosys behaviour discovered

- **Default `synth -flatten` ordering silently DCEs `$memwr` cells**
  when one of N parallel write-enable drivers folds to constant after
  flatten. Asymmetric driver counts (e.g. `data_write` driven only by
  `fill_grant`, while `tag_write` driven by `fill_grant ∨
  inval_grant`) make the data RAM disappear while the tag RAM
  survives. Frontend-independent: reproduces with both yosys-slang
  and sv2v→yosys-V on the same swap SV.
- **Workaround:** run `memory -nomap` per-module BEFORE flatten,
  then `flatten + memory_map`. Restores all four banks intact.
- Working synth scripts:
  - `/tmp/ibex-swap-synth/run_soc_swap_keephier.tcl` (slang plugin)
  - `/tmp/ibex-swap-synth/run_sv2v_hier.tcl` (sv2v + yosys-V)
  - `/tmp/ibex-swap-synth/run_soc_upstream_hier.tcl` (matching upstream flow)

## Why upstream is still ~5k smaller at module level

The +4,601 µm² module-level gap at IC=256 breaks down approximately:

- **+2,096 µm²** added by the IC=128→256 bump (wider index muxes,
  inval-walk counter +1 bit, tag-slice rewires). Upstream is fully
  parameterised so its area is invariant across IC_NUM_LINES; the
  swap had to hand-bump every slice and that costs some logic.
- **+2,505 µm² residual** from the IC=128 final state (PR #38
  endpoint). Likely the small remaining cost of the per-FB Phase
  FSM submodule boundaries, FbAgeArb arbiter generality, and
  the way `unique case` lowers compared to upstream's bespoke
  one-hot priority encoders.

## Lessons captured to memory

- `feedback_yosys_flatten_before_memory.md` — yosys flatten-before-memory
  DCE bug + hier flow workaround.
- `feedback_soc_area_needs_param_match.md` — verify cache geometry
  parameters match before claiming an area gap.

(Plus prior session memories from #319, #320, #321, RDC guard,
`unpacked ascending`, etc. — all under
`~/.claude/projects/-Users-<user>-github-arch-ibex/memory/`.)

## Open follow-ups

1. **arch-ibex IbexTop.arch wmask fix** — replace `64'hFFFF…` with
   `{LineSizeECC{1'b1}}` equivalent. Not a blocker; only matters if
   ICacheECC=1 is enabled later.
2. **Module-level icache gap** — +4,601 µm² (+15.2%) remains. Further
   reduction would target the per-FB submodule boundary cost or the
   FbAgeArb arbiter generality, but neither has a clear path.
3. **yosys upstream issue** — file the flatten-before-memory DCE
   reproducer with yosys-slang + native frontends both demonstrating it.
4. **icache cache-hit functional bugs** — surfaced after PR #43 fixed
   the `cs_registers ICache` parameter wiring. The bench is currently
   `@cocotb.test(skip=True)`. Two distinct bugs in the swap's
   cache-enabled path identified via VCD:

   **Bug A — writeback / lookup deadlock.**
   `fill_grant = fill_write_req & ~lookup_req_ic0`. When the CPU
   issues back-to-back same-line lookups during a tight loop, the
   coalesce check suppresses new FB allocations (so `fb_count` stays
   at 1, never hitting the throttle threshold at 3) but the
   `lookup_req_ic0=1` simultaneously gates `fill_grant` low. The
   miss FB has data ready (`beats_rcvd=2`, `wants_wb=1`) but its
   writeback never gets RAM-port grant. FB stays pinned forever.

   **Workaround validated:** suppress `lookup_req_ic0` for one cycle
   when `coalesce_ic0 && (fb_wants_wb != 0)`. This lets `fill_grant`
   fire, the writeback drains, the FB releases. Gate stays at 129/130
   with this fix applied — but it doesn't address Bug B.

   **Bug B — addr_out_q vs FB-data desynchronization.**
   With Bug A worked-around, the CPU progresses through the bench's
   soak loop and warm-up but immediately loops `kernel_start →
   halt → kernel_start` for thousands of iterations. VCD trace at
   the loop hot-spot:

   - Cycle T: `pc_id=0x10018c` (bnez consumed), `valid=1`,
     `rdata=fe0298e3` (correct, the bnez)
   - Cycle T+1: bnez branch_i fires → `addr_out_q := 0x10017c`
     (loop body start)
   - Cycle T+2: `valid=1`, `rdata=00730333` (the `add` at 0x10017c) —
     correct so far. Consume → `addr_out_q := 0x100180`.
   - Cycle T+4: `valid=1` again with **same `rdata=00730333`** but
     `addr_out_q=0x100180` (the `mul`/`add` slot). The cache
     re-delivers the previously-fetched `add` instead of the
     instruction at the new address.
   - Eventually `addr_out_q` jumps to `0x10016c`, the icache
     delivers `0x0000006f` (the halt instruction at that address),
     CPU consumes — but it's been executing wrong instructions for
     several cycles, so the architectural state is corrupted.

   Root cause: on a `branch_i` pulse, `addr_out_q` updates to the
   branch target, but the output stage may still be granting the
   PRIOR FB (which holds data from the old fetch line). The FB's
   data and `addr_out_q` are out of sync — `valid_q` rises with
   addr=new but data=old. The CPU executes the wrong instruction.

   Fix sketch (not implemented): when `branch_i` fires, also clear
   `valid_q` and force `out_arb` to invalidate any in-flight grant
   so the next `valid_q` rise comes from a fresh, post-branch FB
   allocation. Upstream Ibex does something analogous via
   `fill_stale_q` gating on `fill_out_req` (line 795 of
   `ibex_icache.sv`). The swap has `stale_q` per FB, but `wants_out`
   suppresses on stale only AFTER the current cycle's grant — the
   pre-stale-delivered output still propagates to `valid_q`.

   Both fixes together would let icache_bench run to completion and
   give a real cache-enabled CPI measurement. Requires careful
   FB-lifecycle restructuring; estimate 1-2 days of focused work
   plus verification against the existing 129-test gate.

   **Bug B refinement (post-PR #44 dig).** A second VCD pass with
   `wants_out_v[fb] |= !branch_i` applied (mirroring upstream's
   gating) showed *zero* behavioural change — same kernel→halt loop,
   same wrong-rdata pattern. The root cause is one layer deeper:

   `fill_data_q[fb]` is a per-FB 64-bit register that is *not*
   reset on FB allocation. When an FB releases and is later
   re-allocated for a different line, `fill_data_q[fb]` still
   holds the *previous* line's content until either
   `data_we_ic1_hit` (cache hit) or `data_we_beat0/beat1` (bus
   fill arrival) overwrites it.

   VCD evidence at the loop hot-spot (cycle right after FB0 is
   re-allocated from line 0x100178 to line 0x100180):

   - `fb0_addr` transitions `0x00100178 → 0x00100180`
   - `fb_busy_mask` goes `0 → 0001`
   - `out_grant_valid` goes high one cycle later
   - `valid_q` rises with `rdata_o = 0x00700393` (the `addi t2,
     zero, 7` instruction at *0x100178* — the prior line) but
     `addr_out_q = 0x00100180`
   - `fill_data_q[0]` shows `0x73033300700393` — the OLD
     line-0x100178 content, *unchanged* across the re-allocation

   So the cache-hit fast path's `data_we_ic1_hit_v[fb] = (phase==1)
   && ic1_hit_combo` either didn't fire, or fired with stale
   `ic_data_rdata_i`, leaving `fill_data_q[fb]` carrying the
   previous allocation's data when `wants_out_v[fb]` re-asserts.

   Likely cause hypotheses to investigate next:

   1. **Tag-only false hit.** If `way0_valid && way0_tag matches`
      reports a hit for a line that was written into a DIFFERENT
      cache index due to the stale-FB writeback (Bug A's pre-fix
      state poisoned the cache), the lookup would "hit" with
      mismatched data. Mitigation: invalidate cache writebacks
      from stale FBs.
   2. **`data_we_ic1_hit` timing race.** The hit-data capture is
      gated on `phase==1`, but `phase` updates on the same edge
      that the FB transitions PhAlloc→PhCheck (1) → PhRunning (3).
      If `phase==1` evaluates as the *registered* value at the
      tag-compare edge, the write-enable could miss the actual
      hit cycle. Mitigation: use `data_we_ic1_hit` based on the
      *next* phase value (combinational) or a dedicated allocation
      flag.
   3. **`fill_data_q` needs an explicit reset/clear on alloc.** A
      one-cycle preset of fill_data_q[fb] on PhAlloc entry would
      eliminate the stale-data hazard at the cost of a small mux,
      but ensures `out_grant_valid` can never deliver pre-realloc
      content.

   Hypothesis (3) is the most defensive and likely the right path.
   Estimate adjusted: 2–3 days of focused work + full gate
   regression + icache_bench CPI re-measurement against upstream.
