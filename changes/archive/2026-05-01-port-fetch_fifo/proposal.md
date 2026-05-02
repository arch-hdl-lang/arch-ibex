# Proposal: Port `ibex_fetch_fifo` to ARCH

## Intent

Replace upstream `ibex_fetch_fifo.sv` (269 LoC) — the small instruction
buffer between the bus-side prefetch buffer and the IF stage — with an
ARCH equivalent. Sits at the head of the IF stage, holds up to
`NUM_REQS+1 = 3` 32-bit fetched memory words plus per-word bus-error
flags, and presents one re-aligned instruction window per cycle to the
compressed decoder.

Seventh leaf-module swap (A7) and the first IF-stage swap. Combinational
read path with clocked write — clear-on-branch is load-bearing for
correct PC reseed. Gateway to porting `ibex_prefetch_buffer` and
`ibex_if_stage` themselves later in Phase A/B.

## Scope

**In scope** — `RV32M = RV32MFast`, default Ibex parameters:

- `NUM_REQS = 2` (default), giving FIFO depth `3`.
- `ResetAll = 0` (default) — only `valid_q` is asynchronously reset; data
  / err / PC flops are unreset (the producer always issues a clear as
  the first transaction post-reset, so unreset state never leaks).
- Empty-FIFO bypass path: an incoming word is observable at the output
  on the same cycle it's pushed.
- Aligned and unaligned (half-word PC) read positions, including
  unaligned 32-bit instructions that straddle two memory words.
- 16-bit (compressed) and 32-bit (uncompressed) instruction
  classification at the head, driving `pop_fifo` and `addr_incr_two`.
- Bus-error propagation including the `err_plus2` corner (error on the
  second half of a straddling 32-bit instruction) and the
  unaligned-compressed err-suppression case.
- Clear-coincident-with-push semantics (clear wins, PC reseeded from
  `in_addr_i`).

**Out of scope**:

- `ResetAll = 1` configuration. If/when downstream uses it, add as a
  separate Requirement and parameter sweep.
- `NUM_REQS != 2`. The width of `busy_o` and the depth of `valid_q` are
  parameterized in upstream; the in-scope parameter is fixed at 2.

## Construct enumeration

| Construct      | Status   | Reason |
|----------------|----------|--------|
| `module`       | picked   | Output mux (head + next + bypass), per-entry err with corner suppression, internal PC, and clear-reseed are all bespoke — handle directly in `seq` + `comb`. |
| `fsm`          | rejected | No multi-cycle state-machine sequencing; every cycle is one transition driven by current inputs and state. |
| `thread`       | rejected | No mid-walk yield / wait; combinational read path can't ride a thread's dead-skid sub-state. |
| `fifo`         | rejected | `pop_data` exposes only the head, but `out_rdata_o` reads head + next + bypass simultaneously to handle unaligned 32-bit straddles. Pop discipline is non-uniform (compressed-aligned doesn't pop). No `clear` port on the construct. Storage savings (3 regs → 1 fifo) don't offset the contract mismatch. |
| `ram` / `cam`  | N/A      | Not address-indexed access. |
| `linklist`     | N/A      | Not pointer-chained storage. |
| `regfile`      | N/A      | Not multi-port register array. |
| `arbiter`      | N/A      | Single producer, single consumer — no arbitration. |
| `counter`      | N/A      | The internal PC is hand-managed against `addr_incr_two`; not a freestanding count primitive. |
| `pipeline`     | rejected | Bespoke realignment + clear-reseed shouldn't ride a generic stage chain. |
| `synchronizer` | N/A      | Single clock domain. |
| `clkgate`      | N/A      | No clock gating. |

## Approach

Tentative ARCH constructs (the implementer agent picks final shapes):

- Plain `module` with one `seq` block (clocked next-state for `valid_q`,
  `rdata_q`, `err_q`, `instr_addr_q`) and one `comb` block (output
  alignment, `pop_fifo`, `aligned_is_compressed` /
  `unaligned_is_compressed`, error muxing, PC increment). No `fsm` /
  `thread` — every cycle is a single-step transition driven by inputs
  and current state.
- `Vec<UInt<32>, 3>` for `rdata_q`, `Vec<Bool, 3>` for `err_q` and
  `valid_q`. `UInt<31>` for `instr_addr_q[31:1]` (bit 0 hard-wired to
  0).
- `busy_o` derived combinationally as `valid_q[2:1]` (upper `NUM_REQS`
  entries).
- `out_rdata_o` combinational mux: aligned → `head[31:0]` (or bypass
  when empty); unaligned → `{ next_source[15:0], head[31:16] }` where
  `next_source` is `rdata_q[1]` if `valid_q[1]` else `in_rdata_i`.
- `out_err_o` / `out_err_plus2_o` follow the same aligned/unaligned
  mux, with the unaligned-compressed suppression and the bypass-half
  err piped from `in_err_i`.
- `clear_i` next-state: clears all `valid_q` bits and overrides the
  push update. `instr_addr_q` next-state: `clear_i ? in_addr_i[31:1] :
  (current + (addr_incr_two ? 1 : 2))` (in 31-bit space — `+1` =
  half-word, `+2` = full word).

## Verification gate

Per the TDD-first / split-gate flow:

1. **Basic suite** (blocking) — one cocotb scenario per spec
   Requirement (~7 tests). Walk each case cycle-by-cycle: drive
   `clk`/`rst`, set inputs, sample outputs combinationally, assert.
2. **Full regression** (background) — every Scenario in the spec plus
   edge cases: full-fill / drain sequences, error patterns across all
   three entries, clear during empty / partial / full / mid-pop,
   compressed-then-uncompressed instruction streams, bypass interleaved
   with normal pushes.

The 4 ISR programs already exercise the IF→ID path on every fetch, so
end-to-end coverage is implicit (they will keep running as part of
`make test`).

## Verification gate caveats

- The FIFO has a producer-side invariant: never pushed-when-full
  without `clear_i`. The basic suite will skip exercising this case
  (UB by contract); the full-regression suite will assert that the
  arch implementation handles `clear_i + in_valid_i + full` without
  going wrong (clear wins).
- The combinational output path (`out_valid_o`, `out_rdata_o`,
  `out_err_o`, `out_addr_o`, `out_err_plus2_o`) has zero latency from
  inputs. cocotb tests must read outputs *before* the next clock edge
  for same-cycle bypass scenarios — pattern is `dut.in_valid_i.value =
  1; await Timer(1, "ns"); assert dut.out_valid_o.value == 1`.

## Reference

Upstream: `$IBEX_ROOT/rtl/ibex_fetch_fifo.sv` (Apache-2.0, 269 LoC).
Producer: `ibex_prefetch_buffer.sv` (drives `clear_i` from `branch_i`,
`in_valid_i` from `instr_rvalid_i & ~branch_discard_q[0]`,
`in_addr_i` from the IF stage's `addr_i` branch target).
Consumer: `ibex_if_stage.sv` (samples `out_valid_o` / `out_rdata_o`
into the compressed decoder and skid path; OR-combines `out_err_o`
with PMP-side errors at `ibex_if_stage.sv:403`).
Reference doc: `~/github/ibex/doc/03_reference/instruction_fetch.rst`.
