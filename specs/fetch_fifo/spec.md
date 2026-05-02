# FetchFifo Specification

## Purpose

`IbexFetchFifo` is the small instruction-word FIFO that sits at the head of Ibex's IF stage between the bus-side prefetch buffer (writer) and the IF stage / compressed decoder (reader). It buffers up to `DEPTH = NUM_REQS+1 = 3` 32-bit fetched memory words plus their per-word bus-error tag, and presents one 32-bit instruction-window output per cycle aligned to the *current PC*. Because instructions may be 16-bit (compressed) or 32-bit, and because a 32-bit instruction may straddle two consecutive words, the FIFO performs combinational re-alignment ("skid") across the head entry and either the next entry or the incoming bypass word, computes the corresponding error/`err_plus2` flags, and advances its internal PC by 2 or 4 each pop. Writes are clocked, the read path is purely combinational (including a feedthrough bypass when the FIFO is empty so an incoming word is immediately visible at the output), and `clear_i` flushes the entire FIFO and reseeds the PC from `in_addr_i` for the next cycle.

## Port contract

| Direction | Name | Type | Description |
|-----------|------|------|-------------|
| param | `NUM_REQS` | int (= `2`) | Number of in-flight bus requests the producer can issue. In-scope value is `2`, giving a logical FIFO depth of `NUM_REQS+1 = 3` entries. |
| param | `ResetAll` | Bool (= `0`) | If set, data and PC flops are also asynchronously reset to 0. Default in-scope value is `0`; only the `valid_q` vector is asynchronously reset. |
| input | `clk_i` | Clock | Posedge clock. |
| input | `rst_ni` | Reset (active-low) | Asynchronous active-low reset. Always clears `valid_q`; with `ResetAll=1` also clears data/err/PC flops. |
| input | `clear_i` | Bool | When high, all FIFO entries are wiped on the next clock edge AND the internal PC is reseeded from `in_addr_i[31:1]` on the next clock edge. Producer drives this from `branch_i` (`ibex_prefetch_buffer.sv:76`). |
| output | `busy_o` | UInt<NUM_REQS> (= `UInt<2>`) | Fill-level snapshot of the upper `NUM_REQS` entries of `valid_q` (i.e. `valid_q[DEPTH-1:DEPTH-NUM_REQS]`). Used by the prefetch buffer to back-pressure new bus requests (`ibex_fetch_fifo.sv:181`). |
| input | `in_valid_i` | Bool | High for one cycle when the producer is pushing a new word. Word is written into the lowest free entry on the next clock edge (or, if the FIFO is empty, observable on the same cycle via the bypass path). |
| input | `in_addr_i` | UInt<32> | Companion address for the new word. Only meaningful when `clear_i` is high — the FIFO uses `in_addr_i[31:1]` as the new internal PC seed; `in_addr_i[0]` is unused (`ibex_fetch_fifo.sv:172`). On a non-`clear_i` push the address is NOT stored per-entry; the FIFO derives the head PC by incrementing internally. |
| input | `in_rdata_i` | UInt<32> | The 32-bit instruction word being pushed. Also exposed combinationally on the bypass path when no entries are valid. |
| input | `in_err_i` | Bool | Bus-error tag for `in_rdata_i`. Stored together with the word; also visible combinationally on the bypass path when no entries are valid. |
| output | `out_valid_o` | Bool | Asserted when a complete instruction (16-bit aligned, 32-bit aligned, 16-bit unaligned, or 32-bit unaligned with both halves available) is presented. Gated for the unaligned-uncompressed case until both halves are available. |
| input | `out_ready_i` | Bool | Consumer accepts the current instruction this cycle. A pop is only effective when both `out_ready_i` and `out_valid_o` are high. |
| output | `out_addr_o` | UInt<32> | Current PC of the instruction being presented. Always halfword-aligned: bit `[0]` is hard-wired to `0`, bits `[31:1]` come from the internal PC register. |
| output | `out_rdata_o` | UInt<32> | The 32-bit instruction window at the current PC. For the aligned case this is the head entry (or bypass word). For the unaligned case (`out_addr_o[1]==1`) it is `{ next_word[15:0], head_word[31:16] }`. The lower 16 bits always carry a complete compressed instruction or the lower half of a 32-bit one; consumer only inspects `[15:0]` and `[17:16]` to determine compressed vs 32-bit. |
| output | `out_err_o` | Bool | Bus-error flag for the instruction at `out_addr_o`. For the aligned case, this is the head entry's err (or bypass err). For the unaligned case, the FIFO ORs together the err tags of the two halves the instruction spans, suppressing the second half's error when the first half is itself a compressed instruction (`ibex_fetch_fifo.sv:92-94`). |
| output | `out_err_plus2_o` | Bool | Set only in the unaligned case when the error originates from the *second* half (the `+2` half) of a 32-bit straddling instruction and the first half is itself error-free. Hard-wired to `0` in the aligned case (`ibex_fetch_fifo.sv:129`). Only required to be correct when `out_err_o` is also set in the unaligned case (`ibex_fetch_fifo.sv:97`). |

## Requirements

### Requirement: Empty-FIFO bypass and idle behavior

The module SHALL present an instruction at its output combinationally on the same cycle a producer drives `in_valid_i` while the FIFO is empty, and SHALL hold `out_valid_o` low when the FIFO is empty and `in_valid_i` is low.

#### Scenario: Idle (no entries, no bypass)

- **Given** `valid_q == 0` (FIFO empty after reset or clear) and `in_valid_i == 0`
- **When** the consumer samples outputs combinationally
- **Then** `out_valid_o == 0` (`ibex_fetch_fifo.sv:70,121,123,130`)
- **And** `out_addr_o[0] == 0` and `out_addr_o[31:1]` reflects the current internal PC

#### Scenario: Bypass push of an aligned instruction into an empty FIFO

- **Given** `valid_q == 0` and the internal PC is word-aligned (`out_addr_o[1] == 0`)
- **When** the producer drives `in_valid_i = 1`, `in_rdata_i = D`, `in_err_i = E`
- **Then** the same cycle `out_valid_o == 1`, `out_rdata_o == D`, `out_err_o == E`, `out_err_plus2_o == 0` (`ibex_fetch_fifo.sv:68-70,127-130`)

### Requirement: Single-write / single-aligned-pop FIFO discipline

The module SHALL accept a write into the lowest free entry on the next clock edge when `in_valid_i` is high without `clear_i`, and SHALL pop the head entry on the next clock edge when an aligned 32-bit instruction is consumed (`out_ready_i & out_valid_o` with `out_addr_o[1]==0` and the head not classified as compressed).

#### Scenario: Push then aligned-32 pop

- **Given** the FIFO is empty and PC is word-aligned
- **When** in cycle 0 the producer pushes `in_valid_i=1`, `in_rdata_i=D` with `D[1:0] == 2'b11` (uncompressed) and `in_err_i=0`, and the consumer holds `out_ready_i=0`
- **Then** at the start of cycle 1 entry 0 holds `D`, `valid_q[0]==1`, `out_valid_o==1`, `out_rdata_o==D`
- **And** if in cycle 1 the consumer asserts `out_ready_i=1`, then at the start of cycle 2 `valid_q[0]==0` (entry popped) and the internal PC has incremented by 4 (`ibex_fetch_fifo.sv:139,142-147,188`)

#### Scenario: Compressed aligned instruction does not pop the entry

- **Given** entry 0 holds a word `D` whose lower 16 bits decode as compressed (`D[1:0] != 2'b11`) and `out_addr_o[1]==0` and `out_err_o==0`
- **When** the consumer asserts `out_ready_i=1` for one cycle
- **Then** the internal PC advances by `2` (not `4`) and entry 0 remains valid (because `aligned_is_compressed` makes `pop_fifo` low) so the upper half of `D` becomes the next instruction at `out_addr_o[1]==1` (`ibex_fetch_fifo.sv:106-107,142-143,188`)

#### Scenario: Bypass with same-cycle pop (passthrough, not stored)

- **Given** `valid_q == 0` (FIFO empty), PC is word-aligned (`out_addr_o[1]==0`), and the consumer holds `out_ready_i = 1`
- **When** the producer drives `in_valid_i = 1, in_rdata_i = D` (bypass push) in cycle 0
- **Then** combinationally in cycle 0 `out_valid_o == 1`, `out_rdata_o == D`, AND at the start of cycle 1 `valid_q[0] == 0` — the bypass word is consumed in flight and is **not stored** into `rdata_q[0]`
- **And** the internal PC has advanced by 4 (or 2 if `D[1:0] != 2'b11`)
- **Note:** This implies a **push-then-pop** ordering invariant. Upstream computes `valid_pushed` against the pre-pop `valid_q`, then `valid_popped[i] = pop_fifo ? valid_pushed[i+1] : valid_pushed[i]` (`ibex_fetch_fifo.sv:202`). With `pop_fifo=1` and an empty FIFO, `valid_pushed[0]=1` then `valid_popped[0]=valid_pushed[1]=0`, leaving slot 0 empty. The `entry_en[i]` write-enable matches: `entry_en[0] = (valid_pushed[1] & pop_fifo) | (in_valid_i & lowest_free_entry[0] & ~pop_fifo)` excludes the bypass-and-pop case via the `~pop_fifo` AND in the second term (`ibex_fetch_fifo.sv:207-209`). A pop-then-push implementation that pushes the bypass word into `rdata_q[0]` after popping a (pre-existing or empty) head causes the **next PC** to read the just-consumed word — observable only at SoC integration time, not by isolated unit tests.

### Requirement: Depth and producer back-pressure

The module SHALL hold up to `DEPTH = NUM_REQS+1 = 3` words simultaneously, expose the upper `NUM_REQS` entries of its valid vector via `busy_o`, and SHALL NOT be pushed-into when full unless `clear_i` is asserted.

#### Scenario: busy_o reflects upper entries

- **Given** `valid_q == 3'b011` (entries 0 and 1 valid, entry 2 free) with `NUM_REQS == 2`
- **Then** `busy_o == 2'b01` — i.e. `{valid_q[2], valid_q[1]} = {0,1}` (`ibex_fetch_fifo.sv:181`)

#### Scenario: No push when full (producer-enforced invariant)

- **Given** `valid_q[DEPTH-1] == 1` (FIFO full) and `clear_i == 0`
- **Then** the producer SHALL NOT drive `in_valid_i == 1` (`ibex_fetch_fifo.sv:266-267` assertion `IbexFetchFifoPushFull`).
- **Note:** the arch implementation MAY treat the simultaneous `in_valid_i & full & ~clear_i` case as undefined behavior — the producer guarantees it does not occur (see Integration constraints).

### Requirement: Clear flushes all entries and reseeds PC

When `clear_i` is asserted, the module SHALL on the next clock edge invalidate every FIFO entry and SHALL set the internal PC to `in_addr_i[31:1]`, regardless of any concurrent `in_valid_i`.

#### Scenario: Pure clear

- **Given** `valid_q == 3'b011`, internal PC = `P`
- **When** in cycle 0 `clear_i=1`, `in_valid_i=0`, `in_addr_i = A`
- **Then** at the start of cycle 1 `valid_q == 0` and the internal PC equals `A[31:1]` (`ibex_fetch_fifo.sv:139,149,204,219`)
- **And** `out_addr_o == {A[31:1], 1'b0}` from cycle 1 onward

#### Scenario: Clear coincident with a push

- **Given** the FIFO is full (`valid_q == 3'b111`)
- **When** in cycle 0 `clear_i=1` and `in_valid_i=1` with `in_addr_i = A`
- **Then** at the start of cycle 1 `valid_q == 0` (clear wins over the push: `valid_d[i] = valid_popped[i] & ~clear_i`, `ibex_fetch_fifo.sv:204,219`) and the PC equals `A[31:1]` (`ibex_fetch_fifo.sv:149`).
- **Note:** the assertions at `ibex_fetch_fifo.sv:262-267` explicitly carve out `clear_i` from the "no push when full" rule, confirming this case is reachable.

### Requirement: Unaligned 32-bit instruction read straddles two sources

When the internal PC is half-word-aligned (`out_addr_o[1] == 1`) and the instruction at that PC is uncompressed, the module SHALL drive `out_rdata_o = { next_source[15:0], head_word[31:16] }`, where `next_source` is `rdata_q[1]` if `valid_q[1]` else the bypass `in_rdata_i`. `out_valid_o` SHALL be high only when both halves are available.

#### Scenario: Unaligned 32-bit, both halves already in FIFO

- **Given** `valid_q[1:0] == 2'b11`, `out_addr_o[1] == 1`, head's upper half `rdata_q[0][31:16]` decodes as uncompressed (`[17:16] != 2'b11`'s negation, i.e. `rdata[17:16] == 2'b11`)
- **Then** `out_rdata_o == { rdata_q[1][15:0], rdata_q[0][31:16] }` and `out_valid_o == 1` (`ibex_fetch_fifo.sv:84,102,123`)
- **And** when the consumer pops with `out_ready_i=1`, the FIFO drops entry 0 (`pop_fifo == 1` because `~aligned_is_compressed | out_addr_o[1]` simplifies to `1`) and the internal PC advances by 4 (`addr_incr_two == 0` because `unaligned_is_compressed == 0`) (`ibex_fetch_fifo.sv:142,188`).

#### Scenario: Unaligned 32-bit, second half via bypass

- **Given** `valid_q[1:0] == 2'b01`, `out_addr_o[1] == 1`, `in_valid_i == 1`, `in_rdata_i = N`
- **Then** `out_rdata_o == { N[15:0], rdata_q[0][31:16] }` and `out_valid_o == 1` (`ibex_fetch_fifo.sv:85,103`).
- **And** when the consumer pops, entry 0 is dropped and `N` is pushed into entry 0 on the next edge.

#### Scenario: Unaligned 32-bit, second half not yet available

- **Given** `valid_q[1:0] == 2'b01`, `out_addr_o[1] == 1`, head's upper half is uncompressed, and `in_valid_i == 0`
- **Then** `out_valid_o == 0` (`ibex_fetch_fifo.sv:103,123`) — the consumer must wait.

#### Scenario: Unaligned compressed instruction (no straddle needed)

- **Given** `valid_q[0] == 1`, `out_addr_o[1] == 1`, and head's upper half is compressed (`rdata_q[0][17:16] != 2'b11`) with `out_err_o == 0`
- **Then** `out_valid_o == 1` even if `valid_q[1] == 0` and `in_valid_i == 0` (`ibex_fetch_fifo.sv:120-121`) — the FIFO uses the lower-cost `valid` rather than `valid_unaligned`.
- **And** on pop (`out_ready_i=1`), entry 0 IS dropped — `pop_fifo = out_ready_i & out_valid_o & (~aligned_is_compressed | out_addr_o[1])` simplifies to `1` because `out_addr_o[1]==1`. The internal PC advances by 2 because `addr_incr_two = out_addr_o[1] ? unaligned_is_compressed : aligned_is_compressed = unaligned_is_compressed = 1` (`ibex_fetch_fifo.sv:142,188`).

### Requirement: Bus-error propagation across straddling boundaries

The module SHALL surface the bus-error flag of the half-word currently being executed, including the edge cases where a 32-bit unaligned instruction straddles two memory words with possibly different err tags, and SHALL set `out_err_plus2_o` only when an unaligned-uncompressed instruction's error originates from the second word.

#### Scenario: Aligned read with err on head entry

- **Given** `valid_q[0] == 1`, `err_q[0] == 1`, `out_addr_o[1] == 0`
- **Then** `out_err_o == 1` and `out_err_plus2_o == 0` (`ibex_fetch_fifo.sv:69,127-129`)

#### Scenario: Unaligned 32-bit, err on first half only

- **Given** `valid_q[1:0] == 2'b11`, `out_addr_o[1] == 1`, `err_q[0] == 1`, `err_q[1] == 0`, head's upper half is uncompressed
- **Then** `out_err_o == 1` and `out_err_plus2_o == 0` (`ibex_fetch_fifo.sv:92,98`)

#### Scenario: Unaligned 32-bit, err on second half only

- **Given** `valid_q[1:0] == 2'b11`, `out_addr_o[1] == 1`, `err_q[0] == 0`, `err_q[1] == 1`, head's upper half is uncompressed
- **Then** `out_err_o == 1` and `out_err_plus2_o == 1` (`ibex_fetch_fifo.sv:92,98`)

#### Scenario: Unaligned compressed, second half's err is suppressed

- **Given** `valid_q[1:0] == 2'b11`, `out_addr_o[1] == 1`, `err_q[0] == 0`, `err_q[1] == 1`, and the upper half of entry 0 decodes as a compressed instruction (`rdata_q[0][17:16] != 2'b11`, so `unaligned_is_compressed == 1`)
- **Then** `out_err_o == 0` (the second half's err is masked because the current instruction is fully contained in entry 0's upper half) and `out_err_plus2_o == 0` (`ibex_fetch_fifo.sv:92`)

#### Scenario: Unaligned 32-bit completed via bypass with err on bypass half

- **Given** `valid_q[1:0] == 2'b01`, `out_addr_o[1] == 1`, `err_q[0] == 0`, `in_valid_i == 1`, `in_err_i == 1`, head's upper half is uncompressed
- **Then** `out_err_o == 1` and `out_err_plus2_o == 1` (`ibex_fetch_fifo.sv:93-94,99`)

### Requirement: Reset state

On `rst_ni` low, the module SHALL clear `valid_q` to zero so that `out_valid_o` is `0` (modulo bypass) and `busy_o == 0`. Per-entry data/err/PC flops are NOT reset by default (`ResetAll == 0` in scope); the producer is required to issue a branch (clear) as the very first transaction so unreset state is never observed.

#### Scenario: After reset, FIFO is empty

- **Given** `rst_ni` was asserted low and is now high
- **Then** `valid_q == 0`, so `busy_o == 0` and (if `in_valid_i == 0`) `out_valid_o == 0` (`ibex_fetch_fifo.sv:228-234`).

## Integration constraints

### Consumer-side (output constraints — derived from `ibex_if_stage.sv`)

- **`out_valid_o` (`fetch_valid_raw`) is consumed as a simple AND-gated signal**, not OR-combined with another source. `ibex_if_stage.sv:337` wires `valid_o` directly to `fetch_valid_raw`, which is then qualified by branch-prediction logic and the optional skid buffer (`ibex_if_stage.sv:682,703`). The FIFO MUST hold `out_valid_o` low whenever it has nothing valid to present, including across the unaligned-uncompressed second-half wait — the consumer relies on `out_valid_o` as the sole liveness signal.
- **`out_rdata_o` (`fetch_rdata`) flows directly to the compressed decoder and skid path** (`ibex_if_stage.sv:338,683,704`). It MUST be stable while `out_valid_o` is high and `out_ready_i` is low (the consumer may hold the same instruction across multiple cycles when the ID stage stalls). The combinational definition in the FIFO already satisfies this because `rdata_q[*]`, `instr_addr_q`, and the input bypass are all stable so long as no clock edge with `entry_en` or `instr_addr_en` fires.
- **`out_err_o` (`fetch_err`) flows directly to `if_instr_bus_err`** (`ibex_if_stage.sv:688,706`). It is then OR-combined with PMP-side errors at `ibex_if_stage.sv:403`, but the FIFO is the *sole* source of bus errors on this OR — there is no other module pushing into the same wire, so the FIFO MUST present the un-masked bus-error flag for the current instruction without pre-applying any PMP/`pmp_err_if_*` qualification.
- **`out_err_plus2_o` (`fetch_err_plus2`) is consumed only at `ibex_if_stage.sv:406-407`** and is OR-combined with the PMP `+2` flag, then gated by `~pmp_err_if_i`. The consumer relies on `fetch_err_plus2` being meaningful only when `fetch_err` is also high (and only for unaligned uncompressed instructions). The FIFO comment at `ibex_fetch_fifo.sv:96-97` matches this: "Only needs to be correct when unaligned and if `err_unaligned` is set." The FIFO MAY drive `out_err_plus2_o` to a don't-care value otherwise; the consumer's gating ensures correctness.
- **`out_addr_o[0]` is consumed as `0`.** `pc_if_o` (`ibex_if_stage.sv:393`) is wired from `if_instr_addr` whose lowest bit is later examined via `if_instr_addr[1]` (e.g. `ibex_if_stage.sv:399-400,406`). The FIFO MUST hard-wire `out_addr_o[0] = 0` (as it does at `ibex_fetch_fifo.sv:169`); the consumer never expects byte alignment information here.
- **`busy_o` flows into `ibex_prefetch_buffer.sv:86` (`fifo_ready = ~&(fifo_busy | rdata_outstanding_rev)`).** The producer treats `busy_o` strictly as a fill-level snapshot of the upper `NUM_REQS` entries — the FIFO MUST NOT include entry 0 in `busy_o`, because the producer's accounting already reserves slots for outstanding-but-not-yet-returned bus requests in the lower bits.

### Producer-side (input guarantees — derived from `ibex_prefetch_buffer.sv`)

- **`in_valid_i` is gated by `~branch_discard_q[0]`** (`ibex_prefetch_buffer.sv:235`): the prefetch buffer never pushes a word that belongs to a fetch issued *before* a branch the buffer has since seen. This means the FIFO never receives stale post-branch garbage on `in_rdata_i` — every push is intended for the current fetch stream as of issue time.
- **`in_addr_i` is wired to the IF stage's `addr_i`** (`ibex_prefetch_buffer.sv:237`: `assign fifo_addr = addr_i;`), i.e. the *branch-target address*. It is therefore only semantically meaningful on the cycle the producer asserts `clear_i` (which it drives directly from `branch_i`, `ibex_prefetch_buffer.sv:76`) — that is the only cycle the FIFO uses `in_addr_i` (line 149 of the FIFO). On non-clear pushes the FIFO MAY treat `in_addr_i` as don't-care; the arch implementation MUST NOT key any state off `in_addr_i` outside the `clear_i` window.
- **`in_addr_i[0]` is unused.** The FIFO explicitly marks it `unused_addr_in` (`ibex_fetch_fifo.sv:172`); the producer does not guarantee any particular value for bit 0 (the prefetch buffer drives `addr_i` from the IF stage's branch target, which is software-supplied and may have bit 0 set for compressed-target jumps — though externally word-aligned bus requests strip it).
- **The producer does NOT guarantee `clear_i` and `in_valid_i` are mutually exclusive.** `fifo_clear` (`ibex_prefetch_buffer.sv:76`) is `branch_i`, while `fifo_valid` (`ibex_prefetch_buffer.sv:235`) is `instr_rvalid_i & ~branch_discard_q[0]`. On the cycle a branch arrives, `branch_discard_q[0]` may not yet be set (it's a registered tracker), so an `instr_rvalid_i` arriving *the same cycle* as `branch_i` can produce simultaneous `clear_i & in_valid_i`. The FIFO MUST make `clear_i` win (state goes empty, PC reseeded); the FIFO assertions `IbexFetchFifoPushPopFull` and `IbexFetchFifoPushFull` (`ibex_fetch_fifo.sv:262-267`) explicitly excuse the "full" precondition when `clear_i` is set, confirming this combination is intentional and reachable.
- **The producer guarantees the FIFO is never pushed-to when full without `clear_i`.** `valid_new_req` (`ibex_prefetch_buffer.sv:116-117`) requires `(fifo_ready | branch_i) & ~rdata_outstanding_q[NUM_REQS-1]`, where `fifo_ready` checks against the upper `NUM_REQS` of `valid_q`. Because issuing a new bus request precedes the data return that becomes a FIFO push, by the time `instr_rvalid_i` asserts there is guaranteed to be a free slot (or `branch_i` is asserted, which clears). The arch implementation MAY therefore leave the "push-when-full-without-clear" case as undefined behavior.
- **`in_err_i` is the bus's `instr_err_i`** (`ibex_prefetch_buffer.sv:101`) and is sampled together with `in_rdata_i` on the same cycle as `instr_rvalid_i`. There is no producer-side guarantee that `in_err_i == 0` when `in_valid_i == 0`; the FIFO MUST gate err observation on `in_valid_i` (which it does at lines 69 and 92-94), so the arch implementation MUST do the same.
- **No reset-cycle special case.** The CPU resets with a branch (`ibex_prefetch_buffer.sv:149-150` comment), so the very first transaction the FIFO observes after reset is `clear_i = 1` with `in_addr_i = boot_addr`. The arch implementation MAY rely on this: out-of-reset, the FIFO will see `clear_i` before any `in_valid_i`, so unreset internal `rdata_q` / `instr_addr_q` flops cannot leak into observable behavior.
