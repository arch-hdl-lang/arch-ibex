# Proposal: Port `ibex_wb_stage` to ARCH (B2)

## Intent

This swap replaces the upstream `ibex_wb_stage.sv` (252 LoC) with
`src/IbexWbStage.arch`. The writeback stage is the third pipeline stage,
sitting between ID/EX and the register file. It routes write-back data from
either the ID/EX stage's ALU result or the LSU's load-data response to the
register file write port, and tracks pipeline readiness. This is Phase B swap
B2, after all nine Phase A leaf swaps (A1–A9) have landed on main.

## Scope

**In scope:**
- `WritebackStage == 0` only (passthrough mode). The SoC uses this fixed
  parameter value. In this mode the module is comb-only: it passes
  `rf_waddr_id_i`/`rf_wdata_id_i`/`rf_we_id_i` straight through to the
  register file, while OR-combining `rf_we_id_i` and `rf_we_lsu_i` via
  a masked-OR combiner for `rf_wdata_wb_o`/`rf_we_wb_o`. Performance
  counters, `dummy_instr_wb_o`, and `ready_wb_o` are all combinational.
- `DummyInstructions == 0` (dummy instruction path is out of scope but
  `dummy_instr_wb_o` must still be wired through for port compatibility).
- `ResetAll == 0` (out of scope since no flopped WB regs in passthrough mode).

**Out of scope:**
- `WritebackStage == 1` (flopped WB stage with `wb_valid_q`, `rf_we_wb_q`,
  `rf_waddr_wb_q`, `rf_wdata_wb_q`, `wb_instr_type_q`, etc.). All flopped
  state, `ready_wb_o` deassert/stall behavior, data forwarding path, and
  `outstanding_load/store_wb_o` logic are out of scope for this swap.
- `DummyInstructions == 1` (dummy `x0` forwarding into WB stage).
- `ResetAll == 1` (unconditional reset of all flops on rst_ni).

## Construct enumeration

| Construct      | Status | Reason |
|----------------|--------|--------|
| `module`       | **picked** | Outer container — bespoke comb routing + port glue; use directly. |
| `fsm`          | **rejected** | No multi-cycle state machine; `WritebackStage=0` is pure comb. |
| `thread`       | **rejected** | No `wait until`/`do … until` yields; every output is combinational (WritebackStage=0 path). |
| `fifo`         | **rejected** | Not a FIFO-shaped interface; no push/pop protocol on the write-data path. |
| `ram`          | **N/A** | Not address-indexed storage. |
| `cam`          | **N/A** | Not content-addressed. |
| `linklist`     | **N/A** | Not pointer-chained storage. |
| `regfile`      | **N/A** | Not a multi-port register array (that's A2). |
| `arbiter`      | **N/A** | Not request-grant arbitration. |
| `counter`      | **N/A** | Not a freestanding count primitive. |
| `pipeline`     | **rejected** | The passthrough (WS=0) doesn't add a pipeline stage; WS=1 would but is out of scope. |
| `synchronizer` | **N/A** | Single clock domain. |
| `clkgate`      | **N/A** | No clock gating in WB stage. |

## Approach

**Constructs used:** `module` + `comb` blocks only (no `seq`, no `thread`).

With `WritebackStage == 0`, all outputs are purely combinational:
- `rf_waddr_wb_o` ← `rf_waddr_id_i` (direct wire).
- `rf_wdata_wb_o` ← `(rf_we_id_i ? rf_wdata_id_i : 0) | (rf_we_lsu_i ? rf_wdata_lsu_i : 0)` (masked OR combiner; the one-hot assertion `RFWriteFromOneSourceOnly` in upstream SV makes this safe).
- `rf_we_wb_o` ← `rf_we_id_i | rf_we_lsu_i`.
- `ready_wb_o` ← `1` (constant; WS=0 never stalls).
- `outstanding_load_wb_o`, `outstanding_store_wb_o`, `rf_write_wb_o`, `pc_wb_o`, `rf_wdata_fwd_wb_o`, `instr_done_wb_o` ← all `0` (WS=0 tie-offs).
- `perf_instr_ret_wb_spec_o`, `perf_instr_ret_compressed_wb_spec_o` ← `0` (speculative counters unused in WS=0).
- `perf_instr_ret_wb_o` ← `instr_perf_count_id_i & en_wb_i & ~(lsu_resp_valid_i & lsu_resp_err_i)`.
- `perf_instr_ret_compressed_wb_o` ← `perf_instr_ret_wb_o & instr_is_compressed_id_i`.
- `dummy_instr_wb_o` ← `dummy_instr_id_i` (wire-through even in DI=0 for port compat).

The `clk_i` and `rst_ni` ports are required for port-interface compatibility
but unused in the WS=0 passthrough. ARCH requires the domain declaration.

## Verification gate

**Basic gate:** `pytest tests/test_wb_stage_unit.py tests/test_soc_lint.py tests/test_cpu_programs.py`

**Full regression:** `pytest tests/test_wb_stage_unit_full.py`

**Pass criteria:**
- All basic unit tests green (one test per spec Requirement).
- SoC lint passes (no new Verilator errors or warnings).
- All 4 ISR programs (`test_cpu_programs.py`) pass.
- Full regression suite green (all scenarios, edge cases).

## Verification gate caveats

- The module is purely combinational (WS=0). Tests should drive inputs and
  check outputs after a `Timer(1, "ns")` settle — no clock edge required for
  basic checks. Some tests will still need to run a clock for the perf counter
  signals that depend on `en_wb_i` (which is only meaningful in the context
  of a single-cycle pulse).
- `clk_i` and `rst_ni` are unused in WS=0. Verilator will emit
  `UNUSEDSIGNAL` warnings for them — suppress with `-Wno-UNUSEDSIGNAL` in
  the test runner.
- The `rf_wdata_wb_o` combiner is a masked OR, not a multiplexer: both
  sources active simultaneously would corrupt the result. The upstream
  assertion `RFWriteFromOneSourceOnly` guarantees one-hot `rf_wdata_wb_mux_we`.
  Tests should verify the combiner logic but need not test the illegal
  dual-assert case.

## Reference

- Upstream: `~/github/ibex/rtl/ibex_wb_stage.sv` (252 LoC).
- Producers into WB stage:
  - `~/github/ibex/rtl/ibex_id_stage.sv` — drives `rf_waddr_id_i`, `rf_wdata_id_i`, `rf_we_id_i`, `en_wb_i`, `instr_type_wb_i`, `pc_id_i`, `instr_is_compressed_id_i`, `instr_perf_count_id_i`, `dummy_instr_id_i`.
  - `~/github/ibex/rtl/ibex_load_store_unit.sv` — drives `rf_wdata_lsu_i`, `rf_we_lsu_i` (A9 IbexLoadStoreUnit), `lsu_resp_valid_i`, `lsu_resp_err_i`.
- Consumer:
  - `~/github/ibex/rtl/ibex_register_file_ff.sv` — downstream of `rf_waddr_wb_o`, `rf_wdata_wb_o`, `rf_we_wb_o` (A2 IbexRegisterFileFf).
  - `~/github/ibex/rtl/ibex_id_stage.sv` — samples `ready_wb_o`, `rf_write_wb_o`, `outstanding_load_wb_o`, `outstanding_store_wb_o`, `rf_wdata_fwd_wb_o`.
  - `~/github/ibex/rtl/ibex_controller.sv` — samples `outstanding_load_wb_o`, `outstanding_store_wb_o`.
  - Performance counter logic in `ibex_core.sv` — samples `perf_instr_ret_*`.
- Related reference: `~/github/ibex/doc/03_reference/pipeline_details.rst` (writeback stage section).
