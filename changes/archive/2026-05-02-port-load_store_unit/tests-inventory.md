# Test inventory: load_store_unit basic suite

One test per spec Requirement in
`changes/port-load_store_unit/specs/load_store_unit/spec.md`.

- `test_obi_handshake` — verifies req→gnt→rvalid cycle sequencing, address-phase signal stability with a delayed grant (1 idle cycle), and that data_req_o and busy_o deassert after rvalid returns the FSM to IDLE
- `test_word_aligned_address` — verifies data_addr_o[1:0] == 0 for byte accesses at all four byte offsets (0–3) regardless of adder_result_ex_i
- `test_byte_enable_generation` — verifies data_be_o for byte (all 4 offsets), halfword (offsets 0 and 2), and aligned word (4'b1111) accesses; each case checks the first-transaction byte enable
- `test_write_data_rotation` — verifies data_wdata_o is rotated correctly for a byte store at offset 1 (0xAABBCCDD → 0xBBCCDDAA) and that data_be_o matches (4'b0010)
- `test_read_data_extraction` — verifies lsu_rdata_o contains the zero-extended byte [7:0] from data_rdata_i for an aligned byte load unsigned (spec scenario: rdata=0xAABBCC87 → 0x00000087)
- `test_misaligned_access_split` — verifies a misaligned word load (offset 2) produces two OBI transactions: addr_incr_req_o asserts after the first grant, correct byte enables on both transactions (0b1100 / 0b0011), and lsu_resp_valid_o asserts only after the second rvalid
- `test_lsu_req_done_o` — verifies lsu_req_done_o pulses for exactly one cycle on the grant cycle of an aligned store and is 0 the cycle before and after
- `test_lsu_resp_valid_o` — verifies lsu_resp_valid_o is 0 before rvalid, asserts to 1 on the rvalid cycle, and returns to 0 the following cycle for an aligned word load
- `test_lsu_rdata_valid_o` — verifies lsu_rdata_valid_o asserts for a successful aligned word load and does NOT assert for an aligned word store
- `test_error_reporting` — verifies load_err_o asserts (and lsu_rdata_valid_o does not) when data_bus_err_i is high on rvalid for a load; also verifies store_err_o asserts for a bus error on a store
- `test_busy_o` — verifies busy_o is 0 in IDLE with no request, 1 while waiting for a delayed grant (FSM in WAIT_GNT), and 0 again after the transaction completes
- `test_performance_counter_pulses` — verifies perf_load_o pulses once on the first load request cycle (and not in WAIT_GNT), and perf_store_o pulses once on the first store request cycle, with the complementary signal 0 in each case
- `test_reset_state` — verifies busy_o=0 and addr_last_o=0 immediately after rst_ni is asserted, after release, and after asserting reset mid-transaction (which must return the FSM to IDLE)
