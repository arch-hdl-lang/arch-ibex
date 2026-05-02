# PrefetchBuffer Basic Suite — Test Inventory

Tests live in `tests/cocotb_tests/test_prefetch_buffer_unit.py`.
Pytest collector: `tests/test_prefetch_buffer_unit.py`.
One `@cocotb.test()` per spec Requirement (10 total).

- `test_request_issuance_gating` — verifies that `instr_req_o` is only asserted when `req_i` is high, the FIFO has a free slot, and the outstanding queue is not full; also verifies suppression when `req_i = 0`.
- `test_hold_until_granted` — verifies that `instr_req_o` and `instr_addr_o` remain stable across multiple cycles until `instr_gnt_i` is asserted (OBI hold-until-granted).
- `test_fetch_addr_sequencing` — verifies that the bus address advances by exactly 4 after each granted request and that every issued address has `bits[1:0] == 2'b00`.
- `test_branch_flush_and_discard` — verifies that a branch marks the outstanding in-flight slot for discard and that the subsequent `instr_rvalid_i` does not push data into the FIFO (`valid_o` stays 0).
- `test_outstanding_request_tracking` — verifies that after two back-to-back grants with no rvalid the outstanding queue is full and `instr_req_o` is suppressed even with `req_i = 1`.
- `test_fifo_backpressure_accounting` — verifies that `instr_req_o` is suppressed when the bitwise-OR of `fifo_busy` and the reversed outstanding vector is all-ones (combined FIFO + outstanding overlay full).
- `test_busy_status` — verifies that `busy_o` is 1 when `instr_req_o` is high, 1 when an outstanding slot awaits rvalid with `instr_req_o` low, and 0 only when both conditions are false.
- `test_reset_state` — verifies that after `rst_ni` is deasserted the module has no active request, no outstanding slots, and `busy_o = 0`; also verifies no spurious request while `req_i = 0`.
- `test_fifo_push_gating_on_discard` — verifies both sub-scenarios: (a) normal rvalid with discard bit clear causes `valid_o` to go high; (b) rvalid with discard bit set (branch seen) leaves `valid_o` low.
- `test_fifo_addr_forwarding` — verifies that `addr_i` is forwarded to the FIFO's `in_addr_i` on branch cycles so that after data arrives `addr_o` reflects the word-aligned branch target.
