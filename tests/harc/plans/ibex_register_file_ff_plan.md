# ibex_register_file_ff HARC Verification Plan

## Sources Reused

- Spec: `specs/register_file_ff/spec.md`
- Current cocotb: `tests/cocotb_tests/test_ibex_register_file_ff_unit.py`
- Pytest runner: `tests/test_register_file_ff_unit.py`

## Reusable Components

- `RfAccessTxn`: write, read-port-A, read-port-B, dual-read, and
  read-during-write operations.
- Register-file driver/helpers: reset, write one cycle, drive read addresses,
  read both ports, and idle write controls.
- Passive monitor: observes write transactions and read responses; can be reused
  later around an embedded register-file instance via probes.
- Scoreboard/reference model: tracks architectural register state, x0 behavior,
  read-during-write old-value semantics, RV32E implemented address range, dummy
  x0 behavior, and `DataWidth`.
- Coverage collector: covers read/write addresses, x0 access, dual-read
  patterns, read/write collisions, RV32E decode, dummy x0 mux, and data
  patterns.

## Required Scenarios

- Asynchronous reset clears all implemented registers to `WordZeroVal`.
- Write-then-read round trip.
- Write-enable low holds previous value.
- Per-register decode isolates neighboring registers.
- Two combinational read ports: distinct and same-address reads.
- Read-during-write returns old value before the edge and new value after.
- x0 reads `WordZeroVal` and attempted x0 writes are dropped when
  `DummyInstructions=0`.
- Dummy x0 capture and read mux behavior when `DummyInstructions=1`.
- RV32E in-range write succeeds and out-of-range write drops.
- Non-32 `DataWidth` round trip.
- `test_en_i` has no functional influence.
- Full register/address isolation beyond sampled cocotb addresses, using
  representative address-class sweeps plus targeted neighboring-register checks.

## Functional Coverage Goals

- Hit read ports A and B independently and together.
- Hit register classes x0, low nonzero, mid, high, and RV32E out-of-range.
- Hit write enable asserted/deasserted and same-address read/write collision.
- Hit `DummyInstructions` values `0` and `1`.
- Hit `RV32E` values `0` and `1`.
- Hit `DataWidth` values `32` and at least one wider value.
- Hit nonzero `WordZeroVal`.
- Hit `test_en_i` asserted and deasserted with otherwise identical accesses.

## Code Coverage Goal

Reach 100% generated-SV code coverage across parameterized runs covering normal
RV32I, dummy instruction x0, RV32E, and wider data-width elaborations. Exclude
only code unreachable in a specific parameter elaboration after review.
