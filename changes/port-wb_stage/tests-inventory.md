# Tests Inventory — IbexWbStage basic suite

File: `tests/cocotb_tests/test_wb_stage_unit.py`
Requirement mapping from `changes/port-wb_stage/specs/wb_stage/spec.md`.

| Test name | Requirement | Docstring |
|-----------|-------------|-----------|
| `req1_address_passthrough` | REQ-1 | REQ-1: rf_waddr_wb_o equals rf_waddr_id_i combinatorially. |
| `req2_we_or_id_only` | REQ-2 | REQ-2a: rf_we_wb_o = rf_we_id_i \| rf_we_lsu_i — ID only active. |
| `req2_we_or_lsu_only` | REQ-2 | REQ-2b: rf_we_wb_o = rf_we_id_i \| rf_we_lsu_i — LSU only active. |
| `req2_we_or_neither` | REQ-2 | REQ-2c: rf_we_wb_o = 0 when both enables are 0. |
| `req3_wdata_id_path` | REQ-3 | REQ-3a: rf_wdata_wb_o = rf_wdata_id_i when rf_we_id_i=1, rf_we_lsu_i=0. |
| `req3_wdata_lsu_path` | REQ-3 | REQ-3b: rf_wdata_wb_o = rf_wdata_lsu_i when rf_we_lsu_i=1, rf_we_id_i=0. |
| `req3_wdata_neither_zero` | REQ-3 | REQ-3c: rf_wdata_wb_o = 0 when neither write enable is asserted. |
| `req4_ready_always_one` | REQ-4 | REQ-4: ready_wb_o is constant 1 regardless of other inputs. |
| `req5_perf_ret_basic` | REQ-5 | REQ-5a: perf_instr_ret_wb_o — normal retire (no error). |
| `req5_perf_ret_lsu_error_suppressed` | REQ-5 | REQ-5b: perf_instr_ret_wb_o suppressed when lsu_resp_valid & lsu_resp_err. |
| `req5_perf_ret_en_wb_gating` | REQ-5 | REQ-5c: perf_instr_ret_wb_o = 0 when en_wb_i = 0. |
| `req5_perf_ret_count_gating` | REQ-5 | REQ-5d: perf_instr_ret_wb_o = 0 when instr_perf_count_id_i = 0. |
| `req6_perf_compressed_retire` | REQ-6 | REQ-6a: perf_instr_ret_compressed_wb_o asserted for compressed retired instr. |
| `req6_perf_noncompressed_no_compressed_count` | REQ-6 | REQ-6b: perf_instr_ret_compressed_wb_o = 0 for non-compressed retired instr. |
| `req7_speculative_counters_zero` | REQ-7 | REQ-7: perf_instr_ret_wb_spec_o and perf_instr_ret_compressed_wb_spec_o are always 0. |
| `req8_dummy_instr_passthrough` | REQ-8 | REQ-8: dummy_instr_wb_o equals dummy_instr_id_i combinatorially. |
| `req9_ws1_outputs_tied_zero` | REQ-9 | REQ-9: outstanding_load_wb_o, outstanding_store_wb_o, pc_wb_o, rf_write_wb_o, rf_wdata_fwd_wb_o, and instr_done_wb_o are all 0. |

## Summary

- 9 Requirements covered.
- 17 test functions in basic suite (REQ-5 has 4 sub-tests; REQ-2 has 3; REQ-3 has 3; REQ-6 has 2).
- Two-stage review is mandatory (9 Requirements ≥ 3 threshold).
