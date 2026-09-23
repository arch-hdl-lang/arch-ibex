# `formal/icache_liveness/` — bounded liveness of the icache writeback

The property Bug C (`da9059f`) is actually about: **once a fill buffer asserts
`fill_write_req`, `fill_grant` must fire within N cycles.** Encoded as a
starvation counter in `prop.v`; cycles where the invalidation walk holds the
RAM port are excluded (inval has priority by design, bounded by the walk).

```bash
make build                                   # generates build/*.sv
formal/icache_liveness/run.sh nothrottle exact branchyield
```

## Setup

- **Design under test:** the real generated `ibex_icache` + sub-modules,
  through `sv2v`, with `prop.v` injected by `make_variants.py`.
- **Variants** differ only in the `lookup_grant` line:
  `nothrottle` (pre-Bug-C), `exact` (the Bug C fix as first shipped —
  coalesce on the exact lookup line), `branchyield` (on `main` since #10).
- **Upstream comparison:** `icache_upstream.v` is upstream Ibex's
  `ibex_icache` from the SV lane (`flow/out/sv/ibex_top.v`, run
  `flow/sv2v.sh` first), with the same property on upstream's names
  (`fill_req_ic0` / `fill_grant_ic0`) and the same walk abstraction. Its port
  list is identical, so the environment is shared unchanged.
- **Environment** (`live_top.v`): everything the core and memory drive is a
  free, adversarial input, constrained only by OBI protocol (gnt answers a
  request; rvalid only for an outstanding grant) and `branch_i ⇒ req_i`.
  Tag/data RAM read data is free, i.e. the cache may be warm.
- **Abstraction:** the cold-boot invalidation walk is cut from 256 lines to 4.
  Sound here: RAM contents are free inputs, so the walk's writes constrain
  nothing, and inval cycles never count as starvation.

## Results

| task | env | result | meaning |
|---|---|---|---|
| `nothrottle` | unconstrained | **FAIL @ step 78** | Bug C reproduced: 65 cycles of `fill_write_req`, lookup wins every cycle, pool full |
| `exact` | unconstrained | **FAIL @ step 78** | see "Finding 1" |
| `branchyield` | unconstrained | **FAIL @ step 78** | see "Finding 1" |
| `exact_fair` | branch ≥ 1 / 16 cycles | **FAIL @ step 78** | ~45 branches in the window, none yields |
| `branchyield_fair` | branch ≥ 1 / 16 cycles | **PASS** (BMC, depth 100) | |
| `cover` | branch ≥ 1 / 16 cycles | both covers **reached** | the PASS above is not vacuous |
| `tight17` / `tight14` | branch ≥ 1 / 16 cycles | **PASS** / **FAIL @ step 28** | worst-case starvation is 14–16 cycles, i.e. the branch interval |
| `prove17` | branch ≥ 1 / 16 cycles | **PASS** (PDR, unbounded) | starvation < 17 **for all time**, not just 100 cycles |
| `upstream` | unconstrained | **FAIL @ step 76** | upstream Ibex, same property |
| `upstream_fair` | branch ≥ 1 / 16 cycles | **FAIL @ step 76** | ~35 branches in the window; a branch *bypasses* upstream's throttle rather than yielding |

"PASS (BMC, depth 100)" means *no violation within 100 cycles*, not a proof
for all time; that is what `prove17` is for.

### Finding 1 — neither Bug C fix bounds writeback latency in general

All three variants fail unconstrained, and the counterexample for the two
real fixes is not Bug C:

- a fill buffer (FB0) has filled a line and asserts `fill_write_req`;
- the core stalls (`ready_i = 0`);
- the prefetch address still advances **one line per cycle**;
- each lookup **hits** (warm cache), so its fill buffer is allocated and
  released ~3 cycles later without needing the RAM port — the pool hovers at
  2–3 busy and never fills;
- no branch, no coalescing, no full pool ⇒ the lookup wins every cycle and
  FB0's writeback waits indefinitely.

**This is not a deadlock**: the pool never fills and the core is not waiting
on that line. It is unbounded writeback *latency*, reachable with a warm
cache and a long enough core stall. The environment makes RAM contents free,
which is what allows every lookup to hit; whether a real program produces
that exact pattern for 64+ cycles has not been shown on a real trace.

**It is inherited from upstream.** Upstream Ibex fails the same property.
Its grant is unconditional (`lookup_grant_ic0 = lookup_req_ic0`); a
writeback only gets through when `lookup_req_ic0` drops — pool full
(`~&fill_busy_q`) or the fill-level throttle. Warm-cache hits trip neither:
hit buffers are not "in fill", and they release before the pool fills. In
the upstream trace the pool is full only on the final cycle, and at that
moment `lookup_req` drops and the writeback is granted — the safety valve
works, it just never fires during the churn. That valve is also exactly what
the pre-Bug-C Arch port was missing, which is why *it* hung.

### Finding 2 — the #10 change bounds it by the branch interval; the original fix and upstream do not

Under branch fairness (a branch at least every 16 cycles), `branchyield`
holds and `exact` fails:

- `branchyield` yields on **every** branch while a writeback is pending,
  whatever the target — so starvation is bounded by the gap between
  branches. `tight17`/`tight14` show the bound is tight: 14 ≤ worst < 17.
- `exact` only yields when the branch target is already in flight. Its
  counterexample has ~45 branches in the 64-cycle window, none of them to an
  in-flight line, so none yields.

- Upstream behaves like `exact` here, and for a simpler reason: a branch
  bypasses its throttle (`branch_i | ~lookup_throttle`), so branches never
  help a pending writeback.

`prove17` makes the bound unbounded rather than 100-cycle: under the
fairness assumption, starvation stays below 17 cycles for all time.

So the change that took the adder off the RAM grant (+3.07 ns WNS) also,
as a side effect, turned unbounded writeback latency into latency bounded by
branch frequency — making the Arch icache strictly better than upstream Ibex
on this property.

**Scope of that claim:** the design is the abstracted one (4-line walk), RAM
contents are free (a warm cache is allowed), and branch fairness is an
assumption about the core, not something proved. The failing results are
real, replayed traces; the passing ones were checked for vacuity (`cover`)
and tightness (`tight17`/`tight14`).

## Harness defects found on the way (all silent or misleading)

1. `x` constants from **SBY's own later passes** (`maccmap` inside its
   techmap) — the AIG backend rejects them. Fixed by mapping memories and
   arithmetic in our script first, then `setundef -anyseq`.
2. The default trace-replay solver (`yices`) is not installed: BMC said FAIL
   with no trace. Fixed with `aigsmt z3`.
3. **Chained `~a:~b:` task prefixes are not supported** — SBY honours the
   first and passes the rest through as a literal line. Fixed by task tags.
4. The 256-cycle walk made the first PDR run impractically deep — hence the
   abstraction above.
5. `run.sh` aborted after the first task: `sby` exits non-zero on FAIL,
   which is an *expected* verdict here, and `set -e` + `pipefail` turned it
   into a script failure. Each task's verdict is now reported and the loop
   continues.
