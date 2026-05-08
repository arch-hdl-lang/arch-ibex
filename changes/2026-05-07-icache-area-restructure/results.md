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
