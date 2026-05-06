# spec-notes — additional ambiguities surfaced while writing tests

The spec already flags 3 ambiguities under `## Spec ambiguities flagged`
(speculative `instr_req_o` on hit, sticky `valid_o` across `branch_i`,
R-LK-4 same-line double-allocation). These additional items came up
while writing the test bodies; the test design takes the conservative
choice in each case.

## A. Tag comparison key word format

R-LK-2 says the comparison key is `{1'b1, lookup_addr_ic1[ADDR_W-1:IC_INDEX_HI+1]}`.
The tag-RAM word is `{valid, tag[20:0]}` per spec § Module interface
(IC_TAG_SIZE=22 = 1 + 21). Tests assume:

- `ic_tag_rdata_i[w][21]` is the valid bit
- `ic_tag_rdata_i[w][20:0]` is the stored tag (compared against
  `lookup_addr_ic1[31:10]` since `IC_INDEX_HI = 9`)
- a hit requires both `valid=1` AND tag bits match

If the implementation packs the valid bit at the low end (`{tag[20:0],
valid}`), the `_tag_word` helper in the test file will need to flip.
Tests use a single helper to centralise this; correcting it is a
one-line change.

## B. RAM single-port write+read serialisation

Spec § Producer-side says same-cycle write-and-read on the same RAM
bank is disallowed by `prim_ram_1p`, and the icache structurally
serialises this via R-ARB-1 / R-ARB-4. The unit harness models the
RAM as a passive responder that returns whatever the test driver
sets on `ic_*_rdata_i`; it does NOT mirror the icache's writes back
into a model that the next read could observe. This is intentional —
tests verify the icache's contract (correct request patterns,
correct arbitration), not RAM-content invariants. Cross-cycle
write-then-read consistency is implicitly covered by the
full-regression scenarios that walk the full miss → fill → hit path
across distinct lines.

## C. Speculative IC0 `instr_req_o` on miss/branch

Spec ambiguity 1 already covers the branch-into-hit case. For the
branch-into-miss path (S2), the spec says a speculative `instr_req_o`
"MAY fire" at C0. Tests do not bind to single-cycle timing of the
speculative request; they only verify that within a small window after
the branch, `instr_req_o` is asserted with a correct address.

## D. Scramble-key request edge

R-INV-3 says the cache MUST assert `ic_scr_key_req_o = 1` while in
`OUT_OF_RESET` with `ic_scr_key_valid_i = 0`. R-INV-6 reinforces the
re-request on `icache_inval_i`. The test harness checks for at least
one cycle of `ic_scr_key_req_o = 1` during the request window, not a
specific cycle count, since the FSM may transition to
`AWAIT_SCRAMBLE_KEY` in the same or next cycle.
