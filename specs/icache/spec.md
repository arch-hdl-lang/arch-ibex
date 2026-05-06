# Specification: ibex_icache

The instruction cache (`ibex_icache`) sits between Ibex's IF stage and the
instruction-side bus master, replacing the simple prefetch buffer with a
2-way 4 kB cache plus a pool of fill buffers that track outstanding misses,
in-flight prefetch, and stream-output multiplexing. It accepts a
prefetch / branch-redirect handshake from the core, drives a read-only OBI
master to the instruction bus, owns single-port tag- and data-RAM
interfaces, and implements a scramble-key request handshake. This spec
captures the externally observable contract; the implementation is free to
organise its fill-buffer pool and lookup-vs-fill arbitration as it sees
fit (e.g. as an associative CAM plus an arbiter).

## Module interface

Pinned scope: `ibex_icache import ibex_pkg::*` instantiated from
`ibex_if_stage` (`ibex_if_stage.sv:275-322`). Cache geometry comes from
`ibex_pkg.sv:380-401`: `BUS_SIZE=32`, `IC_NUM_WAYS=2`, `IC_LINE_SIZE=64`,
`IC_LINE_BEATS=2`, `IC_NUM_LINES=128`, `IC_INDEX_W=7`, `IC_TAG_SIZE=22`
(includes one valid bit), `IC_LINE_W=3`.

### Clock / reset

| Port      | Dir | Width | Role                                                                  | Cite                  |
|-----------|-----|-------|-----------------------------------------------------------------------|-----------------------|
| `clk_i`   | in  | 1     | Single positive-edge clock for all flops.                             | `ibex_icache.sv:24`   |
| `rst_ni`  | in  | 1     | Active-low async-asserted, sync-deasserted reset.                     | `ibex_icache.sv:25`   |

### Core-side request / response

| Port           | Dir | Width | Role                                                                     | Cite                          |
|----------------|-----|-------|--------------------------------------------------------------------------|-------------------------------|
| `req_i`        | in  | 1     | Core wants instructions; while low the cache must wind down fetching.    | `ibex_icache.sv:28`           |
| `branch_i`     | in  | 1     | One-cycle pulse: redirect prefetch + output stream to `addr_i`.          | `ibex_icache.sv:31`           |
| `addr_i`       | in  | 32    | Branch target, halfword-aligned (`addr_i[0]=0`); valid only with `branch_i`. | `ibex_icache.sv:32`       |
| `ready_i`      | in  | 1     | IF-stage downstream consumer pops `rdata_o` this cycle.                  | `ibex_icache.sv:35`           |
| `valid_o`      | out | 1     | Output beat valid (sticky until accepted or branched away).              | `ibex_icache.sv:36, 1190`     |
| `rdata_o`      | out | 32    | Aligned-by-`addr_o` 32-bit instruction beat (low halfword may come from skid). | `ibex_icache.sv:37, 1191` |
| `addr_o`       | out | 32    | PC of the beat on `rdata_o`; halfword-granular (LSB always 0).           | `ibex_icache.sv:38, 1192`     |
| `err_o`        | out | 1     | The current beat is faulted (bus error during line fill or ECC failure).  | `ibex_icache.sv:39, 1193`    |
| `err_plus2_o`  | out | 1     | The fault is on the upper halfword of an unaligned 32-bit instruction.   | `ibex_icache.sv:40, 1196`     |

### Instruction-bus master (OBI-flavoured, read-only)

| Port             | Dir | Width      | Role                                                            | Cite                       |
|------------------|-----|------------|-----------------------------------------------------------------|----------------------------|
| `instr_req_o`    | out | 1          | Read request valid; must hold until `instr_gnt_i`.              | `ibex_icache.sv:43, 1035`  |
| `instr_gnt_i`    | in  | 1          | Bus accepts the request this cycle.                             | `ibex_icache.sv:44`        |
| `instr_addr_o`   | out | 32         | Word-aligned read address (`[1:0] = 0`).                        | `ibex_icache.sv:45, 1036`  |
| `instr_rdata_i`  | in  | 32         | Read data beat, valid with `instr_rvalid_i`.                    | `ibex_icache.sv:46`        |
| `instr_err_i`    | in  | 1          | Bus error qualifier on `instr_rvalid_i`.                        | `ibex_icache.sv:47`        |
| `instr_rvalid_i` | in  | 1          | One pulse per accepted request, in request-issue order.         | `ibex_icache.sv:48`        |

### Tag-RAM port (single-port, IC_NUM_WAYS=2 banks)

| Port              | Dir | Width / Shape                       | Role                                                                                         | Cite                       |
|-------------------|-----|-------------------------------------|----------------------------------------------------------------------------------------------|----------------------------|
| `ic_tag_req_o`    | out | `Vec<2,UInt<1>>`                    | Per-way request strobe (one-hot for fill/inval/ECC-correct, all-ones for lookup).            | `ibex_icache.sv:51, 444`   |
| `ic_tag_write_o`  | out | 1                                   | 1 = write that cycle (fill/inval/ECC-correct), 0 = read.                                     | `ibex_icache.sv:52, 445`   |
| `ic_tag_addr_o`   | out | `UInt<7>` (`IC_INDEX_W`)            | Line index applied to all banks.                                                             | `ibex_icache.sv:53, 446`   |
| `ic_tag_wdata_o`  | out | `UInt<TagSizeECC>`                  | `{valid,tag[20:0]}`, possibly XORed with tweak/ECC checkbits.                                | `ibex_icache.sv:54, 449`   |
| `ic_tag_rdata_i`  | in  | unpacked `Vec<2,UInt<TagSizeECC>>`  | Per-way tag read; arrives 1 cycle after `ic_tag_req_o[way]=1`.                               | `ibex_icache.sv:55`        |

Timing: tag RAM is single-port synchronous. A `ic_tag_req_o` pulse at cycle
N delivers `ic_tag_rdata_i` at cycle N+1; a write in cycle N consumes the
port (no read on the same way that cycle). See producer-side notes below.

### Data-RAM port (single-port, IC_NUM_WAYS=2 banks, line-wide)

| Port              | Dir | Width / Shape                        | Role                                                                                          | Cite                       |
|-------------------|-----|--------------------------------------|-----------------------------------------------------------------------------------------------|----------------------------|
| `ic_data_req_o`   | out | `Vec<2,UInt<1>>`                     | Per-way request strobe (one-hot for fill, all-ones for lookup).                               | `ibex_icache.sv:56, 458`   |
| `ic_data_write_o` | out | 1                                    | 1 = write a complete line, 0 = read.                                                          | `ibex_icache.sv:57, 459`   |
| `ic_data_addr_o`  | out | `UInt<7>`                            | Line index, identical to `ic_tag_addr_o` in the same cycle.                                   | `ibex_icache.sv:58, 460`   |
| `ic_data_wdata_o` | out | `UInt<LineSizeECC>` (=64 with ECC=0) | Full cache line write data.                                                                   | `ibex_icache.sv:59, 463`   |
| `ic_data_rdata_i` | in  | unpacked `Vec<2,UInt<LineSizeECC>>`  | Per-way line read; arrives 1 cycle after `ic_data_req_o[way]=1`.                              | `ibex_icache.sv:60`        |

Tag and data ports are addressed in lockstep (`data_index_ic0 =
tag_index_ic0`, `ibex_icache.sv:281`); the implementation may merge their
arbitration.

### Scramble-key handshake

| Port                  | Dir | Width | Role                                                           | Cite                       |
|-----------------------|-----|-------|----------------------------------------------------------------|----------------------------|
| `ic_scr_key_valid_i`  | in  | 1     | New scramble key landed in the RAM cells (req/ack ack side).   | `ibex_icache.sv:61`        |
| `ic_scr_key_req_o`    | out | 1     | Request a fresh scramble key (req/ack req side).               | `ibex_icache.sv:62, 1212`  |

When `ICacheScramble=0` (this SoC), the upstream wrapper ties
`ic_scr_key_valid_i` to a constant 1 (`ibex_top.sv:581`,
`scramble_key_valid_q <= 1'b1`), so the cache passes through
`AWAIT_SCRAMBLE_KEY` in a single cycle.

### Control / status

| Port              | Dir | Width | Role                                                                                  | Cite                          |
|-------------------|-----|-------|---------------------------------------------------------------------------------------|-------------------------------|
| `icache_enable_i` | in  | 1     | 1 = caching mode, 0 = pass-through (no allocate, no lookup).                          | `ibex_icache.sv:65`           |
| `icache_inval_i`  | in  | 1     | Pulse: invalidate all tag entries; a new scramble key is also requested.              | `ibex_icache.sv:66, 1247`     |
| `busy_o`          | out | 1     | Cache is invalidating or has outstanding memory traffic; safe-clock-gate gate.         | `ibex_icache.sv:67, 1303`     |
| `ecc_error_o`     | out | 1     | Pulse on a tag/data ECC failure during a lookup. Tied 0 when `ICacheECC=0`.            | `ibex_icache.sv:68, 643, 651` |

## Parameters

Pinned to the values in `ibex_top` parameter binding from the IF stage
instantiation (`ibex_if_stage.sv:275-281`). The arch-ibex `IbexTop` source
currently pins `ICache=0` (`src/IbexTop.arch:56-62`); for the icache port we
spec the `ICache=1` case explicitly because the icache module is only
instantiated under that branch (`ibex_if_stage.sv:273`).

| Parameter         | Pinned value                  | Cite                                  | Effect on this spec |
|-------------------|-------------------------------|---------------------------------------|---------------------|
| `ICacheECC`       | `1'b0`                        | `ibex_top.sv:32, ibex_if_stage.sv:276` | No ECC checkbits on tag/data RAM widths; `ecc_error_o = 0` always; `ecc_write_req` path is dead code (`ibex_icache.sv:644-652`). |
| `ResetAll`        | `1'b0`                        | `ibex_if_stage.sv:277`                 | Implementation may skip explicit `'0` resets on prefetch / fill / output address / data flops. |
| `BusSizeECC`      | `BUS_SIZE = 32`               | `ibex_top.sv:195-196`                  | `ic_data_*` width parameters collapse to plain `BUS_SIZE`/`IC_LINE_SIZE`. |
| `TagSizeECC`      | `IC_TAG_SIZE = 22`            | `ibex_top.sv:198-199`                  | Tag-RAM width = 22 bits (1 valid + 21 tag bits). |
| `LineSizeECC`     | `IC_LINE_SIZE = 64`           | `ibex_top.sv:197`                      | Data-RAM width = 64 bits per way. |
| `BranchCache`     | `1'b0` (default)              | `ibex_icache.sv:20`                    | All non-allocating-condition gating reduces to `icache_enable_i & ~inval_block_cache` (`ibex_icache.sv:678-683`). |
| `TweakInfection`  | `1'b0` (no `ICacheTweak…` in IF stage instantiation) | `ibex_if_stage.sv:281` | All `*_tweak_lw_*` paths are zeros (`ibex_icache.sv:432-437`); the spec ignores the tweak XOR. |

Locked package values (`ibex_pkg.sv:381-401`):

- `NUM_FB = 4` (`ibex_icache.sv:72`) — pool of outstanding-miss tracking
  slots (this is the CAM target).
- `FB_THRESHOLD = NUM_FB - 2 = 2` (`ibex_icache.sv:74`) — once the in-flight
  count exceeds this, lookups are throttled unless they are a branch.
- `IC_NUM_WAYS = 2`, `IC_LINE_BEATS = 2`, `IC_INDEX_W = 7`,
  `IC_TAG_SIZE = 22`, `IC_OUTPUT_BEATS = 2`.

## Requirements

### R-INV-RESET — Cold-start / invalidation FSM (`icache.rst:223-225`, `ibex_icache.sv:1219-1278`)

R-INV-1. Out of reset the cache MUST advance through
  `OUT_OF_RESET → AWAIT_SCRAMBLE_KEY → INVAL_CACHE → IDLE`
  (`ibex_icache.sv:194-198, 1219-1268`).

R-INV-2. While the FSM is not in `IDLE` (`ibex_icache.sv:1271`), the
  cache MUST hold `inval_block_cache = 1` (`ibex_icache.sv:1217, 1264`)
  so lookups MAY proceed but MUST NOT allocate a way (`lookup_actual_ic0
  = 0`, `ibex_icache.sv:266`).

R-INV-3. In `OUT_OF_RESET`, when `ic_scr_key_valid_i = 0` the cache
  MUST assert `ic_scr_key_req_o = 1` (`ibex_icache.sv:1220-1227`);
  unconditional transition to `AWAIT_SCRAMBLE_KEY`.

R-INV-4. In `AWAIT_SCRAMBLE_KEY` the cache MUST wait for
  `ic_scr_key_valid_i = 1` and MUST hold `ic_scr_key_req_o = 0`
  (`ibex_icache.sv:1228-1239`).

R-INV-5. In `INVAL_CACHE` the cache MUST issue tag-RAM writes
  clearing the valid bit for every index in `[0, IC_NUM_LINES)`
  (`ibex_icache.sv:1240-1255, 257-258`); transitions to `IDLE` once
  `&inval_index_q` is reached.

R-INV-6. A pulse on `icache_inval_i` while in `INVAL_CACHE` or `IDLE`
  MUST raise `ic_scr_key_req_o`, return to `AWAIT_SCRAMBLE_KEY`, and
  restart the invalidation (`ibex_icache.sv:1247-1252, 1259-1261`).

R-INV-7. `busy_o = 1` while `inval_state_q != IDLE`
  (`ibex_icache.sv:1303`).

### R-REQ — Request acceptance and prefetch (`icache.rst:256-274`, `ibex_icache.sv:217-251`)

R-REQ-1. The cache MUST maintain a prefetch-address register that
  advances by one cache-line stride (`IC_LINE_BYTES = 8`) for every
  granted lookup (`ibex_icache.sv:219-222`).

R-REQ-2. When `branch_i = 1`, the cache MUST capture `addr_i` as the
  new prefetch address; if a lookup is also granted that cycle the
  granted-line advance takes precedence (`ibex_icache.sv:219-224`).

R-REQ-3. The cache MUST issue a lookup this cycle iff
  `req_i = 1` ∧ at least one FB free (`~&fill_busy_q`) ∧ no
  ECC-correct write pending ∧ (`branch_i = 1` ∨ `~lookup_throttle`)
  (`ibex_icache.sv:249-250`). `lookup_throttle` MUST assert as soon as
  more than `FB_THRESHOLD = 2` fill buffers are live
  (`ibex_icache.sv:247`).

R-REQ-4. With `req_i = 0` or all FBs busy, the cache MUST stop issuing
  new lookups, but MUST continue draining in-flight fills and serving
  queued output beats (`icache.rst:258-261, ibex_icache.sv:249, 1303`).

R-REQ-5. Lookup address = `addr_i` when `branch_i = 1`, else the
  registered prefetch address (`ibex_icache.sv:251`).

R-REQ-6. `addr_i[0]` MUST be 0 (halfword alignment, `icache.rst:265`).

### R-LK — Cache lookup, hit detection, allocation (icache.rst:142-149)

R-LK-1. A lookup pipeline stage IC1 MUST receive `ic_tag_rdata_i` and
  `ic_data_rdata_i` exactly one cycle after the lookup was granted in
  IC0 (`ibex_icache.sv:465-490, 497-501`).

R-LK-2. A lookup hits when any way's tag, equal-compared with
  `{1'b1, lookup_addr_ic1[ADDR_W-1:IC_INDEX_HI+1]}`, matches
  (`ibex_icache.sv:498-503`); on hit the IC1 way's data MUST be the
  source for the corresponding fill buffer's output stream
  (`ibex_icache.sv:941, 1043`).

R-LK-3. On miss, the cache MUST select a victim way: the lowest-indexed
  invalid way if any way is invalid, otherwise the global round-robin
  way (`ibex_icache.sv:518-534`).

R-LK-4. While a fill buffer is live for line `L`, any subsequent lookup
  that resolves to line `L` whose data is already (partially or fully)
  in the buffer MUST be serviced from that buffer rather than triggering
  a second external request whenever functionally possible
  (`ibex_icache.sv:747` — `fill_hit_ic1` couples a lookup at IC1 to the
  matching fill buffer entry; `ibex_icache.sv:865, 941, 1043`). NOTE: it
  is acceptable for the implementation to occasionally allocate the same
  line twice — the upstream doc explicitly permits this corner
  (`icache.rst:73-74`); however the common case (the FB-hit path) MUST
  return data directly from the in-flight FB without a redundant bus
  request.

R-LK-5. A lookup MUST NOT cause a tag/data RAM write or allocate a way
  while `inval_block_cache = 1`, while `icache_enable_i = 0`, or while
  an ECC-correct write is pending (`ibex_icache.sv:266, 678-683`).

### R-FB — Fill buffer pool capacity and arbitration (`icache.rst:150-166`, `ibex_icache.sv:706-906`)

R-FB-1. Pool size = `NUM_FB = 4` (`ibex_icache.sv:72`); when all four
  are busy, lookups MUST stall (`~&fill_busy_q`,
  `ibex_icache.sv:249`).

R-FB-2. Each granted lookup MUST allocate exactly one FB in IC0
  (`ibex_icache.sv:699`); allocation policy is otherwise unconstrained.

R-FB-3. Each FB holds (a) lookup address, (b) branch-staleness flag,
  (c) cache-allocate flag (cleared if FB was allocated while cache was
  disabled/invalidating, suppressing RAM write-back), (d) hit/miss flag
  set in IC1, (e) per-beat error flags, (f) line data (sourced from
  IC1 hit data or `instr_rdata_i` beats) (`ibex_icache.sv:716-906`).

R-FB-4. Inter-FB arbitration for (i) external requests, (ii) RAM
  write-backs, (iii) IF-stage output, (iv) `instr_rvalid_i` consumption
  MUST be age-ordered: oldest eligible wins
  (`ibex_icache.sv:840-851`). The "older" set is captured at allocation
  and decays as older FBs release (`ibex_icache.sv:724`).

R-FB-5. An FB MUST release (clear `fill_busy_q`) only once (a) all
  expected bus beats have been received, (b) any cache write-back has
  completed or been suppressed by allocate-flag/hit/error, AND (c) all
  output beats have been delivered to IF OR the FB is stale
  (`ibex_icache.sv:728-734`).

R-FB-6. Remaining external requests MAY be cancelled early when the FB
  is stale and non-allocating, or on an IC1 hit
  (`ibex_icache.sv:766-774`).

### R-EXT — Instruction-bus master behaviour

R-EXT-1. `instr_req_o = 1` iff any live FB needs more beats
  (`|fill_ext_req`, `ibex_icache.sv:1029-1030`) OR a speculative-IC0
  request fires on a branch / cache-disabled granted lookup
  (`ibex_icache.sv:702, 1029`).

R-EXT-2. Once `instr_req_o = 1`, the cache MUST hold it (and
  `instr_addr_o`) stable until `instr_gnt_i = 1`
  (`ibex_icache.sv:763-774`). Matches `instruction_fetch.rst:53-55`.

R-EXT-3. `instr_addr_o[1:0] = 0` (`ibex_icache.sv:1036`); points to the
  next required bus beat for the oldest bus-arbitrated FB
  (`ibex_icache.sv:841, 988-996`), or to the lookup beat on the
  speculative-IC0 path (`ibex_icache.sv:1032-1033`).

R-EXT-4. Bus beats arrive in request order; the cache MUST steer
  `instr_rvalid_i` / `instr_rdata_i` / `instr_err_i` to the oldest FB
  still expecting beats (`ibex_icache.sv:850-851, 944-957`). Bus
  errors MUST be recorded per-beat (`ibex_icache.sv:946-957`).

R-EXT-5. After an FB has cancelled its external requests due to a
  recorded bus error, no further `instr_req_o` MUST fire for that FB
  (`ibex_icache.sv:766-774, 814-818`).

### R-ARB — RAM-port arbitration between lookups, fills, invalidates, ECC-correct (icache.rst:142-149, ibex_icache.sv:262-283)

R-ARB-1. Lookup requests MUST have higher priority than fill writes for
  the tag/data RAM port (`ibex_icache.sv:262-264`). Concretely:
  `lookup_grant_ic0 = lookup_req_ic0`; `fill_grant_ic0 = fill_req_ic0 &
  ~lookup_req_ic0 & ~inval_write_req & ~ecc_write_req`.

R-ARB-2. Invalidation writes (`inval_write_req`) and ECC-correct writes
  (`ecc_write_req`) MUST suppress both lookup AND fill grants for the
  cycle they fire (`ibex_icache.sv:249-250, 263-264, 269-277`).

R-ARB-3. Lookup throttling (`lookup_throttle`) ensures fills are not
  starved indefinitely: once more than `FB_THRESHOLD` buffers are live,
  non-branch lookups stall, allowing fill writes to drain
  (`ibex_icache.sv:247, 249`). Branches always bypass the throttle
  (`ibex_icache.sv:249`, `branch_i | ~lookup_throttle`).

R-ARB-4. The chosen RAM-port driver in IC0 MUST be: invalidate index
  (highest), else ECC-correct index, else granted-fill index, else
  lookup index (`ibex_icache.sv:270-273`). Ways are correspondingly
  selected: ECC-correct ways, else fill way, else all-ones for lookup
  (`ibex_icache.sv:274-276`).

### R-OUT — IF-stage output stream (`icache.rst:243-254`, `ibex_icache.sv:1012-1196`)

R-OUT-1. `valid_o` MUST assert when (a) a complete compressed
  instruction resides in the skid buffer, OR (b) muxed line data for
  the current output address is available, alignment is satisfied,
  and any needed upper halfword is also available
  (`ibex_icache.sv:1128-1132`).

R-OUT-2. Once `valid_o` is asserted for a no-error beat, it MUST stay
  asserted (and `rdata_o`/`addr_o`/`err_o`/`err_plus2_o` stable) until
  `ready_i = 1` accepts it OR `branch_i = 1` cancels it
  (`icache.rst:243-247`, `ibex_icache.sv:1100, 1135, 1145-1146`).

R-OUT-3. After a beat with `err_o = 1` is presented, all output signals
  MAY change arbitrarily until the next `branch_i = 1`
  (`icache.rst:247-248`).

R-OUT-4. `addr_o` is the halfword PC of the beat
  (`ibex_icache.sv:1192`). On `ready_i & valid_o` it MUST advance by 2
  if `rdata_o[1:0] != 2'b11` (compressed), else by 4
  (`ibex_icache.sv:1102, 1138, 1141-1143`); on `branch_i` it MUST jump
  to `addr_i` (`ibex_icache.sv:1146`). `addr_o[0]` MUST be 0.

R-OUT-5. `err_plus2_o = 1` only when the fault is on the upper halfword
  of an unaligned 32-bit instruction (skid buffer carrying clean lower
  half, upper-half fetch faults; `ibex_icache.sv:1196`,
  `icache.rst:276-278`). MUST be 0 for compressed-instruction faults
  and for aligned 32-bit faults.

R-OUT-6. The 16-bit skid buffer handles 32-bit instructions crossing a
  `BUS_SIZE` boundary (`ibex_icache.sv:1095-1114`); MUST clear on
  `branch_i` (`ibex_icache.sv:1106`).

R-OUT-7. On a cache hit at IC1, the hit data MUST drive `valid_o` no
  later than the cycle after IC1 — i.e. one cycle after the lookup
  was granted (`ibex_icache.sv:1043, 1067`).

### R-EN — Enable / disable

R-EN-1. When `icache_enable_i = 0` AND no invalidation is in progress,
  the cache MUST operate in pass-through mode: lookups MUST NOT allocate
  (`fill_cache_new = 0`, `ibex_icache.sv:678-683`); a fill buffer
  allocated during disable MUST never write back to the RAMs even if
  `icache_enable_i` later goes high (`ibex_icache.sv:743-745`).

R-EN-2. When `icache_enable_i = 0`, lookups MUST still issue external
  bus requests (`ibex_icache.sv:702, 1029`) so the IF stream still
  receives instructions; only allocation is suppressed.

R-EN-3. When `icache_enable_i` toggles to 0 with a fill buffer in
  flight that already holds the cache-allocate flag, the buffer MUST
  drop its allocate flag (`ibex_icache.sv:743-745`,
  `fill_cache_d` AND-gates with `icache_enable_i & ~icache_inval_i`).

### R-INV — Invalidation request semantics

R-INV-A. A pulse on `icache_inval_i` MUST eventually cause every cache
  line's tag-valid bit to become 0 (`icache.rst:223-225`,
  `ibex_icache.sv:1240-1255`).

R-INV-B. While invalidation is in progress, lookups MAY be issued (they
  go to the bus as in pass-through) but MUST NOT allocate
  (`ibex_icache.sv:266, 678-683`). The doc note (`icache.rst:288-295`)
  is reflected here as: "to be sure of executing newly fetched code, the
  caller must raise `icache_inval_i` for at least a cycle and then
  branch."

R-INV-C. Live fill buffers at the time `icache_inval_i` pulses MUST drop
  their allocate flag for the remainder of their life
  (`ibex_icache.sv:743-745`).

### R-BUSY — Busy / clock-gate semantics

R-BUSY-1. `busy_o = 1` MUST hold while `inval_state_q != IDLE` OR while
  any fill buffer has unresolved external traffic
  (`fill_busy_q[i] & ~fill_rvd_done[i]`, `ibex_icache.sv:1303`).

R-BUSY-2. `busy_o = 0` is a permission for the SoC to clock-gate the
  cache (`icache.rst:291-292`); the implementation MUST NOT gate itself.

### R-ECC — ECC error reporting (degenerate under ICacheECC=0)

R-ECC-1. With `ICacheECC = 0`, `ecc_error_o` MUST be tied to 0
  (`ibex_icache.sv:644-652`). The implementation MAY drop the ECC
  pipeline entirely. (No SoC-visible test of `ecc_error_o` is required.)

### R-RESET — Reset behaviour

R-RST-1. On `rst_ni = 0`, `valid_o`, `instr_req_o`, `ic_tag_req_o`,
  `ic_data_req_o`, `ic_scr_key_req_o` MUST all be 0
  (`ibex_icache.sv:444, 458, 1212`, plus FSM reset
  `ibex_icache.sv:1273-1278`).

R-RST-2. After reset deassertion, the cache MUST NOT make any
  `instr_req_o` until at least the first `branch_i` pulse arrives. The
  upstream doc explicitly notes "the address counter is not initialised
  on reset, the behaviour of the I$ is unspecified unless `branch_i` is
  asserted on or before the first cycle that `req_i` is asserted after
  reset" (`icache.rst:280-281`). The implementation MAY assume the IF
  stage upholds this — but it MUST NOT diverge wildly: pre-first-branch
  it MUST hold `valid_o = 0`.

R-RST-3. The invalidation FSM walks the entire tag RAM out of reset
  (R-INV-1); concretely `valid_o` MUST stay 0 until at least
  `IC_NUM_LINES` cycles after key arrival
  (`ibex_icache.sv:1240-1255`).

## Scenarios

Times are clock cycles after the indicated trigger; `(C0)` denotes the
cycle of the trigger.

### S1 — Cold boot through key wait into IDLE

GIVEN reset has just deasserted (cycle C0); `ic_scr_key_valid_i` is held
to 1 by the SoC (no scramble); `req_i = 0`, `branch_i = 0`.
WHEN cycles run with no input stimulus.
THEN at C1 the FSM is in `AWAIT_SCRAMBLE_KEY`; at C2 it advances to
`INVAL_CACHE` and begins issuing `ic_tag_write_o = 1` for index 0; over
the following `IC_NUM_LINES = 128` cycles it walks every index; after
that it lands in `IDLE` (`ic_tag_write_o = 0`); throughout this period
`busy_o = 1` and `valid_o = 0`. (`ibex_icache.sv:1219-1268, 1303`)

### S2 — Branch into cold cache, single miss → fill → output

GIVEN FSM `IDLE`, all FBs free, `icache_enable_i = 1`, no bus traffic.
WHEN at C0 `branch_i = 1`, `addr_i = 0x0010_0080`, `req_i = 1`,
`ready_i = 1`.
THEN C0 grants the lookup (branches bypass throttle), one FB allocates,
prefetch advances by one line, and a speculative `instr_req_o` MAY fire.
C1 IC1 reports a tag miss (all ways invalid). The FB drives
`instr_req_o` until `IC_LINE_BEATS = 2` beats arrive on `instr_rvalid_i`
(rvalid in request order); the first beat is forwarded to the IF output
the same cycle via `fill_data_rvd` (`ibex_icache.sv:867-870, 1061`). A
tag+data RAM write fires once both beats have landed and the IC0 RAM
port is free (`ibex_icache.sv:814-821`).

### S3 — Cache hit fast-path

GIVEN line `L` is cached (S2 completed), FSM `IDLE`, all FBs free.
WHEN at C0 `branch_i = 1`, `addr_i ∈ L`, `req_i = 1`, `ready_i = 1`.
THEN C0 grants the lookup; C1 IC1 hits; the C0-allocated FB takes
`hit_data_ic1` and presents the first output beat via `fill_data_hit`.
The contract: at most one bus request per branch-into-hit cycle, and
zero subsequent requests for this lookup once the hit is recognised at
IC1 (`ibex_icache.sv:702, 766-774, 941, 1043`).

### S4 — Branch lands on a line currently being filled (CAM hit target)

GIVEN at C0 an FB is allocated for line `L`, beat 0 has returned but
beat 1 has not, FSM `IDLE`, cache enabled.
WHEN at C2 `branch_i = 1` with `addr_i ∈ L` (any offset).
THEN the new lookup MUST detect at C3 that `L` is already in a fill
buffer (`fill_hit_ic1`, `ibex_icache.sv:747`) and MUST stream from that
buffer rather than issue a redundant `instr_req_o` for `L`. The earlier
FB's now-stale output is suppressed by `fill_stale_q | branch_i`
(`ibex_icache.sv:740-748, 795-797`). Contract: at most one outstanding
bus-request line per address `L` (this is the CAM target; see also
ambiguity 3).

### S5 — Branch during fill to a different line

GIVEN at C0 an FB is filling line `L1`; FSM `IDLE`, cache enabled.
WHEN at C2 `branch_i = 1`, `addr_i ∈ L2 ≠ L1`.
THEN the C0 FB is marked stale (`fill_stale_d`, `ibex_icache.sv:740`);
its IF output is dropped; if it has the allocate flag the remaining
beats are still consumed and written back; otherwise its remaining
external requests are cancelled (`ibex_icache.sv:766-774`). A new FB
allocates for `L2` and proceeds per S2.

### S6 — Two simultaneous misses (2 FBs in flight)

GIVEN FSM `IDLE`, cache enabled, FB pool empty, two distinct
not-cached lines `L1`, `L2`, `fb_fill_level ≤ FB_THRESHOLD = 2`.
WHEN at C0 a granted lookup misses on `L1`, at C1 a granted
(linear-prefetch) lookup misses on `L2`.
THEN two FBs go live, age-arbitrated for the bus master and for IF
output (`ibex_icache.sv:840-851`); `instr_rvalid_i` beats route to the
oldest expecting FB first; output to IF goes oldest-first
(`fill_data_sel`, `ibex_icache.sv:845-848`). Once
`fb_fill_level > FB_THRESHOLD`, `lookup_throttle = 1` and the next
non-branch lookup is suppressed (`ibex_icache.sv:247, 249`).

### S7 — Invalidation during fill

GIVEN at C0 an FB is filling line `L`; FSM `IDLE`, cache enabled.
WHEN at C2 `icache_inval_i = 1`.
THEN FSM → `AWAIT_SCRAMBLE_KEY` (`ic_scr_key_req_o = 1`);
`inval_block_cache = 1` from C3; the in-flight FB drops its allocate
flag (`ibex_icache.sv:743-745`) but still drains its beats and forwards
them to IF (so the live stream is not corrupted) — it just won't write
back. Once `ic_scr_key_valid_i = 1` returns, the FSM walks all
`IC_NUM_LINES` indices and returns to `IDLE`. `busy_o = 1` throughout.

### S8 — Disable then re-enable cycle

GIVEN FSM `IDLE`, cache enabled, line `L` cached.
WHEN at C0 `icache_enable_i` drops to 0; lookups in C1..C5 traverse the
cache while disabled; at C6 `icache_enable_i` is re-raised.
THEN lookups in C0..C5 issue bus requests but do NOT write the RAMs
(`ibex_icache.sv:702, 1029, 678-683`). After C6 a lookup of line `L`
MUST still hit — `L`'s tag was preserved (no eviction since allocation
was suppressed; `ibex_icache.sv:525-531`).

### S9 — Bus error on a fill beat

GIVEN at C0 an FB is filling line `L`.
WHEN beat 0 returns at C2 with `instr_err_i = 1`.
THEN the per-beat error flag is recorded
(`ibex_icache.sv:946-957`); subsequent external requests for the same
FB are cancelled (`ibex_icache.sv:766-774`); the corresponding output
beat to IF is presented with `err_o = 1`. After IF accepts the errored
beat, R-OUT-3 relaxes the output-stability contract until the next
`branch_i`.

### S10 — `req_i` deassertion drains then idles

GIVEN one FB is mid-fill at C0.
WHEN `req_i = 0` from C0 onward and no further lookups are issued.
THEN the FB completes its remaining beats, writes back to the RAMs if
allocate is set, then releases. After release `busy_o = 0` and no
further `instr_req_o` is asserted (`ibex_icache.sv:249-250, 1303`).

## Integration constraints

### Consumer-side (ibex_if_stage)

`ibex_if_stage.sv:273-322` instantiates the icache. Pin map:

- `branch_i ← prefetch_branch = branch_req | nt_branch_mispredict_i`
  (`ibex_if_stage.sv:262`); under `BranchPredictor=0` the second term
  is 0, so `branch_i` is the `branch_req = pc_set_i |
  predict_branch_taken` strobe (`ibex_if_stage.sv:391`). Back-to-back
  branch pulses on consecutive cycles are legal.
- `addr_i ← prefetch_addr` (`ibex_if_stage.sv:263`); valid only in the
  cycle of the `branch_i` pulse.
- `ready_i ← fetch_ready` (`ibex_if_stage.sv:691, 707`). The IF stage
  MAY drop `ready_i` on any cycle, including right after `branch_i`;
  the sticky-valid contract (R-OUT-2) MUST hold across such drops.
- `valid_o → fetch_valid_raw → fetch_valid`
  (`ibex_if_stage.sv:267`).
- `rdata_o`, `addr_o`, `err_o`, `err_plus2_o` are sampled ONLY when
  `valid_o = 1`, by downstream `if_instr_*` flops
  (`ibex_if_stage.sv:406-407, 532-549`). They MAY change when
  `valid_o = 0`. `err_plus2_o` feeds `instr_fetch_err_plus2_o` to the
  controller; semantics per R-OUT-5.
- `req_i` is a direct top-level pin (`ibex_if_stage.sv:39, 286`); the
  IF stage's contract is "do not assert `ready_i` while `req_i` is
  low" (`icache.rst:261`).

### Producer-side (ibex_top + SoC RAM cells)

`ibex_top.sv:592-770` instantiates the tag/data RAMs and the
scramble plumbing. Under SoC pinning (`ICacheScramble=0`):

- Tag and data RAMs are `prim_ram_1p` (single-port, sync-read),
  width=`TagSizeECC=22` and `LineSizeECC=64`, depth=`IC_NUM_LINES=128`
  (`ibex_top.sv:707-746`). Read latency: data on `rdata_o` 1 cycle
  after `req_i=1`.
- `ic_*_addr_o` at cycle N drives the RAM's `addr_i` at N;
  `ic_*_rdata_i` at N+1 carries the result. No buffering between the
  icache and the RAMs.
- `ic_scr_key_valid_i` is tied to `scramble_key_valid_q = 1'b1`
  (`ibex_top.sv:581`), so `AWAIT_SCRAMBLE_KEY` resolves in one cycle.
  `ic_scr_key_req_o` has no externally-visible effect with scramble
  disabled.
- RAMs have no flow-control input observed by the icache; requests are
  unconditionally accepted. The implementation may model the RAM ports
  as combinational-grant single-port memories.
- Same-cycle write-and-read on the same RAM bank is disallowed by
  `prim_ram_1p`; the icache structurally serialises this via
  lookup-vs-fill arbitration (R-ARB-1, R-ARB-4).

## Out of scope

- **Lockstep / shadow core** (`ibex_top.sv:784+`) — pinned 0.
- **RVFI / formal-only ports** (`ibex_icache.sv:1321-1334`).
- **Debug-trigger interactions** — icache has no debug pins.
- **`instr_pmp_err_i`** — referenced in `icache.rst:236-241` but absent from the actual port list; doc is stale, spec follows RTL.
- **ECC error path detail** — degenerate under `ICacheECC=0` (R-ECC-1).
- **Tweak infection** — `TweakInfection=0`. **`BranchCache=1`** — pinned 0; allocate-every-miss.

## Spec ambiguities flagged

1. **Speculative `instr_req_o` on branch-into-hit (S3).** Upstream
   raises `instr_req_o` for one cycle on a branch and cancels at IC1.
   A CAM-based implementation may resolve the hit one cycle earlier
   and never raise the speculative request. R-LK-4 is permissive
   (FB-hit MUST return data without a redundant bus request); tests
   MUST NOT bind to single-cycle `instr_req_o` on branch-into-hit.

2. **Sticky `valid_o` across `branch_i`.** R-OUT-2 says `valid_o`
   stays high until `ready_i`. Upstream drops `valid_o` on `branch_i`
   via the address redirect; the arch implementation should treat
   `branch_i` as the canonical override.

3. **R-LK-4 second allocation.** The upstream doc `icache.rst:73-74`
   permits same-line double-allocation as a corner case. A CAM-based
   implementation MAY strengthen this to "always coalesce" — this is
   a contract strengthening, not a relaxation.
