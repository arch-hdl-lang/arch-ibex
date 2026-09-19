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
| `10-toolchain.md`, `11-port-changes.md`, `12-icache-handshake.md`, `13-lint.md`, `14-sky130.md`, `15-ecp5.md` | `11-` and `12-` carry **literal diff hunks** of `src/IbexIcache.arch` and `src/FbAgeArb.arch` (14 and 6 changed source lines respectively), not descriptions of them, and cite `reports/phase2_port_changes.diff` (103 changed source lines across the same two files). See the 2026-09-19 note: this flag is retired. | no (they name scripts under `flow/`) | no | |
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
Post-P&R on 0.72.1: regenerated `reports/arch_openroad_final_*`, previous run kept as `arch_openroad_v0720_final_*`; scrubbed.
0.72.2 re-pin: `reports/gate_v0722_*`, `arch_check_v0722.log`: scrubbed; no ARCH source.

Part C: `16-benchmarks.md` (no ARCH source; names benchmark problem IDs and evaluator
files) and `reports/{verilogeval,cvdp}_reverify_v0722_*` (CSV/JSONL verdict tables and
the CVDP notes; scrubbed; no candidate source).


## Update 2026-09-19 — scrub, check hardening, flag retirement

### What the old verification step could not see

The 2026-09-05 re-scan was `grep -r <username> review-package` -> 0 hits,
and it still returns 0 today. It was nevertheless blind to a live leak:
**38 occurrences of `pytest-of-$(id -un | cut -c1-8)`** across 8 files
(`reports/gate_*make_test.{log,junit.xml}`). pytest truncates its own
long `PosixPath` repr with `...`, and the cut landed mid-username, so
what survived was 8 of the 11 characters of the login. A grep for the
*whole* username cannot match a *truncation* of it. The full-length
occurrence on the same line had been scrubbed correctly, which is why
the file looked clean on inspection.

A second category the three original flags did not cover was present in
**26 files, 1149 occurrences**: the macOS per-user temp id — the
`/var/folders/<xx>/<32-char>` directory that `$TMPDIR` points into.
Host-identifying, not a username, so nothing looked for it.

### Actions taken

One `sed` pass over the files that carried either pattern — the file set
determined by `grep -rl`, **not** by a filename glob. A glob of the form
`reports/gate_*_make_test.*` was considered and rejected: it misses
`gate_make_test.*` (no version infix, 12 of the 38 occurrences) and
covers none of the 18 further files carrying only the temp id. The
temp-id expression is written without the `/private` prefix because 20
of the 1149 occurrences lack it.

```bash
TRUNC=$(id -un | cut -c1-8)          # what pytest's truncated repr leaves behind
TMPID=$(dirname "${TMPDIR%/}")       # /var/folders/<xx>/<32-char>

grep -rlE "pytest-of-${TRUNC}|${TMPID}" reports/ \
| while IFS= read -r f; do
    sed -i '' -e "s/pytest-of-${TRUNC}/pytest-of-<user>/g" \
              -e "s#${TMPID}#/var/folders/<tmp>#g" "$f"
  done
```

Both patterns are derived from the environment rather than written out,
so this document does not itself contain the strings it exists to
eliminate — otherwise the checks below would flag the checklist and
train the reader to ignore their output.

**26 files changed, 508 insertions, 508 deletions** — a 1:1 line
substitution, no line added or removed. Verified content-neutral: every
removed line, after normalising the two patterns, is byte-identical to
its replacement, and the pytest verdict totals are unchanged (e.g.
`gate_make_test.log` 12 failed / 162 passed before and after,
`gate_v0721_make_test.log` 7 failed / 167 passed). Scrubbed paths only;
results unchanged.

### Verification step (replaces the 2026-09-05 one)

Run from `review-package/`. **All three must return zero**; the first is
a prefix, so it cannot be defeated by truncation the way the old
whole-username grep was.

```bash
grep -r "$(id -un | cut -c1-5)" .                        # username, prefix-safe
grep -rE '/var/folders/[a-z0-9]{2}/[a-z0-9_]{30,}' .     # macOS per-user temp ids
grep -rE '/(Users|home)/[a-z]' .                         # $HOME-style absolute paths
```

Result 2026-09-19: **0 / 0 / 0.**

### The two live flags

The three original flags are reduced to two:

1. **Username fragments** — any prefix, not just the whole login.
2. **Host-identifying absolute paths** — `$HOME`, per-user temp ids.

**The ARCH-source flag is retired.** It was written when it was still
open whether `src/*.arch` would be published. It is being published, so
a check that flags quoted ARCH source in the package no longer protects
anything, and keeping it would leave the playbook contradicting the
publication decision — as it already did: the TASK2 table claimed `11-`
and `12-` "quote the changed ARCH hunks by description" when both in
fact carry literal hunks (14 and 6 changed source lines). That row is
corrected above rather than acted on. Flow scripts are likewise no
longer flagged: the three originally noted are derived from lowRISC's
Apache-2.0 flow, and the library path that motivated the flag is now
`~/.volare/sky130A`.

### History: not rewritten, with a trigger

The leak is in **22 commits**, and those are exactly the **22 unpushed
commits** on this branch (`git merge-base origin/main HEAD` =
`8c4b3ca`). `origin/main` carries zero occurrences, the `review-package`
branch has never been pushed, and `arch-hdl-lang/arch-ibex` is private.
The dirty history — the truncated login and the temp ids — has therefore
never left this machine.

Scope correction: that statement covers `review-package/` only, which is
what this document is about. Repo-wide the picture differs — the **full**
login is already on `origin/main` in the 7 inherited files listed below,
pushed long before this audit. Cleaning those is a separate decision
about the repository, not about the review package; the pre-push gate
does not flag them, because they are already on the remote and
re-flagging them would make it fire on every push.

Decision: **do not rewrite now.** A rewrite is only needed if the dirty
commits are published, publication cannot happen without a push, and the
push is the natural gate. Running `git filter-repo` inside a live
worktree of a repo carrying 30+ branches — most of them pushed — is a
larger risk today than the thing it would prevent.

The gate is **mechanical, not a note**: `scripts/sanitize_check.sh` runs
the three checks over the commits a push would add, and a `pre-push`
hook refuses the push on any hit. The rewrite therefore happens because
the gate demands it, not because someone remembers this document.
Verified end-to-end: `git push --dry-run origin HEAD:review-package`
exits 1 and the branch is still absent from the remote.

Two things the gate had to get right, both found by testing it rather
than reasoning about it:

- **It scans newly added blobs, not whole trees.** This repo inherits 7
  files from `origin/main` that contain the full login (`WORKFLOW.md`,
  `changes/2026-05-07-*/results.md`, `changes/2026-05-11-*/results.md`
  and four under `changes/archive/2026-05-04-port-ibex_*/`). A
  whole-tree scan re-flags those on every push, so the gate would refuse
  everything forever and be bypassed with `--no-verify` on reflex.
- **Binary blobs are neutralised with `tr -d '\000'`, not detected with
  `grep -q $'\0'`.** The shell expands `$'\0'` to the empty string, so
  that grep matches every blob and the scan skips everything and reports
  clean. The first version of this gate had exactly that bug and passed
  a range known to be dirty. Re-test against a dirty range after any
  edit to the script.

The containment also makes the rewrite cheap and exactly scoped whenever
it is wanted, because the leak range shares no commit with any pushed
branch:

```bash
# what the pre-push gate demands before this branch can be published
git filter-repo --refs 8c4b3ca..review-package \
  --replace-text <(printf 'pytest-of-%s==>pytest-of-<user>\n%s==>/var/folders/<tmp>\n' \
                     "$(id -un | cut -c1-8)" "$(dirname "${TMPDIR%/}")")
```

This keeps every commit, so the effort-proxy counts (205 / 92 / 35) are
preserved exactly. It changes the 22 commit hashes, which is
inconsequential: the paper cites the upstream Ibex commit, not an
arch-ibex one.

### Consequences

- **No hash manifest exists** in `review-package/` (`SHA256SUMS`,
  `*.sha256`, or any file of `^[a-f0-9]{64}  ` lines — none). Nothing to
  regenerate. Should one be added later, it must be generated *after*
  this scrub, and the eight report files whose content changed are the
  ones above.
- **Three stale archives at the repo root carry the pre-scrub content**:
  `review-package 2.zip` (2026-09-05), `review-package 3.zip`
  (2026-09-05) and `review-package 4.zip` (2026-09-06) each contain an
  unscrubbed `gate_make_test.log`. All four root zips are untracked.
  They are superseded packaging snapshots, not part of the upload set;
  delete or regenerate them rather than shipping one by mistake.
  (`review-package.zip`, 2026-09-03, predates those logs and is clean of
  this pattern.)
- **Inventory drift**: 135 of the 159 files in `reports/` are named
  nowhere in this document, covered only by the blanket "scrubbed with
  the same sed" sentences. That is how the truncation survived several
  re-runs. `TASK5.md` is likewise unlisted; like the other briefs it is
  not for upload.
