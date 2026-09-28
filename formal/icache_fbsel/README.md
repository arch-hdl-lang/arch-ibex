# `formal/icache_fbsel/` — fill-buffer output-selection uniqueness

**Claim:** in every reachable state of the Arch icache, at most one fill
buffer is a *candidate* for the output line. A candidate has its live
`wants_out` set and its line address equal to the output stage's
`source_line_addr`; the same-cycle beat-ready test is deliberately left out.

**Why it matters:** the output stage picks the oldest *covering* fill buffer
(candidate + beat ready), and beat-ready depends on the same-cycle bus beat
and IC1 hit, which sit on the ECP5 fetch-critical path. If the candidate is
unique, the late beat-ready term only gates validity and can move after the
select.

```bash
make build
formal/icache_fbsel/run.sh kstrong equiv lcover nocoalbmc nocoalprop noopen nogate
```

## Proof

`kstrong`: k-induction (smtbmc + boolector, depth 4) of `prop.v` (the claim)
together with the helper lemmas in `lemma.v` (`-DLEMMA -DLEMMA_STRONG`).
The lemmas, each needed to rule out an unreachable induction counterexample:

| lemma | why induction needed it |
|---|---|
| phase is never 2 | the lifecycle is 0 → 1 → 3 → 0 |
| `busy_q[fb]` ⇔ phase ≠ 0 | coalescing reads `busy_q`; a running FB with `busy_q = 0` would escape it |
| two allocated, non-stale FBs never hold the same line | the coalesce check at allocation; implies the claim |
| response queue: occupancy ≤ 8, head = `mem[rd_ptr]` | `BusRespFifo` (latency 1) consistency |
| per FB: queued entries naming it = beats granted − received (0 on a hit) | ties response routing to FB state; an idle FB has none queued |
| `beats_sent ≤ 2`, `beats_rcvd ≤ beats_sent` (no hit) | per allocated FB |
| a held bus request belongs to a running FB with `beats_sent < 2` | the grant-hold register |

Environment: `live_top.v` from `formal/icache_liveness/` (OBI-legal core and
memory, free RAM contents, several outstanding requests allowed), plus one
assumption stated inside the icache where the queue is visible: **rvalid only
when the response queue is non-empty** — the memory answers only granted,
unanswered requests (live_top's own counter states the same about the bus).
`BusRespFifo` gets formal-only observation ports (`make.py`), since Yosys's
frontend has no hierarchical references. Short invalidation walk as in the
liveness harness.

## Equivalence of the early select (`equiv`)

The output stage now picks its FB from registered state only: the open
(allocated, non-stale) FB whose line matches `source_line_addr`, which is
unique by the lemma above and is the only FB that can cover. `-DEQUIV`
rebuilds the previous select -- the minimum-age FB among the covering ones,
from formal-only `f_age` inputs wired to `fb_age_q` -- and asserts, under the
same lemmas and k-induction:

1. `raw_fb_idx` (out_done pulses, `hold_done_idx_q`) equals the old index,
   always;
2. whenever an FB covers (`fb_any`), `fb_sel_idx` equals the old index.

`fb_sel_line/addr/beats/err` reach nothing unless `fb_any` (they are muxed
under `fb_any` / `raw_is_fb`), so (1) and (2) make every output and every
register update identical to the old select.

## Recent-line buffer storage (`equiv3`)

The recent-line buffer's {line address, line data} entries live in two
`RecentLineRam` banks instead of flops: one written only by the IC1-hit
capture, one only by the completed-FB-line capture, so neither bank has a
write-data mux (FPGA flows map each to single-write-port distributed RAM).
Per entry, the flop `recent_src_hit_q[i]` records which bank wrote it last
(a live value table) and the read takes that bank. The valid bits stay in
flops.

`-DEQUIV3` keeps a shadow of the old flop storage (`f_sa`/`f_sl`), updated by
the old logic (clear writes nothing; else IC1-hit capture; else FB-line
capture), and asserts under the same lemmas and k-induction:

1. for every valid entry, the resolved buffer `f_rl_mem` (entry i from the
   bank `recent_src_hit_q[i]` names; `make.py` builds it from formal-only
   observation ports on both banks) equals the shadow;
2. `recent_covers` equals the old covers test;
3. whenever the output is valid, `raw_line` equals the old output line.

Invalid entries are never read (`recent_covers` is gated by the valid bit),
so these make every output identical to the flop version.

Mutants (all must FAIL): `hraddr` writes the hit bank at the FB index,
`nosrc` leaves the live-value bit alone on an FB-line capture (a later read
returns the hit bank's older copy), `noprio` writes the FB bank even when an
IC1-hit capture wins the cycle. `lcover` also covers an output served from
the recent-line buffer once from each bank.

## Results (2026-09-26, arch-ibex 6acb8d3 = after #17)

| task | result |
|---|---|
| `kstrong` | **PASS** — base case and induction: the claim holds for all reachable states |
| `lcover` | all three covers reached by step 6 under the same assumptions: several FBs wanting out at once, one candidate among them, a candidate whose beat is not ready (not vacuous) |
| `nocoalprop` (mutant: allocation ignores coalescing; claim only) | **FAIL at step 5** from reset |
| `nocoalbmc` (same mutant, with lemmas) | **FAIL at step 5** (two live FBs on one line) |
| `equiv` (restructured select vs the old age-minimum select) | **PASS** — base case and induction |
| `noopen` (mutant: the select ignores the open gating) | **FAIL** (BMC from reset) |
| `nogate` (mutant: lifecycle index not 0 when no FB covers) | **FAIL** (BMC from reset) |

Before #17 the induction could not close: its counterexample was a bus
response routed to an idle fill buffer, which led to finding the
single-register response tracker bug fixed there.

`cti.py <trace.vcd>` prints the fill-buffer state per step of an SBY trace.
