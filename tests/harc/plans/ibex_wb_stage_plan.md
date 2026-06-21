# ibex_wb_stage HARC Verification Plan

## Sources Reused

- Spec: `specs/wb_stage/spec.md`
- Current cocotb basic suite: `tests/cocotb_tests/test_wb_stage_unit.py`
- Current cocotb full suite: `tests/cocotb_tests/test_wb_stage_unit_full.py`
- Existing inventory: `changes/archive/2026-05-02-port-wb_stage/tests-inventory.md`
- Pytest runners: `tests/test_wb_stage_unit.py`,
  `tests/test_wb_stage_unit_full.py`

## Reusable Components

- `WbTxn`: ID writeback fields, LSU response fields, retire metadata, and
  expected writeback class.
- WB driver/helper: drives a combinational writeback transaction and samples
  outputs after settle.
- Passive monitor: observes writeback outputs and retire counter outputs;
  reusable later when `ibex_wb_stage` is embedded in core-level benches.
- Scoreboard/reference helpers: compute write address passthrough, write-enable
  OR, masked-OR write data, retire counters, dummy flag passthrough, and
  tied-zero outputs.
- Coverage collector: covers ID write path, LSU write path, no-write path,
  retire gating, compressed retire, LSU error suppression, dummy flag, and
  constant-output checks.

## Required Scenarios

- `rf_waddr_wb_o` equals `rf_waddr_id_i`.
- `rf_we_wb_o` is OR of ID and LSU write enables.
- `rf_wdata_wb_o` selects ID data, LSU data, or zero under onehot0 producer
  assumptions.
- `ready_wb_o` is always one.
- `perf_instr_ret_wb_o` is gated by instruction count, enable, and LSU error.
- `perf_instr_ret_compressed_wb_o` is retire and compressed.
- Speculative retire outputs are tied zero.
- Dummy-instruction flag passes through.
- WS=1-only outputs are tied zero in `WritebackStage=0`.
- Full-suite parity must preserve the current exhaustive/sweep intent:
  all 32 register addresses, varied ID and LSU data patterns, all 16
  retire-counter combinations, speculative-counter sweeps, tied-zero outputs
  under varied activity, and rapid combinational input toggling.
- Invalid dual-write stimulus is only a negative/integration-constraint case;
  normal write-data parity assumes the onehot0 producer contract.
- The environment constraint `rf_we_id_i` and `rf_we_lsu_i` are onehot0 must be
  represented as a monitor/integration assertion in higher-level reuse, even
  though the unit datapath can be stimulated directly.

## Functional Coverage Goals

- Hit ID write, LSU write, and no-write classes.
- Hit every register address `0..31`.
- Hit varied ID and LSU data patterns including zero, all-ones, alternating
  bits, sign-bit-set, and mixed constants.
- Hit retire enabled/disabled, countable/non-countable, LSU error/no-error.
- Hit all 16 combinations of retire-control inputs:
  `instr_perf_count_id_i`, `en_wb_i`, `lsu_resp_valid_i`, and
  `lsu_resp_err_i`.
- Hit compressed retire true and false.
- Hit dummy flag true and false.
- Hit speculative-counter tie-offs and WS=1-only tied-zero outputs while other
  unrelated inputs toggle.
- Hit rapid combinational tracking across back-to-back input changes.
- Hit the onehot0 write-source environment constraint as an observed/assumed
  monitor condition for reusable higher-level benches.

## Code Coverage Goal

Reach 100% generated-SV code coverage for the `WritebackStage=0`,
`DummyInstructions=0`, `ResetAll=0` configuration. Code that belongs only to
`WritebackStage=1` may be excluded only if it exists in the elaborated SV and is
reviewed as configuration-dead for this scope.
