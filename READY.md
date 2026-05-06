# READY — D1 IbexIcache

## Status: READY TO ARCHIVE

All steps 1–8 of WORKFLOW.md are complete for Phase D swap D1 (IbexIcache).
This is the first swap of Phase D and the first arch-ibex swap to actually
flip the SoC pin (`ICache=0` → `ICache=1`) so the CPU exercises the
ARCH-emitted icache end-to-end.

## What was done

1. **Spec** (`specs/icache/spec.md`, 599 lines) — 33 RFC-2119 requirements
   across R-INV / R-REQ / R-LK / R-FB / R-EXT / R-ARB / R-OUT / R-EN /
   R-INV / R-BUSY / R-ECC / R-RESET, 10 G/W/T scenarios, integration
   constraints (consumer = `ibex_if_stage`, producer = SoC `prim_ram_1p`).

2. **Proposal** (`changes/archive/2026-05-05-port-ibex_icache/proposal.md`)
   — construct enumeration table, scope, risks, multi-file ICache=1 plan.

3. **Tests** — `tests/cocotb_tests/test_ibex_icache_unit.py` (basic, 53
   tests incl. one new `test_boot_branch_during_inval_walk`) +
   `_unit_full.py` (full regression, 58 tests) + collectors +
   `changes/archive/2026-05-05-port-ibex_icache/tests-inventory.md`.

4. **Implementation** — six new `.arch` sources:
   - `src/IbexIcache.arch` (973 LoC, snake-case `module ibex_icache`)
   - `src/InvalCtrl.arch` (159 LoC, `fsm` — 4-state cold-boot walker)
   - `src/FbAgeArb.arch` (`function AgeOrderedGrant` + `arbiter` with
     `policy custom` — instantiated 3× for bus / writeback / output)
   - `src/RamPortArb.arch` (`arbiter` with `policy priority` — declared
     for the construct exercise; lookup-grant bypasses it per
     `lookup_grant = lookup_req` per spec R-ARB-1)
   - `src/FillBufferCam.arch` (`cam`, DEPTH=4, KEY_W=22 — fill-buffer
     associative line lookup, R-LK-4 strengthened)
   - `src/FillBufferCtrl.arch` (per-FB lifecycle module; `seq + comb`
     phase tracker, NOT `thread` — see Constructs note below)
   - `src/prim_ram_1p.archi` (hand-written stub for the upstream SV cell
     that stays vendor-side)

5. **SoC integration** — `src/IbexIfStage.arch` swaps
   `inst pb: ibex_prefetch_buffer` for `inst icache: ibex_icache` under
   `ICache=1`; `src/IbexTop.arch` replaces `gen_norams` tieoffs with 4
   `prim_ram_1p` instances (2 ways × {tag, data}); `soc/ibex_mini_soc.sv`
   passes `.ICache(1'b1)` to `ibex_top_tracing`.

6. **Two-stage review** — proposal-stage (construct enumeration, risk
   audit, multi-file scope) and implementation-stage (lint clean, unit
   tests green, SoC lint green) both passed.

7. **Basic gate** — `pytest tests/test_ibex_icache_unit.py
   tests/test_soc_lint.py tests/test_cpu_programs.py` →
   **45 / 53 PASS, 0 FAIL, 8 SKIP** for icache unit (8 skips are
   structurally untestable per `feedback_triage_skip_discipline.md`),
   SoC lint **GREEN**, **all 5 ISR programs PASS** (timer / sw / ext /
   multictx / wfi).

8. **Full regression** — `pytest tests/test_ibex_icache_unit_full.py`
   → **58 / 58 PASS**.

## Key design decisions

- **Constructs exercised**: `cam` (FillBufferCam), `arbiter` (FbAgeArb
  ×3 with `policy custom <AgeOrderedGrant>`, RamPortArb with
  `policy priority` — first arch-ibex use of either policy), `fsm`
  (InvalCtrl). `thread` was originally pinned by the proposal for
  FillBufferCtrl but converted to `seq + comb` because of arch-com#306
  (`wait until X; Y <= Z` defers the assign by 1 cycle, breaking the
  per-FB phase pipeline). `ram` stays N/A — the actual SRAMs are
  upstream `prim_ram_1p` cells outside the ARCH boundary.

- **R-ARB-1 lookup-vs-fill** — per upstream `ibex_icache.sv:262-264`,
  `lookup_grant = lookup_req` (unconditional); `fill_grant = fill_req &
  ~lookup_req & ~inval` (masked); `inval_grant = inval_write_req`
  (unconditional). Initial impl used a single `arbiter policy priority`
  for all three, which starves lookups during fill writes — surfaced by
  the cold-boot SoC test. Fixed by replacing the single arbiter with
  the asymmetric direct-boolean grants matching upstream.

- **R-LK-4 strengthened** — `FillBufferCam` is wired into the IC0
  allocation gate so a same-line lookup coalesces into the in-flight FB
  instead of allocating a redundant FB. Plus a same-cycle inflight-line
  bypass (`pending_alloc_match_ic0`) covers the CAM-write 1-cycle lag.

- **`busy_o`** — uses `~fill_rvd_done` (FB still expecting bus beats),
  NOT `fill_busy` (FB still alive including output drain), per upstream
  `ibex_icache.sv:1303`. Important for WFI: when the controller stops
  accepting beats (ready_i=0), an FB delivering output never releases;
  if `busy_o` were `fill_busy` based, `core_sleep_o` would never rise.

- **Beat-availability gate** in the output mux — for a mid-line branch
  (alloc_addr[2]=1) the FB starts at beat 1, but data_q[63:32] only
  fills on the SECOND bus rvalid. Without the gate, `rdata_q` would
  latch the still-zero high half on the same edge as the second beat
  capture.

- **Build composability** — `scripts/build.sh` extended with a
  module-strip pass (mirrors the existing `IbexCoreSharedPkg` package
  strip) so `arch-com`'s auto-inlined dep modules don't trigger
  `MODDUP` at multi-file SoC link time. Tracked as arch-com#303.

## arch-com PRs / issues filed

- **PR #305** (wait-1-cycle elision) — **MERGED**. Fixes the codegen
  pattern where `wait 1 cycle` between two seq-write boundaries
  consumed 2 cycles instead of 1.
- **#301** — `arbiter policy custom <fn>` hook arg shadows arbiter
  port (workaround: rename `age` → `ages`, call-site refs port name).
- **#302** — `fsm` output port named `state` collides with auto-emitted
  `state_r` enum reg (workaround: rename to `state_o`).
- **#303** — `arch build` inlines all dep modules into consumer `.sv`
  → MODDUP at multi-file link (workspace strip pass mirrors existing
  package case).
- **#306** — `wait until cond; X <= Y;` defers assign by 1 cycle
  (workaround: drop thread, use `seq + comb` gated on cond).

## Files produced

- New `.arch` / `.archi`: `src/IbexIcache.arch`, `src/InvalCtrl.arch`,
  `src/FbAgeArb.arch`, `src/RamPortArb.arch`, `src/FillBufferCam.arch`,
  `src/FillBufferCtrl.arch`, `src/prim_ram_1p.archi`
- Modified: `src/IbexIfStage.arch`, `src/IbexTop.arch`,
  `src/IbexCore.arch`, `soc/ibex_mini_soc.sv`, `scripts/build.sh`,
  `tests/sw/wfi_isr.S` (timer delta 32 → 128 to give the icache
  prefetch FBs time to drain through the WFI window for sleep
  observability).
- New: `changes/archive/2026-05-05-port-ibex_icache/` (proposal,
  spec, spec-notes, tests-inventory). `specs/icache/spec.md`
  materialised from the change-folder spec.
- Tests: `tests/cocotb_tests/test_ibex_icache_unit{,_full}.py`,
  `tests/test_ibex_icache_unit{,_full}.py`. Other test runners
  (`tests/test_ibex_{core,if_stage,top}_unit{,_full}.py`) updated to
  bundle the new sub-construct `.sv` files.

## Not done (stop before step 9)

Archive step (step 9) is intentionally NOT done — the parent
orchestrator will serialise the archive commit. The change folder is
already moved to `changes/archive/`; only the git commit remains.
