# TASK3: pin to arch v0.72.0, RVFI conditional ports, benchmark re-verification

Three independent parts in three repos. Parts A and B run in `arch-ibex`;
Part C runs in the two benchmark artifact repos. Same ground rules as
TASK2: work on a branch, commit per phase with plain messages (no
AI-authorship trailers), scripts under `flow/`, reports under
`review-package/reports/`, cite a file for every number, ask before any
run over ~15 minutes, never loosen a constraint on one lane only.

Compiler for every part: **arch v0.72.0** from the published release
(https://github.com/arch-hdl-lang/arch-com/releases/tag/v0.72.0). Install
the platform binary, record `arch --version` and the SHA-256 of the
asset you installed in each repo's toolchain note. Do not build from
`main`; the point is that a reader can install the same binary.

---

## Part A — arch-ibex: pin and re-gate on v0.72.0

A1. Add a compiler pin to the repo: a `.arch-version` file containing
`0.72.0`, and make `scripts/build.sh` (or the Makefile) check
`arch --version` against it and refuse to build on a mismatch. This is
the reproducibility guard the package's caveat 1 called for.

A2. Remove the scratch-pin recipe from `10-toolchain.md` (the
`git am` patches) and replace it with the release install; move the two
`.patch` files out of `reports/` (they are now upstream).

A3. `make build` with v0.72.0 — expect 23/23 with no port changes, since
v0.72.0 contains #993/#994 and the Phase 1 rewrite is already in `src/`.
If anything fails, stop and show me.

A4. Re-run the full gate with assertions on, exactly as TASK2 Phase 2.4:
`make lint`, `make test`, `test_arch_tests.py`, CoreMark compare. Commit
logs and junit as `reports/gate_v0720_*`. Report pass/fail/skip per
suite. The 12 tooling-drift failures from the last gate (pybind wrapper,
HARC flag, uncommitted plan files) may still be present; list them by
cause and confirm none is a design suite. If arch-com#996 (pybind
wrapper) is fixed in v0.72.0, those six should now pass — report either
way.

A5. Re-run the core-level lint (TASK2 Phase 3) on v0.72.0 output and
update `13-lint.md`; note whether the `PROCASSINIT` pattern (arch-com#995)
is still emitted.

## Part B — arch-ibex: RVFI as conditional ports, then re-run sky130

B1. In the ported `ibex_top` (and any intermediate module that only
forwards them), wrap the 38 RVFI output ports in a `generate if RVFI`
block under a new `param RVFI: const = 0;` (spec §19.2, "Conditional
Ports and Logic"). Simulation builds must set `RVFI = 1` to match the
harness's `-DRVFI=1`; find where the harness sets parameters and add the
override there. Show me the diff before applying. Record it in
`11-port-changes.md` as a Phase B change with the rationale "match
upstream's `ifdef RVFI` boundary for synthesis".

B2. Confirm RVFI=1 builds still pass A4's gate (re-run at least the 10 CPU
programs and the 74 arch tests; commit as `reports/gate_v0720_rvfi1_*`).

B3. Confirm the RVFI=0 generated `ibex_top.sv` has no `rvfi_*` ports
(`grep -c rvfi_ build/ibex_top.sv` → 0) and that sv2v + Yosys accept it.

B4. Re-run the sky130 flow for the Arch lane only (`./flow/sky130_synth.sh
arch` then `./flow/openroad/run.sh arch`; ask first, ~3.5 h last time).
The SV lane's reports stay as they are — nothing changed on that lane —
but state in `14-sky130.md` that the SV numbers are from the 2026-09-04
run and the Arch numbers from this run, with the same flow scripts at
the same commit. Commit the new Arch reports as `arch_openroad_final_*`
(overwrite) and keep the old ones as `arch_openroad_rvfi_final_*` for
traceability. Update the post-P&R table and the "Reading the numbers"
paragraph; report how much of the 1.14× area and 0.70× fmax gap the RVFI
ports accounted for.

B5. Re-run ECP5 for the Arch lane (`./flow/ecp5_pnr.sh`, 3 seeds; fast).
Expect little change since the ports already vanished out-of-context;
report the delta anyway and update `15-ecp5.md`.

B6. Rewrite `00-summary.md` to reflect v0.72.0 and the RVFI change;
supersede the affected rows in the "Superseded" table.

## Part C — benchmark artifact repos: re-verify under v0.72.0 without LLM calls

Repos: `arch-hdl-lang/verilogeval-rerun-results` and
`arch-hdl-lang/cvdp-spec-rtl-eval`. Read each repo's README and the
harness scripts first; do not invoke any LLM, any Codex CLI, or any MCP
tool. This part only recompiles archived candidates and reruns the
existing black-box harness.

C1. For each repo, locate the archived final Arch candidates for every
problem in the paper's in-scope set (156 VerilogEval, 50 CVDP) and the
harness entry point that compiles a candidate with `arch build` and
runs the reference testbench. Write `tools/reverify.sh` (or `.py`) that,
for each problem: runs `arch build` with v0.72.0, runs the harness,
records `{problem, arch_build_ok, sim_result, wall_time}` to
`reverify/v0.72.0/results.csv`, and saves the build log on any failure.

C2. Run it on all 206 problems. Report: number that build, number that
pass, and a list of every problem whose outcome differs from the
archived 0.70.6 result — in either direction. Diff the generated SV
against the archived 0.70.6 SV for each problem and report how many
differ (a byte-identical count is a useful sentence in the paper).

C3. For any regression, stop and show me the build log or simulation
diff before doing anything else. Do not edit any candidate.

C4. Commit `reverify/v0.72.0/` (results, logs, generated SV diffs
summary) and a `TOOLCHAIN.md` line recording the v0.72.0 asset SHA-256.

## Deliverable

Upload set: refreshed `review-package/00-summary.md`, `10-`–`15-`,
`reports/`, and from each benchmark repo `reverify/v0.72.0/results.csv`
plus the regression list (if any).
