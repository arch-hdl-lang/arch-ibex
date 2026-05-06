# READY — D2 IbexPmp

## Status: READY TO ARCHIVE

All steps 1–8 of WORKFLOW.md are complete for Phase D swap D2 (IbexPmp).
First arch-ibex swap to follow the **D1-lessons workflow updates**
(spec ambiguity resolutions in proposal, cross-scenario tests in
`_unit_full.py`, construct-compliance audit at Stage 1 review).

## What was done

1. **Spec** (`specs/pmp/spec.md`, 500 lines) — 22 RFC-2119
   requirements across R-MODE / R-PERM / R-MML / R-MMWP / R-DBG /
   R-PRIO / R-CHAN, 10 G/W/T scenarios, 5 spec ambiguities flagged
   (each with a `> Resolution:` line).

2. **Proposal**
   (`changes/archive/2026-05-06-port-ibex_pmp/proposal.md`) — first
   arch-ibex proposal with the new `## Spec ambiguity resolutions`
   table (5 rows, A1–A5: MML retroactive, DmAddrMask non-contiguous,
   NAPOT degenerate, mseccfg.rlb unused, reserved pmp_req_e).
   Construct enumeration: only `module` picked; everything else
   rejected (combinational permission checker, no state).

3. **Tests** (22 basic + 28 full = 50 cocotb tests, 0 skips):
   - `tests/cocotb_tests/test_ibex_pmp_unit.py` — one test per RFC-2119
     MUST.
   - `tests/cocotb_tests/test_ibex_pmp_unit_full.py` — every Scenario
     S1..S10 + **5 cross-scenario integration tests** (multi-match ∩
     MMWP, locked ∩ MML, debug ∩ MML, per-channel ∩ multi-region,
     TOR-chain ∩ priority) per the new WORKFLOW.md rule + 13 edge
     cases. **NO `boot_during_cold_init` test** (PMP isn't a
     fetch-path module).

4. **Implementation** (`src/IbexPmp.arch`, 602 LoC) — single
   `module ibex_pmp` with one `comb` block. Pure combinational; no
   `seq`, no `reg`, no clock, no reset. Per-region NAPOT mask uses
   the closed form `size_mask = v ^ (v + 1)` for `v =
   csr_pmp_addr[r][33:2]`. Per-region per-channel match unrolled
   for `PMPNumRegions=4` × `PMPNumChan=3` (12 cells of work).

5. **SoC integration** — none. Module is built standalone and
   unit-tested. Under SoC pinning `PMPEnable=0` it is not
   instantiated; flipping `PMPEnable=1` is a follow-up swap (not
   D2).

6. **Two-stage review** — spec-compliance + construct-compliance
   audit (Stage 1, new in D1-lessons). Construct audit: only
   `module` was pinned `picked` and the impl uses only `module`.
   Trivially compliant.

7. **Basic gate** — `pytest tests/test_ibex_pmp_unit.py
   tests/test_soc_lint.py tests/test_cpu_programs.py` →
   **22 / 22 PASS, 0 FAIL, 0 SKIP** for PMP unit, SoC lint
   **GREEN**, all 5 ISR programs PASS (unchanged from D1).

8. **Full regression** — `pytest tests/test_ibex_pmp_unit_full.py`
   → **28 / 28 PASS**.

## Key design decisions

- **Constructs exercised**: only `module` (intentional per the
  proposal — PMP is pure combinational with no state).
  The proposal correctly rejected `cam`, `arbiter`, `fsm`, etc.;
  the audit at Stage 1 confirmed the impl matches.

- **Type encoding** — `pmp_cfg_t`, `pmp_mseccfg_t`, `pmp_req_e`,
  `priv_lvl_e`, `pmp_cfg_mode_e` modeled as raw `UInt<W>` with
  `let` constants for the encoding values. No `package` since
  these types aren't used by other arch swaps (PMPEnable=0 SoC).
  Field access via slice (e.g. `csr_pmp_cfg_i[0][5]` for `lock`).

- **NAPOT closed form** — `size_mask = v ^ (v + 1)` is the
  smallest expression that captures the spec's "trailing-1
  prefix from bit 2 of csr_pmp_addr is don't-care" rule. Edge
  case: `v=0` gives `mask=1` (only bit 0 of slice = bit 2 of addr
  is don't-care), making the smallest NAPOT region 8 bytes —
  consistent with NAPOT minimum (NA4 covers the 4-byte case).

- **Spec scenario S3 was wrong** — the spec's `csr=0x1F → 16-byte
  at base 0x10` doesn't match the spec's own algorithm REQ-MODE-3
  (which gives 64 bytes at base 0). The correct pmpaddr for
  16-byte at base 0x10 is `csr=0x14`. Eight tests had the wrong
  encoding because they followed S3; all corrected to use
  algorithm-consistent values. **Workflow lesson:** spec-stage
  review should hand-evaluate at least one Scenario per algorithm
  rule.

- **R-DBG-3 spec rule** — bypass test ignores bits [33:32]. Initial
  impl required them to be zero; corrected to drop the check per
  the spec's literal "ignore" wording.

## arch-com PRs / issues filed during D2

None. The PMP port surfaced no new arch-com bugs (D1's six issues
already cover the territory).

## Workflow lessons surfaced (potential WORKFLOW.md follow-up)

- Spec scenarios can be self-inconsistent with their own
  algorithm. The construct-compliance audit (Stage 1) doesn't
  catch this — it only verifies impl-vs-spec, not spec-vs-spec.
  A "Scenario hand-evaluation" check at spec-stage review or
  test-author stage could catch it. (Not blocking D2; flagged for
  future workflow iteration.)

- Test author misunderstandings about address encoding (byte vs
  word, slice semantics) propagated into 8 test setup bugs that
  all needed correction during impl-stage debugging. A "drive a
  reference helper that converts byte-PA to the port format" in
  the test scaffold could prevent this systematically.

## Files produced

- `src/IbexPmp.arch` (NEW, 602 LoC).
- `specs/pmp/spec.md` (NEW, materialised from change folder).
- `tests/cocotb_tests/test_ibex_pmp_unit{,_full}.py` (NEW).
- `tests/test_ibex_pmp_unit{,_full}.py` (pytest collectors, NEW).
- `changes/archive/2026-05-06-port-ibex_pmp/` (proposal,
  spec-source, tests-inventory, archived).

## Not done (stop before step 9)

Archive step (step 9) is intentionally NOT done — the parent
orchestrator will serialise the archive commit. The change folder
is already moved to `changes/archive/`; only the git commit
remains.

D2-flip (toggle SoC `PMPEnable=1` and instantiate `IbexPmp` in
IbexCore) is a separate follow-up swap; D2 ships as a
standalone-module port.
