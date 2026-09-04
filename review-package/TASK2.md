# TASK2: fix the blockers and produce post-P&R evidence for both lanes

Continuation of `review-package/TASK.md`. Read `review-package/00-summary.md`
through `04-synthesis.md` first; they record the state you are starting from,
in particular:

- the Arch lane only compiles with a rebuilt `arch 0.70.0 @ 2ffcc60b`;
  the current compiler rejects `src/IbexIcache.arch`;
- with the compiler-generated handshake assertions enabled, the Arch lane
  fails all 10 CPU programs at ~140 ns on
  `FbAgeArb._auto_hs_request__lane_valid_stable` (icache requester lane 2
  drops `valid` before `ready`);
- every Arch-lane synthesis number comes from notes whose scripts and
  reports are gone; no timing exists for either lane; no P&R exists at all.

This task fixes those, then produces fresh, committed, reproducible
synthesis and post-place-and-route results on both lanes.

## Ground rules

- Work on branch `review-package`. Commit at the end of each phase with a
  plain descriptive message. Do not push. Do not add any AI-authorship
  trailer or co-author line to commit messages.
- All new scripts go under `flow/` in the repo, never under `/tmp` or a
  scratch directory. All reports go under `review-package/reports/`,
  prefixed `sv_` or `arch_` by lane. The whole point is that nothing is
  lost again.
- Record every tool version you use in `review-package/10-toolchain.md`
  (`arch --version` + arch-com commit, verilator, yosys, nextpnr-ecp5,
  openroad, sv2v, python/cocotb).
- Both lanes get identical constraints, clock targets, parameters, file
  lists (except the swapped modules), and tool versions. If a lane fails
  timing, report the failure; do not loosen the constraint for one lane.
- Ask before: any run longer than ~15 minutes, any change to `src/*.arch`
  beyond what Phase 1–2 require, and any change under `flow/` that alters
  what is being measured.
- Every number in a deliverable cites the report file it came from.

## Phase 0 — Compiler pin (write `review-package/10-toolchain.md`)

1. Check out and build arch-com at tag/commit for release **0.70.6** (the
   version pinned in the paper). Record the commit.
2. `make build` the port with it. Report pass/fail per file.
3. If it fails, also try the newest release tag. Report which releases
   build the port cleanly.
4. Stop and report. I will choose the pin. Do not start Phase 1 until I
   confirm the version.

## Phase 1 — Make the port compile on the chosen pin

1. For each file the pinned compiler rejects, show me the diagnostic and
   propose the minimal source change. The `IbexIcache.arch` "operands at
   cycle 0 and N" error is the known one.
2. Apply only changes I approve. Keep a diff of every change in
   `review-package/11-port-changes.md` with a one-line rationale each.
3. Re-run `arch check` on all 23 files with the pinned compiler; commit
   the log as `reports/arch_check_pinned.log`.

## Phase 2 — Resolve the icache handshake violation and get a green gate

1. Diagnose, don't patch. Determine whether upstream Ibex's icache
   legitimately retracts a fetch request (e.g., on branch redirect) before
   it is granted. Cite the upstream file and lines. Then determine which
   is true:
   (a) the port faithfully reproduces upstream behaviour and the
       compiler's `valid_ready` contract on that arbiter port is stricter
       than the protocol the design actually uses, or
   (b) the port introduced a retraction upstream does not perform.
2. Write the finding to `review-package/12-icache-handshake.md` before
   changing anything, and wait for my go-ahead.
3. Fix accordingly. For (a) the expected fix is declaring that channel
   with the handshake variant that matches the real protocol (or a
   `valid_only`-style lane if retraction is legal), not deleting the
   assertion. For (b) fix the port logic. Record the diff in
   `11-port-changes.md`.
4. Run the full gate with assertions ON (no `--no-assert` anywhere):
   - `make lint`
   - `make test` (all suites, including per-module unit suites and
     `test_archsim_units.py`)
   - `tests/test_arch_tests.py` (74 signatures vs upstream references)
   - `RUN_COREMARK_COMPARE=1 pytest tests/test_coremark_compare.py`
   Commit junit XML and logs for each. Report pass/fail/skip counts and
   wall time per suite, per lane where the suite applies to both.
5. If anything fails, stop and show me. Do not mark tests skipped to get
   green.

## Phase 3 — Lint delta (write `review-package/13-lint.md`)

1. Re-run the core-level Verilator `-Wall` lint on both lanes (the
   `ibex_top` file lists from the earlier task), with and without
   waivers, using the Phase-2 generated SV. Commit logs.
2. Classify every warning class present on the Arch lane but not the SV
   lane into: (i) caused by single-configuration hard-coding
   (`UNUSEDPARAM`/`UNUSEDSIGNAL` from parameters the port fixes),
   (ii) emitted by the compiler (e.g. `PROCASSINIT`, `UNOPTFLAT`),
   (iii) other. For (ii), record the exact generated-SV pattern so it can
   be filed against arch-com; do not fix it in the generated SV by hand.

## Phase 4 — sky130 synthesis + STA + post-P&R, both lanes

Target: `ibex_top` in the port's configuration (RV32IMC, RV32MFast,
2-stage, ICache=1 with 256 lines, PMP=1 with 4 regions, FF regfile, no
branch predictor). Both lanes use the same parameter overrides.

4.1 Source lists. Build two file lists under `flow/`:
`flow/ibex_top_sv.f` (upstream) and `flow/ibex_top_arch.f` (upstream with
`build/*.sv` shadowing), derived the same way as the lint lists. Use
`prim_generic_*` RAM implementations so memories are inferred, not
black-boxed.

4.2 sv2v both lists to single-file Verilog (`flow/out/{sv,arch}/ibex_top.v`).
Report any sv2v error per lane.

4.3 Logic synthesis + STA (replaces the lost numbers). Write
`flow/sky130_synth.sh` that runs, for each lane: Yosys `synth -flatten`
with the same `memory -nomap` handling the old notes describe, map to
`sky130_fd_sc_hd` tt corner, `stat -liberty`, then OpenSTA with an SDC
that sets one clock at the same period for both lanes (start at 10 ns).
Confirm OpenSTA reports zero black-boxed cells; if any appear, stop and
show me. Commit `arch_sky130_synth_area.rpt`, `sv_sky130_synth_area.rpt`
and the STA reports.

4.4 Post-P&R with OpenROAD-flow-scripts. ORFS ships a sky130hd Ibex
design (`flow/designs/sky130hd/ibex/`). Create two design configs under
`flow/orfs/{sv,arch}/config.mk` copied from it, pointing `VERILOG_FILES`
at the sv2v outputs, with identical `CORE_UTILIZATION`, `PLACE_DENSITY`,
`CLOCK_PERIOD`, and constraint files. Run the full flow for both lanes
(ask first; each run may take 30–90 minutes). Commit for each lane:
`*_orfs_final_area.rpt` (`report_design_area`), `*_orfs_final_timing.rpt`
(`report_wns`, `report_tns`, `report_checks -path_delay max` top paths),
`*_orfs_final_power.rpt`, the final GDS/DEF is NOT needed. Record: cell
count, stdcell area, utilization, WNS, TNS, achieved fmax (1 /
(period − WNS) when WNS < 0, else report period met), power.

Write `review-package/14-sky130.md` with one table per metric family,
both lanes side by side, and the exact commands.

## Phase 5 — ECP5 post-P&R with Yosys + nextpnr, both lanes

Same `ibex_top` target and parameters. Write `flow/ecp5_pnr.sh` that, for
each lane:

1. `yosys -p "read_verilog -sv <sv2v file>; synth_ecp5 -top ibex_top -json flow/out/<lane>/ibex_top.json"` — check the log for any `$mem`
   that did not map to `DP16KD`/`PDPW16KD` block RAM; if the two lanes
   map memories differently, stop and show me, that is a non-design
   divergence.
2. `nextpnr-ecp5 --85k --package CABGA381 --speed 6 --json ... --freq 50
   --timing-allow-fail --report flow/out/<lane>/report.json --seed 1`
   with a minimal LPF that assigns only the clock. Use the same `--freq`
   and `--seed` for both lanes; then also run seeds 2 and 3 and report
   the spread.
3. From `report.json` and the nextpnr log record: LUT4/FF (`TRELLIS_SLICE`
   or `LUT4`/`TRELLIS_FF` counts), `DP16KD`, `MULT18X18D`, and achieved
   fmax for the clock domain, per seed.

Commit the JSON reports and logs. Write `review-package/15-ecp5.md`.

## Phase 6 — Summary and sanitize

1. Rewrite `review-package/00-summary.md` as the new single source of
   truth: functional (assertions on), LOC, diagnostics, sky130 synth +
   post-P&R, ECP5 post-P&R, effort proxies, "not measured", caveats,
   commands. Mark which earlier numbers this supersedes.
2. Sanitize as in `06-sanitize.md`: delete the two 2.5 MB unusable timing
   reports, delete or redact `arch_check_0.71.0.log`, run the username
   `sed` over `reports/`, paraphrase the quoted Arch source line in
   `01-inventory.md`. Re-run the sanitize scan and update the file.
3. Final commit. Print `git log --oneline review-package` and
   `git status`.

## Explicitly out of scope for this task

- Vivado / Xilinx post-P&R (needs a Linux host; separate task if a host
  is available).
- The SpinalHDL port of one module for the three-way comparison
  (separate task).
- Fixing the `PROCASSINIT` emitter pattern inside arch-com (file it; do
  not work around it here).
