# ibex_counter HARC Verification Plan

## Sources Reused

- Spec: `specs/counter/spec.md`
- Current cocotb basic suite: `tests/cocotb_tests/test_ibex_counter_unit.py`
- Current cocotb full suite: `tests/cocotb_tests/test_ibex_counter_unit_full.py`
- Existing inventory: `changes/archive/2026-04-29-port-ibex-counter/tests-inventory.md`
- Pytest runners: `tests/test_ibex_counter_unit.py`,
  `tests/test_ibex_counter_unit_full.py`

## Reusable Components

- `CounterCfg`: test configuration for `CounterWidth` and `ProvideValUpd`.
- `CounterOpTxn`: reset, idle, increment, low write, high write, simultaneous
  write/increment, and sample operations.
- Counter driver/helpers: reset, idle strobes, write low/high, pulse increment,
  hold increment, and sample outputs.
- Passive monitor: observes counter output, update output, write strobes,
  increment strobe, and reset.
- Scoreboard/reference model: tracks the expected truncated counter value and
  expected `counter_val_upd_o` behavior per configuration.
- Coverage collector: covers width, update gating, operation priority,
  wraparound, half-word writes, high-bit zeroing, and reset override.

## Required Scenarios

- Asynchronous reset clears the counter and overrides writes/increment.
- Increment advances and wraps for `CounterWidth` values `1`, `32`, and `64`.
- Bits above `CounterWidth` remain tied zero for sub-64 widths.
- Write priority: high write beats low write, any write beats increment.
- Low-half and high-half write behavior for width 64.
- Truncation/discard behavior for width 32 and width 1.
- `ProvideValUpd=0` hard-wires update output to zero.
- `ProvideValUpd=1` publishes current value plus one, independent of
  `counter_inc_i`, and wraps correctly.
- Full-verification expansion beyond the archived basic inventory: every
  `CounterWidth` x `ProvideValUpd` configuration must close coverage, not only
  the `CounterWidth=32`, `ProvideValUpd=1` parity suite.

## Functional Coverage Goals

- Hit `CounterWidth` values `1`, `32`, and `64`.
- Hit `ProvideValUpd` values `0` and `1`.
- Hit reset, idle, increment, low write, high write, dual write, write plus
  increment, and wraparound operation classes.
- Hit low-half boundary values `0`, `1`, all-ones, even, odd, and mixed data.
- Cross width with operation class and update-gating behavior.

## Code Coverage Goal

Reach 100% generated-SV code coverage across the merged counter parameter
regression. Any parameter-elaborated unreachable code must be reviewed per
configuration before exclusion.
