# PrefetchBuffer Specification

## Purpose

`PrefetchBuffer` is a 2-slot instruction-prefetch unit that sits between Ibex's IF stage and the
OBI-compliant instruction bus. It issues word-aligned bus requests speculatively ahead of the
instruction stream, buffers up to two outstanding in-flight requests, discards stale responses on a
branch, and feeds completed instruction words into the internal `IbexFetchFifo`. The module
decouples the bus latency from the pipeline: while the bus resolves a request, the IF stage can
continue consuming instructions already held in the downstream FIFO. On a branch the FIFO is
flushed, any in-flight requests are marked for discard, and prefetching resumes from the new PC.
The module presents the processor side of the OBI request/grant/rvalid handshake; it does not
implement the FIFO itself (that is `IbexFetchFifo`).

---

## Port contract

| Direction | Name            | Type       | Description |
|-----------|-----------------|------------|-------------|
| param     | `NUM_REQS`      | Int = `2`  | Number of outstanding bus-request slots. Fixed at `2`. |
| input     | `clk_i`         | Clock      | Posedge clock. |
| input     | `rst_ni`        | Reset (active-low) | Asynchronous active-low reset. Clears all control state. Address registers are NOT reset (CPU resets with a branch, so unreset address state is never observed). |
| input     | `req_i`         | Bool       | Fetch enable from the IF stage. When low the module SHALL NOT issue new bus requests. |
| input     | `branch_i`      | Bool       | Branch strobe from the IF stage. When high, the module SHALL flush the FIFO, load the next fetch address from `addr_i`, and mark all in-flight requests for discard. Combinational; valid for one cycle. |
| input     | `addr_i`        | UInt<32>   | Branch target address. Meaningful only when `branch_i` is high; used as the new fetch base address and as the PC seed forwarded to the FIFO's `in_addr_i`. |
| input     | `ready_i`       | Bool       | Downstream (FIFO output) is ready to accept an instruction this cycle. Wired to the FIFO's `out_ready_i`. |
| output    | `valid_o`       | Bool       | A complete instruction is available at the FIFO output. Wired from the FIFO's `out_valid_o`. |
| output    | `rdata_o`       | UInt<32>   | Instruction word at the FIFO output. Wired from the FIFO's `out_rdata_o`. |
| output    | `addr_o`        | UInt<32>   | PC of the instruction at the FIFO output. Wired from the FIFO's `out_addr_o`. |
| output    | `err_o`         | Bool       | Bus-error flag for the instruction at the FIFO output. Wired from the FIFO's `out_err_o`. |
| output    | `err_plus2_o`   | Bool       | Set when the bus error for the current unaligned 32-bit instruction originates from its second half. Wired from the FIFO's `out_err_plus2_o`. |
| output    | `instr_req_o`   | Bool       | OBI request valid. Held high until `instr_gnt_i` is asserted. |
| input     | `instr_gnt_i`   | Bool       | OBI grant: the bus has accepted the outstanding request. After this the module MAY change `instr_addr_o`. |
| output    | `instr_addr_o`  | UInt<32>   | Word-aligned fetch address. Bits `[1:0]` are always `2'b00`. MUST remain stable from the cycle `instr_req_o` is first asserted until the cycle `instr_gnt_i` is high. |
| input     | `instr_rdata_i` | UInt<32>   | Bus return data. Valid when `instr_rvalid_i` is high. |
| input     | `instr_err_i`   | Bool       | Bus error tag for `instr_rdata_i`. Sampled together with `instr_rvalid_i`. |
| input     | `instr_rvalid_i`| Bool       | OBI rvalid: one-cycle pulse per granted request, in order. Triggers dequeue of the oldest outstanding-request slot. |
| output    | `busy_o`        | Bool       | High while at least one request is outstanding OR while `instr_req_o` is high. Used by the IF stage to suppress halts. |

---

## Requirements

### Requirement: Request Issuance Gating

The module SHALL issue a bus request (`instr_req_o` high) if and only if ALL of the following hold:
(a) `req_i` is high, AND
(b) there is room for the returned data — either the FIFO has a free slot (accounting for in-flight
    requests) or a branch flush is in progress, AND
(c) the outstanding-request queue is not full (fewer than `NUM_REQS` requests are awaiting rvalid).

A request that was not granted in the cycle it was first raised SHALL be held stable (address and
valid strobe) until `instr_gnt_i` is asserted. Once granted, the module SHALL retract `instr_req_o`
on the next cycle unless the gating conditions still permit a new request.

#### Scenario: New request issued when FIFO has space and no pending request

- GIVEN `req_i = 1`, the FIFO reports at least one free slot (`fifo_ready` is high), and fewer than
  `NUM_REQS` responses are outstanding
- WHEN the module samples these inputs on a rising clock edge
- THEN `instr_req_o` is asserted combinationally the same cycle with `instr_addr_o` carrying the
  next fetch address (word-aligned)
- (ref: ibex_prefetch_buffer.sv:116-117, 261)

#### Scenario: Request suppressed when FIFO is full and no branch

- GIVEN `req_i = 1`, the FIFO's upper `NUM_REQS` entries are all occupied and there are matching
  outstanding requests (so `fifo_ready` is low), and `branch_i = 0`
- WHEN the module evaluates its combinational logic
- THEN `instr_req_o` is low — no new bus request is issued
- (ref: ibex_prefetch_buffer.sv:86, 116-117)

#### Scenario: Branch forces request issuance regardless of FIFO fill

- GIVEN `req_i = 1`, the FIFO is full, and `branch_i = 1`
- WHEN the module evaluates its combinational logic this cycle
- THEN `instr_req_o` MAY be asserted this cycle (because `branch_i` overrides the FIFO-full
  back-pressure term) provided the outstanding-request queue is not already full
- (ref: ibex_prefetch_buffer.sv:116: `(fifo_ready | branch_i)`)

---

### Requirement: OBI Hold-Until-Granted

Once a bus request is raised (`instr_req_o` high), the module SHALL hold both `instr_req_o` and
`instr_addr_o` stable on every cycle until `instr_gnt_i` is high. A new request MUST NOT replace
the current address while the current grant is still pending.

#### Scenario: Ungrated request held through back-to-back cycles

- GIVEN `instr_req_o` was asserted in cycle N with address `A`, and `instr_gnt_i` remained low in
  cycles N and N+1
- WHEN cycle N+1 is evaluated
- THEN `instr_req_o` is still high and `instr_addr_o == A`
- (ref: ibex_prefetch_buffer.sv:122, 144-147, 191-195)

#### Scenario: Request released after grant

- GIVEN `instr_req_o` is high with address `A`, and `instr_gnt_i` goes high in cycle N
- WHEN the module evaluates cycle N+1
- THEN `instr_req_o` reflects the fresh gating conditions (MAY be low if no new request is
  warranted), and `instr_addr_o` MAY change to the next sequential fetch address
- (ref: ibex_prefetch_buffer.sv:122, 262)

---

### Requirement: Fetch Address Sequencing

The module SHALL track the next address to fetch. On a branch, the fetch address SHALL be loaded
from `addr_i`. Thereafter, each time a new bus request is issued (not a re-issue of a held request)
the fetch address SHALL advance by 4. The address issued on the bus SHALL always be word-aligned
(bits `[1:0]` forced to `2'b00`).

A separate "held address" is latched when a new request is first raised and is used to replay the
same address on subsequent cycles until the request is granted, ensuring address stability under
back-pressure.

#### Scenario: Sequential prefetch

- GIVEN the current fetch address is `F` (word-aligned) and a new request was just issued at `F`
- WHEN the grant is received this cycle and gating conditions permit a new request immediately
- THEN the next bus address SHALL be `F + 4` (word-aligned)
- (ref: ibex_prefetch_buffer.sv:170-172)

#### Scenario: Branch redirects fetch address

- GIVEN `branch_i = 1` and `addr_i = T` in cycle N
- WHEN the next new request is issued (cycle N or N+1 depending on gating)
- THEN the bus address SHALL be `{T[31:2], 2'b00}` (word-aligned branch target)
- (ref: ibex_prefetch_buffer.sv:170, 195)

#### Scenario: Held-request address does not advance

- GIVEN a request is outstanding (held, not yet granted) with address `H`
- WHEN `branch_i = 0` and `instr_gnt_i = 0`
- THEN `instr_addr_o == H` on every cycle until `instr_gnt_i` is asserted
- (ref: ibex_prefetch_buffer.sv:144, 191)

---

### Requirement: Branch Flush and Discard

On `branch_i` the module SHALL:
1. Clear the FIFO on the same cycle (by asserting the FIFO's `clear_i`).
2. Mark every currently in-flight request (requests that have been granted but whose `instr_rvalid_i`
   has not yet arrived) with a "discard" bit.
3. If a request is pending grant at the same cycle as `branch_i`, mark that request for discard too.

Any `instr_rvalid_i` arriving while the oldest outstanding slot's discard bit is set SHALL be
dropped — its data MUST NOT be pushed into the FIFO.

#### Scenario: In-flight request discarded after branch

- GIVEN one request is outstanding (granted, awaiting rvalid) and `branch_i` pulses in cycle N
- WHEN `instr_rvalid_i` arrives in a later cycle while the discard bit for that slot is set
- THEN the response data is discarded — the FIFO is NOT pushed
- (ref: ibex_prefetch_buffer.sv:210-212, 235)

#### Scenario: Ungrated request cancelled by branch

- GIVEN `instr_req_o` was asserted but `instr_gnt_i` was low, and `branch_i` pulses this cycle
- WHEN the request is subsequently granted (the bus may still grant it)
- THEN the module SHALL track this as a discardable outstanding slot (the discard-pending flag
  propagates at grant time)
- (ref: ibex_prefetch_buffer.sv:125, 210)

#### Scenario: Branch with no in-flight requests

- GIVEN no requests are outstanding and `branch_i` pulses
- WHEN the module processes the next cycle
- THEN the FIFO is cleared, the fetch address is loaded from `addr_i`, and the discard state
  remains all-zero (nothing to discard)
- (ref: ibex_prefetch_buffer.sv:76, 170, 243-254)

---

### Requirement: Outstanding Request Tracking

The module SHALL maintain a shift-register of `NUM_REQS = 2` slots to track which requests are
awaiting `instr_rvalid_i`. A slot is set when a request is granted (`instr_gnt_i` high while
`instr_req_o` high). The oldest outstanding slot is always at index 0. When `instr_rvalid_i`
arrives, all slots shift down by one (the oldest is consumed). A companion discard-flag register
mirrors the same structure and is set on a per-slot basis whenever a branch arrives while that slot
is live.

The module SHALL NOT issue a new bus request when all `NUM_REQS` outstanding slots are already
occupied (i.e. when the highest-index slot is valid).

#### Scenario: Two back-to-back requests accumulate in the queue

- GIVEN one request was granted in cycle N and a second was granted in cycle N+1, with no rvalid
  arriving yet
- THEN both slots are occupied; `instr_req_o` SHALL be low (queue full, cannot issue more) even if
  `req_i = 1` and FIFO has space
- (ref: ibex_prefetch_buffer.sv:116-117, 201-226)

#### Scenario: rvalid shifts the queue down

- GIVEN both slots are occupied (oldest in slot 0, newer in slot 1)
- WHEN `instr_rvalid_i` is high for one cycle
- THEN slot 0 is consumed, slot 1 shifts to slot 0, and the queue now has one free slot
- (ref: ibex_prefetch_buffer.sv:229-232)

---

### Requirement: FIFO Back-Pressure Accounting

The module SHALL compute available FIFO headroom by overlaying the FIFO's fill-level vector
(`fifo_busy`, which is `busy_o` from `IbexFetchFifo`) with the outstanding-request vector reversed.
This prevents issuing a request for which there would be no FIFO slot to receive the data once the
response arrives.

Specifically, a new request is only permitted when the bitwise-OR of `fifo_busy` and the reversed
outstanding vector is NOT all-ones — i.e., at least one slot in the combined view is free.

#### Scenario: FIFO half-full and one request outstanding — issue permitted

- GIVEN `fifo_busy = 2'b01` (one FIFO slot used) and one outstanding request (reversed outstanding
  vector = `2'b10`), so bitwise-OR = `2'b11`
- THEN `fifo_ready` is low — the module SHALL NOT issue a new request (combined overlay shows no
  free slot)
- (ref: ibex_prefetch_buffer.sv:79-86)

#### Scenario: FIFO empty and no outstanding requests — issue permitted

- GIVEN `fifo_busy = 2'b00` and no outstanding requests
- THEN `fifo_ready` is high — the module MAY issue a request if other gating conditions hold
- (ref: ibex_prefetch_buffer.sv:86)

---

### Requirement: Busy Status

`busy_o` SHALL be high whenever any outstanding request is pending (at least one slot in the
outstanding tracker is set) OR when `instr_req_o` is currently high. `busy_o` SHALL be low only
when no request is in flight and no bus request is currently being asserted.

#### Scenario: Busy while request is asserted

- GIVEN `instr_req_o` is high (request pending grant)
- THEN `busy_o == 1` regardless of whether any slot in the outstanding tracker is set
- (ref: ibex_prefetch_buffer.sv:67)

#### Scenario: Busy while awaiting rvalid

- GIVEN `instr_req_o` is low (no current request) but at least one outstanding tracker slot is set
- THEN `busy_o == 1`
- (ref: ibex_prefetch_buffer.sv:67)

#### Scenario: Idle after all responses returned

- GIVEN the outstanding tracker is all-zero and `instr_req_o` is low
- THEN `busy_o == 0`
- (ref: ibex_prefetch_buffer.sv:67)

---

### Requirement: Reset State

After `rst_ni` is deasserted low, the module SHALL initialize the following state:
- Request-pending flag: cleared (no active bus request)
- Discard-request flag: cleared
- Outstanding-request tracker: all slots clear (no pending responses)
- Discard-branch tracker: all slots clear

The fetch address and held-address registers are NOT reset (the comment at
`ibex_prefetch_buffer.sv:149` notes "CPU resets with a branch, so no need to reset these
addresses"). The very first IF-stage operation after reset SHALL be a branch that loads `addr_i`,
making the unreset address state unobservable.

#### Scenario: Post-reset state, before first branch

- GIVEN `rst_ni` was low and is now released
- THEN `instr_req_o == 0`, the outstanding tracker is all-zero, `busy_o == 0`
- AND no bus request is issued until `req_i` and valid gating conditions are met
- (ref: ibex_prefetch_buffer.sv:243-254)

---

### Requirement: FIFO Push Gating on Discard

The module SHALL push a returned data word into the FIFO if and only if `instr_rvalid_i` is high
AND the oldest outstanding slot's discard bit is NOT set. If the discard bit is set the response
is silently dropped.

#### Scenario: Normal rvalid push (no discard)

- GIVEN `instr_rvalid_i = 1`, the oldest outstanding slot's discard bit = 0
- THEN `in_valid_i` to the FIFO is asserted high, causing the word to be pushed
- (ref: ibex_prefetch_buffer.sv:235)

#### Scenario: Discarded rvalid (branch was seen)

- GIVEN `instr_rvalid_i = 1`, the oldest outstanding slot's discard bit = 1
- THEN `in_valid_i` to the FIFO is low — the word is dropped, FIFO state is unaffected
- (ref: ibex_prefetch_buffer.sv:235)

---

### Requirement: FIFO Address Forwarding

The module SHALL forward `addr_i` (the current branch target from the IF stage) directly to the
FIFO's `in_addr_i` port on every cycle. The FIFO only consumes this value on cycles where
`clear_i` (i.e., `branch_i`) is high. On non-branch cycles the FIFO ignores `in_addr_i`.

#### Scenario: Branch address reaches FIFO

- GIVEN `branch_i = 1` and `addr_i = T`
- WHEN the FIFO processes `clear_i` this cycle
- THEN the FIFO's internal PC is seeded from `T[31:1]` on the next clock edge
- (ref: ibex_prefetch_buffer.sv:76, 237)

---

## Integration constraints

### Consumer-side (output constraints — derived from ibex_if_stage.sv)

- **`valid_o` (`fetch_valid_raw`) drives the IF stage's fetch-valid signal** (`ibex_if_stage.sv:337`).
  The IF stage squashes it further with a branch-mispredict flag (`ibex_if_stage.sv:267`) but
  otherwise treats it as the sole "instruction available" signal. The module MUST hold `valid_o`
  low whenever no complete instruction is ready.

- **`rdata_o` (`fetch_rdata`) feeds both the compressed decoder and the branch-predictor / skid
  buffer** (`ibex_if_stage.sv:338, 683, 704`). The module MUST hold `rdata_o` stable for any cycle
  where `valid_o` is high and `ready_i` is low (the consumer stalls across multiple cycles without
  changing anything, so the output must not flicker).

- **`addr_o` (`fetch_addr`) is used as the PC for the current IF-stage instruction** and is passed
  downstream to the ID stage and to `pc_if_o` (`ibex_if_stage.sv:393`). Bit `[0]` is expected to
  be hard-wired to `0` (the FIFO guarantees this). Bit `[1]` is examined for misalignment
  (`ibex_if_stage.sv:399-400, 406`).

- **`err_o` (`fetch_err`) flows to `if_instr_bus_err`** (`ibex_if_stage.sv:688, 706`), which is
  then OR-combined with PMP errors (`ibex_if_stage.sv:403`). The module MUST present the raw
  bus-error flag without masking — PMP qualification happens in the IF stage.

- **`err_plus2_o` (`fetch_err_plus2`) is OR-combined with the PMP `+2` error flag**
  (`ibex_if_stage.sv:406-407`) and is only meaningful when `err_o` is also set and the instruction
  is unaligned uncompressed. The module MAY drive `err_plus2_o` to any value when `err_o` is low
  or the instruction is aligned.

- **`busy_o` (`prefetch_busy`) drives `if_busy_o`** (`ibex_if_stage.sv:394`), which the wider
  pipeline uses to inhibit clock-gating or stall decisions. It MUST be high any time the module
  cannot guarantee that all outstanding fetches have been resolved.

- **`instr_req_o` and `instr_addr_o` are passed unmodified to the instruction bus**
  (`ibex_if_stage.sv:298-300, 344-346`). The IF-stage asserts that `instr_addr_o[1:0] == 2'b00`
  whenever `instr_req_o` is high (`ibex_if_stage.sv:837`).

### Producer-side (input guarantees — derived from ibex_if_stage.sv)

- **`req_i` is driven directly from the IF stage's `req_i` input** (`ibex_if_stage.sv:329, 39`). It
  reflects the global instruction-fetch enable; the module MUST treat it as the master on/off gate
  for issuing new requests.

- **`branch_i` (`prefetch_branch`) is the OR of `pc_set_i` and `predict_branch_taken`**
  (`ibex_if_stage.sv:262, 391`). It is a single-cycle combinational pulse; the module MUST latch
  the branch target from `addr_i` on the same cycle.

- **`addr_i` (`prefetch_addr`) is a mux output selecting among branch target, exception PC, mepc,
  depc, and boot address** (`ibex_if_stage.sv:216-228, 263`). It is only meaningful when
  `branch_i` is high.

- **`ready_i` (`fetch_ready`) is gated by the ID stage's readiness, any dummy-instruction stall,
  and (with branch prediction) skid-buffer occupancy** (`ibex_if_stage.sv:691-692, 707-708`). The
  module MUST NOT consume an output word unless `ready_i` is high (it is the FIFO's `out_ready_i`).

- **`instr_gnt_i`, `instr_rvalid_i`, `instr_rdata_i`, and `instr_err_i` are OBI bus signals**
  passed straight through from the instruction memory/cache interface (`ibex_if_stage.sv:343-350`).
  `instr_rvalid_i` fires exactly once per granted request (upstream doc:
  `instruction_fetch.rst:62`). The module MUST NOT make any assumption about the number of cycles
  between grant and rvalid.

### Internal FIFO interface (derived from ibex_fetch_fifo.sv and specs/fetch_fifo/spec.md)

The following bullets describe what this module guarantees to — or assumes from — `IbexFetchFifo`.
Items already stated verbatim in `specs/fetch_fifo/spec.md §Integration constraints — Producer
side` are cross-referenced rather than re-derived.

- **`in_valid_i` gated by branch-discard** — the module drives `in_valid_i = instr_rvalid_i &
  ~discard_bit_for_oldest_slot`. Per A7 spec §Integration constraints — Producer side: "`in_valid_i`
  is gated by `~branch_discard_q[0]`" (`ibex_prefetch_buffer.sv:235`).

- **`in_addr_i` always wired to `addr_i`** — per A7 spec §Integration constraints — Producer side:
  "`in_addr_i` is wired to the IF stage's `addr_i`" (`ibex_prefetch_buffer.sv:237`). Only
  meaningful to the FIFO when `clear_i` is asserted; on non-branch cycles the FIFO ignores it.

- **`clear_i` and `in_valid_i` may coincide** — per A7 spec §Integration constraints — Producer
  side: "The producer does NOT guarantee `clear_i` and `in_valid_i` are mutually exclusive." When
  `branch_i` arrives the same cycle as `instr_rvalid_i`, `branch_discard_q[0]` may not be set yet
  (it is a registered tracker), so both `clear_i` and `in_valid_i` can be high simultaneously.
  The FIFO MUST let `clear_i` win (entries cleared, PC reseeded).

- **FIFO never pushed when full without `clear_i`** — per A7 spec §Integration constraints —
  Producer side: "The producer guarantees the FIFO is never pushed-to when full without `clear_i`."
  The outstanding-request accounting (`fifo_ready`) ensures a free slot exists before a request is
  issued, so by the time the response arrives there is always room.

- **`in_err_i` is the bus's `instr_err_i`** — per A7 spec §Integration constraints — Producer
  side: "`in_err_i` is the bus's `instr_err_i`" (`ibex_prefetch_buffer.sv:101`). The module passes
  `instr_err_i` directly; no masking is applied before handing it to the FIFO.

- **No reset-cycle special case** — per A7 spec §Integration constraints — Producer side: "No
  reset-cycle special case — CPU resets with a branch." The FIFO will always see `clear_i` before
  any `in_valid_i`, so unreset FIFO data flops are never exposed.

- **`fifo_busy` (FIFO's `busy_o`) is consumed as a back-pressure signal** — the module reads
  `fifo_busy` every cycle and ORs it (bitwise) with the reversed outstanding-request vector to
  compute `fifo_ready`. The FIFO MUST faithfully reflect the upper `NUM_REQS` entries of its
  fill-level vector in `busy_o` without latency (`ibex_fetch_fifo.sv:181`).
