# LoadStoreUnit Specification

## Purpose

The Load Store Unit (LSU) sits between the ID/EX pipeline stage and the external data memory bus.
It receives a logical byte address and an access type (byte / halfword / word) from the execute
stage and translates each RISC-V load or store into one or two naturally-aligned 32-bit OBI
transactions. The LSU handles byte-enable generation, write-data byte-lane rotation, read-data
extraction with sign or zero extension, and the two-transaction split required for misaligned word
or halfword accesses. It reports completion to the ID/EX stage via `lsu_req_done_o` (address phase
done) and `lsu_resp_valid_o` (data phase done), and surfaces bus errors and PMP errors to the
controller as load or store exceptions.

---

## Port contract

| Direction | Name                  | Width | Description |
|---|---|---|---|
| in  | clk_i                 | 1     | System clock (rising-edge active) |
| in  | rst_ni                | 1     | Asynchronous active-low reset |
| out | data_req_o            | 1     | OBI request strobe to data memory |
| in  | data_gnt_i            | 1     | OBI grant from data memory |
| in  | data_rvalid_i         | 1     | OBI response valid from data memory |
| in  | data_bus_err_i        | 1     | Bus error accompanying data_rvalid_i |
| in  | data_pmp_err_i        | 1     | PMP access fault (combinational, valid when data_req_o is high) |
| out | data_addr_o           | 32    | Word-aligned address to data memory |
| out | data_we_o             | 1     | Write enable to data memory |
| out | data_be_o             | 4     | Byte-enable to data memory |
| out | data_wdata_o          | 32    | Write data to data memory (MemECC=0 scope) |
| in  | data_rdata_i          | 32    | Read data from data memory (MemECC=0 scope) |
| in  | lsu_we_i              | 1     | Write enable from ID/EX (1 = store, 0 = load) |
| in  | lsu_type_i            | 2     | Access width: 2'b00 = word, 2'b01 = halfword, 2'b10/11 = byte |
| in  | lsu_wdata_i           | 32    | Store data from ID/EX register file |
| in  | lsu_sign_ext_i        | 1     | Sign-extend load result (1 = signed, 0 = unsigned) |
| out | lsu_rdata_o           | 32    | Load result to ID/EX / writeback |
| out | lsu_rdata_valid_o     | 1     | Load result in lsu_rdata_o is valid this cycle |
| in  | lsu_req_i             | 1     | Access request from ID/EX (held until lsu_req_done_o) |
| in  | adder_result_ex_i     | 32    | Effective byte address from ALU |
| out | addr_incr_req_o       | 1     | Request to ID/EX to re-compute address + 4 (misaligned second transaction) |
| out | addr_last_o           | 32    | Address of most recent transaction (for mtval / AGU) |
| out | lsu_req_done_o        | 1     | Address phase complete; ID/EX may stop holding the request |
| out | lsu_resp_valid_o      | 1     | Data phase of the final transaction is complete (or PMP error) |
| out | load_err_o            | 1     | Load transaction error (bus error or PMP fault) |
| out | load_resp_intg_err_o  | 1     | Load response ECC integrity error (MemECC=0: always 0) |
| out | store_err_o           | 1     | Store transaction error (bus error or PMP fault) |
| out | store_resp_intg_err_o | 1     | Store response ECC integrity error (MemECC=0: always 0) |
| out | busy_o                | 1     | LSU has an outstanding (non-IDLE) transaction in progress |
| out | perf_load_o           | 1     | Pulse: a load request was initiated this cycle |
| out | perf_store_o          | 1     | Pulse: a store request was initiated this cycle |

**Scope note:** This specification covers `MemECC = 0` only (MemDataWidth = 32).
`load_resp_intg_err_o` and `store_resp_intg_err_o` are therefore always 0.

---

## Requirements

---

### Requirement: OBI-Handshake

The LSU SHALL implement the OBI (Open Bus Interface) protocol on the data bus: it asserts
`data_req_o` to start a transaction, holds all address-phase signals stable until `data_gnt_i`
is received, then awaits `data_rvalid_i` for the response.

#### Scenario: Immediate grant — aligned access

- GIVEN the FSM is IDLE and `lsu_req_i` is asserted
- WHEN `data_gnt_i` is asserted on the same cycle as `data_req_o`
- THEN the address phase completes in one cycle; the FSM transitions toward awaiting
  `data_rvalid_i` (returns to IDLE for aligned accesses)
- (ref: ibex_load_store_unit.sv:394–399)

#### Scenario: Delayed grant — aligned access

- GIVEN the FSM is IDLE and `lsu_req_i` is asserted
- WHEN `data_gnt_i` is NOT asserted on the first cycle
- THEN `data_req_o` remains asserted and all address-phase outputs (`data_addr_o`, `data_we_o`,
  `data_be_o`, `data_wdata_o`) remain stable until `data_gnt_i` is received
- (ref: ibex_load_store_unit.sv:399–402, WAIT_GNT state lines 449–460)

#### Scenario: Response phase

- GIVEN a grant has been received for a (non-misaligned) transaction
- WHEN `data_rvalid_i` is asserted
- THEN `lsu_resp_valid_o` is asserted and the FSM returns to IDLE
- (ref: ibex_load_store_unit.sv:509)

#### Scenario: Address-phase signal stability

- The LSU SHALL NOT change `data_addr_o`, `data_we_o`, `data_be_o`, or `data_wdata_o` between
  the assertion of `data_req_o` and the cycle on which `data_gnt_i` is received.

---

### Requirement: Word-Aligned Address

The LSU SHALL present a word-aligned address on `data_addr_o` regardless of the byte offset
of the effective address.

#### Scenario: Address alignment

- GIVEN `adder_result_ex_i` has any value A
- WHEN `data_req_o` is asserted
- THEN `data_addr_o` equals `{A[31:2], 2'b00}`
- (ref: ibex_load_store_unit.sv:517, assertion IbexDataAddrUnaligned at line 622)

---

### Requirement: Byte-Enable Generation

The LSU SHALL assert only the byte-enable lanes on `data_be_o` that correspond to the bytes
being accessed.  The byte-enable is a function of access type (`lsu_type_i`) and the byte offset
(`adder_result_ex_i[1:0]`).

#### Byte-enable reference tables

**Byte access (lsu_type_i = 2'b10 or 2'b11) — any offset, aligned only (no split):**

| Byte offset [1:0] | data_be_o |
|---|---|
| 2'b00 | 4'b0001 |
| 2'b01 | 4'b0010 |
| 2'b10 | 4'b0100 |
| 2'b11 | 4'b1000 |

**Halfword access (lsu_type_i = 2'b01) — first transaction:**

| Byte offset [1:0] | data_be_o |
|---|---|
| 2'b00 | 4'b0011 |
| 2'b01 | 4'b0110 |
| 2'b10 | 4'b1100 |
| 2'b11 (misaligned) | 4'b1000 |

**Halfword access (lsu_type_i = 2'b01) — second transaction (misaligned, offset==2'b11 only):**

| (any offset) | data_be_o |
|---|---|
| second half | 4'b0001 |

**Word access (lsu_type_i = 2'b00) — first transaction:**

| Byte offset [1:0] | data_be_o |
|---|---|
| 2'b00 (aligned)   | 4'b1111 |
| 2'b01 (misaligned) | 4'b1110 |
| 2'b10 (misaligned) | 4'b1100 |
| 2'b11 (misaligned) | 4'b1000 |

**Word access (lsu_type_i = 2'b00) — second transaction (misaligned):**

| Byte offset [1:0] | data_be_o |
|---|---|
| 2'b00 | 4'b0000 (not used) |
| 2'b01 | 4'b0001 |
| 2'b10 | 4'b0011 |
| 2'b11 | 4'b0111 |

#### Scenario: Byte store at offset 2

- GIVEN `lsu_type_i = 2'b10` (byte) and `adder_result_ex_i[1:0] = 2'b10`
- WHEN `data_req_o` is asserted
- THEN `data_be_o = 4'b0100`
- (ref: ibex_load_store_unit.sv:155–164)

#### Scenario: Aligned word access

- GIVEN `lsu_type_i = 2'b00` (word) and `adder_result_ex_i[1:0] = 2'b00`
- WHEN `data_req_o` is asserted (first / only transaction)
- THEN `data_be_o = 4'b1111`
- (ref: ibex_load_store_unit.sv:123)

#### Scenario: Misaligned word, first transaction at offset 2

- GIVEN `lsu_type_i = 2'b00` and `adder_result_ex_i[1:0] = 2'b10`
- WHEN the first OBI transaction fires
- THEN `data_be_o = 4'b1100`
- (ref: ibex_load_store_unit.sv:125)

#### Scenario: Misaligned word, second transaction at offset 2

- GIVEN `lsu_type_i = 2'b00` and original offset was 2'b10 (second transaction in progress)
- WHEN the second OBI transaction fires
- THEN `data_be_o = 4'b0011`
- (ref: ibex_load_store_unit.sv:133)

---

### Requirement: Write-Data Rotation

For store operations, the LSU SHALL rotate the 32-bit register value so that the bytes to be
written appear in the correct lanes of the 32-bit OBI write-data word, matching the active
byte-enable lanes.

#### Write-data rotation table

| Byte offset [1:0] | data_wdata_o[31:0] |
|---|---|
| 2'b00 | lsu_wdata_i[31:0] (no rotation) |
| 2'b01 | {lsu_wdata_i[23:0], lsu_wdata_i[31:24]} |
| 2'b10 | {lsu_wdata_i[15:0], lsu_wdata_i[31:16]} |
| 2'b11 | {lsu_wdata_i[7:0], lsu_wdata_i[31:8]} |

The same rotation applies to both transactions of a misaligned access. The byte enables on
each transaction ensure only the correct lanes are actually written.

#### Scenario: Store byte at offset 1

- GIVEN `lsu_we_i = 1`, `adder_result_ex_i[1:0] = 2'b01`, `lsu_wdata_i = 32'hAABBCCDD`
- WHEN `data_req_o` is asserted
- THEN `data_wdata_o = 32'hBBCCDDAA` and `data_be_o = 4'b0010`
  (byte DD appears at lane [15:8] matching be bit 1)
- (ref: ibex_load_store_unit.sv:175–182)

---

### Requirement: Read-Data Extraction

For load operations, the LSU SHALL extract the requested bytes from the 32-bit OBI read-data
word, concatenating data across two words for misaligned accesses, and sign-extend or zero-extend
the result according to `lsu_sign_ext_i`.

The extracted value is available on `lsu_rdata_o` and is valid when `lsu_rdata_valid_o` is
asserted.

#### Sub-requirement: Byte extraction

| Byte offset [1:0] | Unsigned (`lsu_sign_ext_i=0`) | Signed (`lsu_sign_ext_i=1`) |
|---|---|---|
| 2'b00 | {24'h0, data_rdata_i[7:0]} | {{24{data_rdata_i[7]}}, data_rdata_i[7:0]} |
| 2'b01 | {24'h0, data_rdata_i[15:8]} | {{24{data_rdata_i[15]}}, data_rdata_i[15:8]} |
| 2'b10 | {24'h0, data_rdata_i[23:16]} | {{24{data_rdata_i[23]}}, data_rdata_i[23:16]} |
| 2'b11 | {24'h0, data_rdata_i[31:24]} | {{24{data_rdata_i[31]}}, data_rdata_i[31:24]} |

#### Sub-requirement: Halfword extraction (aligned and misaligned)

| Byte offset [1:0] | Unsigned | Signed |
|---|---|---|
| 2'b00 | {16'h0, data_rdata_i[15:0]} | {{16{data_rdata_i[15]}}, data_rdata_i[15:0]} |
| 2'b01 | {16'h0, data_rdata_i[23:8]} | {{16{data_rdata_i[23]}}, data_rdata_i[23:8]} |
| 2'b10 | {16'h0, data_rdata_i[31:16]} | {{16{data_rdata_i[31]}}, data_rdata_i[31:16]} |
| 2'b11 (misaligned, uses 2nd word for high byte) | {16'h0, data_rdata_i[7:0], rdata_first[31:24]} | {{16{data_rdata_i[7]}}, data_rdata_i[7:0], rdata_first[31:24]} |

Where `rdata_first[31:24]` is bits [31:24] of the memory response for the first transaction,
captured in a register when the first `data_rvalid_i` is received.

#### Sub-requirement: Word extraction (aligned and misaligned)

| Byte offset [1:0] | data_rdata_ext |
|---|---|
| 2'b00 | data_rdata_i[31:0] |
| 2'b01 | {data_rdata_i[7:0], rdata_first[31:8]} |
| 2'b10 | {data_rdata_i[15:0], rdata_first[31:16]} |
| 2'b11 | {data_rdata_i[23:0], rdata_first[31:24]} |

Where `rdata_first[31:8]` (or `[31:16]`, `[31:24]`) is bits [31:8] (etc.) of the first
transaction's read data, captured when the first `data_rvalid_i` was received.

#### Scenario: Aligned byte load unsigned

- GIVEN `lsu_type_i = 2'b10`, `lsu_sign_ext_i = 0`, offset = 2'b00, `data_rdata_i = 32'hAABBCC87`
- WHEN `data_rvalid_i` is received (IDLE state, no error)
- THEN `lsu_rdata_o = 32'h00000087` and `lsu_rdata_valid_o` is asserted
- (ref: ibex_load_store_unit.sv:283–290)

#### Scenario: Misaligned halfword load signed, second response

- GIVEN `lsu_type_i = 2'b01`, `lsu_sign_ext_i = 1`, offset = 2'b11
- GIVEN first transaction returned `data_rdata_i[31:24] = 8'hA0` (which has sign bit set)
- WHEN second transaction `data_rvalid_i` arrives with `data_rdata_i[7:0] = 8'h12`
- THEN `lsu_rdata_o = 32'hFFFF12A0` (sign-extended from bit 15 of reconstructed halfword)
- (ref: ibex_load_store_unit.sv:270–275)

---

### Requirement: Misaligned Access Split

The LSU SHALL split a misaligned access into two consecutive word-aligned OBI transactions.
A misaligned access is defined as:
- A word access (`lsu_type_i = 2'b00`) where the byte offset (`adder_result_ex_i[1:0]`) is
  non-zero (2'b01, 2'b10, or 2'b11).
- A halfword access (`lsu_type_i = 2'b01`) where the byte offset is 2'b11.

#### Scenario: Misaligned access detection

- GIVEN `lsu_req_i` is asserted
- WHEN `lsu_type_i = 2'b00` and `adder_result_ex_i[1:0] != 2'b00`, OR
  `lsu_type_i = 2'b01` and `adder_result_ex_i[1:0] == 2'b11`
- THEN the LSU initiates two OBI transactions
- (ref: ibex_load_store_unit.sv:362–364)

#### Scenario: Misaligned access — first transaction fires immediately with grant

- GIVEN a misaligned access is requested and `data_gnt_i` is received on the first cycle
- WHEN `data_gnt_i` is received
- THEN `addr_incr_req_o` is asserted on the next cycle to request the second address computation,
  and the second OBI transaction begins immediately (FSM enters WAIT_RVALID_MIS)
- (ref: ibex_load_store_unit.sv:394–402, 419–447)

#### Scenario: Misaligned access — first transaction needs extra grant cycle

- GIVEN a misaligned access is requested but `data_gnt_i` is NOT received on the first cycle
- WHEN the FSM is in WAIT_GNT_MIS
- THEN `data_req_o` remains asserted; `addr_incr_req_o` is NOT yet asserted
- WHEN `data_gnt_i` is eventually received
- THEN `addr_incr_req_o` is asserted and the FSM transitions to WAIT_RVALID_MIS
- (ref: ibex_load_store_unit.sv:405–417)

#### Scenario: Misaligned access — addr_incr_req_o drives second address

- GIVEN the FSM is in WAIT_RVALID_MIS or WAIT_GNT (with a pending misaligned second transaction)
- WHEN `addr_incr_req_o` is asserted
- THEN the ID/EX stage re-computes the address as `addr_last_o + 4` and presents it on
  `adder_result_ex_i`; the LSU uses this new address for `data_addr_o` of the second transaction
- (ref: ibex_load_store_unit.sv:423, 451; ibex_id_stage.sv:305–307)

#### Scenario: First rdata captured for misaligned load

- GIVEN a misaligned load is in progress
- WHEN `data_rvalid_i` arrives for the first transaction (FSM in WAIT_RVALID_MIS or
  WAIT_RVALID_MIS_GNTS_DONE)
- THEN bits [31:8] of `data_rdata_i` are captured in an internal register for use in reconstructing
  the final load value when the second response arrives
- (ref: ibex_load_store_unit.sv:190–196, `rdata_update` assignments at lines 431, 475)

#### Scenario: addr_last_o reflects second-transaction address

- GIVEN a misaligned access is in progress and `addr_incr_req_o` is high
- WHEN the second address phase begins
- THEN `addr_last_o` is updated to the word-aligned address of the second transaction
- (ref: ibex_load_store_unit.sv:217)

#### Scenario: Misaligned access — both grants received before first rvalid

- GIVEN a misaligned access where the second grant arrives before the first `data_rvalid_i`
- THEN the FSM transitions to WAIT_RVALID_MIS_GNTS_DONE and awaits both responses in order
- (ref: ibex_load_store_unit.sv:441–446, 462–479)

---

### Requirement: lsu_req_done_o

`lsu_req_done_o` SHALL be asserted for exactly one cycle to indicate that the address phase
(last OBI grant) of the current request has been accepted and the ID/EX stage no longer needs
to hold `lsu_req_i` asserted.

#### Scenario: Aligned access, immediate grant

- GIVEN an aligned access with `data_gnt_i` on the same cycle as `data_req_o`
- WHEN the FSM transitions from IDLE back to IDLE in the same combinational evaluation
- THEN `lsu_req_done_o` is asserted that cycle
- (ref: ibex_load_store_unit.sv:487: `lsu_req_done_o = (lsu_req_i | (ls_fsm_cs != IDLE)) & (ls_fsm_ns == IDLE)`)

#### Scenario: Misaligned access, req_done after second grant

- GIVEN a misaligned access
- WHEN the second OBI grant is received (FSM transitions to IDLE from WAIT_GNT or
  WAIT_RVALID_MIS)
- THEN `lsu_req_done_o` is asserted that cycle; `lsu_req_i` may be deasserted by ID/EX

#### Scenario: lsu_req_done_o is a single-cycle pulse

- `lsu_req_done_o` SHALL be 1 only on the cycle where the next-state is IDLE and the current
  state is non-IDLE or `lsu_req_i` is high; it SHALL be 0 in all other cycles.

---

### Requirement: lsu_resp_valid_o

`lsu_resp_valid_o` SHALL be asserted for one cycle when the data phase of the **final** OBI
transaction of the current request completes (either `data_rvalid_i` is received while the FSM
is in IDLE, or a PMP error is pending while the FSM is in IDLE).

#### Scenario: Normal load/store completion

- GIVEN the FSM is in IDLE (waiting for the last rvalid)
- WHEN `data_rvalid_i` is asserted
- THEN `lsu_resp_valid_o` is asserted this cycle
- (ref: ibex_load_store_unit.sv:509)

#### Scenario: PMP error terminates transaction

- GIVEN `pmp_err_q` (the registered PMP error from the first address phase) is set and the FSM
  is in IDLE
- THEN `lsu_resp_valid_o` is asserted (no `data_rvalid_i` is needed)
- (ref: ibex_load_store_unit.sv:509)

---

### Requirement: lsu_rdata_valid_o

`lsu_rdata_valid_o` SHALL be asserted only for load transactions that complete without error.
It SHALL NOT be asserted for stores, for error responses, or when an integrity error occurs.

#### Scenario: Successful load

- GIVEN FSM is IDLE, `data_rvalid_i` is asserted, the transaction is a load (`data_we_q = 0`),
  no bus error (`data_bus_err_i = 0`), no PMP error (`pmp_err_q = 0`), no prior error
  (`lsu_err_q = 0`), and no integrity error (`data_intg_err = 0`, always true for MemECC=0)
- THEN `lsu_rdata_valid_o` is asserted and `lsu_rdata_o` holds the sign/zero-extended load result
- (ref: ibex_load_store_unit.sv:510–514)

#### Scenario: Store response

- GIVEN `data_rvalid_i` is asserted and `data_we_q = 1`
- THEN `lsu_rdata_valid_o` is NOT asserted
- (ref: ibex_load_store_unit.sv:511)

---

### Requirement: Error Reporting

The LSU SHALL assert `load_err_o` when a load transaction fails due to a bus error or PMP
fault. It SHALL assert `store_err_o` when a store transaction fails. These signals are asserted
only when `lsu_resp_valid_o` is also asserted (i.e., on the cycle the failure is reported).

A PMP error on the first transaction of a misaligned access is latched; a PMP error on the
second transaction is captured from `data_pmp_err_i` at the time of the first rvalid.  Either
error causes the final `lsu_resp_valid_o` to carry an error flag.

#### Scenario: Bus error on load

- GIVEN FSM is IDLE, `data_rvalid_i` is asserted, `data_bus_err_i` is asserted, and
  `data_we_q = 0`
- THEN `load_err_o` is asserted this cycle (and `lsu_resp_valid_o` is also asserted)
- THEN `lsu_rdata_valid_o` is NOT asserted
- (ref: ibex_load_store_unit.sv:542)

#### Scenario: PMP error on store

- GIVEN a store is in progress and `data_pmp_err_i` was asserted during the address phase
  (now latched)
- WHEN the FSM reaches IDLE
- THEN `store_err_o` is asserted alongside `lsu_resp_valid_o`
- (ref: ibex_load_store_unit.sv:508, 543)

#### Scenario: Bus error on first half of misaligned load is latched

- GIVEN a misaligned load is in progress and `data_bus_err_i` is asserted with the first
  `data_rvalid_i`
- THEN the error is latched internally; when the second response arrives, `load_err_o` is
  asserted with `lsu_resp_valid_o`
- (ref: ibex_load_store_unit.sv:430, 508)

#### Scenario: addr_last_o reflects failing address for mtval

- GIVEN a transaction fails (bus error or PMP error)
- THEN `addr_last_o` retains the address of the failing transaction and is NOT updated to a
  subsequent address; the controller uses this for the `mtval` CSR
- (ref: ibex_load_store_unit.sv:213–225: `addr_update` is NOT set when an error occurs)

---

### Requirement: busy_o

`busy_o` SHALL be asserted whenever the LSU FSM is not in the IDLE state, indicating that
an outstanding transaction is in progress.

#### Scenario: Idle

- GIVEN the FSM is in IDLE and `lsu_req_i = 0`
- THEN `busy_o = 0`
- (ref: ibex_load_store_unit.sv:555)

#### Scenario: Outstanding transaction

- GIVEN the FSM is in any state other than IDLE (WAIT_GNT, WAIT_GNT_MIS, WAIT_RVALID_MIS,
  WAIT_RVALID_MIS_GNTS_DONE)
- THEN `busy_o = 1`
- (ref: ibex_load_store_unit.sv:555)

---

### Requirement: Performance Counter Pulses

`perf_load_o` and `perf_store_o` SHALL each pulse for exactly one cycle, on the cycle in which
a new request is first presented from the IDLE state (i.e., the first `data_req_o` assertion
for each instruction).

#### Scenario: Load instruction starts

- GIVEN FSM is IDLE, `lsu_req_i` is asserted, `lsu_we_i = 0`
- WHEN the FSM processes the request in the IDLE state
- THEN `perf_load_o = 1` and `perf_store_o = 0` this cycle only
- (ref: ibex_load_store_unit.sv:391–392)

#### Scenario: Store instruction starts

- GIVEN FSM is IDLE, `lsu_req_i` is asserted, `lsu_we_i = 1`
- THEN `perf_store_o = 1` and `perf_load_o = 0` this cycle only
- (ref: ibex_load_store_unit.sv:391–392)

#### Scenario: Subsequent cycles of the same access

- GIVEN a delayed grant causes the FSM to stay in WAIT_GNT or WAIT_GNT_MIS
- THEN `perf_load_o = 0` and `perf_store_o = 0` (pulses do NOT repeat)
- (ref: ibex_load_store_unit.sv:405–460: perf signals only set in IDLE case)

---

### Requirement: Reset State

On assertion of `rst_ni` (active low), the LSU SHALL reset to the IDLE state with all
registered error flags, offset registers, and rdata registers cleared to zero.

#### Scenario: Reset

- GIVEN `rst_ni` is deasserted (logic 0)
- THEN the FSM state is IDLE, `busy_o = 0`, `addr_last_o = 0`, all internal registers cleared
- (ref: ibex_load_store_unit.sv:490–502)

---

## Integration constraints

### Producer-side constraints

The ID/EX stage (`ibex_id_stage.sv`) drives the LSU as follows:

1. **`lsu_req_i`**: Asserted when the instruction in ID/EX is a load or store AND the instruction
   is executing (`instr_executing`). The ID/EX stage holds `lsu_req_i` high until
   `lsu_req_done_o` is received. After `lsu_req_done_o`, the instruction moves to writeback and
   `lsu_req_i` may be deasserted.
   (ref: ibex_id_stage.sv:642, 800–806)

2. **`lsu_type_i`**: Encodes the RISC-V access width. Values are: 2'b00 = word (LW/SW),
   2'b01 = halfword (LH/LHU/SH), 2'b10 or 2'b11 = byte (LB/LBU/SB). This signal is stable
   while `lsu_req_i` is asserted and while the LSU is busy.

3. **`lsu_we_i`**: 1 for store instructions, 0 for loads. Stable for the same duration as
   `lsu_type_i`.

4. **`lsu_sign_ext_i`**: 1 for signed loads (LB, LH), 0 for unsigned (LBU, LHU, LW). Stable
   while the request is active.

5. **`adder_result_ex_i`**: The effective byte address computed by the ALU (base + offset).
   On the first cycle of a new request this holds the instruction's effective address.
   When `addr_incr_req_o` is asserted by the LSU (misaligned second transaction), the ID/EX stage
   switches the ALU inputs so that `adder_result_ex_i` = `addr_last_o + 4` on the next cycle.
   (ref: ibex_id_stage.sv:305–307: OP_A_FWD + IMM_B_INCR_ADDR)

6. **`lsu_wdata_i`**: The value of the source register for store instructions (forwarded from the
   register file or writeback). Stable while `lsu_req_i` is asserted.

7. **`data_req_allowed`**: Internally in ID/EX, `lsu_req_i` is only asserted when a new data
   request is permitted (no outstanding memory access from a prior instruction in writeback).
   (ref: ibex_id_stage.sv:917, 1018)

### Consumer-side constraints

**`ibex_wb_stage.sv`** (writeback stage):

1. **`lsu_rdata_o` / `lsu_rdata_valid_o`**: The writeback stage samples these to write load
   data to the register file. `rf_we_lsu_i` in the WB stage is driven by `lsu_rdata_valid_o`.
   The writeback stage accepts load data exactly when `lsu_rdata_valid_o` is asserted.
   (ref: ibex_wb_stage.sv:169)

2. **`lsu_resp_valid_i`** (connected to `lsu_resp_valid_o`): The WB stage uses this to determine
   when a load/store instruction is done (`wb_done`). While the WB stage has an outstanding
   load or store and `lsu_resp_valid_i` has not arrived, `ready_wb_o` is deasserted, stalling
   the ID/EX stage from issuing a new instruction.
   (ref: ibex_wb_stage.sv:93, 141)

3. **`lsu_resp_err_i`** (connected to `load_err_o | store_err_o`): The WB stage uses this to
   suppress the instruction-retired performance counter for errored load/store instructions.
   (ref: ibex_wb_stage.sv:161)

**`ibex_controller.sv`** (pipeline controller):

1. **`load_err_i` / `store_err_i`** (connected to `load_err_o` / `store_err_o`): The controller
   treats these as LSU exception requests (`exc_req_lsu`). When either is asserted, the controller
   initiates a pipeline flush and redirects the PC to the trap handler. With the writeback stage,
   the errored instruction is in WB so `wb_exception_o` is asserted, preventing the instruction
   currently in ID/EX from executing.
   (ref: ibex_controller.sv:218, 268)

2. **`lsu_addr_last_i`** (connected to `addr_last_o`): The controller uses this to populate the
   `mtval` CSR with the faulting address when a load/store access fault occurs.
   (ref: ibex_controller.sv:61)

3. **`lsu_req_done_o`** (consumed by `ibex_id_stage.sv`): The ID/EX stage uses this to determine
   when to advance an LSU instruction to the writeback stage. Until `lsu_req_done_o` is high,
   the instruction is held in ID/EX (`stall_mem`).
   (ref: ibex_id_stage.sv:972, 800–806)
