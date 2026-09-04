# 00 — Summary: ARCH port of Ibex vs. hand-written SystemVerilog

Evidence package for Reviewer 1, comment 2. Collected 2026-09-03 from
the private `arch-ibex` repo at commit `8c4b3ca` (2026-06-29). Every
number below is traceable to a file or command named in
`01-inventory.md` … `04-synthesis.md`; those files carry the caveats
in full. Numbers are reported as measured; no judgement about which
lane is "better" is made here.

**Design under comparison.** lowRISC Ibex (`eede2fb`, 2026-04-10)
configured RV32IMC, `RV32MFast`, 2-stage pipeline (no writeback
stage), instruction cache on (2-way, 256 lines), PMP on (4 regions),
FF register file, no branch predictor, no security features. 18 Ibex
RTL modules were ported to ARCH (23 ARCH files including 4 icache
helper constructs and one shared package); `ibex_pkg`, `ibex_csr`, the
`prim_*` cells and the simulation wrappers are reused from upstream;
`ibex_cs_registers` is a hand-written SV fork. Both lanes run inside
the same hand-written test SoC.

**Toolchain.** Arch lane: `arch 0.70.0` at arch-com `2ffcc60b`
(2026-05-14), rebuilt for this package because the compiler on the
machine (0.71.0, 2026-09-01) rejects one source and a June build emits
unlinkable module names (`01-inventory.md` §4). Verilator 5.048,
cocotb 2.0.1, Yosys 0.64/0.67, OpenSTA 3.1.0. No Vivado.

## Functional

| Suite | Upstream SV lane | Arch lane, as-is | Arch lane, generated checker disabled (`--no-assert`) |
|---|---|---|---|
| SoC lint (`-Wall`, project waivers) | FAIL, 1 warning (`SYNCASYNCNET`, SoC wrapper) | FAIL, 3 warnings (same + 2 `PROCASSINIT` in generated multdiv) | — |
| 10 CPU programs (ISRs, PMP faults, icache bench), end-to-end | 10 / 10 pass, 11.0 s | 0 / 10 (all stop at 140 ns on one compiler-generated valid/ready assertion in the icache arbiter) | 10 / 10 pass, 7.3 s |
| RISC-V arch tests rv32i_m I/M/C (74), signatures vs. upstream-generated references | (references are upstream) | not run (would fail on the same assertion) | 74 / 74 bit-identical, 19.7 s |
| Last gate recorded in git (`make test`, 2026-05-13) | — | 130 passed / 0 failed / 75 skipped | — |
| CoreMark, one recorded run (2026-05-11) | 111,651 ticks | 113,150 ticks (1.013×) | — |

The as-is failure is a real interface-contract violation (the icache
retracts a request to its arbiter before grant) that the compiler's
generated protocol checker flags; it was invisible to the project's
own gate because the gate's Verilator at the time did not evaluate
assertions by default. With the checker off, architectural behaviour
matches upstream on every program tried. Details: `02-functional.md`.

## Lines of code (ported module set only)

| Lane | Files | Total | Blank | Comment | Code |
|---|---|---|---|---|---|
| Upstream Ibex SV | 18 | 13,816 | 1,885 | 2,506 | 9,425 |
| ARCH source (all) | 23 | 10,326 | 881 | 3,102 | 6,343 |
| ARCH source (18 direct ports only) | 18 | 9,696 | 806 | 2,995 | 5,895 |
| ARCH-generated SV (all) | 23 | 10,327 | 110 | 3,358 | 6,859 |

Counter: 20-line Python (`cloc` not installed). Per-module table in
`03-source-metrics.md` §1. Main caveat: the upstream files are
parametric over every Ibex configuration and carry SVA; the ARCH port
hard-codes one configuration.

## Compile-time diagnostics

| Check | Upstream SV | Arch lane |
|---|---|---|
| `arch check` (compiler 0.70.0 @ 2ffcc60b) | n/a | 23 / 23 pass; 4 warnings (3 × `port reg` output timing in `IbexMultdivFast`, 1 × suppressed comb SCC) |
| `arch check` (compiler 0.71.0, current) | n/a | 22 / 23 pass; `IbexIcache.arch` 4 errors ("operands at cycle 0 and N") |
| Verilator `-Wall`, core only (`ibex_top`), with upstream `.vlt` waivers | 3 (`UNOPTFLAT`) | 150 (`UNUSEDPARAM` 74, `UNUSEDSIGNAL` 61, `DECLFILENAME` 6, `IMPORTSTAR` 4, `WIDTHEXPAND` 3, `PROCASSINIT` 2) |
| Verilator `-Wall`, core only, no waivers on either lane | 339 | 499 (of which 361 `UNUSEDPARAM`, mostly in shared upstream packages) |
| Verilator errors | 0 | 0 |

Details and per-file placement: `03-source-metrics.md` §2.

## Development-effort proxies (git; no hours inferred)

| Proxy | Value |
|---|---|
| Repo history | 205 commits, 2026-04-28 → 2026-06-29 |
| Commits touching `src/*.arch` | 92, 2026-04-29 → 2026-06-24 |
| Commits by area | src 93, tests 67, changes 32, specs 21, scripts 8, soc 3 |
| Most-revised ARCH file | `IbexIcache.arch`, 35 commits |
| Learning-store `arch check` failure records for this repo | 0 — but the store only starts 2026-06-24, after the port was written |

## Synthesis / implementation

| Metric | Upstream SV | Arch lane | Notes |
|---|---|---|---|
| FPGA (Vivado or `synth_xilinx`): LUT / FF / BRAM / DSP / WNS / TNS / fmax | not measured | not measured | no FPGA flow exists or was ever run |
| sky130 Yosys area, icache module (recorded 2026-05-08) | 30,170 µm² | 34,771 µm² (+15.2 %) | raw reports gone; number from a committed note |
| sky130 Yosys area, whole SoC (recorded 2026-05-08 / 05-11) | 1,715,080 µm² | 1,743,692 µm² (+1.7 %) / 1,812,378 → 1,803,009 µm² (+5.1 %) | two notes disagree on the swap number; do not average |
| sky130 OpenSTA power, 30 % uniform activity (recorded 2026-05-11) | 464.2 mW | 529.8 mW (1.14×) | not simulation-annotated |
| sky130 timing | one upstream-only report, invalid (STA black-boxed latches) | none | no fmax on either lane |

All synthesis numbers are open-PDK logic-synthesis estimates, **not
post-place-and-route**. Details: `04-synthesis.md`.

## Not measured / not available

- Any FPGA synthesis or implementation result, either lane.
- Any post-P&R area, timing or utilisation, any technology, either lane.
- Any valid timing (fmax / WNS / TNS), either lane.
- ARCH-lane synthesis report files (only quoted numbers survive).
- A like-for-like upstream synthesis report in the port's configuration.
- Per-module unit suites (34 files), `arch sim` back-end suites, and
  the arch tests on the as-is (assertions-on) Arch lane.
- CoreMark on the current toolchain (one recorded run only).
- riscv-dv and Spike co-simulation (not present in the repo).
- The exact ARCH compiler commit the sources were originally validated
  with (not recorded anywhere).

## Caveats

1. **Compiler drift.** The repo pins no compiler. The current compiler
   rejects one source; the June-era compiler emits parameter-mangled
   instance names for an external RAM stub that no SV defines. The
   Arch lane therefore uses a compiler rebuilt from 2026-05-14.
2. **Simulator drift.** Verilator 5.048 (installed 2026-05-26) evaluates
   assertions by default and adds `PROCASSINIT`; the project's last
   green gate (2026-05-13) ran on an earlier, unrecorded Verilator. The
   SoC lint now fails on both lanes for a SoC-wrapper warning.
3. **Configuration breadth.** Upstream SV is fully parametric; the ARCH
   port is single-configuration. LOC and unused-parameter counts both
   reflect that.
4. **Reused and forked pieces.** `ibex_pkg`, `ibex_csr`, `prim_*`,
   tracer, and the CSR-file fork are identical on both lanes; the
   generated CLINT/PLIC are outside the Ibex core.
5. **Synthesis provenance.** The only swap-vs-upstream area numbers come
   from committed notes whose scripts and reports lived under `/tmp`
   and are gone; the surviving upstream report is in a different core
   configuration with invalid STA.
6. **Waivers.** The core-level lint comparison "with waivers" applies
   lowRISC's path-matched `.vlt` files, which by construction match the
   upstream files and not the generated ones; the "no waivers" row is
   the symmetric comparison.

## Commands run, in order

Paths: `<scratch>` is a session temp directory outside the repo;
`<lint-verilator>` is the fusesoc output directory created by the
harness. `ARCH_BIN` for Arch-lane steps is
`<scratch>/arch-com-B/target/release/arch`; pytest is
`/opt/homebrew/anaconda3/bin/pytest` (the Python with cocotb).

```
# Step 1
git log / git status / git worktree list; ls src soc tests specs changes scripts
git -C ~/github/ibex log -1; git -C ~/github/ibex status --short; git -C ~/github/ibex tag | wc -l
~/github/arch-com/target/release/arch --version; git -C ~/github/arch-com describe --tags; git -C ~/github/arch-com log -1
ARCH_BIN=~/github/arch-com/target/release/arch make build            # fails on src/IbexIcache.arch
git -C ~/github/arch-com worktree add --detach <scratch>/arch-com-567af654 567af654 && cargo build --release   # 0.70.4, mangles prim_ram_1p
git -C ~/github/arch-com worktree add --detach <scratch>/arch-com-A 15735a77 && cargo build --release           # 0.70.0, links
git -C ~/github/arch-com worktree add --detach <scratch>/arch-com-B 2ffcc60b && cargo build --release           # 0.70.0, links (used)
git clean -fXq -- src/ build/; ARCH_BIN=<scratch>/arch-com-B/target/release/arch make build                     # 23/23 .sv
# Step 2
pytest --collect-only -q tests/
pytest tests/test_soc_lint.py tests/test_cpu_programs.py -p no:cacheprovider -v --junitxml=reports/functional_arch_lane.junit.xml   # Arch lane
git clean -fXq -- build/;  (same pytest)  --junitxml=reports/functional_sv_lane.junit.xml                                            # SV lane
cp <scratch>/build-B/*.sv build/; PATH=<scratch>/noassert-bin:$PATH pytest tests/test_cpu_programs.py ... --junitxml=reports/functional_arch_lane_noassert.junit.xml
PATH=<scratch>/noassert-bin:$PATH pytest tests/test_arch_tests.py -q --junitxml=reports/archtests_arch_lane_noassert.junit.xml
# Step 3
python3 <scratch>/loc.py ~/github/ibex/rtl/{18 files} | src/*.arch | <scratch>/build-B/*.sv   # reports/loc_*.txt
for f in src/*.arch; do $ARCH_BIN check $f; done                      # reports/arch_check_B.log, arch_check_0.71.0.log
verilator --lint-only -Wall -Wno-fatal --unroll-count 72 --top-module ibex_top -G<12 params> -f <scratch>/{upstream_core|arch_core_B}[_nowaiver].vc   # reports/lint_*.log
git log --oneline -- 'src/*.arch' | wc -l; git log --format=%ad --date=short -- src/ ; per-file git log counts; ls changes/archive
python3 (parse ~/.arch/learn/events.jsonl)
# Step 4 (collection only; no synthesis run)
ls ~/github/ibex/syn/syn_out/*; cat .../baseline_upstream/reports/area.rpt, timing/overall.rpt, log/sta.log
cp ... review-package/reports/sv_sky130_*; git -C ~/github/ibex diff syn/syn_yosys.sh > reports/sv_sky130_syn_yosys.sh.local.diff
ls /tmp/ibex-swap-synth /tmp/ibex-power-*                            # all missing
```

Repo state after the task: `git status` shows only the untracked
`review-package/` directory (plus the runbook file copied to the repo
root by the owner). No tracked file was modified.
