# `formal/` — icache `lookup_grant` rewrite harness

Formal support for reworking the Bug C fix (`da9059f`) so it stops putting
the ALU adder on the icache RAM request path.

## Why

`da9059f` changed

```
lookup_grant = lookup_req_ic0;                       // upstream, address-independent
```

to

```
lookup_grant = lookup_req_ic0 && !((coalesce_ic0 || fb_full) && fill_write_req);
```

`coalesce_ic0` compares the fill buffers' line tags against
`lookup_addr_ic0`, which on a branch is the ALU adder's output. The icache
RAM request therefore sits behind the adder. Post-P&R, all five of the Arch
lane's worst paths run

```
IF/ID instr reg -> ALU adder -> FB tag compare -> lookup_grant
                -> icache RAM req -> 16K-flop fanout tree -> rdata reg
```

at **-15.07 ns** WNS against the SV lane's **-9.66 ns** (`review-package/16-per-module.md`).
The gap is 20 extra logic levels / +8.05 ns in the cone feeding the RAM
enable; the RAM-side cost is comparable in both lanes.

## What this harness checks

`icache_grant_lemma.sv` models the real cone from `src/IbexIcache.arch`:
4 fill buffers, 29-bit line tags (`addr[31:3]`), `fb_busy_recent_mask` =
`fb_busy_mask` OR'd with four cycles of history, and
`pending_alloc_match_ic0` off the IC1 registers.

Run with SymbiYosys + z3:

```bash
formal/run_grant_lemma.sh "<verilog defines>" [depth]
```

### 1. `COALESCE_LEMMA` — is "just register it" sound?

| defines | result |
|---|---|
| `-DCOALESCE_LEMMA` | FAIL |
| `-DCOALESCE_LEMMA -DASSUME_STABLE` | pass |
| `-DCOALESCE_LEMMA -DIMPLIES` | **FAIL** |
| `-DCOALESCE_LEMMA -DIMPLIES -DASSUME_STABLE` | pass |

Registering `coalesce_ic0` is equivalent **only** while the whole cone is
stable — and the cone is `{lookup_line, fb_busy_recent_mask, stale_q,
fb0..3_addr, lookup_alloc_ic1_q, lookup_addr_ic1_q}`, not just the address.

Row 3 is the one that matters: even the liveness-safe direction
(`coalesce_comb ⇒ coalesce_q`) fails. The counterexample has `stale_q`
changing while everything else holds: `coalesce_comb` goes 0→1 immediately,
the registered copy lags one cycle, and the design grants the lookup one
more time instead of yielding the RAM to fill — exactly the starvation
window Bug C closes. **A naive registered throttle is unsound.**

### 2. `GRANT_INDEP` — is the adder off the RAM path?

Two copies with identical fill-buffer state but different lookup lines must
produce the same grant. This states the timing question formally.

| defines | result |
|---|---|
| `-DGRANT_INDEP -DGRANT_PREFIX` (upstream / pre-`da9059f`) | **pass** |
| `-DGRANT_INDEP` (current) | **FAIL** |

Use this as the acceptance test for any candidate rewrite: edit `grant_of`
to model the candidate and require **pass**. It is *necessary, not
sufficient* — it only says the address is off the grant. Preserving Bug C's
liveness is a separate obligation (see below).

## Not covered here

The liveness property Bug C is actually about — "if `fill_write_req` holds
continuously, `fill_grant` occurs within N cycles" — is **not** in this
harness. It involves the whole fill-buffer lifecycle, not just the coalesce
cone, so it needs the full `ibex_icache` under BMC with constrained inputs
rather than this small model. A candidate rewrite needs both:

1. `GRANT_INDEP` **pass** (adder off the RAM path), and
2. bounded-liveness preserved, with the bound calibrated so the pre-`da9059f`
   design *violates* it — otherwise the property is vacuous and proves
   nothing.

Plus the existing regression: `tests/cocotb_tests/test_icache_bench.py` and
the `sw_isr` / `multictx_isr` / `pmp_load_isr` scenarios the source cites.

## 3. Retiming the comparison (`icache_grant_retime.sv`)

Can the coalesce compare be moved a cycle earlier? The answer splits by mux
leg, because `lookup_line_ic0 = (branch_i ? addr_i : prefetch_addr_q)[31:3]`.

Run with `formal/run_retime.sh "<defines>"`.

| defines | result | meaning |
|---|---|---|
| `-DRETIME_SOUND` | **pass** | Retiming the **prefetch leg** is sound: evaluate the compare on the D side in cycle N-1 and register the result — provably equal to computing it live. Every input on that leg is a register, so there is something to retime across. |
| `-DRETIME_BRANCH_ATTEMPT` | **FAIL** | Retiming the **branch leg** is not. `addr_i` is the ALU adder's output in cycle N; no register sits between the adder and the compare, so there is no earlier copy to compute from. |
| `-DCANDIDATE_INDEP` | **pass** | Candidate = retimed prefetch leg + a conservative constant on the branch leg (`branch_i ? 1'b1 : retimed_prefetch_q`). Address-independent, so the adder comes off the RAM path. |
| `-DCANDIDATE_CONSERVATIVE` | **pass** | The candidate yields at least as often as today (`coalesce_today ⇒ coalesce_candidate`), so fill is never starved *more* than it is now — the Bug C direction. |

So a viable rewrite exists: retime the prefetch leg, and on a branch stop
asking "is this exact line in flight?" and just yield. It is conservative,
which is the safe direction for Bug C.

### What these results do and do not establish

- BMC to depth 12, not unbounded proofs.
- The register D-side inputs are driven as *free* inputs, which
  over-approximates the real design (more behaviours than can actually
  occur). A **pass** is therefore stronger than needed; a FAIL would need
  checking against the real next-state logic before believing it.
- `CANDIDATE_CONSERVATIVE` is the safe *direction*, not the liveness
  property itself. Bounded liveness still has to be checked on the full
  `ibex_icache` (see above).
- The candidate **costs lookup throughput**: on any branch coinciding with
  `fill_write_req` it yields even when the line would not have matched.
  That is a performance question — measure it on `test_icache_bench.py` /
  CoreMark, it cannot be proved here.
### The `branch_i` timing assumption — measured, holds

The candidate keeps the mux select (`branch_i`) on the grant path while
taking the address off it, so it only helps if the select arrives well
before the address. Measured with OpenSTA on the routed design
(`flow/out/arch/openroad/results/*.v` + `.spef`, propagated clock):

| signal | arrival |
|---|---|
| `id_stage_i.branch_set_raw` (branch control, flop Q) | **3.755 ns** |
| `icache.prefetch_addr_q[13]` (prefetch leg, flop Q) | **3.960 ns** |
| `icache.lookup_addr_ic0[13]` (mux output) | **15.493 ns** |
| `icache.lookup_grant` | 18.788 ns |

The mux output is late because of the **data** leg, not a late select: the
path reaching it starts at the IF/ID instruction register and contains the
5-deep `maj3` carry chain plus xor/xnor stages -- the ALU adder. Both
*registered* mux inputs arrive at ~3.8-4.0 ns, so the ~11.5 ns of extra
delay can only come from `addr_i`.

So the branch control leads the address by **~11.7 ns**. The assumption
holds with a very large margin.

Caveat: the icache's `branch_i` port name does not survive flattening, so
`id_stage_i.branch_set_raw` is a proxy for it. Any logic between the two
would have to burn 11.7 ns to invalidate the conclusion.

## 4. Measured: what the rewrite is actually worth

Everything above says whether a rewrite can be made *sound*. It says nothing
about whether the prize is real. That needs synthesis + P&R, so it was
measured directly with a one-line, deliberately **incorrect** upper-bound
probe: revert `lookup_grant` to the pre-`da9059f` form (which reinstates the
Bug C deadlock) and run the full flow. No correct rewrite can beat this.

Same compiler (v0.72.5, verified to reproduce the pinned release's SV
byte-for-byte before the edit), same flow, one logic line changed.

| metric | current design | upper bound | delta |
|---|---|---|---|
| WNS setup | -15.074 ns | **-12.270 ns** | **+2.804 ns** |
| TNS setup | -912,634 ns | **-289,326 ns** | **-68 %** |
| design area | 2,449,039 um2 | 2,418,304 um2 | -30,735 um2 (-1.3 %) |
| clock skew (setup) | -1.012 ns | -0.631 ns | improved |
| WNS hold | -0.550 ns | -0.597 ns | slightly worse |

Implied Fmax 39.9 -> 44.9 MHz (+12.5 %). The SV lane is at -9.660 ns
(50.9 MHz), so this closes **2.80 of the 5.41 ns lane gap -- about half**.

### The projection was wrong, and this is why the measurement mattered

The path-composition analysis suggested ~8 ns (the Arch lane's worst path
carried 20 more logic levels than the SV lane's). That figure is the depth
difference *between the two lanes' worst paths*, which is not the same as
the amount recoverable by one change. The real recovery is 2.80 ns.

The reason is visible in the new timing report: the critical path **moves**.

- The icache RAM endpoints (`data_bank_w1.rdata_o[*]`) are still there but
  are now **adder-free** (`maj3` count 0) and sit at -11.1 ns, improved from
  -14.9.
- The new worst path is different work entirely: `register_file_i.raddr_a_i[4]`
  -> `data_req_o` (an output port), -12.270 ns, and it *does* carry an adder
  (7x `maj3`).

So the icache-specific gain is ~3.9 ns (-15.07 -> -11.1), but WNS only
improves by 2.80 because a previously-hidden LSU/`data_req_o` path becomes
the binding constraint. **Further icache work buys nothing until
`data_req_o` is addressed.**

### Is it worth it?

2.80 ns WNS and -68 % TNS for reintroducing a deadlock is not a trade -- the
upper bound is not shippable. The question is whether the *conservative
candidate* (section 3) gets close to it. It should: it keeps only `branch_i`
on the grant, and `branch_i` arrives at 3.755 ns against the address's
15.493 ns. That has not been measured; it is the next experiment, and it is
one flow run.

### Method note: assessing relative quality before the route finishes

Synthesis-stage STA in this flow is **not** usable as a relative indicator,
for a fixable reason rather than an inherent one. `flow/sky130_synth.sh`'s
SDC sets a clock and zero I/O delays and nothing else -- no
`set_driving_cell`, `set_load`, `set_max_fanout` or `set_max_transition` --
so ABC maps for area with no timing target and leaves a minimum-strength
`nor2` driving 11,008 loads, which STA charges 340 ns. That is an unbuffered
netlist, not a measurement artifact.

Cheaper checkpoints that *are* usable, in increasing cost:

1. **RTL, seconds, no synthesis** -- `GRANT_INDEP` above answers "is the
   adder in this cone?" A candidate that fails it can be rejected outright.
2. **Post-CTS + global route** -- `flow.tcl` already reports slack there
   (after `estimate_parasitics -global_routing`), long before detailed
   routing. On this run: -14.571 post-placement, -11.010 post-CTS/GRT,
   -12.270 final. Note the GRT estimate was *optimistic* by 1.26 ns here, so
   treat it as a trend, not a number.
3. **Full P&R** -- ~100 min for this design. Only for the final answer.

Caveat: `flow/openroad/run.sh` writes into the same `flow/out/<lane>/`
every run, so this experiment overwrote the baseline's log, routed netlist
and SPEF. Per-experiment output directories would make staged comparisons
possible.
