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
- It assumes `branch_i` arrives earlier than `addr_i`. `branch_i` is a
  control signal and `addr_i` is the adder output, so this is very likely,
  but confirm it in the timing report before relying on it.
