# Specification: IbexIcacheOutputStage (redesign)

The `IbexIcacheOutputStage` sub-block is the IF-stage-facing output stream
of `IbexIcache`. Its job: take per-cycle data from the icache's lookup
pipeline (IC1-stage hit data) and fill-buffer pool, mux/slice/skid as
needed, and deliver the next instruction word to the IF stage with a
strict `(valid_o, ready_i)` handshake.

This spec replaces the prior in-line R-OUT block of
`changes/archive/2026-05-05-port-ibex_icache/specs/icache/spec.md`. The
predecessor was retrofitted three times (PR #46/#49/#50/#51 plus three
2026-05-09 redesign attempts that all failed) and accumulated patches
that prevent steady-state performance from matching upstream Ibex. This
fresh spec adds **mandatory performance requirements (P-OUT-*)** that
every implementation MUST meet. Functional correctness is necessary but
not sufficient; the implementation MUST also hit the cycle-count targets
measured against the icache_bench / cpu_programs gate.

## Module interface

The block is instantiated from `src/IbexIcache.arch` as
`inst output_stage: IbexIcacheOutputStage` (already extracted in PR #52).

### Clock / reset
| Port      | Dir | Width | Role                                            |
|-----------|-----|-------|-------------------------------------------------|
| `clk_i`   | in  | 1     | Single positive-edge clock for all flops.       |
| `rst_ni`  | in  | 1     | Active-low async-asserted, sync-deasserted.     |

### Consumer-side (R-OUT-2/4/6)
| Port        | Dir | Width | Role                                                                  |
|-------------|-----|-------|-----------------------------------------------------------------------|
| `branch_i`  | in  | 1     | One-cycle pulse: redirect output stream to `addr_i`. Clears skid.     |
| `addr_i`    | in  | 32    | Branch target, halfword-aligned. Valid only with `branch_i`.          |
| `ready_i`   | in  | 1     | IF-stage downstream pops the current beat this cycle.                 |
| `valid_o`   | out | 1     | Output beat valid. Sticky until accepted or branched away.            |
| `rdata_o`   | out | 32    | Aligned-by-`addr_o` 32-bit instruction word.                          |
| `addr_o`    | out | 32    | PC of the beat. Halfword-granular (`[0]=0`).                          |
| `err_o`     | out | 1     | The current beat is faulted.                                          |
| `err_plus2_o` | out | 1   | The fault is on the upper halfword of an unaligned 32-bit instr.      |

### IC1-stage hit observables
| Port                  | Dir | Width | Role                                                          |
|-----------------------|-----|-------|---------------------------------------------------------------|
| `lookup_addr_ic0`     | in  | 32    | Current cycle's IC0 lookup address.                           |
| `lookup_addr_ic1_q`   | in  | 32    | IC1-stage registered lookup address (1 cy after IC0).          |
| `lookup_alloc_ic1_q`  | in  | 1     | IC1-stage "this lookup allocated a new FB" flag.              |
| `any_hit_ic1`         | in  | 1     | IC1-stage tag hit (any way matches).                          |
| `hit_data_ic1`        | in  | 64    | Cache-line data read from the hitting way (combinational from RAM). |

### Fill-buffer pool inputs (selected by parent's 4:1 muxes on out_grant_requester)
| Port                  | Dir | Width | Role                                                                |
|-----------------------|-----|-------|---------------------------------------------------------------------|
| `out_grant_valid`     | in  | 1     | At least one FB wants to drive output this cycle.                  |
| `out_grant_requester` | in  | 2     | Index of the selected FB (oldest-eligible per `FbAgeArb`).         |
| `out_line`            | in  | 64    | Selected FB's `fill_data_q[fb]`.                                   |
| `out_fb_addr`         | in  | 32    | Selected FB's `addr_q[fb]`.                                        |
| `out_err_beat0`       | in  | 1     | Selected FB's beat-0 bus-error flag.                               |
| `out_err_beat1`       | in  | 1     | Selected FB's beat-1 bus-error flag.                               |
| `out_beats_rcvd`      | in  | 2     | Selected FB's beat-receive counter (0..2).                         |

### Per-FB allocate pulses
| Port           | Dir | Width | Role                                                         |
|----------------|-----|-------|--------------------------------------------------------------|
| `fb*_allocate` | in  | 1     | Pulse when FB `*` allocates this cycle (4 ports, fb0..fb3).  |

### Per-FB out-done back-channel
| Port                  | Dir | Width | Role                                                  |
|-----------------------|-----|-------|-------------------------------------------------------|
| `fb*_out_done_pulse`  | out | 1     | Pulse when this block consumes the last beat from FB `*` (4 ports). |

## Parameters

This block has no SoC-visible parameters; cache geometry constants
(`IC_LINE_BEATS`, `IC_LINE_W`, etc.) are inherited from `ibex_pkg`.

## Functional requirements

### R-OUT-VALID — `valid_o` assertion semantics

**R-OUT-VALID-1.** `valid_o` MUST be 0 when `rst_ni=0`.

**R-OUT-VALID-2.** `valid_o` MUST assert in the same cycle that ANY of
the following data sources has the next-instruction beat at `addr_o`:
  - The IC1 hit-data path (`hit_data_ic1`) covers `addr_o`'s line AND
    the half indexed by `addr_o[2]` is a complete instruction (or the
    skid path satisfies an in-flight cross-beat misaligned-32).
  - The selected FB's `out_line` (post-fill) covers `addr_o`'s line.

**R-OUT-VALID-3.** `valid_o` MUST be 0 when `rst_ni=1` AND the icache
has no fetch in flight nor data ready (cold-boot inval walk; pre-first-
branch reset state).

**R-OUT-VALID-4.** Sticky behaviour: once `valid_o=1` for a non-error
beat, all output signals MUST stay stable until either `ready_i=1`
accepts it OR `branch_i=1` cancels it. Equivalently, on the consume edge
the current cycle's `(valid_o, rdata_o, addr_o, err_o, err_plus2_o)` MUST
satisfy the IF-stage's read.

### R-OUT-ADDR — `addr_o` advance semantics

**R-OUT-ADDR-1.** `addr_o` MUST equal the registered output address
(`addr_out_q`).

**R-OUT-ADDR-2.** On `branch_i=1`: at the next clock edge, `addr_out_q`
MUST become `addr_i`.

**R-OUT-ADDR-3.** On a consume edge (`valid_o=1 AND ready_i=1 AND
branch_i=0`): at the next clock edge, `addr_out_q` MUST advance by 2 if
`rdata_o[1:0] != 2'b11` (compressed) else by 4 (uncompressed).

**R-OUT-ADDR-4.** On any other cycle, `addr_out_q` MUST hold its value.
(NO other arm — fast-path, FB-side, skid, etc. — has authority to write
`addr_out_q`.)

### R-OUT-DATA — `rdata_o` muxing

**R-OUT-DATA-1.** `rdata_o[31:0]` MUST be the 32-bit instruction word at
`addr_out_q`. The data source is selected by the source-priority below;
the beat-half is selected by `addr_out_q[2]` and (if needed) the skid
buffer for cross-beat misaligned-32 reassembly.

**R-OUT-DATA-2.** Source priority for `rdata_o`:
  1. Skid-only path: `skid_complete_instr` (compressed instruction wholly
     in `skid_data_q`) — `rdata_o = {16'd0, skid_data_q}`.
  2. Skid-bridge path: `skid_valid_q AND new_beat_avail` (cross-beat
     reassembly) — `rdata_o = {beat_data[15:0], skid_data_q}`.
  3. IC1 hit comb path: `ic1_covers_addr_out_q` — `rdata_o` from
     `hit_data_ic1[63:32]` if `addr_out_q[2]=1` else `[31:0]`.
  4. FB-side path: `fb_covers_addr_out_q` — `rdata_o` from `out_line`
     selected by `addr_out_q[2]`.

(Note: priorities 3 and 4 yield the same data for a coherent line; the
ordering only matters during the cycle the IC1 hit is captured into the
FB's `fill_data_q`.)

### R-OUT-ERR — Error signalling

**R-OUT-ERR-1.** `err_o = 1` when (a) the skid path is delivering a
clean lower halfword stitched to a faulted upper-half beat
(`skid_valid_q AND beat_err`), OR (b) the current beat itself is
faulted (`out_err_beat0/1` per `addr_out_q[2]`).

**R-OUT-ERR-2.** `err_plus2_o = 1` only when the fault is on the upper
halfword of an unaligned 32-bit instruction. MUST be 0 for compressed-
instruction faults and for aligned 32-bit faults.

**R-OUT-ERR-3.** After a `valid_o=1 AND err_o=1` beat is presented, all
output signals MAY change arbitrarily until the next `branch_i=1`.

### R-OUT-SKID — Cross-beat misaligned-32 reassembly

**R-OUT-SKID-1.** The 16-bit skid buffer captures the upper halfword of
a cycle when the current beat would yield a misaligned-uncompressed-32
instruction (i.e., `addr_out_q[1]=1` AND beat upper-halfword bits[1:0]
== 11 AND no err on this beat).

**R-OUT-SKID-2.** While `skid_valid_q=1`, the lower halfword of `rdata_o`
MUST come from `skid_data_q`; the upper halfword MUST come from the
NEXT beat's lower halfword.

**R-OUT-SKID-3.** `skid_valid_q` MUST clear on `branch_i=1`.

### R-OUT-BRANCH — Branch handling

**R-OUT-BRANCH-1.** `branch_i=1` cancels any in-flight delivery: at the
next clock edge, `valid_o` MAY drop (the new `addr_i` typically requires
a fresh fetch); `addr_out_q` becomes `addr_i`; `skid_valid_q` clears.

**R-OUT-BRANCH-2.** A branch into a cache-hit line: `valid_o` MUST
assert with the right data per R-OUT-DATA-2 within the cycle counts
specified in the performance requirements (P-OUT-*).

### R-OUT-FB-DONE — Fill-buffer back-channel

**R-OUT-FB-DONE-1.** When the consume edge accepts the LAST beat from a
specific FB (the FB whose data sourced the just-consumed delivery), the
corresponding `fb*_out_done_pulse` MUST fire for one cycle. The parent
uses this to advance the FB lifecycle (`out_done_q`, `releasing_v`).

**R-OUT-FB-DONE-2.** When the IC1 hit path sources delivery (no FB
involved), `fb*_out_done_pulse` MUST be 0 for all FBs.

## Performance requirements (NEW — must meet)

These requirements define the throughput / latency contract the IF
stage and the rest of the SoC depend on. The implementation MUST hit
these targets simultaneously with the functional requirements. Failure
to meet any P-OUT-* is a correctness regression for the purposes of
the validation gate.

### P-OUT-1 — Steady-state cache-hit throughput

**P-OUT-1-A.** Sustained sequential aligned-uncompressed delivery from
cache hits: 1 cycle per commit (= 1 IPC). Consumer drives `ready_i=1`
every cycle; lines pre-warmed in cache; PC advances by 4 per cycle.

**P-OUT-1-B.** Sustained sequential aligned-compressed delivery: 1 cycle
per commit. PC advances by 2 per cycle.

**P-OUT-1-C.** Mixed-compression sequential: 1 cycle per commit
regardless of compression boundary alignment.

### P-OUT-2 — Within-line beat-1

After consuming beat-0 of a cache-hit line at `addr_out_q[2]=0`, the
next-cycle delivery of beat-1 (`addr_out_q[2]=1`) MUST happen with **0
cycles bubble** — i.e., back-to-back consume cycles. No "register
valid_q, then deliver" 2-cycle pattern is permitted.

### P-OUT-3 — Cross-line transition (cache hit)

After consuming the last instr of line N (cache hit), the first
delivery of line N+1 (also cache hit) MUST happen with **≤1 cycle
bubble**. I.e., consume at cycle X, valid_o asserts at cycle X+2 at
the latest.

### P-OUT-4 — Branch redirect (cache hit)

From `branch_i=1` pulse to `valid_o=1` at `addr_o=addr_i` (assuming the
target line is in cache): **≤2 cycles total** (branch at cycle X,
valid_o at cycle X+2 latest).

### P-OUT-5 — Branch redirect (cache miss)

From `branch_i=1` to `valid_o=1` when the target line is NOT in cache:
**≤(K_bus_serve + 1) cycles**, where K_bus_serve is the bus latency to
fetch beat-0. Implementation MAY NOT add additional bubbles beyond what
the bus protocol requires.

### P-OUT-6 — Disabled-cache passthrough

When `icache_enable_i=0`, sequential aligned-uncompressed delivery
through the bus passthrough path: ≤(K_bus_serve_per_beat + 0) cycles
per commit. Implementation MUST NOT add buffering bubbles between bus
rvalid and `valid_o`.

### P-OUT-7 — `mul`-stalled consumer

When the IF-stage consumer holds `ready_i=0` for N cycles (e.g.
multdiv pipeline stall), `valid_o` MUST stay sticky and `(addr_o,
rdata_o, err_o, err_plus2_o)` MUST stay stable for the entire stall.
On the consume edge after the stall, delivery MUST resume with no
extra bubble.

## Validation: how perf is measured

The performance contract is verified end-to-end via the `icache_bench`
cocotb test (`tests/cocotb_tests/test_icache_bench.py`). Per-loop-instr
`cy/commit` numbers MUST match upstream Ibex's measured baseline
(captured 2026-05-09):

| Instr (PC)             | Line position            | Upstream baseline | This impl MUST meet |
|------------------------|--------------------------|-------------------|---------------------|
| `add@0x10017c`         | line upper, branch tgt   | 1.00              | ≤ 1.10              |
| `mul@0x100180`         | line lower, after branch | 5.00              | ≤ 5.10 (multdiv)    |
| `addi_t2@0x100184`     | line upper, after mul    | 1.00              | ≤ 1.10              |
| `addi_t0@0x100188`     | line lower, after stall  | 1.00              | ≤ 2.10 *            |
| `bne@0x10018c`         | line upper, before branch| 2.99              | ≤ 3.10              |
| **per-iter total**     |                          | 11.0 cy           | **≤ 12.5 cy**       |
| **`result_cycles`**    | (8 × 200-iter kernels)   | **17,680**        | **≤ 19,000**        |

\* `addi_t0` upstream is 1 cy because mul's stall lets the icache fetch
the next line silently. Our impl may be slightly slower here (≤2 cy)
without missing the per-iter total.

## Tightening over the prior R-OUT spec

Compared to the old R-OUT requirements (preserved as functional
contracts above), this spec adds:

1. **R-OUT-ADDR-4**: explicit prohibition on non-consume/branch arms
   writing `addr_out_q`. The prior design accumulated 5+ arms with
   write authority and 3 redesign attempts proved that priority-chain
   arbitration over `addr_out_q` is too brittle. Enforced via a single-
   source advance.

2. **R-OUT-FB-DONE clarification**: `fb*_out_done_pulse` fires ONLY when
   the FB-sourced data is consumed, not when IC1-hit-comb sources the
   delivery. The prior impl pulsed FB-done for IC1-hit cycles too,
   tangling the FB lifecycle.

3. **P-OUT-* mandatory perf**: the prior R-OUT spec had no perf bar.
   Three redesign attempts failed because each found a "functionally
   correct but performance-poor" local optimum. With P-OUT-* the
   implementer cannot ship a 1.74× implementation.

## Reset state contract

After `rst_ni=0` for ≥1 clock period, the block MUST present:
- `valid_o=0`
- `addr_o=0` (or any deterministic value)
- `rdata_o=0`, `err_o=0`, `err_plus2_o=0`
- `fb*_out_done_pulse=0`

After `rst_ni=1` is reasserted: the block MUST NOT spuriously assert
`valid_o` until the first `branch_i` arrives AND its target's data is
available per R-OUT-DATA-2.
