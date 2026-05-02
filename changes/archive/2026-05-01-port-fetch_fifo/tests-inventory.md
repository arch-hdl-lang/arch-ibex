# Basic test inventory — IbexFetchFifo

One cocotb test per spec Requirement (7 tests). Each walks the single
most representative Scenario for that Requirement, with assertions
derived directly from the spec text.

- `empty_fifo_idle_then_bypass` — Req 1: empty FIFO with `in_valid_i=0`
  holds `out_valid_o=0`; same-cycle bypass of an aligned word with
  `in_valid_i=1` drives `out_valid_o=1`, `out_rdata_o=D`, `out_err_o=E`,
  `out_err_plus2_o=0`, `out_addr_o[0]=0`.
- `push_then_aligned_pop` — Req 2: one push of an uncompressed word
  into an empty, aligned FIFO; entry 0 becomes valid and presents the
  word, then a one-cycle pop drains entry 0 and PC advances by 4.
- `busy_reflects_upper_entries` — Req 3: with `NUM_REQS=2`, after two
  pushes `valid_q==3'b011` and `busy_o==2'b01` (i.e. upper 2 entries).
- `pure_clear_flushes_and_reseeds` — Req 4: `clear_i=1` with
  `in_addr_i=A` invalidates every entry on the next edge and reseeds
  the internal PC to `A[31:1]`; `out_addr_o[0]` stays 0 (bit-0 of
  `in_addr_i` is discarded).
- `unaligned_32bit_both_halves_in_fifo` — Req 5: half-word-aligned PC
  (`out_addr_o[1]==1`) with both halves valid → `out_rdata_o ==
  {rdata_q[1][15:0], rdata_q[0][31:16]}`, `out_valid_o=1`; pop drops
  entry 0 and PC += 4.
- `err_unaligned_second_half_only_sets_err_plus2` — Req 6: unaligned
  uncompressed straddle with err on second half only → `out_err_o=1`
  AND `out_err_plus2_o=1` (the only mode in which the consumer reads
  `out_err_plus2_o`).
- `reset_state_clears_valid_and_busy` — Req 7: async-active-low
  `rst_ni` clears `valid_q` so `busy_o=0` and `out_valid_o=0` (with
  `in_valid_i=0`), independent of unreset data/PC flops.
