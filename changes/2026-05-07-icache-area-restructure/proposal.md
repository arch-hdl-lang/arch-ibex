# Proposal: IbexIcache area restructure — centralize fill-data + beat tracking

## Status

DRAFT. Not yet approved. Spec is unchanged (no behavior change), so
this proposal stays purely structural.

## Intent

Close the +12,185 µm² (+40%) gap between `arch-ibex` and upstream
on the icache.

| state | sky130 area | vs upstream |
|---|---|---|
| upstream `ibex_icache` | 30,170 µm² | — |
| swap (current `combined/perf-alu-and-multdiv`) | 42,355 µm² | +12,185 (+40%) |

The skid registers themselves match upstream (16-bit data + valid + err
= 18 FFs each side, ~90 µm² of storage). PR #29 (halfword + skid)
contributed +3,481 µm² of *combinational* logic — not the storage but
the muxes around it. The remaining +8,704 µm² predates skid and is
present even with the bare R-OUT path.

## Root cause

`arch-ibex` `IbexIcache` instantiates four `FillBufferCtrl` submodules,
each owning its own line-data, line-address, beat-error flags, and
`beats_rcvd_q` counter. The outer module then surfaces these via
**eight** N:1 muxes at the output stage:

```arch
let fb_addr_out_sel: UInt<32> =
  (out_grant_requester == 2'd0) ? fb0_addr :
  ((out_grant_requester == 2'd1) ? fb1_addr :
  ((out_grant_requester == 2'd2) ? fb2_addr : fb3_addr));
let fb_data_out_sel:        UInt<64> = …;   // 64-bit
let fb_err_out_sel:         Bool     = …;
let fb_err_beat0_out_sel:   Bool     = …;
let fb_err_beat1_out_sel:   Bool     = …;
let fb_beats_rcvd_out_sel:  UInt<2>  = …;
// + per-FB out_beat_q (Vec<UInt<2>, 4>)
// + per-FB hit-data fast-path mux ic1_hit_beat_data
```

That's:
- 1× 4:1 mux of 64-bit line data (≈ 64 × 7 µm² = 450 µm²)
- 1× 4:1 mux of 32-bit address (≈ 32 × 7 µm² = 225 µm²)
- 4× 4:1 mux of single-bit flags
- 1× 4:1 mux of 2-bit `beats_rcvd`
- 4-element `out_beat_q` Vec keyed by `out_grant_requester`
- All of the above feed into `need_skid_load`, `skid_complete_instr`,
  `out_beat_data`, etc., compounding fanout

Upstream's structure flattens this. `fill_data_q[NUM_FB][LINE_SIZE]`
is a centrally-declared 2-D array; `output_addr_q` is one register;
selection happens via a `fill_data_sel[fb]` one-hot AND'd into the
read of the central array — yosys lowers this to a single
broadside mux without traversing N stub modules.

The +8,704 µm² gap = "structural cost of the per-FB submodule
boundary" (each FB carries its own copies of state that upstream
expresses as indices into shared arrays).

## Proposed restructure

Move fill-data + beat tracking out of `FillBufferCtrl` and into the
outer `IbexIcache` module, so each per-FB submodule owns only its
**control state** (the `Phase` FSM, hit/rvd/done flags). The bulky
data and address remain centralized.

### New ownership

| state | before | after |
|---|---|---|
| `Phase` FSM (`PhEmpty`/`PhAlloc`/`PhRunning`/…) | per-FB FillBufferCtrl | per-FB FillBufferCtrl (unchanged) |
| `fill_addr_q[fb]` (32 bits × 4) | per-FB FillBufferCtrl | outer `IbexIcache` (Vec) |
| `fill_data_q[fb][LINE_SIZE]` (64 bits × 4) | per-FB FillBufferCtrl | outer `IbexIcache` (Vec) |
| `fill_err_beat_q[fb][2]` (2 bits × 4) | per-FB FillBufferCtrl | outer `IbexIcache` (Vec) |
| `beats_rcvd_q[fb]` (2 bits × 4) | per-FB FillBufferCtrl | outer `IbexIcache` (Vec) |
| `hit_q[fb]` / `rvd_q[fb]` / `done_q[fb]` | per-FB FillBufferCtrl | per-FB FillBufferCtrl (unchanged) |
| `out_beat_q[fb]` (2 bits × 4) | outer (already) | outer (collapsed to single `output_addr_q[2]`) |

The Phase FSM stays per-FB — it's the entire reason `FillBufferCtrl`
exists as a separate module. Only the data carrier moves.

### New interface

`FillBufferCtrl` shrinks from "owns a line" to "owns a lifecycle":
- Inputs: alloc / hit / bus_rvalid / inval / branch / shared
  alloc_addr.
- Outputs: `phase_o` (or finer `wants_*` flags), `hit_o`, `rvd_o`,
  `done_o`, `addr_we_o` (write-enable strobe to outer addr Vec),
  `data_we_o[3:0]` (per-beat write-enable strobe to outer data Vec).

The outer module instantiates a 4-element `Vec<UInt<32>, 4>` for
addresses and `Vec<UInt<64>, 4>` for data, each updated by the
per-FB write-enable strobes from the lifecycle FSMs:

```arch
reg fill_data_q: Vec<UInt<64>, 4> reset rst_ni => 64'd0;
reg fill_addr_q: Vec<UInt<32>, 4> reset rst_ni => 32'd0;

seq on clk_i rising
  for fb in 0..3
    if fb_addr_we[fb]    fill_addr_q[fb] <= alloc_addr; end if
    if fb_data_we[fb][0] fill_data_q[fb][31:0]  <= ic_data_rdata_i; end if
    if fb_data_we[fb][1] fill_data_q[fb][63:32] <= ic_data_rdata_i; end if
  end for
end seq
```

Output stage simplifies to a single `output_addr_q` (no per-FB
`out_beat_q`):

```arch
let out_line: UInt<64> = fill_data_q[out_grant_requester];
let out_beat_data: UInt<32> =
  output_addr_q[2] ? out_line[63:32] : out_line[31:0];
```

The `fb_*_out_sel` 4:1 muxes collapse to a single Vec read indexed by
`out_grant_requester`, which yosys lowers to one broadside mux.

## Spec impact

**None.** R-FB, R-EXT, R-OUT, R-LK contracts are unchanged. The
proposal is invariant under output observation: every R-* requirement
is stated in terms of `valid_o` / `rdata_o` / `addr_o` / `err_o` /
busy / inval / scramble-key handshakes — none reference fill-buffer
internal layout.

The `cam` first-class construct usage (R-FB-2 in-flight-line hit)
stays the same — the CAM lookup keys on `fill_addr_q[fb]` whether
that lives inside or outside FillBufferCtrl. The CAM port wiring
shifts from "FillBufferCtrl exposes its addr port" to "outer module
provides the addr Vec to the CAM directly", which is simpler.

## Risks & mitigations

| risk | mitigation |
|---|---|
| Skid logic from PR #29 is in the output stage. Restructure must preserve it. | Keep the entire `seq on clk_i rising` skid block; only the *inputs* change (single Vec read instead of 8 N:1 muxes). |
| `branch_i` clears in-flight FB state. Per-FB ownership of `addr_we` strobes must propagate the cancel correctly. | FillBufferCtrl's lifecycle FSM already handles `branch_i`; the strobe gating already happens there. No semantic change. |
| 4-element Vec writes from per-FB strobes need `for fb in 0..3` lowering. Past sessions have hit Vec-write-from-loop quirks. | Pre-build smoke test (per `feedback_pre_build_smoke_checks.md`): write a 1-FB toy first, confirm Vec-indexed seq writes lower correctly. |
| The 4-FB CAM was the validating use case for `cam` in Phase D. Pulling state out of FillBufferCtrl might appear to weaken that. | The CAM is unchanged — it still associates 4 in-flight addresses against `lookup_addr`. Only the *home* of the addresses moves. |
| Regression: any spec scenario that depended on FillBufferCtrl's old line-data-write-back propagation. | Full SoC gate (`make build && make test`, 129/74) before/after — must stay 129 passed. |

## Construct enumeration (per `feedback_proposal_construct_enumeration.md`)

| construct | status | notes |
|---|---|---|
| `module` | picked | Outer `IbexIcache` and per-FB `FillBufferCtrl` (now lighter). |
| `fsm` | N/A | The per-FB FSM stays inside FillBufferCtrl as `seq on clk` + state enum (current shape); not converted to `fsm` block. |
| `thread` | rejected | FillBufferCtrl already considered + rejected by the original D1 proposal in favor of `seq on clk`; that judgment stands — moving data out doesn't change the lifecycle complexity. |
| `cam` | picked (unchanged) | CAM lookup over `fill_addr_q` for R-FB-2; ownership move keeps the construct, only changes the address port source. |
| `arbiter` | picked (unchanged) | RAM-port and out-arbiter both stay; no change. |
| `fifo` | N/A | Icache has no FIFO; output is single-beat handshake. |
| `ram` | N/A | Tag/data RAM stays SoC-side as `prim_ram_1p`. |
| `linklist` | N/A | |
| `bus` | N/A | OBI handled via direct port wiring per existing convention. |
| `package` | maybe | The lifecycle Phase enum + alloc_addr type are currently inline in FillBufferCtrl; if pulling them outer, may need to extract to a `Pkg` per `feedback_shared_types_package.md`. |
| `shared function` | N/A | No expensive pure functions called from multiple states. |

## Spec ambiguity resolutions (per `feedback_proposal_must_resolve_ambiguity.md`)

None. This is a structural rework; no spec ambiguity is in play.
The R-* requirements in
`changes/archive/2026-05-05-port-ibex_icache/specs/icache/spec.md`
constrain external behavior only and are agnostic to where the line
data lives.

## Expected outcome

| metric | current | target | reasoning |
|---|---|---|---|
| ibex_icache area | 42,355 µm² | ~32,000–34,000 µm² | Eliminates 8 of the 4:1 muxes (≈ 1,200 µm²) and lets yosys CSE the centralized Vec read across the skid + ic1-fast paths (≈ 6,000–8,000 µm² savings). |
| gap to upstream | +40% | +5–12% | Residual gap = CAM area + per-FB FSM duplication, both unavoidable under the chosen `cam` + 4× FB architecture. |
| SoC top area | 138k µm² | 130k µm² | Icache is the dominant area driver after multdiv; closing 8k here moves the SoC top by ~6%. |
| timing (clock period) | unchanged | unchanged | The restructure removes mux levels from the data path but doesn't change critical-path topology. |
| gate (tests/test_*.py) | 129 passed | 129 passed | Bit-equivalent observable behavior. |

## Out of scope

- Reducing NUM_FB below 4 (would be an SoC-visible change to bus
  pipelining behavior; needs separate proposal).
- Replacing the per-FB Phase FSM with a single shared FSM (kills the
  parallelism that makes `cam` valuable).
- Re-walking the skid logic (PR #29's design is correct and matches
  upstream; only its operand-mux fanout changes here).

## Verification plan

1. Smoke-test Vec-indexed seq writes per the pre-build pattern.
2. Implement restructure on a branch from `combined/perf-alu-and-multdiv`.
3. Per-stage gate:
   - archsim (`tests/test_archsim_units.py::test_archsim_unit -k IbexIcache`).
   - icache unit (`tests/cocotb_tests/test_ibex_icache_unit_full.py`).
   - Full SoC (`make build && make test`).
4. Synth re-measure: isolated icache + full SoC top + STA on critical path.
5. Compare against this proposal's targets; iterate or revert if
   savings are < 5,000 µm² or any test regresses.

## Open questions

1. Does pulling `fill_addr_q` to the outer module require also pulling
   `fill_alloc_idx` (the index that maps allocator→FB)? If yes, the
   address-source for CAM lookup gets simpler; if no, the FB still
   needs to expose its own address.
2. Should the restructure also collapse the `fb_err_beat0` /
   `fb_err_beat1` flags into a single `Vec<Bool, 2>` in the outer
   module, indexed by beat? Likely yes for symmetry with `fill_data_q`.
3. Are there formal-verification asserts in upstream that key on
   the per-FB ownership? If so, those need to migrate to the outer
   module's invariants.
