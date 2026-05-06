# Proposal: Port `ibex_icache` to ARCH (D1)

## Intent

This swap replaces `ibex_icache.sv` (1337 LoC upstream) with
`src/IbexIcache.arch` and **flips the SoC pin from `ICache=0` to
`ICache=1`** so the cache is actually exercised. D1 is the first swap
of Phase D, the optional opentitan-flavoured tail of the project plan.
Phase D's selection criterion is "exercises the four arch-com
first-class constructs validated by the spike under
`spike/d-constructs/`": `ram` (kept SoC-side as `prim_ram_1p`),
`arbiter` (RAM-port priority arbitration inside the icache),
`cam` (fill-buffer associative lookup for in-flight-line hits),
and `thread` (per-fill-buffer lifecycle).

Bit-equivalence vs upstream is **not** a goal here. Functional
correctness against the spec at
`changes/2026-05-05-port-ibex_icache/specs/icache/spec.md` (599 lines,
33 RFC-2119 requirements, 10 G/W/T scenarios) is the bar. The
implementation is free to restructure the upstream's NUM_FB-element
register array into a CAM + per-entry threads, since the SoC-visible
contract (core-side handshake, OBI master, RAM port, scramble-key
handshake, busy/ECC/inval) is what matters.

## Scope

**In scope:**

- New `src/IbexIcache.arch` covering all 33 spec requirements,
  primarily the FSM (R-INV-1..7), request/lookup pipeline
  (R-REQ, R-LK), fill-buffer pool (R-FB, the CAM target), bus
  master (R-EXT), RAM-port arbitration (R-ARB), output stream
  (R-OUT), enable/inval/busy/ECC/reset (R-EN, R-INV-A..C, R-BUSY,
  R-ECC, R-RST).
- New `src/ibex_icache.archi` stub auto-emitted by the build.
- Modify `src/IbexTop.arch` to (a) hardcode `ICache=1` (mirroring
  the `param ICache[0:0]: const = 1'd1;` form already used for other
  pinned booleans), (b) instantiate `IbexIcache` between the
  `u_ibex_core` `ic_*` ports and the new RAM cells, (c) replace
  `gen_norams` tag/data tieoffs with `prim_ram_1p` instances
  matching upstream `gen_rams` (lines 707-770 of `ibex_top.sv`).
- New `src/prim_ram_1p.archi` hand-written stub (the RAM cells stay
  upstream SV — this is the same pattern as B4's
  `prim_secded_inv_*.archi` and A2's `prim_clock_gating.archi`).
- Update SoC binding `soc/ibex_mini_soc.sv` line 469 instantiation
  of `ibex_top_tracing` to pass `.ICache(1'b1)`.
- New `tests/cocotb_tests/test_ibex_icache_unit.py` (basic, 33
  spec-aligned tests) + `_unit_full.py` (regression covering 10
  scenarios + edge cases).

**Out of scope:**

- `ICacheECC=1`, `ICacheScramble=1`, `ICacheTweakInfection=1`
  (R-ECC-1 reduces ECC pipeline to dead code; spec §parameters).
- ECC error correction logic (`ibex_icache.sv:586-655`) — degenerate
  under `ICacheECC=0`.
- Tweak infection (`*_tweak_lw_*` paths) — pinned 0.
- `BranchCache=1` (allocate-on-branch only) — pinned 0.
- RVFI / formal-only ports (`ibex_icache.sv:1321-1334`).
- Lockstep / shadow paths.

## Construct enumeration

Per `feedback_proposal_construct_enumeration.md`. One row per
first-class construct from `arch-com/doc/ARCH_HDL_Specification.md`
§8-§12 (as of arch 0.60.1):

| Construct        | Status | Reason |
|------------------|--------|--------|
| `module`         | **picked** | Outer wrapper for `IbexIcache`. Hosts the RAM-port arb, output mux, skid buffer, and inst-blocks for the sub-constructs below. |
| `fsm`            | **picked** | `inval_state` (R-INV-1..7): 4 states (`OUT_OF_RESET`, `AWAIT_SCRAMBLE_KEY`, `INVAL_CACHE`, `IDLE`). Direct fit. |
| `thread`         | **picked** | One thread per fill buffer (NUM_FB=4 inst's of a `FillBuffer` thread): wait-for-allocate → emit bus reqs → collect rvalid beats → write-back → release. Encodes R-FB-3..6 lifecycle as sequential code instead of upstream's hand-managed per-cycle `_d`/`_q` array updates. |
| `fifo`           | rejected | The 16-bit IF-output skid buffer (R-OUT-6) is one register, not a queue. The fill-buffer pool is associative (CAM target), not FIFO. |
| `ram`            | rejected (form) | The actual tag/data SRAMs are SoC-side `prim_ram_1p` cells with module-external instantiation. The icache owns the *port*, not the *cells*. The construct fits but the cells stay upstream-SV per project plan. |
| `cam`            | **picked** | Fill-buffer associative lookup (R-LK-4, S4): on each IC1 cycle, query "is line L already in any live FB?" with KEY_W = line-tag-width, DEPTH = NUM_FB = 4. Insert on FB allocate, clear on FB release. Replaces upstream's `for (i: NUM_FB) fill_addr_q[i] == lookup_addr` reduction (`ibex_icache.sv:747`). |
| `linklist`       | N/A    | No ordered-list semantics in icache. |
| `regfile`        | N/A    | No register-file structure. |
| `arbiter`        | **picked ×2** | (a) RAM-port arbitration (R-ARB-1..4): 3 requesters under `ICacheECC=0` (invalidate-write, fill-write, lookup-read) with strict priority — `policy priority`, the construct as-is. (b) Inter-FB age-ordered arbitration (R-FB-4) over NUM_FB=4 buffers for bus master / RAM write-back / IF output stream — `policy custom <AgeOrderedGrant>`, validated by `spike/d-custom-arbiter/`. The icache uses (b) at three call sites with identical age-ordering semantics (different request masks). |
| `counter`        | rejected | The `inval_index_q` walker (R-INV-5) is small (`UInt<7>` saturating from 0 to `IC_NUM_LINES-1`) and lives inside the FSM body. The `counter` construct's free/lap/event API is more machinery than this needs; plain `reg + seq` is cleaner. |
| `pipeline`       | rejected | IC0→IC1 is one stage of latency entirely owned by the synchronous tag/data RAM read; the IC1-side of the lookup is naturally just `seq` capture of `ic_*_rdata_i`. No multi-stage data-dependent computation to schedule. |
| `synchronizer`   | N/A    | Single clock domain (`SysDomain` from soc). |
| `clkgate`        | N/A    | Clock gating happens at SoC level (`u_ibex.core_clock_gate_i`); the icache exposes `busy_o = 0` as a permission signal, no internal gate. |

**Inter-FB age-ordered arbitration (R-FB-4)** — bus-master, RAM
write-back, and IF-output-stream selection across NUM_FB live FBs is
"oldest eligible wins". Implemented as `arbiter policy custom
<AgeOrderedGrant>` per the spike at
`~/github/arch-ibex-d-spike/spike/d-custom-arbiter/`. Each FB's age
(0..3, 0=oldest) is supplied via a packed `UInt<8>` arbiter port; the
`AgeOrderedGrant` function returns a one-hot grant mask for the
oldest requester. Three call sites (instr-bus master, RAM write-back,
IF output) use the same function with different request masks. **Note:**
hook formal arg names must not collide with arbiter port names due to
arch-com#301 (custom-policy hook function emitted inside arbiter
module body causes `VARHIDDEN`). Workaround: hook formal is `ages`
(plural), call-site uses `age`. Drop the rename when arch-com#301 is
fixed.

## Approach

The implementation follows `feedback_spec_first_arch_blind.md`:
spec extraction (done), test-author from spec (next), arch-implement
from spec + test inventory (after that). The arch-implementer will
NOT see `ibex_icache.sv` or the test bodies. The arch implementer's
prompt will pin the construct mapping above so it doesn't drift.

**Construct skeleton the implementer will produce:**

```
ram ?   <-- not used; SoC instantiates prim_ram_1p cells; we declare
            their `.archi` stub and inst against it from IbexTop.arch

cam FillBufferCam
  param DEPTH = NUM_FB;
  param KEY_W = line-tag-width;
  // insert/clear on FB allocate/release;
  // search every cycle from IC1.

arbiter RamPortArb
  policy priority;
  param NUM_REQ = 3;  // [0]=inval-write (highest) [1]=fill-write [2]=lookup-read

function AgeOrderedGrant(req_mask: UInt<4>, ages: UInt<8>) -> UInt<4>
  // see spike/d-custom-arbiter/AgeOrderedArb.arch — pairwise-min over
  // 4 candidates, sentinel age=3 for non-requesters, returns one-hot.
end function

arbiter FbAgeArb            // used 3× (bus master / RAM wb / IF out)
  policy AgeOrderedGrant;
  param NUM_REQ = NUM_FB;
  port age: in UInt<8>;     // packed {age3,age2,age1,age0}
  hook grant_select(req_mask: UInt<NUM_FB>, ages: UInt<8>) -> UInt<NUM_FB>
    = AgeOrderedGrant(req_mask, age);  // call-site uses port name `age`

module IbexIcache
  // ports per spec §Module interface

  fsm InvalCtrl
    state OUT_OF_RESET / AWAIT_SCRAMBLE_KEY / INVAL_CACHE / IDLE
    // R-INV-1..7

  inst fb[NUM_FB]: FillBufferCtrl // see thread below

  inst tag_match_cam: FillBufferCam
  inst ram_arb: RamPortArb

  thread / module FillBufferCtrl
    // per-FB lifecycle:
    //   wait until allocated
    //   issue bus requests until line-beats received
    //   write back to RAM (if cache-allocate flag set)
    //   forward beats to IF output mux
    //   release
end module IbexIcache
```

**`prim_ram_1p` SV-cell `.archi` stub** — hand-written in
`src/prim_ram_1p.archi`, mirroring upstream `prim_ram_1p`'s pin
shape: `clk_i`, `req_i`, `write_i`, `addr_i`, `wdata_i`, `wmask_i`,
`rdata_o`. Width/Depth are unpacked params. Same `inst <stub>`
pattern as B4 `prim_secded_inv_*.archi`.

**IbexTop.arch deltas:**

1. Replace `param ICache[0:0]: const = 1'd0;` with `1'd1`.
2. Replace `gen_norams` block (currently around line 367) — instead
   of `ic_tag_rdata[w] = 0;` tieoffs, instantiate one `prim_ram_1p`
   per way per data/tag (4 cells total under `IC_NUM_WAYS=2`) and
   the new `IbexIcache` between `u_ibex_core` and the RAM cells.
3. Wire `ic_scr_key_valid` to constant `1'b1` (per
   `ibex_top.sv:581` under `ICacheScramble=0`).

**SoC delta:** add `.ICache(1'b1)` to the `ibex_top_tracing #(...)`
block at `soc/ibex_mini_soc.sv:469`.

## Tests

Per workflow:

- `tests/cocotb_tests/test_ibex_icache_unit.py` — basic suite, one
  cocotb coroutine per spec Requirement (33 tests), one
  representative scenario each.
- `tests/cocotb_tests/test_ibex_icache_unit_full.py` — full
  regression, every Scenario from spec §Scenarios + edge cases.
- ISR programs (full SoC gate) — re-run all 4 existing programs
  (`hello_world`, `irq_basic`, `irq_priority`, `csr_test` — confirm
  the actual list at gate time) under `ICache=1`. The cache should
  be invisible to ISR semantics; if a regression appears it points
  at a real icache bug.

## Risks

1. **First use of `arbiter policy priority` codegen path in
   arch-ibex** — spike only exercised `round_robin` (Phase D
   constructs spike). Construct itself is simple enough that
   no separate smoke is warranted; first build of `IbexIcache.arch`
   is the smoke. If `emit_arbiter_priority` has a bug we find it
   then.
2. **First use of `arbiter policy custom <fn>` codegen path** —
   validated by `spike/d-custom-arbiter/AgeOrderedArb.arch`
   (custom-policy 4-requester age-ordered arbiter, lints clean
   after working around arch-com#301). The icache will reuse the
   exact `AgeOrderedGrant` function from the spike at three call
   sites; no further codegen-path uncertainty.
3. **CAM same-cycle insert+match semantics** — the spec's R-LK-4
   ("FB-hit MUST return data without redundant bus request") is
   permissive (R-LK-4 NOTE: occasional double-allocate is upstream
   behaviour); a CAM that misses an insert-then-match in the same
   cycle is still correct. But if we want the *strengthened*
   contract (always coalesce), insert visibility on the same cycle
   matters. arch-com's CAM `match_policy` defaults TBD; the
   implementer should default to permissive R-LK-4 (no
   strengthening) and only revisit if tests demand it.
3. **`prim_ram_1p` pin-name mismatch** — upstream uses `Width`,
   `Depth`, `MemInitFile` params. The hand-written `.archi` must
   match exactly or `inst` will fail Verilator lint. Verify against
   `~/github/ibex/vendor/lowrisc_ip/ip/prim_generic/rtl/prim_generic_ram_1p.sv`.
4. **Sticky `valid_o` across `ready_i = 0`** — R-OUT-2 + spec
   ambiguity #2. The implementer needs to be told explicitly that
   `branch_i` is the canonical override; otherwise it may produce
   a sticky-valid that fights branch redirects.
5. **Cache disabled corner** (R-EN-2): lookups still issue bus
   reqs but don't allocate. Easy to implement wrong as "skip
   everything when disabled." Spec §R-EN is clear; tests should
   bind to it.

## Related work

- arch-com PR #294 (merged): `unpacked` modifier preserved in
  `.archi` emit + doc-comments above `local param` parse.
- arch-com PR #295 (merged): cam `.archi` emit + arbiter ports[N]
  group + arbiter inst-site vector wire + RAM user-param
  propagation. **All four fixes were surfaced by the D1 spike;**
  D1 implementation depends on them.
- spike `~/github/arch-ibex-d-spike/spike/d-constructs/` — proves
  ram + arbiter + cam + thread compose into one outer module and
  emit lint-clean SV (one benign PINMISSING).
- spike `~/github/arch-ibex-d-spike/spike/d-custom-arbiter/` —
  validates `arbiter policy custom <fn>` codegen for the age-ordered
  R-FB-4 arbitration; surfaced arch-com#301 (hook function shadows
  arbiter ports — workaround: rename hook formals).
- arch-com#301 — open. D1 lands the workaround; future swaps drop
  the hook-formal rename when fixed.

## Done when

- `src/IbexIcache.arch` builds and emits SV that lints under
  Verilator.
- All 33 basic-suite cocotb tests pass.
- Full SoC build green with `ICache=1` (RAMs wired, no
  PINMISSING/UNDRIVEN).
- All 4 ISR programs pass.
- Background regression on `_unit_full.py` reports green (or any
  failure root-caused).
- C2's RV32IMC compliance reference signature (74/74) re-runs green
  under `ICache=1`.
- `READY.md` updated.
