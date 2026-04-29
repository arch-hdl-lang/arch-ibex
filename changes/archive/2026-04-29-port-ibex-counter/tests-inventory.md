# `ibex_counter` basic-suite test inventory

These are the basic-suite cocotb tests in
`tests/cocotb_tests/test_ibex_counter_unit.py`. The suite is built
with `CounterWidth = 32` and `ProvideValUpd = 1` (the most common
combination, exercises both halves of the counter and the upd output).

One test per spec Requirement (six total).

- `reset_clears_counter` — Verifies that while `rst_ni` is held low,
  `counter_val_o` reads the spec-mandated reset value, even after a
  prior write has populated the low half and even when `counter_inc_i`
  and `counter_we_i` are both asserted simultaneously. The clear is
  observed asynchronously, without waiting on a clock edge.
- `increment_advances_counter` — Verifies that with `counter_inc_i = 1`
  and both write strobes low, the counter register updates on the
  next rising edge to its immediate successor (mod 2^CounterWidth).
  Walks one increment from a known seeded value.
- `high_bits_tied_to_zero` — Verifies that bits `[63:CounterWidth]` of
  `counter_val_o` read as zero irrespective of input history,
  including when a high-half write attempts to land ones in those
  positions. Confirms the high half is silently discarded for the
  basic-suite parameter set.
- `write_beats_increment` — Verifies that when `counter_we_i` and
  `counter_inc_i` are both asserted on the same rising edge, the
  next-cycle counter value is the write data (not write data + 1) —
  no carry, the write wins.
- `half_word_write_priority` — Verifies that when both `counter_we_i`
  and `counterh_we_i` are asserted on the same rising edge,
  `counterh_we_i` wins on both halves: the high half is written from
  `counter_val_i` and the low half is preserved unchanged
  (`counter_we_i` is suppressed by the same-cycle `counterh_we_i`).
  Asserts low-half preservation under contention with a distinct bus
  payload.
- `upd_forwards_incremented_value` — Verifies that
  `counter_val_upd_o` combinationally tracks the incremented value of
  the current register (truncated to `CounterWidth`, zero-extended to
  64), independently of `counter_inc_i`, and that bits above
  `CounterWidth` of the upd output are tied to zero.
