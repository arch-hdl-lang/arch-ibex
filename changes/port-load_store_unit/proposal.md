# Proposal: Port `ibex_load_store_unit` to ARCH

## Intent

This swap replaces `ibex_load_store_unit.sv` (624 LoC) with
`src/IbexLoadStoreUnit.arch`. It sits at the interface between the
ID/EX stage and the data-memory OBI bus: it computes the byte-enable
and data alignment for byte/halfword/word stores and sign-extends byte/
halfword loads, with special handling for naturally-misaligned accesses
that require two sequential OBI transactions. This is swap A9 — the
ninth and final Phase A leaf swap, following A7 (IbexFetchFifo) and
parallel with A8 (IbexPrefetchBuffer). It is the first swap to exercise
both `bus` and `thread` first-class constructs in arch-ibex.

## Scope

**In scope:**
- `MemECC = 0` only (SoC config; `MemDataWidth = 32`).
- All access widths: byte (`lsu_type_i = 2'b00`), halfword (`2'b01`),
  word (`2'b10`).
- Sign-extension for byte and halfword loads (`lsu_sign_ext_i`).
- Misaligned handling: split into two OBI transactions, `addr_incr_req_o`
  assertion and `handle_misaligned_q` bookkeeping.
- OBI handshake: `data_req_o` / `data_gnt_i` / `data_rvalid_i` protocol.
- Exception outputs: `load_err_o`, `store_err_o`, PMP errors
  (`data_pmp_err_i` / `pmp_err_q`), bus errors (`data_bus_err_i`).
- Performance counters: `perf_load_o`, `perf_store_o`.
- `lsu_req_done_o` and `lsu_resp_valid_o` handback to ID/EX.

**Out of scope:**
- `MemECC = 1` path (not used in SoC target; `MemDataWidth = 39`).
- `lockstep`, `dummy_instr`, debug triggers (Phase D).

## Construct enumeration

| Construct        | Status | Reason |
|------------------|--------|--------|
| `module`         | picked | Used as the outer container; comb alignment logic and port declarations live at module scope. |
| `thread`         | picked | The request-issue / wait-for-grant / wait-for-rvalid sequencing is naturally expressed as a sequential loop with explicit `wait until` yield points. Misaligned two-cycle path adds a conditional branch inside the same thread — exactly the dispatch-and-rejoin shape. |
| `bus`            | picked | The OBI data-memory interface (`data_req_o` / `data_gnt_i` / `data_rvalid_i` / `data_addr_o` / `data_we_o` / `data_be_o` / `data_wdata_o` / `data_rdata_i`) is a named protocol with clear initiator/target roles; wrapping it in a `bus` definition makes the port contract explicit and enables compiler-enforced direction checks. |
| `fsm`            | rejected | The LSU's sequencing (idle → req → wait-rvalid, with optional split for misaligned) is best expressed as straight-line sequential code with `wait until` yield points rather than explicit named-state transitions. `thread` carries the same state count for free. |
| `fifo`           | rejected | No FIFO-shaped push/pop queue; the LSU holds at most one outstanding transaction at a time. |
| `ram`            | N/A | Not address-indexed storage. |
| `cam`            | N/A | Not content-addressed storage. |
| `linklist`       | N/A | Not pointer-chained storage. |
| `regfile`        | N/A | Not a multi-port register array. |
| `arbiter`        | N/A | Only one requester; no arbitration needed. |
| `counter`        | N/A | No freestanding count primitive needed (misaligned tracking is a 1-bit flag, not a counter). |
| `pipeline`       | rejected | LSU has irregular latency (misaligned = 2 cycles, error = 1 cycle, normal = 1+ cycles) — a fixed-latency pipeline stage chain doesn't fit. |
| `synchronizer`   | N/A | Single clock domain. |
| `clkgate`        | N/A | No clock gating. |

## Approach

The module shell (`module IbexLoadStoreUnit`) declares:
- The OBI data-memory bus port using a locally-defined `BusObi` bus
  with signals: `req`, `gnt`, `rvalid`, `err`, `pmp_err`, `addr`,
  `we`, `be`, `wdata`, `rdata`. The LSU is the initiator; memory is
  the target.
- ID/EX-side input/output ports verbatim from the SV port list (all
  `logic` → `Bool` / `UInt<N>`).

The comb section handles:
- Address alignment (`data_addr` computation from `adder_result_ex_i`).
- Byte-enable generation (`data_be`) based on `lsu_type_i` and
  address offset `data_offset`.
- Write-data byte/halfword replication.
- Read-data extension (byte/halfword sign/zero-extend from `rdata_q` +
  `data_rdata_i` word assembly).

The thread (`LsuReq`) implements the request handshake FSM:
1. `wait until lsu_req_i` (idle).
2. Assert `data_req_o`; `wait until data_gnt_i` (request phase).
3. Update `addr_last_q`, `handle_misaligned_q`, `rdata_q` etc. via seq.
4. For misaligned: assert `addr_incr_req_o`, issue second request, wait
   for second grant.
5. `wait until data_rvalid_i` (response phase).
6. Drive `lsu_rdata_valid_o`, `lsu_resp_valid_o`, error outputs.
7. Loop to state 0 (next request).

Supporting registers: `addr_last_q`, `handle_misaligned_q`, `data_type_q`,
`data_sign_ext_q`, `data_we_q`, `rdata_offset_q`, `rdata_q`, `pmp_err_q`.

## Verification gate

**Basic gate:** `pytest tests/test_load_store_unit_unit.py tests/test_soc_lint.py tests/test_cpu_programs.py`

One cocotb test per spec Requirement (expected ~8–10). SoC lint + 4 ISR
programs must pass.

**Full regression:** `pytest tests/test_load_store_unit_unit_full.py` — every
scenario from the spec plus boundary cases (all-ones address, zero-stride
misaligned, store/load byte at offset 3).

## Verification gate caveats

The LSU's outputs (`lsu_rdata_o`, `lsu_resp_valid_o`) depend on the
`data_rvalid_i` signal returning from external memory, which is external
to the DUT. The testbench must act as a memory model: after `data_gnt_i`
is asserted by the TB, it must drive `data_rvalid_i` (and optionally
`data_rdata_i`) on the following cycle. This is a multi-cycle TB
interaction, not a pure comb test.

`addr_incr_req_o` signals an in-progress misaligned split; the TB must
detect this and serve the second request before asserting `data_rvalid_i`
for the first.

`lsu_req_done_o` goes high when the last request has been granted (i.e.,
the LSU no longer needs a new grant — the CPU can issue the next
instruction). This is distinct from `lsu_resp_valid_o` (data has returned).

## Reference

- Upstream: `~/github/ibex/rtl/ibex_load_store_unit.sv` (624 LoC)
- Package: `~/github/ibex/rtl/ibex_pkg.sv`
- Docs: `~/github/ibex/doc/03_reference/load_store_unit.rst`
- Producer neighbor: `~/github/ibex/rtl/ibex_id_stage.sv`
  (drives `lsu_we_i`, `lsu_type_i`, `lsu_req_i`, `lsu_wdata_i`,
  `lsu_sign_ext_i`, `adder_result_ex_i`)
- Consumer neighbors:
  - `~/github/ibex/rtl/ibex_wb_stage.sv` (samples `lsu_rdata_o`,
    `lsu_rdata_valid_o`)
  - `~/github/ibex/rtl/ibex_controller.sv` (samples `lsu_resp_valid_o`,
    `load_err_o`, `store_err_o`)
- Bus side: `~/github/ibex/rtl/ibex_top.sv` wires
  `data_req_o`/`data_gnt_i`/`data_rvalid_i`/`data_rdata_i` to
  `u_ram` memory model
