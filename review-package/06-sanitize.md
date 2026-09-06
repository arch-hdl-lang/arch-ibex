# 06 — Sanitize: file listing and flags

Every file under `review-package/` as of 2026-09-03, with what it
contains and whether it carries (a) ARCH source code, (b) flow scripts,
or (c) absolute paths containing the owner's username. Flags are
mechanical (`grep`), decisions are the owner's. This file and
`TASK.md` are working files, not part of the upload set.

Upload set per the runbook: `00-summary.md` … `04-synthesis.md` and
`reports/`.

## Markdown deliverables

| File | Lines | (a) ARCH source | (b) flow scripts | (c) username paths | Note |
|---|---|---|---|---|---|
| `00-summary.md` | ~190 | no | no | no | uses `~/…` and `<scratch>` placeholders |
| `01-inventory.md` | 248 | **1 line** (line 169: the single failing expression from `src/IbexIcache.arch:550-552`, quoted for the compiler-drift finding) | no | no | consider paraphrasing that line |
| `02-functional.md` | 206 | no | no | no | quotes one Verilator `%Fatal` line naming generated-SV hierarchy paths |
| `03-source-metrics.md` | 233 | no (names identifiers only, e.g. `div_by_zero_q`) | no (contains the 20-line line-counter script, written for this task) | no | |
| `04-synthesis.md` | 169 | no | no | no | mentions `~/.volare/…` without username |
| `TASK.md` | 90 | no | no | no | the task brief; not for upload |
| `06-sanitize.md` | — | no | no | no | this file; not for upload |

## `reports/`

| File | Size | (a) ARCH source | (b) flow scripts | (c) username paths | Note |
|---|---|---|---|---|---|
| `arch_check_B.log` | 1.9 kB | no (identifiers only) | no | no | 4 compiler warnings |
| `arch_check_0.71.0.log` | 2.9 kB | **yes** — the compiler's diagnostic prints `src/IbexIcache.arch` lines 550-552 verbatim (three lines, four times) | no | no (paths are repo-relative) | redact the source excerpt or drop the file; the finding is described in `01-inventory.md` |
| `functional_sv_lane.log` / `.junit.xml` | 7.8 kB / 10.6 kB | no | no | **yes** (6 / 5 occurrences: repo and temp paths) | pytest output |
| `functional_arch_lane.log` / `.junit.xml` | 168 kB / 36 kB | generated-SV excerpts only (Verilator quotes offending lines of `build/*.sv`) | no | **yes** (224 / 9 occurrences) | full pytest failure output incl. the complete Verilator command line (lists every upstream and generated file path) |
| `functional_arch_lane_noassert.log` / `.junit.xml` | 1.5 kB / 1.2 kB | no | no | **yes** (2 / 0) | |
| `archtests_arch_lane_noassert.log` / `.junit.xml` | 0.5 kB / 33 kB | no | no | **yes** (1 / 1) | |
| `lint_sv_lane_ibex_top.log` | 4.5 kB | no | no | no | 3 warnings, upstream files |
| `lint_sv_lane_ibex_top_nowaiver.log` | 120 kB | no | no | no | upstream files only |
| `lint_arch_lane_ibex_top.log` | 90 kB | generated-SV excerpts (Verilator prints the offending line of `build/*.sv` under each warning) | no | **yes** (152 occurrences, all inside the scratch-directory path that contains the username) | |
| `lint_arch_lane_ibex_top_nowaiver.log` | 214 kB | same | no | **yes** (155) | |
| `loc_upstream.txt`, `loc_arch.txt`, `loc_generated.txt` | ~1.3 kB each | no | no | no | `~/…` and repo-relative paths |
| `sv_sky130_ibex_top_area.rpt` | 5.9 kB | no | no | no | Yosys stat, upstream only |
| `sv_sky130_ibex_top_timing_overall.rpt`, `sv_sky130_ibex_top_timing_reg2reg.rpt` | **2.5 MB each** | no | no | no | upstream only; judged not usable (`04-synthesis.md` §2.2) — candidates to drop for size alone |
| `sv_sky130_ibex_top.sdc` | 0.2 kB | no | **flow constraint file** (4 lines, drive/load only) | no | derived from lowRISC's Apache-2.0 flow |
| `sv_sky130_syn_setup.sh` | 1.2 kB | no | **flow script** (local environment setup for lowRISC's flow) | **yes** (1: the sky130 library path) | |
| `sv_sky130_syn_yosys.sh.local.diff` | 4.7 kB | no | **flow script diff** (local edits to lowRISC's `syn/syn_yosys.sh`, Apache-2.0) | no | |
| `prearch_hybrid_nangate45_synth.stat` | 1.5 kB | no | no | no | pre-port hybrid; provenance only |

## Summary of flags

- **ARCH source code:** one quoted expression in `01-inventory.md`
  (line 169) and the same three source lines inside
  `reports/arch_check_0.71.0.log`. Nothing else contains `.arch`
  text. Several logs contain excerpts of the *generated* SystemVerilog
  (`build/*.sv`), which is derived from the ARCH sources.
- **Flow scripts:** three small files copied from the upstream Ibex
  checkout's `syn/` directory (one SDC, one local setup script, one
  diff against lowRISC's Apache-2.0 script). None is proprietary to
  the ARCH project; the setup script embeds the owner's library path.
- **Username paths:** 10 files, all under `reports/` — every pytest log
  and junit file, the two Arch-lane lint logs (scratch-directory paths),
  and the sky130 setup script. None of the five deliverable `.md`
  files contains the username. A one-line
  `sed -i '' 's|/Users/<user>|~|g; s|/private/tmp/claude-501/[^ ]*scratchpad|<scratch>|g'`
  over `reports/` would remove them; not applied.
- **Size:** the two timing reports are 5 MB together and carry no
  usable number.

No file under `review-package/` contains an email address, token, or
hostname (`grep -lE '@privaterelay|token|secret|password'` → none).

## Repo state

`git status` after the task: untracked `review-package/` and the
runbook copy `claude-code-arch-ibex-instructions.md` at the repo root;
no tracked file modified. `build/` holds the 23 generated `.sv` from
compiler B and `src/` holds the compiler-emitted `.archi` files; both
are gitignored.


## Update 2026-09-05 (TASK2 Phase 6) — actions taken

Applied, not merely flagged, on branch `review-package`:

- **Deleted**: `reports/sv_sky130_ibex_top_timing_overall.rpt` and
  `reports/sv_sky130_ibex_top_timing_reg2reg.rpt` (2.5 MB each, no
  usable number; `04-synthesis.md` §3 notes it).
- **Redacted**: `reports/arch_check_0.71.0.log` — the three quoted
  `src/IbexIcache.arch` source lines (four occurrences) replaced by
  `[ARCH source line redacted]`, diagnostics and line numbers kept.
- **Paraphrased**: the quoted expression in `01-inventory.md` (formerly
  line 169) is now described in words.
- **Username paths**: one `sed` over every file under `review-package/`
  (`/Users/<user>/…worktree` → `${REPO_ROOT}`, `/Users/<user>` → `~`,
  `/private/tmp/…scratchpad` → `<scratch>`, `pytest-of-<user>`,
  `-Users-<user>-…` session ids → `<session>`, any residual `<user>`).
  Re-scan after: `grep -r <username> review-package` → 0 hits.
- **Other scans**: `grep -rlE '@privaterelay|token|secret|password'`
  → only this file (the sentence describing the scan).

Files added by TASK2 (all scanned as above):

| File | (a) ARCH source | (b) flow scripts | (c) username paths | Note |
|---|---|---|---|---|
| `10-toolchain.md`, `11-port-changes.md`, `12-icache-handshake.md`, `13-lint.md`, `14-sky130.md`, `15-ecp5.md` | `11-` and `12-` quote the changed ARCH hunks by description and cite `reports/phase2_port_changes.diff`, which **is a unified diff of `src/IbexIcache.arch` and `src/FbAgeArb.arch`** (owner's call whether to ship it; the numbered files stand without it) | no (they name scripts under `flow/`) | no | |
| `reports/gate_*.log/.junit.xml`, `reports/lint_*`, `reports/arch_check_pinned.log`, `reports/loc_*_phase2/pin.txt` | generated-SV excerpts only (Verilator quotes `build/*.sv` lines) | no | scrubbed | |
| `reports/arch_com_pin_000{1,2}-*.patch` | no (arch-com compiler Rust source, public repo, PRs #993/#994) | no | no | |
| `reports/phase2_test_changes.diff` | no (cocotb Python) | no | no | |
| `reports/{sv,arch}_sky130_synth.ys`, `*_sta.tcl` | no | **yes** — the Yosys / OpenSTA scripts as run (also under `flow/`) | scrubbed | |
| `reports/{sv,arch}_sky130_synth_area.rpt`, `*_sta_*.rpt`, `*_openroad_final_*`, `*_ecp5_*` | no | no (`*_ecp5_synth.ys`, `*_ecp5_ibex_top.lpf` are scripts as run) | scrubbed | nextpnr logs list every top-level port name of `ibex_top` |
| `TASK2.md` | no | no | no | brief; not for upload |

`flow/` itself (17 files) lives in the repo, not in the package; the
package cites it by path. `review-package.zip` at the repo root is the
owner's earlier archive of the first pass and is untracked.

### TASK3 additions (2026-09-05)

`attic/arch_com_pin_000{1,2}-*.patch` (moved out of `reports/`; arch-com compiler
source, both merged upstream), `reports/gate_v0720_*`, `reports/lint_v0720_*`,
`reports/arch_check_v0720.log`, `.arch-version` (repo root): scrubbed with the same
`sed`; no ARCH source; `TASK3.md` is the brief, not for upload.

Phase B additions: `reports/gate_v0720_rvfi1_*`, the `reports/arch_ecp5_rvfi_*`,
`arch_sky130_rvfi_*`, `arch_openroad_rvfi_final_*` copies (previous Arch-lane
reports kept for traceability), re-generated `arch_ecp5_*`, `arch_sky130_*`,
`arch_openroad_final_*`: scrubbed with the same `sed`; no ARCH source.
`src/sim/IbexTopRvfiSim.arch` is design source in the repo, not in the package.

0.72.1 re-run additions: `reports/gate_v0721_*`, `lint_v0721_*`, `arch_check_v0721.log`,
regenerated `arch_sky130_*` / `arch_ecp5_*` (0.72.1) with the 0.72.0 copies kept as
`arch_sky130_v0720_*` / `arch_ecp5_v0720_*`: scrubbed; no ARCH source.
