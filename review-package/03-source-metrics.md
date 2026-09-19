# 03 — Source and diagnostics metrics

Collected 2026-09-03. Arch-lane artefacts are from `arch 0.70.0 @
arch-com 2ffcc60b` (compiler B, see `01-inventory.md` §4); Verilator is
5.048. `cloc` is not installed, so line counts use a 20-line Python
counter (`<scratch>/loc.py`, reproduced at the end of this file) that
classifies each line as blank, comment-only (`//`, or inside `/* */`),
or code. SystemVerilog and ARCH share that comment syntax.

## 1. Lines of code, three ways

Scope: the **ported module set** from `01-inventory.md` §2a — 18
upstream SV files, 23 ARCH source files (18 direct ports + 4 icache
helper constructs + 1 shared package), and the 23 generated SV files.
Excluded on every lane: `ibex_pkg.sv`, `ibex_cs_registers.sv` and its
fork, `prim_*`, the tracer/tracing wrappers, and all SoC scaffolding.

### Totals

| Lane | Files | Total lines | Blank | Comment | Code |
|---|---|---|---|---|---|
| Upstream Ibex SV (hand-written), 18 files | 18 | 13,816 | 1,885 | 2,506 | **9,425** |
| ARCH source, all 23 files | 23 | 10,326 | 881 | 3,102 | **6,343** |
| ARCH source, the 18 direct ports only (helpers + package excluded) | 18 | 9,696 | 806 | 2,995 | **5,895** |
| ARCH-generated SV, all 23 files | 23 | 10,327 | 110 | 3,358 | **6,859** |
| ARCH-generated SV, 18 direct ports only | 18 | 9,551 | 84 | 3,223 | **6,244** |

Sources: `<scratch>/loc.py ~/github/ibex/rtl/{18 files}`;
`loc.py src/*.arch`; `loc.py <scratch>/build-B/*.sv` (a copy of
`build/` after `make build` with compiler B). Per-file output is in
`reports/loc_upstream.txt`, `reports/loc_arch.txt`,
`reports/loc_generated.txt`.

### Per module (total lines / code lines)

| Upstream SV file | Upstream SV | ARCH source | ARCH-generated SV |
|---|---|---|---|
| `ibex_alu.sv` | 1,400 / 812 | 264 / 147 | 293 / 200 |
| `ibex_compressed_decoder.sv` | 847 / 604 | 816 / 468 | 776 / 454 |
| `ibex_controller.sv` | 944 / 558 | 593 / 401 | 625 / 431 |
| `ibex_core.sv` | 2,023 / 1,511 | 1,204 / 853 | 1,117 / 818 |
| `ibex_counter.sv` | 111 / 80 | 100 / 28 | 94 / 30 |
| `ibex_decoder.sv` | 1,212 / 909 | 798 / 540 | 742 / 544 |
| `ibex_ex_block.sv` | 217 / 153 | 227 / 107 | 204 / 107 |
| `ibex_fetch_fifo.sv` | 269 / 148 | 234 / 123 | 237 / 156 |
| `ibex_icache.sv` (main file only) | 1,337 / 889 | 1,224 / 676 | 1,383 / 877 |
| — icache helper constructs (`InvalCtrl`, `FbAgeArb`, `RamPortArb`, `IbexIcacheOutputStage`; inline in upstream) | — | 604 / 435 | 750 / 602 |
| `ibex_id_stage.sv` | 1,156 / 729 | 954 / 627 | 908 / 652 |
| `ibex_if_stage.sv` | 839 / 582 | 426 / 258 | 438 / 282 |
| `ibex_load_store_unit.sv` | 624 / 416 | 546 / 279 | 499 / 269 |
| `ibex_multdiv_fast.sv` | 556 / 389 | 400 / 220 | 536 / 375 |
| `ibex_pmp.sv` | 263 / 168 | 601 / 463 | 477 / 364 |
| `ibex_prefetch_buffer.sv` | 264 / 147 | 287 / 134 | 282 / 159 |
| `ibex_register_file_ff.sv` | 108 / 63 | 103 / 40 | 108 / 51 |
| `ibex_top.sv` | 1,394 / 1,098 | 780 / 475 | 714 / 419 |
| `ibex_wb_stage.sv` | 252 / 169 | 139 / 56 | 118 / 56 |
| `IbexCoreSharedPkg` (no upstream counterpart) | — | 26 / 13 | 26 / 13 |

### Caveats that affect the LOC comparison

- **Configuration breadth is not equal.** The upstream files are
  parametric over every Ibex configuration (RV32B bit-manipulation
  paths in `ibex_alu.sv`, `WritebackStage=1`, branch predictor,
  lockstep, register-file variants, ICache scrambling, etc.) and carry
  `ifdef`-guarded SystemVerilog assertions. The ARCH port hard-codes
  the single configuration in `01-inventory.md` §1 (e.g.
  `src/IbexTop.arch:36-126`) and does not carry the disabled variants
  or the SVA. Part of the upstream-vs-ARCH difference is therefore
  removed functionality, not notation.
- Comment lines in ARCH sources are dominated by `///` doc comments
  citing spec requirements (WORKFLOW.md requires them); they are
  ~30% of ARCH source lines versus ~18% for upstream.
- The generated SV has almost no blank lines (110 total), so its
  "total" is not comparable line-for-line with hand-written SV; the
  code column is the meaningful one.
- `ibex_pmp` is the one module where ARCH source exceeds upstream in
  every column.

## 2. Compile-time diagnostics

### 2a. ARCH compiler (`arch check`, then `make build` = `arch build`)

Run per file: `for f in src/*.arch; do $ARCH_BIN check $f; done`
(`reports/arch_check_B.log`, `reports/arch_check_0.71.0.log`). The
build's own diagnostics (`make build`) were identical to `check`.

| Compiler | Files passing | Diagnostic class | Count | Location |
|---|---|---|---|---|
| B: `arch 0.70.0 @ 2ffcc60b` (2026-05-14) | 23 / 23 | warning: "`<port>` is a `port reg` output assigned inside a state-dependent branch — output value appears 1 cycle after the state transition" | 3 | `src/IbexMultdivFast.arch` (`div_by_zero_q`, `op_numerator_q`, `op_quotient_q`); reported at line 2294 of a 400-line file |
| | | warning: "arch check: 1 comb SCC(s) found; 1 suppressed by pragma; 0 unblessed" | 1 | reported at `src/IbexCoreSharedPkg.arch:409`, a 26-line file |
| | | errors | 0 | |
| Current: `arch 0.71.0 @ f4569890` (2026-09-01) | 22 / 23 | error: "operands at cycle 0 and cycle N" (N = 1..4) | 4 | `src/IbexIcache.arch:551` (pipe-register history taps combined in one expression) |
| | | warning: "1 comb SCC(s) found; 1 suppressed by pragma" | 1 | same as above |
| | | the three `port reg` warnings | 0 | no longer emitted |

Observations, not conclusions: both compilers attach two of the
diagnostics to line numbers that do not exist in the named file
(2294 in a 400-line file, 409 in a 26-line file), so those locations
are not actionable. The suppressed comb-SCC is the ALU↔multdiv adder
sharing loop that upstream also has (see the harness's `UNOPTFLAT`
waiver comment, `tests/test_soc_lint.py:36-43`).

### 2b. Verilator `--lint-only -Wall`

Two granularities were run. All logs are under `reports/`.

**(i) Whole SoC, exactly as the project's own gate runs it**
(`tests/test_soc_lint.py`: `-Wall` plus seven `-Wno-*` waivers and
the upstream `.vlt` waiver files; top = `ibex_mini_soc`). Any
remaining warning fails the test.

| Warning class | Upstream SV lane | Arch lane | Where |
|---|---|---|---|
| `SYNCASYNCNET` | 1 | 1 | `soc/ibex_mini_soc.sv:67` (`IO_RST_N`) — SoC scaffolding; on the Arch lane the underlying mixed-reset use is inside `build/ibex_top.sv:130` (see (ii)) |
| `PROCASSINIT` | 0 | 2 | `build/ibex_multdiv_fast.sv:102,104` — compiler-generated `thread` state variables declared with an initial value and also assigned procedurally |
| Gate verdict | FAIL (1) | FAIL (3) | `reports/functional_sv_lane.log`, `reports/functional_arch_lane.log` |

**(ii) Core only, top = `ibex_top`, both lanes on the same fusesoc
filelist and the same `-G` parameter values as the SoC (ICache=1,
PMPEnable=1, PMPNumRegions=4, DbgTriggerEn=1, DbgHwBreakNum=1, all
security/variant knobs 0).** No `-Wno-*` waivers. The Arch lane
replaces the 18 upstream files with the 23 generated files. Two
variants: with the upstream `.vlt` lint-waiver files that ship in the
Ibex tree (they match paths like `*/rtl/ibex_pmp.sv` and `*_pkg.sv`,
so they mostly do **not** apply to `build/*.sv`), and with those
waiver files removed for parity.

| Warning class | SV lane, with upstream waivers | Arch lane, with upstream waivers | SV lane, no waivers | Arch lane, no waivers |
|---|---|---|---|---|
| `UNUSEDPARAM` | 0 | 74 | 251 | 361 |
| `UNUSEDSIGNAL` | 0 | 61 | 0 | 61 |
| `PINCONNECTEMPTY` | 0 | 0 | 85 | 61 |
| `UNOPTFLAT` | 3 | 0 | 3 | 0 |
| `DECLFILENAME` | 0 | 6 | 0 | 6 |
| `IMPORTSTAR` | 0 | 4 | 0 | 4 |
| `WIDTHEXPAND` | 0 | 3 | 0 | 3 |
| `PROCASSINIT` | 0 | 2 | 0 | 2 |
| `SYNCASYNCNET` | 0 | 0 | 0 | 1 |
| **Total** | **3** | **150** | **339** | **499** |
| Errors | 0 | 0 | 0 | 0 |
| Log | `lint_sv_lane_ibex_top.log` | `lint_arch_lane_ibex_top.log` | `lint_sv_lane_ibex_top_nowaiver.log` | `lint_arch_lane_ibex_top_nowaiver.log` |

Where the Arch-lane warnings sit (with-waivers run; `grep` by file):

| Class | Files (count) |
|---|---|
| `UNUSEDPARAM` (74) | `ibex_core.sv` 17, `ibex_id_stage.sv` 11, `ibex_if_stage.sv` 8, `ibex_icache.sv` 7, `ibex_multdiv_fast.sv` 6, `ibex_top.sv` 5, then 1–3 each in 10 other generated files. These are the configuration parameters the ARCH port declares (to keep the upstream port/parameter surface) but never reads because the configuration is hard-coded. |
| `UNUSEDSIGNAL` (61) | `ibex_icache.sv` 25, `ibex_controller.sv` 10, `ibex_multdiv_fast.sv` 8, `ibex_icache_output_stage.sv` 5, `ibex_decoder.sv` 3, 1–2 each in 6 others. Upstream Ibex is clean here because it uses an explicit `unused_*` sink idiom; the generator does not. |
| `DECLFILENAME` (6) | Generated modules whose SV name is CamelCase (`FbAgeArb`, `InvalCtrl`, `RamPortArb`, `IbexIcacheOutputStage`, package `IbexCoreSharedPkg`) or a compiler helper (`_ibex_multdiv_fast_threads`) inside snake_case files. Cosmetic. |
| `IMPORTSTAR` (4) | `import IbexCoreSharedPkg::*;` at `$unit` scope in `ibex_controller/core/id_stage/if_stage.sv` — generator idiom. |
| `WIDTHEXPAND` (3) | `ibex_register_file_ff.sv:27,29` (1-bit initial values for 32-bit parameters `RV32E`, `DummyInstructions`); `inval_ctrl.sv:169` (2-bit FSM state compared as 32-bit). |
| `PROCASSINIT` (2) | `ibex_multdiv_fast.sv:102,104` (thread state) — the two that also fail the SoC gate. |
| `SYNCASYNCNET` (1, no-waiver run only) | `ibex_top.sv:130` — `rst_ni` used as both a synchronous and an asynchronous reset by generated logic. This is the root of the SoC-level `IO_RST_N` warning on the Arch lane; the SV lane's SoC-level instance of the same warning comes from the SoC wrapper. |

The SV-lane no-waiver numbers are dominated by unused package
parameters (`ibex_tracer_pkg.sv` 205, `prim_secded_pkg.sv` 35) and
empty pin connections in `ibex_lockstep.sv` / `ibex_cs_registers.sv`,
i.e. files that are identical on both lanes; the Arch lane's no-waiver
total includes those same 339 minus 24 `PINCONNECTEMPTY` in files it
replaces. The with-waiver columns are the fairer like-for-like view of
the ported modules themselves: 3 vs 150.

## 3. Development-effort proxies

All from `git log` in this repo (205 commits, 2026-04-28 → 2026-06-29).
No hours are inferred.

| Proxy | Value | Command |
|---|---|---|
| Commits touching any `src/*.arch` | 92 | `git log --oneline -- 'src/*.arch' \| wc -l` |
| First / last commit touching `src/*.arch` | 2026-04-29 / 2026-06-24 | `git log --format=%ad --date=short -- 'src/*.arch'` |
| First / last commit in repo | 2026-04-28 (`446ba0f`, scaffold) / 2026-06-29 (`8c4b3ca`) | `git log --reverse`, `git log -1` |
| Last commit with a recorded green full gate | 2026-05-13 (`dcdbbc8`) | `git log --grep='130 passed'` |
| Commits by area | `src` 93, `tests` 67, `changes` 32, `specs` 21, `scripts` 8, `soc` 3 | `git log --oneline -- <dir> \| wc -l` |
| Most-revised ARCH files (commits) | `IbexIcache.arch` 35, `IbexCore.arch` 13, `IbexTop.arch` 11, `IbexMultdivFast.arch` 10, `IbexLoadStoreUnit.arch` 7, `IbexIdStage.arch` 7, `IbexIcacheOutputStage.arch` 7, `IbexAlu.arch` 7; the other 15 files 1–5 each | per-file `git log --oneline -- src/<f> \| wc -l` |
| Archived swap change-folders (proposal + spec + tasks per module) | 17, dated 2026-04-29 → 2026-05-06 | `ls changes/archive/` |

Learning store (`~/.arch/learn/events.jsonl`, 9,057 lines, 43 not
parseable as JSON):

| Item | Value |
|---|---|
| Events referencing `arch-ibex` (any field) | 144 |
| … of kind `error_fix` (the kind that records a failed `arch check` and its fix) | **0** |
| … of kind `feature` (construct-usage records) | 144 (`module` 68, `use` 27, `fsm` 15, `package` 13, `arbiter` 12, `function` 3, `bus` 2) |
| Date range of those events | 2026-06-24 → 2026-09-03 |
| Date range of the whole store | 2026-06-24 → 2026-09-03 |
| `error_fix` events in the whole store (other projects) | 255 |

The store only begins on 2026-06-24, after the port's active
development window (2026-04-28 → 2026-05-13), so it holds no record of
`arch check` failures during the port. "0 error_fix events" is
therefore *no data*, not *no failures*. The 144 `feature` events were
generated by re-compiling the existing sources (e.g. the HARC work in
June and this task in September), not by writing them.

## Commands run for this step (in order)

```
python3 <scratch>/loc.py ~/github/ibex/rtl/{18 ported files}      # → reports/loc_upstream.txt
python3 <scratch>/loc.py src/*.arch                                 # → reports/loc_arch.txt
python3 <scratch>/loc.py <scratch>/build-B/*.sv                     # → reports/loc_generated.txt
for f in src/*.arch; do <scratch>/arch-com-B/target/release/arch check $f; done   # → reports/arch_check_B.log
for f in src/*.arch; do ~/github/arch-com/target/release/arch check $f; done      # → reports/arch_check_0.71.0.log
# core-level lint, cwd = fusesoc lint-verilator dir (snapshot copied to scratch):
verilator --lint-only -Wall -Wno-fatal --unroll-count 72 --top-module ibex_top \
  -GICache=1 -GPMPEnable=1 -GPMPNumRegions=4 -GDbgTriggerEn=1 -GDbgHwBreakNum=1 -GRV32E=0 \
  -GBranchTargetALU=0 -GWritebackStage=0 -GBranchPredictor=0 -GSecureIbex=0 -GICacheECC=0 -GICacheScramble=0 \
  -f <scratch>/{upstream_core|arch_core_B}[_nowaiver].vc             # → reports/lint_*_ibex_top*.log
git log ... (see §3 table)
python3 (json parse of ~/.arch/learn/events.jsonl)
```

`loc.py` (verbatim):

```python
import sys
def count(path):
    total=blank=comment=0; in_block=False
    for line in open(path, errors="replace"):
        total+=1; s=line.strip()
        if in_block:
            comment+=1
            if "*/" in s: in_block=False
            continue
        if not s: blank+=1; continue
        if s.startswith("//"): comment+=1; continue
        if s.startswith("/*"):
            comment+=1
            if "*/" not in s: in_block=True
            continue
    return total,blank,comment,total-blank-comment
```
